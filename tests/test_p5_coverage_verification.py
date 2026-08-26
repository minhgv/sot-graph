"""P5 — coverage model, completeness engine, language-aware verification.

Locks:
- Coverage states derive from the persisted parser outcome + live disk
  state (indexed/parsed/partial/skipped/excluded/stale/unknown), never
  from result counts; storage errors degrade to basis=unknown.
- Completeness discounts declared gap families per capability and is
  None when unmeasurable; zero-result searches carry the coverage note
  so absence is only claimed within covered scope.
- verify_subject is language-aware (S6): Python via the real ast,
  shipped grammars via tree-sitter, unknown languages ABSTAIN from an
  exact definition verdict — a Python-shaped regex never confirms a
  definition in another language.
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from sot_graph.assurance.coverage import (
    GAP_TAXONOMY,
    CoverageState,
    completeness,
    coverage_note,
    repo_coverage,
)
from sot_graph.providers.verification import (
    NOT_APPLICABLE,
    SPAN_MISMATCH,
    VERIFIED,
    verify_subject,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture(scope="module")
def covered_repo(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("covrepo")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text(
        "def run():\n    return 1\n", encoding="utf-8"
    )
    (repo / "src" / "broken.ts").write_text(
        "export class Ok {\n    m(): number { return 1; }\n}\n", encoding="utf-8"
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")
    subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo), "reconcile"],
        check=True, cwd=repo, capture_output=True,
    )
    return repo


def _db_of(repo: Path):
    from sot_graph.db import Database

    return Database(str(repo / ".sot" / "sot.db"))


class TestCoverageStates:
    def test_reconcile_persists_parser_outcome(self, covered_repo):
        db = _db_of(covered_repo)
        try:
            rows = dict(
                (os.path.relpath(p, str(covered_repo)).replace(os.sep, "/"), o)
                for p, o in db.conn.execute(
                    "SELECT path, parser_outcome FROM file_journal"
                ).fetchall()
            )
            assert rows.get("src/app.py") in ("COMPLETE", "VALID_EMPTY")
            assert rows.get("src/broken.ts") == "COMPLETE"
        finally:
            db.close()

    def test_states_and_totals(self, covered_repo):
        db = _db_of(covered_repo)
        try:
            report = repo_coverage(db, str(covered_repo))
            assert report.basis == "measured"
            states = {f.path: f.state for f in report.files}
            assert states["src/app.py"] == CoverageState.INDEXED
            assert states["src/broken.ts"] == CoverageState.INDEXED
            assert report.totals["indexed"] == 2
            assert report.covered_fraction == 1.0
        finally:
            db.close()

    def test_stale_when_disk_changes(self, covered_repo):
        (covered_repo / "src" / "app.py").write_text(
            "def run():\n    return 2\n", encoding="utf-8"
        )
        try:
            db = _db_of(covered_repo)
            report = repo_coverage(db, str(covered_repo))
            states = {f.path: f.state for f in report.files}
            assert states["src/app.py"] == CoverageState.STALE
            assert "parser-failed" in report.gaps  # stale honestly reported
            comp = completeness(report, "symbols")
            assert comp is not None and comp < 1.0
        finally:
            db.close()
            (covered_repo / "src" / "app.py").write_text(
                "def run():\n    return 1\n", encoding="utf-8"
            )

    def test_generated_paths_excluded(self, tmp_path):
        from sot_graph.db import Database

        db = Database(str(tmp_path / "sot.db"))
        try:
            db.conn.execute(
                "INSERT INTO file_journal (path,sha256,size,mtime_ms,"
                "reconciled_at,parser_outcome) VALUES "
                "('node_modules/x/index.js','h',1,1,1,'COMPLETE')"
            )
            db.conn.commit()
            report = repo_coverage(db, str(tmp_path))
            assert report.files[0].state == CoverageState.EXCLUDED
            assert "generated" in report.gaps
        finally:
            db.close()

    def test_unknown_scope_path_reported_honestly(self, tmp_path):
        from sot_graph.db import Database

        db = Database(str(tmp_path / "sot.db"))
        try:
            report = repo_coverage(db, str(tmp_path), paths=["never/scanned.rs"])
            assert report.files[0].state == CoverageState.UNKNOWN
            assert report.basis == "measured"
        finally:
            db.close()

    def test_storage_error_degrades_to_unknown(self):
        class Boom:
            conn = None

        report = repo_coverage(Boom(), "/nonexistent")
        assert report.basis == "unknown"
        assert completeness(report, "callgraph") is None
        assert "UNKNOWN" in coverage_note(report)
    def test_capability_selects_gap_families(self):
        from sot_graph.assurance.coverage import CoverageReport, FileCoverage

        file_ok = FileCoverage(path="a.py", state=CoverageState.INDEXED,
                               language="python")
        report = CoverageReport(
            basis="measured",
            files=[file_ok],
            totals={"indexed": 1},
            gaps=["dynamic-dispatch", "parser-partial"],
        )
        # symbols capability ignores behavioural gaps -> higher score
        sym = completeness(report, "symbols")
        call = completeness(report, "callgraph")
        assert sym is not None and call is not None
        assert sym > call
        # empty gap report on full coverage stays complete
        clean = CoverageReport(basis="measured", files=[file_ok],
                               totals={"indexed": 1})
        assert completeness(clean, "callgraph") == 1.0
        for code in ("dynamic-dispatch", "reflection", "di",
                     "framework-routing", "macros", "fn-pointers",
                     "generated", "cross-repo", "parser-partial",
                     "parser-failed", "unresolved-edge"):
            assert code in GAP_TAXONOMY


class TestZeroResultIsNotNegativeClaim:
    def test_empty_search_carries_coverage_note(self, covered_repo):
        out = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root", str(covered_repo),
             "search", "zzz_nothing", "--limit", "3"],
            check=True, cwd=covered_repo, capture_output=True, text=True,
        )
        assert "No verified matching knowledge found" in out.stdout
        assert "coverage:" in out.stdout
        assert "within covered scope" in out.stdout

    def test_mcp_search_response_has_coverage(self, covered_repo):
        from sot_graph.mcp_service import McpService

        service = McpService(str(covered_repo / ".sot" / "sot.db"),
                             str(covered_repo))
        res = service.search("zzz_nothing")
        assert res["coverage"]["basis"] == "measured"
        assert res["coverage"]["note"].startswith("coverage:")
        res2 = service.search("run")
        assert res2["coverage"]["basis"] == "measured"


class TestLanguageAwareVerification:
    def _subject(self, tmp_path, rel, name, kind, start, end):
        from types import SimpleNamespace

        return SimpleNamespace(
            path=rel, qualified_name=name, kind=kind,
            start_line=start, end_line=end,
        )

    def test_python_definition_via_real_ast(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("def run():\n    return 1\n", encoding="utf-8")
        out = verify_subject(
            self._subject(tmp_path, "m.py", "m.run", "function", 1, 1),
            str(tmp_path),
        )
        assert out.status == VERIFIED

    def test_python_span_without_definition_mismatches(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("def run():\n    return run\n", encoding="utf-8")
        out = verify_subject(
            self._subject(tmp_path, "m.py", "m.run", "function", 2, 2),
            str(tmp_path),
        )
        assert out.status == SPAN_MISMATCH

    def test_typescript_definition_via_tree_sitter(self, tmp_path):
        f = tmp_path / "svc.ts"
        f.write_text(
            "export class Box {\n    m(): number { return 1; }\n}\n",
            encoding="utf-8",
        )
        out = verify_subject(
            self._subject(tmp_path, "svc.ts", "Box", "class", 1, 3),
            str(tmp_path),
        )
        assert out.status == VERIFIED

    def test_go_method_definition_via_tree_sitter(self, tmp_path):
        f = tmp_path / "w.go"
        f.write_text(
            "package w\n\ntype W struct{}\n\nfunc (w *W) Do() int { return 1 }\n",
            encoding="utf-8",
        )
        out = verify_subject(
            self._subject(tmp_path, "w.go", "W.Do", "method", 5, 5),
            str(tmp_path),
        )
        assert out.status == VERIFIED

    def test_no_grammar_language_abstains_not_confirms(self, tmp_path, monkeypatch):
        f = tmp_path / "weird.zig"
        f.write_text("pub fn run() void {}\n", encoding="utf-8")
        # Simulate a language whose grammar is not installed.
        from sot_graph.providers import verification as v

        monkeypatch.setattr(
            v, "_tree_sitter_defines", lambda *a, **k: None
        )
        out = verify_subject(
            self._subject(tmp_path, "weird.zig", "run", "function", 1, 1),
            str(tmp_path),
        )
        assert out.status == NOT_APPLICABLE
        assert any("S6" in g for g in out.known_gaps)
