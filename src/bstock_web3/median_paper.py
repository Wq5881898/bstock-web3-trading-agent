"""Transactional Median paper ledger. No market HTTP, wallets or live orders."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3

from .engine import BStockEngineConfig
from .median_ticks import MedianTickStream, TickMedianConfig


@dataclass
class MedianLedger:
    cash: str = "1000"
    quantity: str = "0"
    entry_cost: str = "0"
    realized_pnl: str = "0"
    fees: str = "0"
    day: str = ""
    baseline: str | None = None
    last_equity: str | None = None
    pause: str = ""
    entries: int = 0
    losses: int = 0
    last_entry_ms: int | None = None

    @classmethod
    def restore(cls, data):
        if not isinstance(data, dict) or set(data) != set(asdict(cls())):
            raise ValueError("Invalid Median ledger fields")
        result = cls(**data)
        for key in ("cash", "quantity", "entry_cost", "realized_pnl", "fees", "baseline", "last_equity"):
            raw = getattr(result, key)
            if raw is None and key in ("baseline", "last_equity"):
                continue
            if not isinstance(raw, str):
                raise ValueError("Ledger values must be decimal strings")
            try:
                value = Decimal(raw)
            except InvalidOperation as exc:
                raise ValueError("Invalid Median ledger amount") from exc
            if not value.is_finite() or (key != "realized_pnl" and value < 0):
                raise ValueError("Invalid Median ledger amount")
        if (Decimal(result.quantity) > 0) != (Decimal(result.entry_cost) > 0):
            raise ValueError("Incomplete Median position")
        # Permit only Decimal rounding dust, not unexplained deposits/withdrawals.
        if abs(Decimal(result.cash) + Decimal(result.entry_cost) - Decimal("1000") - Decimal(result.realized_pnl)) > Decimal("1e-18"):
            raise ValueError("Median cash/cost/PnL do not reconcile")
        if type(result.entries) is not int or result.entries < 0 or type(result.losses) is not int or result.losses < 0:
            raise ValueError("Invalid Median risk counters")
        if result.last_entry_ms is not None and (type(result.last_entry_ms) is not int or result.last_entry_ms < 0):
            raise ValueError("Invalid entry timestamp")
        if not isinstance(result.day, str) or bool(result.day) != (result.baseline is not None):
            raise ValueError("Incomplete Median daily baseline")
        if result.day:
            datetime.strptime(result.day, "%Y-%m-%d")
        if result.pause not in ("", "MANUAL", "DAILY_LOSS", "DAILY_ENTRY_LIMIT", "CONSECUTIVE_LOSSES", "DATA_GAP", "CLOCK_REWIND"):
            raise ValueError("Invalid Median pause reason")
        return result


class TickPaperSession:
    """Single-thread owner; revision checks also reject stale competing writers.

    All methods except read-only inspection must run on the owning worker thread.
    Inputs and fills are synthetic paper units, not a real Binance balance.
    """

    def __init__(self, path: Path, *, symbol: str, strategy: TickMedianConfig | None = None,
                 risk: BStockEngineConfig | None = None, stream_type=MedianTickStream):
        self.strategy = strategy or TickMedianConfig()
        self.risk = risk or BStockEngineConfig(symbol=symbol, order_size_usdc=Decimal("100"))
        if self.risk.mode != "paper":
            raise ValueError("Median session is paper-only")
        self.symbol = symbol
        self.stream_type = stream_type
        self.stream = stream_type(symbol, self.strategy)
        self.ledger = MedianLedger()
        self.revision = 0
        self.identity = {"symbol": symbol, "strategy": asdict(self.strategy), "risk": {
            name: str(getattr(self.risk, name)) for name in ("order_size_usdc", "paper_fee_rate",
                "paper_daily_loss_limit", "paper_position_cap", "paper_max_daily_entries",
                "paper_max_loss_streak", "paper_entry_cooldown")}}
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5)
        try:
            self.db.execute("PRAGMA synchronous=FULL")
            with self.db:
                self.db.execute("CREATE TABLE IF NOT EXISTS session (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, payload TEXT NOT NULL)")
                self.db.execute("CREATE TABLE IF NOT EXISTS fills (trade_id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
                self.db.execute("INSERT OR IGNORE INTO session VALUES (1, 0, ?)", (self._encode(self.ledger, self.stream),))
            self.revision, raw = self.db.execute("SELECT revision,payload FROM session WHERE id=1").fetchone()
            if type(self.revision) is not int or self.revision < 0:
                raise ValueError("Invalid Median session revision")
            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Duplicate Median session field")
                    result[key] = value
                return result
            if len(raw) > 131072:
                raise ValueError("Median session payload too large")
            payload = json.loads(raw, object_pairs_hook=unique_pairs)
            if not isinstance(payload, dict) or set(payload) != {"version", "identity", "ledger", "stream"} or type(payload["version"]) is not int or payload["version"] != 1 or payload["identity"] != self.identity:
                raise ValueError("Median session configuration mismatch; restore original settings")
            self.ledger = MedianLedger.restore(payload["ledger"])
            self.stream = self.stream_type.restore(payload["stream"], symbol=symbol, config=self.strategy)
            if self.stream.recovery_required and not self.ledger.pause:
                raise ValueError("Recovery marker requires a BUY pause")
            if Decimal(self.ledger.quantity) > 0 and self.stream.next_id is None:
                raise ValueError("Open Median position requires its trade checkpoint")
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def _encode(self, ledger, stream):
        return json.dumps({"version": 1, "identity": self.identity,
                           "ledger": asdict(ledger), "stream": stream.checkpoint()}, allow_nan=False)

    def _copy(self):
        return (MedianLedger.restore(asdict(self.ledger)),
                self.stream_type.restore(self.stream.checkpoint(), symbol=self.symbol, config=self.strategy))

    def _write_transaction(self, ledger, stream, fills):
        # No in-memory publication before SQLite commits successfully.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            revision = self.db.execute("SELECT revision FROM session WHERE id=1").fetchone()[0]
            if revision != self.revision:
                raise RuntimeError("Median session changed in another writer; reopen before continuing")
            for fill in fills:
                self.db.execute("INSERT INTO fills VALUES (?,?)", (fill["trade_id"], json.dumps(fill)))
            self.db.execute("UPDATE session SET revision=?,payload=? WHERE id=1",
                            (revision + 1, self._encode(ledger, stream)))

    def _commit(self, ledger, stream, fills=()):
        self._write_transaction(ledger, stream, fills)
        self.ledger, self.stream = ledger, stream
        self.revision += 1

    def _risk_check(self, ledger, price, time_ms):
        equity = Decimal(ledger.cash) + Decimal(ledger.quantity) * price
        day = datetime.fromtimestamp(time_ms / 1000, timezone.utc).date().isoformat()
        if ledger.day and day < ledger.day:
            ledger.pause = ledger.pause or "CLOCK_REWIND"
            return
        if day != ledger.day:
            ledger.day, ledger.baseline, ledger.entries = day, ledger.last_equity or str(equity), 0
        loss = Decimal(ledger.baseline) - equity
        if loss >= self.risk.paper_daily_loss_limit:
            ledger.pause = ledger.pause or "DAILY_LOSS"
        elif ledger.entries >= self.risk.paper_max_daily_entries:
            ledger.pause = ledger.pause or "DAILY_ENTRY_LIMIT"
        elif ledger.losses >= self.risk.paper_max_loss_streak:
            ledger.pause = ledger.pause or "CONSECUTIVE_LOSSES"
        ledger.last_equity = str(equity)

    def accept_page(self, rows, *, now_ms: int, warmup=False):
        ledger, stream = self._copy()
        try:
            observations = stream.accept_page(rows, now_ms=now_ms, warmup=warmup)
        except ValueError:
            ledger.pause = ledger.pause or "DATA_GAP"
            self._commit(ledger, stream)  # persist the latch, but not an invalid page prefix
            raise
        fills = []
        for point in observations:
            if not point.fresh:
                continue
            tick, price = point.tick, Decimal(str(point.tick.price))
            self._risk_check(ledger, price, tick.time_ms)
            quantity = Decimal(ledger.quantity)
            side = ""
            if quantity > 0 and point.sell:
                gross = quantity * price
                fee = gross * self.risk.paper_fee_rate
                pnl = gross - fee - Decimal(ledger.entry_cost)
                ledger.cash = str(Decimal(ledger.cash) + gross - fee)
                ledger.realized_pnl = str(Decimal(ledger.realized_pnl) + pnl)
                ledger.losses = ledger.losses + 1 if pnl < 0 else 0
                ledger.quantity, ledger.entry_cost = "0", "0"
                side = "sell"
            elif quantity == 0 and point.buy and not ledger.pause:
                if ledger.last_entry_ms is not None and tick.time_ms - ledger.last_entry_ms < self.risk.paper_entry_cooldown * 1000:
                    continue
                spend = min(self.risk.order_size_usdc, Decimal(ledger.cash))
                if spend <= 0:
                    continue
                if spend > self.risk.paper_position_cap:
                    raise ValueError("Median position cost cap exceeded")
                fee = spend * self.risk.paper_fee_rate
                quantity = (spend - fee) / price
                ledger.cash = str(Decimal(ledger.cash) - spend)
                ledger.quantity, ledger.entry_cost = str(quantity), str(spend)
                ledger.entries += 1
                ledger.last_entry_ms = tick.time_ms
                side = "buy"
            if side:
                ledger.fees = str(Decimal(ledger.fees) + fee)
                fills.append({"trade_id": tick.trade_id, "time_ms": tick.time_ms, "side": side,
                              "price": str(price), "quantity": str(quantity), "fee": str(fee)})
                self._risk_check(ledger, price, tick.time_ms)
        if observations:
            self._commit(ledger, stream, fills)
        return fills

    def pause_buys(self):
        ledger, stream = self._copy()
        ledger.pause = ledger.pause or "MANUAL"
        self._commit(ledger, stream)

    def data_error(self):
        ledger, stream = self._copy()
        ledger.pause = ledger.pause or "DATA_GAP"
        stream.recovery_required = True
        self._commit(ledger, stream)

    def resume_buys(self, *, now_ms: int, reconciled=False):
        """Manual only; no new fill, no baseline/count reset, no automatic restart."""
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("Invalid observation time")
        ledger, stream = self._copy()
        latest = stream.latest_tick()
        if latest is None or not 0 <= now_ms - latest["time_ms"] <= 5000:
            raise ValueError("Fresh accepted trade required before resume")
        # Gap recovery requires at least one accepted fresh repair after the failure.
        if type(reconciled) is not bool:
            raise ValueError("Invalid reconciliation flag")
        if stream.recovery_required and not reconciled:
            raise ValueError("Data recovery needs explicit reconciliation; resume is not available yet")
        price = Decimal(str(latest["price"]))
        self._risk_check(ledger, price, latest["time_ms"])
        if Decimal(ledger.baseline) - Decimal(ledger.last_equity) >= self.risk.paper_daily_loss_limit or ledger.entries >= self.risk.paper_max_daily_entries or ledger.pause == "CLOCK_REWIND":
            return False
        ledger.pause, ledger.losses = "", 0
        stream.recovery_required = False
        self._commit(ledger, stream)
        return True

    def fills(self, *, limit=None):
        if limit is None:
            rows = self.db.execute("SELECT payload FROM fills ORDER BY trade_id")
        else:
            if type(limit) is not int or not 1 <= limit <= 1000:
                raise ValueError("Invalid fill history limit")
            rows = reversed(list(self.db.execute(
                "SELECT payload FROM fills ORDER BY trade_id DESC LIMIT ?", (limit,))))
        return [json.loads(row[0]) for row in rows]


class MedianPaperSession(TickPaperSession):
    """Backwards-compatible fixed tick-Median paper session."""


class RangePaperSession(TickPaperSession):
    def __init__(self, path: Path, *, symbol: str, strategy, risk: BStockEngineConfig):
        from .range_ticks import RangeTickStream
        super().__init__(path, symbol=symbol, strategy=strategy, risk=risk,
                         stream_type=RangeTickStream)
