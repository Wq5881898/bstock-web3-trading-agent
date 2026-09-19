import json

import pytest

from bstock_web3.mcp_account import CALLBACK_PATH
from bstock_web3.mcp_confirmed_host import CONFIRMED_SESSION_TOOLS
from bstock_web3.mcp_schema_acceptance import discover_confirmed_schema_once
from bstock_web3.oauth_token import AccessGrant


CLIENT = "https://example.com/oauth/client.json"


class MetadataResponse:
    status_code = 200
    headers = {"Content-Type":"application/json"}
    content = json.dumps({"client_id":CLIENT, "application_type":"native",
        "redirect_uris":["http://127.0.0.1" + CALLBACK_PATH],
        "token_endpoint_auth_method":"none",
        "grant_types":["authorization_code"], "response_types":["code"]}).encode()


class MetadataSession:
    def __init__(self): self.trust_env=True; self.calls=[]
    def get(self, url, **kwargs): self.calls.append(url); return MetadataResponse()


def test_schema_discovery_closes_everything_and_never_calls_tool():
    events=[]
    class Attempt:
        def authorization_url(self): return "https://accounts.example/authorize"
    class Listener:
        attempt=Attempt()
        def __init__(self, client_id, path): events.append(("listener", client_id, path))
        def __enter__(self): return self
        def __exit__(self,*args): events.append("listener_closed")
        def receive(self, timeout): return {"secret":"form"}
    class Exchange:
        def __enter__(self): return self
        def __exit__(self,*args): events.append("exchange_closed")
        def exchange(self, form):
            assert form == {"secret":"form"}
            return AccessGrant("x"*32, "Bearer", 10_000_000_000)
    class Transport:
        def __init__(self, token): assert token == "x"*32
        def __enter__(self): return self
        def __exit__(self,*args): events.append("transport_closed")
    class Client:
        def __init__(self, transport): pass
        def initialize(self): events.append("initialize_and_tools_list_only")
        def schema_report(self): return {"writeTools":["spot.getOrder", "spot.newOrder"]}
    result = discover_confirmed_schema_once(client_id=CLIENT,
        announce_url=lambda url:events.append(("url",url)),
        browser_open=lambda url:events.append(("browser",url)),
        metadata_session=MetadataSession(), listener_factory=Listener,
        token_exchange_factory=Exchange, transport_factory=Transport,
        client_factory=Client)
    assert result == {"writeTools":["spot.getOrder", "spot.newOrder"]}
    assert events == [("listener",CLIENT,CALLBACK_PATH),
        ("url","https://accounts.example/authorize"),
        ("browser","https://accounts.example/authorize"),
        "listener_closed", "exchange_closed", "initialize_and_tools_list_only",
        "transport_closed"]


def test_cancelled_fails_before_metadata_network():
    session=MetadataSession()
    with pytest.raises(ValueError, match="cancelled"):
        discover_confirmed_schema_once(client_id=CLIENT,
            metadata_session=session, cancelled=lambda:True)
    assert session.calls == []


@pytest.mark.parametrize("timeout", [True, 0, 301, 1.5])
def test_invalid_timeout_rejected(timeout):
    with pytest.raises(ValueError, match="timeout"):
        discover_confirmed_schema_once(timeout_seconds=timeout)


def test_browser_failure_keeps_manual_url_flow():
    events=[]
    class Attempt:
        def authorization_url(self): return "https://accounts.example/authorize"
    class Listener:
        attempt=Attempt()
        def __init__(self,*args): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def receive(self, timeout): raise ValueError("fixture stop after browser")
    def browser(_url): raise OSError("no browser")
    with pytest.raises(ValueError, match="fixture stop"):
        discover_confirmed_schema_once(client_id=CLIENT,
            metadata_session=MetadataSession(), listener_factory=Listener,
            announce_url=events.append, browser_open=browser)
    assert events == ["https://accounts.example/authorize"]


def test_schema_report_is_stable_and_contains_no_schema_body():
    from bstock_web3.mcp_confirmed_host import ConfirmedMcpClient
    client = ConfirmedMcpClient(lambda message:None)
    client.ready = True
    client._schemas = {name:{} for name in CONFIRMED_SESSION_TOOLS}
    first = client.schema_report(); second = client.schema_report()
    assert first == second
    assert first["readToolCount"] == 7
    assert first["writeTools"] == ["spot.getOrder", "spot.newOrder"]
    assert len(first["writeSchemaSha256"]) == 64
    assert "schemas" not in first
