from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from bstock_web3.models import Kline
from bstock_web3.spot_signal_source import SpotMtfSignalSource

def test_registered_mtf_uses_only_closed_binance_spot_candles():
    observed = datetime(2026, 9, 22, 12, 0, 30, tzinfo=timezone.utc)
    minute = observed.replace(second=0)
    one = [Kline(minute - timedelta(minutes=240 - i), 100, 100, 100, 100, 1)
           for i in range(240)]
    five = [Kline(minute - timedelta(minutes=1200 - i * 5), 100, 100, 100, 100, 1)
            for i in range(240)]
    one.append(Kline(minute, 999, 999, 999, 999, 1))  # current bar is incomplete
    class Provider:
        def __init__(self): self.calls = []
        def fetch_klines(self, instrument, *, interval, limit):
            assert instrument.provider_symbol == "BTCUSDT"
            self.calls.append(interval)
            return one if interval == "1m" else five
    provider = Provider()
    source = SpotMtfSignalSource("BTCUSDT", "BTC", "USDT", provider=provider)
    account = SimpleNamespace(symbol="BTCUSDT", position_quantity=Decimal("0"),
                              position_cost=Decimal("0"))
    decision, key = source.evaluate(account,
        now_ms=int(observed.timestamp() * 1000))
    assert decision.action == "hold"
    assert decision.price == 100
    assert key == f"bar:{int(one[-2].time.timestamp() * 1000)}"
    assert provider.calls == ["1m", "5m"]
