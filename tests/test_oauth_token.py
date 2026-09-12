import json

import pytest

from bstock_web3.oauth_flow import RESOURCE, TOKEN
from bstock_web3.oauth_token import SessionTokenExchange


def form():
    return {"grant_type":"authorization_code", "code":"code",
        "client_id":"https://example.com/client.json",
        "redirect_uri":"http://127.0.0.1:1234/callback/test",
        "resource":RESOURCE, "code_verifier":"v"*64}


class Response:
    status_code = 200
    headers = {"Content-Type":"application/json; charset=utf-8"}
    content = json.dumps({"access_token":"a"*32, "token_type":"Bearer",
                          "expires_in":3600, "scope":"account"}).encode()


class Session:
    def __init__(self): self.calls=[]
    def close(self): pass
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs)); return Response()


def test_code_exchange_is_pinned_nonredirecting_and_session_only():
    session = Session()
    with SessionTokenExchange(session=session, clock=lambda:1000) as exchange:
        grant = exchange.exchange(form())
    assert grant.usable(now=1000) and not grant.usable(now=4590)
    assert repr(grant) == "AccessGrant(<redacted>)"
    assert session.calls[0][0] == TOKEN
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["data"] == form()


@pytest.mark.parametrize("change", [
    {"resource":"https://evil.example"}, {"grant_type":"refresh_token"},
    {"extra":"x"}, {"code":"bad\nheader"},
])
def test_invalid_token_form_never_reaches_network(change):
    session = Session(); payload=form(); payload.update(change)
    with SessionTokenExchange(session=session) as exchange:
        with pytest.raises(ValueError, match="form"):
            exchange.exchange(payload)
    assert session.calls == []


@pytest.mark.parametrize("payload", [
    {}, {"access_token":"short", "token_type":"Bearer", "expires_in":3600},
    {"access_token":"a"*32, "token_type":"Basic", "expires_in":3600},
    {"access_token":"a"*32, "token_type":"Bearer", "expires_in":1},
])
def test_bad_token_response_is_rejected_without_echo(payload):
    class BadSession(Session):
        def post(self, *args, **kwargs):
            response=Response(); response.content=json.dumps(payload).encode(); return response
    with SessionTokenExchange(session=BadSession()) as exchange:
        with pytest.raises(ValueError) as caught:
            exchange.exchange(form())
    assert "access_token" not in str(caught.value)
