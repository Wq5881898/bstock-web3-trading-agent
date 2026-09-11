"""Single registry for every strategy; execution venues never own strategy copies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .median_ticks import MedianTickStream
from .range_auto import (GuardedRangeAutoStream, GuardedRangeEmaStream,
    RangeAutoStream, RangeMedianAdaptiveStream)
from .range_guard import GuardedRangeMedianStream
from .range_ticks import RangeTickStream
from .strategy import MtfEmaStrategy
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

    def __post_init__(self):
        if self.input_kind not in ("candles", "aggregate-trades"):
            raise ValueError("Invalid strategy input kind")
        if (not isinstance(self.supported_products, frozenset)
                or not self.supported_products
                or not self.supported_products <= ALL_PRODUCT_TAGS):
            raise ValueError("Invalid strategy product tags")

    def supports(self, product: ProductTag | str) -> bool:
        value = getattr(product, "value", product)
        return value in self.supported_products


STRATEGY_SPECS = (
    StrategySpec("mtf", "candles", "strategy_config", "MTF EMA"),
    StrategySpec("median", "aggregate-trades", "median_config", "Tick Median"),
    StrategySpec("range-ema", "aggregate-trades", "range_config", "Range EMA"),
    StrategySpec("range-median", "aggregate-trades", "range_config", "Range Median"),
    StrategySpec("range-median-guarded", "aggregate-trades", "guarded_range_config", "Range Median EMA/P90 Guarded", True),
    StrategySpec("range-ema-guarded", "aggregate-trades", "range_config", "Range EMA Guarded", True),
    StrategySpec("range-auto", "aggregate-trades", "range_auto_config", "Range Auto"),
    StrategySpec("range-guarded-auto", "aggregate-trades", "range_auto_config", "Range Guarded Auto", True),
    StrategySpec("range-median-adaptive", "aggregate-trades", "range_adaptive_config", "Range Median Adaptive"),
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


def build_strategy_runtime(config, symbol: str):
    spec = strategy_spec(config.strategy_kind)
    selected = strategy_config(config)
    if spec.strategy_id == "mtf":
        return CandleStrategyRuntime(spec.strategy_id, MtfEmaStrategy(selected))
    stream_types = {
        "median": MedianTickStream,
        "range-ema": RangeTickStream,
        "range-median": RangeTickStream,
        "range-median-guarded": GuardedRangeMedianStream,
        "range-ema-guarded": GuardedRangeEmaStream,
        "range-auto": RangeAutoStream,
        "range-guarded-auto": GuardedRangeAutoStream,
        "range-median-adaptive": RangeMedianAdaptiveStream,
    }
    return TickStrategyRuntime(spec.strategy_id, stream_types[spec.strategy_id](symbol, selected))
