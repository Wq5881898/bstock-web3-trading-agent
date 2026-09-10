from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import pytest

from bstock_web3.engine import BStockEngineConfig
from bstock_web3.median_paper import RangePaperSession
from bstock_web3.models import Kline
from bstock_web3.range_guard import GuardedRangeMedianConfig, GuardedRangeMedianStream, minute_guard_context

BASE = 1788955200000


def row(i, price, seconds=None):
    return {"a": i, "T": BASE + (i if seconds is None else seconds) * 1000,
            "p": str(price), "q": "1"}


def context(*, down=False, amplitude=.006):
    return {"minute_ema_20": 98 if down else 101, "minute_ema_50": 99 if down else 100,
        "minute_ema_20_previous": 98.5 if down else 100.5,
        "minute_ema_50_previous": 99.2 if down else 99.8,
        "minute_amplitude_p90_60": amplitude}


def warm_rows():
    return [row(0,100),row(1,101.1),row(2,102.2),row(3,103.3),row(4,104.4),row(5,105.5)]


def test_minute_guard_context_uses_completed_snapshot_values():
    start = datetime(2026, 9, 9, tzinfo=timezone.utc)
    bars = tuple(Kline(start+timedelta(minutes=i), 100+i*.01, 101+i*.01,
        99+i*.01, 100+i*.01, 1) for i in range(60))
    result = minute_guard_context(SimpleNamespace(one_minute=bars))
    assert result["minute_amplitude_p90_60"] > 0
    assert result["minute_ema_20"] > result["minute_ema_20_previous"]
    assert result["minute_drawdown_60"] == 0


def test_guard_blocks_confirmed_downtrend_and_locks_amplitude_stop():
    config = GuardedRangeMedianConfig(range_bps=100, window=5, deviation=.003)
    blocked = GuardedRangeMedianStream("BTCUSDT", config)
    blocked.accept_page(warm_rows(), now_ms=BASE+5000, warmup=True, context=context())
    point = blocked.accept_page([row(6,95)], now_ms=BASE+6000, context=context(down=True))[0]
    assert not point.buy and point.reason.startswith("entry_blocked")

    allowed = GuardedRangeMedianStream("BTCUSDT", config)
    allowed.accept_page(warm_rows(), now_ms=BASE+5000, warmup=True, context=context())
    point = allowed.accept_page([row(6,95)], now_ms=BASE+6000, context=context())[0]
    assert point.buy
    assert point.strategy_params["locked_stop_loss"] == pytest.approx(.018)
    assert point.strategy_params["locked_amplitude_p90"] == .006


def test_guarded_session_dynamic_stop_is_locked_and_has_cooldown(tmp_path):
    strategy = GuardedRangeMedianConfig(range_bps=100, window=5, deviation=.003,
        stop_loss_cooldown_seconds=900)
    risk = BStockEngineConfig(symbol="NVDAB", strategy_kind="range-median-guarded",
        guarded_range_config=strategy, state_file=tmp_path/"guarded.sqlite",
        order_size_usdc=Decimal("100"))
    session = RangePaperSession(risk.state_file, symbol="NVDABUSDT", strategy=strategy, risk=risk)
    try:
        session.accept_page(warm_rows(), now_ms=BASE+5000, warmup=True, context=context())
        assert session.accept_page([row(6,95)], now_ms=BASE+6000, context=context())[0]["side"] == "buy"
        assert session.ledger.entry_strategy_params["locked_stop_loss"] == pytest.approx(.018)
        fill = session.accept_page([row(7,93)], now_ms=BASE+7000, context=context(down=True))[0]
        assert fill["side"] == "sell" and fill["reason"] == "stop_loss"
        assert session.ledger.last_sell_reason == "stop_loss"
        assert session.ledger.stop_loss_cooldown_seconds == 900
    finally:
        session.close()
