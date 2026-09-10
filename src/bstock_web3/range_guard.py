"""Alpha2-compatible guarded Range Median over fixed Range bars and closed 1m context."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math

from .range_ticks import RANGE_BPS, RANGE_MEDIAN_WINDOWS, RangeStrategyConfig, RangeTickStream


@dataclass(frozen=True)
class GuardedRangeMedianConfig:
    range_bps: int = 20
    window: int = 60
    deviation: float = .002
    guard_short: int = 20
    guard_long: int = 50
    dynamic_stop_multiplier: float = 3.0
    dynamic_stop_floor: float = .01
    dynamic_stop_cap: float = .05
    dynamic_stop_requires_ema: bool = True
    dynamic_stop_ema_short: int = 20
    dynamic_stop_ema_long: int = 50
    dynamic_stop_ema_mode: str = "below"
    dynamic_stop_drawdown_window: int = 0
    dynamic_stop_drawdown_multiple: float = 1.0
    dynamic_stop_drawdown_floor: float = 0.0
    entry_guard_drawdown_window: int = 0
    entry_guard_drawdown_multiple: float = 1.0
    entry_guard_drawdown_floor: float = 0.0
    catastrophe_stop_multiplier: float | None = None
    catastrophe_stop_floor: float = .02
    catastrophe_stop_cap: float = .08
    stop_loss_cooldown_seconds: int = 900

    def __post_init__(self):
        if self.range_bps not in RANGE_BPS or self.window not in RANGE_MEDIAN_WINDOWS:
            raise ValueError("Unsupported guarded Range size/window")
        for short, long in ((self.guard_short, self.guard_long),
                            (self.dynamic_stop_ema_short, self.dynamic_stop_ema_long)):
            if type(short) is not int or type(long) is not int or not 2 <= short < long <= 200:
                raise ValueError("Guard EMA spans must satisfy 2 <= short < long <= 200")
        fractions = (self.deviation, self.dynamic_stop_floor, self.dynamic_stop_cap,
            self.dynamic_stop_drawdown_floor, self.entry_guard_drawdown_floor,
            self.catastrophe_stop_floor, self.catastrophe_stop_cap)
        multipliers = (self.dynamic_stop_multiplier, self.dynamic_stop_drawdown_multiple,
            self.entry_guard_drawdown_multiple)
        if any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) or v < 0 or v >= 1 for v in fractions):
            raise ValueError("Guard fractions must be finite values below one")
        if self.deviation <= 0 or self.dynamic_stop_floor <= 0 or self.dynamic_stop_cap < self.dynamic_stop_floor:
            raise ValueError("Invalid dynamic stop bounds")
        if any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) or v <= 0 for v in multipliers):
            raise ValueError("Guard multipliers must be positive")
        if self.catastrophe_stop_multiplier is not None and (isinstance(self.catastrophe_stop_multiplier, bool) or
                not isinstance(self.catastrophe_stop_multiplier, (int,float)) or
                not math.isfinite(self.catastrophe_stop_multiplier) or self.catastrophe_stop_multiplier <= 0):
            raise ValueError("Invalid catastrophe multiplier")
        if self.catastrophe_stop_cap < self.catastrophe_stop_floor:
            raise ValueError("Invalid catastrophe stop bounds")
        if self.dynamic_stop_ema_mode not in ("below", "confirmed_down"):
            raise ValueError("Invalid dynamic stop EMA mode")
        for value in (self.dynamic_stop_drawdown_window, self.entry_guard_drawdown_window,
                      self.stop_loss_cooldown_seconds):
            if type(value) is not int or value < 0 or value > 100000:
                raise ValueError("Invalid guard window/cooldown")


def minute_guard_context(snapshot):
    """Derive causal features from completed 1m candles only."""
    bars = tuple(snapshot.one_minute) if snapshot is not None else ()
    closes = [float(bar.close) for bar in bars]
    result = {}
    spans = (15, 20, 45, 50)
    for span in spans:
        if len(closes) < span + 1:
            continue
        alpha = 2 / (span + 1)
        value = closes[0]
        previous = None
        for close in closes[1:]:
            previous = value
            value = alpha * close + (1-alpha) * value
        result[f"minute_ema_{span}"] = value
        result[f"minute_ema_{span}_previous"] = previous
    if len(bars) >= 60:
        amplitudes = sorted(float(bar.high) / float(bar.low) - 1 for bar in bars[-60:] if bar.low > 0)
        if amplitudes:
            index = max(0, math.ceil(.9 * len(amplitudes)) - 1)
            result["minute_amplitude_p90_60"] = amplitudes[index]
    for window in (15, 30, 60):
        if len(closes) >= window:
            tail = closes[-window:]
            peak = max(tail)
            result[f"minute_drawdown_{window}"] = 0.0 if peak <= 0 else max(0.0, peak-tail[-1]) / peak
    return result


class GuardedRangeMedianStream:
    def __init__(self, symbol: str, config: GuardedRangeMedianConfig | None = None):
        self.symbol = symbol
        self.config = config or GuardedRangeMedianConfig()
        if not isinstance(self.config, GuardedRangeMedianConfig):
            raise ValueError("Invalid guarded Range configuration")
        self.base = RangeTickStream(symbol, RangeStrategyConfig(family="median",
            range_bps=self.config.range_bps, window=self.config.window,
            deviation=self.config.deviation))

    @property
    def next_id(self): return self.base.next_id

    @property
    def recovery_required(self): return self.base.recovery_required

    @recovery_required.setter
    def recovery_required(self, value):
        if type(value) is not bool:
            raise ValueError("Invalid recovery marker")
        self.base.recovery_required = value

    def latest_tick(self): return self.base.latest_tick()

    def accept_page(self, rows, *, now_ms: int, warmup=False, context=None):
        points = self.base.accept_page(rows, now_ms=now_ms, warmup=warmup)
        context = context or {}
        result = []
        for point in points:
            metadata = self._live_metadata(context)
            buy, reason = point.buy, point.reason
            if buy:
                guarded = self._entry_confirmed_down(context)
                if guarded is None:
                    buy, reason = False, "guarded_range_waiting_minute_ema"
                elif guarded:
                    buy, reason = False, f"entry_blocked:minute_ema{self.config.guard_short}_below_ema{self.config.guard_long}"
                else:
                    amplitude = context.get("minute_amplitude_p90_60")
                    if amplitude is None:
                        buy, reason = False, "guarded_range_waiting_volatility"
                    else:
                        locked = min(self.config.dynamic_stop_cap,
                            max(self.config.dynamic_stop_floor, float(amplitude) * self.config.dynamic_stop_multiplier))
                        metadata.update(locked_stop_loss=locked, locked_amplitude_p90=float(amplitude),
                            stop_loss_cooldown_seconds=self.config.stop_loss_cooldown_seconds)
                        if self.config.catastrophe_stop_multiplier is not None:
                            catastrophe = min(self.config.catastrophe_stop_cap,
                                max(self.config.catastrophe_stop_floor,
                                    float(amplitude) * self.config.catastrophe_stop_multiplier))
                            metadata["locked_catastrophe_stop_loss"] = max(locked, catastrophe)
            result.append(replace(point, buy=buy, reason=reason, strategy_params=metadata))
        return tuple(result)

    def _entry_confirmed_down(self, context):
        s, l = self.config.guard_short, self.config.guard_long
        try:
            short, long = float(context[f"minute_ema_{s}"]), float(context[f"minute_ema_{l}"])
            prior_short = float(context[f"minute_ema_{s}_previous"])
            prior_long = float(context[f"minute_ema_{l}_previous"])
        except (KeyError, TypeError, ValueError):
            return None
        confirmed = short < long and prior_short < prior_long and short <= prior_short and long <= prior_long
        if confirmed and self.config.entry_guard_drawdown_window:
            try:
                amplitude = float(context["minute_amplitude_p90_60"])
                drawdown = float(context[f"minute_drawdown_{self.config.entry_guard_drawdown_window}"])
            except (KeyError, TypeError, ValueError):
                return None
            confirmed = drawdown >= max(self.config.entry_guard_drawdown_floor,
                amplitude * self.config.entry_guard_drawdown_multiple)
        return confirmed

    def _live_metadata(self, context):
        s, l = self.config.dynamic_stop_ema_short, self.config.dynamic_stop_ema_long
        try:
            short, long = float(context[f"minute_ema_{s}"]), float(context[f"minute_ema_{l}"])
            ps, pl = float(context[f"minute_ema_{s}_previous"]), float(context[f"minute_ema_{l}_previous"])
            confirmed = short < long
            if self.config.dynamic_stop_ema_mode == "confirmed_down":
                confirmed = confirmed and ps < pl and short <= ps and long <= pl
            if confirmed and self.config.dynamic_stop_drawdown_window:
                amplitude = float(context["minute_amplitude_p90_60"])
                drawdown = float(context[f"minute_drawdown_{self.config.dynamic_stop_drawdown_window}"])
                required = max(self.config.dynamic_stop_drawdown_floor,
                    amplitude * self.config.dynamic_stop_drawdown_multiple)
                confirmed = drawdown >= required
            return {"dynamic_stop_ema_confirmed": confirmed,
                    "dynamic_stop_requires_ema": self.config.dynamic_stop_requires_ema}
        except (KeyError, TypeError, ValueError):
            return {"dynamic_stop_ema_confirmed": False,
                    "dynamic_stop_requires_ema": self.config.dynamic_stop_requires_ema}

    def checkpoint(self):
        return {"version": 1, "symbol": self.symbol, "config": asdict(self.config),
                "base": self.base.checkpoint()}

    @classmethod
    def restore(cls, payload, *, symbol, config):
        if (not isinstance(payload, dict) or set(payload) != {"version","symbol","config","base"} or
                type(payload["version"]) is not int or payload["version"] != 1 or payload["symbol"] != symbol or
                not isinstance(payload["config"], dict) or GuardedRangeMedianConfig(**payload["config"]) != config):
            raise ValueError("Invalid guarded Range checkpoint")
        instance = cls(symbol, config)
        instance.base = RangeTickStream.restore(payload["base"], symbol=symbol, config=instance.base.config)
        return instance
