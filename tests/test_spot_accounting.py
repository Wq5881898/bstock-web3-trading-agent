from copy import deepcopy
from decimal import Decimal

import pytest

from bstock_web3.spot_accounting import (SpotFillLedger, fill_risk_stats,
                                         summarize_fills)


def fill(trade_id=1, *, buy=True, qty="1", quote="100", fee="0", asset="USDT"):
    return dict(id=trade_id, orderId=42 if buy else 43, symbol="BTCUSDT",
                time=1000 + trade_id, isBuyer=buy, qty=qty, quoteQty=quote,
                commission=fee, commissionAsset=asset)


def summary(rows):
    return summarize_fills(rows, "BTCUSDT", "BTC", "USDT")


def ledger(path, account="test-agentic"):
    return SpotFillLedger(path, account_ref=account, symbol="BTCUSDT",
                          base_asset="BTC", quote_asset="USDT")


def test_buy_base_fee_and_sell_quote_fee():
    result = summary([fill(fee="0.01", asset="BTC"),
        fill(2, buy=False, qty="0.99", quote="110", fee="1")])
    assert result.quantity == result.cost == 0
    assert result.realized_pnl == Decimal("9")


def test_buy_quote_fee_and_sell_base_fee():
    result = summary([fill(fee="1"),
        fill(2, buy=False, qty="0.9", quote="100", fee="0.1", asset="BTC")])
    assert result.quantity == result.cost == 0
    assert result.realized_pnl == Decimal("-1")


def test_partial_sale_accounts_fills_without_order_status():
    result = summary([fill(), fill(2, buy=False, qty="0.4", quote="44", fee="1")])
    assert (result.quantity, result.cost, result.realized_pnl) == (
        Decimal("0.6"), Decimal("60"), Decimal("3"))


def test_fill_risk_stats_count_orders_and_latest_loss_streak():
    rows = [fill(), fill(2),
        fill(3, buy=False, qty="0.5", quote="45"),
        fill(4, buy=False, qty="0.5", quote="45"),
        fill(5, buy=False, qty="1", quote="110")]
    rows[1]["orderId"] = rows[0]["orderId"]  # two fills, one entry
    rows[3]["orderId"] = rows[2]["orderId"]  # two fills, one losing exit
    for row in rows:
        row["time"] = 1_788_998_400_000 + row["id"]  # 2026-09-10 UTC
    result = fill_risk_stats(rows, "BTCUSDT", "BTC", "USDT", "2026-09-10")
    assert result.daily_entries == 1
    assert result.consecutive_losses == 0  # latest sale order was profitable
    assert result.last_entry_ms == rows[1]["time"]


def test_fill_risk_loss_streak_and_utc_day():
    rows = [fill(), fill(2, buy=False, qty="1", quote="90"),
            fill(3), fill(4, buy=False, qty="1", quote="80")]
    rows[3]["orderId"] = 44
    for row in rows:
        row["time"] = 1_788_998_400_000 + row["id"]
    result = fill_risk_stats(rows, "BTCUSDT", "BTC", "USDT", "2026-09-11")
    assert result.daily_entries == 0
    assert result.consecutive_losses == 2
    with pytest.raises(ValueError, match="risk day"):
        fill_risk_stats(rows, "BTCUSDT", "BTC", "USDT", "bad")
    with pytest.raises(ValueError, match="risk day"):
        fill_risk_stats(rows, "BTCUSDT", "BTC", "USDT", "2026-9-10")


def test_same_timestamp_uses_trade_id_not_input_order():
    rows = [fill(2, buy=False, quote="110"), fill()]
    for row in rows:
        row["time"] = 1000
    assert summary(rows).realized_pnl == 10


@pytest.mark.parametrize("changes", [
    {"id":True}, {"id":-1}, {"orderId":0}, {"time":True},
    {"time":-1}, {"isBuyer":1}, {"qty":0.5}, {"quoteQty":"NaN"},
    {"commission":"Infinity"}, {"qty":"0"}, {"symbol":"ETHUSDT"},
    {"commission":"1", "commissionAsset":"BNB"},
])
def test_invalid_fill_fails_closed(changes):
    row = fill()
    row.update(changes)
    with pytest.raises(ValueError):
        summary([row])


def test_duplicate_fill_and_unexplained_sale_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        summary([fill(), fill()])
    with pytest.raises(ValueError, match="cannot explain"):
        summary([fill(buy=False)])


def test_negative_proceeds_and_no_net_acquisition_rejected():
    with pytest.raises(ValueError, match="proceeds"):
        summary([fill(), fill(2, buy=False, fee="101")])
    with pytest.raises(ValueError, match="net bought"):
        summary([fill(fee="1", asset="BTC")])


def test_persistent_idempotent_sync_and_restart(tmp_path):
    path = tmp_path / "nested" / "fills.json"
    rows = [fill(), fill(2, buy=False, qty="0.4", quote="44")]
    with ledger(path) as state:
        expected = state.sync(rows, history_complete=True)
        assert state.sync(deepcopy(rows), history_complete=True) == expected
        state.rows[0]["qty"] = "999"
        assert state.rows[0]["qty"] == "1"
    with ledger(path) as restored:
        assert restored.summary == expected
        assert restored.sync(rows + [fill(3, buy=False, qty="0.6", quote="66")],
                             history_complete=True).realized_pnl == 10


def test_identity_mismatch_and_corrupt_checkpoint_release_lock(tmp_path):
    path = tmp_path / "fills.json"
    with ledger(path) as state:
        state.sync([fill()], history_complete=True)
    wrong = ledger(path, "other-agentic")
    with pytest.raises(ValueError, match="identity"):
        wrong.__enter__()
    assert not wrong.lock.held
    with ledger(path):
        pass
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        with ledger(path):
            pass


def test_lock_and_complete_history_required(tmp_path):
    path = tmp_path / "fills.json"
    state = ledger(path)
    with pytest.raises(RuntimeError, match="lock"):
        state.sync([], history_complete=True)
    with state:
        with pytest.raises(ValueError, match="Complete"):
            state.sync([], history_complete=False)
        competitor = ledger(path)
        assert not competitor.lock.acquire()


def test_missing_or_changed_previous_fill_rejected(tmp_path):
    with ledger(tmp_path / "fills.json") as state:
        state.sync([fill()], history_complete=True)
        for rows in ([], [fill(quote="101")]):
            with pytest.raises(ValueError, match="missing or changed"):
                state.sync(rows, history_complete=True)
        assert state.summary.cost == 100


def test_replace_failure_preserves_memory_and_disk(tmp_path, monkeypatch):
    import bstock_web3.spot_accounting as module
    path = tmp_path / "fills.json"
    with ledger(path) as state:
        before = state.sync([fill()], history_complete=True)
        contents = path.read_bytes()
        original_replace = module.os.replace
        def fail(*args):
            raise OSError("disk failure")
        monkeypatch.setattr(module.os, "replace", fail)
        rows = [fill(), fill(2, buy=False, quote="110")]
        with pytest.raises(OSError):
            state.sync(rows, history_complete=True)
        assert state.summary == before
        assert path.read_bytes() == contents
        monkeypatch.setattr(module.os, "replace", original_replace)
        assert state.sync(rows, history_complete=True).realized_pnl == 10


def test_empty_account_checkpoint_and_missing_existing_ledger(tmp_path):
    path = tmp_path / "fills.json"
    state = ledger(path)
    with state:
        assert state.sync([], history_complete=True).fill_count == 0
        state.sync([fill()], history_complete=True)
    path.unlink()
    with pytest.raises(ValueError, match="ledger is missing"):
        state.__enter__()
    assert not state.lock.held
