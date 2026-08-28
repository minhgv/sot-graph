"""Tests for sot_graph.proc — unified bounded subprocess runner."""

from __future__ import annotations

import os
import sys

from sot_graph.proc import RunResult, run_command

PY = sys.executable


def test_success_returns_stdout_and_zero_returncode(tmp_path) -> None:
    result = run_command([PY, "-c", "print('hello-proc')"], cwd=tmp_path)

    assert isinstance(result, RunResult)
    assert result.returncode == 0
    assert result.stdout.strip() == "hello-proc"
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.truncated is False
    assert result.error is None


def test_missing_command_reports_error_without_raising() -> None:
    result = run_command(["sot-graph-definitely-not-a-real-binary-xyz"])

    assert result.returncode is None
    assert result.error is not None
    assert result.timed_out is False


def test_timeout_kills_long_sleep() -> None:
    result = run_command(
        [PY, "-c", "import time; time.sleep(30)"],
        timeout_seconds=0.3,
    )

    assert result.timed_out is True
    assert result.returncode is None
    # Deadline must actually bound the wait: the 30s sleep never completed.


def test_oversized_output_is_truncated_to_cap() -> None:
    cap = 4096
    result = run_command(
        [PY, "-c", f"import sys; sys.stdout.write('a' * {cap + 1000})"],
        max_output_bytes=cap,
    )

    assert result.truncated is True
    assert len(result.stdout.encode("utf-8")) == cap


def test_cwd_with_spaces_and_unicode(tmp_path) -> None:
    workdir = os.path.join(str(tmp_path), "thư mục có dấu cách ünï")
    os.makedirs(workdir)
    result = run_command(
        [PY, "-c", "import os; print(os.getcwd())"],
        cwd=workdir,
        env_extra={"PYTHONIOENCODING": "utf-8"},  # child stdout must survive the unicode cwd
    )

    assert result.returncode == 0
    assert result.stdout.strip() == os.path.realpath(workdir)


def test_env_extra_reaches_process(tmp_path) -> None:
    result = run_command(
        [PY, "-c", "import os; print(os.environ['SOT_PROC_TEST_VAR'])"],
        env_extra={"SOT_PROC_TEST_VAR": "injected-42"},
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "injected-42"


def test_stderr_reader_joined_before_return() -> None:
    size = 256 * 1024
    result = run_command(
        [
            PY,
            "-c",
            f"import sys; sys.stderr.write('e' * {size}); sys.stderr.flush()",
        ],
        max_output_bytes=size + 1,
    )

    assert result.returncode == 0
    assert result.stderr == "e" * size
