"""Parallel Range selection strategies and BUY-only alpha2-style entry guards."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import math

from .range_ticks import RANGE_BPS, RANGE_MEDIAN_WINDOWS, RangeStrategyConfig, RangeTickStream
from .regime import EntryGuard, EntryGuardConfig, GuardAction, MarketRegimeDetector


@dataclass(frozen=True)
class RangeAutoConfig:
    ranges_bps: tuple[int, ...] = (10, 20, 30)
    short: int = 8
    long: int = 21
    entry_threshold: float = 0.0
    exit_threshold: float = 0.0

    def __post_init__(self):
        values = tuple(self.ranges_bps) if isinstance(self.ranges_bps, (tuple, list)) else ()
        object.__setattr__(self, "ranges_bps", values)
        if not values or len(values) != len(set(values)) or any(type(v) is not int or v not in RANGE_BPS for v in values):
            raise ValueError("Invalid automatic Range candidates")
        RangeStrategyConfig(range_bps=values[0], short=self.short, long=self.long,
            entry_threshold=self.entry_threshold, exit_threshold=self.exit_threshold)


@dataclass(frozen=True)
class RangeMedianCandidate:
    range_bps: int
    window: int
    deviation: float

    def __post_init__(self):
        RangeStrategyConfig(family="median", range_bps=self.range_bps,
            window=self.window, deviation=self.deviation)


@dataclass(frozen=True)
class RangeMedianAdaptiveConfig:
    candidates: tuple[RangeMedianCandidate, ...] = (
        RangeMedianCandidate(20, 20, .0035), RangeMedianCandidate(30, 60, .004))

    def __post_init__(self):
        raw = tuple(self.candidates) if isinstance(self.candidates, (tuple, list)) else ()
        values = tuple(item if isinstance(item, RangeMedianCandidate) else
            RangeMedianCandidate(**item) if isinstance(item, dict) else item for item in raw)
        object.__setattr__(self, "candidates", values)
        if (not values or any(not isinstance(v, RangeMedianCandidate) for v in values) or
                len({v.range_bps for v in values}) != len(values)):
            raise ValueError("Invalid adaptive Range Median candidates")


def _config_payload(config):
    return json.loads(json.dumps(asdict(config), allow_nan=False))


class _ParallelRangeStream:
    family = ""

    def __init__(self, symbol, config):
        self.symbol, self.config = symbol, config
        self.children = {item.range_bps: RangeTickStream(symbol, item) for item in self._strategies(config)}
        self.recovery_required = False
        self.last_selected_generation = {}

    @staticmethod
    def _strategies(config):
        raise NotImplementedError

    @property
    def next_id(self):
        cursors = {child.next_id for child in self.children.values()}
        if len(cursors) != 1:
            raise ValueError("Parallel Range cursors diverged")
        return next(iter(cursors))

    def latest_tick(self):
        ticks = [child.latest_tick() for child in self.children.values()]
        if any(tick != ticks[0] for tick in ticks[1:]):
            raise ValueError("Parallel Range latest ticks diverged")
        return ticks[0]

    def accept_page(self, rows, *, now_ms: int, warmup=False, context=None,
                    locked_strategy_params=None):
        staged = self.restore(self.checkpoint(), symbol=self.symbol, config=self.config)
        try:
            pages = {bps: child.accept_page(rows, now_ms=now_ms, warmup=warmup)
                     for bps, child in staged.children.items()}
            sizes = {len(points) for points in pages.values()}
            if len(sizes) != 1:
                raise ValueError("Parallel Range observations diverged")
            result = []
            for index in range(next(iter(sizes))):
                points = [pages[bps][index] for bps in staged.children]
                locked_bps = (locked_strategy_params or {}).get("selected_range_bps")
                if locked_bps is not None:
                    chosen = next((p for p in points if p.strategy_params.get("selected_range_bps") == locked_bps), None)
                    if chosen is None:
                        raise ValueError("Open position Range candidate is unavailable")
                else:
                    eligible = [p for p in points if "selection_score" in (p.strategy_params or {})]
                    chosen = max(eligible, key=lambda p: p.strategy_params["selection_score"]) if eligible else points[0]
                metadata = {**(chosen.strategy_params or {}), "selector": self.family}
                buy, sell = chosen.buy, chosen.sell
                if locked_bps is None and "selection_score" in metadata:
                    bps, generation = metadata["selected_range_bps"], chosen.generation
                    fresh_generation = staged.last_selected_generation.get(str(bps)) != generation
                    if self.family == "range_auto":
                        buy = fresh_generation and metadata["selected_fast"] > metadata["selected_slow"]
                        sell = fresh_generation and metadata["selected_fast"] <= metadata["selected_slow"]
                    else:
                        buy = fresh_generation and metadata["selection_score"] >= metadata["selected_deviation"]
                        sell = metadata["selected_close"] >= metadata["selected_median"]
                    staged.last_selected_generation[str(bps)] = generation
                result.append(replace(chosen, reason=(self.family + ":" + chosen.reason),
                    buy=buy and chosen.fresh and not warmup and not staged.recovery_required,
                    sell=sell and chosen.fresh and not warmup, strategy_params=metadata))
        except ValueError:
            self.recovery_required = True
            raise
        self.__dict__.update(staged.__dict__)
        return tuple(result)

    def checkpoint(self):
        return {"version": 1, "symbol": self.symbol, "config": _config_payload(self.config),
            "recovery_required": self.recovery_required,
            "last_selected_generation": self.last_selected_generation,
            "children": {str(key): value.checkpoint() for key, value in self.children.items()}}

    @classmethod
    def restore(cls, payload, *, symbol, config):
        if (not isinstance(payload, dict) or set(payload) != {"version","symbol","config","recovery_required","last_selected_generation","children"} or
                payload["version"] != 1 or payload["symbol"] != symbol or type(payload["recovery_required"]) is not bool):
            raise ValueError("Invalid parallel Range checkpoint")
        instance = cls(symbol, config)
        if payload["config"] != _config_payload(config) or set(payload["children"]) != {str(v) for v in instance.children}:
            raise ValueError("Parallel Range checkpoint configuration mismatch")
        instance.children = {bps: RangeTickStream.restore(payload["children"][str(bps)], symbol=symbol,
            config=child.config) for bps, child in instance.children.items()}
        generations = payload["last_selected_generation"]
        if (not isinstance(generations, dict) or any(k not in {str(v) for v in instance.children} or
                type(v) is not int or v < 0 for k,v in generations.items())):
            raise ValueError("Invalid automatic Range generations")
        instance.last_selected_generation = dict(generations)
        instance.recovery_required = payload["recovery_required"] or any(c.recovery_required for c in instance.children.values())
        instance.next_id
        return instance


class RangeAutoStream(_ParallelRangeStream):
    family = "range_auto"

    @staticmethod
    def _strategies(config):
        if not isinstance(config, RangeAutoConfig):
            raise ValueError("Invalid Range Auto configuration")
        return tuple(RangeStrategyConfig(range_bps=bps, short=config.short, long=config.long,
            entry_threshold=config.entry_threshold, exit_threshold=config.exit_threshold)
            for bps in config.ranges_bps)


class RangeMedianAdaptiveStream(_ParallelRangeStream):
    family = "range_median_adaptive"

    @staticmethod
    def _strategies(config):
        if not isinstance(config, RangeMedianAdaptiveConfig):
            raise ValueError("Invalid adaptive Range Median configuration")
        return tuple(RangeStrategyConfig(family="median", range_bps=item.range_bps,
            window=item.window, deviation=item.deviation) for item in config.candidates)


@dataclass(frozen=True)
class RangeEntryGuardConfig:
    fast_drop_30s: float = -.00075
    fast_drop_2m: float = -.00125
    trend_short: int = 15
    trend_long: int = 45

    def __post_init__(self):
        if not 2 <= self.trend_short < self.trend_long <= 200:
            raise ValueError("Invalid entry guard EMA spans")
        for value in (self.fast_drop_30s, self.fast_drop_2m):
            if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not -1 < value <= 0:
                raise ValueError("Invalid entry guard return threshold")


class GuardedRangeStream:
    """BUY-only guard around a fixed or automatic Range strategy."""

    def __init__(self, symbol, base_config, *, base_type=RangeTickStream,
                 guard_config=None):
        self.symbol, self.config = symbol, base_config
        self.base_type = base_type
        self.guard_config = guard_config or RangeEntryGuardConfig()
        self.base = base_type(symbol, base_config)
        self.recent_ticks = ()
        self.regime_detector = MarketRegimeDetector()

    @property
    def next_id(self): return self.base.next_id
    @property
    def recovery_required(self): return self.base.recovery_required
    @recovery_required.setter
    def recovery_required(self, value): self.base.recovery_required = value
    def latest_tick(self): return self.base.latest_tick()

    def accept_page(self, rows, *, now_ms: int, warmup=False, context=None,
                    locked_strategy_params=None):
        staged = GuardedRangeStream.restore(self.checkpoint(), symbol=self.symbol, config=self.config,
            base_type=self.base_type, guard_config=self.guard_config)
        try:
            points = staged.base.accept_page(rows, now_ms=now_ms, warmup=warmup, context=context,
                locked_strategy_params=locked_strategy_params)
        except ValueError:
            self.recovery_required = True
            raise
        result = []
        for point in points:
            staged.recent_ticks = tuple((ms, price) for ms, price in
                (*staged.recent_ticks, (point.tick.time_ms, point.tick.price))
                if point.tick.time_ms - ms <= 120000)
            snapshot = (context or {}).get("_snapshot")
            regime = staged.regime_detector.evaluate(snapshot) if snapshot is not None else None
            blocked = staged._blocked(context or {}, point.tick.time_ms, point.tick.price, regime)
            buy, reason = point.buy, point.reason
            if buy and blocked:
                buy, reason = False, "entry_blocked:" + blocked
            result.append(replace(point, buy=buy, reason=reason,
                strategy_params={**(point.strategy_params or {}), "entry_guard": "ema_and_fast_drop"}))
        self.__dict__.update(staged.__dict__)
        return tuple(result)

    def _blocked(self, context, now_ms, price, regime):
        guard = EntryGuard(EntryGuardConfig(self.guard_config.fast_drop_30s,
            self.guard_config.fast_drop_2m))
        result = guard.evaluate(price=price, now_ms=now_ms, regime=regime,
            ticks=self.recent_ticks)
        if result.action == GuardAction.BLOCK:
            return ",".join(result.reasons)
        if regime is not None:
            return ""
        s, l = self.guard_config.trend_short, self.guard_config.trend_long
        try:
            if (float(context[f"minute_ema_{s}"]) < float(context[f"minute_ema_{l}"]) and
                    float(context[f"minute_ema_{s}_previous"]) < float(context[f"minute_ema_{l}_previous"])):
                return f"minute_ema{s}_below_ema{l}"
        except (KeyError, TypeError, ValueError):
            # alpha2 allows when no regime snapshot exists; FastDrop stays active.
            return ""
        return ""

    def checkpoint(self):
        return {"version": 2, "symbol": self.symbol, "config": _config_payload(self.config),
            "guard_config": asdict(self.guard_config), "recent_ticks": [list(v) for v in self.recent_ticks],
            "regime": self.regime_detector.checkpoint(),
            "base": self.base.checkpoint()}

    @classmethod
    def restore(cls, payload, *, symbol, config, base_type=RangeTickStream, guard_config=None):
        guard_config = guard_config or RangeEntryGuardConfig()
        legacy = isinstance(payload,dict) and payload.get("version") == 1
        expected = {"version","symbol","config","guard_config","recent_ticks","base"} | (set() if legacy else {"regime"})
        if (not isinstance(payload, dict) or set(payload) != expected or
                payload["version"] not in (1,2) or payload["symbol"] != symbol or payload["config"] != _config_payload(config) or
                payload["guard_config"] != asdict(guard_config) or not isinstance(payload["recent_ticks"], list)):
            raise ValueError("Invalid guarded Range checkpoint")
        instance = cls(symbol, config, base_type=base_type, guard_config=guard_config)
        instance.base = base_type.restore(payload["base"], symbol=symbol, config=config)
        ticks = tuple(tuple(v) for v in payload["recent_ticks"])
        if any(len(v) != 2 or type(v[0]) is not int or v[0] < 0 or isinstance(v[1],bool) or
               not isinstance(v[1],(int,float)) or not math.isfinite(v[1]) or v[1] <= 0 for v in ticks):
            raise ValueError("Invalid guarded Range tick history")
        instance.recent_ticks = ticks
        if not legacy:
            instance.regime_detector = MarketRegimeDetector.restore(payload["regime"])
        return instance


class GuardedRangeEmaStream(GuardedRangeStream):
    def __init__(self, symbol, config, guard_config=None):
        if not isinstance(config, RangeStrategyConfig) or config.family != "ema":
            raise ValueError("Guarded Range EMA requires EMA configuration")
        super().__init__(symbol, config, base_type=RangeTickStream, guard_config=guard_config)

    @classmethod
    def restore(cls, payload, *, symbol, config):
        return GuardedRangeStream.restore(payload, symbol=symbol, config=config,
            base_type=RangeTickStream, guard_config=RangeEntryGuardConfig())


class GuardedRangeAutoStream(GuardedRangeStream):
    def __init__(self, symbol, config, guard_config=None):
        super().__init__(symbol, config, base_type=RangeAutoStream, guard_config=guard_config)

    @classmethod
    def restore(cls, payload, *, symbol, config):
        return GuardedRangeStream.restore(payload, symbol=symbol, config=config,
            base_type=RangeAutoStream, guard_config=RangeEntryGuardConfig())
