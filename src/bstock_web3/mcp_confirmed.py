"""Offline-testable confirmed Spot executor with an injected MCP tool caller.

No HTTP, OAuth or desktop wiring. The existing read-only transports remain
read-only. The future authenticated host supplies tool calls and fresh reads.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from math import lcm
import re
import secrets

from .automation_policy import AutomationPolicy
from .execution_contract import OrderIntent, PositionAction, ProductType
from .execution_safety import (ExecutionArming, ExecutionJournal, ExecutionMode,
    ExecutionPhase, McpReconciliationEvidence, prepare_safe_execution)


def number(value):
    if not isinstance(value, (str, Decimal)) or isinstance(value, bool):
        raise ValueError("Invalid Spot decimal")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("Invalid Spot decimal") from None
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid Spot decimal")
    return result


@dataclass(frozen=True)
class SpotMarketRules:
    symbol: str
    base_asset: str
    quote_asset: str
    min_quantity: Decimal
    max_quantity: Decimal
    step_size: Decimal
    min_notional: Decimal
    max_notional: Decimal | None = None
    market_step_size: Decimal | None = None

    def __post_init__(self):
        if any(not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{1,32}", value)
               for value in (self.symbol, self.base_asset, self.quote_asset)):
            raise ValueError("Invalid Spot rule identity")
        for value in (self.min_quantity, self.max_quantity, self.step_size,
                      self.min_notional):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError("Invalid Spot market rules")
        if self.max_quantity < self.min_quantity:
            raise ValueError("Invalid Spot quantity limits")
        if self.market_step_size is not None and (
                not isinstance(self.market_step_size, Decimal)
                or not self.market_step_size.is_finite()
                or self.market_step_size <= 0):
            raise ValueError("Invalid Spot market lot step")
        if self.max_notional is not None and (
                not isinstance(self.max_notional, Decimal)
                or not self.max_notional.is_finite()
                or self.max_notional < self.min_notional):
            raise ValueError("Invalid Spot notional limits")

    @classmethod
    def from_exchange_info(cls, info, symbol):
        if not isinstance(info, dict) or not isinstance(info.get("symbols"), list):
            raise ValueError("Invalid Spot exchange rules")
        matches = [row for row in info["symbols"]
                   if isinstance(row, dict) and row.get("symbol") == symbol]
        if len(matches) != 1:
            raise ValueError("Spot symbol unavailable")
        row = matches[0]
        if (row.get("status") != "TRADING" or row.get("isSpotTradingAllowed") is not True
                or row.get("quoteOrderQtyMarketAllowed") is not True
                or not isinstance(row.get("orderTypes"), list)
                or "MARKET" not in row["orderTypes"]):
            raise ValueError("Spot market orders unavailable")
        filters = row.get("filters")
        if not isinstance(filters, list) or any(not isinstance(f, dict) for f in filters):
            raise ValueError("Invalid Spot filters")
        by_type = {f.get("filterType"): f for f in filters}
        if len(by_type) != len(filters):
            raise ValueError("Duplicate Spot filters")
        lot = by_type.get("LOT_SIZE")
        if not isinstance(lot, dict):
            raise ValueError("Spot lot filter required")
        minimums, maximums = [], []
        for kind in ("MIN_NOTIONAL", "NOTIONAL"):
            f = by_type.get(kind)
            if f is not None:
                if f.get("applyToMarket" if kind == "MIN_NOTIONAL" else "applyMinToMarket") is not True:
                    raise ValueError("Market notional rule not verified")
                minimums.append(number(f.get("minNotional")))
                if kind == "NOTIONAL" and f.get("applyMaxToMarket") is True:
                    maximums.append(number(f.get("maxNotional")))
        if not minimums:
            raise ValueError("Spot notional filter required")
        # MARKET_LOT_SIZE can tighten the limits; zero disables an individual
        # bound or step, not the entire filter (BTCUSDT has a nonzero maxQty).
        market = by_type.get("MARKET_LOT_SIZE")
        min_quantity = number(lot.get("minQty"))
        max_quantity = number(lot.get("maxQty"))
        market_step = None
        if market is not None:
            market_min = number(market.get("minQty"))
            market_max = number(market.get("maxQty"))
            market_step = number(market.get("stepSize")) or None
            if market_min:
                min_quantity = max(min_quantity, market_min)
            if market_max:
                max_quantity = min(max_quantity, market_max)
        return cls(symbol, row.get("baseAsset"), row.get("quoteAsset"),
            min_quantity, max_quantity,
            number(lot.get("stepSize")), max(minimums),
            min(maximums) if maximums else None, market_step)

    def arguments(self, intent, snapshot, budget, client_id):
        instrument = intent.instrument
        if (instrument.product != ProductType.SPOT or instrument.symbol != self.symbol
                or instrument.venue not in ("BINANCE", "BINANCE_SPOT")
                or instrument.base_asset != self.base_asset
                or instrument.quote_asset != self.quote_asset):
            raise ValueError("Spot instrument rules mismatch")
        args = {"symbol": self.symbol, "type": "MARKET",
                "newClientOrderId": client_id, "newOrderRespType": "FULL"}
        if intent.action == PositionAction.OPEN_LONG:
            amount, notional = budget, budget
            args.update(side="BUY", quoteOrderQty=format(amount, "f"))
        elif intent.action == PositionAction.CLOSE_LONG:
            amount = self.tradable_quantity(snapshot.position_quantity,
                                             intent.reference_price)
            if not self.min_quantity <= amount <= self.max_quantity:
                raise ValueError("Spot sell quantity outside lot limits")
            notional = amount * intent.reference_price
            args.update(side="SELL", quantity=format(amount, "f"))
        else:
            raise ValueError("Unsupported Spot action")
        if notional < self.min_notional or (self.max_notional is not None
                                          and notional > self.max_notional):
            raise ValueError("Spot amount outside notional limits")
        return args

    def tradable_quantity(self, quantity: Decimal,
                          reference_price: Decimal) -> Decimal:
        """Return a valid sell quantity, retaining only untradable dust."""
        if (not isinstance(quantity, Decimal) or not quantity.is_finite()
                or quantity < 0 or not isinstance(reference_price, Decimal)
                or not reference_price.is_finite() or reference_price <= 0):
            raise ValueError("Invalid Spot position or reference price")
        steps = [self.step_size]
        if self.market_step_size is not None:
            steps.append(self.market_step_size)
        precision = max(0, *(-step.as_tuple().exponent for step in steps))
        if precision > 18:
            raise ValueError("Spot lot precision exceeds safe limit")
        scale = 10 ** precision
        common_units = lcm(*(int(step * scale) for step in steps))
        common_step = Decimal(common_units) / Decimal(scale)
        amount = (min(quantity, self.max_quantity) / common_step).to_integral_value(
            rounding=ROUND_DOWN) * common_step
        if amount < self.min_quantity or amount * reference_price < self.min_notional:
            return Decimal("0")
        residual = quantity - amount
        if (residual >= self.min_quantity
                and residual * reference_price >= self.min_notional):
            raise ValueError("Spot residual remains tradable; split order required")
        return amount


@dataclass(frozen=True)
class ConfirmedOrderResult:
    order_id: str
    status: str
    executed_base: Decimal
    executed_quote: Decimal


@dataclass(frozen=True)
class ConfirmedSubmission:
    """One externally dispatchable call after confirmation is consumed."""

    fingerprint: str
    client_order_id: str
    account_ref: str
    symbol: str
    arguments: dict
    prepared_at_ms: int


@dataclass(frozen=True)
class ConfirmedRehearsal:
    """Consumed confirmation that is deliberately not externally dispatchable."""

    fingerprint: str
    client_order_id: str
    account_ref: str
    symbol: str
    arguments: dict
    confirmed_at_ms: int


class ConfirmedSpotExecutor:
    """Single-host executor; every submit consumes one exact confirmation.

    caller(name, arguments) returns decoded tool data. A future host must verify
    discovered schemas and commission/book rules before constructing this
    executor. Decimal amounts remain strings, never lossy floats.
    """
    def __init__(self, caller, journal: ExecutionJournal, policy: AutomationPolicy):
        self._caller, self.journal, self.policy = caller, journal, policy
        self._pending = None

    def preview(self, intent: OrderIntent, evidence: McpReconciliationEvidence,
                rules: SpotMarketRules, *, signal_key, now_ms):
        if self._pending is not None:
            raise RuntimeError("Confirmation already pending")
        if not self.journal.execution_lock_held:
            raise RuntimeError("Execution lock required")
        if any(r.phase in (ExecutionPhase.SUBMITTING, ExecutionPhase.SUBMITTED,
                           ExecutionPhase.UNKNOWN) for r in self.journal.records()):
            raise RuntimeError("Unresolved execution requires reconciliation")
        snapshot = evidence.to_snapshot()
        # Validate lot/notional rules before reserving a durable intent.
        rules.arguments(intent, snapshot, self.policy.config.order_budget_quote, "preview")
        arming = ExecutionArming(ExecutionMode.USER_CONFIRMED, snapshot.account_ref,
            snapshot.symbol, snapshot.product, now_ms + 15_000)
        prepared = prepare_safe_execution(intent, evidence, self.policy, arming,
            self.journal, signal_key=signal_key, now_ms=now_ms)
        if not prepared.decision.allowed:
            raise RuntimeError("Order preparation blocked: " + ",".join(prepared.decision.reasons))
        record = prepared.record
        args = rules.arguments(intent, snapshot, self.policy.config.order_budget_quote,
                               record.client_order_id)
        confirmation = "MCP CONFIRM " + secrets.token_hex(12).upper()
        self._pending = (intent, snapshot, rules, record, args, confirmation, now_ms)
        return {"account": snapshot.account_ref, "arguments": dict(args),
                "confirmation": confirmation, "expiresAtMs": now_ms + 15_000}

    def cancel_preview(self):
        """Discard the confirmation; the reserved signal remains non-reusable."""
        self._pending = None

    def submit(self, confirmation, evidence: McpReconciliationEvidence, *, now_ms):
        submission = self.begin_submission(confirmation, evidence, now_ms=now_ms)
        try:
            payload = self._caller("spot.newOrder", dict(submission.arguments))
            return self.accept_submission_result(
                submission.fingerprint, payload, now_ms=now_ms)
        except Exception:
            self.mark_submission_unknown(submission.fingerprint, now_ms=now_ms)
            raise RuntimeError("Submission uncertain; read-only lookup required") from None

    def begin_submission(self, confirmation, evidence: McpReconciliationEvidence,
                         *, now_ms):
        """Consume confirmation and durably enter SUBMITTING before host I/O."""
        record, args = self._consume_confirmation(
            confirmation, evidence, now_ms=now_ms)
        self.journal.transition(record.fingerprint, ExecutionPhase.SUBMITTING, now_ms=now_ms)
        return ConfirmedSubmission(record.fingerprint, record.client_order_id,
                                   record.account_ref, record.symbol,
                                   dict(args), now_ms)

    def rehearse_confirmation(self, confirmation,
                               evidence: McpReconciliationEvidence, *, now_ms):
        """Consume and revalidate a confirmation without arming host submission.

        The durable record intentionally remains PREPARED.  The returned value
        is a separate type and cannot be passed to the submission-ticket
        builder, preventing a desktop rehearsal from becoming a live order.
        """
        record, args = self._consume_confirmation(
            confirmation, evidence, now_ms=now_ms)
        return ConfirmedRehearsal(record.fingerprint, record.client_order_id,
                                  record.account_ref, record.symbol,
                                  dict(args), now_ms)

    def _consume_confirmation(self, confirmation,
                              evidence: McpReconciliationEvidence, *, now_ms):
        if self._pending is None:
            raise RuntimeError("No confirmation pending")
        intent, previous, rules, record, args, expected, created = self._pending
        if not isinstance(confirmation, str) or not secrets.compare_digest(
                confirmation.encode("utf-8"), expected.encode("ascii")):
            raise RuntimeError("Confirmation mismatch")
        self._pending = None  # exact confirmations are consumed even if revalidation fails
        if type(now_ms) is not int or not created <= now_ms < created + 15_000:
            raise RuntimeError("Confirmation expired")
        if not self.journal.execution_lock_held:
            raise RuntimeError("Execution lock required")
        fresh = evidence.to_snapshot()
        if fresh.account_ref != previous.account_ref or fresh.risk_day != previous.risk_day:
            raise RuntimeError("Confirmed account changed")
        if not self.policy.evaluate(intent, fresh, now_ms=now_ms).allowed:
            raise RuntimeError("Fresh account risk check blocked order")
        updated = rules.arguments(intent, fresh, self.policy.config.order_budget_quote,
                                  record.client_order_id)
        if updated != args:
            raise RuntimeError("Confirmed order amount changed")
        if self.journal.get(record.fingerprint).phase != ExecutionPhase.PREPARED:
            raise RuntimeError("Execution no longer prepared")
        return record, args

    def accept_submission_result(self, fingerprint, payload, *, now_ms):
        """Validate a host result and advance the durable execution journal."""
        if not self.journal.execution_lock_held:
            raise RuntimeError("Execution lock required")
        record = self.journal.get(fingerprint)
        if record.phase not in (ExecutionPhase.SUBMITTING,
                                ExecutionPhase.SUBMITTED,
                                ExecutionPhase.UNKNOWN,
                                ExecutionPhase.FILLED,
                                ExecutionPhase.REJECTED):
            raise RuntimeError("Execution not awaiting a host result")
        result = self.validate_submission_result(fingerprint, payload)
        self._record_result(record, result, now_ms)
        return result

    def validate_submission_result(self, fingerprint, payload):
        """Validate an order result without mutating the execution journal."""
        if not self.journal.execution_lock_held:
            raise RuntimeError("Execution lock required")
        record = self.journal.get(fingerprint)
        side = "BUY" if record.action == PositionAction.OPEN_LONG.value else "SELL"
        return self._parse(payload, record, side)

    def mark_submission_unknown(self, fingerprint, *, now_ms):
        """Conservatively close an uncertain external handoff; never resubmit."""
        if not self.journal.execution_lock_held:
            raise RuntimeError("Execution lock required")
        record = self.journal.get(fingerprint)
        if record.phase == ExecutionPhase.UNKNOWN:
            return record
        if record.phase not in (ExecutionPhase.SUBMITTING,
                                ExecutionPhase.SUBMITTED):
            raise RuntimeError("Only an unresolved execution can become unknown")
        return self.journal.transition(record.fingerprint, ExecutionPhase.UNKNOWN,
            now_ms=now_ms, detail="submission_uncertain")

    def reconcile(self, fingerprint, *, now_ms):
        if not self.journal.execution_lock_held:
            raise RuntimeError("Execution lock required")
        record = self.journal.get(fingerprint)
        if record.phase not in (ExecutionPhase.SUBMITTING, ExecutionPhase.SUBMITTED,
                                ExecutionPhase.UNKNOWN):
            raise RuntimeError("Execution not awaiting reconciliation")
        if record.phase == ExecutionPhase.SUBMITTING:
            record = self.journal.transition(fingerprint, ExecutionPhase.UNKNOWN,
                                            now_ms=now_ms, detail="restart_lookup_only")
        side = "BUY" if record.action == PositionAction.OPEN_LONG.value else "SELL"
        try:
            payload = self._caller("spot.getOrder", {"symbol": record.symbol,
                                  "origClientOrderId": record.client_order_id})
            result = self._parse(payload, record, side)
        except Exception:
            raise RuntimeError("Order lookup unresolved; never resubmit") from None
        self._record_result(record, result, now_ms)
        return result

    @staticmethod
    def _parse(payload, record, side):
        if (not isinstance(payload, dict) or payload.get("symbol") != record.symbol
                or payload.get("clientOrderId") != record.client_order_id
                or payload.get("side") != side or payload.get("type") != "MARKET"
                or type(payload.get("orderId")) is not int or payload["orderId"] <= 0
                or payload.get("status") not in ("NEW", "PARTIALLY_FILLED", "FILLED",
                    "CANCELED", "REJECTED", "EXPIRED", "EXPIRED_IN_MATCH")):
            raise ValueError("Invalid Spot order result")
        if record.external_id and str(payload["orderId"]) != record.external_id:
            raise ValueError("Spot order identity changed")
        base, quote = number(payload.get("executedQty")), number(payload.get("cummulativeQuoteQty"))
        if (base == 0) != (quote == 0) or (payload["status"] == "FILLED" and base == 0):
            raise ValueError("Invalid Spot executed amounts")
        if (payload["status"] == "PARTIALLY_FILLED" and base == 0) \
                or (payload["status"] in ("NEW", "REJECTED") and base != 0):
            raise ValueError("Invalid Spot status and executed amounts")
        if (quote if record.amount_kind == "QUOTE" else base) > number(record.amount):
            raise ValueError("Execution exceeds confirmed amount")
        return ConfirmedOrderResult(str(payload["orderId"]), payload["status"], base, quote)

    def _record_result(self, record, result, now_ms):
        phase = (ExecutionPhase.FILLED if result.status == "FILLED" else
                 ExecutionPhase.SUBMITTED if result.status in ("NEW", "PARTIALLY_FILLED")
                 else ExecutionPhase.REJECTED)
        current = self.journal.get(record.fingerprint)
        if current.phase == phase:
            if (current.external_id is not None
                    and current.external_id != result.order_id):
                raise RuntimeError("External order id changed during reconciliation")
            if (current.phase in (ExecutionPhase.FILLED, ExecutionPhase.REJECTED)
                    and current.detail != result.status):
                raise RuntimeError("Terminal execution result changed")
            return
        if current.phase in (ExecutionPhase.FILLED, ExecutionPhase.REJECTED):
            raise RuntimeError("Terminal execution result changed")
        self.journal.transition(record.fingerprint, phase, now_ms=now_ms,
            external_id=result.order_id, detail=result.status)
