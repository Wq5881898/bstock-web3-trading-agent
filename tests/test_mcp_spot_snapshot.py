from copy import deepcopy
from decimal import Decimal

import pytest

from bstock_web3.mcp_spot_snapshot import (LocalRiskMetrics,
    build_bound_mcp_spot_evidence, build_local_risk_metrics,
    build_mcp_spot_evidence)
from bstock_web3.spot_equity_risk import EquityRiskResult


def fixture():
    return dict(
        account={"uid":123, "accountType":"SPOT", "canTrade":True,
            "balances":[{"asset":"BTC", "free":"0.00023976", "locked":"0"},
                        {"asset":"USDT", "free":"250.00", "locked":"0"}]},
        open_orders=[],
        trades=[{"symbol":"BTCUSDT", "orderId":456, "time":1000,
            "qty":"0.00024000", "quoteQty":"19.15919760",
            "commission":"0.00000024", "commissionAsset":"BTC",
            "isBuyer":True}],
        all_orders=[{"symbol":"BTCUSDT", "orderId":456, "status":"FILLED"}],
        book={"symbol":"BTCUSDT", "bidPrice":"79800", "askPrice":"79801"},
        account_ref="agentic-test", expected_uid=123, symbol="BTCUSDT",
        base_asset="BTC", quote_asset="USDT", risk_day="2026-09-12",
        observed_at_ms=2000, evidence_id="mcp-read-0001",
        risk=LocalRiskMetrics(Decimal("0")), trade_history_complete=True)


def test_real_shape_reconciles_fee_adjusted_position_and_cost():
    result = build_mcp_spot_evidence(**fixture())
    assert result.to_snapshot().reconciled and result.can_trade
    assert result.available_quote == Decimal("250.00")
    assert result.position_quantity == Decimal("0.00023976")
    assert result.position_cost == Decimal("19.15919760")


def test_wrong_agentic_account_is_rejected():
    values = fixture()
    values["expected_uid"] = 999
    with pytest.raises(ValueError, match="identity mismatch"):
        build_mcp_spot_evidence(**values)


def test_sanitized_account_requires_verified_opaque_binding():
    values = fixture()
    values["account"] = deepcopy(values["account"])
    values["account"].pop("uid")
    values.pop("expected_uid")
    values["account_binding_verified"] = True
    result = build_bound_mcp_spot_evidence(**values)
    assert result.account_ref == "agentic-test"
    values["account_binding_verified"] = False
    with pytest.raises(ValueError, match="binding"):
        build_bound_mcp_spot_evidence(**values)


def test_incomplete_history_or_unexplained_balance_is_rejected():
    values = fixture()
    values["trade_history_complete"] = False
    with pytest.raises(ValueError, match="Complete paginated"):
        build_mcp_spot_evidence(**values)
    values = fixture()
    values["account"] = deepcopy(values["account"])
    values["account"]["balances"][0]["free"] = "0.1"
    with pytest.raises(ValueError, match="does not reconcile"):
        build_mcp_spot_evidence(**values)


def test_open_order_blocks_future_policy_through_pending_id():
    values = fixture()
    values["open_orders"] = [{"symbol":"BTCUSDT", "orderId":789}]
    result = build_mcp_spot_evidence(**values)
    assert result.pending_order_id == "789"


def test_third_asset_fee_fails_closed_until_risk_accounting_supports_it():
    values = fixture()
    values["trades"] = deepcopy(values["trades"])
    values["trades"][0].update(commission="0.001", commissionAsset="BNB")
    with pytest.raises(ValueError, match="Third-asset commission"):
        build_mcp_spot_evidence(**values)


def test_local_risk_metrics_come_from_equity_and_complete_fills():
    rows = [
        {"id":1, "symbol":"BTCUSDT", "orderId":10,
         "time":1_788_998_400_001, "qty":"1", "quoteQty":"100",
         "commission":"0", "commissionAsset":"BTC", "isBuyer":True},
        {"id":2, "symbol":"BTCUSDT", "orderId":11,
         "time":1_788_998_400_002, "qty":"1", "quoteQty":"90",
         "commission":"0", "commissionAsset":"USDT", "isBuyer":False}]
    equity = EquityRiskResult(Decimal("10"), Decimal("190"),
                              Decimal("190"), Decimal("200"))
    result = build_local_risk_metrics(trades=rows, symbol="BTCUSDT",
        base_asset="BTC", quote_asset="USDT", risk_day="2026-09-10",
        equity_result=equity)
    assert result == LocalRiskMetrics(Decimal("10"), 1, 1,
                                      1_788_998_400_001)


def test_local_risk_metrics_reject_unverified_equity():
    with pytest.raises(ValueError, match="Verified"):
        build_local_risk_metrics(trades=[], symbol="BTCUSDT", base_asset="BTC",
            quote_asset="USDT", risk_day="2026-09-10", equity_result={})
