from types import SimpleNamespace

import pytest

from bstock_web3.catalog import BinanceExchangeSpotCatalogClient


class Session:
    def __init__(self, status="TRADING"):
        self.status = status
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"symbols": [{
                "symbol": "BTCUSDT", "baseAsset": "BTC",
                "quoteAsset": "USDT", "status": self.status,
                "isSpotTradingAllowed": True,
            }]},
        )


def test_exchange_spot_catalog_resolves_public_symbol_and_status():
    session = Session()
    catalog = BinanceExchangeSpotCatalogClient(
        session=session, base_url="https://example.test/exchangeInfo")
    asset = catalog.resolve("btcusdt")
    assert asset.symbol == "BTC"
    assert asset.spot_symbol == "BTCUSDT"
    assert asset.contract_address == "" and asset.chain_id == ""
    status = catalog.market_status(asset)
    assert status.open_state and status.reason_code == "TRADING"
    assert all(call[1]["params"] == {"symbol": "BTCUSDT"}
               for call in session.calls)


def test_exchange_spot_catalog_reports_closed_market():
    session = Session("BREAK")
    catalog = BinanceExchangeSpotCatalogClient(session=session)
    asset = catalog.resolve("BTCUSDT")
    status = catalog.market_status(asset)
    assert not status.open_state and status.reason_code == "BREAK"


@pytest.mark.parametrize("symbol", ["", "BTC/USDT", "../BTCUSDT", "A" * 33])
def test_exchange_spot_catalog_rejects_invalid_symbol_before_network(symbol):
    session = Session()
    with pytest.raises(ValueError, match="symbol"):
        BinanceExchangeSpotCatalogClient(session=session).resolve(symbol)
    assert not session.calls
