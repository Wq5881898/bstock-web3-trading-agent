"""Offline safety contract between an automation policy and an MCP host.

This module does not contain an MCP client or an order submission method.  It
turns reconciled host evidence into an account snapshot and persists the
idempotency state that a future production host must honor.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re

from .automation_policy import (AccountRiskSnapshot, AutomationAction,
                                AutomationDecision, AutomationPolicy)
from .execution_contract import OrderIntent, PositionAction, ProductType
from .execution_lock import ExecutionLock


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


class ExecutionMode(StrEnum):
    OBSERVE_ONLY = "OBSERVE_ONLY"
    UNATTENDED = "UNATTENDED"


class ExecutionPhase(StrEnum):
    PREPARED = "PREPARED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class McpReconciliationEvidence:
    """Sanitized results of the required read-only MCP queries.

    The future MCP host, rather than this package, performs the actual tool
    calls.  All four evidence flags must be true before ``reconciled`` can be
    true in the resulting policy snapshot.
    """

    evidence_id: str
    account_ref: str
    symbol: str
    product: ProductType
    risk_day: str
    observed_at_ms: int
    account_checked: bool
    balances_checked: bool
    open_orders_checked: bool
    fills_checked: bool
    can_trade: bool
    available_quote: Decimal
    position_quantity: Decimal
    position_cost: Decimal
    daily_equity_loss: Decimal
    daily_entries: int = 0
    consecutive_losses: int = 0
    last_entry_ms: int | None = None
    pending_order_id: str | None = None

    def to_snapshot(self) -> AccountRiskSnapshot:
        flags = (self.account_checked, self.balances_checked,
                 self.open_orders_checked, self.fills_checked)
        if any(type(flag) is not bool for flag in flags):
            raise ValueError("Invalid MCP reconciliation flags")
        if not isinstance(self.evidence_id, str) or not re.fullmatch(
                r"[A-Za-z0-9._:-]{8,128}", self.evidence_id):
            raise ValueError("Invalid MCP evidence id")
        return AccountRiskSnapshot(
            account_ref=self.account_ref,
            symbol=self.symbol,
            product=self.product,
            risk_day=self.risk_day,
            observed_at_ms=self.observed_at_ms,
            reconciled=all(flags),
            can_trade=self.can_trade,
            available_quote=self.available_quote,
            position_quantity=self.position_quantity,
            position_cost=self.position_cost,
            daily_equity_loss=self.daily_equity_loss,
            daily_entries=self.daily_entries,
            consecutive_losses=self.consecutive_losses,
            last_entry_ms=self.last_entry_ms,
            pending_order_id=self.pending_order_id,
        )


@dataclass(frozen=True)
class ExecutionArming:
    mode: ExecutionMode = ExecutionMode.OBSERVE_ONLY
    account_ref: str = ""
    symbol: str = ""
    product: ProductType = ProductType.SPOT
    armed_until_ms: int | None = None

    def block_reasons(self, snapshot: AccountRiskSnapshot, *, now_ms: int):
        reasons = []
        if self.mode != ExecutionMode.UNATTENDED:
            reasons.append("observe_only")
        if not self.account_ref or self.account_ref != snapshot.account_ref:
            reasons.append("armed_account_mismatch")
        if not self.symbol or self.symbol != snapshot.symbol:
            reasons.append("armed_symbol_mismatch")
        if self.product != snapshot.product:
            reasons.append("armed_product_mismatch")
        if (self.armed_until_ms is None or type(self.armed_until_ms) is not int
                or now_ms > self.armed_until_ms):
            reasons.append("arming_expired")
        return tuple(reasons)


def intent_fingerprint(intent: OrderIntent, risk_day: str, signal_key: str,
                       amount_kind: str, amount: Decimal) -> str:
    if not isinstance(intent, OrderIntent):
        raise ValueError("Invalid order intent")
    if not isinstance(intent.action, PositionAction):
        raise ValueError("Invalid order action")
    if (not isinstance(intent.reference_price, Decimal)
            or not intent.reference_price.is_finite()
            or intent.reference_price <= 0):
        raise ValueError("Invalid order reference price")
    if not isinstance(risk_day, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", risk_day):
        raise ValueError("Invalid risk day")
    if not isinstance(signal_key, str) or not re.fullmatch(
            r"[A-Za-z0-9._:-]{1,128}", signal_key):
        raise ValueError("Invalid strategy signal key")
    if amount_kind not in {"QUOTE", "BASE"}:
        raise ValueError("Invalid execution amount kind")
    if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0:
        raise ValueError("Invalid execution amount")
    canonical = {
        "risk_day": risk_day,
        "signal_key": signal_key,
        "strategy_id": intent.strategy_id,
        "symbol": intent.instrument.symbol,
        "product": intent.instrument.product.value,
        "venue": intent.instrument.venue,
        "action": intent.action.value,
        "reference_price": _decimal_text(intent.reference_price),
        "reason": intent.reason,
        "strategy_params": intent.strategy_params,
        "reduce_only": intent.reduce_only,
        "amount_kind": amount_kind,
        "amount": _decimal_text(amount),
    }
    try:
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Order intent is not canonically serializable") from exc
    return hashlib.sha256(encoded).hexdigest()


def client_order_id(fingerprint: str) -> str:
    if not isinstance(fingerprint, str) or not re.fullmatch(
            r"[0-9a-f]{64}", fingerprint):
        raise ValueError("Invalid intent fingerprint")
    return "bstock-" + fingerprint[:28]


@dataclass(frozen=True)
class ExecutionRecord:
    fingerprint: str
    client_order_id: str
    account_ref: str
    symbol: str
    product: str
    action: str
    risk_day: str
    signal_key: str
    amount_kind: str
    amount: str
    phase: ExecutionPhase
    created_at_ms: int
    updated_at_ms: int
    external_id: str | None = None
    detail: str | None = None


class ExecutionJournal:
    """Atomic local journal; an uncertain submission is never auto-retried."""

    VERSION = 1
    _TRANSITIONS = {
        ExecutionPhase.PREPARED: {ExecutionPhase.SUBMITTING},
        ExecutionPhase.SUBMITTING: {
            ExecutionPhase.SUBMITTED, ExecutionPhase.FILLED,
            ExecutionPhase.REJECTED, ExecutionPhase.UNKNOWN},
        ExecutionPhase.SUBMITTED: {
            ExecutionPhase.FILLED, ExecutionPhase.REJECTED,
            ExecutionPhase.UNKNOWN},
        ExecutionPhase.UNKNOWN: {
            ExecutionPhase.SUBMITTED, ExecutionPhase.FILLED,
            ExecutionPhase.REJECTED},
        ExecutionPhase.FILLED: set(),
        ExecutionPhase.REJECTED: set(),
    }

    def __init__(self, path: Path | None = None,
                 execution_lock: ExecutionLock | None = None):
        self.path = path
        self.execution_lock = execution_lock
        self._records: dict[str, ExecutionRecord] = {}
        if self.path is not None and self.path.exists():
            self._load_existing()

    @property
    def execution_lock_held(self):
        if self.path is None or self.execution_lock is None:
            return False
        expected = self.path.with_suffix(self.path.suffix + ".lock")
        return (self.execution_lock.held
                and self.execution_lock.path.resolve() == expected.resolve())

    def prepare(self, intent: OrderIntent, snapshot: AccountRiskSnapshot,
                *, signal_key: str, amount_kind: str, amount: Decimal,
                now_ms: int):
        self._validate_now(now_ms)
        fingerprint = intent_fingerprint(intent, snapshot.risk_day, signal_key,
                                         amount_kind, amount)
        existing = self._records.get(fingerprint)
        if existing is not None:
            return existing, False
        record = ExecutionRecord(
            fingerprint=fingerprint,
            client_order_id=client_order_id(fingerprint),
            account_ref=snapshot.account_ref,
            symbol=intent.instrument.symbol,
            product=intent.instrument.product.value,
            action=intent.action.value,
            risk_day=snapshot.risk_day,
            signal_key=signal_key,
            amount_kind=amount_kind,
            amount=_decimal_text(amount),
            phase=ExecutionPhase.PREPARED,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )
        self._records[fingerprint] = record
        self._save()
        return record, True

    def transition(self, fingerprint: str, phase: ExecutionPhase, *, now_ms: int,
                   external_id: str | None = None,
                   detail: str | None = None):
        self._validate_now(now_ms)
        if not isinstance(phase, ExecutionPhase):
            raise ValueError("Invalid execution phase")
        current = self.get(fingerprint)
        if phase not in self._TRANSITIONS[current.phase]:
            raise RuntimeError(
                f"Invalid execution transition {current.phase}->{phase}")
        if current.external_id and external_id not in (None, current.external_id):
            raise RuntimeError("External order id changed during reconciliation")
        if external_id is not None and (not isinstance(external_id, str)
                or not external_id.strip()):
            raise ValueError("Invalid external order id")
        resolved_external_id = external_id or current.external_id
        if phase in {ExecutionPhase.SUBMITTED, ExecutionPhase.FILLED} \
                and not resolved_external_id:
            raise ValueError("Submitted/filled execution requires external order id")
        if detail is not None and (not isinstance(detail, str)
                or len(detail) > 256):
            raise ValueError("Invalid execution detail")
        payload = asdict(current)
        payload.update(phase=phase, updated_at_ms=now_ms,
                       external_id=resolved_external_id,
                       detail=detail)
        record = ExecutionRecord(**payload)
        self._records[fingerprint] = record
        self._save()
        return record

    def get(self, fingerprint: str):
        try:
            return self._records[fingerprint]
        except (KeyError, TypeError):
            raise KeyError("Unknown execution fingerprint") from None

    def records(self):
        return tuple(sorted(self._records.values(),
                            key=lambda item: item.created_at_ms))

    def _save(self):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {"version": self.VERSION, "records": [
            {**asdict(record), "phase": record.phase.value}
            for record in self.records()]}
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        temporary.replace(self.path)

    @classmethod
    def load(cls, path: Path, execution_lock: ExecutionLock | None = None):
        return cls(path, execution_lock)

    def _load_existing(self):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(payload, dict)
                    or payload.get("version") != self.VERSION):
                raise ValueError
            rows = payload.get("records")
            if not isinstance(rows, list):
                raise ValueError
            for row in rows:
                record = self._parse_record(row)
                if record.fingerprint in self._records:
                    raise ValueError
                self._records[record.fingerprint] = record
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            raise ValueError("Invalid execution journal") from None

    @staticmethod
    def _parse_record(row):
        if not isinstance(row, dict) or set(row) != {
                "fingerprint", "client_order_id", "account_ref", "symbol",
                "product", "action", "risk_day", "phase", "created_at_ms",
                "updated_at_ms", "external_id", "detail", "signal_key",
                "amount_kind", "amount"}:
            raise ValueError
        record = ExecutionRecord(**{**row, "phase": ExecutionPhase(row["phase"])})
        if (not re.fullmatch(r"[0-9a-f]{64}", record.fingerprint)
                or record.client_order_id != client_order_id(record.fingerprint)
                or not isinstance(record.account_ref, str)
                or not record.account_ref.strip()
                or not re.fullmatch(r"[A-Z0-9]{1,32}", record.symbol)
                or record.product not in {item.value for item in ProductType}
                or record.action not in {item.value for item in PositionAction}
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", record.risk_day)
                or type(record.created_at_ms) is not int
                or type(record.updated_at_ms) is not int
                or record.created_at_ms < 0
                or record.updated_at_ms < record.created_at_ms
                or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}",
                                    record.signal_key)
                or record.amount_kind not in {"QUOTE", "BASE"}):
            raise ValueError
        try:
            amount = Decimal(record.amount)
        except Exception:
            raise ValueError from None
        if not amount.is_finite() or amount <= 0:
            raise ValueError
        if (record.phase in {ExecutionPhase.SUBMITTED, ExecutionPhase.FILLED}
                and not record.external_id):
            raise ValueError
        return record

    @staticmethod
    def _validate_now(now_ms):
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("Invalid execution timestamp")


@dataclass(frozen=True)
class SafePreparation:
    decision: AutomationDecision
    record: ExecutionRecord | None = None
    duplicate: bool = False


def prepare_safe_execution(
    intent: OrderIntent,
    evidence: McpReconciliationEvidence,
    policy: AutomationPolicy,
    arming: ExecutionArming,
    journal: ExecutionJournal,
    *,
    signal_key: str,
    now_ms: int,
) -> SafePreparation:
    """Authorize and journal an intent without sending it anywhere."""
    if not isinstance(policy, AutomationPolicy):
        raise ValueError("Invalid automation policy")
    if not isinstance(evidence, McpReconciliationEvidence):
        raise ValueError("Invalid MCP reconciliation evidence")
    if not isinstance(arming, ExecutionArming):
        raise ValueError("Invalid execution arming")
    if not isinstance(journal, ExecutionJournal):
        raise ValueError("Invalid execution journal")
    snapshot = evidence.to_snapshot()
    decision = policy.evaluate(intent, snapshot, now_ms=now_ms)
    reasons = [*decision.reasons, *arming.block_reasons(snapshot, now_ms=now_ms)]
    if journal.path is None:
        reasons.append("non_persistent_execution_journal")
    if not journal.execution_lock_held:
        reasons.append("execution_lock_not_held")
    if reasons:
        blocked = AutomationDecision(AutomationAction.BLOCK,
            tuple(dict.fromkeys(reasons)), decision.buy_pause_reason,
            decision.notify_operator)
        return SafePreparation(blocked)
    if intent.action.value == "OPEN_LONG":
        amount_kind, amount = "QUOTE", policy.config.order_budget_quote
    else:
        amount_kind, amount = "BASE", snapshot.position_quantity
    record, created = journal.prepare(intent, snapshot, signal_key=signal_key,
        amount_kind=amount_kind, amount=amount, now_ms=now_ms)
    if not created:
        blocked = AutomationDecision(AutomationAction.BLOCK,
            ("duplicate_execution_intent",), decision.buy_pause_reason, False)
        return SafePreparation(blocked, record, True)
    return SafePreparation(decision, record, False)
