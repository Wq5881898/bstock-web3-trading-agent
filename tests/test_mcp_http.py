import json
import pytest
from bstock_web3.mcp_http import DiscoveryHTTP
from bstock_web3.mcp_readonly import ReadOnlyHTTP
from bstock_web3.mcp_discovery import DiscoveryClient


class Response:
    def __init__(self, payload, kind="application/json", status=200):
        self.status_code = status
        self.headers = {"Content-Type": kind, "MCP-Session-Id": "fixture-session"}
        self.body = json.dumps(payload).encode()
        if kind == "text/event-stream":
            self.body = b": comment\r\n\r\ndata: " + self.body + b"\r\n\r\n"
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, **kwargs):
        for n in range(0, len(self.body), 11):
            yield self.body[n:n+11]


class Session:
    def __init__(self, kind): self.calls, self.kind = [], kind
    def close(self): pass
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        message = kwargs["json"]
        if message["method"] == "notifications/initialized": return Response({}, status=202)
        result = {"protocolVersion": DiscoveryClient.VERSION, "capabilities": {"tools": {}}, "serverInfo": {}} if message["method"] == "initialize" else {"tools": []}
        return Response({"jsonrpc": "2.0", "id": message["id"], "result": result}, self.kind)


@pytest.mark.parametrize("kind", ["application/json", "text/event-stream"])
def test_discovery_over_fake_http(kind):
    session = Session(kind)
    with DiscoveryHTTP("test-token", session=session) as transport:
        client = DiscoveryClient(transport)
        client.initialize()
        assert client.list_tools() == []
        assert session.calls[1][1]["headers"]["MCP-Session-Id"] == "fixture-session"
        assert session.calls[2][1]["headers"]["MCP-Protocol-Version"] == DiscoveryClient.VERSION
        assert all(not args["allow_redirects"] for _, args in session.calls)
        with pytest.raises(ValueError, match="prohibited"):
            transport({"method": "tools/call"})
        assert len(session.calls) == 3
        assert "test-token" not in repr(transport)
    assert not transport._token


@pytest.mark.parametrize("status", [302, 401, 403, 404, 429, 500])
def test_http_errors_never_retry_or_follow_redirect(status):
    session = Session("application/json")
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs)
        return Response({"error": "private-message"}, status=status)
    session.post = post
    with DiscoveryHTTP("test-token", session=session) as transport:
        with pytest.raises(ValueError) as caught:
            DiscoveryClient(transport).initialize()
        assert "private-message" not in str(caught.value)
    assert len(calls) == 1
    assert calls[0]["allow_redirects"] is False


@pytest.mark.parametrize("bad_id", [999, True, None, "1"])
def test_invalid_envelope_does_not_accept_session(bad_id):
    session = Session("application/json")
    session.post = lambda *a, **k: Response({"jsonrpc": "2.0", "id": bad_id,
        "result": {"protocolVersion": DiscoveryClient.VERSION}})
    with DiscoveryHTTP("test-token", session=session) as transport:
        with pytest.raises(ValueError, match="envelope"):
            DiscoveryClient(transport).initialize()
        assert not transport._initialized
        assert transport._session_id is None


def test_readonly_http_allows_tools_call_but_discovery_transport_does_not():
    session = Session("application/json")
    transport = ReadOnlyHTTP("test-token", session=session)
    transport._initialized = True
    reply = transport({"jsonrpc":"2.0", "id":7, "method":"tools/call",
                       "params":{"name":"spot.getAccount", "arguments":{}}})
    assert reply["result"] == {"tools":[]}
    calls = len(session.calls)
    with pytest.raises(ValueError, match="allowlist"):
        transport({"jsonrpc":"2.0", "id":8, "method":"tools/call",
                   "params":{"name":"spot.newOrder", "arguments":{}}})
    assert len(session.calls) == calls
    with DiscoveryHTTP("test-token", session=Session("application/json")) as discovery:
        with pytest.raises(ValueError, match="prohibited"):
            discovery({"method":"tools/call"})
