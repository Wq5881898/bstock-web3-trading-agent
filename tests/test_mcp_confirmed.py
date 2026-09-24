from dataclasses import replace
from decimal import Decimal

import pytest

from bstock_web3.automation_policy import AutomationPolicy
from bstock_web3.execution_contract import (ExecutionInstrument, OrderIntent,
    PositionAction, ProductType)
from bstock_web3.execution_lock import ExecutionLock
from bstock_web3.execution_safety import (ExecutionJournal, ExecutionPhase,
    McpReconciliationEvidence)
from bstock_web3.mcp_confirmed import ConfirmedSpotExecutor, SpotMarketRules

NOW = 2_000_000


def evidence(**changes):
    values=dict(evidence_id="mcp-evidence-001", account_ref="agentic-test",
        symbol="BTCUSDT", product=ProductType.SPOT, risk_day="2026-09-16",
        observed_at_ms=NOW, account_checked=True, balances_checked=True,
        open_orders_checked=True, fills_checked=True, can_trade=True,
        available_quote=Decimal("200"), position_quantity=Decimal("0"),
        position_cost=Decimal("0"), daily_equity_loss=Decimal("0"))
    values.update(changes)
    return McpReconciliationEvidence(**values)


def intent(sell=False):
    return OrderIntent("mtf", ExecutionInstrument("BTCUSDT", ProductType.SPOT,
        "BINANCE", "BTC", "USDT"),
        PositionAction.CLOSE_LONG if sell else PositionAction.OPEN_LONG,
        Decimal("100"), "test", {}, sell)


def rules():
    return SpotMarketRules("BTCUSDT", "BTC", "USDT", Decimal("0.001"),
        Decimal("1000"), Decimal("0.001"), Decimal("5"))


class Caller:
    def __init__(self): self.calls=[]; self.status="FILLED"; self.fail=False
    def __call__(self, name, args):
        self.calls.append((name, args))
        if self.fail:
            raise TimeoutError("sensitive server data")
        cid=args.get("newClientOrderId", args.get("origClientOrderId"))
        return {"symbol":"BTCUSDT", "clientOrderId":cid,
            "side":"SELL" if args.get("side") == "SELL" else "BUY",
            "type":"MARKET", "orderId":123, "status":self.status,
            "executedQty":"1", "cummulativeQuoteQty":"100"}


@pytest.fixture
def executor(tmp_path):
    path=tmp_path / "execution.json"
    lock=ExecutionLock(path.with_suffix(".json.lock"))
    assert lock.acquire()
    caller=Caller()
    result=ConfirmedSpotExecutor(caller, ExecutionJournal(path,lock), AutomationPolicy())
    yield result, caller, lock
    lock.release()


def preview(executor, **changes):
    return executor.preview(intent(), evidence(**changes), rules(),
                            signal_key="trade:1", now_ms=NOW)


def test_exact_confirmation_submits_once_and_journals_filled(executor):
    engine, caller, _=executor
    plan=preview(engine)
    assert plan["account"] == "agentic-test"
    assert plan["arguments"]["quoteOrderQty"] == "100"
    assert caller.calls == []
    result=engine.submit(plan["confirmation"], evidence(), now_ms=NOW+1)
    assert result.status == "FILLED"
    assert engine.journal.records()[0].phase == ExecutionPhase.FILLED
    assert len(caller.calls) == 1
    with pytest.raises(RuntimeError, match="No confirmation"):
        engine.submit(plan["confirmation"], evidence(), now_ms=NOW+2)
    assert len(caller.calls) == 1


@pytest.mark.parametrize("confirmation", ["wrong", "确认买入", None])
def test_bad_confirmation_never_calls_mcp(executor, confirmation):
    engine,caller,_=executor; preview(engine)
    with pytest.raises(RuntimeError, match="mismatch"):
        engine.submit(confirmation, evidence(), now_ms=NOW)
    assert caller.calls == []


