from decimal import Decimal

import pytest

from bstock_web3.spot_equity_risk import (EquityObservation,
    SpotEquityRiskLedger, normalize_cashflows)


DAY = 1_788_998_400_000  # 2026-09-10T00:00:00Z


def observation(at=DAY + 1000, quote="100", qty="1", bid="100"):
    return EquityObservation("2026-09-10", at, Decimal(quote), Decimal(qty),
                             Decimal(bid))


def ledger(path, account="agentic-test"):
    return SpotEquityRiskLedger(path, account_ref=account, symbol="BTCUSDT")


def flow(flow_id="d1", at=DAY + 1500, amount="10"):
    return {"id": flow_id, "time": at, "amount": amount}


def test_equity_loss_uses_conservative_bid_and_neutralizes_deposit(tmp_path):
    path = tmp_path / "equity.json"
    with ledger(path) as state:
        initial = state.initialize(observation(), [], history_complete=True,
                                   operator_confirmed=True)
        assert initial.raw_equity == initial.baseline_equity == Decimal("200")
        result = state.observe(observation(DAY + 2000, quote="110", bid="90"),
                               [flow()], history_complete=True)
        assert result.raw_equity == 200
        assert result.adjusted_equity == 190
        assert result.daily_equity_loss == 10


def test_withdrawal_does_not_create_loss(tmp_path):
    with ledger(tmp_path / "equity.json") as state:
        state.initialize(observation(), [], history_complete=True,
                         operator_confirmed=True)
        result = state.observe(observation(DAY + 2000, quote="80", bid="100"),
                               [flow(amount="-20")], history_complete=True)
        assert result.adjusted_equity == 200
        assert result.daily_equity_loss == 0


def test_profit_is_zero_loss_not_negative(tmp_path):
    with ledger(tmp_path / "equity.json") as state:
        state.initialize(observation(), [], history_complete=True,
                         operator_confirmed=True)
        assert state.observe(observation(DAY + 2000, bid="120"), [],
                             history_complete=True).daily_equity_loss == 0


def test_restart_and_conservative_day_rollover(tmp_path):
    path = tmp_path / "equity.json"
    with ledger(path) as state:
        state.initialize(observation(), [], history_complete=True,
                         operator_confirmed=True)
        state.observe(observation(DAY + 2000, bid="95"), [], history_complete=True)
    next_day = EquityObservation("2026-09-11", DAY + 86_400_000 + 1000,
                                Decimal("100"), Decimal("1"), Decimal("90"))
    with ledger(path) as restored:
        result = restored.observe(next_day, [], history_complete=True)
        assert result.baseline_equity == 195
        assert result.daily_equity_loss == 5


@pytest.mark.parametrize("history,confirmed", [(False, True), (True, False)])
def test_initialization_requires_complete_history_and_confirmation(
        tmp_path, history, confirmed):
    with ledger(tmp_path / "equity.json") as state:
        with pytest.raises(ValueError, match="explicit baseline"):
            state.initialize(observation(), [], history_complete=history,
                             operator_confirmed=confirmed)


def test_observation_validation():
    with pytest.raises(ValueError, match="UTC"):
        EquityObservation("2026-09-11", DAY, Decimal("1"), Decimal("0"), Decimal("0"))
    with pytest.raises(ValueError, match="liquidation"):
        EquityObservation("2026-09-10", DAY, Decimal("1"), Decimal("1"), Decimal("0"))


@pytest.mark.parametrize("row", [
    {"id":"", "time":DAY, "amount":"1"},
    {"id":"x", "time":True, "amount":"1"},
    {"id":"x", "time":DAY, "amount":1},
    {"id":"x", "time":DAY, "amount":"NaN"},
    {"id":"x", "time":DAY, "amount":"0"},
])
def test_invalid_cashflow_rejected(row):
    with pytest.raises(ValueError):
        normalize_cashflows([row])


def test_duplicate_future_incomplete_and_changed_flow_rejected(tmp_path):
    path = tmp_path / "equity.json"
    with ledger(path) as state:
        state.initialize(observation(), [], history_complete=True,
                         operator_confirmed=True)
        with pytest.raises(ValueError, match="Complete"):
            state.observe(observation(DAY + 2000), [], history_complete=False)
        with pytest.raises(ValueError, match="Future"):
            state.observe(observation(DAY + 2000), [flow(at=DAY + 3000)],
                          history_complete=True)
        state.observe(observation(DAY + 2000), [flow()], history_complete=True)
        with pytest.raises(ValueError, match="missing or changed"):
            state.observe(observation(DAY + 3000), [], history_complete=True)
        with pytest.raises(ValueError, match="duplicate"):
            normalize_cashflows([flow(), flow()])


def test_clock_rewind_double_initialize_and_lock_required(tmp_path):
    path = tmp_path / "equity.json"
    state = ledger(path)
    with pytest.raises(RuntimeError, match="lock"):
        state.initialize(observation(), [], history_complete=True,
                         operator_confirmed=True)
    with state:
        state.initialize(observation(), [], history_complete=True,
                         operator_confirmed=True)
        with pytest.raises(RuntimeError, match="already"):
            state.initialize(observation(), [], history_complete=True,
                             operator_confirmed=True)
        with pytest.raises(ValueError, match="advance"):
            state.observe(observation(), [], history_complete=True)
        assert not ledger(path).lock.acquire()


def test_identity_corruption_and_missing_state_release_lock(tmp_path):
    path = tmp_path / "equity.json"
    with ledger(path) as state:
        state.initialize(observation(), [], history_complete=True,
                         operator_confirmed=True)
    wrong = ledger(path, "other")
    with pytest.raises(ValueError, match="identity"):
        wrong.__enter__()
    assert not wrong.lock.held
    path.write_text("{}", encoding="utf-8")
    broken = ledger(path)
    with pytest.raises(ValueError):
        broken.__enter__()
    assert not broken.lock.held


def test_replace_failure_preserves_state_and_allows_retry(tmp_path, monkeypatch):
    import bstock_web3.spot_equity_risk as module
    path = tmp_path / "equity.json"
    with ledger(path) as state:
        state.initialize(observation(), [], history_complete=True,
                         operator_confirmed=True)
        contents = path.read_bytes()
        original = module.os.replace
        monkeypatch.setattr(module.os, "replace",
                            lambda *args: (_ for _ in ()).throw(OSError("disk")))
        with pytest.raises(OSError):
            state.observe(observation(DAY + 2000, bid="90"), [],
                          history_complete=True)
        assert path.read_bytes() == contents
        monkeypatch.setattr(module.os, "replace", original)
        assert state.observe(observation(DAY + 2000, bid="90"), [],
                             history_complete=True).daily_equity_loss == 10
