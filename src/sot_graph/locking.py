"""
sot_graph.locking — Cross-platform, non-truncating write lock.

The 2-Phase Publication gate serializes every SQLite mutation behind one
stable project lock file (``.sot/write.lock``). The lock file is created once
with O_CREAT|O_RDWR and is never truncated or unlinked during normal
execution: re-creating it would hand out two "valid" locks to different
processes on POSIX systems that bind ``flock`` to the file inode.

Backends are stdlib-only: ``fcntl`` on POSIX, ``msvcrt`` on Windows. Writers
acquire with a bounded timeout; on deadline the caller receives
:class:`LockBusy` and must back off (never block indefinitely).
"""

import errno
import os
import time

__all__ = ["LockBusy", "LockTimeoutError", "WriteLock"]

_RETRY_INTERVAL_S = 0.025


class LockBusy(RuntimeError):
    """Raised when the write lock cannot be acquired within its deadline."""


class LockTimeoutError(LockBusy):
    """Alias/subclass for lock acquisition timeout."""


if os.name == "nt":  # pragma: no cover - exercised only on Windows
    import msvcrt

    def _try_acquire(fd: int) -> bool:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return False
            raise

    def _release(fd: int) -> None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def _try_acquire(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise

    def _release(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


class WriteLock:
    """Bounded, re-entrant-per-process advisory file lock."""

    def __init__(self, path: str, timeout_ms: int = 5_000) -> None:
        if timeout_ms < 0:
            raise ValueError("timeout_ms must be non-negative")
        self.path = os.path.abspath(path)
        self.timeout_ms = int(timeout_ms)
        self._fd: int | None = None

    def acquire(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # O_CREAT|O_RDWR without O_TRUNC: the lock file must keep its inode
        # for the lifetime of the project or stale holders go unnoticed.
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + self.timeout_ms / 1000.0
        try:
            while not _try_acquire(fd):
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(
                        f"Could not acquire write lock on {self.path} within {self.timeout_ms}ms"
                    )
                time.sleep(_RETRY_INTERVAL_S)
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        _release(self._fd)
        os.close(self._fd)
        self._fd = None

    def __enter__(self) -> "WriteLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
