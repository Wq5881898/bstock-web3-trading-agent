from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from bstock_web3.engine import BStockEngine, BStockEngineConfig, EngineState
from bstock_web3.strategy import MtfEmaConfig, SignalDecision
from bstock_web3.market_data import _closed, MultiTimeframeSnapshot
from bstock_web3.models import Kline
from bstock_web3.catalog import BStockAsset


@pytest.mark.parametrize("field", ["order_size_usdc", "paper_fee_rate", "min_net_edge_bps"])
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_engine_config(field, value):
    with pytest.raises(ValueError):
        BStockEngineConfig(**{field: Decimal(value)})


@pytest.mark.parametrize("kwargs", [{"entry_short": True}, {"trend_long": 21.5},
    {"stop_loss": float("nan")}, {"min_expected_edge": float("inf")}, {"stop_loss": 0}])
def test_invalid_strategy_config(kwargs):
    with pytest.raises(ValueError): MtfEmaConfig(**kwargs)


@pytest.mark.parametrize("field,value", [("cash_usdc", "Infinity"), ("realized_pnl", "NaN"),
    ("fees_usdc", "-1"), ("position_quantity", "garbage"), ("entry_price", "100"),
    ("paper_entry_cost", "100"), ("pending_action", "buy"), ("last_signal_bar", "2026-09-09T12:00:00")])
def test_corrupt_state_rejected_without_replacement(tmp_path, field, value):
    path = tmp_path / "state.json"
    content = json.dumps({**asdict(EngineState()), field: value})
    path.write_text(content)
    with pytest.raises(RuntimeError): BStockEngine(BStockEngineConfig(state_file=path))
    assert path.read_text() == content


def test_paper_roundtrip_includes_both_fees_and_rejects_position_overwrite(tmp_path):
    config = BStockEngineConfig(state_file=tmp_path / "paper.json")
    engine = BStockEngine(config)
    buy = SignalDecision("buy", "fixture", 100, None)
    engine._paper_fill(buy)
    before = asdict(engine.state)
    with pytest.raises(ValueError): engine._paper_fill(buy)
    assert asdict(engine.state) == before
    engine = BStockEngine(config)
    engine._paper_fill(SignalDecision("sell", "fixture", 100, None))
    assert Decimal(engine.state.realized_pnl) == Decimal(engine.state.cash_usdc) - 1000
    assert Decimal(engine.state.realized_pnl) == -Decimal(engine.state.fees_usdc)
    assert engine.state.paper_entry_cost is None
    with pytest.raises(ValueError): engine._paper_fill(SignalDecision("sell", "fixture", 100, None))


def test_disk_failure_rolls_back_in_memory_fill(tmp_path, monkeypatch):
    engine = BStockEngine(BStockEngineConfig(state_file=tmp_path / "paper.json"))
    before = asdict(engine.state)
    def fail(): raise OSError("injected disk failure")
    monkeypatch.setattr(engine, "_save_state", fail)
    with pytest.raises(OSError): engine._paper_fill(SignalDecision("buy", "fixture", 100, None))
    assert asdict(engine.state) == before


@pytest.mark.parametrize("change", [{"symbol": "OTHERB"}, {"mode": "quote"}])
def test_state_identity_prevents_cross_session_reuse(tmp_path, change):
    config = BStockEngineConfig(state_file=tmp_path / "paper.json")
    engine = BStockEngine(config)
    engine._paper_fill(SignalDecision("buy", "fixture", 100, None))
    content = config.state_file.read_text()
    with pytest.raises(RuntimeError): BStockEngine(replace(config, **change))
    assert config.state_file.read_text() == content


def test_legacy_paper_position_requires_verified_cost(tmp_path):
    engine = BStockEngine(BStockEngineConfig(state_file=tmp_path / "paper.json"))
    engine.state.position_quantity, engine.state.entry_price = "1", "100"
    before = asdict(engine.state)
    with pytest.raises(ValueError, match="Legacy"):
        engine._paper_fill(SignalDecision("sell", "fixture", 100, None))
    assert asdict(engine.state) == before


def test_candle_integrity_and_unclosed_exclusion():
    now = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    bar = Kline(now-timedelta(minutes=1), 100, 101, 99, 100, 1)
    for bad in (replace(bar, close=float("nan")), replace(bar, volume=-1), replace(bar, high=90),
                replace(bar, time=bar.time+timedelta(seconds=1))):
        with pytest.raises(ValueError): _closed([bad], 1, now)
    with pytest.raises(ValueError): _closed([bar, bar], 1, now)
    assert _closed([bar, replace(bar, time=now)], 1, now) == [bar]


def test_stale_snapshot_cannot_reach_execution(tmp_path):
    asset = BStockAsset("NVDA", "NVDAB", "fixture", "56", "NVDABUSDT", "1")
    now = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    bar = Kline(now-timedelta(minutes=20), 100, 101, 99, 100, 1)
    class Catalog:
        def resolve(self, symbol): return asset
        def market_status(self, asset): return SimpleNamespace(open_state=True, reason_code="TRADING")
    class Feed:
        def fetch(self, *args, **kwargs): return MultiTimeframeSnapshot(asset, (bar,), (bar,), now)
    class Strategy:
        def evaluate(self, *args): raise AssertionError("stale snapshot must be blocked")
    engine = BStockEngine(BStockEngineConfig(state_file=tmp_path / "state.json"),
                         catalog=Catalog(), feed=Feed(), strategy=Strategy())
    assert engine.evaluate_once().signal.reason == "stale_or_missing_candles"
    assert engine.state.last_signal_bar is None
    assert engine.state.cash_usdc == "1000"


def test_continuous_2000_cycles_restart_and_duplicate_bars(tmp_path):
    asset = BStockAsset("NVDA", "NVDAB", "fixture", "56", "NVDABUSDT", "1")
    base = datetime(2026, 9, 9, tzinfo=timezone.utc)
    class Catalog:
        def resolve(self, symbol): return asset
        def market_status(self, asset): return SimpleNamespace(open_state=True, reason_code="TRADING")
    class Feed:
        index = 0
        def fetch(self, asset, now=None):
            stamp = base+timedelta(minutes=self.index)
            return MultiTimeframeSnapshot(asset, (Kline(stamp, 100, 101, 99, 100, 1),), (), stamp+timedelta(minutes=1))
    class Strategy:
        def evaluate(self, snapshot, position):
            return SignalDecision("sell" if position.holding else "buy", "fixture", 100,
                                  snapshot.signal_bar_time.isoformat())
    feed = Feed()
    config = BStockEngineConfig(state_file=tmp_path / "continuous.json", paper_daily_loss_limit=Decimal("1000"),
                               paper_max_daily_entries=10000, paper_max_loss_streak=10000)
    def reopen(): return BStockEngine(config, catalog=Catalog(), feed=feed, strategy=Strategy())
    engine = reopen()
    for index in range(2000):
        feed.index = index
        assert engine.evaluate_once().paper_fill is not None
        before = asdict(engine.state)
        assert engine.evaluate_once().paper_fill is None
        assert asdict(engine.state) == before
        if index % 137 == 0:
            engine = reopen()
            assert asdict(engine.state) == before
    assert Decimal(engine.state.position_quantity) == 0
    assert abs(Decimal(engine.state.cash_usdc) - 1000 - Decimal(engine.state.realized_pnl)) < Decimal("1e-20")
    assert abs(Decimal(engine.state.realized_pnl) + Decimal(engine.state.fees_usdc)) < Decimal("1e-20")
    feed.index = 1
    assert engine.evaluate_once().paper_fill is None  # older bars also cannot replay
