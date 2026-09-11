from decimal import Decimal

import pytest

from bstock_web3.execution_contract import (ExecutionInstrument, PositionAction,
    ProductType, order_intent)
from bstock_web3.strategy import SignalDecision


def test_same_strategy_decision_maps_to_spot_web3_and_futures_without_strategy_copy():
    decision = SignalDecision("buy", "range_auto", 100, "x",
        strategy_id="range-auto", strategy_params={"selected_range_bps":20})
    for product in ProductType:
        instrument = ExecutionInstrument("NVDABUSDT", product, "BINANCE", "NVDAB", "USDT")
        intent = order_intent(decision, instrument)
        assert intent.action == PositionAction.OPEN_LONG
        assert intent.reference_price == Decimal("100")
        assert intent.strategy_id == "range-auto"
        assert intent.strategy_params == {"selected_range_bps":20}


def test_sell_is_reduce_only_and_hold_has_no_execution_intent():
    instrument = ExecutionInstrument("BTCUSDT", ProductType.FUTURES, "BINANCE", "BTC", "USDT")
    intent = order_intent(SignalDecision("sell", "exit", 99, "x", strategy_id="mtf"), instrument)
    assert intent.action == PositionAction.CLOSE_LONG and intent.reduce_only
    assert order_intent(SignalDecision("hold", "wait", None, None), instrument) is None


def test_executable_decision_must_identify_a_registered_strategy():
    instrument = ExecutionInstrument("BTCUSDT", ProductType.SPOT, "BINANCE", "BTC", "USDT")
    with pytest.raises(ValueError, match="registered strategy_id"):
        order_intent(SignalDecision("buy", "entry", 100, "x"), instrument)
