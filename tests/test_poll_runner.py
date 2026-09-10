from threading import Event, get_ident
import pytest
from bstock_web3.poll_runner import PollRunner


def test_single_flight_engine_owned_by_worker_and_stop():
    entered, release = Event(), Event()
    ids = []
    class Engine:
        def __init__(self): ids.append(get_ident())
        def evaluate_once(self):
            ids.append(get_ident())
            entered.set()
            assert release.wait(2)
            return "done"
    runner = PollRunner(Engine)
    try:
        assert runner.submit()
        assert entered.wait(2)
        assert not runner.submit()
        assert runner.take() is None
        runner.close()
        assert not runner.submit()
        release.set()
        assert runner.future.result(timeout=2) == "done"
        assert runner.take().result() == "done"
        assert ids[0] == ids[1] != get_ident()
    finally:
        release.set()
        runner.close()


def test_error_does_not_leave_poll_permanently_busy():
    class Engine:
        def evaluate_once(self): raise ValueError("fixture")
    runner = PollRunner(Engine)
    try:
        runner.submit()
        with pytest.raises(ValueError): runner.future.result(timeout=2)
        with pytest.raises(ValueError): runner.take().result()
        assert runner.submit()
        with pytest.raises(ValueError): runner.future.result(timeout=2)
    finally:
        runner.close()
