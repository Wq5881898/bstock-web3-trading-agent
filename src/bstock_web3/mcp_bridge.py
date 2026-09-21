from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import secrets
from typing import Any, Literal

from .catalog import BStockAsset
from .strategy import SignalDecision


MCP_HOST = "codex"
MCP_TRANSPORT = "codex-binance-agent-os-mcp"
MCP_SPOT_ORDER_TOOL = "spot.newOrder"
MCP_SPOT_READ_TOOLS = (
    "spot.getAccount", "spot.getOpenOrders", "spot.myTrades",
    "spot.allOrders", "spot.accountCommission", "spot.exchangeInfo",
    "spot.tickerBookTicker",
)
ACCOUNT_BINDING_ALGORITHM = "sha256(salt-bytes+uid-ascii)"
MCP_READ_REQUIREMENTS = {
    "read_only": True,
    "complete_trade_and_order_pagination": True,
    "sanitize_account_identifiers_before_persistence": True,
    "local_oauth_prohibited": True,
    "alternate_api_fallback_prohibited": True,
}


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _spot_symbol(value: str) -> str:
    symbol = value.strip().upper() if isinstance(value, str) else ""
    if not symbol or len(symbol) > 32 or not symbol.isalnum():
        raise ValueError("Invalid MCP Spot symbol")
    return symbol


@dataclass(frozen=True)
class McpAccountBinding:
    """Opaque local binding for one host-selected Agentic account."""

    schema_version: str
    account_ref: str
    algorithm: str
    salt: str
    fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("Unsupported MCP account binding version")
        if (not isinstance(self.account_ref, str)
                or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}",
                                self.account_ref) is None):
            raise ValueError("Invalid MCP account reference")
        if self.algorithm != ACCOUNT_BINDING_ALGORITHM:
            raise ValueError("Unsupported MCP account binding algorithm")
        if not isinstance(self.salt, str) or re.fullmatch(
                r"[0-9a-f]{64}", self.salt) is None:
            raise ValueError("Invalid MCP account binding salt")
        if self.fingerprint is not None and (
                not isinstance(self.fingerprint, str) or re.fullmatch(
                    r"[0-9a-f]{64}", self.fingerprint) is None):
            raise ValueError("Invalid MCP account fingerprint")

    @classmethod
    def create(cls, account_ref: str = "agentic-primary"):
        return cls("1.0", account_ref, ACCOUNT_BINDING_ALGORITHM,
                   secrets.token_hex(32))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]):
        expected = {"schema_version", "account_ref", "algorithm", "salt",
                    "fingerprint"}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("Invalid MCP account binding document")
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def enrolled(self, fingerprint: str):
        if self.fingerprint is not None:
            raise RuntimeError("MCP account binding is already enrolled")
        return McpAccountBinding(self.schema_version, self.account_ref,
                                 self.algorithm, self.salt, fingerprint)


def write_mcp_account_binding(binding: McpAccountBinding, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(binding.to_dict(), ensure_ascii=False,
                                    indent=2), encoding="utf-8")
    temporary.replace(path)


def load_mcp_account_binding(path: Path) -> McpAccountBinding:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("Invalid MCP account binding file") from None
    return McpAccountBinding.from_dict(payload)


def load_or_create_mcp_account_binding(
    path: Path, *, account_ref: str = "agentic-primary",
) -> McpAccountBinding:
    if path.exists():
        return load_mcp_account_binding(path)
    binding = McpAccountBinding.create(account_ref)
    write_mcp_account_binding(binding, path)
    return binding


