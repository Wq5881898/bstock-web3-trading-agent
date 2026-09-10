"""Causal fixed Range-bar strategies over validated aggregate trades."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from statistics import median

from .median_ticks import AggregateTick

RANGE_BPS = (5, 10, 20, 30, 50, 75, 100, 150)
RANGE_MEDIAN_WINDOWS = (5, 10, 20, 30, 40, 60)
MAX_RANGE_BARS_PER_TICK = 1000


@dataclass(frozen=True)
class RangeStrategyConfig:
    family: str = "ema"
    range_bps: int = 20
    short: int = 15
    long: int = 45
    entry_threshold: float = 0.0
    exit_threshold: float = 0.0
    window: int = 20
    deviation: float = .003

    def __post_init__(self):
        if self.family not in ("ema", "median") or type(self.range_bps) is not int or self.range_bps not in RANGE_BPS:
            raise ValueError("Invalid Range family/size")
        if type(self.short) is not int or type(self.long) is not int or not 2 <= self.short < self.long <= 100:
            raise ValueError("Range EMA spans must satisfy 2 <= short < long <= 100")
        if type(self.window) is not int or self.window not in RANGE_MEDIAN_WINDOWS:
            raise ValueError("Unsupported Range Median window")
        for key in ("entry_threshold", "exit_threshold", "deviation"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value < 1:
                raise ValueError("Range thresholds must be finite fractions")
        if self.family == "median" and self.deviation == 0:
            raise ValueError("Range Median deviation must be positive")


@dataclass(frozen=True)
class RangeBar:
    sequence: int
    started_ms: int
    closed_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int
    synthetic: bool

    def __post_init__(self):
        for name in ("sequence", "started_ms", "closed_ms", "tick_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError("Invalid Range bar integer")
        values = (self.open, self.high, self.low, self.close, self.volume)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError("Invalid Range bar number")
        if min(values[:4]) <= 0 or self.volume < 0 or self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("Inconsistent Range bar")
        if type(self.synthetic) is not bool or self.closed_ms < self.started_ms:
            raise ValueError("Invalid Range bar metadata")


@dataclass(frozen=True)
class RangeObservation:
    tick: AggregateTick
    fresh: bool
    buy: bool
    sell: bool
    reason: str
    generation: int
    closed_count: int


class RangeTickStream:
    def __init__(self, symbol: str, config: RangeStrategyConfig | None = None):
        from .median_ticks import MedianTickStream
        # Reuse the exact symbol validation boundary without retaining its state.
        MedianTickStream(symbol)
        self.symbol = symbol
        self.config = config or RangeStrategyConfig()
        if not isinstance(self.config, RangeStrategyConfig):
            raise ValueError("Invalid Range configuration")
        self.last_id = None
        self.last_ms = None
        self.last_price = None
        self.last_quantity = None
        self.recovery_required = False
        self.sequence = 0
        self.started_ms = None
        self.open = self.high = self.low = None
        self.volume = 0.0
        self.tick_count = 0
        self.bars = ()
        self.fast = self.slow = None
        self.last_evaluated = 0

    @property
    def next_id(self):
        return self.last_id + 1 if self.last_id is not None else None

    def latest_tick(self):
        if self.last_id is None:
            return None
        return {"time_ms": self.last_ms, "price": self.last_price}

    def _close_for(self, tick):
        if self.open is None:
            self.started_ms = tick.time_ms
            self.open = self.high = self.low = tick.price
            self.volume, self.tick_count = tick.quantity, 1
            return []
        self.high, self.low = max(self.high, tick.price), min(self.low, tick.price)
        completed = []
        while True:
            if len(completed) >= MAX_RANGE_BARS_PER_TICK:
                raise ValueError("Range tick crosses too many bars")
            step = self.open * self.config.range_bps / 10000
            if tick.price >= self.open + step:
                close = self.open + step
            elif tick.price <= self.open - step:
                close = self.open - step
            else:
                break
            self.sequence += 1
            bar = RangeBar(self.sequence, self.started_ms, tick.time_ms, self.open,
                max(self.open, close), min(self.open, close), close,
                self.volume, self.tick_count, bool(completed))
            completed.append(bar)
            self.bars = (*self.bars, bar)[-60:]
            for name, span in (("fast", self.config.short), ("slow", self.config.long)):
                previous = getattr(self, name)
                alpha = 2 / (span + 1)
                setattr(self, name, close if previous is None else alpha * close + (1-alpha) * previous)
            self.started_ms = tick.time_ms
            self.open = self.high = self.low = close
            self.volume, self.tick_count = 0.0, 0
        self.high, self.low = max(self.high, tick.price), min(self.low, tick.price)
        self.volume += tick.quantity
        self.tick_count += 1
        return completed

    def accept_page(self, rows, *, now_ms: int, warmup=False):
        if type(now_ms) is not int or now_ms < 0 or type(warmup) is not bool or not isinstance(rows, list) or len(rows) > 1000:
            self.recovery_required = True
            raise ValueError("Invalid Range page request")
        staged = self.restore(self.checkpoint(), symbol=self.symbol, config=self.config)
        cold = staged.last_id is None
        results = []
        try:
            ticks = [AggregateTick.from_wire(row) for row in rows]
            for left, right in zip(ticks, ticks[1:]):
                if right.trade_id != left.trade_id + 1 or right.time_ms < left.time_ms:
                    raise ValueError("Non-contiguous Range trade page")
            for tick in ticks:
                if staged.last_id is not None and tick.trade_id <= staged.last_id:
                    if tick.trade_id == staged.last_id and (tick.time_ms != staged.last_ms or
                            tick.price != staged.last_price or tick.quantity != staged.last_quantity):
                        raise ValueError("Conflicting replay of latest Range trade")
                    continue
                if staged.last_id is not None and (tick.trade_id != staged.last_id + 1 or tick.time_ms < staged.last_ms):
                    raise ValueError("Missing Range trade or reversed time")
                completed = staged._close_for(tick)
                staged.last_id, staged.last_ms = tick.trade_id, tick.time_ms
                staged.last_price, staged.last_quantity = tick.price, tick.quantity
                fresh = not cold and not warmup and 0 <= now_ms - tick.time_ms <= 5000
                buy = sell = False
                reason = "waiting_range_close"
                if completed:
                    required = staged.config.long if staged.config.family == "ema" else staged.config.window
                    if staged.sequence < required:
                        reason = f"range_warmup:{staged.sequence}/{required}"
                    elif not fresh:
                        reason = "stale_range_close"
                    elif staged.last_evaluated != staged.sequence:
                        if staged.config.family == "ema":
                            buy = staged.fast > staged.slow * (1 + staged.config.entry_threshold)
                            sell = staged.fast <= staged.slow * (1 - staged.config.exit_threshold)
                        else:
                            center = median([bar.close for bar in staged.bars[-staged.config.window:]])
                            close = staged.bars[-1].close
                            buy = close < center * (1 - staged.config.deviation)
                            sell = close > center * (1 + staged.config.deviation)
                        reason = "range_" + staged.config.family + "_close"
                    staged.last_evaluated = staged.sequence
                results.append(RangeObservation(tick, fresh, buy and not staged.recovery_required,
                    sell, reason, staged.sequence, len(completed)))
        except ValueError:
            self.recovery_required = True
            raise
        self.__dict__.update(staged.__dict__)
        return tuple(results)

    def checkpoint(self):
        return {"version": 1, "symbol": self.symbol, "config": asdict(self.config),
            "last_id": self.last_id, "last_ms": self.last_ms, "last_price": self.last_price,
            "last_quantity": self.last_quantity,
            "recovery_required": self.recovery_required,
            "sequence": self.sequence, "started_ms": self.started_ms, "open": self.open,
            "high": self.high, "low": self.low, "volume": self.volume, "tick_count": self.tick_count,
            "bars": [asdict(bar) for bar in self.bars], "fast": self.fast, "slow": self.slow,
            "last_evaluated": self.last_evaluated}

    @classmethod
    def restore(cls, payload, *, symbol, config):
        expected = set(cls(symbol, config).checkpoint())
        if (not isinstance(payload, dict) or set(payload) != expected or
                type(payload["version"]) is not int or payload["version"] != 1 or payload["symbol"] != symbol):
            raise ValueError("Invalid Range checkpoint identity")
        raw_config = payload["config"]
        if not isinstance(raw_config, dict) or set(raw_config) != set(asdict(RangeStrategyConfig())) or RangeStrategyConfig(**raw_config) != config:
            raise ValueError("Range checkpoint configuration mismatch")
        instance = cls(symbol, config)
        for name in ("last_id", "last_ms", "sequence", "started_ms", "tick_count", "last_evaluated"):
            value = payload[name]
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Invalid Range checkpoint integer")
            setattr(instance, name, value)
        if (instance.last_id is None) != (instance.last_ms is None) or instance.last_evaluated > instance.sequence:
            raise ValueError("Incomplete Range cursor/generation")
        if type(payload["recovery_required"]) is not bool:
            raise ValueError("Invalid Range recovery marker")
        instance.recovery_required = payload["recovery_required"]
        numbers = ("last_price", "last_quantity", "open", "high", "low", "volume", "fast", "slow")
        for name in numbers:
            value = payload[name]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value)):
                raise ValueError("Invalid Range checkpoint number")
            setattr(instance, name, value)
        if ((instance.last_id is None) != (instance.last_price is None) or
                (instance.last_id is None) != (instance.last_quantity is None) or
                (instance.last_price is not None and instance.last_price <= 0) or
                (instance.last_quantity is not None and instance.last_quantity < 0)):
            raise ValueError("Incomplete Range latest price")
        if (instance.open is None) != (instance.started_ms is None) or (instance.open is None) != (instance.high is None) or (instance.open is None) != (instance.low is None):
            raise ValueError("Incomplete Range partial bar")
        if (instance.open is None and (instance.volume != 0 or instance.tick_count != 0)) or (
                instance.open is not None and (instance.tick_count < 1 or instance.volume < 0 or
                instance.low > min(instance.open, instance.last_price) or
                instance.high < max(instance.open, instance.last_price) or instance.started_ms > instance.last_ms)):
            raise ValueError("Inconsistent Range partial bar")
        instance.volume = payload["volume"]
        raw_bars = payload["bars"]
        if not isinstance(raw_bars, list) or len(raw_bars) > 60:
            raise ValueError("Invalid Range history size")
        bars = tuple(RangeBar(**row) for row in raw_bars if isinstance(row, dict) and set(row) == set(asdict(RangeBar(1,0,0,1,1,1,1,0,0,False))))
        if len(bars) != len(raw_bars) or any(b.sequence != a.sequence + 1 for a,b in zip(bars,bars[1:])):
            raise ValueError("Invalid Range bar history")
        if bars and (bars[-1].sequence != instance.sequence or len(bars) > instance.sequence):
            raise ValueError("Range sequence/history mismatch")
        if bars and instance.started_ms < bars[-1].closed_ms:
            raise ValueError("Range history/partial time mismatch")
        instance.bars = bars
        if instance.sequence and (not bars or instance.fast is None or instance.slow is None):
            raise ValueError("Missing Range EMA checkpoint")
        if not instance.sequence and (bars or instance.fast is not None or instance.slow is not None or instance.last_evaluated):
            raise ValueError("Unexpected empty Range features")
        return instance
