from datetime import datetime, timezone
from decimal import Decimal

import pytest

from bstock_web3.spot_api_reconcile import SpotApiReconciler

NOW = int(datetime(2026, 9, 22, 12, tzinfo=timezone.utc).timestamp() * 1000)


class FakeReadApi:
    def __init__(self):
        self.quote = "200"
        self.base = "0"
        self.bid = "100"
        self.trades = []
        self.orders = []

    def exchange_info(self, symbol):
        return {"symbols": [{"symbol": symbol, "status": "TRADING",
            "isSpotTradingAllowed": True, "quoteOrderQtyMarketAllowed": True,
            "orderTypes": ["MARKET"], "baseAsset": "BTC", "quoteAsset": "USDT",
            "filters": [{"filterType": "LOT_SIZE", "minQty": "0.001",
                         "maxQty": "100", "stepSize": "0.001"},
                        {"filterType": "MIN_NOTIONAL", "minNotional": "5",
                         "applyToMarket": True}]}]}

    def open_orders_all(self): return []
    def my_trades(self, symbol, *, from_id, limit):
        return [row for row in self.trades if row["id"] >= from_id]
    def all_orders(self, symbol, *, order_id, limit):
        return [row for row in self.orders if row["orderId"] >= order_id]
    def commission(self, symbol):
        return {"symbol": symbol,
            "standardCommission": {"taker": "0.001", "buyer": "0", "seller": "0"},
            "specialCommission": {"taker": "0", "buyer": "0", "seller": "0"},
            "taxCommission": {"taker": "0", "buyer": "0", "seller": "0"}}
    def book_ticker(self, symbol):
        return {"symbol": symbol, "bidPrice": self.bid, "askPrice": "101"}
    def account(self):
        return {"accountType": "SPOT", "canTrade": True, "balances": [
            {"asset": "USDT", "free": self.quote, "locked": "0"},
            {"asset": "BTC", "free": self.base, "locked": "0"}]}


def test_full_fill_equity_and_unexplained_transfer_guard(tmp_path):
    api = FakeReadApi()
    reconciler = SpotApiReconciler(api, tmp_path, account_ref="api-test",
        symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT")
    initial = reconciler.initialize(now_ms=NOW)
    assert initial.evidence.daily_equity_loss == 0
    api.quote, api.base = "100", "1"
    api.trades = [{"symbol": "BTCUSDT", "id": 1, "orderId": 99,
        "time": NOW + 1, "isBuyer": True, "qty": "1", "quoteQty": "100",
        "commission": "0", "commissionAsset": "USDT"}]
    api.orders = [{"symbol": "BTCUSDT", "orderId": 99}]
    api.bid = "80"
    current = reconciler.read(now_ms=NOW + 2)
    assert current.evidence.position_quantity == Decimal("1")
    assert current.evidence.daily_equity_loss == Decimal("20")
    api.quote = "101"
    with pytest.raises(ValueError, match="Unexplained"):
        reconciler.read(now_ms=NOW + 3)


def test_missing_baseline_blocks_read(tmp_path):
    reconciler = SpotApiReconciler(FakeReadApi(), tmp_path,
        account_ref="api-test", symbol="BTCUSDT", base_asset="BTC",
        quote_asset="USDT")
    with pytest.raises(RuntimeError, match="not initialized"):
        reconciler.read(now_ms=NOW)
