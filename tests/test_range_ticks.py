from copy import deepcopy
import json

import pytest

from bstock_web3.range_ticks import RangeStrategyConfig, RangeTickStream

BASE = 1788955200000


def row(i, price, stamp=None, quantity="1"):
    return {"a": i, "T": BASE+i*1000 if stamp is None else stamp, "p": str(price), "q": quantity}


@pytest.mark.parametrize("changes", [
    {"family": "slope"}, {"range_bps": 25}, {"range_bps": True},
    {"short": 1}, {"short": 45, "long": 15}, {"long": 101},
    {"window": 15}, {"entry_threshold": float("nan")},
    {"exit_threshold": -1}, {"deviation": 1},
    {"family": "median", "deviation": 0},
])
def test_config_validation(changes):
    with pytest.raises(ValueError): RangeStrategyConfig(**changes)


def test_exact_multi_bar_construction_preserves_source_volume_semantics():
    stream = RangeTickStream("BTCUSDT", RangeStrategyConfig(range_bps=100, short=2, long=3))
    assert stream.accept_page([row(0,100,quantity="2")], now_ms=BASE) [0].closed_count == 0
    point = stream.accept_page([row(1,103.1,quantity="5")], now_ms=BASE+1000)[0]
    assert point.closed_count == 3 and point.generation == 3
    assert [round(bar.close,6) for bar in stream.bars] == [101,102.01,103.0301]
    assert [bar.synthetic for bar in stream.bars] == [False,True,True]
    assert [bar.volume for bar in stream.bars] == [2,0,0]
    assert stream.volume == 5 and stream.tick_count == 1
    assert point.buy and not point.sell


def test_ema_evaluates_one_final_generation_and_no_replay():
    config = RangeStrategyConfig(range_bps=100, short=2, long=3)
    stream = RangeTickStream("BTCUSDT", config)
    stream.accept_page([row(0,100)], now_ms=BASE)
    first = stream.accept_page([row(1,103.1)], now_ms=BASE+1000)[0]
    assert first.generation == 3 and first.buy
    assert stream.accept_page([row(1,103.1)], now_ms=BASE+1000) == ()
    waiting = stream.accept_page([row(2,103.2)], now_ms=BASE+2000)[0]
    assert waiting.reason == "waiting_range_close" and not waiting.buy and not waiting.sell
    falling = stream.accept_page([row(3,98)], now_ms=BASE+3000)[0]
    assert falling.closed_count > 1 and falling.sell and not falling.buy


def test_median_uses_closed_range_bars_only():
    config = RangeStrategyConfig(family="median", range_bps=100, window=5, deviation=.003)
    stream = RangeTickStream("BTCUSDT", config)
    stream.accept_page([row(0,100)], now_ms=BASE)
    for i, price in enumerate((101.1,102.2,103.3,104.4),1):
        point = stream.accept_page([row(i,price)], now_ms=BASE+i*1000)[0]
        assert not point.buy
    point = stream.accept_page([row(5,105.5)], now_ms=BASE+5000)[0]
    assert point.generation >= 5 and point.sell
    point = stream.accept_page([row(6,95)], now_ms=BASE+6000)[0]
    assert point.closed_count > 1 and point.buy


def test_warmup_and_stale_closes_are_consumed_without_future_signal():
    config = RangeStrategyConfig(range_bps=100, short=2, long=3)
    stream = RangeTickStream("BTCUSDT", config)
    points = stream.accept_page([row(0,100),row(1,103.1)], now_ms=BASE+1000)
    assert all(not p.buy and not p.sell for p in points)
    generation = stream.sequence
    assert stream.last_evaluated == generation
    point = stream.accept_page([row(2,104.2)], now_ms=BASE+10000)[0]
    assert point.reason == "stale_range_close" and not point.buy
    point = stream.accept_page([row(3,104.3)], now_ms=BASE+3000)[0]
    assert point.reason == "waiting_range_close" and stream.last_evaluated == stream.sequence


