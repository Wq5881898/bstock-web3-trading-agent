from bstock_web3.catalog import BStockCatalogClient


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"success": True, "code": "000000", "data": [
            {"type": 3, "chainId": "56", "ticker": "NVDA", "symbol": "NVDAB",
             "contractAddress": "0x123", "cs": "NVDABUSDT", "multiplier": "1"},
            {"type": 2, "chainId": "56", "symbol": "IGNORED", "contractAddress": "0x0"},
        ]}


class Session:
    def get(self, *args, **kwargs):
        return Response()


def test_catalog_filters_type_three_bsc_assets():
    asset = BStockCatalogClient(session=Session()).resolve("NVDA")
    assert asset.symbol == "NVDAB"
    assert asset.spot_symbol == "NVDABUSDT"

