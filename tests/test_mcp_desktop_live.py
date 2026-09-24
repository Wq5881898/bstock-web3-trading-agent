from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from bstock_web3.catalog import BStockAsset
from bstock_web3.execution_safety import ExecutionPhase
from bstock_web3.mcp_bridge import (MCP_SPOT_READ_TOOLS, McpAccountBinding,
    build_mcp_spot_plan, write_mcp_plan)
from bstock_web3.mcp_desktop_live import prepare_desktop_live_handoff
from bstock_web3.mcp_equity_guard import McpSpotEquityGuard
from bstock_web3.mcp_execution_result import MCP_SPOT_TERMINAL_TOOLS
from bstock_web3.mcp_host_receipt import VerifiedSpotHostReceipt
from bstock_web3.strategy import SignalDecision


NOW = 2_000_000
NOW_DT = datetime.fromtimestamp(NOW / 1000, timezone.utc)
BINDING = McpAccountBinding("1.0", "agentic-primary",
    "sha256(salt-bytes+uid-ascii)", "a" * 64, "b" * 64)


def _utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def exchange_info():
    return {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING",
        "isSpotTradingAllowed": True, "quoteOrderQtyMarketAllowed": True,
        "orderTypes": ["MARKET"], "baseAsset": "BTC", "quoteAsset": "USDT",
        "filters": [
            {"filterType": "LOT_SIZE", "minQty": "0.000001",
             "maxQty": "100", "stepSize": "0.000001"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "5",
             "applyToMarket": True},
            {"filterType": "MARKET_LOT_SIZE", "minQty": "0",
             "maxQty": "0", "stepSize": "0"}]}]}


def candidate(tmp_path):
    asset = BStockAsset("BTC", "BTC", "0x02fc", "56", "BTCUSDT", "1")
    signal = SignalDecision("buy", "fixture", 100.0,
        "1970-01-01T00:33:20Z", expected_edge=0.004, strategy_id="mtf")
    plan = build_mcp_spot_plan(asset, signal, amount_usdt=Decimal("10"),
        account_binding=BINDING, now=NOW_DT)
    path = tmp_path / "btc-order-plan.json"
    write_mcp_plan(plan, path)
    return path, plan


def verified_receipt():
    tools = {
        "spot.getAccount": {"accountType": "SPOT", "canTrade": True,
            "balances": [{"asset": "BTC", "free": "0", "locked": "0"},
                         {"asset": "USDT", "free": "100", "locked": "0"}]},
        "spot.getOpenOrders": [], "spot.myTrades": [], "spot.allOrders": [],
        "spot.accountCommission": {"symbol": "BTCUSDT"},
        "spot.exchangeInfo": exchange_info(),
        "spot.tickerBookTicker": {"symbol": "BTCUSDT", "bidPrice": "99",
                                   "askPrice": "100"},
    }
    assert tuple(tools) == MCP_SPOT_READ_TOOLS
    return VerifiedSpotHostReceipt("request-001", "BTCUSDT",
        "agentic-primary", "b" * 64, _utc(NOW_DT), "BTC", "USDT",
        tools, BINDING, False)


def initialize_risk(tmp_path, receipt=None):
    receipt = receipt or verified_receipt()
    path = tmp_path / "live" / "btcusdt-equity-risk.json"
    with McpSpotEquityGuard(
            path, account_ref=receipt.account_ref,
            account_fingerprint=receipt.account_fingerprint,
            symbol=receipt.symbol) as guard:
        guard.initialize(receipt, operator_confirmed=True)


