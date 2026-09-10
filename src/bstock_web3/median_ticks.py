"""Offline, causal aggregate-trade Median preparation; no execution or HTTP.

Preserves the source strategy's current-tick-inclusive rolling-price semantics.
The future executor must commit cursor and fills together, not independently.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
from statistics import median
import tempfile


def _integer(value, name):
    if type(value) is not int or not 0 <= value <= 9223372036854775807:
        raise ValueError(f"Invalid {name}")
    return value


def _number(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"Invalid {name}")
    try:
        parsed = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid {name}") from exc
    if not math.isfinite(parsed) or parsed < 0 or (positive and parsed == 0):
        raise ValueError(f"Invalid {name}")
    return parsed


@dataclass(frozen=True)
class AggregateTick:
    trade_id: int
    time_ms: int
    price: float
    quantity: float

    def __post_init__(self):
        _integer(self.trade_id, "aggregate trade ID")
        _integer(self.time_ms, "UTC timestamp")
        object.__setattr__(self, "price", _number(self.price, "price", positive=True))
        object.__setattr__(self, "quantity", _number(self.quantity, "quantity"))

    @classmethod
    def from_wire(cls, row):
        if not isinstance(row, dict):
            raise ValueError("Aggregate trade must be an object")
        try:
            return cls(row["a"], row["T"], row["p"], row["q"])
        except KeyError as exc:
            raise ValueError("Incomplete aggregate trade") from exc


@dataclass(frozen=True)
class TickMedianConfig:
    window: int = 20
    entry_deviation: float = .002
    exit_deviation: float = .002

    def __post_init__(self):
        if type(self.window) is not int or not 1 <= self.window <= 100:
            raise ValueError("Median window must be 1–100 trades")
        for key in ("entry_deviation", "exit_deviation"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value < 1:
                raise ValueError("Median deviation must be a finite fraction")


@dataclass(frozen=True)
class MedianObservation:
    tick: AggregateTick
    median_price: float | None
    fresh: bool
    buy: bool
    sell: bool
    reason: str


class MedianTickStream:
    """Single-owner feature state. First page is warmup, including after empty restore."""

    def __init__(self, symbol: str, config: TickMedianConfig | None = None):
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9]{1,32}", symbol):
            raise ValueError("Invalid market symbol")
        self.symbol = symbol
        self.config = config or TickMedianConfig()
        if not isinstance(self.config, TickMedianConfig):
            raise ValueError("Invalid Median configuration")
        self._ticks: tuple[AggregateTick, ...] = ()
        self.recovery_required = False

    @property
    def next_id(self):
        return self._ticks[-1].trade_id + 1 if self._ticks else None

    def latest_tick(self):
        """Return the last accepted market point without exposing mutable state."""
        if not self._ticks:
            return None
        tick = self._ticks[-1]
        return {"time_ms": tick.time_ms, "price": tick.price}

    def accept_page(self, rows, *, now_ms: int, warmup=False, context=None) -> tuple[MedianObservation, ...]:
        _integer(now_ms, "observation time")
        try:
            if type(warmup) is not bool or not isinstance(rows, list) or len(rows) > 1000:
                raise ValueError("Expected at most 1000 aggregate trades")
            ticks = [AggregateTick.from_wire(row) for row in rows]
            for prior, tick in zip(ticks, ticks[1:]):
                if tick.trade_id != prior.trade_id + 1 or tick.time_ms < prior.time_ms:
                    raise ValueError("Non-contiguous or time-reversed trade page")
            staged = list(self._ticks)
            known = {tick.trade_id: tick for tick in staged}
            cold = not staged
            results = []
            for tick in ticks:
                if staged and tick.trade_id <= staged[-1].trade_id:
                    if tick.trade_id in known and known[tick.trade_id] != tick:
                        raise ValueError("Conflicting replay of aggregate trade")
                    continue
                if staged and (tick.trade_id != staged[-1].trade_id + 1 or tick.time_ms < staged[-1].time_ms):
                    raise ValueError("Missing aggregate trade or reversed timestamp")
                staged.append(tick)
                staged = staged[-200:]
                center = median([item.price for item in staged[-self.config.window:]]) if len(staged) >= self.config.window else None
                if center is not None and not math.isfinite(center):
                    raise ValueError("Non-finite Median")
                fresh = not cold and not warmup and 0 <= now_ms - tick.time_ms <= 5000
                buy = fresh and not self.recovery_required and center is not None and tick.price < center * (1 - self.config.entry_deviation)
                sell = fresh and center is not None and tick.price > center * (1 + self.config.exit_deviation)
                reason = "warmup" if cold or warmup or center is None else (
                    "stale_or_future_tick" if not fresh else "median_ready")
                results.append(MedianObservation(tick, center, fresh, buy, sell, reason))
        except ValueError:
            self.recovery_required = True
            raise
        # All-or-nothing page acceptance: invalid tails never consume valid prefixes.
        self._ticks = tuple(staged)
        return tuple(results)

    def checkpoint(self):
        return {"version": 1, "symbol": self.symbol, "config": asdict(self.config),
                "recovery_required": self.recovery_required,
                "ticks": [asdict(tick) for tick in self._ticks]}

    @classmethod
    def restore(cls, payload, *, symbol: str, config: TickMedianConfig):
        if not isinstance(payload, dict) or set(payload) != {"version", "symbol", "config", "recovery_required", "ticks"}:
            raise ValueError("Invalid Median checkpoint fields")
        if type(payload["version"]) is not int or payload["version"] != 1 or payload["symbol"] != symbol:
            raise ValueError("Median checkpoint version/symbol mismatch")
        raw_config = payload["config"]
        if not isinstance(raw_config, dict) or set(raw_config) != set(asdict(TickMedianConfig())):
            raise ValueError("Invalid checkpoint configuration")
        restored_config = TickMedianConfig(**raw_config)
        if restored_config != config or type(payload["recovery_required"]) is not bool:
            raise ValueError("Median checkpoint configuration/recovery mismatch")
        rows = payload["ticks"]
        if not isinstance(rows, list) or len(rows) > 200:
            raise ValueError("Invalid checkpoint buffer")
        ticks = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"trade_id", "time_ms", "price", "quantity"}:
                raise ValueError("Invalid checkpoint tick")
            ticks.append(AggregateTick(**row))
        for previous, tick in zip(ticks, ticks[1:]):
            if tick.trade_id != previous.trade_id + 1 or tick.time_ms < previous.time_ms:
                raise ValueError("Checkpoint trade continuity failure")
        instance = cls(symbol, config)
        instance._ticks = tuple(ticks)
        instance.recovery_required = payload["recovery_required"]
        return instance

    def save(self, path: Path):
        """Feature-only checkpoint. Not an order ledger or execution commit."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".median-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(self.checkpoint(), stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path, *, symbol: str, config: TickMedianConfig):
        with path.open("rb") as stream:
            raw = stream.read(131073)
        if len(raw) > 131072:
            raise ValueError("Median checkpoint too large")
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate checkpoint key")
                result[key] = value
            return result
        try:
            payload = json.loads(raw, object_pairs_hook=unique_pairs)
        except (UnicodeError, RecursionError) as exc:
            raise ValueError("Invalid Median checkpoint") from exc
        return cls.restore(payload, symbol=symbol, config=config)
