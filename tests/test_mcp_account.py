import json

import pytest

from bstock_web3.mcp_account import (CALLBACK_PATH, SpotAccountSummary,
    read_spot_account_once, summarize_spot_bundle, validate_client_metadata)
from bstock_web3.mcp_readonly import SpotReadBundle
from bstock_web3.oauth_token import AccessGrant


CLIENT = "https://example.com/oauth/client.json"


class Response:
    status_code = 200
    headers = {"Content-Type":"application/json"}
    content = json.dumps({
        "client_id":CLIENT, "application_type":"native",
        "redirect_uris":["http://127.0.0.1" + CALLBACK_PATH],
        "token_endpoint_auth_method":"none",
        "grant_types":["authorization_code"], "response_types":["code"],
    }).encode()


class MetadataSession:
    def __init__(self): self.calls=[]; self.trust_env=True
    def get(self, url, **kwargs): self.calls.append((url, kwargs)); return Response()


def bundle():
    return SpotReadBundle(
        account={"uid":123, "accountType":"SPOT", "canTrade":True,
                 "balances":[{"asset":"USDT", "free":"100", "locked":"0"}]},
        open_orders=[], trades=[{"id":1}], all_orders=[{"orderId":2}],
        commission={}, exchange_info={},
        book={"symbol":"BTCUSDT", "bidPrice":"100", "askPrice":"101"})


def test_metadata_is_exact_self_identifying_native_document():
    session = MetadataSession()
    payload = validate_client_metadata(CLIENT, session=session)
    assert payload["client_id"] == CLIENT
    assert session.trust_env is False
    assert session.calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("change", [
    {"client_id":"https://evil.example/client.json"},
    {"application_type":"web"}, {"redirect_uris":[]},
    {"token_endpoint_auth_method":"client_secret_basic"},
    {"grant_types":1}, {"response_types":None}, {"redirect_uris":{}},
])
def test_bad_metadata_is_rejected(change):
    class Bad(MetadataSession):
        def get(self, *args, **kwargs):
            response=Response(); payload=json.loads(response.content); payload.update(change)
            response.content=json.dumps(payload).encode(); return response
    with pytest.raises(ValueError, match="metadata"):
        validate_client_metadata(CLIENT, session=Bad())


def test_summary_exposes_only_bounded_account_fields():
    result = summarize_spot_bundle(bundle(), "BTCUSDT")
    assert result == SpotAccountSummary(123, "SPOT", True,
        ({"asset":"USDT", "free":"100", "locked":"0"},),
        0, 1, 1, "BTCUSDT", "100", "101")
    assert set(result.to_dict()) == {"uid", "accountType", "canTrade", "balances",
        "openOrderCount", "tradeCount", "orderCount", "symbol", "bidPrice", "askPrice"}
    excessive = bundle()
    excessive.account["balances"] *= 201
    with pytest.raises(ValueError, match="Excessive"):
        summarize_spot_bundle(excessive, "BTCUSDT")


def test_one_shot_flow_closes_callback_token_and_mcp(monkeypatch):
    events=[]
    class Attempt:
        def authorization_url(self): return "https://accounts.example/authorize"
    class Listener:
        attempt=Attempt()
        def __init__(self, client_id, path): events.append(("listener",client_id,path))
        def __enter__(self): return self
        def __exit__(self,*args): events.append("listener_closed")
        def receive(self, timeout): return {"form":"secret"}
    class Exchange:
        def __enter__(self): return self
        def __exit__(self,*args): events.append("exchange_closed")
        def exchange(self, form):
            assert form == {"form":"secret"}
            return AccessGrant("x"*32, "Bearer", 10_000_000_000)
    class Transport:
        def __init__(self, token): assert token == "x"*32
        def __enter__(self): return self
        def __exit__(self,*args): events.append("transport_closed")
        def __call__(self, message): raise AssertionError("fake client replaces calls")
    class Client:
        def __init__(self, transport): pass
        def initialize(self): events.append("initialized")
    monkeypatch.setattr("bstock_web3.mcp_account.ReadOnlyMcpClient", Client)
    monkeypatch.setattr("bstock_web3.mcp_account.collect_spot_reads",
                        lambda client, symbol, **kwargs: bundle())
    summary = read_spot_account_once("BTCUSDT", client_id=CLIENT,
        announce_url=lambda url: events.append(("url",url)),
        browser_open=lambda url: events.append(("browser",url)),
        metadata_session=MetadataSession(), listener_factory=Listener,
        token_exchange_factory=Exchange, transport_factory=Transport)
    assert summary.uid == 123
    assert events == [
        ("listener", CLIENT, CALLBACK_PATH),
        ("url", "https://accounts.example/authorize"),
        ("browser", "https://accounts.example/authorize"),
        "listener_closed", "exchange_closed", "initialized", "transport_closed",
    ]


def test_invalid_symbol_fails_before_metadata_network():
    session=MetadataSession()
    with pytest.raises(ValueError, match="symbol"):
        read_spot_account_once("btc/usdt", client_id=CLIENT,
                               metadata_session=session)
    assert session.calls == []


def test_pre_cancelled_read_fails_before_metadata_or_browser():
    session=MetadataSession(); browser=[]
    with pytest.raises(ValueError, match="cancelled"):
        read_spot_account_once("BTCUSDT", client_id=CLIENT,
            metadata_session=session, cancelled=lambda:True,
            browser_open=browser.append)
    assert session.calls == [] and browser == []
