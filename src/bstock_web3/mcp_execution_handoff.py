"""File-safe boundary between local confirmation and Codex-hosted MCP I/O.

This module never calls MCP.  It validates a strategy plan against fresh,
reconciled evidence, delegates risk/idempotency to ``ConfirmedSpotExecutor``
and serializes only the already-confirmed single-submission ticket.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
import re
import secrets
from typing import Any, Literal

from .execution_contract import (ExecutionInstrument, OrderIntent,
    PositionAction, ProductType)
from .execution_safety import (McpReconciliationEvidence, client_order_id)
from .mcp_bridge import (MCP_HOST, MCP_SPOT_ORDER_LOOKUP_TOOL,
    MCP_SPOT_ORDER_TOOL, MCP_TRANSPORT, McpAccountBinding, McpSpotOrderPlan)
from .mcp_confirmed import (ConfirmedSpotExecutor, ConfirmedSubmission,
    SpotMarketRules)
from .mcp_confirmed_host import validate_confirmed_arguments


SUBMISSION_OPERATION = "SUBMIT_CONFIRMED_SPOT_ORDER"
SUBMISSION_REQUIREMENTS = {
    "confirmation_consumed": True,
    "single_submission_only": True,
    "terminal_receipt_required": True,
    "unknown_lookup_only": True,
    "local_oauth_prohibited": True,
    "alternate_api_fallback_prohibited": True,
}
_FORBIDDEN_KEYS = frozenset({
    "uid", "accesstoken", "refreshtoken", "apikey", "apisecret",
    "authorizationcode", "password", "privatekey", "seedphrase",
})


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
                raise ValueError("Invalid MCP submission ticket key")
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in _FORBIDDEN_KEYS:
                raise ValueError("MCP submission ticket contains forbidden data")
            _assert_sanitized(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_sanitized(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Invalid MCP submission ticket value")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("Invalid MCP submission ticket value")


def prepare_plan_preview(
    plan: McpSpotOrderPlan,
    evidence: McpReconciliationEvidence,
    rules: SpotMarketRules,
    executor: ConfirmedSpotExecutor,
    *,
    account_fingerprint: str,
    now_ms: int,
) -> dict[str, Any]:
    """Bind a candidate plan to fresh evidence and create a local preview."""
    if (not isinstance(plan, McpSpotOrderPlan)
            or not isinstance(evidence, McpReconciliationEvidence)
            or not isinstance(rules, SpotMarketRules)
            or not isinstance(executor, ConfirmedSpotExecutor)
            or type(now_ms) is not int or now_ms < 0):
        raise ValueError("Invalid MCP execution preflight")
    if (not isinstance(account_fingerprint, str)
            or re.fullmatch(r"[0-9a-f]{64}", account_fingerprint) is None):
        raise ValueError("Invalid MCP account fingerprint")
    now = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
    plan.require_host_preflightable(now=now)
    binding = McpAccountBinding.from_dict(plan.account_binding)
    if (binding.fingerprint is None
            or not secrets.compare_digest(binding.fingerprint,
                                           account_fingerprint)):
        raise ValueError("MCP order plan account fingerprint mismatch")
    snapshot = evidence.to_snapshot()
    if (snapshot.account_ref != binding.account_ref
            or snapshot.symbol != plan.symbol
            or snapshot.product != ProductType.SPOT
            or rules.symbol != plan.symbol
            or rules.base_asset + rules.quote_asset != plan.symbol):
        raise ValueError("MCP order plan preflight identity mismatch")
    action = (PositionAction.OPEN_LONG if plan.side == "BUY"
              else PositionAction.CLOSE_LONG)
    intent = OrderIntent(
        plan.signal["strategy_id"],
        ExecutionInstrument(plan.symbol, ProductType.SPOT, "BINANCE_SPOT",
                            rules.base_asset, rules.quote_asset),
        action, Decimal(str(plan.signal["price"])), plan.signal["reason"],
        dict(plan.signal["strategy_params"]), plan.side == "SELL")
    expected = rules.arguments(intent, snapshot,
        executor.policy.config.order_budget_quote, "preview")
    expected.pop("newClientOrderId")
    if expected != plan.order_arguments:
        raise ValueError("MCP order plan changed during fresh preflight")
    preview = executor.preview(intent, evidence, rules,
        signal_key="mcp:" + plan.signal_fingerprint, now_ms=now_ms)
    visible = dict(preview["arguments"])
    visible.pop("newClientOrderId")
    if visible != plan.order_arguments:
        executor.cancel_preview()
        raise RuntimeError("Prepared MCP order differs from candidate plan")
    return preview


@dataclass(frozen=True)
class McpSpotSubmissionTicket:
    schema_version: str
    operation: Literal["SUBMIT_CONFIRMED_SPOT_ORDER"]
    host: Literal["codex"]
    transport: str
    plan_id: str
    signal_fingerprint: str
    execution_fingerprint: str
    account_ref: str
    account_fingerprint: str
    symbol: str
    tool: Literal["spot.newOrder"]
    lookup_tool: Literal["spot.getOrder"]
    arguments: dict[str, Any]
    requirements: dict[str, Any]
    status: Literal["READY_FOR_SINGLE_SUBMISSION"]
    created_at: str
    expires_at: str

    def __post_init__(self) -> None:
        if (self.schema_version != "1.0"
                or self.operation != SUBMISSION_OPERATION
                or self.host != MCP_HOST or self.transport != MCP_TRANSPORT
                or re.fullmatch(r"mcp-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}",
                                self.plan_id or "") is None
                or re.fullmatch(r"[0-9a-f]{64}",
                                self.signal_fingerprint or "") is None
                or re.fullmatch(r"[0-9a-f]{64}",
                                self.execution_fingerprint or "") is None
                or not isinstance(self.account_ref, str)
                or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}",
                                self.account_ref) is None
                or re.fullmatch(r"[0-9a-f]{64}",
                                self.account_fingerprint or "") is None
                or re.fullmatch(r"[A-Z0-9]{1,32}", self.symbol or "") is None
                or self.tool != MCP_SPOT_ORDER_TOOL
                or self.lookup_tool != MCP_SPOT_ORDER_LOOKUP_TOOL
                or self.requirements != SUBMISSION_REQUIREMENTS
                or self.status != "READY_FOR_SINGLE_SUBMISSION"):
            raise ValueError("Invalid MCP submission ticket")
        validate_confirmed_arguments(self.tool, self.arguments)
        if (self.arguments["symbol"] != self.symbol
                or self.arguments["newClientOrderId"]
                != client_order_id(self.execution_fingerprint)):
            raise ValueError("MCP submission ticket identity mismatch")
        created = _timestamp(self.created_at, "submission ticket creation time")
        expires = _timestamp(self.expires_at, "submission ticket expiry time")
        if not created < expires or expires - created > timedelta(seconds=15):
            raise ValueError("Invalid MCP submission ticket lifetime")
        _assert_sanitized(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]):
        expected = {field.name for field in cls.__dataclass_fields__.values()}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("Invalid MCP submission ticket document")
        return cls(**payload)

    def require_current(self, *, now: datetime | None = None) -> None:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        created = _timestamp(self.created_at, "submission ticket creation time")
        expires = _timestamp(self.expires_at, "submission ticket expiry time")
        if current < created or current >= expires:
            raise RuntimeError("MCP submission ticket expired or not yet valid")


def build_submission_ticket(
    plan: McpSpotOrderPlan,
    submission: ConfirmedSubmission,
    *,
    account_fingerprint: str,
    now: datetime | None = None,
) -> McpSpotSubmissionTicket:
    if not isinstance(plan, McpSpotOrderPlan) \
            or not isinstance(submission, ConfirmedSubmission):
        raise ValueError("Invalid confirmed MCP submission")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    plan.require_host_preflightable(now=current)
    binding = McpAccountBinding.from_dict(plan.account_binding)
    if (binding.fingerprint is None
            or not isinstance(account_fingerprint, str)
            or not secrets.compare_digest(binding.fingerprint,
                                           account_fingerprint)):
        raise ValueError("MCP submission account fingerprint mismatch")
    if (submission.client_order_id
            != client_order_id(submission.fingerprint)
            or submission.account_ref != binding.account_ref
            or submission.symbol != plan.symbol):
        raise ValueError("Invalid confirmed submission identity")
    current_ms = int(current.timestamp() * 1000)
    if not submission.prepared_at_ms <= current_ms \
            < submission.prepared_at_ms + 15_000:
        raise RuntimeError("Confirmed submission is too old for handoff")
    candidate = dict(submission.arguments)
    candidate.pop("newClientOrderId", None)
    if candidate != plan.order_arguments:
        raise ValueError("Confirmed submission differs from MCP order plan")
    plan_expiry = _timestamp(plan.expires_at, "MCP order plan expiry time")
    expires = min(current + timedelta(seconds=15), plan_expiry)
    if expires <= current:
        raise RuntimeError("MCP order plan expired before ticket creation")
    return McpSpotSubmissionTicket(
        schema_version="1.0", operation=SUBMISSION_OPERATION,
        host=MCP_HOST, transport=MCP_TRANSPORT, plan_id=plan.plan_id,
        signal_fingerprint=plan.signal_fingerprint,
        execution_fingerprint=submission.fingerprint,
        account_ref=binding.account_ref,
        account_fingerprint=account_fingerprint, symbol=plan.symbol,
        tool=MCP_SPOT_ORDER_TOOL, lookup_tool=MCP_SPOT_ORDER_LOOKUP_TOOL,
        arguments=dict(submission.arguments),
        requirements=dict(SUBMISSION_REQUIREMENTS),
        status="READY_FOR_SINGLE_SUBMISSION", created_at=_utc(current),
        expires_at=_utc(expires))


def write_submission_ticket(ticket: McpSpotSubmissionTicket,
                            path: Path) -> None:
    if not isinstance(ticket, McpSpotSubmissionTicket):
        raise ValueError("Invalid MCP submission ticket")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(ticket.to_dict(), ensure_ascii=False,
                                    indent=2), encoding="utf-8")
    temporary.replace(path)


def load_submission_ticket(path: Path) -> McpSpotSubmissionTicket:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("Invalid MCP submission ticket file") from None
    return McpSpotSubmissionTicket.from_dict(payload)
