"""Durable, no-per-order-prompt Spot execution for an explicitly started session.

The injected caller can be a fake in tests or the narrow Binance Spot API.
No MCP write tool is called from this module.
"""
from __future__ import annotations

from dataclasses import dataclass

from .automation_policy import AutomationPolicy
from .execution_contract import OrderIntent
from .execution_safety import (ExecutionArming, ExecutionJournal, ExecutionMode,
    ExecutionPhase, McpReconciliationEvidence, prepare_safe_execution)
from .mcp_confirmed import ConfirmedSpotExecutor, SpotMarketRules


@dataclass(frozen=True)
class UnattendedResult:
    outcome: str
    reasons: tuple[str, ...] = ()
    fingerprint: str | None = None
    order_status: str | None = None


class UnattendedSpotExecutor:
    """One order per fresh strategy event, with UNKNOWN lookup-only recovery."""

    def __init__(self, api, journal: ExecutionJournal,
                 policy: AutomationPolicy, *, account_ref: str, symbol: str):
        self.api, self.journal, self.policy = api, journal, policy
        self.account_ref, self.symbol = account_ref, symbol
        self._results = ConfirmedSpotExecutor(self._lookup, journal, policy)

    def _lookup(self, name, arguments):
        if name != "spot.getOrder":
            raise ValueError("Only read-only order lookup is available")
        return self.api.get_order(arguments["symbol"], arguments["origClientOrderId"])

    def execute(self, intent: OrderIntent, evidence: McpReconciliationEvidence,
                rules: SpotMarketRules, *, signal_key: str, now_ms: int):
        if not self.journal.execution_lock_held:
            raise RuntimeError("Execution lock required")
        if evidence.account_ref != self.account_ref or evidence.symbol != self.symbol:
            raise RuntimeError("Session account or symbol binding changed")
        if any(row.phase in (ExecutionPhase.SUBMITTING, ExecutionPhase.SUBMITTED,
                             ExecutionPhase.UNKNOWN) for row in self.journal.records()):
            return UnattendedResult("BLOCKED", ("unresolved_execution",))
        if any(row.account_ref == self.account_ref and row.symbol == self.symbol
               and row.signal_key == signal_key for row in self.journal.records()):
            return UnattendedResult("BLOCKED", ("duplicate_strategy_event",))
        snapshot = evidence.to_snapshot()
        # Validate all amount and venue rules before reserving the signal.
        rules.arguments(intent, snapshot, self.policy.config.order_budget_quote, "preview")
        arming = ExecutionArming(ExecutionMode.UNATTENDED, self.account_ref,
            self.symbol, snapshot.product, now_ms + 15_000)
        prepared = prepare_safe_execution(intent, evidence, self.policy, arming,
            self.journal, signal_key=signal_key, now_ms=now_ms)
        if not prepared.decision.allowed:
            return UnattendedResult("BLOCKED", prepared.decision.reasons,
                                    prepared.record.fingerprint if prepared.record else None)
        record = prepared.record
        arguments = rules.arguments(intent, snapshot,
            self.policy.config.order_budget_quote, record.client_order_id)
        self.journal.transition(record.fingerprint, ExecutionPhase.SUBMITTING,
                                now_ms=now_ms)
        try:
            payload = self.api.market_order(arguments)
            result = self._results.accept_submission_result(
                record.fingerprint, payload, now_ms=now_ms)
        except Exception:
            self._results.mark_submission_unknown(record.fingerprint,
                                                   now_ms=now_ms)
            return UnattendedResult("UNKNOWN", ("lookup_only",), record.fingerprint)
        return UnattendedResult("ORDER", (), record.fingerprint, result.status)

    def reconcile_unresolved(self, *, now_ms: int):
        """Query every unresolved client ID; never submit an order here."""
        outcomes = []
        for row in self.journal.records():
            if row.phase not in (ExecutionPhase.SUBMITTING, ExecutionPhase.SUBMITTED,
                                 ExecutionPhase.UNKNOWN):
                continue
            try:
                result = self._results.reconcile(row.fingerprint, now_ms=now_ms)
            except RuntimeError:
                outcomes.append(UnattendedResult("UNKNOWN", ("lookup_only",),
                                                  row.fingerprint))
            else:
                outcomes.append(UnattendedResult("ORDER", (), row.fingerprint,
                                                  result.status))
        return tuple(outcomes)
