from copy import deepcopy
import json
from statistics import median

import pytest

from bstock_web3.median_ticks import AggregateTick, MedianTickStream, TickMedianConfig


def row(i, price=100, stamp=None):
    return {"a": i, "T": 100000 + i if stamp is None else stamp, "p": str(price), "q": "1"}


def ready():
    stream = MedianTickStream("BTCUSDT", TickMedianConfig(window=3, entry_deviation=.01, exit_deviation=.01))
    observations = stream.accept_page([row(i) for i in range(3)], now_ms=100002)
    assert all(not point.buy and not point.sell and not point.fresh for point in observations)
    return stream


@pytest.mark.parametrize("changes", [
    {"a": True}, {"a": -1}, {"a": "1"}, {"a": 9223372036854775808}, {"T": True}, {"T": -1},
    {"p": "NaN"}, {"p": "Infinity"}, {"p": "0"}, {"p": None},
    {"p": True}, {"q": "-1"}, {"q": []},
])
def test_wire_validation(changes):
    with pytest.raises(ValueError):
        AggregateTick.from_wire({**row(1), **changes})


@pytest.mark.parametrize("changes", [{"window": True}, {"window": 0}, {"window": 101},
    {"entry_deviation": -1}, {"entry_deviation": float("nan")},
    {"exit_deviation": 1}, {"exit_deviation": "0.1"}])
def test_config_validation(changes):
    with pytest.raises(ValueError): TickMedianConfig(**changes)


def test_current_tick_median_rules_and_strict_boundaries():
    stream = ready()
    first = stream.accept_page([row(3, 99)], now_ms=100003)[0]
    assert first.median_price == 100 and not first.buy  # strict '<', not '<='
    second = stream.accept_page([row(4, 95)], now_ms=100004)[0]
    assert second.median_price == 99 and second.buy and not second.sell
    third = stream.accept_page([row(5, 105)], now_ms=100005)[0]
    assert third.median_price == 99 and third.sell and not third.buy


@pytest.mark.parametrize("offset", [5001, -1])
def test_stale_or_future_ticks_warm_without_signals(offset):
    stream = ready()
    result = stream.accept_page([row(3, 95)], now_ms=100003 + offset)[0]
    assert not result.fresh and not result.buy and not result.sell
    assert stream.next_id == 4
    assert result.median_price == 100


def test_same_millisecond_ids_are_not_lost_and_replay_is_idempotent():
    stream = ready()
    page = [row(3, 95, 100003), row(4, 105, 100003)]
    points = stream.accept_page(page, now_ms=100003)
    assert len(points) == 2 and points[0].buy and points[1].sell
    before = stream.checkpoint()
    assert stream.accept_page(page, now_ms=100003) == ()
    assert stream.checkpoint() == before


@pytest.mark.parametrize("page", [
    [row(4)], [row(3), row(5)], [row(3), row(4, stamp=100001)],
    [row(3), row(3)], [row(3), {**row(4), "p": "NaN"}],
    [row(2, 900)], {}, [row(i) for i in range(1001)],
])
def test_invalid_page_never_consumes_prefix_and_latches_recovery(page):
    stream = ready()
    before = stream.checkpoint()
    with pytest.raises(ValueError):
        stream.accept_page(page, now_ms=100005)
    after = stream.checkpoint()
    assert after["ticks"] == before["ticks"]
    assert stream.next_id == 3 and stream.recovery_required


def test_gap_repair_does_not_auto_resume_buys_but_exits_still_signal(tmp_path):
    stream = ready()
    with pytest.raises(ValueError): stream.accept_page([row(4)], now_ms=100004)
    assert not stream.accept_page([row(3, 95)], now_ms=100003)[0].buy
    path = tmp_path / "median.json"
    stream.save(path)
    restored = MedianTickStream.load(path, symbol=stream.symbol, config=stream.config)
    assert restored.recovery_required
    assert restored.accept_page([row(4, 105)], now_ms=100004)[0].sell


def test_checkpoint_restores_exact_indicator_history_and_identity(tmp_path):
    stream = ready()
    stream.accept_page([row(3, 95)], now_ms=100003)
    path = tmp_path / "median.json"
    stream.save(path)
    restored = MedianTickStream.load(path, symbol=stream.symbol, config=stream.config)
    assert restored.checkpoint() == stream.checkpoint()
    assert restored.accept_page([row(4, 105)], now_ms=100004) == stream.accept_page([row(4, 105)], now_ms=100004)
    with pytest.raises(ValueError): MedianTickStream.load(path, symbol="ETHUSDT", config=stream.config)
    with pytest.raises(ValueError): MedianTickStream.load(path, symbol=stream.symbol, config=TickMedianConfig())


@pytest.mark.parametrize("corrupt", [
    lambda data: data.update(version=True),
    lambda data: data.update(recovery_required="false"),
    lambda data: data["config"].update(window=True),
    lambda data: data["ticks"][1].update(trade_id=99),
    lambda data: data["ticks"][1].update(time_ms=0),
    lambda data: data["ticks"][1].update(price="NaN"),
    lambda data: data.update(extra="unknown"),
])
def test_corrupt_checkpoint_is_rejected(corrupt):
    stream = ready()
    data = deepcopy(stream.checkpoint())
    corrupt(data)
    with pytest.raises(ValueError): MedianTickStream.restore(data, symbol=stream.symbol, config=stream.config)


def test_disk_failure_preserves_checkpoint_and_cleans_temporary(monkeypatch, tmp_path):
    stream = ready()
    path = tmp_path / "median.json"
    stream.save(path)
    before = path.read_bytes()
    def fail(*args): raise OSError("disk failure")
    monkeypatch.setattr("bstock_web3.median_ticks.os.replace", fail)
    with pytest.raises(OSError): stream.save(path)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("raw", ['{', '{"version":1,"version":1}', 'x' * 131073],
                         ids=["invalid-json", "duplicate-key", "oversized"])
def test_bad_disk_checkpoint_is_not_overwritten(tmp_path, raw):
    path = tmp_path / "median.json"
    path.write_text(raw)
    with pytest.raises(ValueError): MedianTickStream.load(path, symbol="BTCUSDT", config=TickMedianConfig())
    assert path.read_text() == raw


def test_2000_ticks_match_causal_reference_across_checkpoints():
    config = TickMedianConfig(window=20)
    stream = MedianTickStream("BTCUSDT", config)
    history = [100.] * 20
    stream.accept_page([row(i) for i in range(20)], now_ms=100020)
    for i in range(20, 2020):
        price = 100 + (i % 7 - 3)
        history.append(price)
        result = stream.accept_page([row(i, price)], now_ms=100000+i)[0]
        center = median(history[-config.window:])
        assert result.median_price == center
        assert result.buy == (price < center * (1 - config.entry_deviation))
        assert result.sell == (price > center * (1 + config.exit_deviation))
        if i % 137 == 0:
            stream = MedianTickStream.restore(json.loads(json.dumps(stream.checkpoint())), symbol=stream.symbol, config=config)
        assert len(stream.checkpoint()["ticks"]) <= 200
