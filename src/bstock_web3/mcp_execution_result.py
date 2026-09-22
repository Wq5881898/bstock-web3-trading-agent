"""Strict file boundary for terminal Binance Agent OS Spot results.

The supported MCP host owns all network/tool calls.  This module only verifies
a sanitized result file, reconciles the complete post-order account snapshot,
persists complete fills, and then advances the durable execution journal.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
import re
import secrets
from typing import Any, Literal

from .execution_safety import ExecutionPhase, McpReconciliationEvidence
from .mcp_bridge import (MCP_HOST, MCP_SPOT_ORDER_LOOKUP_TOOL,
    MCP_SPOT_READ_TOOLS, MCP_TRANSPORT, McpAccountBinding)
from .mcp_confirmed import ConfirmedOrderResult, ConfirmedSpotExecutor
from .mcp_execution_handoff import McpSpotSubmissionTicket
from .mcp_spot_snapshot import (LocalRiskMetrics,
    build_bound_mcp_spot_evidence)
from .spot_accounting import (SpotFillLedger, SpotFillSummary,
    fill_risk_stats, normalize_fills)


EXECUTION_RESULT_OPERATION = "SUBMIT_CONFIRMED_SPOT_ORDER_RESULT"
MCP_SPOT_TERMINAL_TOOLS = (MCP_SPOT_ORDER_LOOKUP_TOOL,
                           *MCP_SPOT_READ_TOOLS)
_FORBIDDEN_KEYS = frozenset({
    "uid", "accesstoken", "refreshtoken", "apikey", "apisecret",
    "authorizationcode", "password", "privatekey", "seedphrase",
    "confirmation", "confirmationphrase",
})
_TERMINAL_STATUSES = frozenset({
    "FILLED", "CANCELED", "REJECTED", "EXPIRED", "EXPIRED_IN_MATCH",
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
                raise ValueError("Invalid MCP execution receipt key")
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in _FORBIDDEN_KEYS:
                raise ValueError("MCP execution receipt contains forbidden data")
            _assert_sanitized(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_sanitized(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Invalid MCP execution receipt number")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("Invalid MCP execution receipt value")


@dataclass(frozen=True)
class VerifiedMcpSpotExecutionReceipt:
    receipt_id: str
    plan_id: str
    signal_fingerprint: str
    execution_fingerprint: str
    account_ref: str
    account_fingerprint: str
    symbol: str
    observed_at: str
    outcome: Literal["TERMINAL", "UNKNOWN"]
    completed_tools: tuple[str, ...]
    pagination: dict[str, bool]
    tool_results: dict[str, Any]

    def __post_init__(self) -> None:
        self.require_valid()

    def require_valid(self) -> None:
        if (re.fullmatch(
                r"mcp-exec-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}",
                self.receipt_id or "") is None
                or re.fullmatch(r"mcp-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}",
                                self.plan_id or "") is None
                or re.fullmatch(r"[0-9a-f]{64}",
                                self.signal_fingerprint or "") is None
                or re.fullmatch(r"[0-9a-f]{64}",
                                self.execution_fingerprint or "") is None
                or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}",
                                self.account_ref or "") is None
                or re.fullmatch(r"[0-9a-f]{64}",
                                self.account_fingerprint or "") is None
                or re.fullmatch(r"[A-Z0-9]{1,32}", self.symbol or "") is None
                or self.outcome not in ("TERMINAL", "UNKNOWN")):
            raise ValueError("Invalid verified MCP execution receipt")
        _timestamp(self.observed_at, "execution receipt observation time")
        if self.outcome == "UNKNOWN":
            valid_shape = (self.completed_tools == ()
                and self.pagination == {
                    "trades_complete": False, "orders_complete": False}
                and self.tool_results == {})
        else:
            valid_shape = (self.completed_tools == MCP_SPOT_TERMINAL_TOOLS
                and self.pagination == {
                    "trades_complete": True, "orders_complete": True}
                and set(self.tool_results) == set(MCP_SPOT_TERMINAL_TOOLS))
        if not valid_shape:
            raise ValueError("Invalid verified MCP execution receipt shape")
        _assert_sanitized(asdict(self))

    @property
    def observed_at_ms(self) -> int:
        return int(_timestamp(self.observed_at,
                              "execution receipt observation time").timestamp()
                   * 1000)

    def to_persisted_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(schema_version="1.0",
                       operation=EXECUTION_RESULT_OPERATION,
                       host=MCP_HOST, transport=MCP_TRANSPORT)
        payload["completed_tools"] = list(self.completed_tools)
        return payload


@dataclass(frozen=True)
class ImportedMcpSpotExecution:
    order: ConfirmedOrderResult | None
    phase: ExecutionPhase
    fill_summary: SpotFillSummary | None
    evidence: McpReconciliationEvidence | None


def verify_execution_result_receipt(
    ticket: McpSpotSubmissionTicket,
    binding: McpAccountBinding,
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> VerifiedMcpSpotExecutionReceipt:
    """Verify identity, freshness and exact terminal/unknown receipt shape."""
    if (not isinstance(ticket, McpSpotSubmissionTicket)
            or not isinstance(binding, McpAccountBinding)):
        raise ValueError("Submission ticket and account binding required")
    if (binding.fingerprint is None
            or binding.account_ref != ticket.account_ref
            or not secrets.compare_digest(binding.fingerprint,
                                           ticket.account_fingerprint)):
        raise ValueError("MCP execution account binding mismatch")
    expected = {"schema_version", "receipt_id", "operation", "host",
        "transport", "plan_id", "signal_fingerprint",
        "execution_fingerprint", "account_ref", "account_fingerprint",
        "symbol", "observed_at", "outcome", "completed_tools",
        "pagination", "tool_results"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("Invalid MCP execution receipt document")
    _assert_sanitized(payload)
    if (payload["schema_version"] != "1.0"
            or re.fullmatch(
                r"mcp-exec-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}",
                payload.get("receipt_id") or "") is None
            or payload["operation"] != EXECUTION_RESULT_OPERATION
            or payload["host"] != MCP_HOST
            or payload["transport"] != MCP_TRANSPORT
            or payload["plan_id"] != ticket.plan_id
            or payload["signal_fingerprint"] != ticket.signal_fingerprint
            or payload["execution_fingerprint"]
                != ticket.execution_fingerprint
            or payload["account_ref"] != ticket.account_ref
            or not isinstance(payload["account_fingerprint"], str)
            or not secrets.compare_digest(payload["account_fingerprint"],
                                          ticket.account_fingerprint)
            or payload["symbol"] != ticket.symbol
            or payload["outcome"] not in ("TERMINAL", "UNKNOWN")
            or not isinstance(payload["completed_tools"], list)
            or not isinstance(payload["pagination"], dict)
            or not isinstance(payload["tool_results"], dict)):
        raise ValueError("MCP execution receipt does not match the ticket")
    observed = _timestamp(payload["observed_at"],
                          "execution receipt observation time")
    created = _timestamp(ticket.created_at, "submission ticket creation time")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if observed < created or observed > current:
        raise ValueError("MCP execution receipt observation is invalid")
    if payload["outcome"] == "UNKNOWN":
        if (payload["completed_tools"] != []
                or payload["pagination"] != {
                    "trades_complete": False, "orders_complete": False}
                or payload["tool_results"] != {}):
            raise ValueError("Invalid UNKNOWN MCP execution receipt")
    elif (payload["completed_tools"] != list(MCP_SPOT_TERMINAL_TOOLS)
            or payload["pagination"] != {
                "trades_complete": True, "orders_complete": True}
            or set(payload["tool_results"]) != set(MCP_SPOT_TERMINAL_TOOLS)):
        raise ValueError("Incomplete terminal MCP execution receipt")
    return VerifiedMcpSpotExecutionReceipt(
        receipt_id=payload["receipt_id"], plan_id=payload["plan_id"],
        signal_fingerprint=payload["signal_fingerprint"],
        execution_fingerprint=payload["execution_fingerprint"],
        account_ref=payload["account_ref"],
        account_fingerprint=payload["account_fingerprint"],
        symbol=payload["symbol"], observed_at=payload["observed_at"],
        outcome=payload["outcome"],
        completed_tools=tuple(payload["completed_tools"]),
        pagination=dict(payload["pagination"]),
        tool_results=dict(payload["tool_results"]))


def _exchange_assets(payload: Any, symbol: str) -> tuple[str, str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"),
                                                       list):
        raise ValueError("Invalid terminal Spot exchange identity")
    matches = [row for row in payload["symbols"]
               if isinstance(row, dict) and row.get("symbol") == symbol]
    if len(matches) != 1:
        raise ValueError("Terminal Spot symbol is unavailable")
    base = matches[0].get("baseAsset")
    quote = matches[0].get("quoteAsset")
    if (not isinstance(base, str) or not isinstance(quote, str)
            or re.fullmatch(r"[A-Z0-9]{1,32}", base) is None
            or re.fullmatch(r"[A-Z0-9]{1,32}", quote) is None
            or base + quote != symbol):
        raise ValueError("Invalid terminal Spot exchange identity")
    return base, quote


def _reconcile_order_fills(order: ConfirmedOrderResult, order_payload: dict,
                           orders: Any, open_orders: Any, trades: Any, *,
                           symbol: str, base_asset: str,
                           quote_asset: str) -> list[dict]:
    if order.status not in _TERMINAL_STATUSES:
        raise ValueError("MCP execution receipt is not terminal")
    if not isinstance(orders, list):
        raise ValueError("Invalid terminal Spot order history")
    matches = [row for row in orders if isinstance(row, dict)
               and str(row.get("orderId")) == order.order_id]
    if len(matches) != 1:
        raise ValueError("Terminal Spot order is missing from order history")
    if (not isinstance(open_orders, list)
            or any(isinstance(row, dict)
                   and str(row.get("orderId")) == order.order_id
                   for row in open_orders)):
        raise ValueError("Terminal Spot order still appears open")
    historical = matches[0]
    fields = ("symbol", "clientOrderId", "side", "type", "status",
              "executedQty", "cummulativeQuoteQty")
    if any(historical.get(key) != order_payload.get(key) for key in fields):
        raise ValueError("Terminal Spot order history changed")
    rows = normalize_fills(trades, symbol, base_asset, quote_asset)
    matching = [row for row in rows if str(row["orderId"]) == order.order_id]
    executed_base = sum((Decimal(row["qty"]) for row in matching), Decimal("0"))
    executed_quote = sum((Decimal(row["quoteQty"]) for row in matching),
                         Decimal("0"))
    if (executed_base != order.executed_base
            or executed_quote != order.executed_quote):
        raise ValueError("Terminal Spot fills do not match the order result")
    return rows


def import_execution_result(
    receipt: VerifiedMcpSpotExecutionReceipt,
    ticket: McpSpotSubmissionTicket,
    executor: ConfirmedSpotExecutor,
    fill_ledger: SpotFillLedger | None,
    *,
    daily_equity_loss: Decimal,
    now_ms: int,
) -> ImportedMcpSpotExecution:
    """Persist complete fills before advancing a terminal execution journal."""
    if (not isinstance(receipt, VerifiedMcpSpotExecutionReceipt)
            or not isinstance(ticket, McpSpotSubmissionTicket)
            or not isinstance(executor, ConfirmedSpotExecutor)
            or type(now_ms) is not int or now_ms < receipt.observed_at_ms
            or not isinstance(daily_equity_loss, Decimal)
            or not daily_equity_loss.is_finite()
            or daily_equity_loss < 0):
        raise ValueError("Invalid MCP execution result import")
    receipt.require_valid()
    if (receipt.plan_id != ticket.plan_id
            or receipt.execution_fingerprint != ticket.execution_fingerprint
            or receipt.account_ref != ticket.account_ref
            or receipt.account_fingerprint != ticket.account_fingerprint
            or receipt.symbol != ticket.symbol):
        raise ValueError("MCP execution receipt identity changed")
    record = executor.journal.get(receipt.execution_fingerprint)
    if (record.account_ref != receipt.account_ref
            or record.symbol != receipt.symbol
            or record.client_order_id
                != ticket.arguments["newClientOrderId"]):
        raise ValueError("Execution journal does not match the MCP receipt")
    if receipt.outcome == "UNKNOWN":
        updated = executor.mark_submission_unknown(
            receipt.execution_fingerprint, now_ms=now_ms)
        return ImportedMcpSpotExecution(None, updated.phase, None, None)
    if not isinstance(fill_ledger, SpotFillLedger):
        raise ValueError("Terminal MCP receipt requires a Spot fill ledger")
    results = receipt.tool_results
    base_asset, quote_asset = _exchange_assets(
        results["spot.exchangeInfo"], receipt.symbol)
    if not isinstance(results["spot.accountCommission"], dict):
        raise ValueError("Invalid terminal Spot commission result")
    order_payload = results[MCP_SPOT_ORDER_LOOKUP_TOOL]
    order = executor.validate_submission_result(
        receipt.execution_fingerprint, order_payload)
    rows = _reconcile_order_fills(order, order_payload,
        results["spot.allOrders"], results["spot.getOpenOrders"],
        results["spot.myTrades"], symbol=receipt.symbol,
        base_asset=base_asset, quote_asset=quote_asset)
    risk_day = _timestamp(receipt.observed_at,
                          "execution receipt observation time").date().isoformat()
    stats = fill_risk_stats(rows, receipt.symbol, base_asset,
                            quote_asset, risk_day)
    risk = LocalRiskMetrics(daily_equity_loss, stats.daily_entries,
                            stats.consecutive_losses, stats.last_entry_ms)
    evidence = build_bound_mcp_spot_evidence(
        account=results["spot.getAccount"],
        open_orders=results["spot.getOpenOrders"], trades=rows,
        all_orders=results["spot.allOrders"],
        book=results["spot.tickerBookTicker"],
        account_ref=receipt.account_ref, account_binding_verified=True,
        symbol=receipt.symbol, base_asset=base_asset,
        quote_asset=quote_asset, risk_day=risk_day,
        observed_at_ms=receipt.observed_at_ms,
        evidence_id="exec-" + receipt.receipt_id, risk=risk,
        trade_history_complete=True)
    expected_identity = {"account_ref": receipt.account_ref,
        "symbol": receipt.symbol, "base_asset": base_asset,
        "quote_asset": quote_asset}
    if fill_ledger.identity != expected_identity:
        raise ValueError("Spot fill ledger identity mismatch")
    with fill_ledger:
        summary = fill_ledger.sync(rows, history_complete=True)
    result = executor.accept_submission_result(
        receipt.execution_fingerprint, order_payload, now_ms=now_ms)
    phase = executor.journal.get(receipt.execution_fingerprint).phase
    return ImportedMcpSpotExecution(result, phase, summary, evidence)


def load_execution_result_receipt(
    ticket: McpSpotSubmissionTicket,
    binding: McpAccountBinding,
    path: Path,
    *,
    now: datetime | None = None,
) -> VerifiedMcpSpotExecutionReceipt:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("Invalid MCP execution receipt file") from None
    return verify_execution_result_receipt(ticket, binding, payload, now=now)


def write_verified_execution_result(
    receipt: VerifiedMcpSpotExecutionReceipt, path: Path,
) -> None:
    if not isinstance(receipt, VerifiedMcpSpotExecutionReceipt):
        raise ValueError("Invalid verified MCP execution receipt")
    receipt.require_valid()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt.to_persisted_dict(),
                                    ensure_ascii=False, indent=2),
                         encoding="utf-8")
    temporary.replace(path)
