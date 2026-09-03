"""G9: Windows Job Object tree-kill plumbing in sot_graph.proc.

On POSIX the job helpers are inert stubs (asserted here so the win32
branch can never half-activate elsewhere); on Windows the deadline kill
must reap grandchildren through the KILL_ON_JOB_CLOSE Job Object. The
grandchild scenario mirrors tests/test_proc_process_group.py but probes
liveness via OpenProcess — os.kill(pid, 0) has POSIX-only semantics.
"""
from __future__ import annotations

import sys
import time

import pytest

from sot_graph.proc import (
    _close_job_handle,
    _open_kill_on_close_job,
    _terminate_job,
    run_command,
)

PY = sys.executable


def test_job_helpers_are_inert_on_posix() -> None:
    """Outside win32 the plumbing must degrade to no-ops, never raise."""
    if sys.platform == "win32":
        pytest.skip("POSIX-only inertness contract")
    assert _open_kill_on_close_job() is None
    assert _terminate_job(0) is False


def test_job_handle_created_and_closed_on_windows() -> None:
    if sys.platform != "win32":
        pytest.skip("win32-only Job Object plumbing")
    job = _open_kill_on_close_job()
    assert job is not None, "CreateJobObjectW/SetInformationJobObject failed"
    _close_job_handle(job)


def _pid_alive_win(pid: int) -> bool:
    import ctypes

    windll = getattr(ctypes, "windll", None)
    if windll is None:  # pragma: no cover - win32 without windll is broken
        return True  # fail-safe: assume alive so a miss never looks like a kill
    kernel32 = windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def _wait_gone_win(pid: int, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _pid_alive_win(pid):
            return True
        time.sleep(0.05)
    return False


def test_timeout_kills_grandchild_via_job(tmp_path) -> None:
    """A grandchild must not survive the deadline on win32 either."""
    if sys.platform != "win32":
        pytest.skip("win32-only Job Object tree kill")
    grandchild_pid_file = tmp_path / "grandchild.pid"
    marker = tmp_path / "started"
    grand_code = (
        "import os, sys, time\n"
        "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    parent_code = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', "
        + repr(grand_code)
        + ", sys.argv[1]])\n"
        "open(sys.argv[2], 'w').write('x')\n"
        "time.sleep(30)\n"
    )
    result = run_command(
        [PY, "-c", parent_code, str(grandchild_pid_file), str(marker)],
        timeout_seconds=3.0,
    )
    assert result.timed_out is True
    assert marker.exists(), "child never reached the spawn point"
    grand_pid = int(grandchild_pid_file.read_text())
    assert _wait_gone_win(grand_pid), (
        f"grandchild {grand_pid} orphaned after Job Object kill"
    )