@dataclass(frozen=True)
class McpSpotReadRequest:
    """Credential-free work item for the already authenticated Codex MCP host.

    It deliberately contains no URL, OAuth client identity or access token.  The
    desktop application writes this file; Codex performs the actual MCP calls in
    its supported, user-authorized Binance Agent OS session.
    """

    schema_version: str
    request_id: str
    operation: Literal["READ_SPOT_SNAPSHOT"]
    host: Literal["codex"]
    transport: str
    account_scope: str
    venue: Literal["BINANCE_SPOT"]
    symbol: str
    account_binding: dict[str, Any]
    required_tools: tuple[str, ...]
    requirements: dict[str, Any]
    status: Literal["AWAITING_SUPPORTED_HOST"]
    created_at: str
    expires_at: str

    def __post_init__(self) -> None:
        if (self.schema_version != "2.0"
                or not isinstance(self.request_id, str)
                or re.fullmatch(r"mcp-read-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}",
                                self.request_id) is None
                or self.operation != "READ_SPOT_SNAPSHOT"
                or self.host != MCP_HOST or self.transport != MCP_TRANSPORT
                or self.account_scope !=
                    "existing-host-selected-agentic-sub-account"
                or self.venue != "BINANCE_SPOT"
                or self.symbol != _spot_symbol(self.symbol)
                or tuple(self.required_tools) != MCP_SPOT_READ_TOOLS
                or self.requirements != MCP_READ_REQUIREMENTS
                or self.status != "AWAITING_SUPPORTED_HOST"):
            raise ValueError("Invalid MCP Spot read request")
        binding = McpAccountBinding.from_dict(self.account_binding)
        if binding.to_dict() != self.account_binding:
            raise ValueError("Invalid MCP account binding in request")
        try:
            created = datetime.fromisoformat(
                self.created_at.replace("Z", "+00:00"))
            expires = datetime.fromisoformat(
                self.expires_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            raise ValueError("Invalid MCP read request timestamps") from None
        if (created.tzinfo is None or expires.tzinfo is None
                or not created < expires
                or expires - created > timedelta(hours=1)):
            raise ValueError("Invalid MCP read request lifetime")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]):
        expected = {field.name for field in cls.__dataclass_fields__.values()}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("Invalid MCP Spot read request document")
        values = dict(payload)
        tools = values.get("required_tools")
        if not isinstance(tools, list):
            raise ValueError("Invalid MCP Spot read tools")
        values["required_tools"] = tuple(tools)
        return cls(**values)

    def require_current(self, *, now: datetime | None = None) -> None:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        if current > expiry or self.status != "AWAITING_SUPPORTED_HOST":
            raise RuntimeError("MCP read request is expired or not dispatchable")


def build_mcp_spot_read_request(
    symbol: str, *, max_age_seconds: int = 300,
    account_binding: McpAccountBinding | None = None,
    now: datetime | None = None,
) -> McpSpotReadRequest:
    if type(max_age_seconds) is not int or max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    normalized = _spot_symbol(symbol)
    binding = account_binding or McpAccountBinding.create()
    if not isinstance(binding, McpAccountBinding):
        raise ValueError("MCP account binding required")
    created = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return McpSpotReadRequest(
        schema_version="2.0",
        request_id=(f"mcp-read-{created.strftime('%Y%m%dT%H%M%SZ')}-"
                    f"{secrets.token_hex(4)}"),
        operation="READ_SPOT_SNAPSHOT",
        host=MCP_HOST,
        transport=MCP_TRANSPORT,
        account_scope="existing-host-selected-agentic-sub-account",
        venue="BINANCE_SPOT",
        symbol=normalized,
        account_binding=binding.to_dict(),
        required_tools=MCP_SPOT_READ_TOOLS,
        requirements=dict(MCP_READ_REQUIREMENTS),
        status="AWAITING_SUPPORTED_HOST",
        created_at=_utc(created),
        expires_at=_utc(created + timedelta(seconds=max_age_seconds)),
    )


