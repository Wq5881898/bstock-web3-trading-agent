from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

from .market_data import MultiTimeframeSnapshot
from .models import Kline


SignalAction = Literal["buy", "sell", "hold"]


@dataclass(frozen=True)
class MtfEmaConfig:
    trend_short: int = 8
    trend_long: int = 21
    entry_short: int = 8
    entry_long: int = 21
    atr_period: int = 14
    min_trend_spread: float = 0.0005
    min_expected_edge: float = 0.0025
    stop_loss: float = 0.004

    def __post_init__(self) -> None:
        for name in ("trend_short", "trend_long", "entry_short", "entry_long", "atr_period"):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= 1000:
                raise ValueError("Strategy periods must be integers in [1, 1000]")
        for name in ("min_trend_spread", "min_expected_edge", "stop_loss"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value < 1:
                raise ValueError("Strategy fractions must be finite and in [0, 1)")
        if self.stop_loss == 0:
            raise ValueError("Stop loss must be positive")
        if not 1 <= self.trend_short < self.trend_long:
            raise ValueError("5m EMA 参数必须满足 1 <= short < long")
        if not 1 <= self.entry_short < self.entry_long:
            raise ValueError("1m EMA 参数必须满足 1 <= short < long")
        if self.atr_period < 2:
            raise ValueError("ATR period 必须至少为 2")


@dataclass(frozen=True)
class PositionView:
    quantity: float = 0.0
    entry_price: float = 0.0

    @property
    def holding(self) -> bool:
        return self.quantity > 0


@dataclass(frozen=True)
class SignalDecision:
    action: SignalAction
    reason: str
    price: float | None
    signal_bar_time: str | None
    trend_spread: float | None = None
    expected_edge: float | None = None


class MtfEmaStrategy:
    def __init__(self, config: MtfEmaConfig | None = None) -> None:
        self.config = config or MtfEmaConfig()

    def evaluate(self, snapshot: MultiTimeframeSnapshot,
                 position: PositionView | None = None) -> SignalDecision:
        position = position or PositionView()
        signal_time = snapshot.signal_bar_time.isoformat() if snapshot.signal_bar_time else None
        required_1m = max(self.config.entry_long + 2, self.config.atr_period + 1)
        required_5m = max(self.config.trend_long + 1, self.config.atr_period + 1)
        if len(snapshot.one_minute) < required_1m or len(snapshot.five_minute) < required_5m:
            return SignalDecision("hold", "warming_up", None, signal_time)
        for bars, seconds in ((snapshot.one_minute, 60), (snapshot.five_minute, 300)):
            age = (snapshot.observed_at - bars[-1].time).total_seconds()
            if not seconds <= age < 2 * seconds:
                return SignalDecision("hold", "stale_or_unclosed_timeframe", None, signal_time)

        one = [float(row.close) for row in snapshot.one_minute]
        five = [float(row.close) for row in snapshot.five_minute]
        price = one[-1]
        fast_1 = ema_series(one, self.config.entry_short)
        slow_1 = ema_series(one, self.config.entry_long)
        fast_5 = ema_series(five, self.config.trend_short)[-1]
        slow_5 = ema_series(five, self.config.trend_long)[-1]
        spread = (fast_5 - slow_5) / price if price else 0.0
        edge = atr(snapshot.five_minute, self.config.atr_period) / price if price else 0.0
        cross_up = fast_1[-2] <= slow_1[-2] and fast_1[-1] > slow_1[-1]
        cross_down = fast_1[-2] >= slow_1[-2] and fast_1[-1] < slow_1[-1]

        if position.holding:
            if position.entry_price and price <= position.entry_price * (1 - self.config.stop_loss):
                return SignalDecision("sell", "fixed_stop_loss", price, signal_time, spread, edge)
            if fast_5 <= slow_5:
                return SignalDecision("sell", "five_minute_trend_reversed", price, signal_time, spread, edge)
            if cross_down:
                return SignalDecision("sell", "one_minute_cross_down", price, signal_time, spread, edge)
            return SignalDecision("hold", "holding_conditions_intact", price, signal_time, spread, edge)

        if fast_5 <= slow_5:
            reason = "five_minute_trend_not_bullish"
        elif spread < self.config.min_trend_spread:
            reason = "five_minute_trend_spread_too_small"
        elif edge < self.config.min_expected_edge:
            reason = "expected_edge_below_cost_gate"
        elif not cross_up:
            reason = "one_minute_cross_up_not_confirmed"
        else:
            return SignalDecision("buy", "mtf_ema_confirmed_entry", price, signal_time, spread, edge)
        return SignalDecision("hold", reason, price, signal_time, spread, edge)


def ema_series(values: list[float], span: int) -> list[float]:
    alpha = 2.0 / (span + 1.0)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1 - alpha) * result[-1])
    return result


def atr(bars: tuple[Kline, ...], period: int) -> float:
    rows = bars[-(period + 1):]
    ranges = [max(current.high - current.low, abs(current.high - previous.close),
                  abs(current.low - previous.close))
              for previous, current in zip(rows, rows[1:])]
    return sum(ranges) / len(ranges) if ranges else 0.0

