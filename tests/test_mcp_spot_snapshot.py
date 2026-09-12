from copy import deepcopy
from decimal import Decimal

import pytest

from bstock_web3.mcp_spot_snapshot import (LocalRiskMetrics,
    build_mcp_spot_evidence)


def fixture():
    return dict(
        account={"uid":123, "accountType":"SPOT", "canTrade":True,
            "balances":[{"asset":"BTC", "free":"0.00011988", "locked":"0"},
                        {"asset":"USDT", "free":"190.42", "locked":"0"}]},
        open_orders=[],
        trades=[{"symbol":"BTCUSDT", "orderId":456, "time":1000,
            "qty":"0.00012000", "quoteQty":"9.57959880",
            "commission":"0.00000012", "commissionAsset":"BTC",
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
    assert result.available_quote == Decimal("190.42")
    assert result.position_quantity == Decimal("0.00011988")
    assert result.position_cost == Decimal("9.57959880")


def test_wrong_agentic_account_is_rejected():
    values = fixture()
    values["expected_uid"] = 999
    with pytest.raises(ValueError, match="identity mismatch"):
        build_mcp_spot_evidence(**values)


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
