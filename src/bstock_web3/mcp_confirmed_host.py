"""Schema-gated Spot client for an injected supported MCP host.

This module deliberately has no HTTP/OAuth transport, retains no tokens and
does not decide when to trade. Codex owns the authenticated Binance MCP session.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re

from .mcp_discovery import DiscoveryClient
from .mcp_readonly import READ_ONLY_TOOLS, ReadOnlyMcpClient


CONFIRMED_WRITE_TOOLS = frozenset({"spot.newOrder", "spot.getOrder"})
CONFIRMED_SESSION_TOOLS = READ_ONLY_TOOLS | CONFIRMED_WRITE_TOOLS


def _symbol(value):
    return (isinstance(value, str) and re.fullmatch(r"[A-Z0-9]{1,32}", value)
            is not None)


def _positive_decimal_string(value):
    if not isinstance(value, str) or len(value) > 128:
        return False
    try:
        number = Decimal(value)
    except InvalidOperation:
        return False
    return number.is_finite() and number > 0


def validate_confirmed_arguments(name, args):
    """Exact local contract, independently enforced above and below the client."""
    if not isinstance(args, dict):
        raise ValueError("Invalid confirmed MCP arguments")
    if name == "spot.getOrder":
        if set(args) != {"symbol", "origClientOrderId"}:
            raise ValueError("Unexpected Spot order lookup argument")
        if not _symbol(args["symbol"]):
            raise ValueError("Invalid MCP Spot symbol")
        client_id = args["origClientOrderId"]
        if (not isinstance(client_id, str)
                or re.fullmatch(r"bstock-[0-9a-f]{28}", client_id) is None):
            raise ValueError("Invalid Spot client order ID")
        return
    if name != "spot.newOrder":
        raise ValueError("MCP tool is not on the confirmed-write allowlist")
    common = {"symbol", "side", "type", "newClientOrderId", "newOrderRespType"}
    amount_names = set(args) - common
    if amount_names not in ({"quoteOrderQty"}, {"quantity"}):
        raise ValueError("Exactly one Spot order amount is required")
    if (not _symbol(args.get("symbol")) or args.get("type") != "MARKET"
            or args.get("newOrderRespType") != "FULL"
            or args.get("side") not in ("BUY", "SELL")):
        raise ValueError("Invalid confirmed Spot market order")
    if ((args["side"] == "BUY" and amount_names != {"quoteOrderQty"})
            or (args["side"] == "SELL" and amount_names != {"quantity"})):
        raise ValueError("Spot amount does not match order side")
    if not _positive_decimal_string(args[next(iter(amount_names))]):
        raise ValueError("Invalid Spot order amount")
    client_id = args.get("newClientOrderId")
    if (not isinstance(client_id, str)
            or re.fullmatch(r"bstock-[0-9a-f]{28}", client_id) is None):
        raise ValueError("Invalid Spot client order ID")


def _allows_string(schema):
    if not isinstance(schema, dict):
        return False
    kind = schema.get("type")
    if kind == "string" or isinstance(kind, list) and "string" in kind:
        return True
    alternatives = schema.get("anyOf") or schema.get("oneOf")
    return (isinstance(alternatives, list) and alternatives
            and any(_allows_string(item) for item in alternatives))


def _allows_number(schema):
    if not isinstance(schema, dict):
        return False
    kind = schema.get("type")
    if kind == "number" or isinstance(kind, list) and "number" in kind:
        return True
    alternatives = schema.get("anyOf") or schema.get("oneOf")
    return (isinstance(alternatives, list) and alternatives
            and any(_allows_number(item) for item in alternatives))


def _wire_decimal(value, schema):
    """Adapt an internal exact decimal string to the discovered wire schema.

    The real Binance MCP schema currently declares order amounts as JSON
    numbers.  Keep strings throughout policy/confirmation handling and convert
    only at the final host boundary.  Conversion fails closed unless Python's
    JSON float spelling round-trips to the exact same Decimal value.
    """
    if _allows_string(schema):
        return value
    if not _allows_number(schema):
        raise ValueError("Unsupported confirmed MCP amount schema")
    try:
        exact = Decimal(value)
        wire = float(value)
    except (InvalidOperation, OverflowError, TypeError, ValueError):
        raise ValueError("Spot amount cannot be represented by MCP schema") from None
    if (not math.isfinite(wire) or wire <= 0
            or Decimal(str(wire)) != exact):
        raise ValueError("Spot amount cannot be represented exactly by MCP schema")
    return wire


def validate_confirmed_schema(name, schema):
    """Fail closed if live tool discovery is incompatible with our contract."""
    expected = ({"symbol", "origClientOrderId"} if name == "spot.getOrder" else
        {"symbol", "side", "type", "newClientOrderId", "newOrderRespType",
         "quoteOrderQty", "quantity"} if name == "spot.newOrder" else None)
    if expected is None or not isinstance(schema, dict) \
            or schema.get("type") != "object":
        raise ValueError("Unsupported confirmed MCP schema")
    properties, required = schema.get("properties"), schema.get("required", [])
    if (not isinstance(properties, dict) or not expected <= properties.keys()
            or not isinstance(required, list)
            or any(not isinstance(item, str) for item in required)
            or not set(required) <= expected
            or not {"symbol"} <= set(required)):
        raise ValueError("Incompatible confirmed MCP schema")
    # getOrder documents orderId/origClientOrderId as a conditional choice, so
    # the live schema correctly requires only symbol.  Runtime validation above
    # still requires exactly origClientOrderId for lookup-only recovery.
    minimum_required = (set() if name == "spot.getOrder" else {"side", "type"})
    if not minimum_required <= set(required):
        raise ValueError("Incompatible confirmed MCP required fields")
    text_fields = ({"symbol", "origClientOrderId"} if name == "spot.getOrder"
        else {"symbol", "side", "type", "newClientOrderId",
              "newOrderRespType"})
    if any(not _allows_string(properties[key]) for key in text_fields):
        raise ValueError("Confirmed MCP string schema required")
    if name == "spot.newOrder" and any(
            not (_allows_string(properties[key])
                 or _allows_number(properties[key]))
            for key in ("quoteOrderQty", "quantity")):
        raise ValueError("Confirmed MCP amount schema required")
    if name == "spot.newOrder":
        enum_requirements = {
            "side": {"BUY", "SELL"}, "type": {"MARKET"},
            "newOrderRespType": {"FULL"},
        }
        for key, values in enum_requirements.items():
            enum = properties[key].get("enum")
            if enum is not None and (not isinstance(enum, list)
                    or any(not isinstance(item, str) for item in enum)
                    or not values <= set(enum)):
                raise ValueError("Incompatible confirmed MCP enum")


class ConfirmedMcpClient:
    """Discover schemas once, then expose a callable to the confirmed executor."""

    def __init__(self, exchange):
        self._exchange = exchange
        self._next_id = 20_000
        self._schemas = {}
        self.ready = False

    def initialize(self):
        discovery = DiscoveryClient(self._exchange)
        discovery.initialize()
        tools = discovery.list_tools()
        schemas = {item["name"]: item["inputSchema"] for item in tools
                   if item["name"] in CONFIRMED_SESSION_TOOLS}
        missing = CONFIRMED_SESSION_TOOLS - schemas.keys()
        if missing:
            raise ValueError("Required confirmed-session MCP tools unavailable")
        for name in CONFIRMED_WRITE_TOOLS:
            validate_confirmed_schema(name, schemas[name])
        self._schemas, self.ready = schemas, True

    def schema_report(self):
        if not self.ready:
            raise ValueError("Initialize before reading MCP schema report")
        selected = {name:self._schemas[name] for name in
                    sorted(CONFIRMED_WRITE_TOOLS)}
        canonical = json.dumps(selected, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False).encode("ascii")
        return {"protocolVersion":DiscoveryClient.VERSION,
            "readToolCount":len(READ_ONLY_TOOLS),
            "writeTools":sorted(CONFIRMED_WRITE_TOOLS),
            "writeSchemaSha256":hashlib.sha256(canonical).hexdigest()}

    def call(self, tool_name, arguments):
        if not self.ready:
            raise ValueError("Initialize before calling MCP tools")
        if tool_name not in CONFIRMED_SESSION_TOOLS:
            raise ValueError("MCP tool is not on the confirmed-session allowlist")
        if tool_name in READ_ONLY_TOOLS:
            ReadOnlyMcpClient._validate_arguments(tool_name, arguments)
        else:
            validate_confirmed_arguments(tool_name, arguments)
        wire_arguments = dict(arguments)
        if tool_name == "spot.newOrder":
            amount_name = "quoteOrderQty" if "quoteOrderQty" in arguments \
                else "quantity"
            wire_arguments[amount_name] = _wire_decimal(
                arguments[amount_name], self._schemas[tool_name]["properties"]
                [amount_name])
        self._next_id += 1
        request_id = self._next_id
        reply = self._exchange({"jsonrpc":"2.0", "id":request_id,
            "method":"tools/call", "params":{"name":tool_name,
                                                "arguments":wire_arguments}})
        if (not isinstance(reply, dict) or reply.get("jsonrpc") != "2.0"
                or type(reply.get("id")) is not int or reply["id"] != request_id
                or "error" in reply or not isinstance(reply.get("result"), dict)):
            raise ValueError("Invalid MCP tool response")
        result = reply["result"]
        if result.get("isError") is True:
            raise ValueError("Confirmed MCP tool failed")
        return ReadOnlyMcpClient._decode_result(result)

    def __call__(self, name, arguments):
        return self.call(name, arguments)
