"""Single registry for every strategy; execution venues never own strategy copies."""
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
import re
from typing import Callable, Literal

from .median_ticks import MedianTickStream, TickMedianConfig
from .range_auto import (GuardedRangeAutoStream, GuardedRangeEmaStream,
    RangeAutoConfig, RangeAutoStream, RangeMedianAdaptiveConfig,
    RangeMedianAdaptiveStream)
from .range_guard import (GuardedRangeMedianConfig, GuardedRangeMedianStream)
from .range_ticks import RangeStrategyConfig, RangeTickStream
from .strategy import MtfEmaConfig, MtfEmaStrategy
from .strategy_contract import CandleStrategyRuntime, TickStrategyRuntime

ProductTag = Literal["SPOT", "WEB3_SPOT", "FUTURES"]
ALL_PRODUCT_TAGS: frozenset[ProductTag] = frozenset({"SPOT", "WEB3_SPOT", "FUTURES"})


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    input_kind: str
    config_field: str
    label: str
    guarded: bool = False
    supported_products: frozenset[ProductTag] = ALL_PRODUCT_TAGS
    config_type: type | None = None
    default_config_factory: Callable[[], object] | None = None
    runtime_factory: Callable[[str, str, object], object] | None = None

    def __post_init__(self):
        if self.input_kind not in ("candles", "aggregate-trades"):
            raise ValueError("Invalid strategy input kind")
        if (not isinstance(self.supported_products, frozenset)
                or not self.supported_products
                or not self.supported_products <= ALL_PRODUCT_TAGS):
            raise ValueError("Invalid strategy product tags")
        portability = (self.config_type, self.default_config_factory,
            self.runtime_factory)
        if any(item is not None for item in portability) and any(
                item is None for item in portability):
            raise ValueError("Incomplete portable strategy factory")
        if self.config_type is not None and (not isinstance(self.config_type, type)
                or not callable(self.default_config_factory)
                or not callable(self.runtime_factory)):
            raise ValueError("Invalid portable strategy factory")

    def supports(self, product: ProductTag | str) -> bool:
        value = getattr(product, "value", product)
        return value in self.supported_products


def _candle_runtime(strategy_type, strategy_id, symbol, config):
    del symbol
    return CandleStrategyRuntime(strategy_id, strategy_type(config))


def _tick_runtime(stream_type, strategy_id, symbol, config, *, family=None):
    if family is not None and getattr(config, "family", None) != family:
        raise ValueError(f"Strategy {strategy_id!r} requires Range family {family!r}")
    return TickStrategyRuntime(strategy_id, stream_type(symbol, config))


STRATEGY_SPECS = (
    StrategySpec("mtf", "candles", "strategy_config", "MTF EMA",
        config_type=MtfEmaConfig, default_config_factory=MtfEmaConfig,
        runtime_factory=partial(_candle_runtime, MtfEmaStrategy)),
    StrategySpec("median", "aggregate-trades", "median_config", "Tick Median",
        config_type=TickMedianConfig, default_config_factory=TickMedianConfig,
        runtime_factory=partial(_tick_runtime, MedianTickStream)),
    StrategySpec("range-ema", "aggregate-trades", "range_config", "Range EMA",
        config_type=RangeStrategyConfig,
        default_config_factory=partial(RangeStrategyConfig, family="ema"),
        runtime_factory=partial(_tick_runtime, RangeTickStream, family="ema")),
    StrategySpec("range-median", "aggregate-trades", "range_config", "Range Median",
        config_type=RangeStrategyConfig,
        default_config_factory=partial(RangeStrategyConfig, family="median"),
        runtime_factory=partial(_tick_runtime, RangeTickStream, family="median")),
    StrategySpec("range-median-guarded", "aggregate-trades", "guarded_range_config", "Range Median EMA/P90 Guarded", True,
        config_type=GuardedRangeMedianConfig,
        default_config_factory=GuardedRangeMedianConfig,
        runtime_factory=partial(_tick_runtime, GuardedRangeMedianStream)),
    StrategySpec("range-ema-guarded", "aggregate-trades", "range_config", "Range EMA Guarded", True,
        config_type=RangeStrategyConfig,
        default_config_factory=partial(RangeStrategyConfig, family="ema"),
        runtime_factory=partial(_tick_runtime, GuardedRangeEmaStream, family="ema")),
    StrategySpec("range-auto", "aggregate-trades", "range_auto_config", "Range Auto",
        config_type=RangeAutoConfig, default_config_factory=RangeAutoConfig,
        runtime_factory=partial(_tick_runtime, RangeAutoStream)),
    StrategySpec("range-guarded-auto", "aggregate-trades", "range_auto_config", "Range Guarded Auto", True,
        config_type=RangeAutoConfig, default_config_factory=RangeAutoConfig,
        runtime_factory=partial(_tick_runtime, GuardedRangeAutoStream)),
    StrategySpec("range-median-adaptive", "aggregate-trades", "range_adaptive_config", "Range Median Adaptive",
        config_type=RangeMedianAdaptiveConfig,
        default_config_factory=RangeMedianAdaptiveConfig,
        runtime_factory=partial(_tick_runtime, RangeMedianAdaptiveStream)),
)
_BY_ID = {item.strategy_id: item for item in STRATEGY_SPECS}


def strategy_spec(strategy_id: str) -> StrategySpec:
    try:
        return _BY_ID[strategy_id]
    except (KeyError, TypeError) as exc:
        raise ValueError("Unknown strategy") from exc


def strategy_ids():
    return tuple(_BY_ID)


def compatible_strategy_ids(product: ProductTag | str):
    """Return strategies that may produce orders for a product type."""
    value = getattr(product, "value", product)
    if value not in ALL_PRODUCT_TAGS:
        raise ValueError("Unknown product tag")
    return tuple(item.strategy_id for item in STRATEGY_SPECS if item.supports(value))


def ensure_strategy_supports(strategy_id: str, product: ProductTag | str) -> None:
    if not strategy_spec(strategy_id).supports(product):
        value = getattr(product, "value", product)
        raise ValueError(f"Strategy {strategy_id!r} does not support product {value!r}")


def strategy_config(config):
    spec = strategy_spec(config.strategy_kind)
    return getattr(config, spec.config_field)


def default_strategy_config(strategy_id: str):
    spec = strategy_spec(strategy_id)
    if spec.default_config_factory is None:
        raise ValueError("Strategy has no portable configuration factory")
    return spec.default_config_factory()


def build_portable_strategy_runtime(strategy_id: str, symbol: str, config=None):
    """Build any strategy without an engine, UI, MCP or wallet configuration."""
    spec = strategy_spec(strategy_id)
    if not isinstance(symbol, str):
        raise ValueError("Invalid market symbol")
    normalized_symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,32}", normalized_symbol):
        raise ValueError("Invalid market symbol")
    selected = default_strategy_config(strategy_id) if config is None else config
    if spec.config_type is None or not isinstance(selected, spec.config_type):
        raise ValueError(f"Invalid configuration for strategy {strategy_id!r}")
    if spec.runtime_factory is None:
        raise ValueError("Strategy has no portable runtime factory")
    return spec.runtime_factory(spec.strategy_id, normalized_symbol, selected)


def build_strategy_runtime(config, symbol: str):
    """Compatibility adapter for this application's BStockEngineConfig."""
    return build_portable_strategy_runtime(config.strategy_kind, symbol,
        strategy_config(config))
