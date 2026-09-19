"""One-shot OAuth and schema discovery. Never calls an MCP tool."""
from __future__ import annotations

import time
import webbrowser

from .mcp_account import (CALLBACK_PATH, PROJECT_CLIENT_ID,
                          validate_client_metadata)
from .mcp_confirmed_host import ConfirmedHTTP, ConfirmedMcpClient
from .oauth_callback import CallbackListener
from .oauth_token import SessionTokenExchange


def discover_confirmed_schema_once(
    *, client_id=PROJECT_CLIENT_ID, announce_url=print,
    browser_open=webbrowser.open, timeout_seconds=300, metadata_session=None,
    listener_factory=CallbackListener,
    token_exchange_factory=SessionTokenExchange,
    transport_factory=ConfirmedHTTP,
    client_factory=ConfirmedMcpClient,
    cancelled=lambda:False,
):
    """Authorize, validate tools/list only, close everything and return hashes."""
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 300:
        raise ValueError("Invalid OAuth timeout")
    if not callable(cancelled) or not callable(announce_url) \
            or not callable(browser_open):
        raise ValueError("Invalid schema-discovery callback")
    if cancelled():
        raise ValueError("MCP schema discovery cancelled")
    validate_client_metadata(client_id, session=metadata_session)
    if cancelled():
        raise ValueError("MCP schema discovery cancelled")
    deadline = time.monotonic() + timeout_seconds
    with listener_factory(client_id, CALLBACK_PATH) as listener:
        url = listener.attempt.authorization_url()
        announce_url(url)
        try:
            browser_open(url)
        except Exception:
            pass
        form = None
        while form is None:
            if cancelled():
                raise ValueError("MCP schema discovery cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("OAuth authorization timed out")
            form = listener.receive(min(.25, remaining))
    if cancelled():
        raise ValueError("MCP schema discovery cancelled")
    with token_exchange_factory() as exchange:
        grant = exchange.exchange(form)
    if not grant.usable():
        raise ValueError("OAuth access token expired")
    if cancelled():
        raise ValueError("MCP schema discovery cancelled")
    with transport_factory(grant.access_token) as transport:
        client = client_factory(transport)
        client.initialize()  # initialize + tools/list only
        report = client.schema_report()
    if not isinstance(report, dict):
        raise ValueError("Invalid MCP schema report")
    return report
