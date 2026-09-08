from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from bstock_web3.catalog import BStockAsset, BStockMarketStatus
from bstock_web3.engine import BStockEngine, BStockEngineConfig, TradePlan
from bstock_web3.strategy import SignalDecision
from bstock_web3.wallet import WalletOrderResult, WalletQuote


class Wallet:
    def __init__(self):
        self.swaps = 0

    def swap(self, **kwargs):
        self.swaps += 1
        raise AssertionError("must not be called")

    def token_balance(self, *args, **kwargs):
        return Decimal("100")


def test_wrong_confirmation_blocks_before_swap(tmp_path):
    wallet = Wallet()
    engine = BStockEngine(BStockEngineConfig(
        mode="live-confirmed", eligibility_file=tmp_path / "eligible.json",
        state_file=tmp_path / "state.json"), wallet=wallet)
    asset = BStockAsset("NVDA", "NVDAB", "0x2", "56", "NVDABUSDT", "1")
    signal = SignalDecision("buy", "test", 200.0, "x", expected_edge=0.01)
    quote = WalletQuote("USDC", "20", "NVDAB", "0.1", 0.01)
    plan = TradePlan("buy", asset, "20", "0x1", "0x2", quote, quote,
                     Decimal("10"), True, "CONFIRM ABCD", signal,
                     datetime.now(timezone.utc))
    with pytest.raises(RuntimeError, match="确认码"):
        engine.execute_confirmed(plan, "CONFIRM WRONG")
    assert wallet.swaps == 0


def test_expired_quote_blocks_before_swap(tmp_path):
    wallet = Wallet()
    engine = BStockEngine(BStockEngineConfig(
        mode="live-confirmed", eligibility_file=tmp_path / "eligible.json",
        state_file=tmp_path / "state.json", max_quote_age_seconds=1), wallet=wallet)
    asset = BStockAsset("NVDA", "NVDAB", "0x2", "56", "NVDABUSDT", "1")
    signal = SignalDecision("buy", "test", 200.0, "x", expected_edge=0.01)
    quote = WalletQuote("USDC", "20", "NVDAB", "0.1", 0.01)
    plan = TradePlan("buy", asset, "20", "0x1", "0x2", quote, quote,
                     Decimal("10"), True, "CONFIRM ABCD", signal,
                     datetime.now(timezone.utc) - timedelta(seconds=2))
    with pytest.raises(RuntimeError, match="Quote 已过期"):
        engine.execute_confirmed(plan, "CONFIRM ABCD")
    assert wallet.swaps == 0


def test_existing_pending_order_blocks_before_wallet_calls(tmp_path):
    wallet = Wallet()
    engine = BStockEngine(BStockEngineConfig(
        mode="live-confirmed", state_file=tmp_path / "state.json"), wallet=wallet)
    engine.state.pending_order_id = "existing-order"
    asset = BStockAsset("NVDA", "NVDAB", "0x2", "56", "NVDABUSDT", "1")
    with pytest.raises(RuntimeError, match="拒绝重复提交"):
        engine.execute_confirmed(_live_plan(asset), "CONFIRM SAFE")
    assert wallet.swaps == 0


def test_corrupt_state_fails_closed(tmp_path):
    state = tmp_path / "state.json"
    state.write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="状态文件损坏"):
        BStockEngine(BStockEngineConfig(state_file=state))


@pytest.mark.parametrize("amount", ["0", "-1"])
def test_non_positive_order_size_is_rejected(amount):
    with pytest.raises(ValueError, match="必须大于 0"):
        BStockEngineConfig(order_size_usdc=Decimal(amount))


class Catalog:
    def __init__(self, asset):
        self.asset = asset
        self.market_status_calls = 0

    def resolve(self, symbol):
        return self.asset

    def market_status(self, asset):
        self.market_status_calls += 1
        return BStockMarketStatus(True, "TRADING", None, "OPEN")


class PendingWallet:
    def __init__(self, result=None, fail_after_submit=False):
        self.result = result
        self.fail_after_submit = fail_after_submit

    def token_balance(self, *args, **kwargs):
        return Decimal("100")

    def swap(self, *, on_submitted, **kwargs):
        on_submitted("order-pending", datetime.now(timezone.utc))
        if self.fail_after_submit:
            raise RuntimeError("status endpoint offline")
        return self.result

    def order_status(self, order_id):
        return self.result


