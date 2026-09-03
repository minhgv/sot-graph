"""P0 invariant tests: snapshot content binding + fail-closed ledger + atomic writes.

Invariants from plan/sot-graph-p0-trust-chain-implementation-2026-08-28.md
(Contracts 2 & 4, worker A2):

(a) the same dirty file with different contents yields a different
    ``scope_digest`` (content binding, not just git status);
(b) evidence lacking a snapshot hash or a source path is never
    ``SUPPORTED`` (``UNBOUND``), and unverified spans stay ``UNVERIFIED``;
(c) a ``record_provider_outcome`` failure mid-way leaves no partial
    rows (single-transaction rollback).
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time

import pytest

from sot_graph.db import Database
from sot_graph.snapshot import capture_worktree_snapshot
from sot_graph.assurance.ledger import union_evidence


# ------------------------------------------------------- Contract 2: content binding

def _write(root, rel: str, text: str) -> None:
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)

class TestScopeDigestContentBinding:
    def test_same_file_different_contents_different_scope_digest(self, tmp_path):
        """Invariant (a): scope_digest binds CONTENT, not git status."""
        root = str(tmp_path / "repo")
        os.makedirs(root)
        _write(root, "app.py", "value = 1\n")
        s1 = capture_worktree_snapshot(root, cited_paths=["app.py"])
        _write(root, "app.py", "value = 2\n")
        s2 = capture_worktree_snapshot(root, cited_paths=["app.py"])

        assert s1.scope_digest and s2.scope_digest
        assert s1.scope_digest != s2.scope_digest
        assert s1.content_digests["app.py"] == hashlib.sha256(b"value = 1\n").hexdigest()
        assert s2.content_digests["app.py"] == hashlib.sha256(b"value = 2\n").hexdigest()
        # Identical content -> identical binding (deterministic).
        s3 = capture_worktree_snapshot(root, cited_paths=["app.py"])
        assert s3.scope_digest == s2.scope_digest
        assert s1.algo_version == s2.algo_version == "sha256-v2"

    def test_cited_paths_deduplicated(self, tmp_path):
        root = str(tmp_path / "repo")
        os.makedirs(root)
        _write(root, "a.py", "x = 1\n")
        snap = capture_worktree_snapshot(root, cited_paths=["a.py", "a.py"])
        assert list(snap.content_digests) == ["a.py"]
        assert snap.scope_digest is not None

    def test_unreadable_cited_path_fails_closed(self, tmp_path):
        """Missing/unreadable cited file -> scope_digest unset (fail-closed)."""
        root = str(tmp_path / "repo")
        os.makedirs(root)
        _write(root, "a.py", "x = 1\n")
        snap = capture_worktree_snapshot(
            root, cited_paths=["a.py", "ghost/missing.py"]
        )
        assert snap.scope_digest is None
        assert snap.unreadable == ["ghost/missing.py"]
        d = snap.as_dict()
        assert "scope_digest" not in d
        assert d["unreadable"] == ["ghost/missing.py"]
        # Still a v2 capture — the algorithm ran, it just refused to bind.
        assert d["algo_version"] == "sha256-v2"

    def test_default_capture_stays_v1_status_only(self, tmp_path):
        """No cited_paths -> unchanged legacy behavior (sha256-v1, no fields)."""
        root = str(tmp_path / "repo")
        os.makedirs(root)
        _write(root, "a.py", "x = 1\n")
        snap = capture_worktree_snapshot(root)
        assert snap.algo_version == "sha256-v1"
        assert snap.content_digests == {}
        assert snap.scope_digest is None
        assert snap.unreadable == []
        d = snap.as_dict()
        assert "content_digests" not in d
        assert "scope_digest" not in d
        assert "unreadable" not in d

    def test_v1_and_v2_descriptors_never_collide(self, tmp_path):
        root = str(tmp_path / "repo")
        os.makedirs(root)
        _write(root, "a.py", "x = 1\n")
        v1 = capture_worktree_snapshot(root)
        v2 = capture_worktree_snapshot(root, cited_paths=["a.py"])
        assert v1.algo_version == "sha256-v1"
        assert v2.algo_version == "sha256-v2"
        # Contract 2: content-bound and status-only captures of the same
        # git state must produce distinct descriptor digests.
        assert v1.descriptor_digest != v2.descriptor_digest
        assert v2.as_dict()["scope_digest"] == v2.scope_digest


# --------------------------------------------- Contract 4: fail-closed ledger union

def _seed_union_db(db: Database, rows: list[dict], project_root: Optional[str] = None) -> None:
    """Insert ok runs + evidence rows.

    Row keys: provider, path, src, snap, dst, l1, l2, invalidated, project_root.
    """
    with db.conn:
        for i, r in enumerate(rows):
            rid = f"run_seed_{i}"
            proj_root = r.get("project_root") or project_root
            db.conn.execute(
                "INSERT OR REPLACE INTO provider_runs "
                "(id, provider_name, capability, status, created_at, project_root) "
                "VALUES (?,?,?,?,1,?)",
                (rid, r["provider"], "trace_path", "ok", proj_root),
            )
            db.conn.execute(
                "INSERT OR REPLACE INTO provider_evidence "
                "(id, run_id, provider_name, path, relation, src_symbol, "
                "dst_symbol, line_start, line_end, snapshot_hash, "
                "invalidated_at, recorded_at, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)",
                (
                    f"ev_seed_{i}", rid, r["provider"], r["path"], "defines",
                    r["src"], r.get("dst"), r.get("l1"), r.get("l2"),
                    r.get("snap", ""),
                    int(time.time()) if r.get("invalidated") else None, 1,
                ),
            )


def _by_src(out: list[dict], src: str) -> dict:
    matches = [
        e for e in out
        if "error" not in e and e["identity"]["src"] == src
    ]
    assert matches, f"no union entry for src={src!r} in {out!r}"
    return matches[0]


@pytest.fixture()
def union_repo(tmp_path):
    """A plain directory with one verifiable Python file (no git needed)."""
    root = str(tmp_path / "repo")
    os.makedirs(root)
    with open(os.path.join(root, "app.py"), "w", encoding="utf-8") as fh:
        fh.write("def run_1():\n    return 1\n")
    return root


class TestFailClosedUnion:
    def test_verified_span_is_supported(self, union_repo, tmp_path):
        db = Database(str(tmp_path / "sot.db"))
        try:
            _seed_union_db(db, [{
                "provider": "cbm", "path": "app.py", "src": "run_1",
                "snap": "s1", "l1": 1, "l2": 2,
            }], project_root=union_repo)
            out = union_evidence(db, union_repo)
            entry = _by_src(out, "run_1")
            assert entry["status"] == "SUPPORTED"
            assert entry["span"] == [1, 2]
            assert entry["conflict"] is False
        finally:
            db.close()

    def test_missing_snapshot_never_supported(self, union_repo, tmp_path):
        """Invariant (b): no snapshot binding -> UNBOUND, never SUPPORTED."""
        db = Database(str(tmp_path / "sot.db"))
        try:
            _seed_union_db(db, [
                # empty-string snapshot hash
                {"provider": "cbm", "path": "app.py", "src": "run_1",
                 "snap": "", "l1": 1, "l2": 2},
                # NULL snapshot hash
                {"provider": "scip", "path": "app.py", "src": "run_2",
                 "snap": None, "l1": 1, "l2": 2},
            ], project_root=union_repo)
            out = union_evidence(db, union_repo)
            e1 = _by_src(out, "run_1")
            e2 = _by_src(out, "run_2")
            assert e1["status"] == "UNBOUND"
            assert e2["status"] == "UNBOUND"
            assert e1["identity"]["snapshot"] is None
        finally:
            db.close()

    def test_missing_path_never_supported(self, union_repo, tmp_path):
        db = Database(str(tmp_path / "sot.db"))
        try:
            _seed_union_db(db, [{
                "provider": "cbm", "path": "", "src": "run_1",
                "snap": "s1", "l1": 1, "l2": 2,
            }], project_root=union_repo)
            out = union_evidence(db, union_repo)
            assert _by_src(out, "run_1")["status"] == "UNBOUND"
        finally:
            db.close()

    def test_unverified_span_stays_unverified(self, union_repo, tmp_path):
        """Span present but symbol not defined there -> UNVERIFIED."""
        db = Database(str(tmp_path / "sot.db"))
        try:
            _seed_union_db(db, [{
                "provider": "cbm", "path": "app.py", "src": "ghost_fn",
                "snap": "s1", "l1": 1, "l2": 2,
            }], project_root=union_repo)
            out = union_evidence(db, union_repo)
            entry = _by_src(out, "ghost_fn")
            assert entry["status"] == "UNVERIFIED"
            assert entry["span"] == [1, 2]
        finally:
            db.close()

    def test_zero_spans_stay_unverified(self, union_repo, tmp_path):
        db = Database(str(tmp_path / "sot.db"))
        try:
            _seed_union_db(db, [{
                "provider": "cbm", "path": "app.py", "src": "run_1",
                "snap": "s1", "l1": None, "l2": None,
            }], project_root=union_repo)
            out = union_evidence(db, union_repo)
            entry = _by_src(out, "run_1")
            assert entry["status"] == "UNVERIFIED"
            assert "span" not in entry
        finally:
            db.close()

    def test_verify_spans_false_opts_out_of_verification(self, union_repo, tmp_path):
        """Explicit cheap-read opt-out never yields SUPPORTED."""
        db = Database(str(tmp_path / "sot.db"))
        try:
            _seed_union_db(db, [{
                "provider": "cbm", "path": "app.py", "src": "run_1",
                "snap": "s1", "l1": 1, "l2": 2,
            }], project_root=union_repo)
            out = union_evidence(db, union_repo, verify_spans=False)
            entry = _by_src(out, "run_1")
            assert entry["status"] == "UNVERIFIED"
            assert entry["span"] == [1, 2]
        finally:
            db.close()

    def test_invalidated_evidence_excluded_from_union(self, union_repo, tmp_path):
        db = Database(str(tmp_path / "sot.db"))
        try:
            _seed_union_db(db, [
                {"provider": "cbm", "path": "app.py", "src": "run_1",
                 "snap": "s1", "l1": 1, "l2": 2},
                {"provider": "scip", "path": "app.py", "src": "run_1",
                 "snap": "s1", "l1": 1, "l2": 2},
            ], project_root=union_repo)
            n = db.invalidate_provider_evidence(["ev_seed_1"])
            assert n == 1
            out = union_evidence(db, union_repo)
            entry = _by_src(out, "run_1")
            assert entry["providers"] == ["cbm"]
            # Idempotent: re-invalidating keeps the first timestamp.
            assert db.invalidate_provider_evidence(["ev_seed_1"]) == 0
        finally:
            db.close()


# ------------------------------------------ Contract 4: atomic provider write path

class ExplodingConn:
    """Proxy connection raising on a matching statement (crash simulator)."""

    def __init__(self, real, needle: str):
        self._real = real
        self._needle = needle

    def execute(self, sql, *args, **kwargs):
        if self._needle in sql:
            raise sqlite3.OperationalError("simulated crash before commit")
        return self._real.execute(sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        if self._needle in sql:
            raise sqlite3.OperationalError("simulated crash before commit")
        return self._real.executemany(sql, *args, **kwargs)

    def __enter__(self):
        return self._real.__enter__()

    def __exit__(self, *exc_info):
        return self._real.__exit__(*exc_info)

    def __getattr__(self, name):
        return getattr(self._real, name)


class TestAtomicProviderOutcome:
    def _outcome_args(self):
        return (
            {
                "provider_name": "cbm",
                "provider_version": "0.0.0",
                "capability": "search_graph",
                "status": "ok",
                "run_id": "run_atomic",
            },
            {
                "sot_repo_id": "/repo",
                "provider_name": "cbm",
                "provider_project_id": "proj-1",
            },
            [{
                "id": "ev_atomic",
                "path": "a.py",
                "src_symbol": "foo",
                "relation": "defines",
                "snapshot_hash": "s" * 40,
            }],
        )

    def test_outcome_persists_run_binding_and_evidence(self, tmp_path):
        db = Database(str(tmp_path / "sot.db"))
        try:
            run, binding, evidence = self._outcome_args()
            rid = db.record_provider_outcome(run, binding, evidence)
            assert rid == "run_atomic"
            assert db.conn.execute(
                "SELECT COUNT(*) FROM provider_runs WHERE id='run_atomic'"
            ).fetchone()[0] == 1
            assert db.conn.execute(
                "SELECT COUNT(*) FROM provider_project_bindings"
            ).fetchone()[0] == 1
            assert db.conn.execute(
                "SELECT COUNT(*) FROM provider_evidence WHERE id='ev_atomic'"
            ).fetchone()[0] == 1
        finally:
            db.close()

    def test_evidence_failure_rolls_back_everything(self, tmp_path):
        """Invariant (c): mid-way failure leaves no partial ledger rows."""
        db = Database(str(tmp_path / "sot.db"))
        try:
            real = db.conn
            db.conn = ExplodingConn(
                real, "INSERT INTO provider_evidence"
            )
            run, binding, evidence = self._outcome_args()
            with pytest.raises(sqlite3.OperationalError):
                db.record_provider_outcome(run, binding, evidence)
            db.conn = real
            for table in (
                "provider_runs", "provider_project_bindings", "provider_evidence"
            ):
                count = db.conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                assert count == 0, f"{table} kept {count} row(s) after rollback"
        finally:
            db.close()

    def test_invalidated_evidence_never_supports_union(self, union_repo, tmp_path):
        """Ledger-only evidence whose rows get invalidated drops out of the
        union entirely instead of surfacing stale support."""
        db = Database(str(tmp_path / "sot.db"))
        try:
            db.record_provider_outcome(
                {
                    "provider_name": "cbm",
                    "capability": "search_graph",
                    "status": "ok",
                    "run_id": "run_inv",
                },
                None,
                [{
                    "id": "ev_inv",
                    "path": "app.py",
                    "src_symbol": "run_1",
                    "relation": "defines",
                    "line_start": 1,
                    "line_end": 2,
                    "snapshot_hash": "s1",
                }],
            )
            assert db.invalidate_provider_evidence(["ev_inv"]) == 1
            out = union_evidence(db, union_repo)
            assert [e for e in out if "error" not in e] == []
        finally:
            db.close()
