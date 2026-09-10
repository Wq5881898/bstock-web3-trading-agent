from dataclasses import asdict, replace
from decimal import Decimal
import json
import sqlite3

import pytest

from bstock_web3.engine import BStockEngineConfig
from bstock_web3.median_paper import MedianPaperSession
from bstock_web3.median_ticks import TickMedianConfig

BASE = 1788955200000
STRATEGY = TickMedianConfig(window=3, entry_deviation=.01, exit_deviation=.01)


def row(i, price=100, stamp=None):
    return {"a": i, "T": BASE + i * 1000 if stamp is None else stamp, "p": str(price), "q": "1"}


def make(tmp_path, **limits):
    risk = BStockEngineConfig(order_size_usdc=Decimal("100"), **limits)
    return MedianPaperSession(tmp_path / "median.sqlite", symbol="BTCUSDT", strategy=STRATEGY, risk=risk)


def tick(session, i, price, stamp=None):
    data = row(i, price, stamp)
    return session.accept_page([data], now_ms=data["T"])


def prime(session):
    assert session.accept_page([row(i) for i in range(3)], now_ms=BASE+2000) == []


def test_roundtrip_restart_and_duplicate_replay(tmp_path):
    session = make(tmp_path)
    prime(session)
    assert tick(session, 3, 95)[0]["side"] == "buy"
    before = asdict(session.ledger)
    session.close()
    session = make(tmp_path)
    try:
        assert asdict(session.ledger) == before
        assert tick(session, 3, 95) == []
        assert tick(session, 4, 105)[0]["side"] == "sell"
        assert len(session.fills()) == 2
        assert Decimal(session.ledger.quantity) == 0
        assert abs(Decimal(session.ledger.cash) - 1000 - Decimal(session.ledger.realized_pnl)) < Decimal("1e-18")
        assert Decimal(session.ledger.fees) > .1
    finally:
        session.close()


def test_loss_pause_does_not_force_exit_and_original_signal_can_sell(tmp_path):
    session = make(tmp_path)
    try:
        prime(session)
        tick(session, 3, 95)
        assert tick(session, 4, 80) == []
        assert session.ledger.pause == "DAILY_LOSS"
        assert Decimal(session.ledger.quantity) > 0
        assert not session.resume_buys(now_ms=BASE+4000)
        assert tick(session, 5, 100)[0]["side"] == "sell"
        assert session.ledger.pause == "DAILY_LOSS"
        assert tick(session, 6, 70) == []
    finally:
        session.close()


def test_manual_pause_resume_preserves_baseline_and_emits_no_fill(tmp_path):
    session = make(tmp_path)
    try:
        prime(session)
        session.pause_buys()
        assert tick(session, 3, 95) == []
        baseline = session.ledger.baseline
        assert session.resume_buys(now_ms=BASE+3000)
        assert session.ledger.baseline == baseline
        assert session.fills() == []
        assert tick(session, 4, 90)[0]["side"] == "buy"
        with pytest.raises(ValueError, match="Fresh"):
            session.resume_buys(now_ms=BASE+10000)
    finally:
        session.close()


def test_daily_count_survives_rollover_without_automatic_resume(tmp_path):
    session = make(tmp_path, paper_max_daily_entries=1)
    try:
        prime(session)
        tick(session, 3, 95)
        assert session.ledger.pause == "DAILY_ENTRY_LIMIT"
        tick(session, 4, 105)
        assert not session.resume_buys(now_ms=BASE+4000)
        tick(session, 5, 100, BASE+86400000)
        assert session.ledger.entries == 0
        assert session.ledger.pause == "DAILY_ENTRY_LIMIT"
        assert session.resume_buys(now_ms=BASE+86400000)
    finally:
        session.close()


def test_cooldown_limits_buys_not_sells(tmp_path):
    session = make(tmp_path)
    try:
        prime(session)
        tick(session, 3, 95)
        assert tick(session, 4, 105)[0]["side"] == "sell"
        assert tick(session, 5, 90) == []
        assert session.ledger.pause == ""
        assert tick(session, 6, 80, BASE+63000)[0]["side"] == "buy"
    finally:
        session.close()


def test_gap_rolls_back_prefix_persists_pause_and_keeps_signal_exits(tmp_path):
    session = make(tmp_path)
    prime(session)
    tick(session, 3, 95)
    with pytest.raises(ValueError):
        session.accept_page([row(4, 105), row(6, 90)], now_ms=BASE+6000)
    assert session.stream.next_id == 4
    assert len(session.fills()) == 1
    assert session.ledger.pause == "DATA_GAP"
    session.close()
    session = make(tmp_path)
    try:
        assert tick(session, 4, 105)[0]["side"] == "sell"
        assert tick(session, 5, 90) == []
        with pytest.raises(ValueError, match="reconciliation"):
            session.resume_buys(now_ms=BASE+5000)
    finally:
        session.close()


