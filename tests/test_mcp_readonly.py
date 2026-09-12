import json

import pytest

from bstock_web3.mcp_discovery import DiscoveryClient
from bstock_web3.mcp_readonly import (READ_ONLY_TOOLS, ReadOnlyMcpClient,
    collect_spot_reads)


class Exchange:
    def __init__(self):
        self.calls = []

    def __call__(self, message):
        self.calls.append(message)
        if "id" not in message:
            return None
        if message["method"] == "initialize":
            result = {"protocolVersion":DiscoveryClient.VERSION,
                "capabilities":{"tools":{}}, "serverInfo":{}}
        elif message["method"] == "tools/list":
            result = {"tools":[{"name":name, "inputSchema":{}}
                               for name in sorted(READ_ONLY_TOOLS)]}
        else:
            name = message["params"]["name"]
            args = message["params"]["arguments"]
            payload = self.payload(name, args)
            result = {"content":[{"type":"text",
                "text":json.dumps(payload)}]}
        return {"jsonrpc":"2.0", "id":message["id"], "result":result}

    @staticmethod
    def payload(name, args):
        if name == "spot.getAccount": return {"accountType":"SPOT"}
        if name in {"spot.getOpenOrders", "spot.myTrades", "spot.allOrders"}:
            return []
        if name == "spot.accountCommission": return {"symbol":args["symbol"]}
        if name == "spot.exchangeInfo": return {"symbols":[]}
        return {"symbol":args["symbol"], "bidPrice":"1", "askPrice":"2"}


def test_readonly_client_discovers_and_collects_exact_allowlist():
    exchange = Exchange()
    client = ReadOnlyMcpClient(exchange)
    client.initialize()
    bundle = collect_spot_reads(client, "BTCUSDT")
    assert bundle.account == {"accountType":"SPOT"}
    called = [row["params"]["name"] for row in exchange.calls
              if row.get("method") == "tools/call"]
    assert set(called) == READ_ONLY_TOOLS
    assert all(row["params"]["name"] != "spot.newOrder"
               for row in exchange.calls if row.get("method") == "tools/call")


def test_write_tool_and_unexpected_arguments_are_blocked_before_exchange():
    exchange = Exchange()
    client = ReadOnlyMcpClient(exchange)
    client.initialize()
    before = len(exchange.calls)
    with pytest.raises(ValueError, match="allowlist"):
        client.call("spot.newOrder", {"symbol":"BTCUSDT"})
    with pytest.raises(ValueError, match="Unexpected"):
        client.call("spot.getOpenOrders", {"symbol":"BTCUSDT", "side":"BUY"})
    assert len(exchange.calls) == before


def test_missing_required_read_tool_fails_initialization():
    exchange = Exchange()
    original = exchange.__call__
    def missing(message):
        reply = original(message)
        if message.get("method") == "tools/list":
            reply["result"]["tools"] = reply["result"]["tools"][:-1]
        return reply
    client = ReadOnlyMcpClient(missing)
    with pytest.raises(ValueError, match="unavailable"):
        client.initialize()


def test_paginated_reads_reject_repeated_ids():
    exchange = Exchange()
    client = ReadOnlyMcpClient(exchange)
    client.initialize()
    original = exchange.payload
    def repeated(name, args):
        if name == "spot.myTrades":
            return [{"id":1}] * 1000
        return original(name, args)
    exchange.payload = repeated
    with pytest.raises(ValueError, match="ordering"):
        collect_spot_reads(client, "BTCUSDT")


@pytest.mark.parametrize("symbol", ["btcUSDT", "BTC-USDT", "", "X"*33])
def test_symbol_validation_is_fail_closed(symbol):
    exchange = Exchange()
    client = ReadOnlyMcpClient(exchange)
    client.initialize()
    with pytest.raises(ValueError, match="symbol"):
        client.call("spot.getOpenOrders", {"symbol":symbol})
