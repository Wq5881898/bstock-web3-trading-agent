"""Replayable, fee-aware Spot accounting. No network or order submission."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import os
import re

from .execution_lock import ExecutionLock


@dataclass(frozen=True)
class SpotFillSummary:
    quantity: Decimal
    cost: Decimal
    realized_pnl: Decimal
    fill_count: int


@dataclass(frozen=True)
class SpotFillRiskStats:
    daily_entries: int
    consecutive_losses: int
    last_entry_ms: int | None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise ValueError("Invalid fill amount")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("Invalid fill amount") from None
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid fill amount")
    return result


def normalize_fills(trades, symbol, base_asset, quote_asset, *, require_ids=True):
    if not isinstance(trades, list):
        raise ValueError("Invalid Spot trade history")
    normalized, seen = [], set()
    for row in trades:
        if not isinstance(row, dict) or row.get("symbol") != symbol:
            raise ValueError("Invalid Spot trade history")
        if type(row.get("time")) is not int or row["time"] < 0:
            raise ValueError("Invalid fill timestamp")
        if type(row.get("isBuyer")) is not bool:
            raise ValueError("Invalid Spot trade side")
        trade_id = row.get("id")
        if require_ids or trade_id is not None:
            if type(trade_id) is not int or trade_id < 0 or trade_id in seen:
                raise ValueError("Invalid or duplicate fill ID")
            seen.add(trade_id)
        order_id = row.get("orderId")
        if require_ids and (type(order_id) is not int or order_id <= 0):
            raise ValueError("Invalid fill order ID")
        qty, quote = _number(row.get("qty")), _number(row.get("quoteQty"))
        commission = _number(row.get("commission", "0"))
        asset = row.get("commissionAsset")
        if qty == 0 or quote == 0:
            raise ValueError("Invalid zero fill quantity or quote")
        if commission and asset not in {base_asset, quote_asset}:
            raise ValueError("Third-asset commission requires explicit risk accounting")
        normalized.append(dict(symbol=symbol, id=trade_id, orderId=order_id,
            time=row["time"], isBuyer=row["isBuyer"], qty=str(qty),
            quoteQty=str(quote), commission=str(commission),
            commissionAsset=asset if commission else None))
    return sorted(normalized, key=lambda row: (row["time"], row["id"] or 0))


def _replay_fills(trades, symbol, base_asset, quote_asset, *, require_ids=True):
    rows = normalize_fills(trades, symbol, base_asset, quote_asset,
                           require_ids=require_ids)
    quantity = cost = realized = Decimal("0")
    sale_pnl = {}
    for row in rows:
        qty, quote, fee = (Decimal(row[key]) for key in
                           ("qty", "quoteQty", "commission"))
        base_fee = fee if row["commissionAsset"] == base_asset else Decimal("0")
        quote_fee = fee if row["commissionAsset"] == quote_asset else Decimal("0")
        if row["isBuyer"]:
            acquired = qty - base_fee
            if acquired <= 0:
                raise ValueError("Invalid net bought quantity")
            quantity += acquired
            cost += quote + quote_fee
        else:
            disposed = qty + base_fee
            if disposed > quantity:
                raise ValueError("Trade history cannot explain sold quantity")
            proceeds = quote - quote_fee
            if proceeds < 0:
                raise ValueError("Invalid net sale proceeds")
            removed_cost = cost * disposed / quantity
            fill_pnl = proceeds - removed_cost
            realized += fill_pnl
            sale_pnl[row["orderId"]] = sale_pnl.get(
                row["orderId"], Decimal("0")) + fill_pnl
            quantity -= disposed
            cost = Decimal("0") if quantity == 0 else cost - removed_cost
    return rows, SpotFillSummary(quantity, cost, realized, len(rows)), sale_pnl


def summarize_fills(trades, symbol, base_asset, quote_asset, *, require_ids=True):
    return _replay_fills(trades, symbol, base_asset, quote_asset,
                         require_ids=require_ids)[1]


def fill_risk_stats(trades, symbol, base_asset, quote_asset, risk_day):
    """Derive entry count and completed-sale loss streak from complete fills."""
    if not isinstance(risk_day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", risk_day):
        raise ValueError("Invalid risk day")
    try:
        parsed_day = datetime.strptime(risk_day, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValueError("Invalid risk day") from None
    if parsed_day != risk_day:
        raise ValueError("Invalid risk day")
    rows, _, sale_pnl = _replay_fills(
        trades, symbol, base_asset, quote_asset, require_ids=True)
    buys = [row for row in rows if row["isBuyer"]]
    daily_orders = {row["orderId"] for row in buys if
        datetime.fromtimestamp(row["time"] / 1000, timezone.utc).date().isoformat()
        == risk_day}
    last_entry = max((row["time"] for row in buys), default=None)
    sale_last_fill = {}
    for row in rows:
        if not row["isBuyer"]:
            sale_last_fill[row["orderId"]] = (row["time"], row["id"])
    sale_order_sequence = sorted(sale_last_fill, key=sale_last_fill.get)
    streak = 0
    for order_id in reversed(sale_order_sequence):
        if sale_pnl[order_id] < 0:
            streak += 1
        else:
            break
    return SpotFillRiskStats(len(daily_orders), streak, last_entry)


class SpotFillLedger:
    """Account-bound complete-history checkpoint protected by an OS lock.

    Sync requires the full paginated history; missing or altered prior fills fail
    closed. Disk is replaced before memory changes, so failed writes are retryable.
    Order acknowledgements are never treated as fills.
    """

    def __init__(self, path: Path, *, account_ref: str, symbol: str,
                 base_asset: str, quote_asset: str):
        values = (account_ref, symbol, base_asset, quote_asset)
        if any(not isinstance(value, str) or not value for value in values) \
                or base_asset == quote_asset:
            raise ValueError("Invalid ledger identity")
        self.path = Path(path)
        self.identity = dict(account_ref=account_ref, symbol=symbol,
                             base_asset=base_asset, quote_asset=quote_asset)
        self.lock = ExecutionLock(self.path.with_suffix(self.path.suffix + ".lock"))
        self._rows = []
        self._summary = SpotFillSummary(Decimal("0"), Decimal("0"), Decimal("0"), 0)

    @property
    def summary(self):
        return self._summary

    @property
    def rows(self):
        return tuple(dict(row) for row in self._rows)

    def _normalize(self, rows):
        return normalize_fills(rows, self.identity["symbol"],
            self.identity["base_asset"], self.identity["quote_asset"])

    def _summarize(self, rows):
        return summarize_fills(rows, self.identity["symbol"],
            self.identity["base_asset"], self.identity["quote_asset"])

    def __enter__(self):
        self.lock.require()
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("version") != 1 or data.get("identity") != self.identity:
                    raise ValueError("Ledger identity or version mismatch")
                rows = self._normalize(data.get("fills"))
                summary = self._summarize(rows)
                self._rows, self._summary = rows, summary
            elif self._rows:
                raise ValueError("Previously recorded ledger is missing")
        except Exception:
            self.lock.release()
            raise
        return self

    def __exit__(self, *args):
        self.lock.release()

    def sync(self, trades, *, history_complete: bool):
        if not self.lock.held:
            raise RuntimeError("Ledger lock must be held")
        if history_complete is not True:
            raise ValueError("Complete paginated trade history is required")
        rows = self._normalize(trades)
        incoming = {row["id"]: row for row in rows}
        if any(incoming.get(row["id"]) != row for row in self._rows):
            raise ValueError("Previously recorded fills are missing or changed")
        summary = self._summarize(rows)
        data = dict(version=1, identity=self.identity, fills=rows)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
        self._rows, self._summary = rows, summary
        return summary