def test_transaction_failure_rolls_back_fills_cursor_and_memory(tmp_path):
    session = make(tmp_path)
    prime(session)
    before, checkpoint, revision = asdict(session.ledger), session.stream.checkpoint(), session.revision
    session.db.execute("CREATE TRIGGER fail_session BEFORE UPDATE ON session BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    session.db.commit()
    try:
        with pytest.raises(sqlite3.DatabaseError): tick(session, 3, 95)
        assert asdict(session.ledger) == before
        assert session.stream.checkpoint() == checkpoint
        assert session.revision == revision
        assert session.fills() == []
        session.db.execute("DROP TRIGGER fail_session")
        session.db.commit()
        assert tick(session, 3, 95)[0]["side"] == "buy"
        assert len(session.fills()) == 1
    finally:
        session.close()


def test_stale_second_writer_cannot_overwrite_session(tmp_path):
    first, second = make(tmp_path), make(tmp_path)
    try:
        prime(first)
        with pytest.raises(RuntimeError, match="another writer"):
            prime(second)
        assert second.stream.next_id is None
        tick(first, 3, 95)
        assert len(first.fills()) == 1
    finally:
        first.close()
        second.close()


def test_reopen_rejects_changed_strategy_or_limits(tmp_path):
    session = make(tmp_path)
    prime(session)
    tick(session, 3, 95)
    session.close()
    with pytest.raises(ValueError, match="configuration mismatch"):
        make(tmp_path, paper_max_daily_entries=10)
    with pytest.raises(ValueError, match="configuration mismatch"):
        MedianPaperSession(tmp_path / "median.sqlite", symbol="BTCUSDT", strategy=replace(STRATEGY, window=4))
    restored = make(tmp_path)
    assert len(restored.fills()) == 1
    restored.close()


@pytest.mark.parametrize("field,value", [("cash", "NaN"), ("quantity", "2"),
    ("losses", True), ("pause", "unknown"), ("baseline", "1000")])
def test_corrupt_ledger_fails_closed(tmp_path, field, value):
    session = make(tmp_path)
    payload = json.loads(session.db.execute("SELECT payload FROM session").fetchone()[0])
    payload["ledger"][field] = value
    session.db.execute("UPDATE session SET payload=?", (json.dumps(payload),))
    session.db.commit()
    session.close()
    with pytest.raises(ValueError): make(tmp_path)


def test_no_live_mode_or_historical_fills(tmp_path):
    with pytest.raises(ValueError, match="paper-only"):
        make(tmp_path, mode="quote")
    session = make(tmp_path)
    try:
        prime(session)
        assert session.accept_page([row(3, 95)], now_ms=BASE+10000) == []
        assert session.accept_page([row(4, 90)], now_ms=BASE+3999) == []
        assert session.fills() == []
    finally:
        session.close()


def test_three_fee_inclusive_losses_and_manual_acknowledgement(tmp_path):
    session = make(tmp_path, paper_entry_cooldown=0)
    try:
        prime(session)
        i = 3
        for _ in range(3):
            for price in (100, 100, 95, 90, 90, 95):
                tick(session, i, price)
                i += 1
        assert len(session.fills()) == 6
        assert session.ledger.losses == 3
        assert session.ledger.pause == "CONSECUTIVE_LOSSES"
        assert Decimal(session.ledger.realized_pnl) < 0
        baseline = session.ledger.baseline
        assert session.resume_buys(now_ms=BASE+(i-1)*1000)
        assert session.ledger.losses == 0
        assert session.ledger.baseline == baseline
    finally:
        session.close()


def test_200_roundtrips_atomic_recovery_and_audit(tmp_path):
    limits = dict(paper_entry_cooldown=0, paper_max_daily_entries=1000,
                  paper_max_loss_streak=1000, paper_daily_loss_limit=Decimal("500"))
    session = make(tmp_path, **limits)
    try:
        prime(session)
        i = 3
        for cycle in range(200):
            for price in (100, 100, 95, 90, 90, 95):
                tick(session, i, price)
                assert tick(session, i, price) == []
                i += 1
            if cycle % 23 == 0:
                prior = asdict(session.ledger)
                session.close()
                session = make(tmp_path, **limits)
                assert asdict(session.ledger) == prior
        records = session.fills()
        assert len(records) == 400
        assert len({fill["trade_id"] for fill in records}) == 400
        assert session.ledger.entries == 200
        assert session.ledger.losses == 200
        assert Decimal(session.ledger.quantity) == 0
        assert abs(Decimal(session.ledger.cash) - 1000 - Decimal(session.ledger.realized_pnl)) < Decimal("1e-18")
        assert abs(Decimal(session.ledger.realized_pnl) + Decimal(session.ledger.fees)) < Decimal("1e-18")
    finally:
        session.close()
