import json
import pytest
from bstock_web3.aggregate_provider import AggregateTradeProvider


class Response:
    def __init__(self, rows, status=200, headers=None):
        self.status_code, self.headers = status, headers or {}
        self.body = json.dumps(rows).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, **kwargs): yield self.body


class HTTP:
    def __init__(self, response): self.response, self.calls = response, []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def row(i): return {"a": i, "T": 1000+i, "p": "100", "q": "1"}


def test_pinned_public_get_cursor_without_credentials():
    http = HTTP(Response([row(10), row(11)]))
    client = AggregateTradeProvider(session=http)
    assert len(client.fetch("BTCUSDT", from_id=10, limit=20)) == 2
    url, args = http.calls[0]
    assert url == "https://data-api.binance.vision/api/v3/aggTrades"
    assert args["params"] == {"symbol": "BTCUSDT", "fromId": 10, "limit": 20}
    assert args["allow_redirects"] is False
    assert "headers" not in args and "auth" not in args


@pytest.mark.parametrize("rows,status", [([row(11)], 200), ([row(10),row(12)], 200),
    ({"code": -1}, 200), ([{**row(10), "p": "NaN"}], 200), ([], 302), ([], 500)])
def test_bad_response_rejected(rows, status):
    client = AggregateTradeProvider(session=HTTP(Response(rows, status)))
    with pytest.raises(ValueError): client.fetch("BTCUSDT", from_id=10)


def test_retry_after_prevents_further_requests():
    clock = [100.]
    http = HTTP(Response([], 429, {"Retry-After": "120"}))
    client = AggregateTradeProvider(session=http, clock=lambda: clock[0])
    with pytest.raises(ValueError): client.fetch("BTCUSDT")
    clock[0] = 219
    with pytest.raises(ValueError, match="cooling"): client.fetch("BTCUSDT")
    assert len(http.calls) == 1
    clock[0] = 221
    http.response = Response([])
    assert client.fetch("BTCUSDT") == []


@pytest.mark.parametrize("kwargs", [{"symbol": "../BTC"}, {"symbol": "BTCUSDT", "limit": True},
    {"symbol": "BTCUSDT", "limit": 1001}, {"symbol": "BTCUSDT", "from_id": -1}])
def test_bad_request_never_hits_network(kwargs):
    http = HTTP(Response([]))
    with pytest.raises(ValueError): AggregateTradeProvider(session=http).fetch(**kwargs)
    assert not http.calls
