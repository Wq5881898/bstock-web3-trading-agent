from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sys

import pytest

from bstock_web3.catalog import BStockAsset, BStockMarketStatus
from bstock_web3.mcp_bridge import McpAccountBinding, ACCOUNT_BINDING_ALGORITHM
from bstock_web3 import mcp_cli
from bstock_web3.strategy import SignalDecision


def binding():
    return McpAccountBinding("1.0", "agentic-primary",
        ACCOUNT_BINDING_ALGORITHM, "a" * 64, "b" * 64)


class Receipt:
    symbol = "BTCUSDT"

    def __init__(self, observed_at, quantity="0.00000988"):
        self.observed_at = observed_at
        self.quantity = quantity

    def summary(self):
        return {"positionQuantity": self.quantity,
                "positionCost": "0.85000000"}

    def tradable_position(self):
        return Decimal(self.quantity), Decimal("0.85000000")


def test_verified_position_rejects_stale_or_wrong_symbol(monkeypatch, tmp_path):
    now = datetime(2026, 9, 22, 22, tzinfo=timezone.utc)
    old = Receipt((now - timedelta(seconds=16)).isoformat())
    monkeypatch.setattr(mcp_cli, "load_verified_receipt", lambda *_: old)
    with pytest.raises(ValueError, match="not fresh"):
        mcp_cli._verified_position(tmp_path / "receipt.json", binding(),
                                   symbol="BTCUSDT", now=now)
    old.observed_at = now.isoformat()
    old.symbol = "NVDAB"
    with pytest.raises(ValueError, match="symbol mismatch"):
        mcp_cli._verified_position(tmp_path / "receipt.json", binding(),
                                   symbol="BTCUSDT", now=now)


def test_spot_plan_cli_uses_verified_position_and_no_plan_on_hold(
        monkeypatch, tmp_path, capsys):
    receipt = Receipt(datetime.now(timezone.utc).isoformat())
    monkeypatch.setattr(mcp_cli, "load_mcp_account_binding", lambda *_: binding())
    monkeypatch.setattr(mcp_cli, "load_verified_receipt", lambda *_: receipt)

    class Catalog:
        def resolve(self, symbol):
            assert symbol == "BTCUSDT"
            return BStockAsset("BTC", "BTC", "", "", symbol, "1")

        def market_status(self, _asset):
            return BStockMarketStatus(True, "TRADING", None, "TRADING")

    class Feed:
        def fetch(self, _asset):
            return object()

    class Strategy:
        def evaluate(self, _snapshot, position):
            assert position.quantity == float(receipt.quantity)
            return SignalDecision("hold", "test", None, None)

    monkeypatch.setattr(mcp_cli, "BinanceExchangeSpotCatalogClient", Catalog)
    monkeypatch.setattr(mcp_cli, "BStockMultiTimeframeFeed", Feed)
    monkeypatch.setattr(mcp_cli, "MtfEmaStrategy", Strategy)
    monkeypatch.setattr(sys, "argv", ["bstock-mcp-plan", "--verified-snapshot",
                                  str(tmp_path / "receipt.json")])
    assert mcp_cli.main() == 0
    assert json.loads(capsys.readouterr().out)["mcpPlanCreated"] is False


def test_spot_plan_cli_rejects_web3_symbol_before_network(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["bstock-mcp-plan", "--symbol", "NVDAB",
                                  "--verified-snapshot", str(tmp_path / "r.json")])
    with pytest.raises(SystemExit, match="2"):
        mcp_cli.main()