def test_checkpoint_partial_and_recursive_ema_restore_exactly():
    config = RangeStrategyConfig(range_bps=20, short=3, long=5)
    left = RangeTickStream("NVDABUSDT", config)
    left.accept_page([row(0,100),row(1,101.1)], now_ms=BASE+1000)
    payload = json.loads(json.dumps(left.checkpoint()))
    right = RangeTickStream.restore(payload, symbol="NVDABUSDT", config=config)
    assert right.checkpoint() == left.checkpoint()
    page = [row(2,99.7),row(3,100.8)]
    assert right.accept_page(page, now_ms=BASE+3000) == left.accept_page(page, now_ms=BASE+3000)
    assert right.checkpoint() == left.checkpoint()


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(version=True), lambda p: p.update(symbol="OTHER"),
    lambda p: p.update(last_id=True), lambda p: p.update(last_ms=None),
    lambda p: p.update(open=None), lambda p: p.update(fast=float("nan")),
    lambda p: p.update(last_evaluated=999), lambda p: p["bars"][0].update(sequence=99),
    lambda p: p.update(extra=1),
])
def test_corrupt_checkpoint_rejected(mutate):
    config = RangeStrategyConfig(range_bps=100, short=2, long=3)
    stream = RangeTickStream("BTCUSDT", config)
    stream.accept_page([row(0,100),row(1,103.1)], now_ms=BASE+1000)
    payload = deepcopy(stream.checkpoint())
    mutate(payload)
    with pytest.raises(ValueError): RangeTickStream.restore(payload, symbol="BTCUSDT", config=config)


@pytest.mark.parametrize("page", [[row(2,101)], [row(1,101),row(3,102)],
    [row(1,101),row(2,102,stamp=BASE)], [{**row(1,101),"p":"NaN"}], {}])
def test_bad_page_does_not_consume_prefix_and_latches_recovery(page):
    stream = RangeTickStream("BTCUSDT", RangeStrategyConfig())
    stream.accept_page([row(0,100)], now_ms=BASE)
    before = deepcopy(stream.checkpoint())
    with pytest.raises(ValueError): stream.accept_page(page, now_ms=BASE+3000)
    assert stream.next_id == 1 and stream.bars == tuple()
    assert stream.recovery_required
    assert {**stream.checkpoint(), "recovery_required": False} == before


def test_latest_trade_conflict_and_absurd_crossing_fail_closed():
    config = RangeStrategyConfig(range_bps=5, short=2, long=3)
    stream = RangeTickStream("BTCUSDT", config)
    stream.accept_page([row(1, 100)], now_ms=BASE)
    original = deepcopy(stream.checkpoint())
    with pytest.raises(ValueError, match="Conflicting replay"):
        stream.accept_page([row(1, 101)], now_ms=BASE)
    assert stream.next_id == 2 and stream.recovery_required
    safe = RangeTickStream.restore(original, symbol="BTCUSDT", config=config)
    with pytest.raises(ValueError, match="too many bars"):
        safe.accept_page([row(2, 1e100)], now_ms=BASE+1000)
    assert safe.next_id == 2 and safe.recovery_required


def test_2000_ticks_restore_parity_and_bounded_history():
    config = RangeStrategyConfig(family="median", range_bps=5, window=60, deviation=.003)
    left = RangeTickStream("BTCUSDT", config)
    for i in range(2000):
        price = 100 + (i % 41 - 20) * .03
        point = left.accept_page([row(i,price)], now_ms=BASE+i*1000)
        if i % 137 == 0:
            right = RangeTickStream.restore(json.loads(json.dumps(left.checkpoint())), symbol="BTCUSDT", config=config)
            assert right.checkpoint() == left.checkpoint()
            left = right
        assert len(left.bars) <= 60
        assert point[0].closed_count >= 0
