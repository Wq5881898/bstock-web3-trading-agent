from types import SimpleNamespace

import requests

from bstock_web3.models import MarketInstrument
from bstock_web3.provider import BinanceSpotKlineProvider


class Session:
    def __init__(self):
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        if self.calls < 3:
            raise requests.ConnectionError("temporary")
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: [[1_788_796_800_000, "100", "101", "99", "100.5", "2"]],
        )


def test_kline_provider_retries_transient_network_errors():
    session = Session()
    sleeps = []
    provider = BinanceSpotKlineProvider(session=session, max_retries=3,
        retry_backoff_seconds=0.01, sleeper=sleeps.append)
    instrument = MarketInstrument("BINANCE", "BSTOCK_SPOT", "NVDAB",
                                  "NVDAB", "USDT", "NVDABUSDT")
    rows = provider.fetch_klines(instrument)
    assert len(rows) == 1
    assert session.calls == 3
    assert sleeps == [0.01, 0.02]
