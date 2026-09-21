"""Strict import boundary for sanitized results from the supported Codex host."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
import re
import secrets
from typing import Any

from .mcp_bridge import (MCP_HOST, MCP_SPOT_READ_TOOLS, MCP_TRANSPORT,
    McpAccountBinding, McpSpotReadRequest)
from .mcp_spot_snapshot import (LocalRiskMetrics,
    build_bound_mcp_spot_evidence)


RESULT_OPERATION = "READ_SPOT_SNAPSHOT_RESULT"
FORBIDDEN_KEYS = frozenset({
    "uid", "accesstoken", "refreshtoken", "apikey", "apisecret",
    "authorizationcode", "password", "privatekey", "seedphrase",
})


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"Invalid {label}")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid {label}") from None
    if result.tzinfo is None:
        raise ValueError(f"Invalid {label}")
    return result.astimezone(timezone.utc)


def _assert_sanitized(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Invalid MCP receipt key")
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in FORBIDDEN_KEYS:
                raise ValueError("MCP receipt contains forbidden identity or credential data")
            _assert_sanitized(item)
    elif isinstance(value, list):
        for item in value:
            _assert_sanitized(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Invalid MCP receipt number")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("Invalid MCP receipt value")


def _exchange_assets(payload: Any, symbol: str) -> tuple[str, str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
        raise ValueError("Invalid MCP exchange info result")
    matches = [row for row in payload["symbols"]
               if isinstance(row, dict) and row.get("symbol") == symbol]
    if len(matches) != 1:
        raise ValueError("MCP exchange info symbol mismatch")
    row = matches[0]
    base, quote = row.get("baseAsset"), row.get("quoteAsset")
    if (row.get("status") != "TRADING"
            or row.get("isSpotTradingAllowed") is not True
            or not isinstance(base, str) or not isinstance(quote, str)
            or re.fullmatch(r"[A-Z0-9]{1,32}", base) is None
            or re.fullmatch(r"[A-Z0-9]{1,32}", quote) is None
            or base + quote != symbol):
        raise ValueError("Invalid MCP Spot exchange identity")
    return base, quote


@dataclass(frozen=True)
class VerifiedSpotHostReceipt:
    request_id: str
    symbol: str
    account_ref: str
    account_fingerprint: str
    observed_at: str
    base_asset: str
    quote_asset: str
    tool_results: dict[str, Any]
    binding: McpAccountBinding
    enrolled_now: bool

    @property
    def observed_at_ms(self) -> int:
        return int(_timestamp(self.observed_at, "receipt observation time").timestamp()
                   * 1000)

    def to_evidence(self, *, risk_day: str,
                    risk: LocalRiskMetrics):
        return build_bound_mcp_spot_evidence(
            account=self.tool_results["spot.getAccount"],
            open_orders=self.tool_results["spot.getOpenOrders"],
            trades=self.tool_results["spot.myTrades"],
            all_orders=self.tool_results["spot.allOrders"],
            book=self.tool_results["spot.tickerBookTicker"],
            account_ref=self.account_ref, account_binding_verified=True,
            symbol=self.symbol, base_asset=self.base_asset,
            quote_asset=self.quote_asset, risk_day=risk_day,
            observed_at_ms=self.observed_at_ms,
            evidence_id=f"host-{self.request_id}", risk=risk,
            trade_history_complete=True)

    def summary(self) -> dict[str, Any]:
        evidence = self.to_evidence(
            risk_day=_timestamp(self.observed_at, "receipt observation time")
                .date().isoformat(),
            risk=LocalRiskMetrics(Decimal("0")))
        snapshot = evidence.to_snapshot()
        return {
            "requestId": self.request_id,
            "symbol": self.symbol,
            "accountRef": self.account_ref,
            "accountFingerprint": self.account_fingerprint,
            "enrolledNow": self.enrolled_now,
            "canTrade": snapshot.can_trade,
            "availableQuote": format(snapshot.available_quote, "f"),
            "positionQuantity": format(snapshot.position_quantity, "f"),
            "positionCost": format(snapshot.position_cost, "f"),
            "pendingOrderId": snapshot.pending_order_id,
            "observedAt": self.observed_at,
        }

    def to_persisted_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "status": "VERIFIED",
            "request_id": self.request_id,
            "symbol": self.symbol,
            "account_ref": self.account_ref,
            "account_fingerprint": self.account_fingerprint,
            "observed_at": self.observed_at,
            "completed_tools": list(MCP_SPOT_READ_TOOLS),
            "tool_results": self.tool_results,
        }


def verify_spot_host_receipt(
    request: McpSpotReadRequest, binding: McpAccountBinding,
    payload: dict[str, Any], *, allow_enroll: bool = False,
    now: datetime | None = None,
) -> VerifiedSpotHostReceipt:
    if not isinstance(request, McpSpotReadRequest) \
            or not isinstance(binding, McpAccountBinding):
        raise ValueError("Verified request and account binding required")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    request.require_current(now=current)
    if binding.to_dict() != request.account_binding:
        raise ValueError("MCP request account binding changed")
    expected = {"schema_version", "request_id", "operation", "host",
        "transport", "symbol", "account_ref", "account_fingerprint",
        "observed_at", "completed_tools", "pagination", "tool_results"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("Invalid MCP host receipt document")
    _assert_sanitized(payload)
    if (payload["schema_version"] != "1.0"
            or payload["request_id"] != request.request_id
            or payload["operation"] != RESULT_OPERATION
            or payload["host"] != MCP_HOST
            or payload["transport"] != MCP_TRANSPORT
            or payload["symbol"] != request.symbol
            or payload["account_ref"] != binding.account_ref
            or payload["account_ref"] != request.account_binding["account_ref"]
            or payload["completed_tools"] != list(MCP_SPOT_READ_TOOLS)
            or payload["pagination"] != {
                "trades_complete": True, "orders_complete": True}
            or not isinstance(payload["tool_results"], dict)
            or set(payload["tool_results"]) != set(MCP_SPOT_READ_TOOLS)):
        raise ValueError("MCP host receipt does not match the request")
    fingerprint = payload["account_fingerprint"]
    if not isinstance(fingerprint, str) or re.fullmatch(
            r"[0-9a-f]{64}", fingerprint) is None:
        raise ValueError("Invalid MCP host account fingerprint")
    enrolled_now = False
    if binding.fingerprint is None:
        if allow_enroll is not True:
            raise RuntimeError("First Agentic account receipt requires explicit enrollment")
        binding = binding.enrolled(fingerprint)
        enrolled_now = True
    elif not secrets.compare_digest(binding.fingerprint, fingerprint):
        raise ValueError("Agentic account fingerprint mismatch")
    observed = _timestamp(payload["observed_at"], "receipt observation time")
    created = _timestamp(request.created_at, "request creation time")
    expires = _timestamp(request.expires_at, "request expiry time")
    if observed < created or observed > expires or observed > current:
        raise ValueError("MCP host receipt observation is outside request lifetime")
    results = payload["tool_results"]
    base, quote = _exchange_assets(results["spot.exchangeInfo"], request.symbol)
    if not isinstance(results["spot.accountCommission"], dict):
        raise ValueError("Invalid MCP commission result")
    receipt = VerifiedSpotHostReceipt(
        request.request_id, request.symbol, binding.account_ref, fingerprint,
        payload["observed_at"], base, quote, results, binding, enrolled_now)
    receipt.summary()  # strict balance/fill/order/book reconciliation
    return receipt


def load_json_document(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError(f"Invalid {label} file") from None
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid {label} document")
    return payload


def write_verified_receipt(receipt: VerifiedSpotHostReceipt,
                           path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt.to_persisted_dict(),
                                    ensure_ascii=False, indent=2),
                         encoding="utf-8")
    temporary.replace(path)
