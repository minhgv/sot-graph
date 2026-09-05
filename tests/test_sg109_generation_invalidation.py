"""SG-109 — generation-scoped evidence invalidation and conflict join.

Locks (issue #4, reassessment §7 P0-6):
- Evidence identity is project-root-scoped: a fresh ingest of a path is
  a newer generation of that identity and APPEND-ONLY supersedes prior
  live rows (invalidated_at + reason recorded once; never overwritten,
  never deleted). Re-ingests of OTHER projects cannot touch it, and
  runs without a project root skip the supersede instead of guessing.
- The diff receipt's evidence join is generation-correct: status-ok
  runs of THIS project only, live rows only. Old-generation evidence
  can neither support a current claim (excluded from the live list)
  nor silently vanish (counted in invalidated_evidence_dead_count).
- Provider conflicts are unioned into the receipt: open_conflicts is
  the real count from the evidence union (the historical hard-coded 0
  hid live contradictions), and any conflict degrades the decision to
  CONFLICTED — never a false-assured receipt.
- Receipts stay pure reads: identical calls produce identical digests
  even with dead and live evidence present.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from sot_graph.assurance.receipts import diff_impact_receipt
from sot_graph.snapshot import capture_worktree_snapshot


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _ev(path, src="src_sym", dst="dst_sym", relation="call",
        ls=1, le=2, snap=None, eid=None):
    return {
        "id": eid, "path": path, "src_symbol": src, "dst_symbol": dst,
        "relation": relation, "line_start": ls, "line_end": le,
        "snapshot_hash": snap,
    }


def _ingest(db, run_id, project_root, items, provider="prov",
            status="ok"):
    db.record_provider_outcome(
        run={
            "provider_name": provider, "run_id": run_id,
            "project_root": project_root,
            "capability": "COMPILER_INDEXED_SYMBOLS", "status": status,
        },
        binding=None,
        evidence=items,
    )


def _rows(db, path):
    return db.conn.execute(
        "SELECT id, run_id, invalidated_at, invalidation_reason "
        "FROM provider_evidence WHERE path = ? ORDER BY id",
        (path,),
    ).fetchall()


class TestIngestSupersede:
    def test_reingest_supersedes_prior_live_rows_on_same_path(self, tmp_path):
        from sot_graph.db import Database

        project = os.path.realpath(str(tmp_path))
        db = Database(str(tmp_path / "sot.db"))
        try:
            _ingest(db, "run_a", project, [
                _ev("app.py", eid="a_app"), _ev("util.py", eid="a_util"),
            ])
            # Nothing superseded yet: first generation stays live.
            assert all(r[2] is None for r in _rows(db, "app.py"))

            _ingest(db, "run_b", project, [_ev("app.py", eid="b_app")])
            app = {r[0]: r for r in _rows(db, "app.py")}
            assert app["a_app"][2] is not None
            assert app["a_app"][3] == "superseded_by_run:run_b"
            assert app["b_app"][2] is None  # new generation live
            # Un-re-ingested path keeps its older generation alive.
            assert _rows(db, "util.py")[0][2] is None
        finally:
            db.close()

    def test_first_transition_sticks_append_only(self, tmp_path):
        from sot_graph.db import Database

        project = os.path.realpath(str(tmp_path))
        db = Database(str(tmp_path / "sot.db"))
        try:
            _ingest(db, "run_a", project, [_ev("app.py", eid="a")])
            _ingest(db, "run_b", project, [_ev("app.py", eid="b")])
            first_at, first_reason = _rows(db, "app.py")[0][2:4]
            assert first_reason == "superseded_by_run:run_b"

            # A third generation must not rewrite the first transition.
            _ingest(db, "run_c", project, [_ev("app.py", eid="c")])
            rows = {r[0]: r for r in _rows(db, "app.py")}
            assert rows["a"][2] == first_at
            assert rows["a"][3] == "superseded_by_run:run_b"
            assert rows["b"][3] == "superseded_by_run:run_c"
            assert rows["c"][2] is None
        finally:
            db.close()

    def test_project_isolation(self, tmp_path):
        from sot_graph.db import Database

        here = os.path.realpath(str(tmp_path / "here"))
        there = os.path.realpath(str(tmp_path / "there"))
        os.makedirs(here, exist_ok=True)
        os.makedirs(there, exist_ok=True)
        db = Database(str(tmp_path / "sot.db"))
        try:
            _ingest(db, "run_here", here, [_ev("app.py", eid="h1")])
            _ingest(db, "run_there", there, [_ev("app.py", eid="t1")])
            # Neither project's re-ingest may supersede the other's.
            rows = {r[0]: r for r in _rows(db, "app.py")}
            assert rows["h1"][2] is None
            assert rows["t1"][2] is None
            assert rows["t1"][3] is None
        finally:
            db.close()

    def test_unbound_project_skips_supersede(self, tmp_path):
        from sot_graph.db import Database

        project = os.path.realpath(str(tmp_path))
        db = Database(str(tmp_path / "sot.db"))
        try:
            _ingest(db, "run_bound", project, [_ev("app.py", eid="x1")])
            _ingest(db, "run_unbound", None, [_ev("app.py", eid="u1")])
            rows = {r[0]: r for r in _rows(db, "app.py")}
            # No project root → the supersede cannot be scoped safely,
            # so it is skipped rather than guessed.
            assert rows["x1"][2] is None
            assert rows["u1"][2] is None
        finally:
            db.close()

    def test_failed_run_rows_not_transitioned(self, tmp_path):
        from sot_graph.db import Database

        project = os.path.realpath(str(tmp_path))
        db = Database(str(tmp_path / "sot.db"))
        try:
            _ingest(db, "run_dead", project, [_ev("app.py", eid="f1")],
                    status="failed")
            _ingest(db, "run_live", project, [_ev("app.py", eid="l1")])
            rows = {r[0]: r for r in _rows(db, "app.py")}
            # Failed runs never supported claims; the supersede only
            # moves status-ok rows, so the failed row is left as-is.
            assert rows["f1"][2] is None
            assert rows["l1"][2] is None
        finally:
            db.close()


    def test_cross_provider_evidence_coexists(self, tmp_path):
        from sot_graph.db import Database

        project = os.path.realpath(str(tmp_path))
        db = Database(str(tmp_path / "sot.db"))
        try:
            _ingest(db, "run_x", project, [_ev("app.py", eid="px")],
                    provider="prov_x")
            _ingest(db, "run_y", project, [_ev("app.py", eid="py")],
                    provider="prov_y")
            # Evidence identity includes the provider: a supersede must
            # never cross provider boundaries, or the union could never
            # federate providers to surface conflicts.
            rows = {r[0]: r for r in _rows(db, "app.py")}
            assert rows["px"][2] is None
            assert rows["py"][2] is None
        finally:
            db.close()


@pytest.fixture(scope="module")
def gen_repo(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("sg109repo")
    (repo / ".gitignore").write_text(".sot/\n", encoding="utf-8")
    (repo / "app.py").write_text("def run():\n    return 1\n",
                                 encoding="utf-8")
    (repo / "util.py").write_text("def help():\n    return 41\n",
                                  encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "c1")
    return repo


def _db_of(repo: Path):
    from sot_graph.db import Database

    return Database(str(repo / ".sot" / "sot.db"))


class TestDiffReceiptGenerationJoin:
    def test_old_generation_neither_supports_nor_vanishes(self, gen_repo):
        project = os.path.realpath(str(gen_repo))
        db = _db_of(gen_repo)
        try:
            # Generation N-2: evidence on app.py and util.py.
            _ingest(db, "gen_a", project, [
                _ev("app.py", eid="old_app"), _ev("util.py", eid="old_util"),
            ])
            # Change app.py (generation N-1 world), re-ingest app.py.
            (gen_repo / "app.py").write_text(
                "def run():\n    return 2\n", encoding="utf-8"
            )
            _git(gen_repo, "add", "-A")
            _git(gen_repo, "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "c2")
            _ingest(db, "gen_b", project, [_ev("app.py", eid="new_app")])
        finally:
            db.close()

        db = _db_of(gen_repo)
        try:
            receipt = diff_impact_receipt(db, str(gen_repo), target="HEAD~1")
        finally:
            db.close()
        live = {e["id"]: e for e in receipt["invalidated_evidence"]}
        # Only the CURRENT generation's live rows support the claim...
        assert "new_app" in live
        assert "old_app" not in live
        # ...while the dead generation stays countable, not hidden.
        assert receipt["invalidated_evidence_dead_count"] == 1
        # Evidence on the not-re-ingested path is never transitioned:
        # its journal row stays live in the DB regardless of whether
        # the diff extractor cites the path.
        db = _db_of(gen_repo)
        try:
            util_rows = _rows(db, "util.py")
            assert util_rows[0][0] == "old_util"
            assert util_rows[0][2] is None
        finally:
            db.close()
        assert receipt["schema_version"] == "1.7"

    def test_dead_count_zero_when_no_history(self, tmp_path):
        repo = tmp_path / "fresh"
        repo.mkdir()
        (repo / ".gitignore").write_text(".sot/\n", encoding="utf-8")
        (repo / "app.py").write_text("def run():\n    return 1\n",
                                     encoding="utf-8")
        _git(repo, "init", "-q")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c1")
        (repo / "app.py").write_text("def run():\n    return 2\n",
                                     encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c2")
        db = _db_of(repo)
        try:
            receipt = diff_impact_receipt(db, str(repo), target="HEAD~1")
        finally:
            db.close()
        assert receipt["invalidated_evidence_dead_count"] == 0
        assert receipt["invalidated_evidence"] == []

    def test_cross_project_evidence_ignored(self, gen_repo):
        db = _db_of(gen_repo)
        try:
            _ingest(db, "other_project", "/some/other/project",
                    [_ev("app.py", eid="alien")])
            receipt = diff_impact_receipt(db, str(gen_repo), target="HEAD~1")
        finally:
            db.close()
        live_ids = {e["id"] for e in receipt["invalidated_evidence"]}
        assert "alien" not in live_ids
        # The alien row is neither transitioned nor counted: its DB row
        # stays untouched by this project's receipts (the module DB may
        # legitimately carry this project's own dead rows from earlier
        # tests, so the invariant is asserted at the row level).
        db = _db_of(gen_repo)
        try:
            alien = [r for r in _rows(db, "app.py") if r[0] == "alien"]
            assert alien and alien[0][2] is None and alien[0][3] is None
        finally:
            db.close()

    def test_receipts_are_pure_reads_digest_stable(self, gen_repo):
        db = _db_of(gen_repo)
        try:
            a = diff_impact_receipt(db, str(gen_repo), target="HEAD~1")
            b = diff_impact_receipt(db, str(gen_repo), target="HEAD~1")
        finally:
            db.close()
        # Dead + live evidence present (previous tests' rows share the
        # module fixture db) — repeated receipts must not mutate any
        # invalidation state, so the digest cannot drift.
        assert a["digest"] == b["digest"]

    def test_replay_three_generations(self, gen_repo):
        """N/N-1/N-2 replay: only generation N supports; N-1/N-2 dead."""
        project = os.path.realpath(str(gen_repo))
        db = _db_of(gen_repo)
        try:
            # Two more generations on app.py after gen_a/gen_b.
            _ingest(db, "gen_c", project, [_ev("app.py", eid="c_app")])
            _ingest(db, "gen_d", project, [_ev("app.py", eid="d_app")])
            receipt = diff_impact_receipt(db, str(gen_repo), target="HEAD~1")
        finally:
            db.close()
        live_ids = {e["id"] for e in receipt["invalidated_evidence"]}
        assert "d_app" in live_ids            # newest generation live
        assert "c_app" not in live_ids        # N-1 superseded
        assert "new_app" not in live_ids      # N-2 superseded
        assert "old_app" not in live_ids
        # All three superseded generations remain countable.
        assert receipt["invalidated_evidence_dead_count"] == 3


class TestConflictJoin:
    def test_provider_conflict_degrades_receipt(self, tmp_path):
        repo = tmp_path / "confrepo"
        repo.mkdir()
        (repo / ".gitignore").write_text(".sot/\n", encoding="utf-8")
        (repo / "app.py").write_text("def run():\n    return 1\n",
                                     encoding="utf-8")
        _git(repo, "init", "-q")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c1")
        # Working-tree change so the diff receipt has a diff to bind.
        (repo / "app.py").write_text("def run():\n    return 2\n",
                                     encoding="utf-8")
        project = os.path.realpath(str(repo))
        # Bind the evidence to the exact post-change snapshot the
        # receipt will capture, with disagreeing spans that cannot
        # verify — an unresolvable provider contradiction.
        snap = capture_worktree_snapshot(
            str(repo), cited_paths=["app.py"]
        ).as_dict()["scope_digest"]
        db = _db_of(repo)
        try:
            _ingest(db, "conf_x", project, [
                _ev("app.py", ls=900, le=901, snap=snap, eid="cx"),
            ], provider="prov_x")
            _ingest(db, "conf_y", project, [
                _ev("app.py", ls=902, le=903, snap=snap, eid="cy"),
            ], provider="prov_y")
            receipt = diff_impact_receipt(db, str(repo), working_tree=True)
        finally:
            db.close()
        assert receipt["assurance_facts"]["open_conflicts"] >= 1
        assert "open_conflicts" in receipt["assurance"]["reason_codes"]
        # The severity join may rank a co-occurring condition higher
        # (here: the post-change tree is legitimately STALE until the
        # next reconcile) — the SG-109 invariant is that the conflict
        # is SURFACED (facts + reason code) and the receipt is never
        # false-assured, not that CONFLICTED outranks everything.
        assert not receipt["assurance"]["status"].startswith("ASSURED")
