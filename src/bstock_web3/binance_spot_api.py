"""Narrow Binance Spot REST transport for an explicitly armed API session.

This module has no credential storage, generic request method, withdrawal,
transfer, or order-cancellation capability. In particular POST is never retried.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import os
import re
import time
from urllib.parse import urlencode

import requests


PRODUCTION_URL = "https://api.binance.com"
TESTNET_URL = "https://testnet.binance.vision"
ALLOWED_URLS = frozenset((PRODUCTION_URL, TESTNET_URL))


@dataclass(frozen=True)
class SpotApiCredentials:
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)

    def __post_init__(self):
        if not self.api_key or not self.api_secret:
            raise ValueError("Binance Spot API credentials are required")

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("BINANCE_API_KEY", ""),
                   os.environ.get("BINANCE_API_SECRET", ""))

    @property
    def fingerprint(self):
        return hashlib.sha256(self.api_key.encode("utf-8")).hexdigest()


class SpotApiError(RuntimeError):
    """A REST call failed; never infer that a POST was not accepted."""


class BinanceSpotApi:
    def __init__(self, credentials: SpotApiCredentials, *,
                 base_url: str = PRODUCTION_URL, session=None,
                 clock_ms=None, timeout_seconds: float = 10):
        if not isinstance(credentials, SpotApiCredentials):
            raise ValueError("Spot API credentials required")
        if base_url not in ALLOWED_URLS:
            raise ValueError("Spot API base URL is not allowlisted")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Invalid Spot API timeout")
        self.credentials = credentials
        self.base_url = base_url
        self.session = session or requests.Session()
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.timeout_seconds = timeout_seconds

    @property
    def account_fingerprint(self):
        return self.credentials.fingerprint

    def _request(self, method, path, params=None, *, signed=False):
        if path not in {
            "/api/v3/time", "/api/v3/exchangeInfo", "/api/v3/ticker/bookTicker",
            "/api/v3/account", "/api/v3/openOrders", "/api/v3/myTrades",
            "/api/v3/allOrders", "/api/v3/order", "/api/v3/account/commission",
        } or (method == "POST" and path != "/api/v3/order") or method not in {"GET", "POST"}:
            raise ValueError("Spot API endpoint not permitted")
        values = dict(params or {})
        headers = {}
        if signed:
            values.update(recvWindow=5000, timestamp=self.clock_ms())
            headers["X-MBX-APIKEY"] = self.credentials.api_key
            payload = urlencode(values)
            values["signature"] = hmac.new(
                self.credentials.api_secret.encode("utf-8"),
                payload.encode("utf-8"), hashlib.sha256).hexdigest()
        try:
            response = self.session.request(method, self.base_url + path,
                params=values if method == "GET" else None,
                data=values if method == "POST" else None,
                headers=headers, timeout=self.timeout_seconds)
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as exc:
            # Avoid leaking an exception message that could include a signed URL.
            raise SpotApiError("Binance Spot request failed; order status may be unknown") from None
        if not isinstance(result, (dict, list)) or (
                isinstance(result, dict) and isinstance(result.get("code"), int)
                and result["code"] < 0):
            raise SpotApiError("Binance Spot returned an error; order status may be unknown")
        return result

    @staticmethod
    def _symbol(symbol):
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9]{1,32}", symbol):
            raise ValueError("Invalid Spot symbol")
        return symbol

    def server_time(self):
        return self._request("GET", "/api/v3/time")

    def exchange_info(self, symbol):
        return self._request("GET", "/api/v3/exchangeInfo",
                             {"symbol": self._symbol(symbol)})

    def book_ticker(self, symbol):
        return self._request("GET", "/api/v3/ticker/bookTicker",
                             {"symbol": self._symbol(symbol)})

    def account(self):
        return self._request("GET", "/api/v3/account", signed=True)

    def open_orders(self, symbol):
        return self._request("GET", "/api/v3/openOrders",
                             {"symbol": self._symbol(symbol)}, signed=True)

    def open_orders_all(self):
        return self._request("GET", "/api/v3/openOrders", signed=True)

    def my_trades(self, symbol, *, from_id=None, limit=1000):
        params = {"symbol": self._symbol(symbol), "limit": limit}
        if from_id is not None:
            params["fromId"] = from_id
        return self._request("GET", "/api/v3/myTrades", params, signed=True)

    def all_orders(self, symbol, *, order_id=None, limit=1000):
        params = {"symbol": self._symbol(symbol), "limit": limit}
        if order_id is not None:
            params["orderId"] = order_id
        return self._request("GET", "/api/v3/allOrders", params, signed=True)

    def commission(self, symbol):
        return self._request("GET", "/api/v3/account/commission",
                             {"symbol": self._symbol(symbol)}, signed=True)

    def get_order(self, symbol, client_order_id):
        if not isinstance(client_order_id, str) or not re.fullmatch(
                r"bstock-[0-9a-f]{28}", client_order_id):
            raise ValueError("Invalid client order ID")
        return self._request("GET", "/api/v3/order", {"symbol": self._symbol(symbol),
            "origClientOrderId": client_order_id}, signed=True)

    def market_order(self, arguments):
        if not isinstance(arguments, dict) or not {
                "symbol", "side", "type", "newClientOrderId", "newOrderRespType"
                } <= arguments.keys():
            raise ValueError("Invalid market order")
        side = arguments["side"]
        amount_key = "quoteOrderQty" if side == "BUY" else "quantity" if side == "SELL" else None
        if (amount_key is None or set(arguments) != {
                "symbol", "side", "type", "newClientOrderId", "newOrderRespType", amount_key}
                or arguments["type"] != "MARKET"
                or arguments["newOrderRespType"] != "FULL"):
            raise ValueError("Only bounded Spot market orders are permitted")
        self._symbol(arguments["symbol"])
        if not re.fullmatch(r"bstock-[0-9a-f]{28}", arguments["newClientOrderId"]):
            raise ValueError("Invalid client order ID")
        from decimal import Decimal, InvalidOperation
        if not isinstance(arguments[amount_key], str):
            raise ValueError("Order amount must be an exact decimal string")
        try:
            amount = Decimal(arguments[amount_key])
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("Invalid order amount") from None
        if not amount.is_finite() or amount <= 0:
            raise ValueError("Invalid order amount")
        return self._request("POST", "/api/v3/order", arguments, signed=True)
