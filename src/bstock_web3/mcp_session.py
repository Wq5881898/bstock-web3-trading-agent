"""Durable strategy-to-MCP-candidate session with no network or submission code."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from .automation_policy import (AccountRiskSnapshot, AutomationPolicy,
                                AutomationPolicyConfig)
from .catalog import BStockAsset
from .execution_contract import (ExecutionInstrument, ProductType,
                                 order_intent)
from .execution_safety import McpReconciliationEvidence
from .mcp_bridge import (McpAccountBinding, McpSpotOrderPlan,
                         build_mcp_spot_plan, write_mcp_plan)
from .strategy import SignalDecision
from .strategy_registry import ensure_strategy_supports


class McpSessionPhase(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    BUY_PAUSED = "BUY_PAUSED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    WAITING_RESULT = "WAITING_RESULT"
    STOPPING = "STOPPING"
    RECOVERY_ONLY = "RECOVERY_ONLY"


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("Session configuration is not canonically serializable")


def _digest(value: Any) -> str:
    encoded = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class McpSessionBinding:
    account_ref: str
    account_fingerprint: str
    symbol: str
    strategy_id: str
    strategy_config_digest: str
    risk_config_digest: str

    def __post_init__(self):
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", self.account_ref):
            raise ValueError("Invalid session account reference")
        if not re.fullmatch(r"[0-9a-f]{64}", self.account_fingerprint):
            raise ValueError("Invalid session account fingerprint")
        if not re.fullmatch(r"[A-Z0-9]{1,32}", self.symbol):
            raise ValueError("Invalid session symbol")
        ensure_strategy_supports(self.strategy_id, ProductType.SPOT)
        for value in (self.strategy_config_digest, self.risk_config_digest):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("Invalid session configuration digest")

    @classmethod
    def create(cls, account: McpAccountBinding, *, symbol: str,
               strategy_id: str, strategy_config: dict,
               risk_config: AutomationPolicyConfig):
        if not isinstance(account, McpAccountBinding) or account.fingerprint is None:
            raise ValueError("An enrolled Agentic account binding is required")
        if not isinstance(risk_config, AutomationPolicyConfig):
            raise ValueError("Invalid session risk configuration")
        return cls(account.account_ref, account.fingerprint, symbol.strip().upper(),
                   strategy_id, _digest(strategy_config),
                   _digest(asdict(risk_config)))


@dataclass(frozen=True)
class McpCandidateResult:
    status: str
    phase: McpSessionPhase
    reasons: tuple[str, ...] = ()
    plan: McpSpotOrderPlan | None = None
    plan_path: Path | None = None


class McpTradingSession:
    """One account/symbol/strategy session that only emits MCP candidate files."""

    VERSION = 2

    def __init__(self, path: Path, binding: McpSessionBinding,
                 policy_config: AutomationPolicyConfig | None = None):
        self.path = Path(path)
        self.binding = binding
        self.policy_config = policy_config or AutomationPolicyConfig()
        if not isinstance(binding, McpSessionBinding):
            raise ValueError("Invalid session binding")
        expected_risk = _digest(asdict(self.policy_config))
        if expected_risk != binding.risk_config_digest:
            raise ValueError("Risk configuration does not match session binding")
        self.policy = AutomationPolicy(self.policy_config)
        self.phase = McpSessionPhase.STOPPED
        self.created_at_ms: int | None = None
        self.updated_at_ms: int | None = None
        self.pending: dict | None = None
        self.processed_signal_keys: list[str] = []
        self.recovery_reason: str | None = None
        if self.path.exists():
            self._load()

    def start(self, evidence: McpReconciliationEvidence, *, now_ms: int):
        if self.phase != McpSessionPhase.STOPPED:
            raise RuntimeError("Session is not stopped")
        self._validate_evidence(evidence, now_ms)
        self.phase = McpSessionPhase.STARTING
        self.created_at_ms = self.created_at_ms or now_ms
        self.updated_at_ms = now_ms
        self._persist()
        try:
            self.policy.observe(evidence.to_snapshot(), now_ms=now_ms)
            self.phase = (McpSessionPhase.BUY_PAUSED
                          if self.policy.buy_pause_reason
                          else McpSessionPhase.RUNNING)
            self.updated_at_ms = now_ms
            self._persist()
        except Exception:
            self.phase = McpSessionPhase.RECOVERY_ONLY
            self.recovery_reason = "start_interrupted"
            self.updated_at_ms = now_ms
            self._persist()
            raise
        return self.phase

    def prepare_candidate(self, asset: BStockAsset, signal: SignalDecision,
                          evidence: McpReconciliationEvidence,
                          account: McpAccountBinding, *, output_dir: Path,
                          now_ms: int) -> McpCandidateResult:
        if self.phase not in {McpSessionPhase.RUNNING,
                              McpSessionPhase.BUY_PAUSED}:
            return McpCandidateResult("BLOCKED", self.phase,
                                      ("session_not_accepting_signals",))
        self._validate_evidence(evidence, now_ms)
        self._validate_account(account)
        if not isinstance(signal, SignalDecision):
            raise ValueError("Invalid strategy signal")
        if signal.strategy_id != self.binding.strategy_id:
            raise ValueError("Strategy changed during session")
        signal_key = self._signal_key(signal)
        if signal_key in self.processed_signal_keys:
            return McpCandidateResult("DUPLICATE", self.phase,
                                      ("signal_already_processed",))

        snapshot = evidence.to_snapshot()
        self.policy.observe(snapshot, now_ms=now_ms)
        if self.policy.buy_pause_reason:
            self.phase = McpSessionPhase.BUY_PAUSED
        if signal.action == "hold":
            self._record_processed(signal_key)
            self.updated_at_ms = now_ms
            self._persist()
            return McpCandidateResult("HOLD", self.phase)

        intent = order_intent(signal, ExecutionInstrument(
            self.binding.symbol, ProductType.SPOT, "BINANCE",
            asset.symbol, "USDT"))
        decision = self.policy.evaluate(intent, snapshot, now_ms=now_ms)
        if not decision.allowed:
            self.updated_at_ms = now_ms
            self._persist()
            return McpCandidateResult("BLOCKED", self.phase, decision.reasons)

        self.pending = {"status": "RESERVING", "signal_key": signal_key,
                        "plan_id": None, "plan_path": None,
                        "side": signal.action.upper(), "created_at_ms": now_ms,
                        "execution_fingerprint": None, "ticket_path": None}
        self.phase = McpSessionPhase.WAITING_CONFIRMATION
        self.updated_at_ms = now_ms
        self._persist()
        try:
            plan = build_mcp_spot_plan(
                asset, signal,
                amount_usdt=self.policy_config.order_budget_quote,
                position_quantity=snapshot.position_quantity,
                account_binding=account,
                now=datetime.fromtimestamp(now_ms / 1000, timezone.utc),
            )
            name = hashlib.sha256(signal_key.encode("utf-8")).hexdigest()[:20]
            plan_path = Path(output_dir) / f"candidate-{name}.json"
            if plan_path.exists():
                raise RuntimeError("Candidate path already exists")
            write_mcp_plan(plan, plan_path)
            self.pending.update(status="READY", plan_id=plan.plan_id,
                                plan_path=str(plan_path.resolve()))
            self._record_processed(signal_key)
            self.updated_at_ms = now_ms
            self._persist()
            return McpCandidateResult("READY", self.phase, plan=plan,
                                      plan_path=plan_path.resolve())
        except Exception:
            self.phase = McpSessionPhase.RECOVERY_ONLY
            self.recovery_reason = "candidate_reservation_interrupted"
            self.updated_at_ms = now_ms
            self._persist()
            raise

    def dismiss_candidate(self, *, outcome: str, now_ms: int):
        if outcome not in {"REJECTED", "EXPIRED", "CANCELLED"}:
            raise ValueError("Invalid candidate dismissal outcome")
        if not self.pending or self.pending.get("status") != "READY":
            raise RuntimeError("No ready candidate")
        self.pending = None
        self.updated_at_ms = now_ms
        if self.phase == McpSessionPhase.STOPPING:
            self.phase = McpSessionPhase.STOPPED
        else:
            self.phase = (McpSessionPhase.BUY_PAUSED
                          if self.policy.buy_pause_reason
                          else McpSessionPhase.RUNNING)
        self._persist()
        return self.phase

    def begin_confirmation(self, *, plan_id: str, now_ms: int):
        """Persist the point after confirmation is consumed and before ticket I/O."""
        if (self.phase != McpSessionPhase.WAITING_CONFIRMATION
                or not self.pending or self.pending.get("status") != "READY"
                or self.pending.get("plan_id") != plan_id):
            raise RuntimeError("Candidate is not ready for confirmation")
        self.pending["status"] = "CONFIRMING"
        self.phase = McpSessionPhase.WAITING_RESULT
        self.updated_at_ms = now_ms
        self._persist()

    def record_submission_ticket(self, *, plan_id: str,
                                 execution_fingerprint: str,
                                 ticket_path: Path, now_ms: int):
        if (self.phase != McpSessionPhase.WAITING_RESULT
                or not self.pending
                or self.pending.get("status") != "CONFIRMING"
                or self.pending.get("plan_id") != plan_id
                or not re.fullmatch(r"[0-9a-f]{64}", execution_fingerprint)):
            raise RuntimeError("Session is not awaiting a submission ticket")
        self.pending.update(status="TICKET_READY",
                            execution_fingerprint=execution_fingerprint,
                            ticket_path=str(Path(ticket_path).resolve()))
        self.updated_at_ms = now_ms
        self._persist()

    def record_execution_outcome(self, *, outcome: str,
                                 evidence: McpReconciliationEvidence | None,
                                 now_ms: int):
        if (not self.pending
                or self.pending.get("status") not in {"CONFIRMING",
                                                       "TICKET_READY"}
                or self.phase not in {McpSessionPhase.WAITING_RESULT,
                                      McpSessionPhase.STOPPING}):
            raise RuntimeError("Session is not awaiting an execution result")
        if outcome == "UNKNOWN":
            self.pending["status"] = "UNKNOWN"
            self.phase = McpSessionPhase.RECOVERY_ONLY
            self.recovery_reason = "execution_outcome_unknown"
        elif outcome in {"FILLED", "REJECTED"}:
            if evidence is not None:
                self._validate_evidence(evidence, now_ms)
                self.policy.observe(evidence.to_snapshot(), now_ms=now_ms)
            stopping = self.phase == McpSessionPhase.STOPPING
            self.pending = None
            self.recovery_reason = None
            self.phase = (McpSessionPhase.STOPPED if stopping else
                          McpSessionPhase.BUY_PAUSED
                          if self.policy.buy_pause_reason else
                          McpSessionPhase.RUNNING)
        else:
            raise ValueError("Invalid execution outcome")
        self.updated_at_ms = now_ms
        self._persist()
        return self.phase

    def enter_recovery(self, *, reason: str, now_ms: int):
        if not isinstance(reason, str) or not reason or len(reason) > 128:
            raise ValueError("Invalid recovery reason")
        self.phase = McpSessionPhase.RECOVERY_ONLY
        self.recovery_reason = reason
        self.updated_at_ms = now_ms
        self._persist()

    def request_manual_resume(self, evidence: McpReconciliationEvidence,
                              *, now_ms: int):
        if self.phase != McpSessionPhase.BUY_PAUSED or self.pending:
            raise RuntimeError("Session is not eligible for BUY resume")
        self._validate_evidence(evidence, now_ms)
        decision = self.policy.request_manual_resume(
            evidence.to_snapshot(), now_ms=now_ms)
        if decision.allowed:
            self.phase = McpSessionPhase.RUNNING
        self.updated_at_ms = now_ms
        self._persist()
        return decision

    def stop(self, *, now_ms: int):
        if self.phase == McpSessionPhase.STOPPED:
            return self.phase
        if self.phase == McpSessionPhase.RECOVERY_ONLY:
            raise RuntimeError("Recovery must be resolved before stopping")
        self.updated_at_ms = now_ms
        self.phase = (McpSessionPhase.STOPPING if self.pending
                      else McpSessionPhase.STOPPED)
        self._persist()
        return self.phase

    def _validate_evidence(self, evidence, now_ms):
        if not isinstance(evidence, McpReconciliationEvidence):
            raise ValueError("Invalid MCP reconciliation evidence")
        snapshot = evidence.to_snapshot()
        if snapshot.account_ref != self.binding.account_ref:
            raise ValueError("Session account changed")
        if snapshot.symbol != self.binding.symbol or snapshot.product != ProductType.SPOT:
            raise ValueError("Session instrument changed")
        if now_ms < snapshot.observed_at_ms:
            raise ValueError("Session clock precedes account evidence")

    def _validate_account(self, account):
        if (not isinstance(account, McpAccountBinding)
                or account.account_ref != self.binding.account_ref
                or account.fingerprint != self.binding.account_fingerprint):
            raise ValueError("Agentic account binding changed")

    def _signal_key(self, signal):
        if (not isinstance(signal.signal_bar_time, str)
                or not signal.signal_bar_time.strip()
                or len(signal.signal_bar_time) > 128):
            raise ValueError("Strategy signal requires a stable event time")
        return f"{signal.strategy_id}:{signal.signal_bar_time.strip()}"

    def _record_processed(self, signal_key):
        if signal_key not in self.processed_signal_keys:
            self.processed_signal_keys.append(signal_key)
        if len(self.processed_signal_keys) > 10000:
            raise RuntimeError("Session signal history limit reached")

    def _payload(self):
        return {"version": self.VERSION, "binding": asdict(self.binding),
                "phase": self.phase.value, "created_at_ms": self.created_at_ms,
                "updated_at_ms": self.updated_at_ms,
                "policy": self.policy.checkpoint(), "pending": self.pending,
                "processed_signal_keys": self.processed_signal_keys,
                "recovery_reason": self.recovery_reason}

    def _persist(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(self._payload(), handle, ensure_ascii=True,
                      allow_nan=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    def _load(self):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            expected = {"version", "binding", "phase", "created_at_ms",
                        "updated_at_ms", "policy", "pending",
                        "processed_signal_keys", "recovery_reason"}
            if not isinstance(payload, dict) or set(payload) != expected \
                    or payload["version"] != self.VERSION \
                    or McpSessionBinding(**payload["binding"]) != self.binding:
                raise ValueError
            phase = McpSessionPhase(payload["phase"])
            processed = payload["processed_signal_keys"]
            if (not isinstance(processed, list) or len(processed) > 10000
                    or len(set(processed)) != len(processed)
                    or any(not isinstance(item, str) or not item for item in processed)):
                raise ValueError
            self.policy = AutomationPolicy.restore(payload["policy"],
                                                   self.policy_config)
            self.phase = phase
            self.created_at_ms = payload["created_at_ms"]
            self.updated_at_ms = payload["updated_at_ms"]
            self.pending = payload["pending"]
            self.processed_signal_keys = processed
            self.recovery_reason = payload["recovery_reason"]
            self._validate_loaded_state()
            if self.phase == McpSessionPhase.STARTING or (
                    self.pending and self.pending.get("status") in {
                        "RESERVING", "CONFIRMING"}):
                self.phase = McpSessionPhase.RECOVERY_ONLY
                self.recovery_reason = "interrupted_persistent_transition"
                self._persist()
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError,
                KeyError, ValueError):
            raise ValueError("Invalid MCP trading session") from None

    def _validate_loaded_state(self):
        if (type(self.created_at_ms) is not int or self.created_at_ms < 0
                or type(self.updated_at_ms) is not int
                or self.updated_at_ms < self.created_at_ms):
            raise ValueError("Invalid session timestamps")
        if self.recovery_reason is not None and (
                not isinstance(self.recovery_reason, str)
                or not self.recovery_reason
                or len(self.recovery_reason) > 128):
            raise ValueError("Invalid session recovery reason")
        if self.pending is not None:
            expected = {"status", "signal_key", "plan_id", "plan_path",
                        "side", "created_at_ms", "execution_fingerprint",
                        "ticket_path"}
            if (not isinstance(self.pending, dict)
                    or set(self.pending) != expected
                    or self.pending["status"] not in {
                        "RESERVING", "READY", "CONFIRMING", "TICKET_READY",
                        "UNKNOWN"}
                    or not isinstance(self.pending["signal_key"], str)
                    or not self.pending["signal_key"]
                    or len(self.pending["signal_key"]) > 256
                    or self.pending["side"] not in {"BUY", "SELL"}
                    or type(self.pending["created_at_ms"]) is not int
                    or self.pending["created_at_ms"] < self.created_at_ms
                    or self.pending["created_at_ms"] > self.updated_at_ms):
                raise ValueError("Invalid pending candidate")
            reserved = self.pending["status"] == "RESERVING"
            if reserved == all(isinstance(self.pending[key], str)
                               and bool(self.pending[key])
                               for key in ("plan_id", "plan_path")):
                raise ValueError("Invalid pending candidate readiness")
            if reserved and (self.pending["plan_id"] is not None
                             or self.pending["plan_path"] is not None):
                raise ValueError("Invalid candidate reservation")
            has_ticket = self.pending["status"] in {"TICKET_READY", "UNKNOWN"}
            if has_ticket != (
                    isinstance(self.pending["execution_fingerprint"], str)
                    and bool(self.pending["execution_fingerprint"])
                    and isinstance(self.pending["ticket_path"], str)
                    and bool(self.pending["ticket_path"])):
                raise ValueError("Invalid pending submission ticket")
            if has_ticket and not re.fullmatch(
                    r"[0-9a-f]{64}", self.pending["execution_fingerprint"]):
                raise ValueError("Invalid execution fingerprint")
        pending_phases = {McpSessionPhase.WAITING_CONFIRMATION,
                          McpSessionPhase.WAITING_RESULT,
                          McpSessionPhase.STOPPING}
        if ((self.phase in pending_phases and self.pending is None)
                or (self.pending is not None
                    and self.phase not in pending_phases
                    | {McpSessionPhase.RECOVERY_ONLY})):
            raise ValueError("Session phase/pending mismatch")
        if self.phase == McpSessionPhase.BUY_PAUSED \
                and self.policy.buy_pause_reason is None:
            raise ValueError("BUY_PAUSED session has no risk latch")
        if self.phase == McpSessionPhase.RUNNING \
                and self.policy.buy_pause_reason is not None:
            raise ValueError("RUNNING session has an active risk latch")
