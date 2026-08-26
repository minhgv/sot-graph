"""Tests for the P1 CLI query wiring: --provider on explore/usages/diff-impact
and the `sot providers sync` admin command.

The real codebase-memory-mcp binary is never invoked: every executable is a
fake script placed on a private PATH (same pattern as tests/test_cbm_adapter).
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from sot_graph.cli import main as cli_main
from sot_graph.db import Database
from sot_graph.reconciler import Reconciler

PY = sys.executable


# These tests discover the fake CBM binary through PATH by bare name; on
# Windows CreateProcess only auto-appends .exe for bare names, so the .cmd
# fake cannot be spawned there. Adapter spawn behavior stays covered
# cross-platform by tests/test_cbm_adapter.py (absolute command paths).
requires_path_spawned_cbm = pytest.mark.skipif(
    sys.platform == "win32",
    reason="PATH-discovered bare-name fakes need PE executables on Windows",
)

def make_exe(directory: Path, name: str, body: str) -> str:
    if os.name == "nt":
        # CreateProcess cannot exec shebang scripts; install a .cmd wrapper
        # that forwards to this interpreter, keeping a single spawnable argv[0].
        script = directory / f"{name}.py"
        script.write_text(body, encoding="utf-8")
        wrapper = directory / f"{name}.cmd"
        wrapper.write_text(f'@"{sys.executable}" "%~dp0{name}.py" %*\r\n', encoding="utf-8")
        return str(wrapper)
    path = directory / name
    path.write_text(f"#!{PY}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def make_cbm_fake(bin_dir: Path, *, version: str | None = "0.10.8",
                  projects: str = "cwd", search_report: str | None = None,
                  trace_report: str | None = None, changes=None) -> None:
    """Install a fake `codebase-memory-mcp` handling the tools sot calls.

    ``projects="cwd"`` answers list_projects with one project whose root_path
    is os.getcwd() (run_command always cwd's to realpath(repo_root)), so the
    §6 exactly-one-match resolution succeeds for any repo root.
    """
    lines = ["import json, os, sys", "argv = sys.argv[1:]"]
    if version is None:
        lines += ["sys.exit(3) if False else None"]
    else:
        lines += [
            "if argv and argv[0] == '--version':",
            f"    print('codebase-memory-mcp {version}'); sys.exit(0)",
        ]
    lines += [
        "tool = argv[argv.index('--json') + 1]",
        "if tool == 'list_projects':",
    ]
    if projects == "cwd":
        lines += [
            "    payload = {'projects': [{'name': 'fake-proj',"
            " 'root_path': os.getcwd()}], 'total': 1, 'has_more': False}",
        ]
    elif projects == "none":
        lines += ["    payload = {'projects': [], 'total': 0, 'has_more': False}"]
    else:
        lines += [f"    payload = {projects!r}"]
    lines += ["elif tool == 'search_graph':"]
    if search_report is not None:
        lines += [f"    payload = {search_report!r}"]
    else:
        # P3.1: search_graph is queried with format=json; the empty answer
        # is the structured zero-row model, not a text report.
        lines += ["    payload = {'total': 0, 'search_mode': 'bm25',"
                  " 'cols': ['qn', 'label', 'file', 'lines', 'rank'],"
                  " 'rows': [], 'has_more': False}"]
    lines += ["elif tool == 'trace_path':"]
    if trace_report is not None:
        lines += [f"    payload = {trace_report!r}"]
    else:
        lines += [
            "    payload = {'function': '', 'direction': 'both',"
            " 'callees_total': 0, 'callees': {'cols': ['name', 'hop'],"
            " 'groups': []}, 'callers_total': 0,"
            " 'callers': {'cols': ['name', 'hop'], 'groups': []}}",
        ]
    lines += ["elif tool == 'detect_changes':"]
    if changes is not None:
        lines += [f"    payload = {changes!r}"]
    else:
        lines += ["    payload = {'changed_files': [], 'impacted': []}"]
    lines += [
        "elif tool == 'index_repository':",
        "    payload = {'ok': True, 'indexed': True}",
        "else:",
        "    payload = ''",
        "text = payload if isinstance(payload, str) else json.dumps(payload)",
        "env = {'content': [{'type': 'text', 'text': text}],"
        " 'isError': False, 'structuredContent': {}}",
        "print(json.dumps(env))",
    ]
    make_exe(bin_dir, "codebase-memory-mcp", "\n".join(lines) + "\n")


def make_failing_cbm(bin_dir: Path) -> None:
    """A CBM binary whose --version probe exits non-zero (unhealthy)."""
    make_exe(bin_dir, "codebase-memory-mcp", "import sys\nsys.stderr.write('boom\\n')\nsys.exit(3)\n")


def no_spawn(monkeypatch) -> None:
    def boom(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("external process spawned in builtin mode")

    import sot_graph.proc as proc_mod
    import sot_graph.providers.codebase_memory as cm_mod
    monkeypatch.setattr(proc_mod, "run_command", boom)
    monkeypatch.setattr(cm_mod, "run_command", boom)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A tiny indexed repo with one symbol and one caller."""
    (tmp_path / "app.py").write_text(
        "def target():\n    return 1\n\n\ndef caller():\n    return target()\n"
    )
    db = Database(str(tmp_path / ".sot" / "sot.db"))
    try:
        Reconciler(db, str(tmp_path)).reconcile()
    finally:
        db.close()
    return tmp_path


@pytest.fixture()
def bin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bin"
    d.mkdir()
    return d


def allow_external(repo: Path, enabled: bool) -> None:
    cfg_dir = repo / ".sot"
    cfg_dir.mkdir(exist_ok=True)
    (cfg_dir / "config.toml").write_text(f"allow_external = {str(enabled).lower()}\n")


class TestBuiltinDefault:
    def test_default_builtin_never_spawns(self, repo, monkeypatch, capsys):
        no_spawn(monkeypatch)
        rc = cli_main(["--root", str(repo), "explore", "target", "--json"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        # exact legacy shape: federation keys absent
        assert "external_candidates" not in out
        assert "coverage" not in out and "known_gaps" not in out
        assert "truncated" not in out

    def test_explicit_builtin_flag_identical(self, repo, monkeypatch):
        no_spawn(monkeypatch)
        rc = cli_main([
            "--root", str(repo), "explore", "target",
            "--provider", "builtin", "--json",
        ])
        assert rc == 0


class TestAllowExternalGate:
    def test_blocked_prefer_warns_and_falls_back(self, repo, monkeypatch, capsys):
        allow_external(repo, False)
        no_spawn(monkeypatch)
        rc = cli_main([
            "--root", str(repo), "usages", "target",
            "--provider", "prefer:codebase-memory", "--json",
        ])
        captured = capsys.readouterr()
        assert rc == 0
        assert "allow_external=false" in captured.err
        assert captured.out
        out = json.loads(captured.out)
        assert out.get("external_candidates") == []
        assert out["callers"], "builtin callers preserved"

    def test_blocked_require_fails_closed(self, repo, monkeypatch, capsys):
        allow_external(repo, False)
        no_spawn(monkeypatch)
        rc = cli_main([
            "--root", str(repo), "explore", "target",
            "--provider", "require:codebase-memory", "--json",
        ])
        captured = capsys.readouterr()
        assert rc != 0
        assert "fails closed" in captured.err

    def test_invalid_spec_rejected(self, repo):
        rc = cli_main([
            "--root", str(repo), "explore", "target",
            "--provider", "prefer-no-colon", "--json",
        ])
        assert rc == 2


class TestRequireFailsClosedUnhealthy:
    def test_unhealthy_binary_require_exits_nonzero(
        self, repo, bin_dir, monkeypatch, capsys
    ):
        allow_external(repo, True)
        make_failing_cbm(bin_dir)
        monkeypatch.setenv("PATH", str(bin_dir))
        rc = cli_main([
            "--root", str(repo), "usages", "target",
            "--provider", "require:codebase-memory", "--json",
        ])
        captured = capsys.readouterr()
        assert rc != 0
        assert "unavailable" in captured.err

    def test_missing_binary_prefer_falls_back(
        self, repo, bin_dir, monkeypatch, capsys
    ):
        allow_external(repo, True)
        monkeypatch.setenv("PATH", str(bin_dir))  # empty: binary absent
        rc = cli_main([
            "--root", str(repo), "usages", "target",
            "--provider", "prefer:codebase-memory", "--json",
        ])
        captured = capsys.readouterr()
        assert rc == 0
        assert "unavailable" in captured.err


TRACE_REPORT = {
    "function": "target", "direction": "both",
    "callees_total": 1,
    "callees": {"cols": ["name", "hop", "strategy", "confidence"],
                "groups": [{"qn_prefix": "fake-proj.core",
                            "rows": [["helper", 1, "lsp", 0.95]]}]},
    "callers_total": 1,
    "callers": {"cols": ["name", "hop", "strategy", "confidence"],
                "groups": [{"qn_prefix": "fake-proj.app",
                            "rows": [["caller", 1, "lsp", 0.93]]}]},
}


class TestMergeOrderAndVerdict:
    @requires_path_spawned_cbm
    def test_candidates_after_builtin_with_ceiling_and_provider_tag(
        self, repo, bin_dir, monkeypatch, capsys
    ):
        allow_external(repo, True)
        make_cbm_fake(bin_dir, trace_report=TRACE_REPORT)
        monkeypatch.setenv("PATH", str(bin_dir))
        rc = cli_main([
            "--root", str(repo), "usages", "target",
            "--provider", "prefer:codebase-memory", "--json",
        ])
        captured = capsys.readouterr()
        assert rc == 0, captured.err
        out = json.loads(captured.out)
        cands = out["external_candidates"]
        assert cands, "CBM candidates must be merged"
        # union semantics: builtin data intact first, CBM appended after
        assert out["callers"], "builtin callers preserved"
        assert all(c["provider"] == "codebase-memory" for c in cands)
        # P1 snapshot unbound: ceiling caps every candidate at UNVERIFIABLE
        assert all(c["verdict"] == "UNVERIFIABLE" for c in cands)
        # envelope additions present
        assert any(p.get("name") == "codebase-memory" for p in out["providers"])
        assert "codebase-memory" in out["coverage"]
        assert out["known_gaps"], "snapshot-binding gap must be declared"

    @requires_path_spawned_cbm
    def test_target_mismatch_recorded_as_conflict(
        self, repo, bin_dir, monkeypatch, capsys
    ):
        allow_external(repo, True)
        # symbols-only caps force search rows, which carry file paths
        cfg = repo / ".sot"
        cfg.mkdir(exist_ok=True)
        (cfg / "config.toml").write_text(
            "allow_external = true\n"
            "[providers.codebase-memory]\n"
            'capabilities = ["symbols"]\n'
        )
        # CBM claims `target` lives in app2.py while builtin says app.py
        report = {
            "total": 1, "search_mode": "bm25",
            "cols": ["qn", "label", "file", "lines", "rank"],
            "rows": [["fake-proj.app2.target", "Function", "app2.py", "9-9", -5.0]],
            "has_more": False,
        }
        make_cbm_fake(bin_dir, search_report=report)
        monkeypatch.setenv("PATH", str(bin_dir))
        rc = cli_main([
            "--root", str(repo), "usages", "target",
            "--provider", "prefer:codebase-memory", "--json",
        ])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0
        conflicts = out.get("conflicts_detected") or []
        assert conflicts, "path disagreement must be recorded, not adjudicated"
        assert conflicts[0]["kind"] == "target_mismatch"


class TestTruncationPropagation:
    @requires_path_spawned_cbm
    def test_has_more_sets_truncated_true(self, repo, bin_dir, monkeypatch, capsys):
        allow_external(repo, True)
        # symbols-only capabilities force the search_symbols method
        cfg = repo / ".sot"
        cfg.mkdir(exist_ok=True)
        (cfg / "config.toml").write_text(
            "allow_external = true\n"
            "[providers.codebase-memory]\n"
            'capabilities = ["symbols"]\n'
        )
        report = {
            "total": 2, "search_mode": "bm25",
            "cols": ["qn", "label", "file", "lines", "rank"],
            "rows": [["fake-proj.app.target", "Function", "app.py", "1-2", -5.0]],
            "has_more": True,
        }
        make_cbm_fake(bin_dir, search_report=report)
        monkeypatch.setenv("PATH", str(bin_dir))
        rc = cli_main([
            "--root", str(repo), "usages", "target",
            "--provider", "prefer:codebase-memory", "--json",
        ])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert out["truncated"] is True


class TestProvidersSync:
    @requires_path_spawned_cbm
    def test_sync_invokes_index_and_emits_receipt(self, repo, bin_dir, monkeypatch, capsys):
        """P3.1: explicit sync wraps index_repository with lock + receipt."""
        allow_external(repo, True)
        make_cbm_fake(bin_dir)  # answers index_repository with ok
        monkeypatch.setenv("PATH", str(bin_dir))
        rc = cli_main([
            "--root", str(repo), "providers", "sync", "codebase-memory",
            "--json",
        ])
        captured = capsys.readouterr()
        assert rc == 0, captured.err + captured.out
        receipt = json.loads(captured.out)["providers_sync"]
        assert receipt["capability"] == "index_repository"
        assert receipt["status"] == "ok"
        assert receipt["run_id"].startswith("run_")

    def test_sync_never_runs_without_explicit_command(self, repo, monkeypatch, capsys):
        """The implicit path (ensure_index) still abstains — no spawn."""
        no_spawn(monkeypatch)
        from sot_graph.providers.base import IndexRequest
        from sot_graph.providers.codebase_memory import CodebaseMemoryProvider

        provider = CodebaseMemoryProvider()
        record = provider.ensure_index(IndexRequest(repo_root=str(repo)))
        assert record.status == "abstained"
        assert "implicit indexing refused" in record.detail

    def test_sync_unknown_provider_fails_cleanly(self, repo):
        rc = cli_main(["--root", str(repo), "providers", "sync", "gitnexus"])
        assert rc == 1


class TestRegistryAdapterProbe:
    @requires_path_spawned_cbm
    def test_codebase_memory_probed_via_adapter(self, repo, bin_dir, monkeypatch):
        from sot_graph.config import load_config
        from sot_graph.providers_registry import detect_providers

        make_cbm_fake(bin_dir, version="9.9.9-fake")
        monkeypatch.setenv("PATH", str(bin_dir))
        cfg = load_config(str(repo), overrides={"allow_external": True})
        statuses = detect_providers(str(repo), cfg)
        cbm = next(s for s in statuses if s.name == "codebase-memory")
        assert cbm.installed and cbm.healthy
        assert cbm.version == "9.9.9-fake"
        assert cbm.probe_engine == "adapter"
