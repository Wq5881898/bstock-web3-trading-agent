import base64
import hashlib
from urllib.parse import parse_qs, urlsplit, urlencode

import pytest

from bstock_web3.oauth_flow import AuthorizationAttempt, RESOURCE


def attempt(**kwargs):
    return AuthorizationAttempt("https://example.com/oauth/client.json", "http://127.0.0.1:12345/callback/test", **kwargs)


def callback(flow, **changes):
    state = parse_qs(urlsplit(flow.authorization_url()).query)["state"][0]
    return flow.redirect_uri + "?" + urlencode({"state": state, "code": "test-code", **changes})


def test_pkce_resource_binding_and_one_shot():
    flow = attempt()
    query = parse_qs(urlsplit(flow.authorization_url()).query)
    form = flow.consume_callback(callback(flow))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [challenge]
    assert form["resource"] == RESOURCE
    assert form["code_verifier"] not in repr(flow)
    with pytest.raises(ValueError, match="consumed"):
        flow.consume_callback(flow.redirect_uri)


def test_wrong_state_target_denial_and_expiry():
    flow = attempt()
    with pytest.raises(ValueError, match="state"):
        flow.consume_callback(callback(flow, state="wrong"))
    with pytest.raises(ValueError, match="target"):
        flow.consume_callback(callback(flow).replace("12345", "12346"))
    with pytest.raises(ValueError, match="denied"):
        flow.consume_callback(callback(flow, error="access_denied"))
    now = [0]
    flow = attempt(clock=lambda: now[0])
    url = callback(flow)
    now[0] = 300
    with pytest.raises(ValueError, match="expired"):
        flow.consume_callback(url)


def test_duplicate_code_and_state_rejected():
    flow = attempt()
    with pytest.raises(ValueError, match="state"):
        flow.consume_callback(callback(flow) + "&state=other")
    with pytest.raises(ValueError, match="duplicate"):
        flow.consume_callback(callback(flow) + "&code=other")


@pytest.mark.parametrize("client,redirect", [
    ("http://example.com/client.json", "http://127.0.0.1:12345/callback/test"),
    ("https://example.com/client.json", "http://0.0.0.0:12345/callback/test"),
    ("https://example.com/client.json", "http://127.0.0.1/callback/test"),
])
def test_unsafe_urls_rejected(client, redirect):
    with pytest.raises(ValueError):
        AuthorizationAttempt(client, redirect)
