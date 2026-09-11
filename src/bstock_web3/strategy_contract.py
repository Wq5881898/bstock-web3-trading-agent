"""Venue-neutral strategy contract shared by candle and tick strategies."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from .strategy import PositionView, SignalDecision

InputKind = Literal["candles", "aggregate-trades"]


@dataclass(frozen=True)
class CandleMarketInput:
    snapshot: object


@dataclass(frozen=True)
class TradeMarketInput:
    rows: list
    now_ms: int
    warmup: bool = False
    context: dict | None = None


@dataclass(frozen=True)
class StrategyEvaluation:
    strategy_id: str
    input_kind: InputKind
    fresh: bool
    buy: bool
    sell: bool
    reason: str
    price: float | None
    observed_ms: int | None
    source_id: int | str | None
    strategy_params: dict = field(default_factory=dict)
    trend_spread: float | None = None
    expected_edge: float | None = None

    def decision(self, position: PositionView | None = None) -> SignalDecision:
        position = position or PositionView()
        action = "sell" if position.holding and self.sell else "buy" if not position.holding and self.buy else "hold"
        signal_time = None
        if self.observed_ms is not None:
            from datetime import datetime, timezone
            signal_time = datetime.fromtimestamp(self.observed_ms / 1000, timezone.utc).isoformat()
        elif isinstance(self.source_id, str):
            signal_time = self.source_id
        return SignalDecision(action, self.reason, self.price, signal_time,
            self.trend_spread, self.expected_edge, self.strategy_id,
            dict(self.strategy_params))


@runtime_checkable
class StrategyRuntime(Protocol):
    strategy_id: str
    input_kind: InputKind

    def evaluate(self, market, position: PositionView | None = None,
                 locked_strategy_params: dict | None = None) -> tuple[StrategyEvaluation, ...]: ...


class CandleStrategyRuntime:
    input_kind: InputKind = "candles"

    def __init__(self, strategy_id: str, strategy):
        self.strategy_id, self.strategy = strategy_id, strategy

    def evaluate(self, market, position=None, locked_strategy_params=None):
        if not isinstance(market, CandleMarketInput):
            raise ValueError("Candle strategy requires CandleMarketInput")
        decision = self.strategy.evaluate(market.snapshot, position)
        stamp = decision.signal_bar_time
        evaluation = StrategyEvaluation(self.strategy_id, self.input_kind, True,
            decision.action == "buy", decision.action == "sell", decision.reason,
            decision.price, None, stamp, dict(decision.strategy_params),
            decision.trend_spread, decision.expected_edge)
        return (evaluation,)


class TickStrategyRuntime:
    input_kind: InputKind = "aggregate-trades"

    def __init__(self, strategy_id: str, stream):
        self.strategy_id, self.stream = strategy_id, stream

    def evaluate(self, market, position=None, locked_strategy_params=None):
        if not isinstance(market, TradeMarketInput):
            raise ValueError("Tick strategy requires TradeMarketInput")
        points = self.stream.accept_page(market.rows, now_ms=market.now_ms,
            warmup=market.warmup, context=market.context,
            locked_strategy_params=locked_strategy_params)
        return tuple(StrategyEvaluation(self.strategy_id, self.input_kind,
            point.fresh, point.buy, point.sell, point.reason, float(point.tick.price),
            point.tick.time_ms, point.tick.trade_id,
            dict(getattr(point, "strategy_params", None) or {})) for point in points)

    @property
    def next_id(self): return self.stream.next_id
    @property
    def recovery_required(self): return self.stream.recovery_required
    @recovery_required.setter
    def recovery_required(self, value): self.stream.recovery_required = value
    def latest_tick(self): return self.stream.latest_tick()
    def checkpoint(self): return self.stream.checkpoint()


def evaluate_tick_stream(strategy_id, stream, market, *, position=None,
                         locked_strategy_params=None):
    """Small adapter for transactional sessions that persist the native stream."""
    return TickStrategyRuntime(strategy_id, stream).evaluate(market, position,
        locked_strategy_params)
