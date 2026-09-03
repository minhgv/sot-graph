"""P8 — OMP integration E2E: the full assured-change loop.

Exit gate (plan §P8): on one fixture repository,

    scope receipt → edit → targeted tests → diff-impact receipt →
    reconcile → reviewer asserts

must run green end-to-end, builtin-only (no external provider
configured), with assurance degraded honestly rather than faked.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

REPO_PY = """import util


def run():
    return util.help() + 1
"""

TEST_PY = """from app import run


def test_run():
    assert run() == 43
"""


def _sot(repo: Path, *args: str, check: bool = True):
    out = subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo), *args],
        cwd=repo, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if check:
        assert out.returncode == 0, out.stderr
    return out


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture()
def e2e_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "e2e"
    repo.mkdir()
    (repo / "app.py").write_text(REPO_PY, encoding="utf-8")
    (repo / "util.py").write_text("def help():\n    return 42\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text(TEST_PY, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "c1")
    _sot(repo, "reconcile")
    return repo


class TestAssuredChangeLoop:
    def test_full_loop_builtin_only(self, e2e_repo: Path):
        # 1. PRE-change scope receipt (operator gate).
        pre = json.loads(
            _sot(e2e_repo, "scope-receipt", "run", "--json").stdout
        )
        assert pre["proof_scope"] == "pre_change_only"
        assert pre["assurance"]["status"] == "ASSURED_WITHIN_SCOPE"
        assert pre["assurance"]["reason_codes"] == []
        # builtin-only degradation is stated, not faked
        assert pre["providers"]["runs"] == []
        assert pre["coverage"]["basis"] == "measured"

        # 2. Edit (the change the receipt scoped).
        (e2e_repo / "app.py").write_text(
            "import util\n\n\ndef run():\n    return util.help() + 2\n",
            encoding="utf-8",
        )
        (e2e_repo / "tests" / "test_app.py").write_text(
            "from app import run\n\n\ndef test_run():\n    assert run() == 44\n",
            encoding="utf-8",
        )

        # 3. Targeted tests (candidate set from the receipt).
        candidates = pre["candidate_tests"]
        assert any("test_app" in c for c in candidates)
        targeted = subprocess.run(
            [sys.executable, "-m", "pytest", "-q",
             str(e2e_repo / "tests" / "test_app.py")],
            cwd=e2e_repo, capture_output=True, text=True,
        )
        assert targeted.returncode == 0, targeted.stdout + targeted.stderr

        # 4. POST-change diff receipt binds its own snapshot.
        post = json.loads(
            _sot(e2e_repo, "diff-impact", "--working-tree", "--json").stdout
        )
        # diff-impact CLI payload wraps the engine result; the receipt
        # fields we care about are the P7 additions.
        assert post.get("snapshot") or post.get("post_change_snapshot")
        assert "changed_files" in post

        # 5. Reconcile binds the post-change state.
        _sot(e2e_repo, "reconcile")

        # 6. Reviewer assertion: post-reconcile scope receipt is clean.
        after = json.loads(
            _sot(e2e_repo, "scope-receipt", "run", "--json").stdout
        )
        assert after["stale_files"] == []
        assert after["assurance"]["status"] != "BLOCKED"
        # reviewer cross-check: pre receipt was never post-proof
        assert pre["digest"] != after["digest"]

    def test_blocked_rename_stops_the_loop(self, e2e_repo: Path):
        blocked = _sot(e2e_repo, "scope-receipt", "ghost",
                       "--change-kind", "rename", check=False)
        assert blocked.returncode == 2
        assert "BLOCKED" in blocked.stdout

    def test_omp_rules_installed_reference_receipts(self, tmp_path: Path):
        from sot_graph.adapters import omp as omp_adapter

        installed = omp_adapter.setup_omp(
            tmp_path, global_install=False, workspace_install=True,
        )
        rules = tmp_path / ".omp" / "rules" / "sot-graph.md"
        assert str(rules) in installed
        text = rules.read_text(encoding="utf-8")
        assert "scope-receipt" in text
        assert "Stop-time rule" in text
        assert "closure_decision" in text
        assert "100%" not in text

    def test_omp_skill_and_rules_no_absolute_claims(self, tmp_path: Path):
        from sot_graph.adapters import omp as omp_adapter

        omp_adapter.setup_omp(tmp_path, global_install=False,
                              workspace_install=True)
        for rel in (".omp/rules/sot-graph.md", ".omp/skills/sot-graph/SKILL.md"):
            text = (tmp_path / rel).read_text(encoding="utf-8")
            assert "100%" not in text, rel


class TestMcpAssuranceInputs:
    def test_search_policy_and_budget_params(self, e2e_repo: Path):
        from sot_graph.mcp_service import McpService, McpServiceError

        service = McpService(str(e2e_repo / ".sot" / "sot.db"), str(e2e_repo))
        try:
            res = service.search("run", assurance=True,
                                 provider_policy="prefer_external", budget=5)
            assert res["policy"]["provider_policy"] == "prefer_external"
            assert res["policy"]["builtin_only"] is False
            # Honest fallback: the note states builtin was served because
            # MCP has no external provider wired in.
            assert res["policy"]["note"] is not None
            assert "no external provider is wired into" in res["policy"]["note"]
            assert res["coverage"]["basis"] == "measured"

            lean = service.search("run", assurance=False)
            assert lean["coverage"] is None
            assert lean["policy"]["note"] is None  # builtin_only needs no note

            usages = service.usages("run", provider_policy="builtin_only")
            assert usages["policy"]["builtin_only"] is True
            assert usages["coverage"]["basis"] == "measured"

            with pytest.raises(Exception):
                service.search("run", provider_policy="bogus")

            # require_external fails closed on the builtin-only MCP path.
            with pytest.raises(McpServiceError) as exc:
                service.search("run", provider_policy="require_external")
            assert exc.value.code == "policy_unsatisfiable"
            with pytest.raises(McpServiceError) as exc:
                service.usages("run", provider_policy="require_external")
            assert exc.value.code == "policy_unsatisfiable"
        finally:
            service.close()

    def test_scope_receipt_and_diff_impact_receipt(self, e2e_repo: Path):
        """MCP receipt tools return payload + digest; statuses pass through."""
        from sot_graph.mcp_service import McpService

        service = McpService(str(e2e_repo / ".sot" / "sot.db"), str(e2e_repo))
        try:
            scope = service.scope_receipt("run")
            assert scope["digest"]
            assert "status" in scope["assurance"]
            assert scope["assurance"]["status"] != "BLOCKED"
            assert scope["proof_scope"] == "pre_change_only"

            (e2e_repo / "app.py").write_text(
                "import util\n\n\ndef run():\n    return util.help() + 3\n",
                encoding="utf-8",
            )
            diff = service.diff_impact_receipt("HEAD~1")
            assert diff["digest"]
            assert "status" in diff or "closure_decision" in diff

            import asyncio

            # The worktree changed above, so the receipt digest MUST move
            # (snapshot binding), and the async wrapper must agree with a
            # fresh sync call on the SAME post-edit state.
            post_scope = service.scope_receipt("run")
            assert post_scope["digest"] != scope["digest"]
            async_scope = asyncio.run(service.ascope_receipt("run"))
            assert async_scope["digest"] == post_scope["digest"]
        finally:
            service.close()