def terminal_payload(ticket):
    order = {"symbol": "BTCUSDT",
        "clientOrderId": ticket.arguments["newClientOrderId"],
        "side": "BUY", "type": "MARKET", "orderId": 123,
        "status": "FILLED", "executedQty": "0.1",
        "cummulativeQuoteQty": "10"}
    trade = {"id": 1, "orderId": 123, "symbol": "BTCUSDT", "time": NOW + 2,
        "isBuyer": True, "qty": "0.1", "quoteQty": "10", "commission": "0",
        "commissionAsset": "USDT"}
    results = {"spot.getOrder": order,
        "spot.getAccount": {"accountType": "SPOT", "canTrade": True,
            "balances": [{"asset": "BTC", "free": "0.1", "locked": "0"},
                         {"asset": "USDT", "free": "90", "locked": "0"}]},
        "spot.getOpenOrders": [], "spot.myTrades": [trade],
        "spot.allOrders": [dict(order)], "spot.accountCommission": {},
        "spot.exchangeInfo": exchange_info(),
        "spot.tickerBookTicker": {"symbol": "BTCUSDT", "bidPrice": "99",
                                   "askPrice": "100"}}
    assert tuple(results) == MCP_SPOT_TERMINAL_TOOLS
    return {"schema_version": "1.0",
        "receipt_id": "mcp-exec-19700101T003320Z-1234abcd",
        "operation": "SUBMIT_CONFIRMED_SPOT_ORDER_RESULT", "host": "codex",
        "transport": "codex-binance-agent-os-mcp", "plan_id": ticket.plan_id,
        "signal_fingerprint": ticket.signal_fingerprint,
        "execution_fingerprint": ticket.execution_fingerprint,
        "account_ref": "agentic-primary", "account_fingerprint": "b" * 64,
        "symbol": "BTCUSDT",
        "observed_at": _utc(NOW_DT + timedelta(milliseconds=2)),
        "outcome": "TERMINAL",
        "completed_tools": list(MCP_SPOT_TERMINAL_TOOLS),
        "pagination": {"trades_complete": True, "orders_complete": True},
        "tool_results": results}


def test_desktop_live_handoff_writes_ticket_without_calling_mcp(tmp_path):
    plan_path, _ = candidate(tmp_path)
    initialize_risk(tmp_path)
    session = prepare_desktop_live_handoff(
        plan_path, verified_receipt(), tmp_path, now_ms=NOW)
    assert session.executor.policy.config.max_position_cost == Decimal("10")
    ticket_path, ticket, result_path = session.confirm(
        session.preview["confirmation"], now_ms=NOW + 1)
    assert ticket_path.is_file()
    assert result_path.name.startswith("result-")
    assert ticket.tool == "spot.newOrder"
    assert session.executor.journal.get(ticket.execution_fingerprint).phase \
        == ExecutionPhase.SUBMITTING
    persisted = ticket_path.read_text(encoding="utf-8").lower()
    assert session.preview["confirmation"].lower() not in persisted
    assert "api_key" not in persisted
    session.close()


def test_desktop_live_terminal_import_commits_fill_ledger(tmp_path):
    plan_path, _ = candidate(tmp_path)
    initialize_risk(tmp_path)
    session = prepare_desktop_live_handoff(
        plan_path, verified_receipt(), tmp_path, now_ms=NOW)
    _, ticket, result_path = session.confirm(
        session.preview["confirmation"], now_ms=NOW + 1)
    result_path.write_text(json.dumps(terminal_payload(ticket)),
                           encoding="utf-8")
    imported = session.import_result(now_ms=NOW + 3)
    assert imported.phase == ExecutionPhase.FILLED
    assert imported.fill_summary.quantity == Decimal("0.1")
    assert session.closed and not session.lock.held
    assert session.ledger_path.is_file()


def test_desktop_live_cancel_before_confirmation_is_safe(tmp_path):
    plan_path, _ = candidate(tmp_path)
    initialize_risk(tmp_path)
    session = prepare_desktop_live_handoff(
        plan_path, verified_receipt(), tmp_path, now_ms=NOW)
    session.cancel(); session.cancel()
    assert session.closed and not session.lock.held
    assert session.ticket is None


def test_desktop_live_wrong_confirmation_writes_nothing(tmp_path):
    plan_path, _ = candidate(tmp_path)
    initialize_risk(tmp_path)
    session = prepare_desktop_live_handoff(
        plan_path, verified_receipt(), tmp_path, now_ms=NOW)
    with pytest.raises(RuntimeError, match="mismatch"):
        session.confirm("MCP CONFIRM " + "0" * 24, now_ms=NOW + 1)
    assert session.ticket is None
    assert not list((tmp_path / "live").glob("ticket-*.json"))
    session.cancel()


def test_desktop_live_refuses_missing_confirmed_equity_baseline(tmp_path):
    plan_path, _ = candidate(tmp_path)
    with pytest.raises(RuntimeError, match="Confirmed MCP equity baseline"):
        prepare_desktop_live_handoff(
            plan_path, verified_receipt(), tmp_path, now_ms=NOW)
    assert not list((tmp_path / "live").glob("ticket-*.json"))
