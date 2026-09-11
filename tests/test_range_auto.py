import json
from decimal import Decimal

import pytest

from bstock_web3.range_auto import (GuardedRangeAutoStream, RangeAutoConfig,
    RangeAutoStream, RangeMedianAdaptiveConfig, RangeMedianAdaptiveStream,
    RangeMedianCandidate)
from bstock_web3.engine import BStockEngineConfig
from bstock_web3.median_paper import RangePaperSession

BASE = 1788955200000


def row(i, price):
    return {"a": i, "T": BASE+i*1000, "p": str(price), "q": "1"}


def up_context():
    return {"minute_ema_15": 101, "minute_ema_45": 100,
        "minute_ema_15_previous": 100.5, "minute_ema_45_previous": 99.8}


@pytest.mark.parametrize("config", [
    lambda: RangeAutoConfig(()),
    lambda: RangeAutoConfig((20,20)),
    lambda: RangeAutoConfig((25,)),
    lambda: RangeMedianAdaptiveConfig((RangeMedianCandidate(20,20,.003),
        RangeMedianCandidate(20,60,.004))),
])
def test_auto_config_rejects_invalid_candidates(config):
    with pytest.raises(ValueError):
        config()


def test_auto_selects_strongest_range_and_open_position_locks_candidate():
    config = RangeAutoConfig((100,150), short=2, long=3)
    stream = RangeAutoStream("BTCUSDT", config)
    points = []
    for i, price in enumerate((100,102,104)):
        points.extend(stream.accept_page([row(i,price)], now_ms=BASE+i*1000))
    assert points[-1].buy and points[-1].strategy_params["selected_range_bps"] == 100
    locked = points[-1].strategy_params
    point = stream.accept_page([row(3,106)], now_ms=BASE+3000,
        locked_strategy_params=locked)[0]
    assert point.strategy_params["selected_range_bps"] == 100
    assert point.strategy_params["selector"] == "range_auto"


def test_median_adaptive_selects_candidate_and_checkpoint_round_trips():
    config = RangeMedianAdaptiveConfig((RangeMedianCandidate(100,5,.003),
        RangeMedianCandidate(150,5,.003)))
    stream = RangeMedianAdaptiveStream("BTCUSDT", config)
    for i, price in enumerate((100,102,104,106,108,110)):
        stream.accept_page([row(i,price)], now_ms=BASE+i*1000)
    point = stream.accept_page([row(6,95)], now_ms=BASE+6000)[0]
    assert point.buy and point.strategy_params["selected_range_bps"] == 150
    payload = json.loads(json.dumps(stream.checkpoint()))
    restored = RangeMedianAdaptiveStream.restore(payload, symbol="BTCUSDT", config=config)
    assert restored.checkpoint() == payload


def test_guarded_auto_blocks_only_buy_and_restores_exactly():
    config = RangeAutoConfig((100,150), short=2, long=3)
    stream = GuardedRangeAutoStream("BTCUSDT", config)
    for i, price in enumerate((100,102)):
        stream.accept_page([row(i,price)], now_ms=BASE+i*1000, context=up_context())
    down = {"minute_ema_15": 98, "minute_ema_45": 99,
        "minute_ema_15_previous": 98.5, "minute_ema_45_previous": 99.2}
    point = stream.accept_page([row(2,104)], now_ms=BASE+2000, context=down)[0]
    assert not point.buy and point.reason == "entry_blocked:minute_ema15_below_ema45"
    payload = json.loads(json.dumps(stream.checkpoint()))
    restored = GuardedRangeAutoStream.restore(payload, symbol="BTCUSDT", config=config)
    assert restored.checkpoint() == payload
    # A falling strategy exit is never suppressed by an entry guard.
    point = restored.accept_page([row(3,95)], now_ms=BASE+3000, context=down)[0]
    assert point.sell


def test_auto_paper_position_keeps_selected_fixed_range_across_restart(tmp_path):
    strategy = RangeAutoConfig((100,150), short=2, long=3)
    path = tmp_path / "auto.sqlite"
    risk = BStockEngineConfig(strategy_kind="range-auto", range_auto_config=strategy,
        state_file=path, order_size_usdc=Decimal("100"))
    session = RangePaperSession(path, symbol="BTCUSDT", strategy=strategy, risk=risk)
    try:
        for i, price in enumerate((100,102)):
            assert session.accept_page([row(i,price)], now_ms=BASE+i*1000) == []
        assert session.accept_page([row(2,104)], now_ms=BASE+2000)[0]["side"] == "buy"
        assert session.ledger.entry_strategy_params["selected_range_bps"] == 100
    finally:
        session.close()
    restored = RangePaperSession(path, symbol="BTCUSDT", strategy=strategy, risk=risk)
    try:
        assert restored.ledger.entry_strategy_params["selected_range_bps"] == 100
        assert restored.accept_page([row(3,106)], now_ms=BASE+3000) == []
        assert restored.ledger.entry_strategy_params["selected_range_bps"] == 100
        fill = restored.accept_page([row(4,95)], now_ms=BASE+4000)[0]
        assert fill["side"] == "sell" and fill["reason"] == "strategy"
    finally:
        restored.close()


def test_guard_wrapper_bad_page_latches_recovery_without_consuming_prefix():
    strategy = RangeAutoConfig((100,150), short=2, long=3)
    stream = GuardedRangeAutoStream("BTCUSDT", strategy)
    stream.accept_page([row(0,100)], now_ms=BASE, context=up_context())
    with pytest.raises(ValueError):
        stream.accept_page([row(2,102)], now_ms=BASE+2000, context=up_context())
    assert stream.recovery_required and stream.next_id == 1
