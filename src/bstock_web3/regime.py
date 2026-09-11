"""Venue-neutral market-regime classifier and reusable BUY entry guard.

Consumes the project's closed-candle snapshot plus normalized ticks. It owns no
exchange, wallet, order or position state, so Spot, Web3 and future derivatives
can share the same instance semantics.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import math


class RegimeState(StrEnum):
    UP_TREND = "UP_TREND"
    DOWN_TREND = "DOWN_TREND"
    RANGE = "RANGE"
    UP_BREAKOUT = "UP_BREAKOUT"
    DOWN_BREAKOUT = "DOWN_BREAKOUT"
    DISORDERED = "DISORDERED"
    UNKNOWN = "UNKNOWN"


class GuardAction(StrEnum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class RegimeDetectorConfig:
    minimum_1m_bars: int = 20
    trend_efficiency_enter: float = .55
    trend_efficiency_exit: float = .40
    trend_ema_spread_atr_enter: float = .35
    trend_ema_spread_atr_exit: float = .15
    trend_slope_atr_enter: float = .03
    range_efficiency_max: float = .35
    range_cross_count_min: int = 4
    breakout_distance_atr: float = .25
    breakout_vol_ratio_min: float = 1.30
    disordered_vol_ratio_min: float = 1.50
    minimum_real_bars_15m: int = 3
    stale_after_seconds: int = 300
    enter_confirmations: int = 3
    exit_confirmations: int = 2

    def __post_init__(self):
        integers = (self.minimum_1m_bars, self.range_cross_count_min,
            self.minimum_real_bars_15m, self.stale_after_seconds,
            self.enter_confirmations, self.exit_confirmations)
        if any(type(v) is not int or v <= 0 for v in integers):
            raise ValueError("Invalid regime integer")
        if self.minimum_1m_bars < 20:
            raise ValueError("Regime detector requires at least 20 one-minute bars")
        numbers = tuple(v for k,v in asdict(self).items() if k not in {
            "minimum_1m_bars", "range_cross_count_min", "minimum_real_bars_15m",
            "stale_after_seconds", "enter_confirmations", "exit_confirmations"})
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v < 0 for v in numbers):
            raise ValueError("Invalid regime threshold")


@dataclass(frozen=True)
class RegimeSnapshot:
    evaluated_at_ms: int
    stable_state: RegimeState
    candidate_state: RegimeState
    confidence: float
    reasons: tuple[str, ...]
    features: dict


@dataclass(frozen=True)
class EntryGuardConfig:
    fast_drop_30s: float = -.00075
    fast_drop_2m: float = -.00125

    def __post_init__(self):
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not -1 < v <= 0
               for v in (self.fast_drop_30s, self.fast_drop_2m)):
            raise ValueError("Invalid FastDrop threshold")


@dataclass(frozen=True)
class EntryGuardResult:
    action: GuardAction
    reasons: tuple[str, ...]
    features: dict


class MarketRegimeDetector:
    version = "rule-v1-venue-neutral"

    def __init__(self, config=None):
        self.config = config or RegimeDetectorConfig()
        self.stable_state = RegimeState.UNKNOWN
        self.pending_state = RegimeState.UNKNOWN
        self.candidate_count = 0
        self.exit_count = 0
        self.last_evaluated_ms = None
        self.latest = None

    def evaluate(self, snapshot):
        observed_ms = int(snapshot.observed_at.timestamp() * 1000)
        signal_ms = int(snapshot.signal_bar_time.timestamp() * 1000) if snapshot.signal_bar_time else None
        if signal_ms is not None and signal_ms == self.last_evaluated_ms and self.latest is not None:
            return self.latest
        candidate, reasons, features, confidence, immediate_unknown = self._classify(snapshot)
        stable = self._transition(candidate, immediate_unknown)
        features.update(transition_candidate_count=self.candidate_count,
            transition_exit_count=self.exit_count)
        self.last_evaluated_ms = signal_ms
        self.latest = RegimeSnapshot(observed_ms, stable, candidate, confidence,
            reasons, features)
        return self.latest

    def _classify(self, snapshot):
        bars, five, cfg = list(snapshot.one_minute), list(snapshot.five_minute), self.config
        if len(bars) < cfg.minimum_1m_bars:
            return RegimeState.UNKNOWN, ("insufficient_closed_1m_bars",), {"closed_1m_bars":len(bars)}, 0., False
        age = (snapshot.observed_at-bars[-1].time).total_seconds()
        if age > cfg.stale_after_seconds:
            return RegimeState.UNKNOWN, ("last_bar_is_stale",), {"last_bar_age_seconds":age}, 0., True
        real = sum(1 for bar in bars[-15:] if float(bar.volume) > 0)
        if real < cfg.minimum_real_bars_15m:
            return RegimeState.UNKNOWN, ("insufficient_real_bars_15m",), {"real_bars_15m":real}, 0., True
        closes = [float(v.close) for v in bars]
        atr = _atr(bars, 14)
        if atr is None or atr <= 0:
            return RegimeState.UNKNOWN, ("atr_unavailable",), {}, 0., False
        emas = {span:_ema(closes,span) for span in (5,10,15,20,30,40,45,50,60)}
        ema20s = _ema_series(closes,20)
        slope = _slope(ema20s[-10:]) / atr
        efficiency = _efficiency(closes[-21:])
        spread = (emas[20]-emas[60]) / atr
        returns = [b/a-1 for a,b in zip(closes,closes[1:]) if a]
        short_vol, long_vol = _std(returns[-10:]), _std(returns[-60:])
        vol_ratio = short_vol/long_vol if long_vol else 1.
        crossings = sum(1 for a,b,c,d in zip(closes[-20:-1],closes[-19:],ema20s[-20:-1],ema20s[-19:])
                        if (a-c)*(b-d) < 0)
        previous = bars[-21:-1]
        prior_high = max(float(v.high) for v in previous)
        prior_low = min(float(v.low) for v in previous)
        up_break, down_break = (closes[-1]-prior_high)/atr, (prior_low-closes[-1])/atr
        direction_5m = _background([float(v.close) for v in five])
        features = {"closed_1m_bars":len(bars), "closed_5m_bars":len(five),
            "real_bars_15m":real, "atr14":atr, **{f"ema{k}":v for k,v in emas.items()},
            "ema_spread_atr":spread, "ema20_slope_atr":slope,
            "efficiency_ratio_20":efficiency, "vol_ratio":vol_ratio,
            "cross_count_ema20":crossings, "up_break_distance_atr":up_break,
            "down_break_distance_atr":down_break, "direction_5m":direction_5m,
            "distance_ema20_atr":(closes[-1]-emas[20])/atr}
        if up_break >= cfg.breakout_distance_atr and vol_ratio >= cfg.breakout_vol_ratio_min:
            return RegimeState.UP_BREAKOUT, ("up_breakout_confirmed",), features, min(1.,up_break/cfg.breakout_distance_atr), False
        if down_break >= cfg.breakout_distance_atr and vol_ratio >= cfg.breakout_vol_ratio_min:
            return RegimeState.DOWN_BREAKOUT, ("down_breakout_confirmed",), features, min(1.,down_break/cfg.breakout_distance_atr), False
        if vol_ratio >= cfg.disordered_vol_ratio_min and spread*slope < 0:
            return RegimeState.DISORDERED, ("high_volatility_direction_conflict",), features, .5, False
        if efficiency >= cfg.trend_efficiency_enter and spread >= cfg.trend_ema_spread_atr_enter and slope >= cfg.trend_slope_atr_enter and direction_5m != "DOWN":
            return RegimeState.UP_TREND, ("up_trend_confirmed",), features, _trend_confidence(efficiency,spread,cfg), False
        if efficiency >= cfg.trend_efficiency_enter and spread <= -cfg.trend_ema_spread_atr_enter and slope <= -cfg.trend_slope_atr_enter and direction_5m != "UP":
            return RegimeState.DOWN_TREND, ("down_trend_confirmed",), features, _trend_confidence(efficiency,spread,cfg), False
        family = _family(self.stable_state)
        if family == "UP" and efficiency >= cfg.trend_efficiency_exit and spread >= cfg.trend_ema_spread_atr_exit and slope > 0 and direction_5m != "DOWN":
            return RegimeState.UP_TREND, ("up_trend_retained",), features, _trend_confidence(efficiency,spread,cfg), False
        if family == "DOWN" and efficiency >= cfg.trend_efficiency_exit and spread <= -cfg.trend_ema_spread_atr_exit and slope < 0 and direction_5m != "UP":
            return RegimeState.DOWN_TREND, ("down_trend_retained",), features, _trend_confidence(efficiency,spread,cfg), False
        if efficiency <= cfg.range_efficiency_max and crossings >= cfg.range_cross_count_min:
            return RegimeState.RANGE, ("range_confirmed",), features, min(1.,crossings/cfg.range_cross_count_min), False
        return RegimeState.UNKNOWN, ("structure_not_confirmed",), features, 0., False

    def _transition(self, observed, immediate=False):
        if observed == RegimeState.UNKNOWN and immediate:
            self.stable_state, self.pending_state = observed, observed
            self.candidate_count = self.exit_count = 0
        elif _family(observed) == _family(self.stable_state):
            if observed != RegimeState.UNKNOWN: self.stable_state = observed
            self.pending_state, self.candidate_count, self.exit_count = observed, 0, 0
        elif _family(observed) != _family(self.pending_state):
            self.pending_state, self.candidate_count = observed, 1
            self.exit_count = 1 if self.stable_state != RegimeState.UNKNOWN else 0
        else:
            self.candidate_count += 1
            if self.stable_state == RegimeState.UNKNOWN and self.candidate_count >= self.config.enter_confirmations:
                self.stable_state, self.candidate_count = observed, 0
            elif self.stable_state != RegimeState.UNKNOWN:
                self.exit_count += 1
                if self.exit_count >= self.config.exit_confirmations:
                    self.stable_state, self.candidate_count, self.exit_count = observed, 0, 0
        return self.stable_state

    def checkpoint(self):
        return {"version":1, "config":asdict(self.config), "stable_state":self.stable_state.value,
            "pending_state":self.pending_state.value, "candidate_count":self.candidate_count,
            "exit_count":self.exit_count, "last_evaluated_ms":self.last_evaluated_ms,
            "latest": None if self.latest is None else {
                "evaluated_at_ms":self.latest.evaluated_at_ms,
                "stable_state":self.latest.stable_state.value,
                "candidate_state":self.latest.candidate_state.value,
                "confidence":self.latest.confidence, "reasons":list(self.latest.reasons),
                "features":self.latest.features}}

    @classmethod
    def restore(cls, payload, config=None):
        config = config or RegimeDetectorConfig()
        if not isinstance(payload,dict) or set(payload) != {"version","config","stable_state","pending_state","candidate_count","exit_count","last_evaluated_ms","latest"} or payload["version"] != 1 or payload["config"] != asdict(config):
            raise ValueError("Invalid regime checkpoint")
        result = cls(config)
        result.stable_state, result.pending_state = RegimeState(payload["stable_state"]), RegimeState(payload["pending_state"])
        for key in ("candidate_count","exit_count"):
            if type(payload[key]) is not int or payload[key] < 0: raise ValueError("Invalid regime transition")
            setattr(result,key,payload[key])
        if payload["last_evaluated_ms"] is not None and (type(payload["last_evaluated_ms"]) is not int or payload["last_evaluated_ms"] < 0):
            raise ValueError("Invalid regime timestamp")
        result.last_evaluated_ms = payload["last_evaluated_ms"]
        latest = payload["latest"]
        if latest is not None:
            if not isinstance(latest,dict) or set(latest) != {"evaluated_at_ms","stable_state","candidate_state","confidence","reasons","features"}:
                raise ValueError("Invalid latest regime")
            evaluated_at_ms, confidence = latest["evaluated_at_ms"], latest["confidence"]
            if type(evaluated_at_ms) is not int or evaluated_at_ms < 0:
                raise ValueError("Invalid latest regime timestamp")
            if (isinstance(confidence,bool) or not isinstance(confidence,(int,float))
                    or not math.isfinite(confidence) or not 0 <= confidence <= 1):
                raise ValueError("Invalid latest regime confidence")
            if (not isinstance(latest["reasons"],list)
                    or not all(isinstance(reason,str) for reason in latest["reasons"])
                    or not isinstance(latest["features"],dict)):
                raise ValueError("Invalid latest regime details")
            latest_stable = RegimeState(latest["stable_state"])
            if latest_stable != result.stable_state:
                raise ValueError("Latest regime does not match stable state")
            result.latest = RegimeSnapshot(evaluated_at_ms, latest_stable,
                RegimeState(latest["candidate_state"]), float(confidence),
                tuple(latest["reasons"]), dict(latest["features"]))
        return result


class EntryGuard:
    def __init__(self, config=None): self.config = config or EntryGuardConfig()

    def evaluate(self, *, price, now_ms, regime, ticks):
        features, reasons = {}, []
        for seconds, limit in ((30,self.config.fast_drop_30s),(120,self.config.fast_drop_2m)):
            prior = next((p for ms,p in reversed(ticks) if ms <= now_ms-seconds*1000), None)
            value = None if prior is None else price/prior-1
            features[f"return_{seconds}s"] = value
            if value is not None and value <= limit: reasons.append(f"fast_drop_{seconds}s")
        if not reasons and regime is not None and regime.stable_state in {
                RegimeState.DOWN_TREND, RegimeState.DOWN_BREAKOUT, RegimeState.DISORDERED}:
            reasons.append("regime_"+regime.stable_state.value.lower())
        return EntryGuardResult(GuardAction.BLOCK if reasons else GuardAction.ALLOW,
            tuple(reasons), features)


def _ema_series(values, span):
    alpha, result = 2/(span+1), [values[0]]
    for value in values[1:]: result.append(alpha*value+(1-alpha)*result[-1])
    return result
def _ema(values, span): return _ema_series(values,span)[-1]
def _std(values):
    if not values: return 0.
    mean=sum(values)/len(values); return math.sqrt(sum((v-mean)**2 for v in values)/len(values))
def _efficiency(values):
    path=sum(abs(b-a) for a,b in zip(values,values[1:])); return abs(values[-1]-values[0])/path if path else 0.
def _slope(values):
    n=len(values); mean_x=(n-1)/2; mean_y=sum(values)/n
    denominator=sum((i-mean_x)**2 for i in range(n))
    return sum((i-mean_x)*(v-mean_y) for i,v in enumerate(values))/denominator if denominator else 0.
def _atr(bars, period):
    if len(bars) < period+1: return None
    values=[]
    for previous,current in zip(bars,bars[1:]):
        values.append(max(float(current.high)-float(current.low),abs(float(current.high)-float(previous.close)),abs(float(current.low)-float(previous.close))))
    alpha=1/period; result=values[0]
    for value in values[1:]: result=alpha*value+(1-alpha)*result
    return result
def _background(values):
    if len(values)<6:return "UNKNOWN"
    fast,slow=_ema(values,5),_ema(values,12)
    return "UP" if fast>slow else "DOWN" if fast<slow else "NEUTRAL"
def _family(state):
    if state in (RegimeState.UP_TREND,RegimeState.UP_BREAKOUT):return "UP"
    if state in (RegimeState.DOWN_TREND,RegimeState.DOWN_BREAKOUT):return "DOWN"
    return state.value
def _trend_confidence(efficiency,spread,cfg):
    return round(.5*min(1.,efficiency/cfg.trend_efficiency_enter)+.5*min(1.,abs(spread)/cfg.trend_ema_spread_atr_enter),4)
