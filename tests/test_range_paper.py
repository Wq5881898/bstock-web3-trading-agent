from decimal import Decimal

from bstock_web3.engine import BStockEngineConfig
from bstock_web3.median_paper import RangePaperSession
from bstock_web3.range_ticks import RangeStrategyConfig

BASE = 1788955200000


def row(i, price): return {"a":i,"T":BASE+i*1000,"p":str(price),"q":"1"}


def test_range_median_transactional_buy_sell_restart(tmp_path):
    strategy = RangeStrategyConfig(family="median", range_bps=100, window=5, deviation=.003)
    risk = BStockEngineConfig(strategy_kind="range-median", range_config=strategy,
        order_size_usdc=Decimal("100"), paper_entry_cooldown=0)
    path = tmp_path / "range.sqlite"
    session = RangePaperSession(path, symbol="BTCUSDT", strategy=strategy, risk=risk)
    try:
        session.accept_page([row(0,100),row(1,101.1),row(2,102.2),row(3,103.3),row(4,104.4),row(5,105.5)],
                            now_ms=BASE+5000)
        assert not session.fills()
        fills = session.accept_page([row(6,95)], now_ms=BASE+6000)
        assert fills[0]["side"] == "buy"
        session.close()
        session = RangePaperSession(path, symbol="BTCUSDT", strategy=strategy, risk=risk)
        assert session.ledger.pause == ""
        fills = session.accept_page([row(7,110)], now_ms=BASE+7000)
        assert fills[0]["side"] == "sell"
        assert [fill["side"] for fill in session.fills()] == ["buy","sell"]
    finally:
        session.close()


def test_range_ema_risk_pause_still_allows_sell(tmp_path):
    strategy = RangeStrategyConfig(range_bps=100, short=2, long=3)
    risk = BStockEngineConfig(strategy_kind="range-ema", range_config=strategy,
        order_size_usdc=Decimal("100"), paper_entry_cooldown=0)
    session = RangePaperSession(tmp_path/"range.sqlite", symbol="BTCUSDT", strategy=strategy, risk=risk)
    try:
        session.accept_page([row(0,100),row(1,103.1)], now_ms=BASE+1000)
        assert session.accept_page([row(2,104.2)], now_ms=BASE+2000)[0]["side"] == "buy"
        session.pause_buys()
        assert session.accept_page([row(3,98)], now_ms=BASE+3000)[0]["side"] == "sell"
        assert session.ledger.pause == "MANUAL"
    finally:
        session.close()
