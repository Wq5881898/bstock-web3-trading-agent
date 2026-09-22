from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bstock_web3.automation_policy import AutomationPolicy
from bstock_web3.catalog import BStockAsset
from bstock_web3.execution_contract import ProductType
from bstock_web3.execution_lock import ExecutionLock
from bstock_web3.execution_safety import (ExecutionJournal, ExecutionPhase,
    McpReconciliationEvidence)
from bstock_web3.mcp_bridge import (MCP_SPOT_READ_TOOLS, McpAccountBinding,
    build_mcp_spot_plan)
from bstock_web3.mcp_confirmed import ConfirmedSpotExecutor, SpotMarketRules
from bstock_web3.mcp_execution_handoff import (build_submission_ticket,
    prepare_plan_preview)
from bstock_web3.mcp_execution_result import (MCP_SPOT_TERMINAL_TOOLS,
    import_execution_result, load_execution_result_receipt,
    verify_execution_result_receipt, write_verified_execution_result)
from bstock_web3.spot_accounting import SpotFillLedger
from bstock_web3.strategy import SignalDecision


NOW = 2_000_000
NOW_DT = datetime.fromtimestamp(NOW / 1000, timezone.utc)
ASSET = BStockAsset("BTC", "BTC", "none", "0", "BTCUSDT", "1")
BINDING = McpAccountBinding(
    "1.0", "agentic-primary", "sha256(salt-bytes+uid-ascii)",
    "a" * 64, "b" * 64)


def _utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def evidence(**changes):
    values = dict(evidence_id="mcp-evidence-001",
        account_ref="agentic-primary", symbol="BTCUSDT",
        product=ProductType.SPOT, risk_day="1970-01-01",
        observed_at_ms=NOW, account_checked=True, balances_checked=True,
        open_orders_checked=True, fills_checked=True, can_trade=True,
        available_quote=Decimal("200"), position_quantity=Decimal("0"),
        position_cost=Decimal("0"), daily_equity_loss=Decimal("0"))
    values.update(changes)
    return McpReconciliationEvidence(**values)


def rules():
    return SpotMarketRules("BTCUSDT", "BTC", "USDT", Decimal("0.001"),
        Decimal("1000"), Decimal("0.001"), Decimal("5"))


def exchange_info():
    return {"symbols":[{"symbol":"BTCUSDT", "baseAsset":"BTC",
        "quoteAsset":"USDT", "status":"TRADING",
        "isSpotTradingAllowed":True, "quoteOrderQtyMarketAllowed":True,
        "orderTypes":["MARKET"], "filters":[
            {"filterType":"LOT_SIZE", "minQty":"0.001",
             "maxQty":"1000", "stepSize":"0.001"},
            {"filterType":"MIN_NOTIONAL", "minNotional":"5",
             "applyToMarket":True}]}]}


@pytest.fixture
def prepared(tmp_path):
    journal_path = tmp_path / "execution.json"
    lock = ExecutionLock(journal_path.with_suffix(".json.lock"))
    assert lock.acquire()
    executor = ConfirmedSpotExecutor(
        lambda *_: (_ for _ in ()).throw(AssertionError("no MCP in importer")),
        ExecutionJournal(journal_path, lock), AutomationPolicy())
    signal = SignalDecision("buy", "test", 100.0,
        "1970-01-01T00:33:20Z", expected_edge=0.004, strategy_id="mtf")
    plan = build_mcp_spot_plan(ASSET, signal, amount_usdt=Decimal("100"),
        account_binding=BINDING, now=NOW_DT)
    preview = prepare_plan_preview(plan, evidence(), rules(), executor,
        account_fingerprint="b" * 64, now_ms=NOW)
    submission = executor.begin_submission(
        preview["confirmation"], evidence(), now_ms=NOW + 1)
    ticket = build_submission_ticket(plan, submission,
        account_fingerprint="b" * 64,
        now=NOW_DT + timedelta(milliseconds=1))
    yield executor, ticket, tmp_path
    lock.release()


