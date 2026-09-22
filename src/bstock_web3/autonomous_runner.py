"""One-cycle orchestration; hosts may schedule it continuously and stop it."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .autonomous_session import SessionPhase
from .unattended_spot import UnattendedResult


def _buy_cost_block(signal, snapshot):
    """Conservative round-trip taker + side fees and current spread gate."""
    try:
        rates = snapshot.commission
        buy_fee = sell_fee = Decimal("0")
        for name in ("standardCommission", "specialCommission", "taxCommission"):
            section = rates[name]
            taker = Decimal(str(section["taker"]))
            buyer = Decimal(str(section["buyer"]))
            seller = Decimal(str(section["seller"]))
            if any(not value.is_finite() or value < 0 for value in (taker, buyer, seller)):
                raise ValueError
            buy_fee += taker + buyer
            sell_fee += taker + seller
        bid = Decimal(str(snapshot.book["bidPrice"]))
        ask = Decimal(str(snapshot.book["askPrice"]))
        edge = Decimal(str(signal.expected_edge))
        if (not edge.is_finite() or edge <= 0 or bid <= 0 or ask < bid):
            raise ValueError
        spread = (ask - bid) / ask
        return edge <= buy_fee + sell_fee + spread
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return True


class AutonomousSpotRunner:
    def __init__(self, session, reconciler, signal_source):
        self.session, self.reconciler = session, reconciler
        self.signal_source = signal_source

    def start(self, *, now_ms: int):
        # Baseline and history must be accepted before the execution session arms.
        snapshot = self.reconciler.initialize(now_ms=now_ms)
        if not snapshot.evidence.to_snapshot().reconciled:
            raise RuntimeError("Initial Spot account is not reconciled")
        self.session.start()
        return snapshot

    def tick(self, *, now_ms: int):
        if self.session.phase not in (SessionPhase.RUNNING, SessionPhase.BUY_PAUSED):
            return UnattendedResult("BLOCKED", ("session_not_running",))
        unresolved = self.session.executor.reconcile_unresolved(now_ms=now_ms)
        if any(result.outcome == "UNKNOWN" or result.order_status in
               ("NEW", "PARTIALLY_FILLED") for result in unresolved):
            return UnattendedResult("BLOCKED", ("unresolved_execution",))
        snapshot = self.reconciler.read(now_ms=now_ms)
        self.session.observe_risk(snapshot.evidence, now_ms=now_ms)
        signal, key = self.signal_source.evaluate(snapshot.evidence, now_ms=now_ms)
        if signal.action == "hold" or key is None:
            return UnattendedResult("HOLD")
        if signal.action == "buy" and _buy_cost_block(signal, snapshot):
            return UnattendedResult("BLOCKED", ("expected_edge_below_spot_cost",))
        return self.session.process(signal, snapshot.evidence, snapshot.rules,
            signal_key=key, now_ms=now_ms,
            filled_order_ids=snapshot.filled_order_ids)

    def stop(self, *, now_ms: int):
        self.session.request_stop()
        snapshot = self.reconciler.read(now_ms=now_ms)
        return self.session.finish_stop(now_ms=now_ms,
            evidence=snapshot.evidence,
            filled_order_ids=snapshot.filled_order_ids)
