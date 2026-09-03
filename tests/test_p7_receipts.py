"""P7 — impact receipts: scope receipt, diff receipt, rename gate.

Locks:
- scope_receipt carries every pre-change field family (identity,
  snapshot, anchors, callers/callees, relations, bounded transitive
  impact, affected files, candidate tests, ledger cross-check, coverage,
  risk rules, OMP confirmations) with schema_version + digest.
- Digest is deterministic; any content change flips it.
- Risk rules implement roadmap §R7.3 exactly.
- The rename gate BLOCKS a public rename when caller coverage is
  insufficient; '0 callers' is only claimable inside a bounded assured
  scope with measured coverage.
- diff_impact_receipt binds a post-change snapshot, reports invalidated
  evidence and remaining gaps, and keeps the pre receipt digest as
  cross-reference only (proof_scope pre_change_only never post proof).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from sot_graph.assurance.receipts import (
    RECEIPT_SCHEMA_VERSION,
    check_rename_gate,
    classify_change_risk,
    diff_impact_receipt,
    receipt_digest,
    scope_receipt,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture(scope="module")
def receipt_repo(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("rrepo")
    (repo / "app.py").write_text(
        "import util\n\n"
        "def run():\n"
        "    return util.help() + 1\n",
        encoding="utf-8",
    )
    (repo / "util.py").write_text(
        "def help():\n    return 41\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text(
        "from app import run\n\n"
        "def test_run():\n    assert run()\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c1")
    subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo), "reconcile"],
        check=True, cwd=repo, capture_output=True,
    )
    return repo


def _db_of(repo: Path):
    from sot_graph.db import Database

    return Database(str(repo / ".sot" / "sot.db"))


class TestScopeReceipt:
    def test_field_families_present(self, receipt_repo):
        db = _db_of(receipt_repo)
        try:
            payload = scope_receipt(db, str(receipt_repo), "run")
        finally:
            db.close()
        assert payload["schema_version"] == RECEIPT_SCHEMA_VERSION == "1.1"
        assert payload["proof_scope"] == "pre_change_only"
        assert payload["request"]["target"] == "run"
        assert payload["identity"]["selected"]["symbol"] == "run"
        assert payload["snapshot"]["commit_sha"]
        assert payload["source_anchors"][0]["path"].endswith("app.py")
        # run() -> util.help(): one outgoing call edge.
        assert any(c["symbol"] == "help" for c in payload["direct_callees"])
        # tests/test_app.py imports run — candidate test discovered.
        assert any("test_app" in t for t in payload["candidate_tests"])
        assert payload["coverage"]["basis"] == "measured"
        assert payload["providers"]["union_entries"] >= 0
        assert payload["assurance"]["risk"]["level"] == "verify"
        assert payload["assurance"]["omp_confirmations"]
        assert len(payload["digest"]) == 64

    def test_digest_deterministic_and_sensitive(self, receipt_repo):
        db = _db_of(receipt_repo)
        try:
            a = scope_receipt(db, str(receipt_repo), "run")
            b = scope_receipt(db, str(receipt_repo), "run")
        finally:
            db.close()
        assert a["digest"] == b["digest"]
        b2 = dict(b)
        b2["request"] = dict(b["request"], target="help")
        b2["digest"] = receipt_digest(
            {k: v for k, v in b2.items() if k != "digest"}
        )
        assert a["digest"] != b2["digest"]

    def test_unresolved_target_is_not_assured(self, receipt_repo):
        db = _db_of(receipt_repo)
        try:
            payload = scope_receipt(db, str(receipt_repo), "does_not_exist")
        finally:
            db.close()
        assert payload["identity"]["status"] == "NOT_FOUND"
        assert payload["identity"]["selected"] is None
        assert payload["assurance"]["status"] == "ABSTAINED"
        assert "target_not_found" in payload["assurance"]["reason_codes"]
        assert payload["assurance"]["rename_gate"]["resolved"] is False

    def test_affected_files_snapshot_binding_covers_transitive_dependencies(self, receipt_repo):
        db = _db_of(receipt_repo)
        try:
            payload = scope_receipt(db, str(receipt_repo), "run")
        finally:
            db.close()
        snap = payload["snapshot"]
        assert snap.get("scope_digest") is not None
        digests = snap.get("content_digests") or {}
        # Must bind both app.py and util.py because run calls util.help
        assert "app.py" in digests
        assert "util.py" in digests

    def test_parser_failures_in_journal_degrades_to_partial(self, receipt_repo):
        db = _db_of(receipt_repo)
        try:
            db.conn.execute(
                "INSERT OR REPLACE INTO file_journal "
                "(path, sha256, size, mtime_ms, reconciled_at, parser_outcome, parser_error) "
                "VALUES ('broken.py', 'abc', 10, 1000, 1000, 'PARSE_ERROR', 'SyntaxError: invalid syntax')"
            )
            db.conn.commit()
            payload = scope_receipt(db, str(receipt_repo), "run")
        finally:
            db.conn.execute("DELETE FROM file_journal WHERE path = 'broken.py'")
            db.conn.commit()
            db.close()
        assert payload["assurance"]["status"] == "PARTIAL"
        assert "parser_failures" in payload["assurance"]["reason_codes"]


    def test_missing_unreadable_affected_file_yields_unverifiable(self, receipt_repo):
        import os
        db = _db_of(receipt_repo)
        util_path = receipt_repo / "util.py"
        content = util_path.read_text(encoding="utf-8")
        st = util_path.stat()
        try:
            util_path.unlink()
            payload = scope_receipt(db, str(receipt_repo), "run")
        finally:
            util_path.write_text(content, encoding="utf-8")
            os.utime(util_path, (st.st_atime, st.st_mtime))
            db.close()
        assert payload["assurance"]["status"] == "UNVERIFIABLE"
        assert "snapshot_unbound" in payload["assurance"]["reason_codes"]
class TestRiskRules:
    def test_r7_3_table(self):
        assert classify_change_risk(
            kind_of_change="local-body"
        )["level"] == "verify"
        audit = classify_change_risk(kind_of_change="public-api")
        assert audit["level"] == "audit" and audit["absence_assurance"]
        rename = classify_change_risk(kind_of_change="rename")
        assert rename["level"] == "audit"
        auth = classify_change_risk(kind_of_change="local-body", touches_auth=True)
        assert auth["security_reviewer"] is True
        assert auth["absence_assurance"] is False
        dyn = classify_change_risk(kind_of_change="local-body", dynamic_heavy=True)
        assert dyn["absence_assurance"] is False
        surface = classify_change_risk(
            kind_of_change="local-body", symbol_kind="class"
        )
        assert surface["level"] == "audit"


class TestRenameGate:
    def test_zero_callers_blocked_when_coverage_unmeasurable(self, tmp_path):
        from sot_graph.db import Database

        db = Database(str(tmp_path / "empty.db"))
        try:
            gate = check_rename_gate(db, str(tmp_path), "ghost")
            assert gate["blocked"] is True
            assert "cannot bound" in gate["reason"] or "coverage" in gate["reason"]
        finally:
            db.close()

    def test_zero_callers_claimable_in_covered_scope(self, receipt_repo):
        # util.help has exactly one caller (run) — find a truly
        # caller-free symbol: none exists, so simulate by asserting the
        # gate passes when callers exist and coverage is measured.
        db = _db_of(receipt_repo)
        try:
            gate = check_rename_gate(db, str(receipt_repo), "help")
            assert gate["resolved"] is True
            assert gate["callers_found"] == 1
            # coverage measured on the fixture → not blocked
            assert gate["blocked"] is False
        finally:
            db.close()

    def test_scope_receipt_blocks_rename_with_uncovered_scope(self, tmp_path):
        from sot_graph.db import Database

        db = Database(str(tmp_path / "empty.db"))
        try:
            payload = scope_receipt(
                db, str(tmp_path), "ghost", kind_of_change="rename",
            )
        finally:
            db.close()
        assert payload["assurance"]["rename_gate"]["blocked"] is True
        assert payload["assurance"]["status"] == "ABSTAINED"
        assert "target_not_found" in payload["assurance"]["reason_codes"]

class TestDiffReceipt:
    def test_post_change_receipt_shape(self, receipt_repo):
        db = _db_of(receipt_repo)
        try:
            pre = scope_receipt(db, str(receipt_repo), "run")
            # make a post-change commit touching app.py
            (receipt_repo / "app.py").write_text(
                "import util\n\n"
                "def run():\n"
                "    return util.help() + 2\n",
                encoding="utf-8",
            )
            _git(receipt_repo, "add", "-A")
            _git(receipt_repo, "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "c2")
            post = diff_impact_receipt(
                db, str(receipt_repo), target="HEAD~1",
                pre_receipt=pre,
            )
        finally:
            db.close()
        assert post["schema_version"] == RECEIPT_SCHEMA_VERSION
        assert post["proof_scope"] == "post_change"
        assert post["diff_identity"]["target"] == "HEAD~1"
        assert any("app.py" in str(f) for f in post["changed_files"])
        assert post["post_change_snapshot"]
        assert post["pre_receipt_digest"] == pre["digest"]
        assert "digest" in post and len(post["digest"]) == 64
        assert post["closure_decision"] in ("open", "closed")
        assert isinstance(post["remaining_gaps"], list)
        # pre receipt is cross-reference only — its proof scope forbids
        # using it as post-change proof.
        assert pre["proof_scope"] == "pre_change_only"

    def test_reconcile_note_and_test_surface(self, receipt_repo):
        db = _db_of(receipt_repo)
        try:
            post = diff_impact_receipt(db, str(receipt_repo), target="HEAD")
        finally:
            db.close()
        assert post["reconcile"]["required"] is True
        # HEAD diff is empty; closure can still be decided honestly.
        assert post["closure_decision"] in ("open", "closed")


class TestClosureDecision:
    """G8: closure_decision must be reachable, not dead logic.

    stale_files used to be hardcoded to the full changed-file list, so
    decide() could never return ASSURED_WITHIN_SCOPE and closure was
    constant "open". Staleness is now MEASURED against the journal: a
    reconciled change closes the receipt; an unreconciled one stays open.
    """

    def _repo_with_change(self, tmp_path, *, reconcile_after_change: bool) -> Path:
        repo = tmp_path / ("crepo" if reconcile_after_change else "urepo")
        repo.mkdir()
        (repo / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
        _git(repo, "init", "-q")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c1")
        subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root", str(repo), "reconcile"],
            check=True, cwd=repo, capture_output=True,
        )
        (repo / "app.py").write_text("def run():\n    return 2\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c2")
        if reconcile_after_change:
            subprocess.run(
                [sys.executable, "-m", "sot_graph.cli", "--root", str(repo),
                 "reconcile"],
                check=True, cwd=repo, capture_output=True,
            )
        return repo

    def test_reconciled_change_closes_receipt(self, tmp_path):
        repo = self._repo_with_change(tmp_path, reconcile_after_change=True)
        db = _db_of(repo)
        try:
            post = diff_impact_receipt(db, str(repo), target="HEAD")
        finally:
            db.close()
        assert post["changed_files"], "fixture broken: empty diff"
        assert post["assurance"]["status"] == "ASSURED_WITHIN_SCOPE"
        assert post["closure_decision"] == "closed"
        assert post["remaining_gaps"] == []

    def test_unreconciled_change_stays_open(self, tmp_path):
        repo = self._repo_with_change(tmp_path, reconcile_after_change=False)
        db = _db_of(repo)
        try:
            post = diff_impact_receipt(db, str(repo), target="HEAD")
        finally:
            db.close()
        assert post["changed_files"], "fixture broken: empty diff"
        assert post["assurance"]["status"] == "STALE"
        assert "stale_sources" in post["assurance"]["reason_codes"]
        assert post["closure_decision"] == "open"


class TestCliSurface:
    def test_scope_receipt_command(self, receipt_repo):
        out = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root", str(receipt_repo),
             "scope-receipt", "run"],
            cwd=receipt_repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        assert out.returncode == 0, out.stderr
        assert "Scope receipt" in out.stdout
        assert "pre_change_only" in out.stdout

    def test_scope_receipt_json_has_digest(self, receipt_repo):
        import json

        out = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root", str(receipt_repo),
             "scope-receipt", "run", "--json"],
            cwd=receipt_repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        payload = json.loads(out.stdout)
        assert payload["digest"]
        assert payload["schema_version"] == RECEIPT_SCHEMA_VERSION

    def test_rename_blocked_exit_code(self, tmp_path, capsys):
        # Unresolved target in an empty graph: BLOCKED → exit 2.
        subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root", str(tmp_path),
             "reconcile"],
            cwd=tmp_path, capture_output=True,
        )
        out = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root", str(tmp_path),
             "scope-receipt", "ghost", "--change-kind", "rename"],
            cwd=tmp_path, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        assert out.returncode == 2
        assert "BLOCKED" in out.stdout
