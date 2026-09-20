import json

import pytest

from bstock_web3.mcp_confirmed_host import (CONFIRMED_SESSION_TOOLS,
    ConfirmedMcpClient, validate_confirmed_arguments,
    validate_confirmed_schema)
from bstock_web3.mcp_discovery import DiscoveryClient


def schema(name):
    fields = ({"symbol", "origClientOrderId"} if name == "spot.getOrder" else
        {"symbol", "side", "type", "newClientOrderId", "newOrderRespType",
         "quoteOrderQty", "quantity"})
    required = (["symbol", "origClientOrderId"] if name == "spot.getOrder" else
                ["symbol", "side", "type"])
    return {"type":"object", "properties":{key:{"type":"string"}
            for key in fields}, "required":required, "additionalProperties":False}


def buy():
    return {"symbol":"BTCUSDT", "side":"BUY", "type":"MARKET",
        "newClientOrderId":"bstock-" + "a" * 28,
        "newOrderRespType":"FULL", "quoteOrderQty":"10.00"}


class Exchange:
    def __init__(self): self.calls = []
    def __call__(self, message):
        self.calls.append(message)
        if "id" not in message: return None
        if message["method"] == "initialize":
            payload = {"protocolVersion":DiscoveryClient.VERSION,
                       "capabilities":{"tools":{}}, "serverInfo":{}}
        elif message["method"] == "tools/list":
            payload = {"tools":[{"name":name, "inputSchema":
                schema(name) if name.startswith("spot.") and name in {
                    "spot.newOrder", "spot.getOrder"} else {}}
                for name in sorted(CONFIRMED_SESSION_TOOLS)]}
        else:
            payload = {"ok":True, "name":message["params"]["name"]}
            return {"jsonrpc":"2.0", "id":message["id"], "result":
                {"content":[{"type":"text", "text":json.dumps(payload)}]}}
        return {"jsonrpc":"2.0", "id":message["id"], "result":payload}


def test_confirmed_client_discovers_schema_and_calls_exact_order():
    exchange = Exchange()
    client = ConfirmedMcpClient(exchange)
    client.initialize()
    assert client("spot.newOrder", buy()) == {"ok":True, "name":"spot.newOrder"}
    lookup = {"symbol":"BTCUSDT", "origClientOrderId":"bstock-" + "a" * 28}
    assert client("spot.getOrder", lookup)["ok"]


def test_read_tool_remains_available_in_same_reconciled_session():
    exchange = Exchange()
    client = ConfirmedMcpClient(exchange)
    client.initialize()
    assert client.call("spot.getAccount", {})["name"] == "spot.getAccount"


@pytest.mark.parametrize("changes", [
    {"side":"SELL"}, {"type":"LIMIT"}, {"newOrderRespType":"ACK"},
    {"quoteOrderQty":"0"}, {"quoteOrderQty":"NaN"},
    {"newClientOrderId":"external-id"}, {"symbol":"btcUSDT"},
    {"quantity":"1"}, {"recvWindow":5000},
])
def test_invalid_buy_is_rejected_before_exchange(changes):
    args = buy(); args.update(changes)
    with pytest.raises(ValueError):
        validate_confirmed_arguments("spot.newOrder", args)


def test_valid_sell_and_exact_lookup():
    args = buy()
    args.update(side="SELL", quantity="0.001")
    args.pop("quoteOrderQty")
    validate_confirmed_arguments("spot.newOrder", args)
    validate_confirmed_arguments("spot.getOrder", {
        "symbol":"BTCUSDT", "origClientOrderId":args["newClientOrderId"]})


@pytest.mark.parametrize("changes", [
    {}, {"symbol":"BTCUSDT"},
    {"symbol":"BTCUSDT", "origClientOrderId":"bad"},
    {"symbol":"BTCUSDT", "origClientOrderId":"bstock-" + "a"*28,
     "orderId":1},
])
def test_invalid_lookup_rejected(changes):
    with pytest.raises(ValueError):
        validate_confirmed_arguments("spot.getOrder", changes)


def test_unknown_tool_and_call_before_initialize_rejected_without_exchange():
    exchange = Exchange(); client = ConfirmedMcpClient(exchange)
    with pytest.raises(ValueError, match="Initialize"):
        client.call("spot.newOrder", buy())
    client.initialize(); count = len(exchange.calls)
    with pytest.raises(ValueError, match="allowlist"):
        client.call("wallet.withdraw", {})
    assert len(exchange.calls) == count


def test_missing_tool_or_incompatible_schema_fails_initialization():
    exchange = Exchange(); original = exchange.__call__
    def missing(message):
        result = original(message)
        if message.get("method") == "tools/list":
            result["result"]["tools"] = [row for row in result["result"]["tools"]
                if row["name"] != "spot.newOrder"]
        return result
    with pytest.raises(ValueError, match="unavailable"):
        ConfirmedMcpClient(missing).initialize()

    exchange = Exchange(); original = exchange.__call__
    def numeric(message):
        result = original(message)
        if message.get("method") == "tools/list":
            row = next(row for row in result["result"]["tools"]
                       if row["name"] == "spot.newOrder")
            row["inputSchema"]["properties"]["quoteOrderQty"] = {"type":"number"}
        return result
    with pytest.raises(ValueError, match="string schema"):
        ConfirmedMcpClient(numeric).initialize()


def test_schema_rejects_extra_required_or_missing_contract_field():
    value = schema("spot.newOrder")
    value["required"].append("timestamp")
    with pytest.raises(ValueError, match="schema"):
        validate_confirmed_schema("spot.newOrder", value)
    value = schema("spot.newOrder")
    value["properties"].pop("quantity")
    with pytest.raises(ValueError, match="schema"):
        validate_confirmed_schema("spot.newOrder", value)
