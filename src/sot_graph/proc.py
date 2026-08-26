"""
sot_graph.proc — Unified bounded subprocess runner.

Single entry point :func:`run_command` executes an argv list (never a shell)
and always returns a :class:`RunResult`; spawn failures and timeouts are
reported as data instead of raised exceptions, so provider adapters can treat
"command did not work" uniformly.

- ``timeout_seconds`` kills the whole process group on deadline
  (``timed_out=True``); the child is spawned in its own session so
  grandchildren never outlive the deadline.
- Output is drained incrementally from both pipes with a hard per-stream
  byte cap: the moment a stream exceeds ``max_output_bytes`` the process
  group is SIGKILLed mid-stream (``truncated=True``). Memory stays bounded
  regardless of how much the child produces.
"""
from __future__ import annotations

import os
import signal
import subprocess
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


def _kill_process_group(proc: subprocess.Popen) -> None:
    """SIGKILL the child's entire process group, falling back to the child."""
    if hasattr(os, "killpg") and hasattr(os, "getpgid"):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass  # already gone or unreachable; fall through to proc.kill()
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

    try:
        # start_new_session detaches the child into its own process group so a
        # timeout/cap kill can SIGKILL grandchildren too (no orphaned helpers).
        proc = subprocess.Popen(  # noqa: S603 - argv is caller-controlled, shell is never used
            list(frozen_argv),
            cwd=None if cwd is None else os.fspath(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError) as exc:
        return RunResult(
            argv=frozen_argv,
            returncode=None,
            stdout="",
            stderr="",
            timed_out=False,
            truncated=False,
            error=_short_error(exc),
        )

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
                _kill_process_group(proc)
                break
            if overflow.is_set():
                truncated = True
                _kill_process_group(proc)
                break
            time.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        try:
            proc.wait(timeout=_JOIN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:  # pragma: no cover - pathological reaper hang
            _kill_process_group(proc)
            proc.wait(timeout=_JOIN_TIMEOUT_SECONDS)
        stdout_thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
        for stream in (proc.stdout, proc.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass

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
