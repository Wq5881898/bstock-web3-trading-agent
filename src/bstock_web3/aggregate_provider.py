"""Pinned public market-data reader. No credentials, orders or redirects."""
import json
import math
import re
import time

import requests

from .median_ticks import AggregateTick
from .provider import DEFAULT_SPOT_MARKET_URL


class AggregateTradeProvider:
    def __init__(self, *, session=None, clock=time.monotonic):
        self.session = session or requests.Session()
        self._owned = session is None
        if self._owned:
            self.session.trust_env = False
        self.clock = clock
        self.retry_at = 0.0

    def close(self):
        if self._owned:
            self.session.close()

    def fetch(self, symbol, *, from_id=None, limit=1000):
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9]{1,32}", symbol):
            raise ValueError("Invalid public trade symbol")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Trade page limit must be 1–1000")
        if from_id is not None and (type(from_id) is not int or not 0 <= from_id <= 9223372036854775807):
            raise ValueError("Invalid aggregate trade cursor")
        if self.clock() < self.retry_at:
            raise ValueError("Public trade endpoint cooling down")
        params = {"symbol": symbol, "limit": limit}
        if from_id is not None:
            params["fromId"] = from_id
        try:
            with self.session.get(DEFAULT_SPOT_MARKET_URL + "/api/v3/aggTrades", params=params,
                                  timeout=(5, 10), allow_redirects=False, stream=True) as response:
                if response.status_code in (418, 429):
                    try:
                        delay = float(response.headers.get("Retry-After", "60"))
                        if not math.isfinite(delay) or delay < 0:
                            delay = 60
                    except (TypeError, ValueError):
                        delay = 60
                    self.retry_at = self.clock() + max(1, delay)
                    raise ValueError("Public market rate limit; waiting for Retry-After")
                if response.status_code != 200:
                    raise ValueError(f"Public market HTTP status {response.status_code}")
                body = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    body.extend(chunk)
                    if len(body) > 1048576:
                        raise ValueError("Public trade response too large")
                rows = json.loads(body)
                if not isinstance(rows, list) or len(rows) > limit:
                    raise ValueError("Invalid public trade page")
                ticks = [AggregateTick.from_wire(row) for row in rows]
                if ticks and from_id is not None and ticks[0].trade_id != from_id:
                    raise ValueError("Server did not return the requested trade cursor")
                for left, right in zip(ticks, ticks[1:]):
                    if right.trade_id != left.trade_id + 1 or right.time_ms < left.time_ms:
                        raise ValueError("Non-contiguous public trade response")
                return rows
        except (requests.RequestException, ValueError):
            self.retry_at = max(self.retry_at, self.clock() + 3)
            raise