@dataclass(frozen=True)
class McpSpotOrderPlan:
    """Credential-free handoff from the deterministic engine to an MCP host.

    The plan is data, not an executable API request. The Agent OS host must query
    current account/market state, show the final order to the operator and obtain
    confirmation through the supported host before calling ``spot.newOrder``.
    """

    schema_version: str
    plan_id: str
    transport: str
    account_scope: str
    venue: str
    symbol: str
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET"]
    order_arguments: dict[str, Any]
    signal: dict[str, Any]
    risk_controls: dict[str, Any]
    required_tool: str
    status: Literal["AWAITING_SUPPORTED_HOST"]
    created_at: str
    expires_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def require_host_dispatchable(
        self, *, host_confirmed: bool, now: datetime | None = None,
    ) -> None:
        """Fail closed until the supported host records its real confirmation."""
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        if host_confirmed is not True:
            raise RuntimeError("Supported MCP host confirmation required")
        if current > expiry:
            raise RuntimeError("MCP order plan expired")
        if self.required_tool != MCP_SPOT_ORDER_TOOL:
            raise RuntimeError("MCP tool allowlist validation failed")
        if self.status != "AWAITING_SUPPORTED_HOST":
            raise RuntimeError("MCP order plan is not dispatchable")


def build_mcp_spot_plan(
    asset: BStockAsset,
    signal: SignalDecision,
    *,
    amount_usdt: Decimal,
    position_quantity: Decimal = Decimal("0"),
    max_age_seconds: int = 45,
    min_expected_edge_bps: Decimal = Decimal("10"),
    now: datetime | None = None,
) -> McpSpotOrderPlan:
    if signal.action not in {"buy", "sell"}:
        raise ValueError("只有 buy/sell 信号可以生成 MCP 订单计划")
    if amount_usdt <= 0:
        raise ValueError("amount_usdt 必须大于 0")
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds 必须大于 0")

    expected_edge_bps = Decimal(str(signal.expected_edge or 0)) * Decimal("10000")
    if signal.action == "buy" and expected_edge_bps < min_expected_edge_bps:
        raise RuntimeError(
            f"预期边际 {expected_edge_bps} bps 低于本地风险门槛 "
            f"{min_expected_edge_bps} bps"
        )

    side: Literal["BUY", "SELL"] = "BUY" if signal.action == "buy" else "SELL"
    if side == "BUY":
        arguments: dict[str, Any] = {
            "symbol": asset.spot_symbol,
            "side": side,
            "type": "MARKET",
            "quoteOrderQty": format(amount_usdt, "f"),
            "newOrderRespType": "FULL",
        }
    else:
        if position_quantity <= 0:
            raise ValueError("SELL 计划必须提供正数 position_quantity")
        arguments = {
            "symbol": asset.spot_symbol,
            "side": side,
            "type": "MARKET",
            "quantity": format(position_quantity, "f"),
            "newOrderRespType": "FULL",
        }

    created = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expires = created + timedelta(seconds=max_age_seconds)
    plan_id = f"mcp-{created.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    return McpSpotOrderPlan(
        schema_version="2.0",
        plan_id=plan_id,
        transport=MCP_TRANSPORT,
        account_scope="existing-host-selected-agentic-sub-account",
        venue="BINANCE_SPOT",
        symbol=asset.spot_symbol,
        side=side,
        order_type="MARKET",
        order_arguments=arguments,
        signal=asdict(signal),
        risk_controls={
            "manual_confirmation_required": True,
            "confirmation_owner": "SUPPORTED_MCP_HOST",
            "existing_host_session_required": True,
            "local_oauth_prohibited": True,
            "alternate_api_fallback_prohibited": True,
            "host_must_query_spot_account": True,
            "host_must_revalidate_symbol": True,
            "host_must_query_commission": True,
            "host_must_show_final_order": True,
            "host_must_query_terminal_order_status": True,
            "min_expected_edge_bps": str(min_expected_edge_bps),
            "expected_edge_bps": str(expected_edge_bps),
            "max_plan_age_seconds": max_age_seconds,
            "credential_storage": "HOST_ONLY",
        },
        required_tool=MCP_SPOT_ORDER_TOOL,
        status="AWAITING_SUPPORTED_HOST",
        created_at=_utc(created),
        expires_at=_utc(expires),
    )


def write_mcp_plan(plan: McpSpotOrderPlan, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def write_mcp_read_request(request: McpSpotReadRequest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_mcp_read_request(path: Path) -> McpSpotReadRequest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("Invalid MCP Spot read request file") from None
    return McpSpotReadRequest.from_dict(payload)
