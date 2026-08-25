"""Tests for sot_graph.providers.codebase_memory (one-shot FEDERATED_CLI).

Every executable is a FAKE script on a private PATH — the real
``codebase-memory-mcp`` binary is never invoked. Golden-fixture tests are
owned by another worker and live elsewhere.
"""
from __future__ import annotations

import json
import stat
import sys
import time
from pathlib import Path

import pytest

from sot_graph.providers.base import supports_method
from sot_graph.providers.codebase_memory import (
    NEXT_ACTION_SYNC,
    CodebaseMemoryProvider,
    redact_argv,
)

PY = sys.executable


class TestRedactArgv:
    def test_separated_sensitive_value_masked(self):
        assert redact_argv(
            ("cbm", "--api-token", "hunter2", "--json", "t")
        ) == ("cbm", "--api-token", "***REDACTED***", "--json", "t")

    def test_inline_sensitive_value_masked(self):
        argv = redact_argv(("cbm", "--password=hunter2", "--flag"))
        assert argv[1] == "--password=***REDACTED***"

    def test_benign_flags_untouched(self):
        argv = ("cbm", "cli", "--json", "search_graph", "--args-file", "/tmp/x")
        assert redact_argv(argv) == argv

INJECTION_QUERY = 'x"; rm -rf $HOME; echo pwned; `id` $(reboot)'


def make_exe(directory: Path, name: str, body: str) -> str:
    path = directory / name
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def envelope(text: str, *, is_error: bool = False) -> str:
    return json.dumps(
        {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
            "structuredContent": {},
        }
    )


def payload_envelope(payload) -> str:
    return envelope(json.dumps(payload))


class LedgerRecorder:
    """Duck-typed stand-in for Database.record_provider_run."""

    def __init__(self):
        self.calls = []

    def record_provider_run(self, provider_name, **kwargs):
        self.calls.append((provider_name, kwargs))
        return kwargs.get("run_id", "rec")

def success_exe(directory: Path, name: str, payload, *, exit_code: int = 0,
                stderr_extra: str = "") -> str:
    """Fake CLI printing one valid success envelope for any request."""
    script = (
        "import json, sys\n"
        f"sys.stderr.write({stderr_extra!r})\n"
        "env = {'content': [{'type': 'text', 'text': json.dumps(" + repr(payload) + ")}],"
        " 'isError': False, 'structuredContent': {}}\n"
        "print(json.dumps(env))\n"
        f"sys.exit({exit_code})\n"
    )
    return make_exe(directory, name, script)


def argv_echo_exe(directory: Path, name: str = "cbm-echo") -> str:
    """Fake CLI echoing its argv AND the parsed --args-file JSON request."""
    body = (
        "import json, sys\n"
        "argv = sys.argv[1:]\n"
        "request = None\n"
        "if '--args-file' in argv:\n"
        "    i = argv.index('--args-file')\n"
        "    with open(argv[i + 1], encoding='utf-8') as fh:\n"
        "        request = json.load(fh)\n"
        "env = {'content': [{'type': 'text',\n"
        "                    'text': json.dumps({'argv': argv,\n"
        "                                        'request': request})}],\n"
        "       'isError': False, 'structuredContent': {}}\n"
        "print(json.dumps(env))\n"
    )
    return make_exe(directory, name, body)


REPO = "repo-root"  # relative is fine; adapter canonicalizes via realpath


class TestProbe:
    def test_missing_executable_not_installed(self, tmp_path):
        provider = CodebaseMemoryProvider(command=["no-such-cbm-binary-xyz"])
        status = provider.probe(str(tmp_path))
        assert status.installed is False
        assert status.healthy is False
        assert status.version is None
        assert "not installed" in status.detail

    def test_version_probe_parses_version(self, tmp_path):
        exe = make_exe(tmp_path, "cbm", "print('codebase-memory-mcp 9.9.9-fake')\n")
        ledger = LedgerRecorder()
        provider = CodebaseMemoryProvider(command=[exe], db=ledger)
        status = provider.probe(str(tmp_path))
        assert (status.installed, status.healthy) == (True, True)
        assert status.version == "9.9.9-fake"
        assert ledger.calls, "probe must reach the provider_runs ledger"
        name, kwargs = ledger.calls[0]
        assert name == "codebase-memory" and kwargs["capability"] == "probe"

    def test_unparseable_version_output_is_unhealthy(self, tmp_path):
        exe = make_exe(tmp_path, "cbm", "print('hello world v1')\n")
        provider = CodebaseMemoryProvider(command=[exe])
        status = provider.probe(str(tmp_path))
        assert status.healthy is False
        assert status.version is None
        assert "unparseable" in status.detail

    def test_nonzero_version_probe_is_unhealthy(self, tmp_path):
        exe = make_exe(tmp_path, "cbm", "import sys; sys.exit(3)\n")
        provider = CodebaseMemoryProvider(command=[exe])
        status = provider.probe(str(tmp_path))
        assert status.installed is True and status.healthy is False
        assert "exit=3" in status.detail


