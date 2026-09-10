from dataclasses import asdict
from decimal import Decimal
from types import SimpleNamespace

import pytest

from bstock_web3.catalog import BStockAsset
from bstock_web3.engine import BStockEngineConfig
from bstock_web3.median_monitor import MedianMonitor
from bstock_web3.median_ticks import TickMedianConfig
from bstock_web3.range_ticks import RangeStrategyConfig

BASE = 1788955200


def row(i, price=100, seconds=0):
    return {"a": i, "T": int((BASE+seconds)*1000), "p": str(price), "q": "1"}


class Catalog:
    failed = False
    def resolve(self, symbol): return BStockAsset("NVDA", "NVDAB", "fixture", "56", "NVDABUSDT", "1")
    def market_status(self, asset):
        if self.failed: raise ValueError("status unavailable")
        return SimpleNamespace(open_state=True, reason_code="TRADING")


class Trades:
    def __init__(self): self.rows, self.calls, self.closed, self.failed = [], [], False, False
    def fetch(self, symbol, **kwargs):
        self.calls.append(kwargs)
        if self.failed: raise ValueError("feed failure")
        return self.rows
    def close(self): self.closed = True


class Candles:
    def fetch(self, *args): raise ValueError("chart-only failure")


def setup(tmp_path):
    config = BStockEngineConfig(symbol="NVDAB", strategy_kind="median", state_file=tmp_path / "median.sqlite",
        order_size_usdc=Decimal("100"), median_config=TickMedianConfig(window=3, entry_deviation=.01, exit_deviation=.01))
    trades, clock, catalog = Trades(), [BASE], Catalog()
    def reopen(): return MedianMonitor(config, trades=trades, candles=Candles(), catalog=catalog, clock=lambda:clock[0])
    return reopen, trades, clock, catalog


def test_worker_warmup_fill_restart_manual_resume_and_chart_independence(tmp_path):
    reopen, trades, clock, _ = setup(tmp_path)
    worker = reopen()
    trades.rows = [row(i) for i in range(3)]
    assert not worker.evaluate_once().fills
    assert trades.calls[-1] == {"from_id": None, "limit": 200}
    trades.rows = [row(3,95)]
    assert worker.evaluate_once().fills[0]["side"] == "buy"
    assert trades.calls[-1]["from_id"] == 3
    event = worker.evaluate_once()
    assert event.account_snapshot["quantity"] != "0"
    assert event.recent_fills[-1]["side"] == "buy"
    assert trades.calls[-1]["from_id"] == 4
    worker.close()
    worker = reopen()
    try:
        trades.rows = [row(4,105)]
        event = worker.evaluate_once()
        assert event.fills[0]["side"] == "sell"
        assert event.paper_risk_status == "MANUAL"
        assert [fill["side"] for fill in event.recent_fills] == ["buy", "sell"]
        worker.paper_control("resume")
        trades.rows = []
        assert worker.evaluate_once().paper_risk_status == "ACTIVE"
    finally:
        worker.close()
    assert trades.closed


def test_feed_error_latches_then_contiguous_repair_requires_manual_resume(tmp_path):
    reopen, trades, _, _ = setup(tmp_path)
    worker = reopen()
    try:
        trades.rows = [row(i) for i in range(3)]
        worker.evaluate_once()
        trades.failed = True
        with pytest.raises(ValueError): worker.evaluate_once()
        assert worker.session.stream.next_id == 3
        assert worker.session.ledger.pause == "DATA_GAP"
        trades.failed = False
        worker.paper_control("resume")
        trades.rows = []
        assert worker.evaluate_once().paper_risk_status == "DATA_GAP"  # no accepted repair, even if old tail is fresh
        trades.rows = [row(3,95)]
        assert not worker.evaluate_once().fills
        assert worker.session.stream.recovery_required
        worker.paper_control("resume")
        trades.rows = []
        assert worker.evaluate_once().paper_risk_status == "ACTIVE"
        assert not worker.session.stream.recovery_required
    finally:
        worker.close()


def test_market_status_failure_also_latches(tmp_path):
    reopen, trades, _, catalog = setup(tmp_path)
    worker = reopen()
    try:
        trades.rows = [row(i) for i in range(3)]
        worker.evaluate_once()
        catalog.failed = True
        with pytest.raises(ValueError): worker.evaluate_once()
        assert worker.session.ledger.pause == "DATA_GAP"
    finally:
        worker.close()


def test_catchup_bounded_full_pages_never_fill_or_skip(tmp_path):
    reopen, trades, clock, _ = setup(tmp_path)
    worker = reopen()
    try:
        trades.rows = [row(i) for i in range(3)]
        worker.evaluate_once()
        def paged(symbol, from_id, limit):
            trades.calls.append({"from_id": from_id, "limit": limit})
            return [row(i, 95 if i%2 else 105) for i in range(from_id,from_id+limit)]
        trades.fetch = paged
        assert not worker.evaluate_once().fills
        assert worker.session.stream.next_id == 3003
        assert len(trades.calls) == 4  # cold request + at most three catch-up pages
        assert worker.session.fills() == []
    finally:
        worker.close()


def test_range_monitor_warmup_buy_restart_and_sell(tmp_path):
    config = BStockEngineConfig(symbol="NVDAB", strategy_kind="range-ema",
        state_file=tmp_path / "range.sqlite", order_size_usdc=Decimal("100"),
        range_config=RangeStrategyConfig(family="ema", range_bps=100, short=2, long=3))
    trades, clock, catalog = Trades(), [BASE], Catalog()
    def reopen():
        return MedianMonitor(config, trades=trades, candles=Candles(), catalog=catalog, clock=lambda:clock[0])
    worker = reopen()
    trades.rows = [row(0, 100), row(1, 101), row(2, 102.01), row(3, 103.0301)]
    assert not worker.evaluate_once().fills
    trades.rows = [row(4, 104.060401)]
    assert worker.evaluate_once().fills[0]["side"] == "buy"
    worker.close()
    worker = reopen()
    try:
        trades.rows = [row(5, 99)]
        event = worker.evaluate_once()
        assert event.fills[0]["side"] == "sell"
        assert event.paper_risk_status == "MANUAL"
    finally:
        worker.close()
