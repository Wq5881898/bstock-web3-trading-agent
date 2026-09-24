from dataclasses import replace
from decimal import Decimal

import pytest

from bstock_web3.catalog import BStockAsset, BStockMarketStatus
from bstock_web3.mcp_bridge import write_mcp_account_binding
from bstock_web3.mcp_cycle import McpCyclePaths, run_cycle
from bstock_web3.mcp_equity_guard import McpSpotEquityGuard
from bstock_web3.mcp_host_receipt import write_verified_receipt
from bstock_web3.strategy import SignalDecision

from test_mcp_equity_guard import BINDING, BASE_TIME, BUY, receipt


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
        assert asset == ASSET
        return object()


class Strategy:
    def evaluate(self, snapshot, position):
        return SignalDecision("buy", "fixture", 50.0,
            "1970-01-01T00:33:20Z", expected_edge=0.004)


def setup(tmp_path, current=None):
    current = current or receipt()
    paths = McpCyclePaths(
        binding=tmp_path / "binding.json",
        receipt=tmp_path / "receipt.json",
        equity_guard=tmp_path / "equity.json",
        fill_ledger=tmp_path / "fills.json",
        session=tmp_path / "session.json",
        candidates=tmp_path / "candidates")
    write_mcp_account_binding(BINDING, paths.binding)
    write_verified_receipt(current, paths.receipt)
    with McpSpotEquityGuard(paths.equity_guard,
            account_ref=current.account_ref,
            account_fingerprint=current.account_fingerprint,
            symbol=current.symbol) as guard:
        guard.initialize(receipt(), operator_confirmed=True)
    return paths


def cycle(paths, *, now_ms=BASE_TIME):
    return run_cycle(paths, now_ms=now_ms, catalog=Catalog(),
                     feed=Feed(), strategy=Strategy())


def test_fresh_receipt_starts_durable_session_and_emits_one_candidate(tmp_path):
    paths = setup(tmp_path)
    first = cycle(paths)
    assert first["status"] == "READY"
    assert first["phase"] == "WAITING_CONFIRMATION"
    assert first["planFile"] is not None
    assert paths.session.is_file()
    assert paths.fill_ledger.is_file()
    assert len(list(paths.candidates.glob("candidate-*.json"))) == 1
    second = cycle(paths)
    assert second["status"] == "BLOCKED"
    assert second["reason"] == "session_not_running"
    assert len(list(paths.candidates.glob("candidate-*.json"))) == 1


def test_stale_receipt_cannot_start_session_or_make_candidate(tmp_path):
    paths = setup(tmp_path)
    with pytest.raises(ValueError, match="fresh account receipt"):
        cycle(paths, now_ms=BASE_TIME + 15_001)
    assert not paths.session.exists()
    assert not paths.fill_ledger.exists()


def test_cumulative_loss_latches_buy_before_candidate(tmp_path):
    bought = receipt("after-buy", when=BASE_TIME + 2000,
                     quote="50", base="1", bid="39", trades=(BUY,))
    paths = setup(tmp_path, bought)
    result = cycle(paths, now_ms=BASE_TIME + 2000)
    assert result["status"] == "BLOCKED"
    assert "buy_paused:cumulative_loss_limit" in result["reason"]
    assert result["phase"] == "BUY_PAUSED"
    assert not list(paths.candidates.glob("candidate-*.json"))


def test_changed_account_evidence_fails_before_candidate(tmp_path):
    paths = setup(tmp_path)
    changed = replace(receipt(), account_fingerprint="c" * 64)
    write_verified_receipt(changed, paths.receipt)
    with pytest.raises(ValueError, match="binding mismatch"):
        cycle(paths)
    assert not paths.session.exists()


def test_stale_strategy_bar_cannot_make_candidate(tmp_path):
    paths = setup(tmp_path)
    class StaleStrategy:
        def evaluate(self, snapshot, position):
            return SignalDecision("buy", "old bar", 50.0,
                "1970-01-01T00:28:00Z", expected_edge=0.004)
    with pytest.raises(ValueError, match="bar is stale"):
        run_cycle(paths, now_ms=BASE_TIME, catalog=Catalog(),
                  feed=Feed(), strategy=StaleStrategy())
    assert not paths.session.exists()
