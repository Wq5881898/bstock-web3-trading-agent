from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import secrets
from typing import Any, Literal

from .catalog import BStockAsset
from .strategy import SignalDecision


MCP_TRANSPORT = "binance-agent-os-mcp"
MCP_SPOT_ORDER_TOOL = "spot.newOrder"


@dataclass(frozen=True)
class McpSpotOrderPlan:
    """Credential-free handoff from the deterministic engine to an MCP host.

    The plan is data, not an executable API request. The Agent OS host must query
    current account/market state, show the final order to the operator and receive
    the exact one-time confirmation before calling ``spot.newOrder``.
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
    status: Literal["AWAITING_HOST_VALIDATION"]
    confirmation: str
    created_at: str
    expires_at: str

    def to_dict(self, *, include_confirmation: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        if not include_confirmation:
            payload.pop("confirmation", None)
        return payload

    def require_dispatchable(self, confirmation: str,
                             *, now: datetime | None = None) -> None:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        if current > expiry:
            raise RuntimeError("MCP 订单计划已过期；必须重新生成信号并重新核验行情")
        if confirmation.strip() != self.confirmation:
            raise RuntimeError("MCP 逐笔确认码不匹配；禁止调用 spot.newOrder")
        if self.required_tool != MCP_SPOT_ORDER_TOOL:
            raise RuntimeError("MCP 工具白名单校验失败")
        if self.status != "AWAITING_HOST_VALIDATION":
            raise RuntimeError("MCP 订单计划状态不可提交")


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
            "quoteOrderQty": float(amount_usdt),
            "newOrderRespType": "FULL",
        }
    else:
        if position_quantity <= 0:
            raise ValueError("SELL 计划必须提供正数 position_quantity")
        arguments = {
            "symbol": asset.spot_symbol,
            "side": side,
            "type": "MARKET",
            "quantity": float(position_quantity),
            "newOrderRespType": "FULL",
        }

    created = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expires = created + timedelta(seconds=max_age_seconds)
    plan_id = f"mcp-{created.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    confirmation = f"MCP CONFIRM {secrets.token_hex(4).upper()}"
    return McpSpotOrderPlan(
        schema_version="1.0",
        plan_id=plan_id,
        transport=MCP_TRANSPORT,
        account_scope="oauth-agentic-sub-account",
        venue="BINANCE_SPOT",
        symbol=asset.spot_symbol,
        side=side,
        order_type="MARKET",
        order_arguments=arguments,
        signal=asdict(signal),
        risk_controls={
            "manual_confirmation_required": True,
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
        status="AWAITING_HOST_VALIDATION",
        confirmation=confirmation,
        created_at=created.isoformat().replace("+00:00", "Z"),
        expires_at=expires.isoformat().replace("+00:00", "Z"),
    )


def write_mcp_plan(plan: McpSpotOrderPlan, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
