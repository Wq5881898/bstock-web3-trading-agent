import pytest

from bstock_web3.execution_lock import (ExecutionLock,
    ExecutionLockUnavailable)


def test_only_one_owner_can_hold_execution_lock(tmp_path):
    first = ExecutionLock(tmp_path / "account.lock")
    second = ExecutionLock(tmp_path / "account.lock")
    assert first.acquire()
    assert not second.acquire()
    with pytest.raises(ExecutionLockUnavailable):
        second.require()
    first.release()
    assert second.acquire()
    second.release()


def test_execution_lock_context_releases_on_exception(tmp_path):
    lock = ExecutionLock(tmp_path / "account.lock")
    with pytest.raises(RuntimeError):
        with lock:
            assert lock.held
            raise RuntimeError("fixture")
    assert not lock.held
    with ExecutionLock(tmp_path / "account.lock") as replacement:
        assert replacement.held
