"""One-shot standalone OAuth login and read-only Agent OS Spot snapshot."""
from __future__ import annotations

from dataclasses import dataclass
import json
import time
from urllib.parse import urlsplit
import webbrowser

import requests

from .mcp_readonly import ReadOnlyHTTP, ReadOnlyMcpClient, SpotReadBundle, collect_spot_reads
from .oauth_callback import CallbackListener
from .oauth_token import SessionTokenExchange


PROJECT_CLIENT_ID = (
    "https://cdn.jsdelivr.net/gh/Wq5881898/bstock-web3-trading-agent@main/"
    "site/oauth/bstock-web3-agent.json"
)
CALLBACK_PATH = "/callback/bstock-web3-trading-agent"


def _json_response(response, *, label: str) -> dict:
    if response.status_code != 200:
        raise ValueError(f"{label} unavailable")
    kind = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    body = response.content
    if kind != "application/json" or len(body) > 64_000:
        raise ValueError(f"Invalid {label}")
    try:
        payload = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError(f"Invalid {label}") from None
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid {label}")
    return payload


def validate_client_metadata(client_id: str, *, session=None) -> dict:
    """Fetch and validate the public native-client document before login."""
    parsed = urlsplit(client_id)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path in ("", "/")):
        raise ValueError("Invalid OAuth client metadata URL")
    owned = session is None
    client = session or requests.Session()
    client.trust_env = False
    try:
        try:
            response = client.get(client_id, headers={"Accept":"application/json"},
                                  timeout=(5, 10), allow_redirects=False)
        except requests.RequestException:
            raise ValueError("OAuth client metadata unavailable") from None
        payload = _json_response(response, label="OAuth client metadata")
    finally:
        if owned:
            client.close()
    redirect = "http://127.0.0.1" + CALLBACK_PATH
    redirects = payload.get("redirect_uris")
    grants = payload.get("grant_types")
    responses = payload.get("response_types")
    if (payload.get("client_id") != client_id
            or payload.get("application_type") != "native"
            or not isinstance(grants, list)
            or "authorization_code" not in grants
            or not isinstance(responses, list)
            or "code" not in responses
            or payload.get("token_endpoint_auth_method") != "none"
            or not isinstance(redirects, list)
            or redirect not in redirects):
        raise ValueError("Invalid OAuth client metadata")
    return payload


@dataclass(frozen=True)
class SpotAccountSummary:
    uid: int
    account_type: str
    can_trade: bool
    balances: tuple[dict, ...]
    open_order_count: int
    trade_count: int
    order_count: int
    symbol: str
    bid_price: str
    ask_price: str

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "accountType": self.account_type,
            "canTrade": self.can_trade,
            "balances": list(self.balances),
            "openOrderCount": self.open_order_count,
            "tradeCount": self.trade_count,
            "orderCount": self.order_count,
            "symbol": self.symbol,
            "bidPrice": self.bid_price,
            "askPrice": self.ask_price,
        }


def summarize_spot_bundle(bundle: SpotReadBundle, symbol: str) -> SpotAccountSummary:
    account = bundle.account
    if (type(account.get("uid")) is not int
            or account.get("accountType") != "SPOT"
            or type(account.get("canTrade")) is not bool
            or not isinstance(account.get("balances"), list)
            or bundle.book.get("symbol") != symbol):
        raise ValueError("Invalid MCP Spot account snapshot")
    balances = []
    if len(account["balances"]) > 200:
        raise ValueError("Excessive MCP Spot balances")
    for row in account["balances"]:
        if (not isinstance(row, dict) or not isinstance(row.get("asset"), str)
                or not isinstance(row.get("free"), str)
                or not isinstance(row.get("locked"), str)):
            raise ValueError("Invalid MCP Spot balance")
        if (len(row["asset"]) > 32 or len(row["free"]) > 128
                or len(row["locked"]) > 128):
            raise ValueError("Invalid MCP Spot balance")
        balances.append({"asset":row["asset"], "free":row["free"],
                         "locked":row["locked"]})
    for rows in (bundle.open_orders, bundle.trades, bundle.all_orders):
        if not isinstance(rows, list):
            raise ValueError("Invalid MCP Spot account collection")
    bid, ask = bundle.book.get("bidPrice"), bundle.book.get("askPrice")
    if (not isinstance(bid, str) or not isinstance(ask, str)
            or len(bid) > 128 or len(ask) > 128):
        raise ValueError("Invalid MCP Spot book")
    return SpotAccountSummary(account["uid"], "SPOT", account["canTrade"],
        tuple(balances), len(bundle.open_orders), len(bundle.trades),
        len(bundle.all_orders), symbol, bid, ask)


def read_spot_account_once(
    symbol: str,
    *,
    client_id: str = PROJECT_CLIENT_ID,
    announce_url=print,
    browser_open=webbrowser.open,
    timeout_seconds: int = 300,
    metadata_session=None,
    listener_factory=CallbackListener,
    token_exchange_factory=SessionTokenExchange,
    transport_factory=ReadOnlyHTTP,
    cancelled=lambda: False,
) -> SpotAccountSummary:
    """Authorize once, collect an allowlisted snapshot, then erase the session."""
    if (not isinstance(symbol, str) or not symbol.isalnum()
            or symbol != symbol.upper() or len(symbol) > 32):
        raise ValueError("Invalid MCP Spot symbol")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 300:
        raise ValueError("Invalid OAuth timeout")
    if not callable(cancelled):
        raise ValueError("Invalid cancellation callback")
    if cancelled():
        raise ValueError("MCP account read cancelled")
    validate_client_metadata(client_id, session=metadata_session)
    if cancelled():
        raise ValueError("MCP account read cancelled")
    deadline = time.monotonic() + timeout_seconds
    with listener_factory(client_id, CALLBACK_PATH) as listener:
        url = listener.attempt.authorization_url()
        announce_url(url)
        try:
            browser_open(url)
        except Exception:
            pass  # the announced URL remains available for manual opening
        form = None
        while form is None:
            if cancelled():
                raise ValueError("MCP account read cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("OAuth authorization timed out")
            form = listener.receive(min(.25, remaining))
    if cancelled():
        raise ValueError("MCP account read cancelled")
    with token_exchange_factory() as exchange:
        grant = exchange.exchange(form)
    if not grant.usable():
        raise ValueError("OAuth access token expired")
    if cancelled():
        raise ValueError("MCP account read cancelled")
    with transport_factory(grant.access_token) as transport:
        client = ReadOnlyMcpClient(transport)
        client.initialize()
        bundle = collect_spot_reads(client, symbol, cancelled=cancelled)
    return summarize_spot_bundle(bundle, symbol)
