from dataclasses import replace
from decimal import Decimal

import pytest

from bstock_web3.autonomous_session import (AutonomousSpotSession,
    SessionBinding, SessionPhase)
from bstock_web3.autonomous_runner import AutonomousSpotRunner, _buy_cost_block
from bstock_web3.automation_policy import AutomationPolicy
from bstock_web3.execution_lock import ExecutionLock
from bstock_web3.execution_safety import (ExecutionJournal, ExecutionPhase,
    McpReconciliationEvidence)
from bstock_web3.execution_contract import ProductType
from bstock_web3.mcp_confirmed import SpotMarketRules
from bstock_web3.strategy import SignalDecision
from bstock_web3.spot_api_reconcile import SpotApiSnapshot
from bstock_web3.unattended_spot import UnattendedSpotExecutor

NOW = 2_000_000


def evidence(evidence_id="spot-read-001", **changes):
    values = dict(evidence_id=evidence_id, account_ref="api-account",
        symbol="BTCUSDT", product=ProductType.SPOT, risk_day="2026-09-22",
        observed_at_ms=NOW, account_checked=True, balances_checked=True,
        open_orders_checked=True, fills_checked=True, can_trade=True,
        available_quote=Decimal("200"), position_quantity=Decimal("0"),
        position_cost=Decimal("0"), daily_equity_loss=Decimal("0"))
    values.update(changes)
    return McpReconciliationEvidence(**values)


def signal(action, key):
    return SignalDecision(action, key, 100, key, strategy_id="mtf")


def rules():
    return SpotMarketRules("BTCUSDT", "BTC", "USDT", Decimal("0.001"),
                           Decimal("1000"), Decimal("0.001"), Decimal("5"))


class FakeSpotApi:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.account_fingerprint = "f" * 64

    def market_order(self, args):
        self.calls.append(("POST", dict(args)))
        if self.fail:
            raise TimeoutError("uncertain")
        return self._order(args)

    def get_order(self, symbol, client_order_id):
        self.calls.append(("GET", client_order_id))
        for method, args in self.calls:
            if method == "POST" and args["newClientOrderId"] == client_order_id:
                if self.fail:
                    raise TimeoutError("still uncertain")
                return self._order(args)
        raise AssertionError("Unknown client ID")

    @staticmethod
    def _order(args):
        return dict(symbol=args["symbol"], clientOrderId=args["newClientOrderId"],
            side=args["side"], type="MARKET", orderId=123 if args["side"] == "BUY" else 124,
            status="FILLED", executedQty="1", cummulativeQuoteQty="100")


@pytest.fixture
def harness(tmp_path):
    journal_path = tmp_path / "journal.json"
    lock = ExecutionLock(journal_path.with_suffix(".json.lock"))
    lock.require()
    api = FakeSpotApi()
    journal = ExecutionJournal(journal_path, lock)
    policy = AutomationPolicy()
    executor = UnattendedSpotExecutor(api, journal, policy,
        account_ref="api-account", symbol="BTCUSDT")
    binding = SessionBinding("api-account", "f" * 64, "BTCUSDT", "BTC", "USDT",
        "mtf", "strategy-hash", "risk-hash")
    session = AutonomousSpotSession(tmp_path / "session.json", binding, executor)
    yield session, executor, api, lock
    lock.release()


def test_one_start_buy_then_sell_without_per_order_confirmation(harness):
    session, executor, api, _ = harness
    session.start()
    buy = session.process(signal("buy", "bar:1"), evidence(), rules(),
                          signal_key="bar:1", now_ms=NOW)
    assert buy.outcome == "ORDER" and buy.order_status == "FILLED"
    assert session.process(signal("sell", "bar:2"), evidence(), rules(),
                           signal_key="bar:2", now_ms=NOW).reasons == ("fills_not_reconciled",)
    assert session.process(signal("sell", "bar:2"), evidence("spot-read-002",
        position_quantity=Decimal("1"), position_cost=Decimal("100")), rules(),
        signal_key="bar:2", now_ms=NOW + 1).reasons == ("fill_not_in_ledger",)
    sell = session.process(signal("sell", "bar:2"), evidence("spot-read-002",
        position_quantity=Decimal("1"), position_cost=Decimal("100")), rules(),
        signal_key="bar:2", now_ms=NOW + 1,
        filled_order_ids=frozenset({123}))
    assert sell.outcome == "ORDER" and sell.order_status == "FILLED"
    assert [method for method, _ in api.calls] == ["POST", "POST"]
    assert [row.phase for row in executor.journal.records()] == [
        ExecutionPhase.FILLED, ExecutionPhase.FILLED]
    session.request_stop()
    assert not session.finish_stop(now_ms=NOW + 2)
    assert session.finish_stop(now_ms=NOW + 2,
        evidence=evidence("spot-read-003", position_quantity=Decimal("0")),
        filled_order_ids=frozenset({123, 124}))
    assert session.phase == SessionPhase.STOPPED
    assert session.process(signal("buy", "bar:3"), evidence(), rules(),
                           signal_key="bar:3", now_ms=NOW + 3).outcome == "BLOCKED"


