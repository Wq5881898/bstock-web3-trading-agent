from decimal import Decimal

import pytest

from bstock_web3.automation_policy import AutomationPolicy
from bstock_web3.execution_contract import (ExecutionInstrument, OrderIntent,
    PositionAction, ProductType)
from bstock_web3.execution_lock import ExecutionLock
from bstock_web3.execution_safety import (ExecutionArming, ExecutionJournal,
    ExecutionMode, ExecutionPhase, McpReconciliationEvidence,
    client_order_id, intent_fingerprint, prepare_safe_execution)


NOW = 2_000_000
SIGNAL_KEY = "candle:20260912T120000Z"


def intent(action=PositionAction.OPEN_LONG):
    instrument = ExecutionInstrument(
        "BTCUSDT", ProductType.SPOT, "BINANCE", "BTC", "USDT")
    return OrderIntent("mtf", instrument, action, Decimal("100"), "signal",
                       {"fast": 9}, action == PositionAction.CLOSE_LONG)


def evidence(**changes):
    values = dict(
        evidence_id="mcp-cycle-0001", account_ref="agentic_1",
        symbol="BTCUSDT", product=ProductType.SPOT, risk_day="2026-09-12",
        observed_at_ms=NOW, account_checked=True, balances_checked=True,
        open_orders_checked=True, fills_checked=True, can_trade=True,
        available_quote=Decimal("200"), position_quantity=Decimal("0"),
        position_cost=Decimal("0"), daily_equity_loss=Decimal("0"))
    values.update(changes)
    return McpReconciliationEvidence(**values)


def armed(**changes):
    values = dict(mode=ExecutionMode.UNATTENDED, account_ref="agentic_1",
                  symbol="BTCUSDT", product=ProductType.SPOT,
                  armed_until_ms=NOW + 60_000)
    values.update(changes)
    return ExecutionArming(**values)


def locked_journal(tmp_path, name="journal"):
    journal_path = tmp_path / f"{name}.json"
    lock = ExecutionLock(journal_path.with_suffix(".json.lock"))
    assert lock.acquire()
    return ExecutionJournal(journal_path, lock), lock


def test_all_four_mcp_reads_are_required_for_reconciled_snapshot():
    assert evidence().to_snapshot().reconciled
    assert not evidence(fills_checked=False).to_snapshot().reconciled


def test_default_observe_only_mode_cannot_prepare_submission():
    result = prepare_safe_execution(intent(), evidence(), AutomationPolicy(),
        ExecutionArming(), ExecutionJournal(), signal_key=SIGNAL_KEY, now_ms=NOW)
    assert not result.decision.allowed
    assert "observe_only" in result.decision.reasons
    assert result.record is None


def test_armed_reconciled_intent_gets_deterministic_client_order_id(tmp_path):
    journal, lock = locked_journal(tmp_path)
    result = prepare_safe_execution(intent(), evidence(), AutomationPolicy(),
        armed(), journal, signal_key=SIGNAL_KEY, now_ms=NOW)
    assert result.decision.allowed
    assert result.record.phase == ExecutionPhase.PREPARED
    fingerprint = intent_fingerprint(intent(), "2026-09-12", SIGNAL_KEY,
                                     "QUOTE", Decimal("100"))
    assert result.record.client_order_id == client_order_id(fingerprint)
    assert len(result.record.client_order_id) == 35
    lock.release()


def test_same_intent_is_never_prepared_twice(tmp_path):
    journal, lock = locked_journal(tmp_path)
    first = prepare_safe_execution(intent(), evidence(), AutomationPolicy(),
        armed(), journal, signal_key=SIGNAL_KEY, now_ms=NOW)
    second = prepare_safe_execution(intent(), evidence(), AutomationPolicy(),
        armed(), journal, signal_key=SIGNAL_KEY, now_ms=NOW + 1)
    assert first.decision.allowed
    assert not second.decision.allowed and second.duplicate
    assert second.record == first.record
    assert second.decision.reasons == ("duplicate_execution_intent",)
    lock.release()


def test_unknown_submission_must_reconcile_and_cannot_return_to_prepared():
    journal = ExecutionJournal()
    record, _ = journal.prepare(intent(), evidence().to_snapshot(),
        signal_key=SIGNAL_KEY, amount_kind="QUOTE", amount=Decimal("100"),
        now_ms=NOW)
    record = journal.transition(record.fingerprint, ExecutionPhase.SUBMITTING,
                                now_ms=NOW + 1)
    record = journal.transition(record.fingerprint, ExecutionPhase.UNKNOWN,
                                now_ms=NOW + 2, detail="timeout")
    with pytest.raises(RuntimeError, match="Invalid execution transition"):
        journal.transition(record.fingerprint, ExecutionPhase.SUBMITTING,
                           now_ms=NOW + 3)
    record = journal.transition(record.fingerprint, ExecutionPhase.FILLED,
        now_ms=NOW + 4, external_id="12345")
    assert record.phase == ExecutionPhase.FILLED


