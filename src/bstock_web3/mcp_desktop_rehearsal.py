"""Non-dispatchable desktop rehearsal for the Codex-hosted MCP order flow.

This module deliberately has no MCP caller.  It verifies a fresh candidate and
fresh imported account receipt, exercises the same risk/confirmation checks as
the production handoff, then writes an artifact that a live host must reject.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
from typing import Any, Literal

from .automation_policy import AutomationPolicy, AutomationPolicyConfig
from .execution_lock import ExecutionLock
from .execution_safety import ExecutionJournal, ExecutionPhase
from .mcp_bridge import MCP_HOST, MCP_TRANSPORT, McpSpotOrderPlan, load_mcp_plan
from .mcp_confirmed import ConfirmedRehearsal, ConfirmedSpotExecutor, SpotMarketRules
from .mcp_execution_handoff import prepare_plan_preview
from .mcp_host_receipt import VerifiedSpotHostReceipt
from .mcp_spot_snapshot import LocalRiskMetrics


REHEARSAL_OPERATION = "REHEARSE_CONFIRMED_SPOT_ORDER"


def _utc_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace(
        "+00:00", "Z")


@dataclass(frozen=True)
class McpSpotRehearsalReport:
    schema_version: str
    operation: Literal["REHEARSE_CONFIRMED_SPOT_ORDER"]
    host: Literal["codex"]
    transport: str
    plan_id: str
    signal_fingerprint: str
    execution_fingerprint: str
    account_ref: str
    account_fingerprint: str
    symbol: str
    side: str
    arguments: dict[str, Any]
    dispatch_prohibited: Literal[True]
    required_tool: None
    execution_phase: Literal["PREPARED"]
    status: Literal["REHEARSAL_COMPLETE"]
    confirmed_at: str

    def __post_init__(self):
        if (self.schema_version != "1.0"
                or self.operation != REHEARSAL_OPERATION
                or self.host != MCP_HOST or self.transport != MCP_TRANSPORT
                or not re.fullmatch(r"mcp-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}",
                                    self.plan_id or "")
                or not re.fullmatch(r"[0-9a-f]{64}",
                                    self.signal_fingerprint or "")
                or not re.fullmatch(r"[0-9a-f]{64}",
                                    self.execution_fingerprint or "")
                or not isinstance(self.account_ref, str) or not self.account_ref
                or not re.fullmatch(r"[0-9a-f]{64}",
                                    self.account_fingerprint or "")
                or not re.fullmatch(r"[A-Z0-9]{1,32}", self.symbol or "")
                or self.side not in ("BUY", "SELL")
                or self.dispatch_prohibited is not True
                or self.required_tool is not None
                or self.execution_phase != ExecutionPhase.PREPARED.value
                or self.status != "REHEARSAL_COMPLETE"):
            raise ValueError("Invalid MCP desktop rehearsal report")
        if (not isinstance(self.arguments, dict)
                or self.arguments.get("symbol") != self.symbol
                or self.arguments.get("side") != self.side
                or self.arguments.get("type") != "MARKET"):
            raise ValueError("Invalid MCP rehearsal arguments")
        if not isinstance(self.confirmed_at, str) or not self.confirmed_at.endswith("Z"):
            raise ValueError("Invalid MCP rehearsal timestamp")

    def to_dict(self):
        return asdict(self)


def write_rehearsal_report(report: McpSpotRehearsalReport, path: Path) -> None:
    if not isinstance(report, McpSpotRehearsalReport) or not isinstance(path, Path):
        raise ValueError("Invalid MCP rehearsal report output")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report.to_dict(), ensure_ascii=False,
                                    indent=2), encoding="utf-8")
    temporary.replace(path)


class DesktopMcpRehearsalSession:
    """Own one preview and its lock until confirmation or cancellation."""

    def __init__(self, plan, receipt, evidence, executor, lock, preview,
                 report_path):
        self.plan = plan
        self.receipt = receipt
        self.evidence = evidence
        self.executor = executor
        self.lock = lock
        self.preview = preview
        self.report_path = report_path
        self.closed = False

    def confirm(self, phrase: str, *, now_ms: int | None = None):
        if self.closed:
            raise RuntimeError("MCP rehearsal session is closed")
        current = now_ms if now_ms is not None else int(
            datetime.now(timezone.utc).timestamp() * 1000)
        try:
            confirmed = self.executor.rehearse_confirmation(
                phrase, self.evidence, now_ms=current)
            report = self._report(confirmed)
            write_rehearsal_report(report, self.report_path)
            return self.report_path, report
        finally:
            self.close()

    def cancel(self):
        if self.closed:
            return
        self.executor.cancel_preview()
        self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            self.lock.release()

    def _report(self, confirmed: ConfirmedRehearsal):
        return McpSpotRehearsalReport(
            "1.0", REHEARSAL_OPERATION, MCP_HOST, MCP_TRANSPORT,
            self.plan.plan_id, self.plan.signal_fingerprint,
            confirmed.fingerprint, confirmed.account_ref,
            self.receipt.account_fingerprint, confirmed.symbol,
            self.plan.side, dict(confirmed.arguments), True, None,
            ExecutionPhase.PREPARED.value, "REHEARSAL_COMPLETE",
            _utc_ms(confirmed.confirmed_at_ms))


def prepare_desktop_rehearsal(
    plan_path: Path,
    receipt: VerifiedSpotHostReceipt,
    runtime_dir: Path,
    *,
    daily_equity_loss: Decimal = Decimal("0"),
    now_ms: int | None = None,
) -> DesktopMcpRehearsalSession:
    """Prepare one local-only confirmation exercise from strict inputs."""
    if (not isinstance(plan_path, Path)
            or not isinstance(receipt, VerifiedSpotHostReceipt)
            or not isinstance(runtime_dir, Path)
            or not isinstance(daily_equity_loss, Decimal)
            or not daily_equity_loss.is_finite() or daily_equity_loss < 0):
        raise ValueError("Invalid MCP desktop rehearsal input")
    current = now_ms if now_ms is not None else int(
        datetime.now(timezone.utc).timestamp() * 1000)
    plan = load_mcp_plan(plan_path)
    if plan.symbol != receipt.symbol:
        raise ValueError("MCP rehearsal plan and receipt symbol mismatch")
    risk_day = datetime.fromtimestamp(
        receipt.observed_at_ms / 1000, timezone.utc).date().isoformat()
    evidence = receipt.to_evidence(risk_day=risk_day,
        risk=LocalRiskMetrics(daily_equity_loss))
    rules = SpotMarketRules.from_exchange_info(
        receipt.tool_results["spot.exchangeInfo"], plan.symbol)
    session_dir = runtime_dir / "rehearsal"
    journal_path = session_dir / f"{plan.plan_id}-{current}-execution.json"
    lock = ExecutionLock(journal_path.with_suffix(".json.lock"))
    lock.require()
    try:
        policy = AutomationPolicy(AutomationPolicyConfig(
            order_budget_quote=Decimal(plan.order_arguments.get(
                "quoteOrderQty", "100")),
            cumulative_loss_limit=Decimal("10"),
            max_position_cost=Decimal("100000"),
            max_daily_entries=20, max_consecutive_losses=3,
            entry_cooldown_seconds=60, snapshot_max_age_seconds=15))
        executor = ConfirmedSpotExecutor(
            lambda *_: (_ for _ in ()).throw(
                AssertionError("desktop rehearsal cannot call MCP")),
            ExecutionJournal(journal_path, lock), policy)
        preview = prepare_plan_preview(plan, evidence, rules, executor,
            account_fingerprint=receipt.account_fingerprint, now_ms=current)
        report_path = session_dir / f"{plan.plan_id}-latest-report.json"
        return DesktopMcpRehearsalSession(
            plan, receipt, evidence, executor, lock, preview, report_path)
    except Exception:
        lock.release()
        raise
