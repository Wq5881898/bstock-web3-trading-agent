"""Single-symbol autonomous session state, independent of market-data plumbing."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
import os
from pathlib import Path

from .execution_contract import ExecutionInstrument, ProductType, order_intent
from .automation_policy import AutomationPolicy
from .strategy import SignalDecision
from .strategy_registry import ensure_strategy_supports
from .unattended_spot import UnattendedResult, UnattendedSpotExecutor


class SessionPhase(StrEnum):
    RUNNING = "RUNNING"
    BUY_PAUSED = "BUY_PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    RECOVERY_ONLY = "RECOVERY_ONLY"


@dataclass(frozen=True)
class SessionBinding:
    account_ref: str
    api_key_fingerprint: str
    symbol: str
    base_asset: str
    quote_asset: str
    strategy_id: str
    strategy_config_hash: str
    risk_config_hash: str
    account_uid: int | None = None

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip()
               for key, value in asdict(self).items() if key != "account_uid"):
            raise ValueError("Incomplete autonomous session binding")
        if self.account_uid is not None and (type(self.account_uid) is not int
                                             or self.account_uid <= 0):
            raise ValueError("Invalid bound Spot account UID")
        ensure_strategy_supports(self.strategy_id, ProductType.SPOT)


class AutonomousSpotSession:
    VERSION = 1

    def __init__(self, path: Path, binding: SessionBinding,
                 executor: UnattendedSpotExecutor):
        self.path, self.binding, self.executor = Path(path), binding, executor
        if (executor.account_ref != binding.account_ref or executor.symbol != binding.symbol
                or executor.api.account_fingerprint != binding.api_key_fingerprint):
            raise ValueError("Session execution identity mismatch")
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if (payload.get("version") != self.VERSION
                    or payload.get("binding") != asdict(binding)):
                raise ValueError("Autonomous session binding changed")
            self.phase = SessionPhase(payload["phase"])
            self.last_evidence_id = payload["last_evidence_id"]
            self.awaiting_fills = payload["awaiting_fills"]
            executor.policy = AutomationPolicy.restore(payload["policy"],
                executor.policy.config)
            executor._results.policy = executor.policy
            if self.phase in (SessionPhase.RUNNING, SessionPhase.BUY_PAUSED):
                self.phase = SessionPhase.RECOVERY_ONLY
                self._save()
        else:
            self.phase = SessionPhase.STOPPED
            self.last_evidence_id = None
            self.awaiting_fills = False

    def start(self):
        if self.phase != SessionPhase.STOPPED:
            raise RuntimeError("Session is not stopped")
        if not self.executor.journal.execution_lock_held:
            raise RuntimeError("Execution lock required")
        if self.executor.journal.records():
            raise RuntimeError("Existing order journal requires recovery or a new session directory")
        self.phase = SessionPhase.RUNNING
        self._save()

    def observe_risk(self, evidence, *, now_ms: int):
        if self.phase not in (SessionPhase.RUNNING, SessionPhase.BUY_PAUSED):
            raise RuntimeError("Session is not running")
        if evidence.account_ref != self.binding.account_ref or evidence.symbol != self.binding.symbol:
            raise RuntimeError("Account or symbol binding changed")
        transitioned = self.executor.policy.observe_risk(
            evidence.to_snapshot(), now_ms=now_ms)
        if transitioned:
            self.phase = SessionPhase.BUY_PAUSED
            self._save()
        return transitioned

    def process(self, decision: SignalDecision, evidence, rules, *,
                signal_key: str, now_ms: int,
                filled_order_ids: frozenset[int] = frozenset()):
        if self.phase not in (SessionPhase.RUNNING, SessionPhase.BUY_PAUSED):
            return UnattendedResult("BLOCKED", ("session_not_running",))
        if decision.strategy_id != self.binding.strategy_id:
            raise RuntimeError("Strategy binding changed")
        if evidence.account_ref != self.binding.account_ref or evidence.symbol != self.binding.symbol:
            raise RuntimeError("Account or symbol binding changed")
        if self.awaiting_fills:
            if evidence.evidence_id == self.last_evidence_id:
                return UnattendedResult("BLOCKED", ("fills_not_reconciled",))
            if any(row.phase.value != "FILLED" and row.phase.value != "REJECTED"
                   for row in self.executor.journal.records()):
                return UnattendedResult("BLOCKED", ("order_not_terminal",))
            if not self._orders_reflected(filled_order_ids):
                return UnattendedResult("BLOCKED", ("fill_not_in_ledger",))
            # The caller must provide fresh, complete account/fill evidence.
            if not evidence.to_snapshot().reconciled:
                return UnattendedResult("BLOCKED", ("fills_not_reconciled",))
            self.awaiting_fills = False
            self._save()
        if decision.action == "hold":
            return UnattendedResult("HOLD")
        instrument = ExecutionInstrument(self.binding.symbol, ProductType.SPOT,
            "BINANCE_SPOT", self.binding.base_asset, self.binding.quote_asset)
        intent = order_intent(decision, instrument)
        result = self.executor.execute(intent, evidence, rules,
            signal_key=signal_key, now_ms=now_ms)
        if self.executor.policy.buy_pause_reason and self.phase == SessionPhase.RUNNING:
            self.phase = SessionPhase.BUY_PAUSED
        if result.outcome in ("ORDER", "UNKNOWN"):
            self.awaiting_fills = True
            self.last_evidence_id = evidence.evidence_id
        self._save()
        return result

    def request_stop(self):
        if self.phase in (SessionPhase.STOPPED, SessionPhase.STOPPING):
            return
        self.phase = SessionPhase.STOPPING
        self._save()

    def finish_stop(self, *, now_ms: int, evidence=None,
                    filled_order_ids: frozenset[int] = frozenset()):
        if self.phase != SessionPhase.STOPPING:
            raise RuntimeError("Stop was not requested")
        outcomes = self.executor.reconcile_unresolved(now_ms=now_ms)
        if any(row.outcome == "UNKNOWN" or row.order_status in ("NEW", "PARTIALLY_FILLED")
               for row in outcomes):
            return False
        if self.awaiting_fills:
            if (evidence is None or evidence.evidence_id == self.last_evidence_id
                    or evidence.account_ref != self.binding.account_ref
                    or evidence.symbol != self.binding.symbol
                    or not evidence.to_snapshot().reconciled):
                return False
            if not self._orders_reflected(filled_order_ids):
                return False
            self.awaiting_fills = False
        if not self._orders_reflected(filled_order_ids):
            return False
        self.phase = SessionPhase.STOPPED
        self._save()
        return True

    def resume(self, evidence, *, now_ms: int,
               filled_order_ids: frozenset[int] = frozenset()):
        if self.phase not in (SessionPhase.BUY_PAUSED, SessionPhase.RECOVERY_ONLY):
            raise RuntimeError("Session is not paused or recovering")
        if not self.executor.journal.execution_lock_held:
            raise RuntimeError("Execution lock required")
        if evidence.account_ref != self.binding.account_ref or evidence.symbol != self.binding.symbol:
            raise RuntimeError("Session binding changed")
        if self.executor.reconcile_unresolved(now_ms=now_ms):
            return False
        snapshot = evidence.to_snapshot()
        if self.awaiting_fills and (evidence.evidence_id == self.last_evidence_id
                                    or not snapshot.reconciled):
            return False
        if not self._orders_reflected(filled_order_ids):
            return False
        recovering = self.phase == SessionPhase.RECOVERY_ONLY
        if recovering:
            self.executor.policy.observe_risk(snapshot, now_ms=now_ms)
        elif self.executor.policy.buy_pause_reason:
            decision = self.executor.policy.request_manual_resume(snapshot,
                now_ms=now_ms)
            if not decision.allowed:
                self._save()
                return False
        self.awaiting_fills = False
        self.phase = (SessionPhase.BUY_PAUSED
                      if self.executor.policy.buy_pause_reason
                      else SessionPhase.RUNNING)
        self._save()
        return True

    def _orders_reflected(self, filled_order_ids: frozenset[int]) -> bool:
        """A terminal acknowledgement alone is never a durable fill."""
        for row in self.executor.journal.records():
            if row.phase.value not in ("FILLED", "REJECTED"):
                return False
            if row.phase.value == "REJECTED" and row.detail == "REJECTED":
                continue  # Binance guarantees no execution for this status.
            if row.external_id is None or int(row.external_id) not in filled_order_ids:
                return False
        return True

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": self.VERSION, "binding": asdict(self.binding),
            "phase": self.phase.value, "last_evidence_id": self.last_evidence_id,
            "awaiting_fills": self.awaiting_fills,
            "policy": self.executor.policy.checkpoint()}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