def terminal_payload(ticket, *, status="FILLED"):
    order = {"symbol":"BTCUSDT", "clientOrderId":
        ticket.arguments["newClientOrderId"], "side":"BUY", "type":"MARKET",
        "orderId":123, "status":status, "executedQty":"1",
        "cummulativeQuoteQty":"100"}
    trade = {"id":1, "orderId":123, "symbol":"BTCUSDT", "time":NOW + 2,
        "isBuyer":True, "qty":"1", "quoteQty":"100", "commission":"0",
        "commissionAsset":"USDT"}
    results = {
        "spot.getOrder": order,
        "spot.getAccount": {"accountType":"SPOT", "canTrade":True,
            "balances":[{"asset":"BTC", "free":"1", "locked":"0"},
                        {"asset":"USDT", "free":"100", "locked":"0"}]},
        "spot.getOpenOrders": [],
        "spot.myTrades": [trade],
        "spot.allOrders": [dict(order)],
        "spot.accountCommission": {},
        "spot.exchangeInfo": exchange_info(),
        "spot.tickerBookTicker": {"symbol":"BTCUSDT", "bidPrice":"99",
                                   "askPrice":"100"},
    }
    assert tuple(results) == MCP_SPOT_TERMINAL_TOOLS
    return {"schema_version":"1.0",
        "receipt_id":"mcp-exec-19700101T003320Z-1234abcd",
        "operation":"SUBMIT_CONFIRMED_SPOT_ORDER_RESULT", "host":"codex",
        "transport":"codex-binance-agent-os-mcp", "plan_id":ticket.plan_id,
        "signal_fingerprint":ticket.signal_fingerprint,
        "execution_fingerprint":ticket.execution_fingerprint,
        "account_ref":"agentic-primary", "account_fingerprint":"b" * 64,
        "symbol":"BTCUSDT", "observed_at":_utc(
            NOW_DT + timedelta(milliseconds=2)), "outcome":"TERMINAL",
        "completed_tools":list(MCP_SPOT_TERMINAL_TOOLS),
        "pagination":{"trades_complete":True, "orders_complete":True},
        "tool_results":results}


def unknown_payload(ticket):
    payload = terminal_payload(ticket)
    payload.update(outcome="UNKNOWN", completed_tools=[], tool_results={},
        pagination={"trades_complete":False, "orders_complete":False})
    return payload


def verify(ticket, payload):
    return verify_execution_result_receipt(ticket, BINDING, payload,
        now=NOW_DT + timedelta(milliseconds=3))


def ledger(path):
    return SpotFillLedger(path, account_ref="agentic-primary",
        symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT")


def test_terminal_receipt_syncs_complete_fills_before_journal(prepared, tmp_path):
    executor, ticket, _ = prepared
    receipt = verify(ticket, terminal_payload(ticket))
    result = import_execution_result(receipt, ticket, executor,
        ledger(tmp_path / "fills.json"), daily_equity_loss=Decimal("0"),
        now_ms=NOW + 3)
    assert result.phase == ExecutionPhase.FILLED
    assert result.order.status == "FILLED"
    assert result.fill_summary.quantity == Decimal("1")
    assert result.fill_summary.cost == Decimal("100")
    snapshot = result.evidence.to_snapshot()
    assert snapshot.position_quantity == Decimal("1")
    assert snapshot.position_cost == Decimal("100")
    assert snapshot.daily_entries == 1
    assert executor.journal.get(ticket.execution_fingerprint).phase \
        == ExecutionPhase.FILLED


def test_terminal_receipt_reimport_is_idempotent(prepared, tmp_path):
    executor, ticket, _ = prepared
    receipt = verify(ticket, terminal_payload(ticket))
    state = ledger(tmp_path / "fills.json")
    first = import_execution_result(receipt, ticket, executor, state,
        daily_equity_loss=Decimal("0"), now_ms=NOW + 3)
    second = import_execution_result(receipt, ticket, executor, state,
        daily_equity_loss=Decimal("0"), now_ms=NOW + 4)
    assert second.order == first.order
    assert second.fill_summary == first.fill_summary
    assert len(executor.journal.records()) == 1


def test_unknown_receipt_fails_closed_without_fill_ledger(prepared):
    executor, ticket, _ = prepared
    receipt = verify(ticket, unknown_payload(ticket))
    result = import_execution_result(receipt, ticket, executor, None,
        daily_equity_loss=Decimal("0"), now_ms=NOW + 3)
    assert result.phase == ExecutionPhase.UNKNOWN
    assert result.order is result.fill_summary is result.evidence is None


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(account_fingerprint="c" * 64),
    lambda p: p["completed_tools"].pop(),
    lambda p: p["pagination"].update(trades_complete=False),
    lambda p: p["tool_results"]["spot.getAccount"].update(uid=123),
])
def test_receipt_rejects_identity_incomplete_reads_and_secrets(
        prepared, mutate):
    _, ticket, _ = prepared
    payload = terminal_payload(ticket)
    mutate(payload)
    with pytest.raises(ValueError):
        verify(ticket, payload)