class TestInvocationContract:
    def test_success_payload_extraction(self, tmp_path):
        exe = success_exe(tmp_path, "cbm", {"results": [{"id": "s1"}]})
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "foo")
        )
        assert outcome.ok is True
        assert outcome.payload == {"results": [{"id": "s1"}]}
        assert outcome.error is None
        assert outcome.run.status == "ok"

    def test_structured_content_preferred_over_content_text(self, tmp_path):
        body = (
            "import json, sys\n"
            "env = {'content': [{'type': 'text', 'text': 'NOT JSON {{'}],\n"
            "       'isError': False,\n"
            "       'structuredContent': {'results': ['structured-wins']}}\n"
            "print(json.dumps(env))\n"
        )
        exe = make_exe(tmp_path, "cbm", body)
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "foo")
        )
        assert outcome.ok is True
        assert outcome.payload == {"results": ["structured-wins"]}

    def test_is_error_envelope_fails_with_message(self, tmp_path):
        body = (
            "import json, sys\n"
            "env = {'content': [{'type': 'text', 'text': 'index generation stale'}],\n"
            "       'isError': True, 'structuredContent': {}}\n"
            "print(json.dumps(env))\n"
        )
        exe = make_exe(tmp_path, "cbm", body)
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "foo")
        )
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "provider_error"
        assert "stale" in outcome.error
        assert outcome.next_action == NEXT_ACTION_SYNC

    def test_jsonrpc_error_envelope_detected(self, tmp_path):
        body = (
            "import json, sys\n"
            "print(json.dumps({'jsonrpc': '2.0', 'id': 1,\n"
            "                  'error': {'code': -32000,\n"
            "                            'message': 'bootstrap failed'}}))\n"
        )
        exe = make_exe(tmp_path, "cbm", body)
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "foo")
        )
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "jsonrpc_error"
        assert outcome.error == "bootstrap failed"

    def test_exit_nonzero_after_ok_envelope_fails_closed(self, tmp_path):
        exe = success_exe(tmp_path, "cbm", {"ok": True}, exit_code=1)
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "foo")
        )
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "provider_error"


def _sym_request(repo_root, query, limit=5, project="proj-fake"):
    from sot_graph.providers.base import SymbolRequest
    return SymbolRequest(
        repo_root=repo_root, query=query, limit=limit, project=project,
    )


class TestStdoutCorruption:
    def test_empty_stdout(self, tmp_path):
        exe = make_exe(tmp_path, "cbm", "pass\n")
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "q")
        )
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "empty_stdout"

    def test_malformed_json(self, tmp_path):
        exe = make_exe(tmp_path, "cbm", "print('{oops')\n")
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "q")
        )
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "invalid_json"

    def test_multiple_json_documents(self, tmp_path):
        body = (
            "import json\n"
            "env = {'content': [{'type': 'text', 'text': '{}'}], 'isError': False,\n"
            "       'structuredContent': {}}\n"
            "line = json.dumps(env)\n"
            "print(line); print(line)\n"
        )
        exe = make_exe(tmp_path, "cbm", body)
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "q")
        )
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "multiple_json"
        assert "2 JSON documents" in outcome.error

    def test_log_lines_mixed_into_stdout_rejected(self, tmp_path):
        body = (
            "import json, sys\n"
            "sys.stdout.write('[12:00:00 INFO] indexing chunk 4\\n')\n"
            "env = {'content': [{'type': 'text', 'text': '{}'}], 'isError': False,\n"
            "       'structuredContent': {}}\n"
            "sys.stdout.write(json.dumps(env) + '\\n')\n"
        )
        exe = make_exe(tmp_path, "cbm", body)
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "q")
        )
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "invalid_json"

    def test_oversized_payload_truncated_not_parsed(self, tmp_path):
        exe = success_exe(tmp_path, "cbm", {"blob": "x" * 100_000})
        provider = CodebaseMemoryProvider(command=[exe], max_output_bytes=1024)
        outcome = provider.search_symbols(_sym_request(str(tmp_path), "q"))
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "truncated"
        assert outcome.payload is None


