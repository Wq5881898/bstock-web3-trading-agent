"""Portable MTF strategy fed by Binance Spot candles, without bStock catalog."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from .market_data import _closed
from .models import MarketInstrument
from .provider import BinanceSpotKlineProvider
from .strategy import PositionView
from .strategy_contract import CandleMarketInput
from .strategy_registry import build_portable_strategy_runtime


@dataclass(frozen=True)
class SpotCandleSnapshot:
    one_minute: tuple
    five_minute: tuple
    observed_at: datetime

    @property
    def signal_bar_time(self):
        return self.one_minute[-1].time if self.one_minute else None


class SpotMtfSignalSource:
    def __init__(self, symbol: str, base_asset: str, quote_asset: str,
                 *, config=None, provider=None):
        self.symbol = symbol
        self.instrument = MarketInstrument("BINANCE", "SPOT", symbol,
            base_asset, quote_asset, symbol)
        self.provider = provider or BinanceSpotKlineProvider()
        self.runtime = build_portable_strategy_runtime("mtf", symbol, config)

    def evaluate(self, evidence, *, now_ms: int):
        if evidence.symbol != self.symbol:
            raise ValueError("Signal source symbol mismatch")
        observed = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
        one = self.provider.fetch_klines(self.instrument, interval="1m", limit=240)
        five = self.provider.fetch_klines(self.instrument, interval="5m", limit=240)
        snapshot = SpotCandleSnapshot(tuple(_closed(one, 1, observed)),
                                     tuple(_closed(five, 5, observed)), observed)
        quantity = evidence.position_quantity
        entry = evidence.position_cost / quantity if quantity else Decimal("0")
        position = PositionView(float(quantity), float(entry))
        result = self.runtime.evaluate(CandleMarketInput(snapshot), position)[0]
        signal = result.decision(position)
        if snapshot.signal_bar_time is None:
            return signal, None
        key = f"bar:{int(snapshot.signal_bar_time.timestamp() * 1000)}"
        return signal, key
