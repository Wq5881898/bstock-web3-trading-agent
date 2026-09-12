"""Small cross-process lock used by a future unattended execution host."""
from __future__ import annotations

from pathlib import Path
import os


class ExecutionLockUnavailable(RuntimeError):
    pass


class ExecutionLock:
    """Non-blocking OS lock held for the lifetime of one execution owner."""

    def __init__(self, path: Path):
        if not isinstance(path, Path) or not path.name:
            raise ValueError("Invalid execution lock path")
        self.path = path
        self._handle = None

    @property
    def held(self):
        return self._handle is not None

    def acquire(self):
        if self.held:
            return True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            self._lock(handle)
        except OSError:
            try:
                handle.close()
            except (NameError, OSError):
                pass
            return False
        self._handle = handle
        return True

    def require(self):
        if not self.acquire():
            raise ExecutionLockUnavailable(
                "Execution state is owned by another process")
        return self

    def release(self):
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            self._unlock(handle)
        finally:
            handle.close()

    def __enter__(self):
        return self.require()

    def __exit__(self, exc_type, exc, traceback):
        self.release()

    @staticmethod
    def _lock(handle):
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(handle):
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def __del__(self):
        try:
            self.release()
        except OSError:
            pass