def test_timeout_is_unknown_and_lookup_only(harness):
    session, executor, api, _ = harness
    session.start()
    api.fail = True
    first = session.process(signal("buy", "bar:1"), evidence(), rules(),
                            signal_key="bar:1", now_ms=NOW)
    assert first.outcome == "UNKNOWN"
    assert executor.journal.records()[0].phase == ExecutionPhase.UNKNOWN
    second = session.process(signal("buy", "bar:2"), evidence("spot-read-002"),
                             rules(), signal_key="bar:2", now_ms=NOW + 1)
    assert second.outcome == "BLOCKED"
    assert [method for method, _ in api.calls] == ["POST"]
    assert executor.reconcile_unresolved(now_ms=NOW + 2)[0].outcome == "UNKNOWN"
    api.fail = False
    assert executor.reconcile_unresolved(now_ms=NOW + 3)[0].order_status == "FILLED"
    assert [method for method, _ in api.calls].count("POST") == 1


def test_loss_latches_buy_but_allows_strategy_sell(harness):
    session, executor, api, _ = harness
    session.start()
    risky = evidence(position_quantity=Decimal("1"), position_cost=Decimal("100"),
                     daily_equity_loss=Decimal("10"))
    blocked = session.process(signal("buy", "bar:1"), risky, rules(),
                              signal_key="bar:1", now_ms=NOW)
    assert blocked.outcome == "BLOCKED"
    assert session.phase == SessionPhase.BUY_PAUSED
    sold = session.process(signal("sell", "bar:2"), risky, rules(),
                           signal_key="bar:2", now_ms=NOW + 1)
    assert sold.outcome == "ORDER"
    assert [method for method, _ in api.calls] == ["POST"]


def test_restart_is_recovery_only(harness):
    session, executor, api, _ = harness
    session.start()
    restored = AutonomousSpotSession(session.path, session.binding, executor)
    assert restored.phase == SessionPhase.RECOVERY_ONLY
    assert restored.process(signal("buy", "bar:1"), evidence(), rules(),
                            signal_key="bar:1", now_ms=NOW).outcome == "BLOCKED"
    assert api.calls == []
    with pytest.raises(ValueError, match="identity mismatch"):
        AutonomousSpotSession(session.path,
            replace(session.binding, symbol="ETHUSDT"), executor)


def test_runner_start_two_strategy_cycles_and_stop(harness):
    session, executor, api, _ = harness
    class Reconciler:
        reads = 0
        fees = {"standardCommission": {"taker": "0.001", "buyer": "0", "seller": "0"},
                "specialCommission": {"taker": "0", "buyer": "0", "seller": "0"},
                "taxCommission": {"taker": "0", "buyer": "0", "seller": "0"}}
        book = {"bidPrice": "100", "askPrice": "100.1"}
        def initialize(self, *, now_ms):
            return SpotApiSnapshot(evidence("initial-001"), rules(), self.fees, self.book)
        def read(self, *, now_ms):
            self.reads += 1
            values = ({"position_quantity": Decimal("1"),
                       "position_cost": Decimal("100")}
                      if self.reads == 2 else {})
            return SpotApiSnapshot(evidence(f"cycle-{self.reads:03}",
                observed_at_ms=now_ms, **values), rules(), self.fees, self.book,
                frozenset({123, 124}) if self.reads >= 3 else
                frozenset({123}) if self.reads == 2 else frozenset())
    class Source:
        calls = 0
        def evaluate(self, account, *, now_ms):
            self.calls += 1
            original = signal("buy" if self.calls == 1 else "sell",
                              f"bar:{self.calls}")
            return replace(original, expected_edge=0.01), f"bar:{self.calls}"
    runner = AutonomousSpotRunner(session, Reconciler(), Source())
    runner.start(now_ms=NOW)
    assert runner.tick(now_ms=NOW).order_status == "FILLED"
    assert runner.tick(now_ms=NOW + 1).order_status == "FILLED"
    assert runner.stop(now_ms=NOW + 2)
    assert [method for method, _ in api.calls] == ["POST", "POST"]


def test_spot_cost_gate_fails_closed_without_verified_fees():
    candidate = replace(signal("buy", "bar:1"), expected_edge=0.01)
    snapshot = SpotApiSnapshot(evidence(), rules(), {},
        {"bidPrice": "100", "askPrice": "101"})
    assert _buy_cost_block(candidate, snapshot)


def test_same_signal_key_cannot_dispatch_again_after_fill(harness):
    session, executor, api, _ = harness
    session.start()
    assert session.process(signal("buy", "bar:1"), evidence(), rules(),
        signal_key="bar:1", now_ms=NOW).outcome == "ORDER"
    again = session.process(signal("buy", "bar:1"),
        evidence("spot-read-002", observed_at_ms=NOW + 1,
                 position_quantity=Decimal("1"), position_cost=Decimal("100")),
        rules(), signal_key="bar:1", now_ms=NOW + 1,
        filled_order_ids=frozenset({123}))
    assert again.reasons == ("duplicate_strategy_event",)
    assert [method for method, _ in api.calls] == ["POST"]