class TestSchemaDrift:
    @pytest.mark.parametrize("envelope_builder,expected_status", [
        (lambda: "[]", "schema_drift"),                       # envelope not object
        (lambda: "{}", "schema_drift"),                        # no content array
        (lambda: '{"content": []}', "schema_drift"),           # empty content
        (lambda: '{"content": [{"type": "image"}]}', "schema_drift"),
        (lambda: '{"content": [{"type": "text"}]}', "schema_drift"),   # no text
    ])
    def test_drifted_envelopes_fail_closed(self, tmp_path, envelope_builder,
                                           expected_status):
        body = f"import sys\nsys.stdout.write({envelope_builder()!r} + '\\n')\n"
        exe = make_exe(tmp_path, "cbm", body)
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "q")
        )
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == expected_status
        assert outcome.next_action is None  # drift is not an index problem

    def test_non_json_text_report_passes_through_verbatim(self, tmp_path):
        """Text-report tools (ADR-0001 §6) surface their report verbatim."""
        body = (
            "import json, sys\n"
            "env = {'content': [{'type': 'text', 'text': 'total: 0\\nhas_more: false'}],\n"
            "       'isError': False, 'structuredContent': {}}\n"
            "print(json.dumps(env))\n"
        )
        exe = make_exe(tmp_path, "cbm", body)
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "q")
        )
        assert outcome.ok is True
        assert outcome.payload == "total: 0\nhas_more: false"

    def test_unknown_enum_like_field_preserved_verbatim(self, tmp_path):
        """Unknown payload vocabulary passes through untouched — no guessing."""
        exe = success_exe(tmp_path, "cbm", {"relation": "teleports"})
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "q")
        )
        assert outcome.ok is True
        assert outcome.payload["relation"] == "teleports"


class TestTimeoutAndOrphans:
    def test_timeout_kills_whole_group_and_reports(self, tmp_path):
        grandchild_file = tmp_path / "grand.pid"
        body = (
            "import subprocess, sys, time\n"
            "grand = subprocess.Popen(['sleep', '30'])\n"
            f"open({str(grandchild_file)!r}, 'w').write(str(grand.pid))\n"
            "time.sleep(30)\n"
        )
        exe = make_exe(tmp_path, "cbm-slow", body)
        provider = CodebaseMemoryProvider(command=[exe], query_timeout_seconds=0.5)
        outcome = provider.search_symbols(_sym_request(str(tmp_path), "q"))
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "timeout"

        grand_pid = int(grandchild_file.read_text())
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                import os
                os.kill(grand_pid, 0)
            except ProcessLookupError:
                break  # orphan reaped: group kill worked
            time.sleep(0.05)
        else:
            pytest.fail(f"grandchild {grand_pid} orphaned after group kill")

    def test_injection_string_and_unicode_path_stay_single_argv_element(
        self, tmp_path
    ):
        workdir = tmp_path / "repo có dấu cách ünï"
        workdir.mkdir()
        exe = argv_echo_exe(tmp_path)
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(workdir), INJECTION_QUERY)
        )
        assert outcome.ok is True, outcome.error
        # The hostile string traveled inside the JSON request file, arrived
        # intact as one value, and never touched a shell.
        assert outcome.payload["request"]["query"] == INJECTION_QUERY
        assert "--args-file" in outcome.payload["argv"]
        assert outcome.run.arguments_redacted[0] == exe

    def test_sensitive_flag_values_redacted_in_ledger(self, tmp_path):
        exe = success_exe(tmp_path, "cbm", {})
        ledger = LedgerRecorder()
        provider = CodebaseMemoryProvider(
            command=[exe, "--api-token", "super-secret-value"],
            db=ledger,
        )
        provider.search_symbols(_sym_request(str(tmp_path), "q"))
        name, kwargs = ledger.calls[-1]
        stored = kwargs["arguments_json"]
        assert "super-secret-value" not in stored
        assert "***REDACTED***" in stored
        # The real argv still carries the value (only logs/ledger are redacted).
        assert "super-secret-value" in provider.command


