from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler


class MaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="sot-maintenance-")
        self.root = Path(self._temporary.name)
        self.db_path = self.root / ".sot" / "sot.db"

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _database(self) -> Database:
        return Database(str(self.db_path))

    def _index_source(self, db: Database) -> Path:
        source = self.root / "src" / "sample.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("def maintenance_symbol(value):\n    return value\n", encoding="utf-8")
        summary = Reconciler(db, str(self.root)).reconcile(workers=1)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(summary.updated, 1)
        return source

    def _insert_note(self, db: Database) -> None:
        now = int(time.time())
        db.conn.execute(
            "INSERT INTO graph_nodes "
            "(id,path,kind,symbol,label,body,keywords,line_start,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("note:keep", "note://keep", "note", None, "Keep this note", "body", "keep", None, now),
        )
        db.conn.commit()

    def test_read_only_requires_existing_file_and_rejects_writes(self) -> None:
        missing = self.root / "missing" / "sot.db"
        with self.assertRaises(FileNotFoundError):
            Database(str(missing), read_only=True)
        self.assertFalse(missing.exists())

        db = self._database()
        self._index_source(db)
        db.close()
        read_only = Database(str(self.db_path), read_only=True)
        try:
            self.assertEqual(read_only.conn.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                read_only.conn.execute("INSERT INTO file_journal VALUES ('x','x',1,1,1,1)")
        finally:
            read_only.close()

    def test_default_clean_removes_missing_paths_and_orphans(self) -> None:
        db = self._database()
        source = self._index_source(db)
        db.conn.execute(
            "INSERT INTO graph_edges(path,src,dst,relation,line) VALUES (?,?,?,?,?)",
            ("orphan.py", "missing-src", "missing-dst", "calls", 1),
        )
        db.conn.execute(
            "INSERT INTO pending_edges(path,src,dst_symbol,relation,line) VALUES (?,?,?,?,?)",
            ("orphan.py", "missing-src", "Missing", "references", 1),
        )
        db.conn.commit()
        source.unlink()

        plan = db.plan_clean(str(self.root))
        self.assertEqual(plan.mode, "stale")
        self.assertEqual(plan.paths, (str(source),))
        self.assertGreaterEqual(plan.counts["paths"], 1)
        self.assertGreaterEqual(plan.counts["edges"], 1)
        self.assertGreaterEqual(plan.counts["pending"], 1)
        self.assertEqual(len(db.all_journal_paths()), 1)

        deleted = db.apply_clean(plan)
        self.assertEqual(deleted["paths"], 1)
        self.assertEqual(db.stats(), {"paths": 0, "nodes": 0, "edges": 0, "pending": 0})
        db.close()

    def test_reset_preserves_notes_until_include_notes_is_requested(self) -> None:
        db = self._database()
        self._index_source(db)
        self._insert_note(db)

        plan = db.plan_clean(str(self.root), reset=True)
        self.assertEqual(plan.mode, "reset")
        self.assertEqual(plan.counts["notes"], 0)
        deleted = db.apply_clean(plan)
        self.assertEqual(deleted["paths"], 1)
        self.assertEqual(db.stats()["nodes"], 1)
        self.assertEqual(db.conn.execute("SELECT kind FROM graph_nodes").fetchone()[0], "note")

        with self.assertRaises(ValueError):
            db.plan_clean(str(self.root), include_notes=True)
        plan_with_notes = db.plan_clean(str(self.root), reset=True, include_notes=True)
        self.assertEqual(plan_with_notes.counts["notes"], 1)
        deleted_with_notes = db.apply_clean(plan_with_notes)
        self.assertEqual(deleted_with_notes["notes"], 1)
        self.assertEqual(db.stats()["nodes"], 0)
        db.close()

    def test_vacuum_dry_run_does_not_mutate_and_real_vacuum_is_healthy(self) -> None:
        db = self._database()
        self._index_source(db)
        before = os.path.getsize(self.db_path)
        dry_run = db.vacuum(dry_run=True)
        self.assertTrue(dry_run.dry_run)
        self.assertEqual(dry_run.before_bytes, dry_run.after_bytes)
        self.assertEqual(os.path.getsize(self.db_path), before)

        result = db.vacuum(optimize=True)
        self.assertFalse(result.dry_run)
        self.assertTrue(result.optimized)
        self.assertEqual(db.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
        db.close()


if __name__ == "__main__":
    unittest.main()
