from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bstock_web3.catalog import BStockAsset
from bstock_web3.mcp_bridge import (MCP_SPOT_READ_TOOLS,
    build_mcp_spot_plan, build_mcp_spot_read_request,
    write_mcp_read_request)
from bstock_web3.strategy import SignalDecision


ASSET = BStockAsset("NVDA", "NVDAB", "0x02fc", "56", "NVDABUSDT", "1")


def test_buy_plan_targets_agentic_sub_account_spot_without_credentials():
    signal = SignalDecision(
        "buy", "mtf_ema_confirmed_entry", 220.0, "2026-09-07T15:00:00Z",
        trend_spread=0.002, expected_edge=0.004,
    )
    plan = build_mcp_spot_plan(ASSET, signal, amount_usdt=Decimal("20"))
    assert plan.transport == "codex-binance-agent-os-mcp"
    assert plan.account_scope == "existing-host-selected-agentic-sub-account"
    assert plan.required_tool == "spot.newOrder"
    assert plan.order_arguments == {
        "symbol": "NVDABUSDT", "side": "BUY", "type": "MARKET",
        "quoteOrderQty": "20", "newOrderRespType": "FULL",
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
    assert plan.order_arguments["quantity"] == "0.125"


def test_hold_signal_never_creates_an_order_plan():
    signal = SignalDecision("hold", "no_signal", 220.0, "x", expected_edge=0.004)
    with pytest.raises(ValueError, match="buy/sell"):
        build_mcp_spot_plan(ASSET, signal, amount_usdt=Decimal("20"))


def test_order_plan_delegates_confirmation_and_never_contains_auth_material():
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    signal = SignalDecision("buy", "test", 220.0, "x", expected_edge=0.004)
    plan = build_mcp_spot_plan(
        ASSET, signal, amount_usdt=Decimal("20"), now=now, max_age_seconds=45
    )
    payload = plan.to_dict()
    assert payload["schema_version"] == "2.0"
    assert payload["risk_controls"]["confirmation_owner"] == "SUPPORTED_MCP_HOST"
    assert payload["risk_controls"]["local_oauth_prohibited"] is True
    encoded = str(payload).lower()
    assert "confirmation" not in payload
    assert "access_token" not in encoded and "client_id" not in encoded
    with pytest.raises(RuntimeError, match="confirmation"):
        plan.require_host_dispatchable(host_confirmed=False, now=now)
    with pytest.raises(RuntimeError, match="expired"):
        plan.require_host_dispatchable(
            host_confirmed=True, now=now + timedelta(seconds=46))
    plan.require_host_dispatchable(host_confirmed=True,
                                   now=now + timedelta(seconds=20))


def test_read_request_targets_existing_codex_host_without_login_material(tmp_path):
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    request = build_mcp_spot_read_request("btcusdt", now=now)
    assert request.host == "codex"
    assert request.transport == "codex-binance-agent-os-mcp"
    assert request.account_scope == "existing-host-selected-agentic-sub-account"
    assert request.required_tools == MCP_SPOT_READ_TOOLS
    assert request.requirements["local_oauth_prohibited"] is True
    request.require_current(now=now + timedelta(seconds=299))
    with pytest.raises(RuntimeError, match="expired"):
        request.require_current(now=now + timedelta(seconds=301))
    path = tmp_path / "read.json"
    write_mcp_read_request(request, path)
    contents = path.read_text(encoding="utf-8")
    assert '"symbol": "BTCUSDT"' in contents
    lowered = contents.lower()
    assert "access_token" not in lowered and "redirect_uri" not in lowered


@pytest.mark.parametrize("symbol", ["", "BTC-USDT", "X" * 33])
def test_read_request_rejects_invalid_symbol(symbol):
    with pytest.raises(ValueError, match="symbol"):
        build_mcp_spot_read_request(symbol)
