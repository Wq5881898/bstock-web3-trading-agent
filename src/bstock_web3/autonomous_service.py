"""Deterministic one-cycle service control for a foreground Spot runner."""
from __future__ import annotations

from pathlib import Path

from .autonomous_session import SessionPhase


class SpotServiceCycle:
    def __init__(self, session, runner, directory: Path):
        self.session = session
        self.runner = runner
        self.stop_file = Path(directory) / "stop.request"
        self.resume_file = Path(directory) / "resume.request"

    def step(self, *, now_ms: int):
        if self.stop_file.exists():
            self.session.request_stop()
        try:
            if self.session.phase == SessionPhase.STOPPING:
                if self.runner.stop(now_ms=now_ms):
                    self.stop_file.unlink(missing_ok=True)
                    return {"event": "STOPPED"}
                return {"event": "STOPPING"}
            if self.session.phase not in (SessionPhase.RUNNING, SessionPhase.BUY_PAUSED):
                return {"event": "BLOCKED", "reason": "session_not_running"}
            if self.resume_file.exists():
                if self.session.phase == SessionPhase.BUY_PAUSED:
                    snapshot = self.runner.reconciler.read(now_ms=now_ms)
                    allowed = self.session.resume(snapshot.evidence, now_ms=now_ms,
                        filled_order_ids=snapshot.filled_order_ids)
                    self.resume_file.unlink(missing_ok=True)
                    if not allowed:
                        return {"event": "RESUME_BLOCKED"}
                else:
                    # A stale resume request must not unpause a later risk latch.
                    self.resume_file.unlink(missing_ok=True)
            result = self.runner.tick(now_ms=now_ms)
            return {"event": result.outcome, "reasons": result.reasons,
                "order_status": result.order_status,
                "phase": self.session.phase.value}
        except Exception as exc:
            # Never format a signed URL, credential or remote error body.
            return {"event": "READ_OR_EXECUTION_ERROR",
                "error_type": type(exc).__name__,
                "phase": self.session.phase.value}
