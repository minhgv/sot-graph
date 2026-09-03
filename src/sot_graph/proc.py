"""
sot_graph.proc — Unified bounded subprocess runner.

Single entry point :func:`run_command` executes an argv list (never a shell)
and always returns a :class:`RunResult`; spawn failures and timeouts are
reported as data instead of raised exceptions, so provider adapters can treat
"command did not work" uniformly.

- ``timeout_seconds`` kills the child's whole process TREE on deadline
  (``timed_out=True``): the child is spawned in its own session and the
  group is SIGKILLed (POSIX), or assigned to a Job Object created with
  ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` and terminated as one unit
  (Windows). Grandchildren never outlive the deadline on either platform.
- Output is drained incrementally from both pipes with a hard per-stream
  byte cap: the moment a stream exceeds ``max_output_bytes`` the process
  group is SIGKILLed mid-stream (``truncated=True``). Memory stays bounded
  regardless of how much the child produces.
"""
from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

__all__ = ["RunResult", "run_command"]

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_OUTPUT_BYTES = 8 * 1024 * 1024

#: Drain chunk size for the pipe reader threads.
_READ_CHUNK = 65536

#: Main-loop poll interval while waiting for exit / cap / deadline.
_POLL_INTERVAL_SECONDS = 0.01

#: Grace period to join reader threads after the child died (pipes EOF).
_JOIN_TIMEOUT_SECONDS = 5.0

_WIN32 = sys.platform == "win32"

# Windows has no killpg: instead the child is assigned to a Job Object
# created with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, so terminating (or
# closing the handle of) the job reaps every grandchild at once — the
# moral equivalent of SIGKILLing the POSIX session. Outside win32 (or on
# any plumbing failure) the helpers no-op / return None so the kill path
# falls back instead of crashing the supervisor.
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),  # ULONG_PTR
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32():
    windll = getattr(ctypes, "windll", None)
    return getattr(windll, "kernel32", None) if windll is not None else None


def _open_kill_on_close_job() -> int | None:
    """Create a Job Object whose members die with the handle, or None."""
    if not _WIN32:
        return None
    kernel32 = _kernel32()
    if kernel32 is None:
        return None
    try:
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        ok = kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(job)
            return None
        return int(job)
    except Exception:
        return None


def _assign_job(job: int, proc: subprocess.Popen) -> bool:
    kernel32 = _kernel32()
    if kernel32 is None:
        return False
    try:
        handle = getattr(proc, "_handle", None)
        if not handle:
            return False
        return bool(kernel32.AssignProcessToJobObject(job, handle))
    except Exception:
        return False


def _terminate_job(job: int) -> bool:
    kernel32 = _kernel32()
    if kernel32 is None:
        return False
    try:
        return bool(kernel32.TerminateJobObject(job, 1))
    except Exception:
        return False


def _close_job_handle(job: int) -> None:
    kernel32 = _kernel32()
    if kernel32 is None:
        return
    try:
        kernel32.CloseHandle(job)
    except Exception:
        pass


@dataclass(frozen=True)
class RunResult:
    """Outcome of one bounded subprocess execution."""

    argv: tuple[str, ...]
    returncode: int | None  # None when the process could not be spawned (or was killed on timeout)
    stdout: str  # UTF-8 decoded, errors="replace"
    stderr: str  # UTF-8 decoded, errors="replace"
    timed_out: bool  # True when the deadline expired and the process was killed
    truncated: bool  # True when output exceeded max_output_bytes and was cut
    error: str | None  # Short description of FileNotFoundError/OSError


def _short_error(exc: BaseException) -> str:
    text = str(exc).strip()
    name = type(exc).__name__
    return f"{name}: {text}" if text else name


def _kill_process_group(
    proc: subprocess.Popen, job: int | None = None
) -> None:
    """Terminate the child's whole process tree, best effort on every platform.

    Preference order: Windows Job Object terminate → POSIX group SIGKILL →
    Windows ``taskkill /T`` fallback (job denied or assignment failed) →
    bare child kill.
    """
    if job is not None and _terminate_job(job):
        return
    if hasattr(os, "killpg") and hasattr(os, "getpgid"):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass  # already gone or unreachable; fall through to proc.kill()
    if _WIN32 and proc.poll() is None:
        try:
            subprocess.run(  # noqa: S603,S607 - builtin taskkill, caller-controlled PID
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
                check=False,
            )
            return
        except OSError:
            pass
    proc.kill()


