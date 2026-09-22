from datetime import datetime, timedelta, timezone

import pytest

from bstock_web3.catalog import BStockAsset, BStockMarketStatus
from bstock_web3.market_data import MultiTimeframeSnapshot
from bstock_web3.models import Kline
from bstock_web3.spot_observer import SpotObserverConfig, SpotSignalObserver
from bstock_web3.strategy import PositionView, SignalDecision


NOW = datetime(2026, 9, 22, 19, 30, tzinfo=timezone.utc)
ASSET = BStockAsset("BTC", "BTC", "", "", "BTCUSDT", "1")


class Catalog:
    def resolve(self, symbol):
        assert symbol == "BTCUSDT"
        return ASSET

    def market_status(self, asset):
        assert asset == ASSET
        return BStockMarketStatus(True, "TRADING", None, "TRADING")


class Feed:
    def fetch(self, asset, *, now=None):
        one = tuple(Kline(NOW - timedelta(minutes=i), 100, 101, 99, 100, 1)
                    for i in range(30, 0, -1))
        five = tuple(Kline(NOW - timedelta(minutes=5 * i),
                           100, 101, 99, 100, 1)
                     for i in range(30, 0, -1))
        return MultiTimeframeSnapshot(asset, one, five, NOW)


class Strategy:
    def evaluate(self, snapshot, position):
        assert position == PositionView(0, 0)
        return SignalDecision("buy", "test", 100.0,
                              snapshot.signal_bar_time.isoformat(),
                              expected_edge=0.004)


def config(tmp_path, symbol="BTCUSDT"):
    return SpotObserverConfig(
        symbol=symbol, state_path=tmp_path / "observer.json",
        output_path=tmp_path / "latest.json",
        action_output_path=tmp_path / "action.json")


def test_observer_writes_transport_free_signal_and_deduplicates_bar(tmp_path):
    observer = SpotSignalObserver(
        config(tmp_path), catalog=Catalog(), feed=Feed(), strategy=Strategy())
    first = observer.evaluate_once(PositionView(), now=NOW)
    assert first["mode"] == "OBSERVE_ONLY" and first["transport"] is None
    assert first["execution_eligible"] is False
    assert first["position_snapshot_fresh"] is None
    assert first["symbol"] == "BTCUSDT"
    assert first["signal"]["action"] == "buy"
    assert first["signal"]["strategy_id"] == "mtf"
    assert config(tmp_path).action_output_path.exists()
    second = observer.evaluate_once(PositionView(), now=NOW)
    assert second["duplicate_bar"]
    assert second["signal"]["action"] == "hold"
    assert second["signal"]["reason"] == "signal_bar_already_processed"


def test_observer_marks_old_position_snapshot_non_executable(tmp_path):
    observer = SpotSignalObserver(
        config(tmp_path), catalog=Catalog(), feed=Feed(), strategy=Strategy())
    result = observer.evaluate_once(
        PositionView(), position_observed_at="2026-09-21T19:30:00Z",
        now=NOW)
    assert result["position_snapshot_fresh"] is False
    assert result["execution_eligible"] is False


def test_observer_restart_preserves_deduplication_and_binding(tmp_path):
    original = SpotSignalObserver(
        config(tmp_path), catalog=Catalog(), feed=Feed(), strategy=Strategy())
    original.evaluate_once(PositionView(), now=NOW)
    restored = SpotSignalObserver(
        config(tmp_path), catalog=Catalog(), feed=Feed(), strategy=Strategy())
    assert restored.evaluate_once(PositionView(), now=NOW)["duplicate_bar"]
    with pytest.raises(ValueError, match="Invalid Spot observer state"):
        SpotSignalObserver(config(tmp_path, "ETHUSDT"))


def test_observer_state_corruption_fails_closed(tmp_path):
    cfg = config(tmp_path)
    cfg.state_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid Spot observer state"):
        SpotSignalObserver(cfg)
