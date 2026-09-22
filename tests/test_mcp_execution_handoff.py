from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bstock_web3.automation_policy import AutomationPolicy
from bstock_web3.catalog import BStockAsset
from bstock_web3.execution_contract import ProductType
from bstock_web3.execution_lock import ExecutionLock
from bstock_web3.execution_safety import (ExecutionJournal, ExecutionPhase,
    McpReconciliationEvidence)
from bstock_web3.mcp_bridge import (McpAccountBinding,
    build_mcp_spot_plan)
from bstock_web3.mcp_confirmed import ConfirmedSpotExecutor, SpotMarketRules
from bstock_web3.mcp_execution_handoff import (build_submission_ticket,
    load_submission_ticket, prepare_plan_preview, write_submission_ticket)
from bstock_web3.strategy import SignalDecision


NOW = 2_000_000
NOW_DT = datetime.fromtimestamp(NOW / 1000, timezone.utc)
ASSET = BStockAsset("NVDA", "NVDAB", "0x02fc", "56", "NVDABUSDT", "1")
BINDING = McpAccountBinding(
    "1.0", "agentic-primary", "sha256(salt-bytes+uid-ascii)",
    "a" * 64, "b" * 64)


def plan(amount="100"):
    signal = SignalDecision("buy", "test", 220.0,
        "1970-01-01T00:33:20Z", expected_edge=0.004, strategy_id="mtf")
    return build_mcp_spot_plan(ASSET, signal,
        amount_usdt=Decimal(amount), account_binding=BINDING, now=NOW_DT)


def evidence(**changes):
    values = dict(evidence_id="mcp-evidence-001",
        account_ref="agentic-primary", symbol="NVDABUSDT",
        product=ProductType.SPOT, risk_day="1970-01-01", observed_at_ms=NOW,
        account_checked=True, balances_checked=True, open_orders_checked=True,
        fills_checked=True, can_trade=True, available_quote=Decimal("200"),
        position_quantity=Decimal("0"), position_cost=Decimal("0"),
        daily_equity_loss=Decimal("0"))
    values.update(changes)
    return McpReconciliationEvidence(**values)


def rules():
    return SpotMarketRules("NVDABUSDT", "NVDAB", "USDT",
        Decimal("0.001"), Decimal("1000"), Decimal("0.001"), Decimal("5"))


@pytest.fixture
def engine(tmp_path):
    journal_path = tmp_path / "execution.json"
    lock = ExecutionLock(journal_path.with_suffix(".json.lock"))
    assert lock.acquire()
    calls = []
    def caller(name, arguments):
        calls.append((name, arguments))
        raise AssertionError("file handoff must not call MCP")
    executor = ConfirmedSpotExecutor(
        caller, ExecutionJournal(journal_path, lock), AutomationPolicy())
    yield executor, calls, lock
    lock.release()


def test_confirmed_plan_becomes_short_lived_single_submission_ticket(
        engine, tmp_path):
    executor, calls, _ = engine
    candidate = plan()
    preview = prepare_plan_preview(candidate, evidence(), rules(), executor,
        account_fingerprint="b" * 64, now_ms=NOW)
    submission = executor.begin_submission(
        preview["confirmation"], evidence(), now_ms=NOW + 1)
    ticket = build_submission_ticket(candidate, submission,
        account_fingerprint="b" * 64,
        now=NOW_DT + timedelta(milliseconds=1))
    assert calls == []
    assert executor.journal.get(submission.fingerprint).phase \
        == ExecutionPhase.SUBMITTING
    assert ticket.arguments["newClientOrderId"] == submission.client_order_id
    assert ticket.requirements["single_submission_only"] is True
    encoded = str(ticket.to_dict())
    assert preview["confirmation"] not in encoded
    assert "'confirmation':" not in encoded.lower()
    path = tmp_path / "ticket.json"
    write_submission_ticket(ticket, path)
    assert load_submission_ticket(path) == ticket
    ticket.require_current(now=NOW_DT + timedelta(seconds=14))
    with pytest.raises(RuntimeError, match="expired"):
        ticket.require_current(now=NOW_DT + timedelta(seconds=15, milliseconds=1))


def test_candidate_must_match_policy_amount_before_journal_reservation(engine):
    executor, calls, _ = engine
    with pytest.raises(ValueError, match="changed"):
        prepare_plan_preview(plan("99"), evidence(), rules(), executor,
            account_fingerprint="b" * 64, now_ms=NOW)
    assert executor.journal.records() == () and calls == []


def test_preflight_rejects_account_drift_and_stale_evidence(engine):
    executor, calls, _ = engine
    with pytest.raises(ValueError, match="fingerprint"):
        prepare_plan_preview(plan(), evidence(), rules(), executor,
            account_fingerprint="c" * 64, now_ms=NOW)
    with pytest.raises(RuntimeError, match="blocked"):
        prepare_plan_preview(plan(), evidence(observed_at_ms=NOW - 16_000),
            rules(), executor, account_fingerprint="b" * 64, now_ms=NOW)
    assert calls == []


def test_preflight_rejects_inconsistent_market_rule_assets(engine):
    executor, calls, _ = engine
    inconsistent = SpotMarketRules(
        "NVDABUSDT", "BTC", "USDT", Decimal("0.001"), Decimal("1000"),
        Decimal("0.001"), Decimal("5"))
    with pytest.raises(ValueError, match="identity"):
        prepare_plan_preview(plan(), evidence(), inconsistent, executor,
            account_fingerprint="b" * 64, now_ms=NOW)
    assert calls == []


def test_ticket_rejects_tampering_and_old_confirmed_submission(engine):
    executor, _, _ = engine
    candidate = plan()
    preview = prepare_plan_preview(candidate, evidence(), rules(), executor,
        account_fingerprint="b" * 64, now_ms=NOW)
    submission = executor.begin_submission(
        preview["confirmation"], evidence(), now_ms=NOW + 1)
    with pytest.raises(RuntimeError, match="too old"):
        build_submission_ticket(candidate, submission,
            account_fingerprint="b" * 64,
            now=NOW_DT + timedelta(seconds=16))
    bad = replace(submission, arguments={**submission.arguments,
        "quoteOrderQty":"101"})
    with pytest.raises(ValueError, match="differs"):
        build_submission_ticket(candidate, bad,
            account_fingerprint="b" * 64,
            now=NOW_DT + timedelta(milliseconds=2))


def test_ticket_rejects_invalid_account_reference(engine):
    executor, _, _ = engine
    candidate = plan()
    preview = prepare_plan_preview(candidate, evidence(), rules(), executor,
        account_fingerprint="b" * 64, now_ms=NOW)
    submission = executor.begin_submission(
        preview["confirmation"], evidence(), now_ms=NOW + 1)
    ticket = build_submission_ticket(candidate, submission,
        account_fingerprint="b" * 64,
        now=NOW_DT + timedelta(milliseconds=1))
    payload = ticket.to_dict()
    payload["account_ref"] = "Agentic Primary"
    with pytest.raises(ValueError, match="submission ticket"):
        type(ticket).from_dict(payload)
