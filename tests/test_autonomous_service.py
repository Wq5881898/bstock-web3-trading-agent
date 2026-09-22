from types import SimpleNamespace

from bstock_web3.autonomous_service import SpotServiceCycle
from bstock_web3.autonomous_session import SessionPhase
from bstock_web3.unattended_spot import UnattendedResult


class FakeSession:
    phase = SessionPhase.RUNNING
    def request_stop(self):
        self.phase = SessionPhase.STOPPING


class FakeRunner:
    def __init__(self):
        self.ticks = 0
        self.stops = 0
        self.fail_read = True
        self.stop_ready = False
        self.reconciler = SimpleNamespace()

    def tick(self, *, now_ms):
        self.ticks += 1
        if self.fail_read:
            raise ConnectionError("signed URL must not appear in status")
        return UnattendedResult("HOLD")

    def stop(self, *, now_ms):
        self.stops += 1
        if self.fail_read:
            raise ConnectionError("private server error")
        return self.stop_ready


def test_disconnect_then_stop_remains_stop_only(tmp_path):
    session, runner = FakeSession(), FakeRunner()
    service = SpotServiceCycle(session, runner, tmp_path)
    first = service.step(now_ms=100)
    assert first == {"event": "READ_OR_EXECUTION_ERROR",
                     "error_type": "ConnectionError", "phase": "RUNNING"}
    assert "signed" not in str(first)
    service.stop_file.write_text("requested\n", encoding="ascii")
    second = service.step(now_ms=101)
    assert second["phase"] == "STOPPING"
    assert runner.ticks == 1 and runner.stops == 1
    runner.fail_read = False
    assert service.step(now_ms=102)["event"] == "STOPPING"
    runner.stop_ready = True
    assert service.step(now_ms=103)["event"] == "STOPPED"
    assert not service.stop_file.exists()
    assert runner.ticks == 1  # no new signal after STOPPING


def test_stale_resume_request_does_not_apply_to_future_latch(tmp_path):
    session, runner = FakeSession(), FakeRunner()
    runner.fail_read = False
    service = SpotServiceCycle(session, runner, tmp_path)
    service.resume_file.write_text("requested\n", encoding="ascii")
    assert service.step(now_ms=100)["event"] == "HOLD"
    assert not service.resume_file.exists()
