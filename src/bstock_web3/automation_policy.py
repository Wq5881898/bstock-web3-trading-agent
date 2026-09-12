"""Venue-neutral unattended-execution policy; contains no order transport.

The policy consumes an account snapshot that an MCP/venue adapter has already
reconciled. It can authorize an intent, but it cannot submit one by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
import re

from .execution_contract import OrderIntent, PositionAction, ProductType


class AutomationAction(StrEnum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


def _positive_decimal(value, name):
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError(f"Invalid {name}")


@dataclass(frozen=True)
class AutomationPolicyConfig:
    order_budget_quote: Decimal = Decimal("100")
    cumulative_loss_limit: Decimal = Decimal("10")
    max_position_cost: Decimal = Decimal("100")
    max_daily_entries: int = 20
    max_consecutive_losses: int = 3
    entry_cooldown_seconds: int = 60
    snapshot_max_age_seconds: int = 15

    def __post_init__(self):
        for name in ("order_budget_quote", "cumulative_loss_limit",
                     "max_position_cost"):
            _positive_decimal(getattr(self, name), name)
        for name in ("max_daily_entries", "max_consecutive_losses",
                     "snapshot_max_age_seconds"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"Invalid {name}")
        if (type(self.entry_cooldown_seconds) is not int
                or self.entry_cooldown_seconds < 0):
            raise ValueError("Invalid entry_cooldown_seconds")
        if self.order_budget_quote > self.max_position_cost:
            raise ValueError("Order budget exceeds position cost limit")


@dataclass(frozen=True)
class AccountRiskSnapshot:
    account_ref: str
    symbol: str
    product: ProductType
    risk_day: str
    observed_at_ms: int
    reconciled: bool
    can_trade: bool
    available_quote: Decimal
    position_quantity: Decimal
    position_cost: Decimal
    daily_equity_loss: Decimal
    daily_entries: int = 0
    consecutive_losses: int = 0
    last_entry_ms: int | None = None
    pending_order_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.account_ref, str) or not self.account_ref.strip():
            raise ValueError("Invalid account reference")
        if (not isinstance(self.symbol, str)
                or not re.fullmatch(r"[A-Z0-9]{1,32}", self.symbol)):
            raise ValueError("Invalid snapshot symbol")
        if not isinstance(self.product, ProductType):
            raise ValueError("Invalid snapshot product")
        if not isinstance(self.risk_day, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", self.risk_day):
            raise ValueError("Invalid risk day")
        if type(self.observed_at_ms) is not int or self.observed_at_ms < 0:
            raise ValueError("Invalid snapshot timestamp")
        if type(self.reconciled) is not bool or type(self.can_trade) is not bool:
            raise ValueError("Invalid account flags")
        for name in ("available_quote", "position_quantity", "position_cost",
                     "daily_equity_loss"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"Invalid {name}")
        for name in ("daily_entries", "consecutive_losses"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"Invalid {name}")
        if self.last_entry_ms is not None and (type(self.last_entry_ms) is not int
                or self.last_entry_ms < 0):
            raise ValueError("Invalid last entry timestamp")
        if self.pending_order_id is not None and (not isinstance(
                self.pending_order_id, str) or not self.pending_order_id.strip()):
            raise ValueError("Invalid pending order")


@dataclass(frozen=True)
class AutomationDecision:
    action: AutomationAction
    reasons: tuple[str, ...]
    buy_pause_reason: str | None
    notify_operator: bool = False

    @property
    def allowed(self):
        return self.action == AutomationAction.ALLOW


class AutomationPolicy:
    """Stateful BUY latch with explicit, risk-preserving manual recovery."""

    CHECKPOINT_VERSION = 1

    def __init__(self, config=None):
        self.config = config or AutomationPolicyConfig()
        if not isinstance(self.config, AutomationPolicyConfig):
            raise ValueError("Invalid automation policy configuration")
        self.buy_pause_reason: str | None = None
        self.latched_at_ms: int | None = None
        self.risk_day: str | None = None

    def evaluate(self, intent: OrderIntent, snapshot: AccountRiskSnapshot,
                 *, now_ms: int) -> AutomationDecision:
        self._validate_inputs(intent, snapshot, now_ms)
        common = self._common_blocks(intent, snapshot, now_ms)
        transitioned = self._observe_buy_risk(snapshot, now_ms)
        if intent.action == PositionAction.CLOSE_LONG:
            reasons = [*common]
            if snapshot.position_quantity <= 0:
                reasons.append("no_position_to_close")
            return self._decision(reasons, transitioned)

        reasons = [*common]
        if self.buy_pause_reason:
            reasons.append("buy_paused:" + self.buy_pause_reason)
        if snapshot.available_quote < self.config.order_budget_quote:
            reasons.append("insufficient_quote_balance")
        if (snapshot.position_cost + self.config.order_budget_quote
                > self.config.max_position_cost):
            reasons.append("position_cost_limit")
        if (snapshot.last_entry_ms is not None and now_ms - snapshot.last_entry_ms
                < self.config.entry_cooldown_seconds * 1000):
            reasons.append("entry_cooldown")
        return self._decision(reasons, transitioned)

    def pause_buys(self, *, reason="manual_pause", now_ms: int):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Invalid pause reason")
        self._validate_now(now_ms)
        transitioned = self.buy_pause_reason is None
        if transitioned:
            self.buy_pause_reason = reason.strip()
            self.latched_at_ms = now_ms
        return transitioned

    def request_manual_resume(self, snapshot: AccountRiskSnapshot,
                              *, now_ms: int) -> AutomationDecision:
        self._validate_now(now_ms)
        if not isinstance(snapshot, AccountRiskSnapshot):
            raise ValueError("Invalid account risk snapshot")
        reasons = self._snapshot_health(snapshot, now_ms)
        reasons.extend(self._active_risk_reasons(snapshot))
        if reasons:
            return self._decision(reasons, False)
        self.buy_pause_reason = None
        self.latched_at_ms = None
        self.risk_day = snapshot.risk_day
        return AutomationDecision(AutomationAction.ALLOW, (), None, False)

    def checkpoint(self):
        return {"version": self.CHECKPOINT_VERSION,
            "buy_pause_reason": self.buy_pause_reason,
            "latched_at_ms": self.latched_at_ms, "risk_day": self.risk_day}

    @classmethod
    def restore(cls, payload, config=None):
        if (not isinstance(payload, dict) or set(payload) != {
                "version", "buy_pause_reason", "latched_at_ms", "risk_day"}
                or payload["version"] != cls.CHECKPOINT_VERSION):
            raise ValueError("Invalid automation policy checkpoint")
        reason, latched, risk_day = (payload["buy_pause_reason"],
            payload["latched_at_ms"], payload["risk_day"])
        if (reason is None) != (latched is None):
            raise ValueError("Inconsistent automation policy checkpoint")
        if reason is not None and (not isinstance(reason, str) or not reason.strip()
                or type(latched) is not int or latched < 0):
            raise ValueError("Invalid automation policy latch")
        if risk_day is not None and (not isinstance(risk_day, str)
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", risk_day)):
            raise ValueError("Invalid automation policy risk day")
        result = cls(config)
        result.buy_pause_reason, result.latched_at_ms = reason, latched
        result.risk_day = risk_day
        return result

    def _observe_buy_risk(self, snapshot, now_ms):
        if self.buy_pause_reason is not None:
            return False
        reasons = self._active_risk_reasons(snapshot)
        if reasons:
            self.buy_pause_reason = reasons[0]
            self.latched_at_ms = now_ms
            self.risk_day = snapshot.risk_day
            return True
        self.risk_day = snapshot.risk_day
        return False

    def _active_risk_reasons(self, snapshot):
        reasons = []
        if snapshot.daily_equity_loss >= self.config.cumulative_loss_limit:
            reasons.append("cumulative_loss_limit")
        if snapshot.daily_entries >= self.config.max_daily_entries:
            reasons.append("daily_entry_limit")
        if snapshot.consecutive_losses >= self.config.max_consecutive_losses:
            reasons.append("consecutive_loss_limit")
        return reasons

    def _common_blocks(self, intent, snapshot, now_ms):
        reasons = self._snapshot_health(snapshot, now_ms)
        if snapshot.symbol != intent.instrument.symbol:
            reasons.append("symbol_mismatch")
        if snapshot.product != intent.instrument.product:
            reasons.append("product_mismatch")
        return reasons

    def _snapshot_health(self, snapshot, now_ms):
        reasons = []
        age = now_ms - snapshot.observed_at_ms
        if age < 0 or age > self.config.snapshot_max_age_seconds * 1000:
            reasons.append("stale_account_snapshot")
        if not snapshot.reconciled:
            reasons.append("account_not_reconciled")
        if not snapshot.can_trade:
            reasons.append("account_cannot_trade")
        if snapshot.pending_order_id:
            reasons.append("pending_order_exists")
        return reasons

    def _validate_inputs(self, intent, snapshot, now_ms):
        if not isinstance(intent, OrderIntent):
            raise ValueError("Invalid order intent")
        if not isinstance(snapshot, AccountRiskSnapshot):
            raise ValueError("Invalid account risk snapshot")
        self._validate_now(now_ms)

    @staticmethod
    def _validate_now(now_ms):
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("Invalid policy timestamp")

    def _decision(self, reasons, notify):
        unique = tuple(dict.fromkeys(reasons))
        return AutomationDecision(
            AutomationAction.BLOCK if unique else AutomationAction.ALLOW,
            unique, self.buy_pause_reason, notify)
