from datetime import datetime, timezone
from decimal import Decimal

import pytest

from bstock_web3.mcp_bridge import McpAccountBinding
from bstock_web3.mcp_equity_guard import McpSpotEquityGuard
from bstock_web3.mcp_host_receipt import VerifiedSpotHostReceipt


BINDING = McpAccountBinding("1.0", "agentic-primary",
    "sha256(salt-bytes+uid-ascii)", "a" * 64, "b" * 64)
BASE_TIME = 2_000_000
BUY = {"symbol": "BTCUSDT", "id": 1, "orderId": 101,
    "time": BASE_TIME + 1000, "isBuyer": True, "qty": "1",
    "quoteQty": "50", "commission": "0", "commissionAsset": "USDT"}
SELL = {"symbol": "BTCUSDT", "id": 2, "orderId": 102,
    "time": BASE_TIME + 3000, "isBuyer": False, "qty": "1",
    "quoteQty": "40", "commission": "0", "commissionAsset": "USDT"}


def receipt(request_id="baseline", *, when=BASE_TIME, quote="100",
            base="0", bid="50", trades=()):
    rows = list(trades)
    info = {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING",
        "isSpotTradingAllowed": True, "quoteOrderQtyMarketAllowed": True,
        "orderTypes": ["MARKET"], "baseAsset": "BTC", "quoteAsset": "USDT",
        "filters": [
            {"filterType": "LOT_SIZE", "minQty": "0.000001",
             "maxQty": "100", "stepSize": "0.000001"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "5",
             "applyToMarket": True},
            {"filterType": "MARKET_LOT_SIZE", "minQty": "0",
             "maxQty": "0", "stepSize": "0"}]}]}
    tools = {
        "spot.getAccount": {"accountType": "SPOT", "canTrade": True,
            "balances": [{"asset": "BTC", "free": base, "locked": "0"},
                         {"asset": "USDT", "free": quote, "locked": "0"}]},
        "spot.getOpenOrders": [], "spot.myTrades": rows,
        "spot.allOrders": [{"symbol": "BTCUSDT", "orderId": row["orderId"]}
                           for row in rows],
        "spot.accountCommission": {"symbol": "BTCUSDT"},
        "spot.exchangeInfo": info,
        "spot.tickerBookTicker": {"symbol": "BTCUSDT",
                                  "bidPrice": bid, "askPrice": str(Decimal(bid) + 1)},
    }
    observed = datetime.fromtimestamp(when / 1000, timezone.utc).isoformat(
        ).replace("+00:00", "Z")
    return VerifiedSpotHostReceipt(request_id, "BTCUSDT", "agentic-primary",
        "b" * 64, observed, "BTC", "USDT", tools, BINDING, False)


def guard(path):
    return McpSpotEquityGuard(
        path, account_ref="agentic-primary",
        account_fingerprint="b" * 64, symbol="BTCUSDT")


def test_explicit_baseline_and_cumulative_mark_to_market_loss(tmp_path):
    path = tmp_path / "risk.json"
    with guard(path) as state:
        with pytest.raises(ValueError, match="confirmation"):
            state.initialize(receipt(), operator_confirmed=False)
        initial = state.initialize(receipt(), operator_confirmed=True)
        assert initial.cumulative_loss == Decimal("0")
        assert state.observe(receipt()).cumulative_loss == Decimal("0")
    bought = receipt("after-buy", when=BASE_TIME + 2000, quote="50",
                     base="1", bid="39", trades=(BUY,))
    with guard(path) as state:
        result = state.observe(bought)
        assert result.equity == Decimal("89")
        assert result.cumulative_loss == Decimal("11")
    with guard(path) as state:
        assert state.observe(bought).cumulative_loss == Decimal("11")
        sold = receipt("after-sell", when=BASE_TIME + 4000, quote="90",
                       base="0", bid="39", trades=(BUY, SELL))
        assert state.observe(sold).cumulative_loss == Decimal("10")


def test_unexplained_transfer_and_changed_history_fail_without_advancing(tmp_path):
    path = tmp_path / "risk.json"
    with guard(path) as state:
        state.initialize(receipt(), operator_confirmed=True)
        bought = receipt("after-buy", when=BASE_TIME + 2000, quote="50",
                         base="1", bid="39", trades=(BUY,))
        state.observe(bought)
        with pytest.raises(ValueError, match="Unexplained"):
            state.observe(receipt("deposit", when=BASE_TIME + 3000,
                quote="51", base="1", bid="39", trades=(BUY,)))
        assert state.state["last_request_id"] == "after-buy"
        altered = dict(BUY, quoteQty="49")
        with pytest.raises(ValueError, match="changed or shrank"):
            state.observe(receipt("altered", when=BASE_TIME + 3000,
                quote="50", base="1", bid="39", trades=(altered,)))


def test_missing_baseline_or_account_drift_fails_closed(tmp_path):
    path = tmp_path / "risk.json"
    with guard(path) as state:
        with pytest.raises(RuntimeError, match="baseline"):
            state.observe(receipt())
        state.initialize(receipt(), operator_confirmed=True)
        changed = receipt("other", when=BASE_TIME + 1000)
        changed = VerifiedSpotHostReceipt(
            changed.request_id, changed.symbol, changed.account_ref,
            "c" * 64, changed.observed_at, changed.base_asset,
            changed.quote_asset, changed.tool_results, changed.binding, False)
        with pytest.raises(ValueError, match="account or symbol changed"):
            state.observe(changed)
