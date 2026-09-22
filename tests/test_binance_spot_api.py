import hashlib
import hmac
from urllib.parse import urlencode

import pytest

from bstock_web3.binance_spot_api import (BinanceSpotApi,
    PRODUCTION_URL, SpotApiCredentials, SpotApiError)


class FakeResponse:
    def __init__(self, payload, error=None):
        self.payload, self.error = payload, error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []
        self.response = FakeResponse({"ok": True})

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


def api():
    session = FakeSession()
    client = BinanceSpotApi(SpotApiCredentials("test-key", "test-secret"),
        session=session, clock_ms=lambda: 123456, timeout_seconds=3)
    return client, session


def test_private_get_uses_signed_query_and_no_body():
    client, session = api()
    client.get_order("BTCUSDT", "bstock-" + "a" * 28)
    method, url, kwargs = session.calls[0]
    assert method == "GET" and url == PRODUCTION_URL + "/api/v3/order"
    assert kwargs["data"] is None
    assert kwargs["headers"] == {"X-MBX-APIKEY": "test-key"}
    params = kwargs["params"]
    signature = params.pop("signature")
    assert signature == hmac.new(b"test-secret", urlencode(params).encode(),
                                 hashlib.sha256).hexdigest()
    assert params["timestamp"] == 123456 and params["recvWindow"] == 5000


def test_market_order_posts_once_with_bounded_shape():
    client, session = api()
    args = dict(symbol="BTCUSDT", side="BUY", type="MARKET",
        newClientOrderId="bstock-" + "a" * 28,
        newOrderRespType="FULL", quoteOrderQty="100")
    client.market_order(args)
    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == "POST" and url.endswith("/api/v3/order")
    assert kwargs["params"] is None
    assert kwargs["data"]["quoteOrderQty"] == "100"
    with pytest.raises(ValueError, match="Only bounded"):
        client.market_order({**args, "withdraw": "1"})
    assert len(session.calls) == 1


def test_invalid_base_url_and_amount_are_rejected():
    with pytest.raises(ValueError, match="allowlisted"):
        BinanceSpotApi(SpotApiCredentials("key", "secret"),
                       base_url="https://example.com")
    client, session = api()
    args = dict(symbol="BTCUSDT", side="SELL", type="MARKET",
        newClientOrderId="bstock-" + "b" * 28,
        newOrderRespType="FULL", quantity="NaN")
    with pytest.raises(ValueError, match="amount"):
        client.market_order(args)
    assert session.calls == []


def test_http_error_hides_signed_url_and_does_not_retry():
    import requests
    client, session = api()
    session.response = FakeResponse(None, requests.HTTPError("signed secret URL"))
    with pytest.raises(SpotApiError) as error:
        client.account()
    assert "secret" not in str(error.value)
    assert len(session.calls) == 1
