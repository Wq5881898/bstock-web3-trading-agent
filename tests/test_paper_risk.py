from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from dataclasses import replace
import pytest

from bstock_web3.engine import BStockEngine, BStockEngineConfig
from bstock_web3.catalog import BStockAsset
from bstock_web3.market_data import MultiTimeframeSnapshot
from bstock_web3.models import Kline
from bstock_web3.strategy import SignalDecision


def setup(tmp_path):
    asset = BStockAsset("NVDA", "NVDAB", "fixture", "56", "NVDABUSDT", "1")
    class Catalog:
        def resolve(self, symbol): return asset
        def market_status(self, asset): return SimpleNamespace(open_state=True, reason_code="TRADING")
    class Feed:
        now = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
        price = 100
        def fetch(self, *args, **kwargs):
            bar = Kline(self.now-timedelta(minutes=1), self.price, self.price, self.price, self.price, 1)
            return MultiTimeframeSnapshot(asset, (bar,), (), self.now)
    class Strategy:
        action = "buy"
        def evaluate(self, snapshot, position):
            return SignalDecision(self.action, "fixture", snapshot.one_minute[-1].close, snapshot.signal_bar_time.isoformat())
    feed, strategy = Feed(), Strategy()
    config = BStockEngineConfig(state_file=tmp_path / "state.json", order_size_usdc=Decimal("100"))
    def reopen(): return BStockEngine(config, catalog=Catalog(), feed=feed, strategy=strategy)
    return reopen, feed, strategy


def test_loss_latches_buys_but_signal_sells_continue_across_restart(tmp_path):
    reopen, feed, strategy = setup(tmp_path)
    engine = reopen()
    assert engine.evaluate_once().paper_fill["side"] == "buy"
    feed.price = 80
    feed.now += timedelta(minutes=1)
    strategy.action = "hold"
    event = engine.evaluate_once()
    assert event.paper_risk_status == "DAILY_LOSS"
    assert Decimal(engine.state.position_quantity) > 0
    assert event.paper_fill is None
    engine = reopen()
    engine.paper_control("resume")
    assert engine.evaluate_once().paper_risk_status == "DAILY_LOSS"
    strategy.action = "sell"
    feed.now += timedelta(minutes=1)
    assert engine.evaluate_once().paper_fill["side"] == "sell"
    strategy.action = "buy"
    feed.now += timedelta(minutes=1)
    assert engine.evaluate_once().paper_fill is None
    assert engine.state.paper_buy_pause == "DAILY_LOSS"
    feed.now += timedelta(days=1)
    assert engine.evaluate_once().paper_fill is None  # midnight does not release latch
    engine.paper_control("resume")
    feed.now += timedelta(minutes=1)
    assert engine.evaluate_once().paper_fill["side"] == "buy"


def test_manual_pause_retains_baseline_and_requires_fresh_resume(tmp_path):
    reopen, feed, strategy = setup(tmp_path)
    engine = reopen()
    engine.paper_control("pause")
    assert engine.evaluate_once().paper_fill is None
    baseline = engine.state.paper_risk_baseline
    engine = reopen()
    assert engine.state.paper_buy_pause == "MANUAL"
    engine.paper_control("resume")
    assert engine.state.paper_buy_pause == "MANUAL"
    feed.now += timedelta(minutes=1)
    assert engine.evaluate_once().paper_fill["side"] == "buy"
    assert engine.state.paper_risk_baseline == baseline


def test_three_losses_latch_and_manual_resume_resets_streak(tmp_path):
    reopen, feed, strategy = setup(tmp_path)
    engine = reopen()
    for _ in range(3):
        strategy.action = "buy"
        assert engine.evaluate_once().paper_fill["side"] == "buy"
        feed.now += timedelta(minutes=1)
        strategy.action = "sell"
        assert engine.evaluate_once().paper_fill["side"] == "sell"
        feed.now += timedelta(minutes=1)
    assert engine.state.paper_loss_streak == 3
    assert engine.state.paper_buy_pause == "CONSECUTIVE_LOSSES"
    engine = reopen()
    strategy.action = "buy"
    assert engine.evaluate_once().paper_fill is None
    engine.paper_control("resume")
    feed.now += timedelta(minutes=1)
    assert engine.evaluate_once().paper_fill["side"] == "buy"
    assert engine.state.paper_loss_streak == 0


def test_daily_entry_limit_does_not_block_exit_or_allow_same_day_resume(tmp_path):
    reopen, feed, strategy = setup(tmp_path)
    engine = reopen()
    engine.config = replace(engine.config, paper_max_daily_entries=1)
    assert engine.evaluate_once().paper_fill["side"] == "buy"
    assert engine.state.paper_buy_pause == "DAILY_ENTRY_LIMIT"
    engine.paper_control("resume")
    feed.now += timedelta(minutes=1)
    strategy.action = "sell"
    assert engine.evaluate_once().paper_fill["side"] == "sell"
    assert engine.state.paper_buy_pause == "DAILY_ENTRY_LIMIT"
    strategy.action = "buy"
    feed.now += timedelta(days=1)
    assert engine.evaluate_once().paper_fill is None
    assert engine.state.paper_daily_entries == 0
    engine.paper_control("resume")
    feed.now += timedelta(minutes=1)
    assert engine.evaluate_once().paper_fill["side"] == "buy"


def test_cooldown_survives_restart_and_does_not_latch(tmp_path):
    reopen, feed, strategy = setup(tmp_path)
    engine = reopen()
    engine.config = replace(engine.config, paper_entry_cooldown=180)
    engine.evaluate_once()
    feed.now += timedelta(minutes=1)
    strategy.action = "sell"
    engine.evaluate_once()
    engine = reopen()
    engine.config = replace(engine.config, paper_entry_cooldown=180)
    feed.now += timedelta(minutes=1)
    strategy.action = "buy"
    assert engine.evaluate_once().signal.reason == "paper_entry_cooldown"
    assert engine.state.paper_buy_pause == ""
    feed.now += timedelta(minutes=1)
    assert engine.evaluate_once().paper_fill["side"] == "buy"


@pytest.mark.parametrize("kwargs", [{"paper_position_cap": Decimal("10")},
    {"paper_max_daily_entries": True}, {"paper_max_loss_streak": 0}, {"paper_entry_cooldown": -1}])
def test_invalid_limits_rejected(kwargs):
    with pytest.raises(ValueError): BStockEngineConfig(**kwargs)
