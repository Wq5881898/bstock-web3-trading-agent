from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bstock_web3.catalog import BStockAsset
from bstock_web3.mcp_bridge import build_mcp_spot_plan
from bstock_web3.strategy import SignalDecision


ASSET = BStockAsset("NVDA", "NVDAB", "0x02fc", "56", "NVDABUSDT", "1")


def test_buy_plan_targets_agentic_sub_account_spot_without_credentials():
    signal = SignalDecision(
        "buy", "mtf_ema_confirmed_entry", 220.0, "2026-09-07T15:00:00Z",
        trend_spread=0.002, expected_edge=0.004,
    )
    plan = build_mcp_spot_plan(ASSET, signal, amount_usdt=Decimal("20"))
    assert plan.transport == "binance-agent-os-mcp"
    assert plan.account_scope == "oauth-agentic-sub-account"
    assert plan.required_tool == "spot.newOrder"
    assert plan.order_arguments == {
        "symbol": "NVDABUSDT", "side": "BUY", "type": "MARKET",
        "quoteOrderQty": 20.0, "newOrderRespType": "FULL",
    }
    encoded = str(plan.to_dict()).lower()
    assert "api_key" not in encoded
    assert "access_token" not in encoded
    assert "private_key" not in encoded


def test_sell_plan_requires_a_position_quantity():
    signal = SignalDecision(
        "sell", "one_minute_cross_down", 219.0, "2026-09-07T15:01:00Z",
        expected_edge=0.004,
    )
    with pytest.raises(ValueError, match="position_quantity"):
        build_mcp_spot_plan(ASSET, signal, amount_usdt=Decimal("20"))


def test_risk_exit_is_not_blocked_by_the_buy_edge_gate():
    signal = SignalDecision(
        "sell", "fixed_stop_loss", 215.0, "2026-09-07T15:01:00Z",
        expected_edge=0,
    )
    plan = build_mcp_spot_plan(
        ASSET, signal, amount_usdt=Decimal("20"),
        position_quantity=Decimal("0.125"),
    )
    assert plan.side == "SELL"
    assert plan.order_arguments["quantity"] == 0.125


def test_hold_signal_never_creates_an_order_plan():
    signal = SignalDecision("hold", "no_signal", 220.0, "x", expected_edge=0.004)
    with pytest.raises(ValueError, match="buy/sell"):
        build_mcp_spot_plan(ASSET, signal, amount_usdt=Decimal("20"))


def test_dispatch_requires_exact_confirmation_and_unexpired_plan():
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    signal = SignalDecision("buy", "test", 220.0, "x", expected_edge=0.004)
    plan = build_mcp_spot_plan(
        ASSET, signal, amount_usdt=Decimal("20"), now=now, max_age_seconds=45
    )
    with pytest.raises(RuntimeError, match="确认码"):
        plan.require_dispatchable("MCP CONFIRM WRONG", now=now)
    with pytest.raises(RuntimeError, match="过期"):
        plan.require_dispatchable(
            plan.confirmation, now=now + timedelta(seconds=46)
        )
    plan.require_dispatchable(plan.confirmation, now=now + timedelta(seconds=20))
