"""Bounded, allowlisted Binance Agent OS MCP Spot read client."""
from __future__ import annotations

from dataclasses import dataclass
import json

from .mcp_discovery import DiscoveryClient
from .mcp_http import DiscoveryHTTP


READ_ONLY_TOOLS = frozenset({
    "spot.getAccount", "spot.getOpenOrders", "spot.myTrades",
    "spot.allOrders", "spot.accountCommission", "spot.exchangeInfo",
    "spot.tickerBookTicker",
})


class ReadOnlyHTTP(DiscoveryHTTP):
    """HTTP transport that adds only MCP tools/call to the base protocol."""
    ALLOWED_METHODS = DiscoveryHTTP.ALLOWED_METHODS | {"tools/call"}

    def __call__(self, message):
        if isinstance(message, dict) and message.get("method") == "tools/call":
            params = message.get("params")
            if (not isinstance(params, dict) or set(params) != {"name", "arguments"}
                    or params.get("name") not in READ_ONLY_TOOLS
                    or not isinstance(params.get("arguments"), dict)):
                raise ValueError("MCP tool is not on the read-only allowlist")
            ReadOnlyMcpClient._validate_arguments(
                params["name"], params["arguments"])
        return super().__call__(message)


class ReadOnlyMcpClient:
    def __init__(self, exchange):
        self._exchange = exchange
        self._next_id = 10_000
        self._schemas = {}
        self.ready = False

    def initialize(self):
        discovery = DiscoveryClient(self._exchange)
        discovery.initialize()
        tools = discovery.list_tools()
        self._schemas = {item["name"]: item["inputSchema"] for item in tools
                         if item["name"] in READ_ONLY_TOOLS}
        missing = READ_ONLY_TOOLS - self._schemas.keys()
        if missing:
            raise ValueError("Required read-only MCP tools unavailable")
        self.ready = True

    def call(self, tool_name, arguments):
        if not self.ready:
            raise ValueError("Initialize before calling MCP tools")
        if tool_name not in READ_ONLY_TOOLS or tool_name not in self._schemas:
            raise ValueError("MCP tool is not on the read-only allowlist")
        if not isinstance(arguments, dict):
            raise ValueError("Invalid MCP tool arguments")
        self._validate_arguments(tool_name, arguments)
        self._next_id += 1
        request_id = self._next_id
        reply = self._exchange({"jsonrpc":"2.0", "id":request_id,
            "method":"tools/call", "params":{"name":tool_name,
            "arguments":arguments}})
        if (not isinstance(reply, dict) or reply.get("jsonrpc") != "2.0"
                or type(reply.get("id")) is not int or reply["id"] != request_id
                or "error" in reply or not isinstance(reply.get("result"), dict)):
            raise ValueError("Invalid MCP tool response")
        result = reply["result"]
        if result.get("isError") is True:
            raise ValueError("MCP read tool failed")
        return self._decode_result(result)

    @staticmethod
    def _validate_arguments(name, args):
        allowed = {
            "spot.getAccount":{"omitZeroBalances", "recvWindow"},
            "spot.getOpenOrders":{"symbol", "recvWindow"},
            "spot.myTrades":{"symbol", "orderId", "startTime", "endTime",
                             "fromId", "limit", "recvWindow"},
            "spot.allOrders":{"symbol", "orderId", "startTime", "endTime",
                              "limit", "recvWindow"},
            "spot.accountCommission":{"symbol"},
            "spot.exchangeInfo":{"symbol", "showPermissionSets"},
            "spot.tickerBookTicker":{"symbol", "symbolStatus"},
        }[name]
        if not set(args) <= allowed:
            raise ValueError("Unexpected MCP tool argument")
        symbol = args.get("symbol")
        if name != "spot.getAccount" and (not isinstance(symbol, str)
                or not symbol.isalnum() or symbol != symbol.upper()
                or len(symbol) > 32):
            raise ValueError("Invalid MCP Spot symbol")
        if "limit" in args and (type(args["limit"]) is not int
                or not 1 <= args["limit"] <= 1000):
            raise ValueError("Invalid MCP page limit")
        for key in ("fromId", "orderId", "startTime", "endTime"):
            if key in args and (type(args[key]) is not int or args[key] < 0):
                raise ValueError("Invalid MCP pagination value")

    @staticmethod
    def _decode_result(result):
        if "structuredContent" in result:
            return result["structuredContent"]
        content = result.get("content")
        if (not isinstance(content, list) or len(content) != 1
                or not isinstance(content[0], dict)
                or content[0].get("type") != "text"
                or not isinstance(content[0].get("text"), str)
                or len(content[0]["text"]) > 2_000_000):
            raise ValueError("Invalid MCP read content")
        try:
            return json.loads(content[0]["text"])
        except json.JSONDecodeError:
            raise ValueError("Invalid MCP read JSON") from None


@dataclass(frozen=True)
class SpotReadBundle:
    account: dict
    open_orders: list
    trades: list
    all_orders: list
    commission: dict
    exchange_info: dict
    book: dict


def _paginate(client, tool, symbol, cursor_name, row_id, max_pages):
    if type(max_pages) is not int or not 1 <= max_pages <= 100:
        raise ValueError("Invalid MCP pagination bound")
    rows, cursor = [], 0
    seen = set()
    for _ in range(max_pages):
        page = client.call(tool, {"symbol":symbol, cursor_name:cursor,
                                  "limit":1000})
        if not isinstance(page, list) or len(page) > 1000:
            raise ValueError("Invalid MCP page")
        if not page:
            return rows
        ids = []
        for row in page:
            if not isinstance(row, dict) or type(row.get(row_id)) is not int:
                raise ValueError("Invalid MCP paginated row")
            ids.append(row[row_id])
        if ids != sorted(ids) or len(ids) != len(set(ids)) or any(
                item in seen for item in ids) or ids[0] < cursor:
            raise ValueError("Invalid MCP page ordering")
        rows.extend(page)
        seen.update(ids)
        if len(page) < 1000:
            return rows
        cursor = ids[-1] + 1
    raise ValueError("MCP pagination bound reached")


def collect_spot_reads(client: ReadOnlyMcpClient, symbol: str,
                       *, max_pages=20) -> SpotReadBundle:
    """Collect one bounded snapshot. Every operation is on the allowlist."""
    account = client.call("spot.getAccount", {"omitZeroBalances":True})
    open_orders = client.call("spot.getOpenOrders", {"symbol":symbol})
    trades = _paginate(client, "spot.myTrades", symbol, "fromId", "id",
                       max_pages)
    orders = _paginate(client, "spot.allOrders", symbol, "orderId", "orderId",
                       max_pages)
    commission = client.call("spot.accountCommission", {"symbol":symbol})
    exchange_info = client.call("spot.exchangeInfo", {
        "symbol":symbol, "showPermissionSets":True})
    book = client.call("spot.tickerBookTicker", {"symbol":symbol,
                                                  "symbolStatus":"TRADING"})
    if not isinstance(account, dict) or not isinstance(open_orders, list) \
            or not isinstance(commission, dict) \
            or not isinstance(exchange_info, dict) or not isinstance(book, dict):
        raise ValueError("Invalid MCP Spot snapshot shape")
    return SpotReadBundle(account, open_orders, trades, orders, commission,
                          exchange_info, book)