def test_terminal_fill_totals_must_match_order_result(prepared, tmp_path):
    executor, ticket, _ = prepared
    payload = terminal_payload(ticket)
    payload["tool_results"]["spot.myTrades"][0]["quoteQty"] = "99"
    receipt = verify(ticket, payload)
    with pytest.raises(ValueError, match="fills do not match"):
        import_execution_result(receipt, ticket, executor,
            ledger(tmp_path / "fills.json"),
            daily_equity_loss=Decimal("0"), now_ms=NOW + 3)
    assert executor.journal.get(ticket.execution_fingerprint).phase \
        == ExecutionPhase.SUBMITTING


def test_nonterminal_order_cannot_be_imported_as_terminal(prepared, tmp_path):
    executor, ticket, _ = prepared
    receipt = verify(ticket, terminal_payload(ticket,
        status="PARTIALLY_FILLED"))
    with pytest.raises(ValueError, match="not terminal"):
        import_execution_result(receipt, ticket, executor,
            ledger(tmp_path / "fills.json"),
            daily_equity_loss=Decimal("0"), now_ms=NOW + 3)


def test_terminal_order_cannot_still_appear_open(prepared, tmp_path):
    executor, ticket, _ = prepared
    payload = terminal_payload(ticket)
    payload["tool_results"]["spot.getOpenOrders"] = [
        dict(payload["tool_results"]["spot.getOrder"])]
    receipt = verify(ticket, payload)
    with pytest.raises(ValueError, match="still appears open"):
        import_execution_result(receipt, ticket, executor,
            ledger(tmp_path / "fills.json"),
            daily_equity_loss=Decimal("0"), now_ms=NOW + 3)


def test_halted_symbol_can_still_finalize_prior_order(prepared, tmp_path):
    executor, ticket, _ = prepared
    payload = terminal_payload(ticket)
    payload["tool_results"]["spot.exchangeInfo"]["symbols"][0]["status"] \
        = "BREAK"
    receipt = verify(ticket, payload)
    result = import_execution_result(receipt, ticket, executor,
        ledger(tmp_path / "fills.json"), daily_equity_loss=Decimal("0"),
        now_ms=NOW + 3)
    assert result.phase == ExecutionPhase.FILLED


def test_ledger_failure_never_advances_execution_journal(
        prepared, tmp_path, monkeypatch):
    executor, ticket, _ = prepared
    receipt = verify(ticket, terminal_payload(ticket))
    state = ledger(tmp_path / "fills.json")
    monkeypatch.setattr(state, "sync", lambda *a, **k:
        (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        import_execution_result(receipt, ticket, executor, state,
            daily_equity_loss=Decimal("0"), now_ms=NOW + 3)
    assert executor.journal.get(ticket.execution_fingerprint).phase \
        == ExecutionPhase.SUBMITTING


def test_verified_execution_receipt_round_trip(prepared, tmp_path):
    _, ticket, _ = prepared
    receipt = verify(ticket, terminal_payload(ticket))
    path = tmp_path / "verified-execution.json"
    write_verified_execution_result(receipt, path)
    assert load_execution_result_receipt(ticket, BINDING, path,
        now=NOW_DT + timedelta(milliseconds=3)) == receipt
    persisted = path.read_text(encoding="utf-8").lower()
    assert "confirmation" not in persisted and "uid" not in persisted


def test_verified_receipt_is_revalidated_after_nested_mutation(
        prepared, tmp_path):
    executor, ticket, _ = prepared
    receipt = verify(ticket, terminal_payload(ticket))
    receipt.tool_results["spot.getAccount"]["apiKey"] = "must-not-persist"
    with pytest.raises(ValueError, match="forbidden"):
        import_execution_result(receipt, ticket, executor,
            ledger(tmp_path / "fills.json"),
            daily_equity_loss=Decimal("0"), now_ms=NOW + 3)
    assert executor.journal.get(ticket.execution_fingerprint).phase \
        == ExecutionPhase.SUBMITTING
