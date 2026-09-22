from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from bstock_web3.catalog import BStockAsset
from bstock_web3.mcp_bridge import (MCP_SPOT_READ_TOOLS,
    McpAccountBinding, build_mcp_spot_plan, build_mcp_spot_read_request,
    load_mcp_account_binding, load_mcp_plan,
    load_or_create_mcp_account_binding, write_mcp_plan,
    write_mcp_read_request)
from bstock_web3.strategy import SignalDecision


ASSET = BStockAsset("NVDA", "NVDAB", "0x02fc", "56", "NVDABUSDT", "1")
BINDING = McpAccountBinding(
    "1.0", "agentic-primary", "sha256(salt-bytes+uid-ascii)",
    "a" * 64, "b" * 64)


def test_buy_plan_targets_agentic_sub_account_spot_without_credentials():
    signal = SignalDecision(
        "buy", "mtf_ema_confirmed_entry", 220.0, "2026-09-07T15:00:00Z",
        trend_spread=0.002, expected_edge=0.004, strategy_id="mtf",
    )
    plan = build_mcp_spot_plan(ASSET, signal, amount_usdt=Decimal("20"),
                               account_binding=BINDING)
    assert plan.transport == "codex-binance-agent-os-mcp"
    assert plan.account_scope == "existing-host-selected-agentic-sub-account"
    assert plan.required_tool == "spot.newOrder"
    assert plan.lookup_tool == "spot.getOrder"
    assert plan.required_preflight_tools == MCP_SPOT_READ_TOOLS
    expected = {
        "symbol": "NVDABUSDT", "side": "BUY", "type": "MARKET",
        "quoteOrderQty": "20", "newOrderRespType": "FULL",
    }
    assert plan.order_arguments == expected
    encoded = str(plan.to_dict()).lower()
    assert "api_key" not in encoded
    assert "access_token" not in encoded
    assert "private_key" not in encoded


def test_sell_plan_requires_a_position_quantity():
    signal = SignalDecision(
        "sell", "one_minute_cross_down", 219.0, "2026-09-07T15:01:00Z",
        expected_edge=0.004, strategy_id="mtf",
    )
    with pytest.raises(ValueError, match="position_quantity"):
        build_mcp_spot_plan(ASSET, signal, amount_usdt=Decimal("20"),
                            account_binding=BINDING)


def test_risk_exit_is_not_blocked_by_the_buy_edge_gate():
    signal = SignalDecision(
        "sell", "fixed_stop_loss", 215.0, "2026-09-07T15:01:00Z",
        expected_edge=0, strategy_id="mtf",
    )
    plan = build_mcp_spot_plan(
        ASSET, signal, amount_usdt=Decimal("20"),
        position_quantity=Decimal("0.125"), account_binding=BINDING,
    )
    assert plan.side == "SELL"
    assert plan.order_arguments["quantity"] == "0.125"


def test_hold_signal_never_creates_an_order_plan():
    signal = SignalDecision("hold", "no_signal", 220.0, "x",
                            expected_edge=0.004, strategy_id="mtf")
    with pytest.raises(ValueError, match="buy/sell"):
        build_mcp_spot_plan(ASSET, signal, amount_usdt=Decimal("20"),
                            account_binding=BINDING)


def test_order_plan_delegates_confirmation_and_never_contains_auth_material():
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    signal = SignalDecision("buy", "test", 220.0, "x", expected_edge=0.004,
                            strategy_id="mtf")
    plan = build_mcp_spot_plan(
        ASSET, signal, amount_usdt=Decimal("20"), now=now, max_age_seconds=45,
        account_binding=BINDING,
    )
    payload = plan.to_dict()
    assert payload["schema_version"] == "3.0"
    assert payload["account_binding"]["fingerprint"] == "b" * 64
    assert payload["risk_controls"]["confirmation_owner"] == "SUPPORTED_MCP_HOST"
    assert payload["risk_controls"]["local_oauth_prohibited"] is True
    encoded = str(payload).lower()
    assert "confirmation" not in payload
    assert "access_token" not in encoded and "client_id" not in encoded
    with pytest.raises(RuntimeError, match="expired"):
        plan.require_host_preflightable(now=now + timedelta(seconds=46))
    plan.require_host_preflightable(now=now + timedelta(seconds=20))


def test_plan_identity_is_stable_and_strictly_reloadable(tmp_path):
    signal = SignalDecision("buy", "test", 220.0, "2026-09-07T15:00:00Z",
                            expected_edge=0.004, strategy_id="mtf")
    first = build_mcp_spot_plan(ASSET, signal, amount_usdt=Decimal("20"),
        account_binding=BINDING,
        now=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc))
    second = build_mcp_spot_plan(ASSET, signal, amount_usdt=Decimal("20"),
        account_binding=BINDING,
        now=datetime(2026, 9, 7, 12, 1, tzinfo=timezone.utc))
    assert first.signal_fingerprint == second.signal_fingerprint
    path = tmp_path / "plan.json"
    write_mcp_plan(first, path)
    assert load_mcp_plan(path) == first
    payload = json.loads(json.dumps(first.to_dict()))
    payload["order_arguments"]["quoteOrderQty"] = "21"
    with pytest.raises(ValueError, match="identity"):
        type(first).from_dict(payload)


@pytest.mark.parametrize(("field", "value"), [
    ("expected_edge_bps", "41"),
    ("max_plan_age_seconds", 44),
])
def test_plan_rejects_tampered_risk_metadata(field, value):
    signal = SignalDecision("buy", "test", 220.0,
                            "2026-09-07T15:00:00Z",
                            expected_edge=0.004, strategy_id="mtf")
    candidate = build_mcp_spot_plan(
        ASSET, signal, amount_usdt=Decimal("20"), max_age_seconds=45,
        account_binding=BINDING,
        now=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc))
    payload = json.loads(json.dumps(candidate.to_dict()))
    payload["risk_controls"][field] = value
    with pytest.raises(ValueError, match="risk controls"):
        type(candidate).from_dict(payload)


def test_order_plan_requires_enrolled_binding_and_registered_strategy():
    signal = SignalDecision("buy", "test", 220.0, "x", expected_edge=0.004,
                            strategy_id="mtf")
    with pytest.raises(ValueError, match="指纹"):
        build_mcp_spot_plan(ASSET, signal, amount_usdt=Decimal("20"),
            account_binding=McpAccountBinding.create())
    with pytest.raises(ValueError, match="统一策略ID"):
        build_mcp_spot_plan(ASSET, SignalDecision(
            "buy", "test", 220.0, "x", expected_edge=0.004),
            amount_usdt=Decimal("20"), account_binding=BINDING)


def test_read_request_targets_existing_codex_host_without_login_material(tmp_path):
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    request = build_mcp_spot_read_request("btcusdt", now=now)
    assert request.host == "codex"
    assert request.transport == "codex-binance-agent-os-mcp"
    assert request.account_scope == "existing-host-selected-agentic-sub-account"
    assert request.required_tools == MCP_SPOT_READ_TOOLS
    assert request.account_binding["fingerprint"] is None
    assert len(request.account_binding["salt"]) == 64
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


def test_account_binding_is_created_once_and_not_replaced(tmp_path):
    path = tmp_path / "binding.json"
    first = load_or_create_mcp_account_binding(path)
    second = load_or_create_mcp_account_binding(path)
    assert first == second == load_mcp_account_binding(path)
    assert first.fingerprint is None
    assert McpAccountBinding.from_dict(first.to_dict()) == first
