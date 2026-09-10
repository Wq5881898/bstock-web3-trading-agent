"""Offline OAuth request/callback validation. No network, token storage or orders."""
import base64
import hashlib
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

RESOURCE = "https://agent.binance.com/mcp/agentic"
ISSUER = "https://agent.binance.com"
AUTHORIZE = "https://accounts.binance.com/agentic-oauth/authorize"
TOKEN = "https://accounts.binance.com/oauth-agentic/token"


def validate_metadata(resource, authorization):
    """Pinned Binance trust boundary; never follow arbitrary metadata endpoints."""
    if resource.get("resource") != RESOURCE or ISSUER not in resource.get("authorization_servers", []):
        raise ValueError("Unexpected protected resource")
    expected = {"issuer": ISSUER, "authorization_endpoint": AUTHORIZE, "token_endpoint": TOKEN,
                "client_id_metadata_document_supported": True}
    if any(authorization.get(k) != v for k, v in expected.items()):
        raise ValueError("Unexpected authorization metadata")
    for key, required in (("code_challenge_methods_supported", "S256"),
                          ("grant_types_supported", "authorization_code"),
                          ("token_endpoint_auth_methods_supported", "none")):
        if required not in authorization.get(key, []):
            raise ValueError("Required OAuth capability not advertised")


class AuthorizationAttempt:
    """One-shot PKCE attempt; caller must bind loopback before opening browser.

    The returned token form contains secrets: never log or persist it. A future
    transport must POST only to TOKEN, with redirects disabled. No such transport
    is implemented here, and this class does not establish client admission.
    """

    def __init__(self, client_id, redirect_uri, *, clock=time.monotonic):
        client = urlsplit(client_id)
        callback = urlsplit(redirect_uri)
        if client.scheme != "https" or not client.hostname or client.username or client.password or client.query or client.fragment or client.path in ("", "/"):
            raise ValueError("A project-owned HTTPS metadata document URL is required")
        if callback.scheme != "http" or callback.hostname != "127.0.0.1" or not callback.port or callback.username or callback.password or callback.query or callback.fragment or not callback.path.startswith("/callback/"):
            raise ValueError("An explicit loopback callback port and path are required")
        self.client_id, self.redirect_uri = client_id, redirect_uri
        self._clock = clock
        self._expires = clock() + 300
        self._used = False
        self._state = secrets.token_urlsafe(32)
        self._verifier = secrets.token_urlsafe(64)

    def __repr__(self):
        return "AuthorizationAttempt(<redacted>)"

    def authorization_url(self):
        if self._used or self._clock() >= self._expires:
            raise ValueError("Authorization attempt expired or consumed")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self._verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        return AUTHORIZE + "?" + urlencode(dict(response_type="code", client_id=self.client_id,
            redirect_uri=self.redirect_uri, resource=RESOURCE, state=self._state,
            code_challenge=challenge, code_challenge_method="S256"))

    def consume_callback(self, callback_url):
        if self._used or self._clock() >= self._expires:
            raise ValueError("Authorization attempt expired or consumed")
        actual, expected = urlsplit(callback_url), urlsplit(self.redirect_uri)
        if (actual.scheme, actual.netloc, actual.path) != (expected.scheme, expected.netloc, expected.path) or actual.fragment:
            raise ValueError("Callback target mismatch")
        query = parse_qs(actual.query, keep_blank_values=True, max_num_fields=16)
        states = query.get("state", [])
        if len(states) != 1 or not secrets.compare_digest(states[0].encode("utf-8"), self._state.encode("ascii")):
            raise ValueError("Callback state mismatch")
        self._used = True
        verifier, self._verifier = self._verifier, ""
        if "error" in query:
            raise ValueError("Authorization denied")  # never echo server-controlled details
        codes = query.get("code", [])
        if len(codes) != 1 or not codes[0]:
            raise ValueError("Missing or duplicate authorization code")
        return dict(grant_type="authorization_code", code=codes[0], client_id=self.client_id,
                    redirect_uri=self.redirect_uri, resource=RESOURCE, code_verifier=verifier)
