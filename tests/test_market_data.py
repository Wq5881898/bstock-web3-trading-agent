from datetime import datetime, timedelta, timezone

from bstock_web3.catalog import BStockAsset
from bstock_web3.market_data import BStockMultiTimeframeFeed
from bstock_web3.models import Kline


class Provider:
    def fetch_klines(self, instrument, *, interval, limit):
        now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
        minutes = 1 if interval == "1m" else 5
        return [Kline(now - timedelta(minutes=minutes), 1, 2, 0.5, 1.5, 10),
                Kline(now, 1.5, 2, 1, 1.8, 5)]


def test_feed_excludes_current_unclosed_bars():
    asset = BStockAsset("NVDA", "NVDAB", "0x1", "56", "NVDABUSDT", "1")
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    snapshot = BStockMultiTimeframeFeed(Provider()).fetch(asset, now=now)
    assert len(snapshot.one_minute) == 1
    assert len(snapshot.five_minute) == 1
    assert snapshot.signal_bar_time == now - timedelta(minutes=1)