@pytest.mark.parametrize("change", [
    {"can_trade":False}, {"account_ref":"wrong"},
    {"daily_equity_loss":Decimal("10")}, {"pending_order_id":"pending"},
    {"available_quote":Decimal("1")}, {"observed_at_ms":NOW-20_000},
])
def test_submit_revalidates_fresh_account_and_consumes_confirmation(executor, change):
    engine,caller,_=executor; plan=preview(engine)
    with pytest.raises(RuntimeError):
        engine.submit(plan["confirmation"], evidence(**change), now_ms=NOW+1)
    assert caller.calls == []
    with pytest.raises(RuntimeError, match="No confirmation"):
        engine.submit(plan["confirmation"], evidence(), now_ms=NOW+2)


def test_expired_confirmation_cannot_submit(executor):
    engine,caller,_=executor; plan=preview(engine)
    with pytest.raises(RuntimeError, match="expired"):
        engine.submit(plan["confirmation"], evidence(), now_ms=NOW+15_000)
    assert caller.calls == []


def test_lost_execution_lock_prevents_submission(executor):
    engine,caller,lock=executor; plan=preview(engine); lock.release()
    with pytest.raises(RuntimeError, match="lock"):
        engine.submit(plan["confirmation"], evidence(), now_ms=NOW+1)
    assert caller.calls == []


def test_uncertain_submission_requires_lookup_and_never_retries(executor):
    engine,caller,_=executor; plan=preview(engine); caller.fail=True
    with pytest.raises(RuntimeError, match="uncertain") as error:
        engine.submit(plan["confirmation"], evidence(), now_ms=NOW+1)
    assert "sensitive" not in str(error.value)
    record=engine.journal.records()[0]
    assert record.phase == ExecutionPhase.UNKNOWN
    with pytest.raises(RuntimeError, match="Unresolved"):
        engine.preview(intent(), evidence(), rules(), signal_key="trade:2", now_ms=NOW+2)
    with pytest.raises(RuntimeError, match="never resubmit"):
        engine.reconcile(record.fingerprint, now_ms=NOW+2)
    caller.fail=False
    original=engine._caller
    def excessive(name,args):
        payload=original(name,args); payload["cummulativeQuoteQty"]="10000"
        return payload
    engine._caller=excessive
    with pytest.raises(RuntimeError,match="never resubmit"):
        engine.reconcile(record.fingerprint,now_ms=NOW+3)
    assert engine.journal.get(record.fingerprint).phase == ExecutionPhase.UNKNOWN
    engine._caller=original
    result=engine.reconcile(record.fingerprint, now_ms=NOW+3)
    assert result.status == "FILLED"
    assert [name for name,args in caller.calls] == [
        "spot.newOrder","spot.getOrder","spot.getOrder","spot.getOrder"]


def test_submitting_is_persisted_before_tool_call(executor):
    engine,caller,_=executor; plan=preview(engine)
    original=engine._caller
    def check(name,args):
        assert ExecutionJournal(engine.journal.path).records()[0].phase == ExecutionPhase.SUBMITTING
        return original(name,args)
    engine._caller=check
    engine.submit(plan["confirmation"],evidence(),now_ms=NOW+1)


def test_external_handoff_begins_before_io_and_accepts_result(executor):
    engine,caller,_=executor; plan=preview(engine)
    submission=engine.begin_submission(
        plan["confirmation"], evidence(), now_ms=NOW+1)
    record=engine.journal.get(submission.fingerprint)
    assert record.phase == ExecutionPhase.SUBMITTING
    assert caller.calls == []
    assert submission.arguments["newClientOrderId"] == record.client_order_id
    payload=caller("spot.newOrder",submission.arguments)
    result=engine.accept_submission_result(
        submission.fingerprint,payload,now_ms=NOW+2)
    assert result.status == "FILLED"
    assert engine.journal.get(submission.fingerprint).phase == ExecutionPhase.FILLED


def test_external_handoff_can_be_marked_unknown_only_once(executor):
    engine,caller,_=executor; plan=preview(engine)
    submission=engine.begin_submission(
        plan["confirmation"], evidence(), now_ms=NOW+1)
    first=engine.mark_submission_unknown(submission.fingerprint,now_ms=NOW+2)
    second=engine.mark_submission_unknown(submission.fingerprint,now_ms=NOW+3)
    assert first.phase == second.phase == ExecutionPhase.UNKNOWN
    assert caller.calls == []


