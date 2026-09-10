from urllib.parse import parse_qs, urlsplit, urlencode
import requests
import pytest

from bstock_web3.oauth_callback import CallbackListener


def test_loopback_roundtrip_no_token_exchange():
    with CallbackListener("https://example.com/client.json") as listener:
        query = parse_qs(urlsplit(listener.attempt.authorization_url()).query)
        url = listener.attempt.redirect_uri + "?" + urlencode({"state": query["state"][0], "code": "test-only"})
        with requests.Session() as client:
            client.trust_env = False
            rejected = client.get(url, headers={"Host": "evil.example"}, timeout=3)
            assert rejected.status_code == 400
            invalid_state = listener.attempt.redirect_uri + "?" + urlencode({"state": "错误状态", "code": "test-only"})
            assert client.get(invalid_state, timeout=3).status_code == 400
            response = client.get(url, timeout=3)
            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "no-store"
            assert "test-only" not in response.text
            assert listener.receive(0)["code"] == "test-only"
            assert client.get(url, timeout=3).status_code == 410
    assert not listener._thread.is_alive()
    with pytest.raises(ValueError, match="closed"):
        listener.receive()


def test_poll_is_bounded_and_empty_listener_closes():
    with CallbackListener("https://example.com/client.json") as listener:
        assert listener.receive(0) is None
        with pytest.raises(ValueError):
            listener.receive(60)
    listener.close()
