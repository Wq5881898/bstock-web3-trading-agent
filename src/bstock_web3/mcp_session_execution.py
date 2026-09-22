"""File-safe bridge from a durable MCP session to confirmed host handoff."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .automation_policy import AutomationPolicy
from .execution_lock import ExecutionLock
from .execution_safety import (ExecutionJournal, ExecutionPhase,
                               McpReconciliationEvidence)
from .mcp_bridge import (McpAccountBinding, load_mcp_plan)
from .mcp_confirmed import ConfirmedSpotExecutor, SpotMarketRules
from .mcp_execution_handoff import (build_submission_ticket,
                                    load_submission_ticket,
                                    prepare_plan_preview,
                                    write_submission_ticket)
from .mcp_execution_result import (import_execution_result,
                                   load_execution_result_receipt)
from .mcp_session import (McpSessionPhase, McpTradingSession)
from .spot_accounting import SpotFillLedger


class McpSessionExecution:
    """Coordinates files and durable state without owning an MCP transport."""

    def __init__(self, session: McpTradingSession,
                 account: McpAccountBinding, *, journal_path: Path,
                 ticket_dir: Path):
        if not isinstance(session, McpTradingSession):
            raise ValueError("Invalid MCP trading session")
        if (not isinstance(account, McpAccountBinding)
                or account.fingerprint is None
                or account.account_ref != session.binding.account_ref
                or account.fingerprint != session.binding.account_fingerprint):
            raise ValueError("MCP execution account binding mismatch")
        self.session = session
        self.account = account
        self.journal_path = Path(journal_path)
        self.ticket_dir = Path(ticket_dir)
        self.lock = ExecutionLock(
            self.journal_path.with_suffix(self.journal_path.suffix + ".lock"))
        self.journal: ExecutionJournal | None = None
        self.executor: ConfirmedSpotExecutor | None = None
        self._plan = None
        self._preview = None

    def __enter__(self):
        if not self.lock.acquire():
            raise RuntimeError("Another MCP execution coordinator is active")
        try:
            self.journal = ExecutionJournal(self.journal_path, self.lock)
            self.executor = ConfirmedSpotExecutor(
                self._no_network_caller, self.journal, self.session.policy)
        except Exception:
            self.lock.release()
            raise
        return self

    def __exit__(self, *args):
        self.executor = None
        self.journal = None
        self.lock.release()

    @staticmethod
    def _no_network_caller(*_):
        raise RuntimeError("File handoff cannot call MCP directly")

    def prepare_preview(self, evidence: McpReconciliationEvidence,
                        rules: SpotMarketRules, *, now_ms: int):
        self._require_open()
        pending = self.session.pending
        if (self.session.phase != McpSessionPhase.WAITING_CONFIRMATION
                or not pending or pending.get("status") != "READY"):
            raise RuntimeError("Session has no candidate awaiting confirmation")
        plan_path = Path(pending["plan_path"])
        plan = load_mcp_plan(plan_path)
        if plan.plan_id != pending["plan_id"]:
            raise ValueError("Session candidate identity changed")
        preview = prepare_plan_preview(
            plan, evidence, rules, self.executor,
            account_fingerprint=self.account.fingerprint, now_ms=now_ms)
        self._plan, self._preview = plan, preview
        return dict(preview)

    def confirm_to_ticket(self, confirmation: str,
                          evidence: McpReconciliationEvidence, *, now_ms: int):
        self._require_open()
        if self._plan is None or self._preview is None:
            raise RuntimeError("Prepare a fresh preview first")
        submission = self.executor.begin_submission(
            confirmation, evidence, now_ms=now_ms)
        try:
            self.session.begin_confirmation(
                plan_id=self._plan.plan_id, now_ms=now_ms)
            now = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
            ticket = build_submission_ticket(
                self._plan, submission,
                account_fingerprint=self.account.fingerprint, now=now)
            path = self.ticket_dir / f"ticket-{ticket.execution_fingerprint}.json"
            if path.exists():
                raise RuntimeError("Submission ticket already exists")
            write_submission_ticket(ticket, path)
            self.session.record_submission_ticket(
                plan_id=ticket.plan_id,
                execution_fingerprint=ticket.execution_fingerprint,
                ticket_path=path, now_ms=now_ms)
            return ticket, path.resolve()
        except Exception:
            try:
                self.executor.mark_submission_unknown(
                    submission.fingerprint, now_ms=now_ms)
            finally:
                self.session.enter_recovery(
                    reason="submission_ticket_interrupted", now_ms=now_ms)
            raise

    def import_result(self, receipt_path: Path, fill_ledger: SpotFillLedger | None,
                      *, daily_equity_loss: Decimal, now_ms: int):
        self._require_open()
        pending = self.session.pending
        if (self.session.phase not in {McpSessionPhase.WAITING_RESULT,
                                       McpSessionPhase.STOPPING}
                or not pending or pending.get("status") != "TICKET_READY"):
            raise RuntimeError("Session is not awaiting a host result")
        ticket = load_submission_ticket(Path(pending["ticket_path"]))
        if ticket.execution_fingerprint != pending["execution_fingerprint"]:
            raise ValueError("Session submission ticket identity changed")
        now = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
        receipt = load_execution_result_receipt(
            ticket, self.account, Path(receipt_path), now=now)
        imported = import_execution_result(
            receipt, ticket, self.executor, fill_ledger,
            daily_equity_loss=daily_equity_loss, now_ms=now_ms)
        if imported.phase == ExecutionPhase.UNKNOWN:
            self.session.record_execution_outcome(
                outcome="UNKNOWN", evidence=None, now_ms=now_ms)
        elif imported.phase in {ExecutionPhase.FILLED, ExecutionPhase.REJECTED}:
            self.session.record_execution_outcome(
                outcome=imported.phase.value, evidence=imported.evidence,
                now_ms=now_ms)
        else:
            raise RuntimeError("Host result is not terminal")
        return imported

    def _require_open(self):
        if (self.executor is None or self.journal is None
                or not self.lock.held):
            raise RuntimeError("MCP execution coordinator is not open")