class TestLedgerAndRecords:
    def test_run_record_returned_without_db(self, tmp_path):
        exe = success_exe(tmp_path, "cbm", {"x": 1})
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "q")
        )
        run = outcome.run
        assert run.provider_name == "codebase-memory"
        assert run.status == "ok"
        assert run.exit_code == 0
        assert run.duration_ms >= 0
        assert run.arguments_redacted  # non-empty redacted argv

    def test_ledger_receives_matching_run_id(self, tmp_path):
        exe = success_exe(tmp_path, "cbm", {})
        ledger = LedgerRecorder()
        outcome = CodebaseMemoryProvider(command=[exe], db=ledger).search_symbols(
            _sym_request(str(tmp_path), "q")
        )
        name, kwargs = ledger.calls[-1]
        assert kwargs["run_id"] == outcome.run.run_id
        assert kwargs["snapshot_hash"] is None  # P1: unbound


class TestFailClosedVsOptionalFallback:
    def test_required_provider_failure_never_fabricates(self, tmp_path):
        """A failing required provider returns abstention data, not guesses."""
        exe = make_exe(tmp_path, "cbm", "import sys; sys.exit(1)\n")
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "anything")
        )
        assert outcome.ok is False
        assert outcome.payload is None
        assert outcome.error
        assert outcome.next_action == NEXT_ACTION_SYNC

    def test_capability_negotiation_gates_methods(self):
        from sot_graph.config import DEFAULT_PROVIDERS
        gated = CodebaseMemoryProvider(
            config=DEFAULT_PROVIDERS["codebase-memory"]
        )
        assert supports_method(gated, "search_symbols") is True
        assert supports_method(gated, "trace") is False   # not advertised
        bare = CodebaseMemoryProvider()                   # no capabilities
        assert supports_method(bare, "search_symbols") is False
        assert supports_method(bare, "probe") is True     # always allowed


class TestEnsureIndexAbstainsP1:
    def test_ensure_index_never_invokes_binary(self, tmp_path):
        # Binary does not exist at all — if the adapter tried to invoke it,
        # this would be a spawn attempt. Abstention short-circuits instead.
        provider = CodebaseMemoryProvider(command=["no-such-cbm-binary-xyz"])
        record = provider.ensure_index(_index_request(str(tmp_path)))
        assert record.status == "abstained"
        assert record.exit_code is None
        assert record.next_action == NEXT_ACTION_SYNC
        assert "does not invoke index_repository" in record.detail

    def test_coverage_failure_points_at_sync(self, tmp_path):
        exe = make_exe(tmp_path, "cbm", "import sys; sys.exit(7)\n")
        from sot_graph.providers.base import CoverageRequest
        outcome = CodebaseMemoryProvider(command=[exe]).coverage(
            CoverageRequest(repo_root=str(tmp_path))
        )
        assert outcome.ok is False
        assert outcome.next_action == NEXT_ACTION_SYNC


def dispatch_exe(directory: Path, name: str = "cbm-dispatch") -> str:
    """Fake CLI echoing the parsed request; list_projects matches the cwd.

    run_command launches every invocation with cwd=realpath(repo_root), so
    answering ``root_path: os.getcwd()`` makes exactly one project match any
    repo root the adapter resolves against.
    """
    body = (
        "import json, os, sys\n"
        "argv = sys.argv[1:]\n"
        "tool = argv[argv.index('--json') + 1] if '--json' in argv else ''\n"
        "request = None\n"
        "if '--args-file' in argv:\n"
        "    with open(argv[argv.index('--args-file') + 1]) as fh:\n"
        "        request = json.load(fh)\n"
        "if tool == 'list_projects':\n"
        "    payload = {'projects': [{'name': 'fake-proj', 'root_path': os.getcwd()}],\n"
        "               'total': 1, 'has_more': False}\n"
        "else:\n"
        "    payload = {'tool': tool, 'request': request}\n"
        "env = {'content': [{'type': 'text', 'text': json.dumps(payload)}],\n"
        "       'isError': False, 'structuredContent': {}}\n"
        "print(json.dumps(env))\n"
    )
    return make_exe(directory, name, body)


def _trace_request(repo_root, symbol, project=None):
    from sot_graph.providers.base import TraceRequest
    return TraceRequest(repo_root=repo_root, symbol=symbol, project=project)


