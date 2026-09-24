"""Account-bound, no-external-flow equity guard for MCP Spot sessions.

The authorized host supplies verified snapshots.  This ledger never calls MCP.
Transfers after the operator-approved baseline fail closed because the seven
Spot preflight reads do not contain complete sub-account cash-flow history.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
import os
from pathlib import Path

from .execution_lock import ExecutionLock
from .mcp_host_receipt import VerifiedSpotHostReceipt
from .mcp_spot_snapshot import LocalRiskMetrics
from .spot_accounting import normalize_fills


@dataclass(frozen=True)
class SessionEquityRisk:
    cumulative_loss: Decimal
    equity: Decimal
    baseline_equity: Decimal


class McpSpotEquityGuard:
    """Durably tracks session equity; unexplained base/quote flows block trading."""

    VERSION = 1
    _TOLERANCE = Decimal("0.00000001")

    def __init__(self, path: Path, *, account_ref: str,
                 account_fingerprint: str, symbol: str):
        self.path = Path(path)
        self.identity = dict(account_ref=account_ref,
                             account_fingerprint=account_fingerprint,
                             symbol=symbol)
        self.lock = ExecutionLock(self.path.with_suffix(self.path.suffix + ".lock"))
        self.state: dict | None = None

    def __enter__(self):
        self.lock.require()
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if (not isinstance(data, dict) or set(data) != {
                        "version", "identity", "state"}
                        or data["version"] != self.VERSION
                        or data["identity"] != self.identity):
                    raise ValueError("MCP equity guard identity or version mismatch")
                self._validate_state(data["state"])
                self.state = data["state"]
        except Exception:
            self.lock.release()
            raise
        return self

    def __exit__(self, *args):
        self.lock.release()

    @classmethod
    def _validate_state(cls, state):
        if not isinstance(state, dict) or set(state) != {
                "baseline_equity", "last_equity", "last_quote", "last_base",
                "last_bid", "last_observed_at_ms", "last_request_id", "fills"}:
            raise ValueError("Invalid MCP equity guard state")
        for key in ("baseline_equity", "last_equity", "last_quote",
                    "last_base", "last_bid"):
            value = state[key]
            if (not isinstance(value, str) or not Decimal(value).is_finite()
                    or Decimal(value) < 0):
                raise ValueError("Invalid MCP equity guard amount")
        if (type(state["last_observed_at_ms"]) is not int
                or state["last_observed_at_ms"] < 0
                or not isinstance(state["last_request_id"], str)
                or not state["last_request_id"]):
            raise ValueError("Invalid MCP equity guard timestamp")
        rows = state["fills"]
        if not isinstance(rows, list) or any(not isinstance(row, dict)
                                              for row in rows):
            raise ValueError("Invalid MCP equity guard fills")

    def _snapshot(self, receipt: VerifiedSpotHostReceipt):
        if (not isinstance(receipt, VerifiedSpotHostReceipt)
                or receipt.account_ref != self.identity["account_ref"]
                or receipt.account_fingerprint
                    != self.identity["account_fingerprint"]
                or receipt.symbol != self.identity["symbol"]):
            raise ValueError("MCP equity guard account or symbol changed")
        evidence = receipt.to_evidence(
            risk_day=receipt.observed_at[:10],
            risk=LocalRiskMetrics(Decimal("0")))
        snapshot = evidence.to_snapshot()
        if not snapshot.reconciled or not snapshot.can_trade \
                or snapshot.pending_order_id:
            raise ValueError("MCP equity guard requires a tradable settled account")
        account = receipt.tool_results["spot.getAccount"]
        balances = {row["asset"]: row for row in account["balances"]}
        def total(asset):
            row = balances.get(asset)
            return (Decimal(str(row["free"])) + Decimal(str(row["locked"]))
                    if row else Decimal("0"))
        quote, base = total(receipt.quote_asset), total(receipt.base_asset)
        bid = Decimal(receipt.tool_results["spot.tickerBookTicker"]["bidPrice"])
        rows = normalize_fills(receipt.tool_results["spot.myTrades"],
                               receipt.symbol, receipt.base_asset,
                               receipt.quote_asset)
        return quote, base, bid, rows

    def initialize(self, receipt: VerifiedSpotHostReceipt, *,
                   operator_confirmed: bool) -> SessionEquityRisk:
        if not self.lock.held:
            raise RuntimeError("MCP equity guard lock must be held")
        if self.state is not None:
            raise RuntimeError("MCP equity baseline already exists")
        if operator_confirmed is not True:
            raise ValueError("Explicit MCP equity baseline confirmation required")
        quote, base, bid, rows = self._snapshot(receipt)
        equity = quote + base * bid
        self._persist(dict(
            baseline_equity=str(equity), last_equity=str(equity),
            last_quote=str(quote), last_base=str(base), last_bid=str(bid),
            last_observed_at_ms=receipt.observed_at_ms,
            last_request_id=receipt.request_id, fills=rows))
        return SessionEquityRisk(Decimal("0"), equity, equity)

    def observe(self, receipt: VerifiedSpotHostReceipt) -> SessionEquityRisk:
        if not self.lock.held:
            raise RuntimeError("MCP equity guard lock must be held")
        if self.state is None:
            raise RuntimeError("Confirmed MCP equity baseline is required")
        quote, base, bid, rows = self._snapshot(receipt)
        previous = self.state
        seen = {row["id"]: row for row in previous["fills"]}
        incoming = {row["id"]: row for row in rows}
        if any(incoming.get(identifier) != row for identifier, row in seen.items()):
            raise ValueError("MCP equity guard fill history changed or shrank")
        if receipt.observed_at_ms < previous["last_observed_at_ms"]:
            raise ValueError("MCP equity guard snapshot moved backwards")
        if receipt.observed_at_ms == previous["last_observed_at_ms"]:
            if (receipt.request_id != previous["last_request_id"]
                    or rows != previous["fills"]
                    or quote != Decimal(previous["last_quote"])
                    or base != Decimal(previous["last_base"])
                    or bid != Decimal(previous["last_bid"])):
                raise ValueError("MCP equity guard observation changed in place")
        else:
            quote_delta = base_delta = Decimal("0")
            for row in rows:
                if row["id"] in seen:
                    continue
                quantity = Decimal(row["qty"])
                notional = Decimal(row["quoteQty"])
                fee = Decimal(row["commission"])
                base_fee = fee if row["commissionAsset"] == receipt.base_asset else Decimal("0")
                quote_fee = fee if row["commissionAsset"] == receipt.quote_asset else Decimal("0")
                if row["isBuyer"]:
                    base_delta += quantity - base_fee
                    quote_delta -= notional + quote_fee
                else:
                    base_delta -= quantity + base_fee
                    quote_delta += notional - quote_fee
            if (abs(quote - Decimal(previous["last_quote"]) - quote_delta)
                    > self._TOLERANCE
                    or abs(base - Decimal(previous["last_base"]) - base_delta)
                    > self._TOLERANCE):
                raise ValueError("Unexplained Spot balance change; manual review required")
        equity = quote + base * bid
        baseline = Decimal(previous["baseline_equity"])
        if receipt.observed_at_ms > previous["last_observed_at_ms"]:
            self._persist(dict(previous, last_equity=str(equity),
                               last_quote=str(quote), last_base=str(base),
                               last_bid=str(bid),
                               last_observed_at_ms=receipt.observed_at_ms,
                               last_request_id=receipt.request_id, fills=rows))
        return SessionEquityRisk(max(Decimal("0"), baseline - equity),
                                 equity, baseline)

    def _persist(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({"version": self.VERSION, "identity": self.identity,
                       "state": state}, handle, ensure_ascii=True,
                      allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
        self.state = state
