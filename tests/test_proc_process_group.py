"""Tests for sot_graph.proc process-group termination (P1 hardening).

The runner must spawn children in their own session (``start_new_session``)
and SIGKILL the whole process GROUP on deadline so grandchildren never
outlive the timeout.
"""
from __future__ import annotations

import os
import stat
import sys
import time

import pytest

from sot_graph.proc import run_command

PY = sys.executable

# Process-group semantics (setsid/killpg, os.kill(pid, 0) liveness probes) are
# POSIX-only; the Windows equivalent (Job Object tree kill) lives in
# tests/test_proc_windows_job.py and runs on the windows CI matrix.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="process-group kill semantics are POSIX-only",
)


def make_exe(directory, name, body):
    path = directory / name
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _wait_gone(pid: int, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_timeout_kills_grandchild_process_group(tmp_path) -> None:
    """A grandchild spawned by the child must not survive the deadline."""
    parent_pid_file = tmp_path / "parent.pid"
    grandchild_pid_file = tmp_path / "grandchild.pid"
    marker = tmp_path / "started"
    body = (
        "import subprocess, sys, time\n"
        f"open({str(parent_pid_file)!r}, 'w').write(str(__import__('os').getpid()))\n"
        "grand = subprocess.Popen(['sleep', '30'])\n"
        f"open({str(grandchild_pid_file)!r}, 'w').write(str(grand.pid))\n"
        f"open({str(marker)!r}, 'w').write('x')\n"
        "time.sleep(30)\n"
    )
    exe = make_exe(tmp_path, "spawner", body)

    result = run_command([str(exe)], timeout_seconds=2.0)

    assert result.timed_out is True
    assert marker.exists(), "child never reached the spawn point"
    parent_pid = int(parent_pid_file.read_text())
    grand_pid = int(grandchild_pid_file.read_text())
    assert _wait_gone(parent_pid), f"parent {parent_pid} survived the kill"
    assert _wait_gone(grand_pid), (
        f"grandchild {grand_pid} orphaned after group kill"
    )


def test_stderr_captured_when_timeout_kills(tmp_path) -> None:
    exe = make_exe(
        tmp_path, "chatty",
        "import sys, time\nsys.stderr.write('before-sleep-marker\\n')\n"
        "sys.stderr.flush()\ntime.sleep(30)\n",
    )
    result = run_command([str(exe)], timeout_seconds=2.0)
    assert result.timed_out is True
    assert "before-sleep-marker" in result.stderr


def test_success_path_unaffected_by_session_spawn(tmp_path) -> None:
    exe = make_exe(tmp_path, "ok", "print('fine')\n")
    result = run_command([str(exe)])
    assert result.returncode == 0
    assert result.stdout.strip() == "fine"
    assert result.timed_out is False