def test_restart_submitting_performs_only_order_lookup(executor):
    engine,caller,lock=executor; preview(engine)
    record=engine.journal.records()[0]
    engine.journal.transition(record.fingerprint,ExecutionPhase.SUBMITTING,now_ms=NOW+1)
    restored=ConfirmedSpotExecutor(caller,ExecutionJournal(engine.journal.path,lock),AutomationPolicy())
    restored.reconcile(record.fingerprint,now_ms=NOW+2)
    assert caller.calls[0][0] == "spot.getOrder"


def test_partial_fill_remains_unresolved_until_terminal_status(executor):
    engine,caller,_=executor; plan=preview(engine); caller.status="PARTIALLY_FILLED"
    result=engine.submit(plan["confirmation"],evidence(),now_ms=NOW+1)
    record=engine.journal.records()[0]
    assert result.executed_base == Decimal("1") and record.phase == ExecutionPhase.SUBMITTED
    engine.reconcile(record.fingerprint,now_ms=NOW+2)
    caller.status="CANCELED"
    result=engine.reconcile(record.fingerprint,now_ms=NOW+3)
    assert result.executed_base == Decimal("1")  # canceled does not mean zero fills
    assert engine.journal.get(record.fingerprint).phase == ExecutionPhase.REJECTED


def test_sell_continues_after_buy_loss_latch(executor):
    engine,caller,_=executor
    state=evidence(position_quantity=Decimal("1"),position_cost=Decimal("100"),
                   daily_equity_loss=Decimal("10"))
    plan=engine.preview(intent(True),state,rules(),signal_key="exit:1",now_ms=NOW)
    assert plan["arguments"]["quantity"] == "1"
    result=engine.submit(plan["confirmation"],state,now_ms=NOW+1)
    assert result.status == "FILLED" and caller.calls[0][1]["side"] == "SELL"


def test_sell_retains_only_untradable_dust(executor):
    engine,caller,_=executor
    plan=engine.preview(intent(True), evidence(position_quantity=Decimal("1.0001")),
                        rules(),signal_key="exit:1",now_ms=NOW)
    assert Decimal(plan["arguments"]["quantity"]) == Decimal("1")
    assert caller.calls == []


def test_sell_does_not_silently_leave_another_tradable_lot(executor):
    engine,caller,_=executor
    limited=replace(rules(),max_quantity=Decimal("1"))
    with pytest.raises(ValueError, match="residual remains tradable"):
        engine.preview(intent(True),
                       evidence(position_quantity=Decimal("2")), limited,
                       signal_key="exit:1", now_ms=NOW)
    assert caller.calls == []


def test_rules_reject_below_minimum_notional(executor):
    engine,caller,_=executor
    with pytest.raises(ValueError, match="notional"):
        engine.preview(intent(),evidence(),replace(rules(),min_notional=Decimal("101")),
                       signal_key="trade:1",now_ms=NOW)
    assert caller.calls == []


def test_write_journal_failure_prevents_mcp_call(executor,monkeypatch):
    engine,caller,_=executor; plan=preview(engine)
    def fail(): raise OSError("disk failure")
    monkeypatch.setattr(engine.journal,"_save",fail)
    with pytest.raises(OSError):
        engine.submit(plan["confirmation"],evidence(),now_ms=NOW+1)
    assert caller.calls == []


def test_exchange_rules_parse_verified_market_filters():
    info={"symbols":[{"symbol":"BTCUSDT","baseAsset":"BTC","quoteAsset":"USDT",
        "status":"TRADING","isSpotTradingAllowed":True,"quoteOrderQtyMarketAllowed":True,
        "orderTypes":["MARKET"],"filters":[
            {"filterType":"LOT_SIZE","minQty":"0.001","maxQty":"1000","stepSize":"0.001"},
            {"filterType":"MIN_NOTIONAL","minNotional":"5","applyToMarket":True}]}]}
    assert SpotMarketRules.from_exchange_info(info,"BTCUSDT") == rules()
    info["symbols"][0]["status"]="BREAK"
    with pytest.raises(ValueError,match="unavailable"):
        SpotMarketRules.from_exchange_info(info,"BTCUSDT")