def test_execution_journal_round_trip_and_corruption_rejection(tmp_path):
    path = tmp_path / "journal.json"
    journal = ExecutionJournal(path)
    record, _ = journal.prepare(intent(), evidence().to_snapshot(),
        signal_key=SIGNAL_KEY, amount_kind="QUOTE", amount=Decimal("100"),
        now_ms=NOW)
    journal.transition(record.fingerprint, ExecutionPhase.SUBMITTING,
                       now_ms=NOW + 1)
    restored = ExecutionJournal(path)
    assert restored.get(record.fingerprint).phase == ExecutionPhase.SUBMITTING
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid execution journal"):
        ExecutionJournal.load(path)


def test_arming_is_bound_to_account_symbol_product_and_expiry():
    result = prepare_safe_execution(intent(), evidence(), AutomationPolicy(),
        armed(account_ref="wrong", armed_until_ms=NOW - 1),
        ExecutionJournal(), signal_key=SIGNAL_KEY, now_ms=NOW)
    assert not result.decision.allowed
    assert "armed_account_mismatch" in result.decision.reasons
    assert "arming_expired" in result.decision.reasons


def test_risk_policy_still_allows_exit_while_buy_latch_is_active(tmp_path):
    policy = AutomationPolicy()
    journal, lock = locked_journal(tmp_path)
    buy = prepare_safe_execution(intent(), evidence(
        daily_equity_loss=Decimal("10")), policy, armed(),
        journal, signal_key=SIGNAL_KEY, now_ms=NOW)
    assert not buy.decision.allowed
    exit_result = prepare_safe_execution(intent(PositionAction.CLOSE_LONG),
        evidence(daily_equity_loss=Decimal("10"),
                 position_quantity=Decimal("0.01"),
                 position_cost=Decimal("100")), policy, armed(),
        journal,
        signal_key=SIGNAL_KEY + ":exit", now_ms=NOW)
    assert exit_result.decision.allowed
    lock.release()


def test_distinct_strategy_events_at_same_price_are_not_duplicates(tmp_path):
    journal, lock = locked_journal(tmp_path)
    first = prepare_safe_execution(intent(), evidence(), AutomationPolicy(),
        armed(), journal, signal_key="trade:100", now_ms=NOW)
    second = prepare_safe_execution(intent(), evidence(), AutomationPolicy(),
        armed(), journal, signal_key="trade:101", now_ms=NOW + 1)
    assert first.decision.allowed and second.decision.allowed
    assert first.record.fingerprint != second.record.fingerprint
    lock.release()


def test_exact_buy_budget_and_sell_quantity_are_persisted(tmp_path):
    journal, lock = locked_journal(tmp_path)
    buy = prepare_safe_execution(intent(), evidence(), AutomationPolicy(),
        armed(), journal,
        signal_key="trade:buy", now_ms=NOW)
    sell = prepare_safe_execution(intent(PositionAction.CLOSE_LONG), evidence(
        position_quantity=Decimal("0.0123"), position_cost=Decimal("99")),
        AutomationPolicy(), armed(), journal,
        signal_key="trade:sell", now_ms=NOW)
    assert (buy.record.amount_kind, buy.record.amount) == ("QUOTE", "100")
    assert (sell.record.amount_kind, sell.record.amount) == ("BASE", "0.0123")
    lock.release()


def test_unattended_preparation_requires_a_persistent_journal():
    result = prepare_safe_execution(intent(), evidence(), AutomationPolicy(),
        armed(), ExecutionJournal(), signal_key=SIGNAL_KEY, now_ms=NOW)
    assert not result.decision.allowed
    assert "non_persistent_execution_journal" in result.decision.reasons
    assert "execution_lock_not_held" in result.decision.reasons


def test_unattended_preparation_requires_held_execution_lock(tmp_path):
    path = tmp_path / "journal.json"
    journal = ExecutionJournal(path, ExecutionLock(
        path.with_suffix(".json.lock")))
    result = prepare_safe_execution(intent(), evidence(), AutomationPolicy(),
        armed(), journal, signal_key=SIGNAL_KEY, now_ms=NOW)
    assert not result.decision.allowed
    assert result.decision.reasons == ("execution_lock_not_held",)
