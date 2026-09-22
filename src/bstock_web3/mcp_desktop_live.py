"""Desktop live MCP file handoff; never performs a network or MCP call."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .automation_policy import AutomationPolicy, AutomationPolicyConfig
from .execution_lock import ExecutionLock
from .execution_safety import ExecutionJournal, ExecutionPhase
from .mcp_bridge import load_mcp_plan
from .mcp_confirmed import ConfirmedSpotExecutor, SpotMarketRules
from .mcp_execution_handoff import (build_submission_ticket,
                                    prepare_plan_preview,
                                    write_submission_ticket)
from .mcp_execution_result import (import_execution_result,
                                   load_execution_result_receipt)
from .mcp_host_receipt import VerifiedSpotHostReceipt
from .mcp_spot_snapshot import LocalRiskMetrics
from .spot_accounting import SpotFillLedger


class DesktopMcpLiveHandoff:
    """Own one confirmation, ticket and result import until safely closed."""

    def __init__(self, plan, receipt, evidence, executor, lock, preview,
                 ticket_dir: Path, ledger_path: Path,
                 daily_equity_loss: Decimal):
        self.plan = plan
        self.receipt = receipt
        self.evidence = evidence
        self.executor = executor
        self.lock = lock
        self.preview = preview
        self.ticket_dir = ticket_dir
        self.ledger_path = ledger_path
        self.daily_equity_loss = daily_equity_loss
        self.ticket = None
        self.ticket_path = None
        self.result_path = None
        self.closed = False

    def confirm(self, phrase: str, *, now_ms: int | None = None):
        if self.closed or self.ticket is not None:
            raise RuntimeError("MCP live handoff is not awaiting confirmation")
        current = now_ms if now_ms is not None else int(
            datetime.now(timezone.utc).timestamp() * 1000)
        submission = self.executor.begin_submission(
            phrase, self.evidence, now_ms=current)
        try:
            now = datetime.fromtimestamp(current / 1000, timezone.utc)
            ticket = build_submission_ticket(
                self.plan, submission,
                account_fingerprint=self.receipt.account_fingerprint,
                now=now)
            path = self.ticket_dir / f"ticket-{ticket.execution_fingerprint}.json"
            if path.exists():
                raise RuntimeError("MCP submission ticket already exists")
            write_submission_ticket(ticket, path)
            self.ticket = ticket
            self.ticket_path = path.resolve()
            self.result_path = self.ticket_dir / \
                f"result-{ticket.execution_fingerprint}.json"
            return self.ticket_path, ticket, self.result_path.resolve()
        except Exception:
            try:
                self.executor.mark_submission_unknown(
                    submission.fingerprint, now_ms=current)
            finally:
                self.close()
            raise

    def import_result(self, *, now_ms: int | None = None):
        if self.closed or self.ticket is None or self.result_path is None:
            raise RuntimeError("MCP live handoff has no submission ticket")
        current = now_ms if now_ms is not None else int(
            datetime.now(timezone.utc).timestamp() * 1000)
        now = datetime.fromtimestamp(current / 1000, timezone.utc)
        receipt = load_execution_result_receipt(
            self.ticket, self.receipt.binding, self.result_path, now=now)
        ledger = None
        if receipt.outcome == "TERMINAL":
            ledger = SpotFillLedger(
                self.ledger_path, account_ref=self.receipt.account_ref,
                symbol=self.receipt.symbol,
                base_asset=self.receipt.base_asset,
                quote_asset=self.receipt.quote_asset)
        try:
            return import_execution_result(
                receipt, self.ticket, self.executor, ledger,
                daily_equity_loss=self.daily_equity_loss, now_ms=current)
        finally:
            self.close()

    def cancel(self):
        if self.closed:
            return
        if self.ticket is not None:
            raise RuntimeError("Confirmed ticket cannot be cancelled; import result")
        self.executor.cancel_preview()
        self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            self.lock.release()


def prepare_desktop_live_handoff(
    plan_path: Path,
    receipt: VerifiedSpotHostReceipt,
    runtime_dir: Path,
    *,
    daily_equity_loss: Decimal = Decimal("0"),
    now_ms: int | None = None,
) -> DesktopMcpLiveHandoff:
    """Prepare one real, user-confirmed file handoff without dispatching it."""
    if (not isinstance(plan_path, Path)
            or not isinstance(receipt, VerifiedSpotHostReceipt)
            or not isinstance(runtime_dir, Path)
            or not isinstance(daily_equity_loss, Decimal)
            or not daily_equity_loss.is_finite() or daily_equity_loss < 0):
        raise ValueError("Invalid MCP desktop live input")
    current = now_ms if now_ms is not None else int(
        datetime.now(timezone.utc).timestamp() * 1000)
    plan = load_mcp_plan(plan_path)
    if plan.symbol != receipt.symbol:
        raise ValueError("MCP live plan and receipt symbol mismatch")
    risk_day = datetime.fromtimestamp(
        receipt.observed_at_ms / 1000, timezone.utc).date().isoformat()
    evidence = receipt.to_evidence(
        risk_day=risk_day, risk=LocalRiskMetrics(daily_equity_loss))
    rules = SpotMarketRules.from_exchange_info(
        receipt.tool_results["spot.exchangeInfo"], plan.symbol)
    live_dir = runtime_dir / "live"
    journal_path = live_dir / f"{plan.signal_fingerprint}-execution.json"
    lock = ExecutionLock(journal_path.with_suffix(".json.lock"))
    lock.require()
    try:
        budget = Decimal(plan.order_arguments.get("quoteOrderQty", "100"))
        policy = AutomationPolicy(AutomationPolicyConfig(
            order_budget_quote=budget, cumulative_loss_limit=Decimal("10"),
            max_position_cost=Decimal("100000"), max_daily_entries=20,
            max_consecutive_losses=3, entry_cooldown_seconds=60,
            snapshot_max_age_seconds=15))
        executor = ConfirmedSpotExecutor(
            lambda *_: (_ for _ in ()).throw(
                AssertionError("desktop file handoff cannot call MCP")),
            ExecutionJournal(journal_path, lock), policy)
        preview = prepare_plan_preview(
            plan, evidence, rules, executor,
            account_fingerprint=receipt.account_fingerprint, now_ms=current)
        return DesktopMcpLiveHandoff(
            plan, receipt, evidence, executor, lock, preview, live_dir,
            live_dir / f"{receipt.symbol.lower()}-fills.json",
            daily_equity_loss)
    except Exception:
        lock.release()
        raise
