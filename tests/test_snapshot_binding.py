"""
Snapshot binding tests (schema v6): ``snapshots`` table, nullable
``provider_runs.snapshot_id``, and ``sot_graph.snapshot`` git binding helpers.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import tempfile
import unittest

from sot_graph.db import SCHEMA_VERSION, Database
from sot_graph.snapshot import (
    bind_snapshot,
    compute_dirty_fingerprint,
    get_head_sha,
    is_dirty,
)

_SNAP_ID_RE = re.compile(r"^snap_\d+_[0-9a-f]{8}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class SnapshotBindingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        self._git("init", "-q")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Snapshot Test")
        self._write("tracked.txt", "v1\n")
        self._git("add", ".")
        self._git("commit", "-q", "-m", "init")

    # -- helpers ---------------------------------------------------------

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-C", self.repo, *args],
            check=True,
            capture_output=True,
        )

    def _write(self, name: str, content: str) -> None:
        with open(os.path.join(self.repo, name), "w", encoding="utf-8") as fh:
            fh.write(content)

    def _append(self, name: str, content: str) -> None:
        with open(os.path.join(self.repo, name), "a", encoding="utf-8") as fh:
            fh.write(content)

    def _open_db(self, name: str = "sot.db") -> Database:
        return Database(os.path.join(self.tmp.name, name))

    @staticmethod
    def _bind(db: Database, repo_root: str) -> str:
        return db.transactional_mutation(lambda _: bind_snapshot(db.conn, repo_root))

    @staticmethod
    def _snapshot_row(db: Database, snapshot_id: str) -> dict:
        cur = db.conn.execute(
            "SELECT id, repo_root, commit_sha, dirty, dirty_fingerprint, "
            "manifest_digest, algo_version, generation, captured_at "
            "FROM snapshots WHERE id = ?",
            (snapshot_id,),
        )
        keys = [
            "id", "repo_root", "commit_sha", "dirty", "dirty_fingerprint",
            "manifest_digest", "algo_version", "generation", "captured_at",
        ]
        row = cur.fetchone()
        assert row is not None, f"snapshot row missing: {snapshot_id}"
        return dict(zip(keys, row))

    # -- (a) clean repo binding ------------------------------------------

    def test_bind_snapshot_on_clean_git_repo(self) -> None:
        db = self._open_db()
        try:
            snap_id = self._bind(db, self.repo)
            self.assertRegex(snap_id, _SNAP_ID_RE)
            row = self._snapshot_row(db, snap_id)
            expected_sha = subprocess.run(
                ["git", "-C", self.repo, "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            self.assertEqual(row["repo_root"], self.repo)
            self.assertEqual(row["commit_sha"], expected_sha)
            self.assertTrue(_SHA_RE.match(row["commit_sha"]))
            self.assertEqual(row["dirty"], 0)
            self.assertIsNotNone(row["dirty_fingerprint"])
            self.assertTrue(str(row["manifest_digest"]).startswith("sha256:"))
            self.assertEqual(row["algo_version"], "sha256-v1")
            self.assertIsInstance(row["generation"], int)
            self.assertGreaterEqual(row["generation"], 1)
            self.assertIsInstance(row["captured_at"], int)
        finally:
            db.close()

    # -- (b) dirty worktree ----------------------------------------------

    def test_dirty_worktree_changes_fingerprint(self) -> None:
        db = self._open_db()
        try:
            first_id = self._bind(db, self.repo)
            clean_fp = self._snapshot_row(db, first_id)["dirty_fingerprint"]

            self.assertFalse(is_dirty(self.repo))

            self._append("tracked.txt", "v2\n")
            self.assertTrue(is_dirty(self.repo))
            second_id = self._bind(db, self.repo)
            dirty_row = self._snapshot_row(db, second_id)
            self.assertEqual(dirty_row["dirty"], 1)
            self.assertIsNotNone(dirty_row["dirty_fingerprint"])
            self.assertNotEqual(dirty_row["dirty_fingerprint"], clean_fp)

            # Adding another file must move the fingerprint again.
            self._write("new.txt", "untracked\n")
            third_fp = compute_dirty_fingerprint(self.repo)
            self.assertIsNotNone(third_fp)
            self.assertNotEqual(third_fp, dirty_row["dirty_fingerprint"])
        finally:
            db.close()

    # -- (c) non-git directory --------------------------------------------

    def test_non_git_dir_yields_none(self) -> None:
        plain = os.path.join(self.tmp.name, "plain")
        os.makedirs(plain)
        self.assertIsNone(get_head_sha(plain))
        self.assertFalse(is_dirty(plain))
        self.assertIsNone(compute_dirty_fingerprint(plain))

        db = self._open_db("nongit.db")
        try:
            snap_id = self._bind(db, plain)
            row = self._snapshot_row(db, snap_id)
            self.assertIsNone(row["commit_sha"])
            self.assertEqual(row["dirty"], 0)
            self.assertIsNone(row["dirty_fingerprint"])
        finally:
            db.close()

    # -- (d) v5 -> v6 migration is additive and idempotent -----------------

    def test_v5_migration_adds_snapshot_binding_idempotently(self) -> None:
        legacy_path = os.path.join(self.tmp.name, "legacy.db")
        conn = sqlite3.connect(legacy_path)
        conn.execute("PRAGMA user_version = 5")
        conn.execute(
            "CREATE TABLE graph_nodes ("
            " id TEXT PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL,"
            " symbol TEXT, fqn TEXT, signature TEXT, label TEXT NOT NULL,"
            " body TEXT NOT NULL, keywords TEXT, line_start INTEGER,"
            " line_end INTEGER, col_start INTEGER, col_end INTEGER,"
            " updated_at INTEGER NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE provider_runs ("
            " id TEXT PRIMARY KEY, provider_name TEXT NOT NULL,"
            " provider_version TEXT, capability TEXT NOT NULL,"
            " snapshot_hash TEXT, project_root TEXT,"
            " position_encoding TEXT DEFAULT 'UTF-8', arguments_json TEXT,"
            " created_at INTEGER NOT NULL)"
        )
        conn.execute(
            "INSERT INTO provider_runs (id, provider_name, capability, created_at)"
            " VALUES ('run_legacy', 'scip-compiler-ast', 'symbols', 1700000000)"
        )
        conn.commit()
        conn.close()

        db = Database(legacy_path)
        try:
            self.assertEqual(db._user_version(), SCHEMA_VERSION)
            cols = [
                r[1] for r in db.conn.execute("PRAGMA table_info(provider_runs)").fetchall()
            ]
            self.assertIn("snapshot_id", cols)
            tables = {
                r[0] for r in db.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertIn("snapshots", tables)

            # Legacy data survives and is UNBOUND (NULL, never backfilled).
            legacy = db.conn.execute(
                "SELECT id, snapshot_id FROM provider_runs WHERE id = 'run_legacy'"
            ).fetchone()
            self.assertEqual(legacy[0], "run_legacy")
            self.assertIsNone(legacy[1])

            # Nullable: inserting a run without snapshot_id still works.
            db.conn.execute(
                "INSERT INTO provider_runs (id, provider_name, capability, created_at)"
                " VALUES ('run_after', 'ast-heuristic', 'symbols', 1700000001)"
            )

            # Binding works on the migrated database.
            snap_id = self._bind(db, self.repo)
            self.assertRegex(snap_id, _SNAP_ID_RE)
        finally:
            db.close()

        # Reopening is a no-op: no error, version stable, rows intact.
        db2 = Database(legacy_path)
        try:
            self.assertEqual(db2._user_version(), SCHEMA_VERSION)
            count = db2.conn.execute(
                "SELECT COUNT(*) FROM provider_runs"
            ).fetchone()[0]
            self.assertEqual(count, 2)
        finally:
            db2.close()


    def test_drifted_v5_provider_evidence_backfills_columns(self) -> None:
        """Regression: a pre-v5 provider_evidence shape under user_version=5
        must be column-completed before index creation (real .sot DBs hit this)."""
        legacy_path = os.path.join(self.tmp.name, "drifted.db")
        conn = sqlite3.connect(legacy_path)
        conn.execute("PRAGMA user_version = 5")
        conn.execute(
            "CREATE TABLE graph_nodes ("
            " id TEXT PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL,"
            " symbol TEXT, fqn TEXT, signature TEXT, label TEXT NOT NULL,"
            " body TEXT NOT NULL, keywords TEXT, line_start INTEGER,"
            " line_end INTEGER, col_start INTEGER, col_end INTEGER,"
            " updated_at INTEGER NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE provider_runs ("
            " id TEXT PRIMARY KEY, provider_name TEXT NOT NULL,"
            " capability TEXT NOT NULL, created_at INTEGER NOT NULL)"
        )
        # Old 13-column shape: no provider_name/file_path/symbol/role/... columns.
        conn.execute(
            "CREATE TABLE provider_evidence ("
            " id TEXT PRIMARY KEY, run_id TEXT NOT NULL, path TEXT NOT NULL,"
            " src_symbol TEXT NOT NULL, dst_symbol TEXT, relation TEXT NOT NULL,"
            " line_start INTEGER, line_end INTEGER, col_start INTEGER,"
            " col_end INTEGER, confidence REAL DEFAULT 1.0,"
            " metadata_json TEXT, created_at INTEGER NOT NULL)"
        )
        conn.commit()
        conn.close()

        db = Database(legacy_path)
        try:
            self.assertEqual(db._user_version(), SCHEMA_VERSION)
            cols = {
                r[1]
                for r in db.conn.execute("PRAGMA table_info(provider_evidence)").fetchall()
            }
            for required in ("provider_name", "symbol", "role", "recorded_at", "syntax_kind"):
                self.assertIn(required, cols)
            # Legacy evidence row survives with defaulted recorded_at.
            db.conn.execute(
                "INSERT INTO provider_evidence (id, run_id, path, src_symbol, relation, created_at)"
                " VALUES ('ev1', 'run_legacy', 'a.py', 'f', 'calls', 1700000000)"
            )
            legacy = db.conn.execute(
                "SELECT id, provider_name FROM provider_evidence WHERE id = 'ev1'"
            ).fetchone()
            self.assertEqual(legacy[0], "ev1")
            self.assertIsNone(legacy[1])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
