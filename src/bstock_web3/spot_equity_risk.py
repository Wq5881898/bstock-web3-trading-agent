"""Persistent, cash-flow-adjusted Spot equity-loss observations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path

from .execution_lock import ExecutionLock


def _decimal(value, name, *, signed=False):
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise ValueError(f"Invalid {name}")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"Invalid {name}") from None
    if not result.is_finite() or (not signed and result < 0):
        raise ValueError(f"Invalid {name}")
    return result


def _utc_day(timestamp_ms):
    if type(timestamp_ms) is not int or timestamp_ms < 0:
        raise ValueError("Invalid observation timestamp")
    return datetime.fromtimestamp(timestamp_ms / 1000,
                                  timezone.utc).date().isoformat()


@dataclass(frozen=True)
class EquityObservation:
    risk_day: str
    observed_at_ms: int
    quote_total: Decimal
    base_quantity: Decimal
    liquidation_bid: Decimal

    def __post_init__(self):
        if self.risk_day != _utc_day(self.observed_at_ms):
            raise ValueError("Risk day does not match UTC observation")
        for name in ("quote_total", "base_quantity", "liquidation_bid"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"Invalid {name}")
        if self.base_quantity and not self.liquidation_bid:
            raise ValueError("Positive position requires liquidation bid")

    @property
    def raw_equity(self):
        return self.quote_total + self.base_quantity * self.liquidation_bid


@dataclass(frozen=True)
class EquityRiskResult:
    daily_equity_loss: Decimal
    raw_equity: Decimal
    adjusted_equity: Decimal
    baseline_equity: Decimal


def normalize_cashflows(cashflows):
    """Normalize full quote-valued account flows supplied by a verified host."""
    if not isinstance(cashflows, list):
        raise ValueError("Invalid cash-flow history")
    seen, result = set(), []
    for row in cashflows:
        if not isinstance(row, dict):
            raise ValueError("Invalid cash-flow row")
        flow_id, occurred = row.get("id"), row.get("time")
        if (not isinstance(flow_id, str) or not flow_id.strip()
                or len(flow_id) > 128 or flow_id in seen
                or type(occurred) is not int or occurred < 0):
            raise ValueError("Invalid or duplicate cash-flow identity")
        seen.add(flow_id)
        amount = _decimal(row.get("amount"), "cash-flow amount", signed=True)
        if amount == 0:
            raise ValueError("Zero cash flow is not recordable")
        result.append({"id": flow_id, "time": occurred, "amount": str(amount)})
    return sorted(result, key=lambda row: (row["time"], row["id"]))


class SpotEquityRiskLedger:
    """Account/instrument-bound risk baseline; never submits an order."""

    def __init__(self, path: Path, *, account_ref: str, symbol: str):
        if any(not isinstance(value, str) or not value.strip()
               for value in (account_ref, symbol)):
            raise ValueError("Invalid equity ledger identity")
        self.path = Path(path)
        self.identity = {"account_ref": account_ref, "symbol": symbol}
        self.lock = ExecutionLock(self.path.with_suffix(self.path.suffix + ".lock"))
        self._state = None

    def __enter__(self):
        self.lock.require()
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if (not isinstance(data, dict) or data.get("version") != 1
                        or data.get("identity") != self.identity):
                    raise ValueError("Equity ledger identity or version mismatch")
                state = data.get("state")
                self._validate_state(state)
                self._state = state
            elif self._state is not None:
                raise ValueError("Previously recorded equity ledger is missing")
        except Exception:
            self.lock.release()
            raise
        return self

    def __exit__(self, *args):
        self.lock.release()

    @staticmethod
    def _validate_state(state):
        if not isinstance(state, dict) or set(state) != {
                "risk_day", "baseline_at_ms", "baseline_equity",
                "last_observed_at_ms", "last_raw_equity", "cashflows"}:
            raise ValueError("Invalid equity ledger state")
        if state["risk_day"] != _utc_day(state["last_observed_at_ms"]):
            raise ValueError("Invalid equity ledger day")
        if (type(state["baseline_at_ms"]) is not int
                or state["baseline_at_ms"] < 0
                or state["baseline_at_ms"] > state["last_observed_at_ms"]):
            raise ValueError("Invalid equity baseline timestamp")
        _decimal(state["baseline_equity"], "baseline equity")
        _decimal(state["last_raw_equity"], "last raw equity")
        normalized = normalize_cashflows(state["cashflows"])
        if normalized != state["cashflows"]:
            raise ValueError("Non-canonical equity cash-flow history")

    def _require_ready(self):
        if not self.lock.held:
            raise RuntimeError("Equity ledger lock must be held")

    def initialize(self, observation: EquityObservation, cashflows, *,
                   history_complete: bool, operator_confirmed: bool):
        self._require_ready()
        if self._state is not None:
            raise RuntimeError("Equity baseline already initialized")
        if history_complete is not True or operator_confirmed is not True:
            raise ValueError("Complete history and explicit baseline confirmation required")
        flows = normalize_cashflows(cashflows)
        if any(row["time"] > observation.observed_at_ms for row in flows):
            raise ValueError("Future cash flow in observation")
        state = {"risk_day": observation.risk_day,
            "baseline_at_ms": observation.observed_at_ms,
            "baseline_equity": str(observation.raw_equity),
            "last_observed_at_ms": observation.observed_at_ms,
            "last_raw_equity": str(observation.raw_equity), "cashflows": flows}
        self._persist(state)
        return EquityRiskResult(Decimal("0"), observation.raw_equity,
                                observation.raw_equity, observation.raw_equity)

    def observe(self, observation: EquityObservation, cashflows, *,
                history_complete: bool):
        self._require_ready()
        if self._state is None:
            raise RuntimeError("Equity baseline is not initialized")
        if history_complete is not True:
            raise ValueError("Complete cash-flow history is required")
        if observation.observed_at_ms <= self._state["last_observed_at_ms"]:
            raise ValueError("Equity observation must advance")
        flows = normalize_cashflows(cashflows)
        incoming = {row["id"]: row for row in flows}
        if any(incoming.get(row["id"]) != row for row in self._state["cashflows"]):
            raise ValueError("Previously recorded cash flows are missing or changed")
        if any(row["time"] > observation.observed_at_ms for row in flows):
            raise ValueError("Future cash flow in observation")
        state = dict(self._state)
        if observation.risk_day != state["risk_day"]:
            state["risk_day"] = observation.risk_day
            state["baseline_at_ms"] = state["last_observed_at_ms"]
            state["baseline_equity"] = state["last_raw_equity"]
        baseline_at = state["baseline_at_ms"]
        net_flow = sum((Decimal(row["amount"]) for row in flows
                        if baseline_at < row["time"] <= observation.observed_at_ms),
                       Decimal("0"))
        baseline = Decimal(state["baseline_equity"])
        adjusted = observation.raw_equity - net_flow
        loss = max(Decimal("0"), baseline - adjusted)
        state.update(last_observed_at_ms=observation.observed_at_ms,
                     last_raw_equity=str(observation.raw_equity), cashflows=flows)
        self._persist(state)
        return EquityRiskResult(loss, observation.raw_equity, adjusted, baseline)

    def _persist(self, state):
        data = {"version": 1, "identity": self.identity, "state": state}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
        self._state = state
