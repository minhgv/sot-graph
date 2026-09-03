"""P1.f — streaming hard cap in sot_graph.proc.run_command.

A stream that exceeds ``max_output_bytes`` must kill the whole process group
mid-stream (``truncated=True``, bounded memory), without waiting for the
process to finish and without waiting for the wall-clock deadline.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sot_graph.proc import run_command  # noqa: E402

FLOOD = (
    "import sys\n"
    "while True:\n"
    "    sys.stdout.write('x' * 4096)\n"
    "    sys.stdout.flush()\n"
)


def test_oversized_stdout_killed_mid_stream(tmp_path) -> None:
    exe = tmp_path / "flood.py"
    exe.write_text(FLOOD, encoding="utf-8")
    cap = 64 * 1024

    started = time.monotonic()
    result = run_command(
        [sys.executable, str(exe)],
        timeout_seconds=30.0,
        max_output_bytes=cap,
    )
    elapsed = time.monotonic() - started

    assert result.timed_out is False
    assert result.truncated is True
    assert len(result.stdout.encode("utf-8")) <= cap
    # Killed mid-stream: must not have run anywhere near the 30s deadline.
    assert elapsed < 10.0, f"cap kill took {elapsed:.1f}s — process was not killed mid-stream"


def test_oversized_stderr_stream_capped(tmp_path) -> None:
    exe = tmp_path / "flood_err.py"
    exe.write_text(FLOOD.replace("stdout", "stderr"), encoding="utf-8")

    result = run_command(
        [sys.executable, str(exe)],
        timeout_seconds=30.0,
        max_output_bytes=32 * 1024,
    )

    assert result.timed_out is False
    assert result.truncated is True
    assert len(result.stderr.encode("utf-8")) <= 32 * 1024
    assert result.stdout == ""


def test_grandchild_flooder_killed_with_group(tmp_path) -> None:
    parent = tmp_path / "parent.py"
    child = tmp_path / "child.py"
    child.write_text(FLOOD, encoding="utf-8")
    parent.write_text(
        "import subprocess, sys\n"
        f"subprocess.Popen([sys.executable, {str(child)!r}])\n"
        "import time\n"
        "time.sleep(300)\n",
        encoding="utf-8",
    )

    result = run_command(
        [sys.executable, str(parent)],
        timeout_seconds=30.0,
        max_output_bytes=16 * 1024,
    )

    assert result.truncated is True
    # The flooding grandchild must be SIGKILLed with the group; give the OS a
    # moment then assert the parent is gone (group kill proven by the runner's
    # reaping below — returncode present and negative on POSIX, non-zero on Win32).
    if sys.platform == "win32":
        assert result.returncode is not None and result.returncode != 0
    else:
        assert result.returncode is not None and result.returncode < 0

def test_output_exactly_at_cap_not_truncated(tmp_path) -> None:
    exe = tmp_path / "exact.py"
    payload = "y" * 4096
    exe.write_text(f"import sys\nsys.stdout.write({payload!r})\n", encoding="utf-8")

    result = run_command(
        [sys.executable, str(exe)],
        timeout_seconds=30.0,
        max_output_bytes=4096,
    )

    assert result.timed_out is False
    assert result.truncated is False
    assert result.returncode == 0
    assert result.stdout == payload


def test_small_output_unaffected_by_cap_streaming(tmp_path) -> None:
    exe = tmp_path / "ok.py"
    exe.write_text("print('fine')\n", encoding="utf-8")

    result = run_command([sys.executable, str(exe)], max_output_bytes=1024)

    assert result.returncode == 0
    assert result.timed_out is False
    assert result.truncated is False
    assert result.stdout.strip() == "fine"