class _StreamReader:
    """Drain one pipe into a capped buffer, signaling overflow immediately.

    The reader never stores more than ``cap`` bytes; once the stream has
    PRODUCED more than ``cap`` bytes it sets ``overflow`` so the supervisor
    can kill the process group mid-stream.
    """

    def __init__(self, stream, cap: int, overflow: threading.Event) -> None:
        self._stream = stream
        self._cap = cap
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._overflow = overflow
        self.exceeded_cap = False  # stream produced strictly more than cap

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._drain, daemon=True)
        thread.start()
        return thread

    def _drain(self) -> None:
        try:
            read1 = self._stream.read1  # BufferedReader; raises AttributeError on raw pipes
        except AttributeError:
            read1 = self._stream.read
        try:
            while True:
                try:
                    chunk = read1(_READ_CHUNK)
                except (OSError, ValueError):
                    return  # pipe closed or process gone
                if not chunk:
                    return  # EOF
                with self._lock:
                    room = self._cap - len(self._buf)
                    if room > 0:
                        self._buf.extend(chunk[:room])
                    if len(chunk) > room:
                        self.exceeded_cap = True
                        self._overflow.set()
                        return  # cap reached; supervisor kills the process
        except Exception:  # pragma: no cover - reader must never crash the supervisor
            return

    def data(self) -> bytes:
        with self._lock:
            return bytes(self._buf)


def run_command(
    argv: list[str] | tuple[str, ...],
    *,
    cwd: str | os.PathLike[str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    env_extra: dict[str, str] | None = None,
) -> RunResult:
    """Run ``argv`` without a shell and never raise on spawn/timeout failure.

    Args:
        argv: Argument vector executed directly (no shell interpolation).
        cwd: Working directory; may contain spaces or non-ASCII characters.
        timeout_seconds: Wall-clock budget; expiry kills the process group.
        max_output_bytes: Hard per-stream byte cap enforced WHILE streaming;
            overflow kills the process group immediately (``truncated=True``).
        env_extra: Extra environment variables merged over ``os.environ``.

    Returns:
        A :class:`RunResult`. ``returncode is None`` plus a populated
        ``error`` means the process never started; ``timed_out=True`` means
        the deadline killed it; ``truncated=True`` means a stream exceeded
        the cap and the process was killed mid-stream, with the first
        ``max_output_bytes`` bytes retained.
    """
    frozen_argv = tuple(str(part) for part in argv)
    env: dict[str, str] | None = None
    if env_extra:
        env = dict(os.environ)
        env.update(env_extra)

    job = _open_kill_on_close_job()
    try:
        # start_new_session detaches the child into its own process group so a
        # timeout/cap kill can SIGKILL grandchildren too (no orphaned helpers);
        # on Windows the Job Object below provides the equivalent tree kill.
        proc = subprocess.Popen(  # noqa: S603 - argv is caller-controlled, shell is never used
            list(frozen_argv),
            cwd=None if cwd is None else os.fspath(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=not _WIN32,
        )
    except (FileNotFoundError, OSError) as exc:
        if job is not None:
            _close_job_handle(job)
        return RunResult(
            argv=frozen_argv,
            returncode=None,
            stdout="",
            stderr="",
            timed_out=False,
            truncated=False,
            error=_short_error(exc),
        )
    if job is not None:
        # A grandchild spawned between Popen and this assignment escapes the
        # job (closing that window would need a CREATE_SUSPENDED spawn plus a
        # thread handle); the window is microseconds and KILL_ON_JOB_CLOSE
        # still bounds everything that did get assigned.
        _assign_job(job, proc)

    overflow = threading.Event()
    stdout_reader = _StreamReader(proc.stdout, max_output_bytes, overflow)
    stderr_reader = _StreamReader(proc.stderr, max_output_bytes, overflow)
    stdout_thread = stdout_reader.start()
    stderr_thread = stderr_reader.start()

    timed_out = False
    truncated = False
    deadline = time.monotonic() + timeout_seconds
    try:
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                _kill_process_group(proc, job)
                break
            if overflow.is_set():
                truncated = True
                _kill_process_group(proc, job)
                break
            time.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        try:
            proc.wait(timeout=_JOIN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:  # pragma: no cover - pathological reaper hang
            _kill_process_group(proc, job)
            proc.wait(timeout=_JOIN_TIMEOUT_SECONDS)
        stdout_thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
        stderr_thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
        for stream in (proc.stdout, proc.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass
        if job is not None:
            # KILL_ON_JOB_CLOSE: closing the handle terminates any grandchild
            # that raced past assignment/termination; after a clean wait() the
            # job is empty and this is a no-op.
            _close_job_handle(job)

    truncated = truncated or stdout_reader.exceeded_cap or stderr_reader.exceeded_cap

    return RunResult(
        argv=frozen_argv,
        returncode=None if timed_out else int(proc.returncode),
        stdout=stdout_reader.data().decode("utf-8", errors="replace"),
        stderr=stderr_reader.data().decode("utf-8", errors="replace"),
        timed_out=timed_out,
        truncated=truncated,
        error=None,
    )
