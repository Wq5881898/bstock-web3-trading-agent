from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any

import requests

from .models import Kline, MarketInstrument


DEFAULT_SPOT_MARKET_URL = "https://data-api.binance.vision"


class BinanceSpotKlineProvider:
    """Public market data only; this class cannot place orders."""

    def __init__(self, *, base_url: str = DEFAULT_SPOT_MARKET_URL,
                 timeout: float = 10.0, session: Any | None = None,
                 max_retries: int = 3, retry_backoff_seconds: float = 0.25,
                 sleeper: Any = time.sleep) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.sleeper = sleeper
        if self.max_retries < 1:
            raise ValueError("max_retries 必须至少为 1")

    def fetch_klines(self, instrument: MarketInstrument, *, interval: str = "1m",
                     limit: int = 1000, start_time_ms: int | None = None,
                     end_time_ms: int | None = None) -> list[Kline]:
        if not 1 <= limit <= 1000:
            raise ValueError("Binance Spot K线 limit 必须在 1 到 1000 之间")
        params: dict[str, Any] = {
            "symbol": instrument.provider_symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_time_ms is not None:
            params["startTime"] = int(start_time_ms)
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(
                    f"{self.base_url}/api/v3/klines", params=params, timeout=self.timeout
                )
                response.raise_for_status()
                return [self._parse(row) for row in response.json()]
            except (requests.RequestException, ValueError, KeyError, TypeError):
                if attempt + 1 >= self.max_retries:
                    raise
                self.sleeper(self.retry_backoff_seconds * (2 ** attempt))
        raise AssertionError("unreachable")

    @staticmethod
    def _parse(row: list[Any]) -> Kline:
        return Kline(
            time=datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc),
            open=float(row[1]), high=float(row[2]), low=float(row[3]),
            close=float(row[4]), volume=float(row[5]),
        )

