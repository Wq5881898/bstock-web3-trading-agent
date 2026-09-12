"""Pinned discovery-only Streamable HTTP adapter. No tools/call or order path."""
import json
import time
import requests

from bstock_web3.oauth_flow import RESOURCE
from bstock_web3.mcp_discovery import DiscoveryClient


class DiscoveryHTTP:
    ALLOWED_METHODS = frozenset(("initialize", "notifications/initialized", "tools/list"))

    def __init__(self, access_token, *, session=None):
        if not isinstance(access_token, str) or not access_token or any(ord(c) < 33 or ord(c) > 126 for c in access_token):
            raise ValueError("Invalid access token")
        self._token = access_token
        self._session = session or requests.Session()
        self._session.trust_env = False  # no implicit netrc credentials/proxy forwarding
        self._session_id = None
        self._initialized = False

    def __repr__(self):
        return "DiscoveryHTTP(<redacted>)"

    def close(self):
        self._token = ""
        self._session_id = None
        self._initialized = False
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __call__(self, message):
        method = message.get("method")
        if method not in self.ALLOWED_METHODS:
            raise ValueError("Discovery-only transport: method prohibited")
        if not self._token:
            raise ValueError("Transport closed")
        if method != "initialize" and not self._initialized:
            raise ValueError("Initialize transport first")
        if method == "initialize" and self._initialized:
            raise ValueError("Use a new transport to reinitialize")
        headers = {"Authorization": "Bearer " + self._token,
                   "Accept": "application/json, text/event-stream"}
        if self._initialized:
            headers["MCP-Protocol-Version"] = DiscoveryClient.VERSION
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id
        try:
            with self._session.post(RESOURCE, json=message, headers=headers, timeout=(5, 10),
                                    allow_redirects=False, stream=True) as response:
                if response.status_code in (401, 403, 404):
                    self._initialized = False
                    self._session_id = None
                    raise ValueError("MCP authorization/session unavailable; reconnect required")
                if method == "notifications/initialized":
                    if response.status_code != 202:
                        raise ValueError("MCP initialization acknowledgement failed")
                    return None
                if response.status_code != 200:
                    raise ValueError("MCP HTTP request failed; no automatic retry")
                content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if content_type not in ("application/json", "text/event-stream"):
                    raise ValueError("Unsupported MCP response type")
                chunks, size, start = [], 0, time.monotonic()
                for chunk in response.iter_content(chunk_size=4096):
                    size += len(chunk)
                    if size > 2_000_000 or time.monotonic() - start > 20:
                        raise ValueError("MCP response bound exceeded")
                    chunks.append(chunk)
                    if content_type == "text/event-stream":
                        # Parse complete SSE records; stop on matching response.
                        raw = b"".join(chunks).replace(b"\r\n", b"\n")
                        records = raw.split(b"\n\n")
                        for record in records[:-1]:
                            data = b"\n".join(line[5:].lstrip(b" ") for line in record.split(b"\n") if line.startswith(b"data:"))
                            if data:
                                result = json.loads(data)
                                if isinstance(result, dict) and result.get("id") == message.get("id") and ("result" in result or "error" in result):
                                    return self._accept(method, result, response.headers, message.get("id"))
                        chunks = [records[-1]]
                if content_type != "application/json":
                    raise ValueError("MCP stream ended without matching response")
                return self._accept(method, json.loads(b"".join(chunks)), response.headers, message.get("id"))
        except (requests.RequestException, UnicodeError, json.JSONDecodeError):
            raise ValueError("MCP transport failed; sensitive details suppressed") from None

    def _accept(self, method, result, headers, request_id):
        if (not isinstance(result, dict) or result.get("jsonrpc") != "2.0"
                or type(result.get("id")) is not int or result["id"] != request_id
                or "error" in result or not isinstance(result.get("result"), dict)):
            raise ValueError("Invalid MCP response envelope")
        if method == "initialize":
            if not isinstance(result, dict) or not isinstance(result.get("result"), dict) or result["result"].get("protocolVersion") != DiscoveryClient.VERSION:
                raise ValueError("Unsupported initialization response")
            session_id = headers.get("MCP-Session-Id")
            if session_id is not None and (not session_id or len(session_id) > 4096 or any(not 33 <= ord(c) <= 126 for c in session_id)):
                raise ValueError("Invalid MCP session identifier")
            self._session_id = session_id
            self._initialized = True
        return result
