from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from bstock_web3.catalog import BStockAsset
from bstock_web3.engine import BStockEngineConfig
from bstock_web3.market_data import MultiTimeframeSnapshot
from bstock_web3.models import Kline
from bstock_web3.regime import (EntryGuard, GuardAction, MarketRegimeDetector,
    RegimeDetectorConfig, RegimeState)
from bstock_web3.range_ticks import RangeStrategyConfig
from bstock_web3.strategy import MtfEmaConfig, PositionView
from bstock_web3.strategy_contract import CandleMarketInput, TradeMarketInput
from bstock_web3.strategy_registry import (ALL_PRODUCT_TAGS, StrategySpec,
    build_portable_strategy_runtime, build_strategy_runtime,
    compatible_strategy_ids, default_strategy_config, ensure_strategy_supports,
    strategy_ids, strategy_spec)


def snapshot(count=80, *, falling=False):
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    direction = -1 if falling else 1
    one = tuple(Kline(start+timedelta(minutes=i), 100+direction*i*.2,
        100.15+direction*i*.2, 99.85+direction*i*.2,
        100+direction*i*.2+(i%2)*.02, 1) for i in range(count))
    five = tuple(one[i] for i in range(4, count, 5))
    asset = BStockAsset("NVDA", "NVDAB", "fixture", "56", "NVDABUSDT", "1")
    return MultiTimeframeSnapshot(asset, one, five, one[-1].time+timedelta(minutes=1))


def test_registry_is_single_source_for_every_strategy_and_input_kind():
    assert strategy_ids() == ("mtf", "median", "range-ema", "range-median",
        "range-median-guarded", "range-ema-guarded", "range-auto",
        "range-guarded-auto", "range-median-adaptive")
    config = BStockEngineConfig()
    runtime = build_strategy_runtime(config, "NVDABUSDT")
    assert runtime.strategy_id == "mtf" and runtime.input_kind == "candles"
    result = runtime.evaluate(CandleMarketInput(snapshot()), PositionView())[0]
    assert result.strategy_id == "mtf" and result.input_kind == "candles"
    with pytest.raises(ValueError):
        runtime.evaluate(TradeMarketInput([], 0))
    assert strategy_spec("range-auto").input_kind == "aggregate-trades"


def test_every_tick_strategy_builds_through_the_same_contract():
    for strategy_id in strategy_ids()[1:]:
        config = replace(BStockEngineConfig(), strategy_kind=strategy_id,
            range_config=RangeStrategyConfig(family="median" if strategy_id == "range-median" else "ema"))
        runtime = build_strategy_runtime(config, "NVDABUSDT")
        assert runtime.strategy_id == strategy_id
        assert runtime.input_kind == "aggregate-trades"
        result = runtime.evaluate(TradeMarketInput([
            {"a":1,"T":1788955200000,"p":"100","q":"1"}], 1788955200000))[0]
        assert result.strategy_id == strategy_id and result.source_id == 1


def test_every_strategy_has_a_portable_factory_independent_of_engine_config():
    for strategy_id in strategy_ids():
        config = default_strategy_config(strategy_id)
        assert isinstance(config, strategy_spec(strategy_id).config_type)
        runtime = build_portable_strategy_runtime(strategy_id, "nvdabusdt", config)
        assert runtime.strategy_id == strategy_id
    with pytest.raises(ValueError, match="Invalid configuration"):
        build_portable_strategy_runtime("range-median", "NVDABUSDT",
            MtfEmaConfig())
    with pytest.raises(ValueError, match="requires Range family"):
        build_portable_strategy_runtime("range-median", "NVDABUSDT",
            RangeStrategyConfig(family="ema"))
    with pytest.raises(ValueError, match="symbol"):
        build_portable_strategy_runtime("mtf", "bad/symbol")
    with pytest.raises(ValueError, match="symbol"):
        build_portable_strategy_runtime("mtf", None)


def test_strategy_product_tags_are_registry_metadata_not_execution_copies():
    assert set(compatible_strategy_ids("SPOT")) == set(strategy_ids())
    assert set(compatible_strategy_ids("WEB3_SPOT")) == set(strategy_ids())
    assert set(compatible_strategy_ids("FUTURES")) == set(strategy_ids())
    assert all(spec.supported_products == ALL_PRODUCT_TAGS for spec in
        (strategy_spec(strategy_id) for strategy_id in strategy_ids()))
    futures_only = StrategySpec("funding-carry", "candles", "config", "Funding carry",
        supported_products=frozenset({"FUTURES"}))
    assert futures_only.supports("FUTURES") and not futures_only.supports("SPOT")
    ensure_strategy_supports("mtf", "SPOT")
    with pytest.raises(ValueError):
        compatible_strategy_ids("OPTIONS")
    with pytest.raises(ValueError, match="product tags"):
        StrategySpec("bad", "candles", "config", "Bad",
            supported_products=frozenset({"OPTIONS"}))


def test_regime_detector_is_causal_stateful_and_checkpointed():
    detector = MarketRegimeDetector(RegimeDetectorConfig(enter_confirmations=2))
    first = detector.evaluate(snapshot(79))
    second = detector.evaluate(snapshot(80))
    assert first.stable_state == RegimeState.UNKNOWN
    assert second.stable_state == RegimeState.UP_TREND
    restored = MarketRegimeDetector.restore(detector.checkpoint(), detector.config)
    assert restored.checkpoint() == detector.checkpoint()


def test_shared_entry_guard_blocks_regime_and_fast_drop_but_allows_unknown():
    detector = MarketRegimeDetector(RegimeDetectorConfig(enter_confirmations=2))
    detector.evaluate(snapshot(79, falling=True))
    regime = detector.evaluate(snapshot(80, falling=True))
    guard = EntryGuard()
    assert guard.evaluate(price=84, now_ms=120000, regime=regime, ticks=()).action == GuardAction.BLOCK
    assert guard.evaluate(price=99.8, now_ms=120000, regime=None,
        ticks=((0,100.0),)).reasons == ("fast_drop_30s", "fast_drop_120s")
    assert guard.evaluate(price=100, now_ms=120000, regime=None, ticks=()).action == GuardAction.ALLOW
