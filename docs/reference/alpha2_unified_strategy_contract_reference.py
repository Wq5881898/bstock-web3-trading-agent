"""Reference only: proposed Alpha2 unified strategy boundary.

This file is deliberately dependency-free and is not imported by the current
application. Copy the design into Alpha2 incrementally; do not make this file a
second production strategy engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, runtime_checkable


class InputKind(StrEnum):
    FEATURES = "FEATURES"
    CANDLES = "CANDLES"
    AGGREGATE_TRADES = "AGGREGATE_TRADES"


class MarketType(StrEnum):
    ALPHA = "ALPHA"
    SPOT = "SPOT"
    BSTOCK = "BSTOCK"


class ProductType(StrEnum):
    PAPER = "PAPER"
    SPOT = "SPOT"
    WEB3_SPOT = "WEB3_SPOT"
    FUTURES = "FUTURES"


@dataclass(frozen=True)
class PositionView:
    quantity: Decimal = Decimal("0")
    entry_price: Decimal = Decimal("0")
    locked_strategy_type: str = ""
    locked_strategy_params: Mapping[str, Any] = field(default_factory=dict)

    @property
    def holding(self) -> bool:
        return self.quantity > 0


@dataclass(frozen=True)
class StrategyContext:
    """Normalized input. Providers and executors must stay outside this model."""

    symbol: str
    observed_at_ms: int
    price: Decimal
    features: Mapping[str, Any]
    position: PositionView = PositionView()
    candles: object | None = None
    trades: tuple[object, ...] = ()


@dataclass(frozen=True)
class UnifiedStrategyDecision:
    buy: bool = False
    sell: bool = False
    reason: str = ""
    version: str = ""
    strategy_type: str = ""
    strategy_params: Mapping[str, Any] = field(default_factory=dict)
    trailing_stop: Decimal | None = None
    entry_guard_allowed: bool = False
    source_id: int | str | None = None


@runtime_checkable
class StrategyPlugin(Protocol):
    def evaluate(self, context: StrategyContext) -> UnifiedStrategyDecision: ...
    def checkpoint(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_type: str
    label: str
    input_kind: InputKind
    supported_markets: frozenset[MarketType]
    supported_products: frozenset[ProductType]
    required_features: Callable[[Mapping[str, Any]], frozenset[str]]
    factory: Callable[[Mapping[str, Any], str], StrategyPlugin]
    implementation_version: str
    category: str = ""

    def supports(self, market: MarketType, product: ProductType) -> bool:
        return market in self.supported_markets and product in self.supported_products


class StrategyRegistry:
    def __init__(self, definitions: tuple[StrategyDefinition, ...]):
        by_type = {item.strategy_type: item for item in definitions}
        if len(by_type) != len(definitions):
            raise ValueError("Duplicate strategy_type")
        self._definitions = MappingProxyType(by_type)

    def get(self, strategy_type: str) -> StrategyDefinition:
        try:
            return self._definitions[strategy_type]
        except KeyError as exc:
            raise ValueError(f"Unknown strategy type: {strategy_type}") from exc

    def compatible(self, market: MarketType, product: ProductType):
        return tuple(item for item in self._definitions.values()
                     if item.supports(market, product))

    def build(self, strategy_type: str, params: Mapping[str, Any], symbol: str):
        return self.get(strategy_type).factory(dict(params), symbol)


class LegacyRuntimeAdapter:
    """Temporary bridge: preserve Alpha2 decisions while callers migrate."""

    def __init__(self, legacy_runtime):
        self.legacy_runtime = legacy_runtime

    def evaluate(self, context: StrategyContext) -> UnifiedStrategyDecision:
        locked = context.position.locked_strategy_params
        result = self.legacy_runtime.on_market(
            dict(context.features),
            float(context.price),
            locked_strategy_type=context.position.locked_strategy_type,
            locked_strategy_params=dict(locked),
        )
        return UnifiedStrategyDecision(
            buy=result.buy,
            sell=result.sell,
            reason=result.reason,
            version=result.version,
            strategy_type=result.strategy_type,
            strategy_params=dict(result.strategy_params),
            trailing_stop=result.trailing_stop,
            entry_guard_allowed=result.entry_guard_allowed,
        )

    def checkpoint(self) -> Mapping[str, Any]:
        # Alpha2 must explicitly persist freshness generations/adaptive state.
        # Returning an empty checkpoint is acceptable only during the adapter's
        # first parity phase when the legacy owner already persists that state.
        return {}


def assert_compatible(definition: StrategyDefinition, *, market, product) -> None:
    if not definition.supports(market, product):
        raise ValueError(
            f"{definition.strategy_type} does not support {market.value}/{product.value}"
        )

