from datetime import datetime, timezone
from decimal import Decimal

import pytest

from bstock_web3.catalog import BStockAsset
from bstock_web3.execution_safety import ExecutionPhase
from bstock_web3.mcp_bridge import (McpAccountBinding, build_mcp_spot_plan,
    write_mcp_plan)
from bstock_web3.mcp_desktop_rehearsal import prepare_desktop_rehearsal
from bstock_web3.mcp_execution_handoff import McpSpotSubmissionTicket
from bstock_web3.mcp_host_receipt import VerifiedSpotHostReceipt
from bstock_web3.strategy import SignalDecision


NOW = 2_000_000
NOW_DT = datetime.fromtimestamp(NOW / 1000, timezone.utc)
BINDING = McpAccountBinding("1.0", "agentic-primary",
    "sha256(salt-bytes+uid-ascii)", "a" * 64, "b" * 64)


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
    exchange_info = {"symbols":[{
        "symbol":"BTCUSDT", "status":"TRADING",
        "isSpotTradingAllowed":True, "quoteOrderQtyMarketAllowed":True,
        "orderTypes":["MARKET"], "baseAsset":"BTC", "quoteAsset":"USDT",
        "filters":[
            {"filterType":"LOT_SIZE", "minQty":"0.000001",
             "maxQty":"100", "stepSize":"0.000001"},
            {"filterType":"MIN_NOTIONAL", "minNotional":"5",
             "applyToMarket":True},
            {"filterType":"MARKET_LOT_SIZE", "minQty":"0",
             "maxQty":"0", "stepSize":"0"},
        ]}]}
    tools = {
        "spot.getAccount":{"accountType":"SPOT", "canTrade":True,
            "balances":[{"asset":"BTC", "free":"0", "locked":"0"},
                        {"asset":"USDT", "free":"100", "locked":"0"}]},
        "spot.getOpenOrders":[], "spot.myTrades":[], "spot.allOrders":[],
        "spot.accountCommission":{"symbol":"BTCUSDT"},
        "spot.exchangeInfo":exchange_info,
        "spot.tickerBookTicker":{"symbol":"BTCUSDT", "bidPrice":"99",
                                 "askPrice":"100"},
    }
    return VerifiedSpotHostReceipt("request-001", "BTCUSDT",
        "agentic-primary", "b" * 64, _utc(NOW), "BTC", "USDT",
        tools, BINDING, False)


def _utc(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace(
        "+00:00", "Z")


def test_rehearsal_consumes_exact_confirmation_without_dispatch_ticket(tmp_path):
    path, plan = candidate(tmp_path)
    session = prepare_desktop_rehearsal(path, verified_receipt(), tmp_path,
        now_ms=NOW)
    fingerprint = session.preview["arguments"]["newClientOrderId"]
    output, report = session.confirm(session.preview["confirmation"],
                                     now_ms=NOW + 1)
    assert output.is_file() and session.closed and not session.lock.held
    assert report.dispatch_prohibited is True
    assert report.required_tool is None
    assert report.execution_phase == "PREPARED"
    assert report.arguments["newClientOrderId"] == fingerprint
    assert report.plan_id == plan.plan_id
    assert session.executor.journal.get(report.execution_fingerprint).phase \
        == ExecutionPhase.PREPARED
    encoded = output.read_text(encoding="utf-8")
    assert "spot.newOrder" not in encoded
    assert session.preview["confirmation"] not in encoded
    with pytest.raises(ValueError):
        McpSpotSubmissionTicket.from_dict(report.to_dict())


def test_rehearsal_cancel_releases_lock_and_writes_no_report(tmp_path):
    path, _ = candidate(tmp_path)
    session = prepare_desktop_rehearsal(path, verified_receipt(), tmp_path,
        now_ms=NOW)
    output = session.report_path
    session.cancel(); session.cancel()
    assert session.closed and not session.lock.held
    assert not output.exists()


def test_rehearsal_still_enforces_risk_and_exact_phrase(tmp_path):
    path, _ = candidate(tmp_path)
    with pytest.raises(RuntimeError, match="blocked"):
        prepare_desktop_rehearsal(path, verified_receipt(), tmp_path,
            daily_equity_loss=Decimal("10"), now_ms=NOW)
    session = prepare_desktop_rehearsal(path, verified_receipt(), tmp_path,
        now_ms=NOW + 1)
    with pytest.raises(RuntimeError, match="mismatch"):
        session.confirm("MCP CONFIRM " + "0" * 24, now_ms=NOW + 2)
    assert session.closed and not session.lock.held
