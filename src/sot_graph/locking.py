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
import threading
import time
from dataclasses import dataclass
from typing import Dict

__all__ = ["LockBusy", "LockTimeoutError", "WriteLock"]

@dataclass
class _HeldLock:
    fd: int
    owner_pid: int
    owner_thread: int
    depth: int = 1


_REGISTRY_GUARD = threading.RLock()
_HELD_LOCKS: Dict[str, _HeldLock] = {}
_REGISTRY_PID = os.getpid()


def _reset_registry_after_fork() -> None:
    """Drop inherited registry state after ``fork`` without touching parents."""
    global _REGISTRY_PID
    pid = os.getpid()
    if _REGISTRY_PID == pid:
        return
    for held in _HELD_LOCKS.values():
        try:
            os.close(held.fd)
        except OSError:
            pass
    _HELD_LOCKS.clear()
    _REGISTRY_PID = pid

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
    """Bounded advisory lock re-entrant for one owning thread."""

    def __init__(self, path: str, timeout_ms: int = 5_000) -> None:
        if timeout_ms < 0:
            raise ValueError("timeout_ms must be non-negative")
        self.path = os.path.abspath(path)
        self.timeout_ms = int(timeout_ms)
        self._fd: int | None = None
        self._acquisitions = 0
        self._registry_key = os.path.realpath(self.path)
        self._owner_pid: int | None = None
        self._owner_thread: int | None = None

    def _fd_guards_live_path(self, fd: int) -> bool:
        """True when ``fd`` still names the file currently at ``self.path``.

        A lock file deleted or recreated between ``open`` and ``flock``
        leaves the fd guarding an orphaned inode: acquiring it "succeeds"
        while another writer may already hold the replacement file.
        """
        try:
            fd_stat = os.fstat(fd)
            if fd_stat.st_nlink < 1:
                return False
            return os.stat(self.path).st_ino == fd_stat.st_ino
        except OSError:
            # Path vanished between open and verify — contend again.
            return False

    def acquire(self) -> None:
        """Acquire the lock, nesting when this thread already owns it."""
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        key = os.path.realpath(self.path)
        pid = os.getpid()
        thread_id = threading.get_ident()
        deadline = time.monotonic() + self.timeout_ms / 1000.0

        while True:
            with _REGISTRY_GUARD:
                _reset_registry_after_fork()
                held = _HELD_LOCKS.get(key)
                if held is not None:
                    if held.owner_pid == pid and held.owner_thread == thread_id:
                        held.depth += 1
                        self._registry_key = key
                        self._owner_pid = pid
                        self._owner_thread = thread_id
                        self._acquisitions += 1
                        self._fd = held.fd
                        return
                else:
                    fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
                    try:
                        if _try_acquire(fd) and self._fd_guards_live_path(fd):
                            _HELD_LOCKS[key] = _HeldLock(fd, pid, thread_id)
                            self._registry_key = key
                            self._owner_pid = pid
                            self._owner_thread = thread_id
                            self._acquisitions = 1
                            self._fd = fd
                            return
                        # The file we opened was deleted or replaced while we
                        # contended (git clean -x, rm -rf .sot): flocking the
                        # orphaned inode would fork the lock into two
                        # independent files — two writers at once. Release and
                        # contend again on the live path.
                        _release(fd)
                    except BaseException:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                        raise
                    try:
                        os.close(fd)
                    except OSError:
                        pass

            if time.monotonic() >= deadline:
                raise LockTimeoutError(
                    f"Could not acquire write lock on {self.path} within {self.timeout_ms}ms"
                )
            time.sleep(_RETRY_INTERVAL_S)

    def release(self) -> None:
        """Release one nesting level and close the shared descriptor at zero."""
        if self._acquisitions <= 0:
            return
        pid = os.getpid()
        thread_id = threading.get_ident()
        with _REGISTRY_GUARD:
            _reset_registry_after_fork()
            held = _HELD_LOCKS.get(self._registry_key)
            if held is None:
                # A forked child may inherit a lock object after its copied
                # descriptor was closed while resetting the local registry.
                self._acquisitions = 0
                self._fd = None
                return
            if held.owner_pid != pid or held.owner_thread != thread_id:
                raise RuntimeError(
                    "write lock must be released by its owning process/thread"
                )
            self._acquisitions -= 1
            held.depth -= 1
            self._fd = held.fd if self._acquisitions else None
            if held.depth > 0:
                return
            _HELD_LOCKS.pop(self._registry_key, None)
            _release(held.fd)
            try:
                os.close(held.fd)
            except OSError:
                pass
            self._owner_pid = None
            self._owner_thread = None

    def __enter__(self) -> "WriteLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
