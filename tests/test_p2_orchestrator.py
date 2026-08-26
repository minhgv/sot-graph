"""P2 — shared assurance orchestrator.

CLI and MCP must drive ONE engine: the same request against the same
snapshot yields the same canonical evidence shape (parity digest), the
federation spec semantics stay exact (builtin/auto/prefer:/require:/all),
config ``providers_mode = "auto"`` takes effect without repeating the flag,
and a dead external provider never breaks builtin in auto/prefer mode.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sot_graph.assurance import (  # noqa: E402
    assured_query_context,
    effective_provider_spec,
    federated_extras,
    parse_provider_spec,
)
from sot_graph.db import Database  # noqa: E402
from sot_graph.mcp_service import McpService  # noqa: E402
from sot_graph.reconciler import Reconciler  # noqa: E402


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True, capture_output=True,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "app.py").write_text(
        "def target():\n    return 1\n\n\ndef caller():\n    return target()\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    db = Database(str(repo / ".sot" / "sot.db"))
    try:
        Reconciler(db, str(repo)).reconcile()
    finally:
        db.close()
    return repo


def _digest(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class TestProviderSpecParsing:
    @pytest.mark.parametrize("value,expected", [
        (None, ("builtin", None)),
        ("builtin", ("builtin", None)),
        ("auto", ("auto", None)),
        ("all", ("all", None)),
        ("prefer:codebase-memory", ("prefer", "codebase-memory")),
        ("require:codebase-memory", ("require", "codebase-memory")),
    ])
    def test_valid_specs(self, value, expected):
        assert parse_provider_spec(value) == expected

    @pytest.mark.parametrize("value", ["", "prefer:", "require:", "prefer-no-colon", "bogus:x", "magic"])
    def test_invalid_specs_raise(self, value):
        with pytest.raises(ValueError):
            parse_provider_spec(value)


class TestEffectiveSpec:
    def test_explicit_wins(self):
        assert effective_provider_spec("prefer:x", "manual", True) == "prefer:x"
        assert effective_provider_spec("builtin", "auto", True) == "builtin"

    def test_config_auto_applies_without_flag(self):
        # W5/G6.1: providers_mode=auto takes effect without --provider.
        assert effective_provider_spec(None, "auto", True) == "auto"

    def test_auto_stays_builtin_without_allow_external(self):
        assert effective_provider_spec(None, "auto", False) is None
        assert effective_provider_spec(None, "manual", True) is None


class TestBuiltinUntouched:
    def test_builtin_spec_returns_none_without_spawning(self, repo, monkeypatch):
        def boom(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("external process spawned in builtin mode")

        import sot_graph.proc as proc_mod
        import sot_graph.providers.codebase_memory as cm_mod
        monkeypatch.setattr(proc_mod, "run_command", boom)
        monkeypatch.setattr(cm_mod, "run_command", boom)
        assert federated_extras(None, str(repo), "usages", "target") is None
        assert federated_extras("builtin", str(repo), "explore", "target") is None


class TestDeadProviderDegrades:
    def test_auto_with_missing_binary_warns_and_falls_back(self, repo, monkeypatch):
        # PATH without any codebase-memory binary: probe reports uninstalled.
        monkeypatch.setenv("PATH", "")
        cfg_dir = repo / ".sot"
        (cfg_dir / "config.toml").write_text(
            "allow_external = true\n", encoding="utf-8"
        )
        fed = federated_extras("auto", str(repo), "usages", "target")
        assert fed["fail_message"] is None, "auto never fails closed"
        assert any("queryable" in w or "unavailable" in w for w in fed["warnings"])
        assert fed["candidates"] == []

    def test_prefer_with_missing_binary_warns_and_falls_back(self, repo, monkeypatch):
        monkeypatch.setenv("PATH", "")
        cfg_dir = repo / ".sot"
        (cfg_dir / "config.toml").write_text(
            "allow_external = true\n", encoding="utf-8"
        )
        fed = federated_extras("prefer:codebase-memory", str(repo), "usages", "target")
        assert fed is not None
        assert fed["fail_message"] is None
        assert any("unavailable" in w for w in fed["warnings"])

    def test_require_with_missing_binary_fails_closed(self, repo, monkeypatch):
        monkeypatch.setenv("PATH", "")
        cfg_dir = repo / ".sot"
        (cfg_dir / "config.toml").write_text(
            "allow_external = true\n", encoding="utf-8"
        )
        fed = federated_extras("require:codebase-memory", str(repo), "usages", "target")
        assert fed is not None
        assert fed["fail_message"] and "failing closed" in fed["fail_message"]

    def test_require_blocked_by_config_exit_code_is_stable(self, repo, monkeypatch):
        from sot_graph.cli import main as cli_main

        (repo / ".sot" / "config.toml").write_text(
            "allow_external = false\n", encoding="utf-8"
        )
        rc = cli_main([
            "--root", str(repo), "usages", "target",
            "--provider", "require:codebase-memory", "--json",
        ])
        assert rc == 2, "require fail-closed must exit 2 on every surface"

class TestCliMcpParity:
    """Same request + snapshot -> same canonical evidence digest (CLI vs MCP).

    Both surfaces share assurance.assured_query_context; the canonical part
    of the evidence (snapshot descriptor + stale files) must be identical.
    """

    def test_explore_assurance_digest_matches(self, repo):
        db = Database(str(repo / ".sot" / "sot.db"))
        try:
            row = db.conn.execute(
                "SELECT path FROM graph_nodes WHERE symbol = 'target' LIMIT 1"
            ).fetchone()
            assert row is not None
            cited = [row[0]]
            snap_cli, stale_cli = assured_query_context(db, str(repo), cited)
        finally:
            db.close()

        service = McpService(str(repo / ".sot" / "sot.db"), str(repo))
        res = service.usages("target")
        snap_mcp = res["snapshot"]
        stale_mcp = res["stale_files"]

        assert _digest(snap_cli) == _digest(snap_mcp), (
            "CLI and MCP must derive identical snapshot descriptors from one engine"
        )
        assert stale_cli == stale_mcp == []

    def test_mcp_usages_carries_assurance_fields(self, repo):
        service = McpService(str(repo / ".sot" / "sot.db"), str(repo))
        res = service.usages("target")
        assert set(res) >= {"snapshot", "stale_files"}
        assert res["snapshot"]["commit_sha"]
        assert res["callers"], "builtin callers preserved behind MCP"

    def test_mcp_explore_carries_assurance_fields(self, repo):
        service = McpService(str(repo / ".sot" / "sot.db"), str(repo))
        res = service.explore("target")
        assert set(res) >= {"snapshot", "stale_files"}
        assert res["relations"]

    def test_mcp_diff_impact_carries_assurance_fields(self, repo):
        (repo / "extra.py").write_text("def another():\n    return 2\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "second")
        service = McpService(str(repo / ".sot" / "sot.db"), str(repo))
        res = service.diff_impact(target="HEAD~1", format="json")
        assert set(res) >= {"snapshot", "stale_files"}


class TestStaleDetectionShared:
    def test_mcp_detects_stale_file_without_ledger_write(self, repo):
        # Change a cited file after reconcile: MCP must report it stale.
        (repo / "app.py").write_text(
            "def target():\n    return 2\n\n\ndef caller():\n    return target()\n",
            encoding="utf-8",
        )
        service = McpService(str(repo / ".sot" / "sot.db"), str(repo))
        res = service.usages("target")
        assert "app.py" in res["stale_files"], "stale cited file must surface via MCP"


class TestOrchestratorModuleBoundaries:
    def test_cli_has_no_private_orchestration_helpers(self):
        import sot_graph.cli as cli

        gone = [
            "_federation_plan", "_run_federated_query", "_parse_provider_spec",
            "_supports_capability", "_cbm_candidates_from_outcome",
            "_target_conflicts", "_assured_query_context", "_stale_files_warning",
            "_envelope_fed_kwargs", "_resolve_symbol",
        ]
        for name in gone:
            assert not hasattr(cli, name), f"cli.{name} must live in assurance, not cli"

    def test_assurance_public_api(self):
        import sot_graph.assurance as assurance

        for name in [
            "assured_query_context", "resolve_symbol", "stale_files_warning",
            "federation_plan", "run_federated_query", "federated_extras",
            "cbm_candidates_from_outcome", "target_conflicts",
            "envelope_fed_kwargs", "parse_provider_spec",
            "effective_provider_spec", "supports_capability",
        ]:
            assert callable(getattr(assurance, name)), f"assurance.{name} missing"
