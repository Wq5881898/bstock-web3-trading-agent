"""Pinned OAuth authorization-code exchange with session-only credentials."""
from __future__ import annotations

from dataclasses import dataclass
import json
import time

import requests

from .oauth_flow import RESOURCE, TOKEN


@dataclass(frozen=True, repr=False)
class AccessGrant:
    access_token: str
    token_type: str
    expires_at: float
    scope: str | None = None

    def __repr__(self):
        return "AccessGrant(<redacted>)"

    def usable(self, *, now=None, skew_seconds=30):
        current = time.time() if now is None else now
        return bool(self.access_token) and current + skew_seconds < self.expires_at


class SessionTokenExchange:
    """Exchange once and retain nothing; the caller keeps the returned grant."""

    REQUIRED_FORM = frozenset({"grant_type", "code", "client_id",
        "redirect_uri", "resource", "code_verifier"})

    def __init__(self, *, session=None, clock=time.time):
        self._session = session or requests.Session()
        self._session.trust_env = False
        self._clock = clock

    def __repr__(self):
        return "SessionTokenExchange(<no credentials>)"

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def exchange(self, form):
        self._validate_form(form)
        try:
            response = self._session.post(TOKEN, data=form,
                headers={"Accept":"application/json",
                         "Content-Type":"application/x-www-form-urlencoded"},
                timeout=(5, 10), allow_redirects=False)
        except requests.RequestException:
            raise ValueError("OAuth token exchange failed") from None
        if response.status_code != 200:
            raise ValueError("OAuth token exchange rejected")
        kind = response.headers.get("Content-Type", "").split(";")[0].lower()
        body = response.content
        if kind != "application/json" or len(body) > 64_000:
            raise ValueError("Invalid OAuth token response")
        try:
            payload = json.loads(body)
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("Invalid OAuth token response") from None
        if not isinstance(payload, dict):
            raise ValueError("Invalid OAuth token response")
        token = payload.get("access_token")
        token_type = payload.get("token_type")
        expires = payload.get("expires_in")
        scope = payload.get("scope")
        if (not isinstance(token, str) or not 16 <= len(token) <= 16_384
                or any(ord(char) < 33 or ord(char) > 126 for char in token)
                or not isinstance(token_type, str)
                or token_type.lower() != "bearer"
                or type(expires) not in (int, float)
                or not 30 <= expires <= 86_400
                or (scope is not None and not isinstance(scope, str))):
            raise ValueError("Invalid OAuth token response")
        return AccessGrant(token, "Bearer", self._clock() + float(expires), scope)

    @classmethod
    def _validate_form(cls, form):
        if not isinstance(form, dict) or set(form) != cls.REQUIRED_FORM:
            raise ValueError("Invalid OAuth token form")
        if form.get("grant_type") != "authorization_code" \
                or form.get("resource") != RESOURCE:
            raise ValueError("Invalid OAuth token form")
        for key in ("code", "client_id", "redirect_uri", "code_verifier"):
            value = form.get(key)
            if (not isinstance(value, str) or not value or len(value) > 4096
                    or "\r" in value or "\n" in value):
                raise ValueError("Invalid OAuth token form")
