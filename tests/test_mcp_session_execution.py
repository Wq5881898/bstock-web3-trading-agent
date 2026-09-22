from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from bstock_web3.automation_policy import AutomationPolicyConfig
from bstock_web3.catalog import BStockAsset
from bstock_web3.execution_contract import ProductType
from bstock_web3.execution_safety import ExecutionPhase, McpReconciliationEvidence
from bstock_web3.mcp_bridge import McpAccountBinding
from bstock_web3.mcp_confirmed import SpotMarketRules
from bstock_web3.mcp_execution_result import MCP_SPOT_TERMINAL_TOOLS
from bstock_web3.mcp_session import (McpSessionBinding, McpSessionPhase,
                                     McpTradingSession)
from bstock_web3.mcp_session_execution import McpSessionExecution
from bstock_web3.spot_accounting import SpotFillLedger
from bstock_web3.strategy import SignalDecision


NOW = 2_000_000_000_000
NOW_DT = datetime.fromtimestamp(NOW / 1000, timezone.utc)
DAY = NOW_DT.date().isoformat()
ASSET = BStockAsset("NVDA", "NVDAB", "0x02fc", "56", "NVDABUSDT", "1")
ACCOUNT = McpAccountBinding(
    "1.0", "agentic-primary", "sha256(salt-bytes+uid-ascii)",
    "a" * 64, "b" * 64)
POLICY = AutomationPolicyConfig()
BINDING = McpSessionBinding.create(
    ACCOUNT, symbol="NVDABUSDT", strategy_id="mtf",
    strategy_config={"fast": 9}, risk_config=POLICY)


def evidence(at=NOW, **changes):
    values = dict(
        evidence_id=f"mcp-exec-{at}", account_ref="agentic-primary",
        symbol="NVDABUSDT", product=ProductType.SPOT, risk_day=DAY,
        observed_at_ms=at, account_checked=True, balances_checked=True,
        open_orders_checked=True, fills_checked=True, can_trade=True,
        available_quote=Decimal("200"), position_quantity=Decimal("0"),
        position_cost=Decimal("0"), daily_equity_loss=Decimal("0"))
    values.update(changes)
    return McpReconciliationEvidence(**values)


def rules():
    return SpotMarketRules("NVDABUSDT", "NVDAB", "USDT",
        Decimal("0.001"), Decimal("1000"), Decimal("0.001"), Decimal("5"))


def exchange_info():
    return {"symbols": [{"symbol": "NVDABUSDT", "baseAsset": "NVDAB",
        "quoteAsset": "USDT", "status": "TRADING",
        "isSpotTradingAllowed": True, "quoteOrderQtyMarketAllowed": True,
        "orderTypes": ["MARKET"], "filters": [
            {"filterType": "LOT_SIZE", "minQty": "0.001",
             "maxQty": "1000", "stepSize": "0.001"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "5",
             "applyToMarket": True}]}]}


def ready_session(tmp_path):
    session = McpTradingSession(tmp_path / "session.json", BINDING, POLICY)
    session.start(evidence(), now_ms=NOW)
    result = session.prepare_candidate(
        ASSET, SignalDecision("buy", "test", 200.0,
            NOW_DT.isoformat().replace("+00:00", "Z"),
            expected_edge=0.004, strategy_id="mtf"),
        evidence(), ACCOUNT, output_dir=tmp_path / "candidates",
        now_ms=NOW + 1)
    assert result.status == "READY"
    return session


def terminal_receipt(ticket):
    order = {"symbol": "NVDABUSDT",
        "clientOrderId": ticket.arguments["newClientOrderId"],
        "side": "BUY", "type": "MARKET", "orderId": 123,
        "status": "FILLED", "executedQty": "0.5",
        "cummulativeQuoteQty": "100"}
    trade = {"id": 1, "orderId": 123, "symbol": "NVDABUSDT",
        "time": NOW + 3, "isBuyer": True, "qty": "0.5",
        "quoteQty": "100", "commission": "0", "commissionAsset": "USDT"}
    results = {
        "spot.getOrder": order,
        "spot.getAccount": {"accountType": "SPOT", "canTrade": True,
            "balances": [{"asset": "NVDAB", "free": "0.5", "locked": "0"},
                         {"asset": "USDT", "free": "100", "locked": "0"}]},
        "spot.getOpenOrders": [], "spot.myTrades": [trade],
        "spot.allOrders": [dict(order)], "spot.accountCommission": {},
        "spot.exchangeInfo": exchange_info(),
        "spot.tickerBookTicker": {"symbol": "NVDABUSDT",
            "bidPrice": "199", "askPrice": "200"},
    }
    assert tuple(results) == MCP_SPOT_TERMINAL_TOOLS
    return {"schema_version": "1.0",
        "receipt_id": "mcp-exec-20330518T033323Z-1234abcd",
        "operation": "SUBMIT_CONFIRMED_SPOT_ORDER_RESULT", "host": "codex",
        "transport": "codex-binance-agent-os-mcp", "plan_id": ticket.plan_id,
        "signal_fingerprint": ticket.signal_fingerprint,
        "execution_fingerprint": ticket.execution_fingerprint,
        "account_ref": "agentic-primary", "account_fingerprint": "b" * 64,
        "symbol": "NVDABUSDT",
        "observed_at": (NOW_DT + timedelta(milliseconds=3)).isoformat().replace(
            "+00:00", "Z"), "outcome": "TERMINAL",
        "completed_tools": list(MCP_SPOT_TERMINAL_TOOLS),
        "pagination": {"trades_complete": True, "orders_complete": True},
        "tool_results": results}


