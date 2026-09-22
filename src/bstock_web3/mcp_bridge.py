from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import secrets
from typing import Any, Literal

from .catalog import BStockAsset
from .strategy import SignalDecision
from .strategy_registry import ensure_strategy_supports


MCP_HOST = "codex"
MCP_TRANSPORT = "codex-binance-agent-os-mcp"
MCP_SPOT_ORDER_TOOL = "spot.newOrder"
MCP_SPOT_ORDER_LOOKUP_TOOL = "spot.getOrder"
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
    current account/market state, create a confirmation preview, consume that
    confirmation and mint a short-lived submission ticket before it may call
    ``spot.newOrder``.
    """

    schema_version: str
    plan_id: str
    host: Literal["codex"]
    transport: str
    account_scope: str
    account_binding: dict[str, Any]
    venue: str
    symbol: str
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET"]
    order_arguments: dict[str, Any]
    signal: dict[str, Any]
    risk_controls: dict[str, Any]
    signal_fingerprint: str
    required_preflight_tools: tuple[str, ...]
    required_tool: str
    lookup_tool: str
    status: Literal["AWAITING_HOST_PREFLIGHT"]
    created_at: str
    expires_at: str

    def __post_init__(self) -> None:
        if (self.schema_version != "3.0"
                or not isinstance(self.plan_id, str)
                or re.fullmatch(r"mcp-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}",
                                self.plan_id) is None
                or self.host != MCP_HOST or self.transport != MCP_TRANSPORT
                or self.account_scope !=
                    "existing-host-selected-agentic-sub-account"
                or self.venue != "BINANCE_SPOT"
                or self.symbol != _spot_symbol(self.symbol)
                or self.side not in ("BUY", "SELL")
                or self.order_type != "MARKET"
                or tuple(self.required_preflight_tools) != MCP_SPOT_READ_TOOLS
                or self.required_tool != MCP_SPOT_ORDER_TOOL
                or self.lookup_tool != MCP_SPOT_ORDER_LOOKUP_TOOL
                or self.status != "AWAITING_HOST_PREFLIGHT"
                or not isinstance(self.signal_fingerprint, str)
                or re.fullmatch(r"[0-9a-f]{64}",
                                self.signal_fingerprint) is None):
            raise ValueError("Invalid MCP Spot order plan")
        binding = McpAccountBinding.from_dict(self.account_binding)
        if binding.fingerprint is None or binding.to_dict() != self.account_binding:
            raise ValueError("Enrolled MCP account binding required")
        self._validate_signal()
        self._validate_order_arguments()
        expected = _order_plan_fingerprint(
            binding, self.symbol, self.side, self.order_arguments, self.signal)
        if not secrets.compare_digest(expected, self.signal_fingerprint):
            raise ValueError("MCP order plan identity mismatch")
        created, expires = (_parse_utc(value, "MCP order plan timestamp")
                            for value in (self.created_at, self.expires_at))
        if not created < expires or expires - created > timedelta(seconds=60):
            raise ValueError("Invalid MCP order plan lifetime")
        self._validate_risk_controls(expires - created)
        _assert_no_secret_keys(self.to_dict())

    def _validate_signal(self) -> None:
        expected = {field.name for field in SignalDecision.__dataclass_fields__.values()}
        if not isinstance(self.signal, dict) or set(self.signal) != expected:
            raise ValueError("Invalid MCP order signal")
        action = "buy" if self.side == "BUY" else "sell"
        strategy_id = self.signal.get("strategy_id")
        if (self.signal.get("action") != action
                or not isinstance(strategy_id, str) or not strategy_id
                or not isinstance(self.signal.get("reason"), str)
                or not self.signal["reason"].strip()
                or not isinstance(self.signal.get("signal_bar_time"), str)
                or not self.signal["signal_bar_time"].strip()
                or not isinstance(self.signal.get("strategy_params"), dict)):
            raise ValueError("Invalid MCP order signal")
        ensure_strategy_supports(strategy_id, "SPOT")
        try:
            price = Decimal(str(self.signal.get("price")))
        except Exception:
            raise ValueError("Invalid MCP order signal price") from None
        if not price.is_finite() or price <= 0:
            raise ValueError("Invalid MCP order signal price")
        for key in ("trend_spread", "expected_edge"):
            value = self.signal.get(key)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Invalid MCP order signal metric")
            if not Decimal(str(value)).is_finite():
                raise ValueError("Invalid MCP order signal metric")
        try:
            json.dumps(self.signal, sort_keys=True, ensure_ascii=True,
                       allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError("Invalid MCP order signal data") from None

    def _validate_order_arguments(self) -> None:
        amount_name = "quoteOrderQty" if self.side == "BUY" else "quantity"
        expected = {"symbol", "side", "type", amount_name,
                    "newOrderRespType"}
        if (not isinstance(self.order_arguments, dict)
                or set(self.order_arguments) != expected
                or self.order_arguments.get("symbol") != self.symbol
                or self.order_arguments.get("side") != self.side
                or self.order_arguments.get("type") != "MARKET"
                or self.order_arguments.get("newOrderRespType") != "FULL"):
            raise ValueError("Invalid MCP Spot order arguments")
        value = self.order_arguments.get(amount_name)
        if not isinstance(value, str):
            raise ValueError("Invalid MCP order amount")
        try:
            amount = Decimal(value)
        except Exception:
            raise ValueError("Invalid MCP order amount") from None
        if not amount.is_finite() or amount <= 0:
            raise ValueError("Invalid MCP order amount")

    def _validate_risk_controls(self, lifetime: timedelta) -> None:
        static = {
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
            "host_must_prepare_deterministic_client_order_id": True,
            "credential_storage": "HOST_ONLY",
        }
        numeric = {"min_expected_edge_bps", "expected_edge_bps",
                   "max_plan_age_seconds"}
        if (not isinstance(self.risk_controls, dict)
                or set(self.risk_controls) != set(static) | numeric
                or any(self.risk_controls.get(k) != v
                       for k, v in static.items())
                or type(self.risk_controls.get("max_plan_age_seconds")) is not int
                or not 0 < self.risk_controls["max_plan_age_seconds"] <= 60
                or lifetime != timedelta(
                    seconds=self.risk_controls["max_plan_age_seconds"])):
            raise ValueError("Invalid MCP order risk controls")
        parsed: dict[str, Decimal] = {}
        for key in ("min_expected_edge_bps", "expected_edge_bps"):
            value = self.risk_controls.get(key)
            if not isinstance(value, str):
                raise ValueError("Invalid MCP order risk controls")
            try:
                number = Decimal(value)
            except Exception:
                raise ValueError("Invalid MCP order risk controls") from None
            if not number.is_finite() or (key == "min_expected_edge_bps"
                                          and number < 0):
                raise ValueError("Invalid MCP order risk controls")
            parsed[key] = number
        signal_edge = self.signal.get("expected_edge")
        expected_edge_bps = Decimal(str(signal_edge or 0)) * Decimal("10000")
        if (parsed["expected_edge_bps"] != expected_edge_bps
                or self.side == "BUY" and parsed["expected_edge_bps"]
                < parsed["min_expected_edge_bps"]):
            raise ValueError("Invalid MCP order risk controls")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]):
        expected = {field.name for field in cls.__dataclass_fields__.values()}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("Invalid MCP Spot order plan document")
        values = dict(payload)
        tools = values.get("required_preflight_tools")
        if not isinstance(tools, list):
            raise ValueError("Invalid MCP Spot order preflight tools")
        values["required_preflight_tools"] = tuple(tools)
        return cls(**values)

    def require_host_preflightable(
        self, *, now: datetime | None = None,
    ) -> None:
        """Validate freshness before the host creates a safe execution ticket."""
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        if current < created or current >= expiry:
            raise RuntimeError("MCP order plan expired or not yet valid")
        if self.required_tool != MCP_SPOT_ORDER_TOOL:
            raise RuntimeError("MCP tool allowlist validation failed")
        if self.status != "AWAITING_HOST_PREFLIGHT":
            raise RuntimeError("MCP order plan is not preflightable")


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"Invalid {label}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid {label}") from None
    if parsed.tzinfo is None:
        raise ValueError(f"Invalid {label}")
    return parsed.astimezone(timezone.utc)


def _assert_no_secret_keys(value: Any) -> None:
    forbidden = {"uid", "accesstoken", "refreshtoken", "apikey",
                 "apisecret", "authorizationcode", "password",
                 "privatekey", "seedphrase"}
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in forbidden:
                raise ValueError("MCP order plan contains forbidden secret data")
            _assert_no_secret_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_secret_keys(item)


def _order_plan_fingerprint(binding: McpAccountBinding, symbol: str, side: str,
                            arguments: dict[str, Any],
                            signal: dict[str, Any]) -> str:
    order = {key: value for key, value in arguments.items()
             if key != "newClientOrderId"}
    payload = {"account_binding": binding.to_dict(), "symbol": symbol,
               "side": side, "order": order, "signal": signal}
    try:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise ValueError("Invalid MCP order identity data") from None
    return hashlib.sha256(canonical).hexdigest()


def build_mcp_spot_plan(
    asset: BStockAsset,
    signal: SignalDecision,
    *,
    amount_usdt: Decimal,
    position_quantity: Decimal = Decimal("0"),
    max_age_seconds: int = 45,
    min_expected_edge_bps: Decimal = Decimal("10"),
    account_binding: McpAccountBinding | None = None,
    now: datetime | None = None,
) -> McpSpotOrderPlan:
    if signal.action not in {"buy", "sell"}:
        raise ValueError("只有 buy/sell 信号可以生成 MCP 订单计划")
    if amount_usdt <= 0:
        raise ValueError("amount_usdt 必须大于 0")
    if type(max_age_seconds) is not int or not 0 < max_age_seconds <= 60:
        raise ValueError("max_age_seconds 必须在 1 到 60 之间")
    if not isinstance(account_binding, McpAccountBinding) \
            or account_binding.fingerprint is None:
        raise ValueError("必须先完成 Agentic 账户指纹登记")
    if not signal.strategy_id:
        raise ValueError("可执行信号必须包含统一策略ID")
    ensure_strategy_supports(signal.strategy_id, "SPOT")
    if not isinstance(signal.signal_bar_time, str) \
            or not signal.signal_bar_time.strip():
        raise ValueError("可执行信号必须包含稳定事件时间")

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

    signal_payload = asdict(signal)
    fingerprint = _order_plan_fingerprint(
        account_binding, asset.spot_symbol, side, arguments, signal_payload)

    created = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expires = created + timedelta(seconds=max_age_seconds)
    plan_id = f"mcp-{created.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    return McpSpotOrderPlan(
        schema_version="3.0",
        plan_id=plan_id,
        host=MCP_HOST,
        transport=MCP_TRANSPORT,
        account_scope="existing-host-selected-agentic-sub-account",
        account_binding=account_binding.to_dict(),
        venue="BINANCE_SPOT",
        symbol=asset.spot_symbol,
        side=side,
        order_type="MARKET",
        order_arguments=arguments,
        signal=signal_payload,
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
            "host_must_prepare_deterministic_client_order_id": True,
            "min_expected_edge_bps": str(min_expected_edge_bps),
            "expected_edge_bps": str(expected_edge_bps),
            "max_plan_age_seconds": max_age_seconds,
            "credential_storage": "HOST_ONLY",
        },
        signal_fingerprint=fingerprint,
        required_preflight_tools=MCP_SPOT_READ_TOOLS,
        required_tool=MCP_SPOT_ORDER_TOOL,
        lookup_tool=MCP_SPOT_ORDER_LOOKUP_TOOL,
        status="AWAITING_HOST_PREFLIGHT",
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


def load_mcp_plan(path: Path) -> McpSpotOrderPlan:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("Invalid MCP Spot order plan file") from None
    return McpSpotOrderPlan.from_dict(payload)


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