def test_btc_market_lot_maximum_is_supported_without_ignoring_lot_step():
    info={"symbols":[{"symbol":"BTCUSDT","baseAsset":"BTC",
        "quoteAsset":"USDT","status":"TRADING",
        "isSpotTradingAllowed":True,"quoteOrderQtyMarketAllowed":True,
        "orderTypes":["MARKET"],"filters":[
            {"filterType":"LOT_SIZE","minQty":"0.00001000",
             "maxQty":"9000.00000000","stepSize":"0.00001000"},
            {"filterType":"MARKET_LOT_SIZE","minQty":"0.00000000",
             "maxQty":"113.89715343","stepSize":"0.00000000"},
            {"filterType":"NOTIONAL","minNotional":"5.00000000",
             "applyMinToMarket":True,"maxNotional":"9000000.00000000",
             "applyMaxToMarket":False}]}]}
    parsed=SpotMarketRules.from_exchange_info(info,"BTCUSDT")
    assert parsed.max_quantity == Decimal("113.89715343")
    sell=replace(intent(True), reference_price=Decimal("86148.91"))
    state=evidence(position_quantity=Decimal("0.00011"))
    assert Decimal(parsed.arguments(sell,state,Decimal("100"),"preview")["quantity"]) == Decimal("0.00011")
    rounded=parsed.arguments(sell,evidence(position_quantity=Decimal("0.00011988")),
                             Decimal("100"),"preview")
    assert Decimal(rounded["quantity"]) == Decimal("0.00011")
    info["symbols"][0]["filters"][1]["stepSize"]="0.00002000"
    stepped=SpotMarketRules.from_exchange_info(info,"BTCUSDT")
    assert Decimal(stepped.arguments(sell,state,Decimal("100"),
                                     "preview")["quantity"]) == Decimal("0.00010")


def test_preview_return_cannot_mutate_actual_order(executor):
    engine,caller,_=executor; plan=preview(engine)
    plan["arguments"]["quoteOrderQty"]="10000"
    engine.submit(plan["confirmation"],evidence(),now_ms=NOW+1)
    assert caller.calls[0][1]["quoteOrderQty"] == "100"


def test_cancel_discards_confirmation_but_preserves_signal_reservation(executor):
    engine,caller,_=executor; plan=preview(engine); engine.cancel_preview()
    with pytest.raises(RuntimeError,match="No confirmation"):
        engine.submit(plan["confirmation"],evidence(),now_ms=NOW+1)
    with pytest.raises(RuntimeError,match="duplicate"):
        preview(engine)
    assert caller.calls == []


def test_incorrect_order_identity_is_unknown_not_filled(executor):
    engine,caller,_=executor; plan=preview(engine)
    original=engine._caller
    def wrong(name,args):
        payload=original(name,args); payload["clientOrderId"]="another-order"
        return payload
    engine._caller=wrong
    with pytest.raises(RuntimeError,match="uncertain"):
        engine.submit(plan["confirmation"],evidence(),now_ms=NOW+1)
    assert engine.journal.records()[0].phase == ExecutionPhase.UNKNOWN


@pytest.mark.parametrize(("status", "executed"), [
    ("NEW", "1"), ("PARTIALLY_FILLED", "0"), ("REJECTED", "1"),
])
def test_order_status_must_match_executed_amounts(executor, status, executed):
    engine, caller, _ = executor
    plan = preview(engine)
    original = engine._caller
    def inconsistent(name, args):
        payload = original(name, args)
        payload.update(status=status, executedQty=executed,
                       cummulativeQuoteQty=executed)
        return payload
    engine._caller = inconsistent
    with pytest.raises(RuntimeError, match="uncertain"):
        engine.submit(plan["confirmation"], evidence(), now_ms=NOW + 1)
    assert engine.journal.records()[0].phase == ExecutionPhase.UNKNOWN


def test_terminal_status_cannot_change_on_reimport(executor):
    engine, caller, _ = executor
    plan = preview(engine)
    caller.status = "CANCELED"
    engine.submit(plan["confirmation"], evidence(), now_ms=NOW + 1)
    record = engine.journal.records()[0]
    changed = {"symbol":"BTCUSDT", "clientOrderId":record.client_order_id,
        "side":"BUY", "type":"MARKET", "orderId":123,
        "status":"EXPIRED", "executedQty":"1",
        "cummulativeQuoteQty":"100"}
    with pytest.raises(RuntimeError, match="Terminal execution result changed"):
        engine.accept_submission_result(record.fingerprint, changed,
                                        now_ms=NOW + 2)
