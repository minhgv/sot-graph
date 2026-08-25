"""
sot_graph.proc — Unified bounded subprocess runner.

Single entry point :func:`run_command` executes an argv list (never a shell)
and always returns a :class:`RunResult`; spawn failures and timeouts are
reported as data instead of raised exceptions, so provider adapters can treat
"command did not work" uniformly.

Bounded by construction:
- ``timeout_seconds`` kills the process on deadline (``timed_out=True``).
- Output larger than ``max_output_bytes`` is trimmed post-completion
  (``truncated=True``); the process is never killed mid-stream for size.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

__all__ = ["RunResult", "run_command"]

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_OUTPUT_BYTES = 8 * 1024 * 1024


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


def _decode(data: bytes | None) -> bytes:
    return data or b""


def _short_error(exc: BaseException) -> str:
    text = str(exc).strip()
    name = type(exc).__name__
    return f"{name}: {text}" if text else name


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
        timeout_seconds: Wall-clock budget; expiry kills the process.
        max_output_bytes: Per-stream byte cap applied after completion.
        env_extra: Extra environment variables merged over ``os.environ``.

    Returns:
        A :class:`RunResult`. ``returncode is None`` plus a populated
        ``error`` means the process never started; ``timed_out=True`` means
        the deadline killed it; ``truncated=True`` means output was cut.
    """
    frozen_argv = tuple(str(part) for part in argv)
    env: dict[str, str] | None = None
    if env_extra:
        env = dict(os.environ)
        env.update(env_extra)

    try:
        completed = subprocess.run(  # noqa: S603 - argv is caller-controlled, shell is never used
            list(frozen_argv),
            cwd=None if cwd is None else os.fspath(cwd),
            timeout=timeout_seconds,
            capture_output=True,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return RunResult(
            argv=frozen_argv,
            returncode=None,
            stdout=_decode(exc.stdout).decode("utf-8", errors="replace"),
            stderr=_decode(exc.stderr).decode("utf-8", errors="replace"),
            timed_out=True,
            truncated=False,
            error=None,
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

    stdout_bytes = _decode(completed.stdout)
    stderr_bytes = _decode(completed.stderr)
    truncated = len(stdout_bytes) > max_output_bytes or len(stderr_bytes) > max_output_bytes
    if truncated:
        stdout_bytes = stdout_bytes[:max_output_bytes]
        stderr_bytes = stderr_bytes[:max_output_bytes]

    return RunResult(
        argv=frozen_argv,
        returncode=int(completed.returncode),
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        timed_out=False,
        truncated=truncated,
        error=None,
    )
