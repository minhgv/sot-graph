from __future__ import annotations

from dataclasses import is_dataclass
from pathlib import Path
import os
from unittest.mock import patch
import tempfile
import unittest

from sot_graph.db import Database
from sot_graph.reconciler import ParseResult, Reconciler


class ParallelReconcilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="sot-parallel-")
        self.root = Path(self._temporary.name)
        self.db_path = self.root / ".sot" / "sot.db"
        source_dir = self.root / "src"
        source_dir.mkdir(parents=True)
        for index in range(7):
            (source_dir / f"module_{index}.py").write_text(
                f"def symbol_{index}(value):\n    return value + {index}\n",
                encoding="utf-8",
            )

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _snapshot(self, db: Database) -> dict[str, list[tuple]]:
        return {
            "journal": db.conn.execute(
                "SELECT path,sha256,size,mtime_ms FROM file_journal ORDER BY path"
            ).fetchall(),
            "nodes": db.conn.execute(
                "SELECT id,path,kind,symbol,label,body,keywords,line_start "
                "FROM graph_nodes ORDER BY id"
            ).fetchall(),
            "edges": db.conn.execute(
                "SELECT path,src,dst,relation,line FROM graph_edges ORDER BY path,src,dst,relation"
            ).fetchall(),
            "pending": db.conn.execute(
                "SELECT path,src,dst_symbol,relation,line "
                "FROM pending_edges ORDER BY path,src,dst_symbol,relation"
            ).fetchall(),
        }

    def _reset_database(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self.db_path) + suffix)
            if path.exists():
                path.unlink()

    def test_worker_counts_produce_identical_graphs(self) -> None:
        self.assertTrue(is_dataclass(ParseResult))
        db = Database(str(self.db_path))
        try:
            sequential = Reconciler(db, str(self.root)).reconcile(workers=1, batch_size=2)
            sequential_snapshot = self._snapshot(db)
            self.assertEqual(sequential.scanned, 7)
            self.assertEqual(sequential.updated, 7)
            self.assertEqual(sequential.failed, 0)
        finally:
            db.close()

        self._reset_database()
        db = Database(str(self.db_path))
        try:
            parallel = Reconciler(db, str(self.root)).reconcile(workers=2, batch_size=2)
            self.assertEqual(parallel.scanned, 7)
            self.assertEqual(parallel.updated, 7)
            self.assertEqual(parallel.failed, 0)
            self.assertEqual(self._snapshot(db), sequential_snapshot)
        finally:
            db.close()

    def test_reconcile_is_idempotent_then_accounts_for_update_and_delete(self) -> None:
        db = Database(str(self.db_path))
        try:
            reconciler = Reconciler(db, str(self.root))
            first = reconciler.reconcile(workers=1)
            second = reconciler.reconcile(workers=2, batch_size=3)
            self.assertEqual(first.updated, 7)
            self.assertEqual(second.updated, 0)
            self.assertEqual(second.unchanged, 7)

            changed = self.root / "src" / "module_0.py"
            changed.write_text(
                "def symbol_0(value):\n    return value + 1000\n\n# changed\n",
                encoding="utf-8",
            )
            removed = self.root / "src" / "module_1.py"
            removed.unlink()
            result = reconciler.reconcile(workers=2, batch_size=2)
            self.assertEqual(result.updated, 1)
            self.assertEqual(result.deleted, 1)
            self.assertEqual(result.failed, 0)
            self.assertEqual(db.stats()["paths"], 6)
            self.assertFalse(any("module_1.py" in path for path in db.all_journal_paths()))
        finally:
            db.close()

    def test_failed_parse_preserves_previous_rows(self) -> None:
        db = Database(str(self.db_path))
        try:
            reconciler = Reconciler(db, str(self.root))
            reconciler.reconcile(workers=1)
            target = self.root / "src" / "module_0.py"
            target.write_text("def symbol_0(value):\n    return value + 9\n", encoding="utf-8")
            prior = db.get_file_journal(str(target))
            prior_nodes = db.conn.execute(
                "SELECT id FROM graph_nodes WHERE path=? ORDER BY id", (str(target),)
            ).fetchall()
            stat = target.stat()
            failed = ParseResult(
                str(target), None, int(stat.st_size), int(stat.st_mtime * 1000), (), (), (), "parse:src/module_0.py"
            )
            with patch("sot_graph.reconciler._parse_worker", return_value=failed):
                summary = reconciler.reconcile(workers=1)
            self.assertEqual(summary.failed, 1)
            self.assertEqual(db.get_file_journal(str(target)), prior)
            self.assertEqual(
                db.conn.execute("SELECT id FROM graph_nodes WHERE path=? ORDER BY id", (str(target),)).fetchall(),
                prior_nodes,
            )
        finally:
            db.close()

    def test_invalid_parallel_parameters_are_rejected(self) -> None:
        db = Database(str(self.db_path))
        try:
            reconciler = Reconciler(db, str(self.root))
            with self.assertRaises(ValueError):
                reconciler.reconcile(workers=0)
            with self.assertRaises(ValueError):
                reconciler.reconcile(batch_size=0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
