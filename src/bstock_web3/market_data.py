from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

from .catalog import BStockAsset
from .models import Kline, MarketInstrument
from .provider import BinanceSpotKlineProvider


@dataclass(frozen=True)
class MultiTimeframeSnapshot:
    asset: BStockAsset
    one_minute: tuple[Kline, ...]
    five_minute: tuple[Kline, ...]
    observed_at: datetime

    @property
    def signal_bar_time(self) -> datetime | None:
        return self.one_minute[-1].time if self.one_minute else None


def instrument_for(asset: BStockAsset) -> MarketInstrument:
    return MarketInstrument("BINANCE", "BSTOCK_SPOT", asset.symbol, asset.symbol,
                            "USDT", asset.spot_symbol)


class BStockMultiTimeframeFeed:
    def __init__(self, provider: BinanceSpotKlineProvider | None = None, *,
                 one_minute_limit: int = 240, five_minute_limit: int = 240) -> None:
        self.provider = provider or BinanceSpotKlineProvider()
        self.one_minute_limit = one_minute_limit
        self.five_minute_limit = five_minute_limit

    def fetch(self, asset: BStockAsset, *, now: datetime | None = None) -> MultiTimeframeSnapshot:
        observed_at = _utc(now or datetime.now(timezone.utc))
        instrument = instrument_for(asset)
        one = self.provider.fetch_klines(instrument, interval="1m", limit=self.one_minute_limit)
        five = self.provider.fetch_klines(instrument, interval="5m", limit=self.five_minute_limit)
        return MultiTimeframeSnapshot(
            asset, tuple(_closed(one, 1, observed_at)),
            tuple(_closed(five, 5, observed_at)), observed_at,
        )


def _closed(bars: list[Kline], minutes: int, now: datetime) -> list[Kline]:
    result = []
    previous = None
    for bar in bars:
        stamp = _utc(bar.time)
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        if (not all(math.isfinite(v) for v in values) or min(values[:4]) <= 0 or bar.volume < 0
                or bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close)
                or stamp.timestamp() % (minutes * 60) != 0):
            raise ValueError("Invalid OHLCV or misaligned candle")
        if previous is not None and stamp <= previous:
            raise ValueError("Duplicate or unordered candles")
        previous = stamp
        if stamp + timedelta(minutes=minutes) <= _utc(now):
            result.append(bar)
    return result


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