def unknown_receipt(ticket):
    payload = terminal_receipt(ticket)
    payload.update(outcome="UNKNOWN", completed_tools=[], tool_results={},
                   pagination={"trades_complete": False,
                               "orders_complete": False})
    return payload


def coordinator(session, tmp_path):
    return McpSessionExecution(
        session, ACCOUNT, journal_path=tmp_path / "execution.json",
        ticket_dir=tmp_path / "tickets")


def test_preview_confirmation_ticket_and_terminal_import_close_the_loop(tmp_path):
    session = ready_session(tmp_path)
    with coordinator(session, tmp_path) as flow:
        preview = flow.prepare_preview(evidence(NOW + 1), rules(),
                                       now_ms=NOW + 1)
        assert preview["arguments"]["quoteOrderQty"] == "100"
        ticket, ticket_path = flow.confirm_to_ticket(
            preview["confirmation"], evidence(NOW + 2), now_ms=NOW + 2)
        assert ticket_path.exists()
        assert session.phase == McpSessionPhase.WAITING_RESULT
        assert session.pending["status"] == "TICKET_READY"
        receipt_path = tmp_path / "host-result.json"
        receipt_path.write_text(json.dumps(terminal_receipt(ticket)),
                                encoding="utf-8")
        ledger = SpotFillLedger(tmp_path / "fills.json",
            account_ref="agentic-primary", symbol="NVDABUSDT",
            base_asset="NVDAB", quote_asset="USDT")
        imported = flow.import_result(
            receipt_path, ledger, daily_equity_loss=Decimal("0"),
            now_ms=NOW + 4)
    assert imported.phase == ExecutionPhase.FILLED
    assert session.phase == McpSessionPhase.RUNNING
    assert session.pending is None
    assert ledger.summary.quantity == Decimal("0.5")


def test_wrong_confirmation_never_advances_session(tmp_path):
    session = ready_session(tmp_path)
    with coordinator(session, tmp_path) as flow:
        flow.prepare_preview(evidence(NOW + 1), rules(), now_ms=NOW + 1)
        with pytest.raises(RuntimeError, match="mismatch"):
            flow.confirm_to_ticket("WRONG", evidence(NOW + 2), now_ms=NOW + 2)
    assert session.phase == McpSessionPhase.WAITING_CONFIRMATION
    assert session.pending["status"] == "READY"


def test_unknown_host_result_enters_lookup_only_recovery(tmp_path):
    session = ready_session(tmp_path)
    with coordinator(session, tmp_path) as flow:
        preview = flow.prepare_preview(evidence(NOW + 1), rules(), now_ms=NOW + 1)
        ticket, _ = flow.confirm_to_ticket(
            preview["confirmation"], evidence(NOW + 2), now_ms=NOW + 2)
        receipt_path = tmp_path / "unknown.json"
        receipt_path.write_text(json.dumps(unknown_receipt(ticket)),
                                encoding="utf-8")
        imported = flow.import_result(
            receipt_path, None, daily_equity_loss=Decimal("0"),
            now_ms=NOW + 4)
    assert imported.phase == ExecutionPhase.UNKNOWN
    assert session.phase == McpSessionPhase.RECOVERY_ONLY
    assert session.pending["status"] == "UNKNOWN"


def test_ticket_write_failure_is_fail_closed(tmp_path, monkeypatch):
    session = ready_session(tmp_path)
    with coordinator(session, tmp_path) as flow:
        preview = flow.prepare_preview(evidence(NOW + 1), rules(), now_ms=NOW + 1)
        monkeypatch.setattr(
            "bstock_web3.mcp_session_execution.write_submission_ticket",
            lambda *_: (_ for _ in ()).throw(OSError("disk failure")))
        with pytest.raises(OSError, match="disk failure"):
            flow.confirm_to_ticket(
                preview["confirmation"], evidence(NOW + 2), now_ms=NOW + 2)
        record = flow.journal.records()[0]
        assert record.phase == ExecutionPhase.UNKNOWN
    assert session.phase == McpSessionPhase.RECOVERY_ONLY
    assert session.recovery_reason == "submission_ticket_interrupted"


def test_stop_waits_for_terminal_import(tmp_path):
    session = ready_session(tmp_path)
    with coordinator(session, tmp_path) as flow:
        preview = flow.prepare_preview(evidence(NOW + 1), rules(), now_ms=NOW + 1)
        ticket, _ = flow.confirm_to_ticket(
            preview["confirmation"], evidence(NOW + 2), now_ms=NOW + 2)
        assert session.stop(now_ms=NOW + 2) == McpSessionPhase.STOPPING
        receipt_path = tmp_path / "host-result.json"
        receipt_path.write_text(json.dumps(terminal_receipt(ticket)),
                                encoding="utf-8")
        ledger = SpotFillLedger(tmp_path / "fills.json",
            account_ref="agentic-primary", symbol="NVDABUSDT",
            base_asset="NVDAB", quote_asset="USDT")
        flow.import_result(receipt_path, ledger,
            daily_equity_loss=Decimal("0"), now_ms=NOW + 4)
    assert session.phase == McpSessionPhase.STOPPED