def _write_eligibility(path, asset):
    path.write_text(json.dumps({
        "effective_from_utc": "2026-01-01T00:00:00Z",
        "effective_to_utc": "2026-12-31T23:59:59Z",
        "assets": [{"symbol": asset.symbol,
                    "contract_address": asset.contract_address}],
    }), encoding="utf-8")


def _live_plan(asset):
    signal = SignalDecision("buy", "test", 200.0, "x", expected_edge=0.01)
    quote = WalletQuote("USDC", "20", "NVDAB", "0.1", 0.01)
    return TradePlan("buy", asset, "20", "0x1", asset.contract_address,
                     quote, quote, Decimal("10"), True, "CONFIRM SAFE",
                     signal, datetime.now(timezone.utc))


def test_submission_is_persisted_even_if_status_query_fails(tmp_path):
    asset = BStockAsset("NVDA", "NVDAB", "0x2", "56", "NVDABUSDT", "1")
    eligibility = tmp_path / "eligible.json"
    _write_eligibility(eligibility, asset)
    wallet = PendingWallet(fail_after_submit=True)
    engine = BStockEngine(BStockEngineConfig(
        mode="live-confirmed", eligibility_file=eligibility,
        state_file=tmp_path / "state.json"), catalog=Catalog(asset), wallet=wallet)
    with pytest.raises(RuntimeError, match="offline"):
        engine.execute_confirmed(_live_plan(asset), "CONFIRM SAFE")
    assert engine.state.pending_order_id == "order-pending"
    persisted = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert persisted["pending_order_id"] == "order-pending"


def test_pending_order_blocks_new_market_evaluation(tmp_path):
    asset = BStockAsset("NVDA", "NVDAB", "0x2", "56", "NVDABUSDT", "1")
    catalog = Catalog(asset)
    pending = WalletOrderResult("PENDING", "order-pending", None, "20", None, {})
    engine = BStockEngine(BStockEngineConfig(
        mode="live-confirmed", state_file=tmp_path / "state.json"),
        catalog=catalog, wallet=PendingWallet(pending))
    engine.state.pending_order_id = "order-pending"
    engine.state.pending_action = "buy"
    engine.state.pending_from_amount = "20"
    engine.state.pending_submitted_at = datetime.now(timezone.utc).isoformat()
    engine._save_state()
    event = engine.evaluate_once()
    assert event.signal.reason == "pending_order:order-pending"
    assert catalog.market_status_calls == 0


def test_finished_pending_buy_is_reconciled_once(tmp_path):
    asset = BStockAsset("NVDA", "NVDAB", "0x2", "56", "NVDABUSDT", "1")
    catalog = Catalog(asset)
    finished = WalletOrderResult("FINISHED", "order-pending", "0xtx", "20", "0.1", {})
    engine = BStockEngine(BStockEngineConfig(
        mode="live-confirmed", state_file=tmp_path / "state.json"),
        catalog=catalog, wallet=PendingWallet(finished))
    engine.state.pending_order_id = "order-pending"
    engine.state.pending_action = "buy"
    engine.state.pending_from_amount = "20"
    engine.state.pending_submitted_at = datetime.now(timezone.utc).isoformat()
    engine._save_state()
    event = engine.evaluate_once()
    assert event.signal.reason == "pending_order_reconciled:order-pending"
    assert engine.state.position_quantity == "0.1"
    assert engine.state.entry_price == "2.0E+2"
    assert engine.state.pending_order_id is None


def test_confirmation_cannot_be_reused_after_finished_order(tmp_path):
    asset = BStockAsset("NVDA", "NVDAB", "0x2", "56", "NVDABUSDT", "1")
    eligibility = tmp_path / "eligible.json"
    _write_eligibility(eligibility, asset)
    finished = WalletOrderResult("FINISHED", "order-pending", "0xtx", "20", "0.1", {})
    engine = BStockEngine(BStockEngineConfig(
        mode="live-confirmed", eligibility_file=eligibility,
        state_file=tmp_path / "state.json"),
        catalog=Catalog(asset), wallet=PendingWallet(finished))
    plan = _live_plan(asset)
    engine.execute_confirmed(plan, "CONFIRM SAFE")
    persisted = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert persisted["position_quantity"] == "0.1"
    assert persisted["pending_order_id"] is None
    with pytest.raises(RuntimeError, match="已经提交过"):
        engine.execute_confirmed(plan, "CONFIRM SAFE")

