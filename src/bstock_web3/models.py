from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Kline:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class MarketInstrument:
    venue: str
    market_type: str
    symbol: str
    base_asset: str
    quote_asset: str
    provider_symbol: str