class TestProjectResolution:
    def test_explicit_project_skips_list_projects(self, tmp_path):
        exe = argv_echo_exe(tmp_path)
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "q", project="proj-explicit")
        )
        assert outcome.ok is True, outcome.error
        assert outcome.payload["request"]["project"] == "proj-explicit"
        assert "list_projects" not in outcome.payload["argv"]

    def test_resolved_project_injected_when_omitted(self, tmp_path):
        exe = dispatch_exe(tmp_path)
        provider = CodebaseMemoryProvider(command=[exe])
        outcome = provider.search_symbols(_sym_request(str(tmp_path), "q", project=None))
        assert outcome.ok is True, outcome.error
        assert outcome.payload["request"]["project"] == "fake-proj"

    def test_trace_sends_function_name_wire_key(self, tmp_path):
        exe = argv_echo_exe(tmp_path)
        outcome = CodebaseMemoryProvider(command=[exe]).trace(
            _trace_request(str(tmp_path), "build_invoice", project="proj-fake")
        )
        assert outcome.ok is True, outcome.error
        assert outcome.payload["request"]["function_name"] == "build_invoice"
        assert "symbol" not in outcome.payload["request"]

    def test_zero_project_match_abstains_without_tool_call(self, tmp_path):
        # list_projects reports a DIFFERENT root than the queried repo_root.
        body = (
            "import json, sys\n"
            "tool = sys.argv[sys.argv.index('--json') + 1]\n"
            "if tool == 'list_projects':\n"
            "    payload = {'projects': [{'name': 'other', 'root_path': '/elsewhere'}]}\n"
            "else:\n"
            "    payload = {'should_not_be_reached': True}\n"
            "env = {'content': [{'type': 'text', 'text': json.dumps(payload)}],\n"
            "       'isError': False, 'structuredContent': {}}\n"
            "print(json.dumps(env))\n"
        )
        exe = make_exe(tmp_path, "cbm", body)
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "q", project=None)
        )
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "abstained"
        assert "no indexed CBM project" in outcome.error
        assert outcome.next_action == NEXT_ACTION_SYNC

    def test_ambiguous_project_match_abstains(self, tmp_path):
        body = (
            "import json, os, sys\n"
            "tool = sys.argv[sys.argv.index('--json') + 1]\n"
            "root = os.getcwd()\n"
            "payload = {'projects': [\n"
            "    {'name': 'dup-a', 'root_path': root},\n"
            "    {'name': 'dup-b', 'root_path': root}]}\n"
            "env = {'content': [{'type': 'text', 'text': json.dumps(payload)}],\n"
            "       'isError': False, 'structuredContent': {}}\n"
            "print(json.dumps(env))\n"
        )
        exe = make_exe(tmp_path, "cbm-ambig", body)
        outcome = CodebaseMemoryProvider(command=[exe]).search_symbols(
            _sym_request(str(tmp_path), "q", project=None)
        )
        assert outcome.ok is False
        assert outcome.metadata["wire_status"] == "abstained"
        assert "ambiguous" in outcome.error
        assert "list_projects" in outcome.next_action

    def test_resolution_cached_per_repo_root(self, tmp_path):
        counter = tmp_path / "invocations"
        body = (
            "import json, os, sys\n"
            f"open({str(counter)!r}, 'a').write('x')\n"
            "tool = sys.argv[sys.argv.index('--json') + 1]\n"
            "if tool == 'list_projects':\n"
            "    payload = {'projects': [{'name': 'fake-proj', 'root_path': os.getcwd()}]}\n"
            "else:\n"
            "    payload = {'ok': tool}\n"
            "env = {'content': [{'type': 'text', 'text': json.dumps(payload)}],\n"
            "       'isError': False, 'structuredContent': {}}\n"
            "print(json.dumps(env))\n"
        )
        exe = make_exe(tmp_path, "cbm-cache", body)
        provider = CodebaseMemoryProvider(command=[exe])
        first = provider.search_symbols(_sym_request(str(tmp_path), "q1", project=None))
        second = provider.search_symbols(_sym_request(str(tmp_path), "q2", project=None))
        assert first.ok and second.ok
        # P2: one list_projects + two tool calls + two index_status binding
        # probes (one per successful bound query); project resolution itself
        # ran only once.
        assert counter.read_text() == "xxxxx"


def _index_request(repo_root):
    from sot_graph.providers.base import IndexRequest
    return IndexRequest(repo_root=repo_root)
