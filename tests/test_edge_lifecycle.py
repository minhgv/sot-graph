"""Regression tests for edge lifecycle on file move/delete.

Moving a file used to strand every inbound edge from unchanged files on the
deleted node ids: the re-created node reported zero usages until each source
file happened to be edited. delete_path now re-queues inbound edges as
pending and reconcile sweeps orphans afterwards.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler


class EdgeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sot_lifecycle_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel_path, content):
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)

    def make_db(self):
        db = Database(str(self.root / ".sot" / "sot.db"))
        self.addCleanup(db.close)
        return db

    def reconcile(self, db):
        return Reconciler(db, str(self.root)).reconcile()

    def dst_paths(self, db, src_path, relation, dst_symbol):
        rows = db.conn.execute(
            "SELECT n2.path FROM graph_edges e "
            "JOIN graph_nodes n1 ON e.src = n1.id "
            "JOIN graph_nodes n2 ON e.dst = n2.id "
            "WHERE n1.path = ? AND e.relation = ? AND n2.symbol = ?",
            (src_path, relation, dst_symbol),
        ).fetchall()
        return sorted(r[0] for r in rows)

    def test_move_file_re_resolves_inbound_edges(self):
        self.write("pkg_a/helpers.py",
                   "class Base:\n    def run(self):\n        return 1\n")
        self.write("pkg_b/child.py",
                   "from pkg_a.helpers import Base\n\n"
                   "class Child(Base):\n"
                   "    def run(self):\n        return 2\n")
        db = self.make_db()
        self.reconcile(db)
        child = str(self.root / "pkg_b" / "child.py")
        self.assertEqual(
            self.dst_paths(db, child, "extends", "Base"),
            [str(self.root / "pkg_a" / "helpers.py")])

        # Move the defining file.
        os.rename(self.root / "pkg_a" / "helpers.py",
                  self.root / "pkg_a" / "helpers_renamed.py")
        self.reconcile(db)

        self.assertEqual(
            self.dst_paths(db, child, "extends", "Base"),
            [str(self.root / "pkg_a" / "helpers_renamed.py")],
            "extends edge must follow the moved definition")

    def test_move_file_re_resolves_inbound_import_edges(self):
        self.write("pkg_a/__init__.py", "from . import helpers\n")
        self.write("pkg_a/helpers.py",
                   "class Base:\n    def run(self):\n        return 1\n")
        db = self.make_db()
        self.reconcile(db)

        os.rename(self.root / "pkg_a" / "helpers.py",
                  self.root / "pkg_a" / "helpers_renamed.py")
        # 'from . import helpers' now dangles; without edits to __init__.py
        # the edge should not survive as a stale confirmed edge.
        self.reconcile(db)

        dangling = db.conn.execute(
            "SELECT COUNT(*) FROM graph_edges e WHERE NOT EXISTS "
            "(SELECT 1 FROM graph_nodes n WHERE n.id = e.dst)"
        ).fetchone()[0]
        self.assertEqual(dangling, 0)

    def test_delete_file_leaves_no_dangling_edges(self):
        self.write("pkg_a/helpers.py",
                   "class Base:\n    def run(self):\n        return 1\n")
        self.write("pkg_b/child.py",
                   "from pkg_a.helpers import Base\n\n"
                   "class Child(Base):\n"
                   "    def run(self):\n        return 2\n")
        db = self.make_db()
        self.reconcile(db)

        os.remove(self.root / "pkg_a" / "helpers.py")
        self.reconcile(db)

        dangling = db.conn.execute(
            "SELECT COUNT(*) FROM graph_edges e WHERE NOT EXISTS "
            "(SELECT 1 FROM graph_nodes n WHERE n.id = e.src) OR NOT EXISTS "
            "(SELECT 1 FROM graph_nodes n WHERE n.id = e.dst)"
        ).fetchone()[0]
        self.assertEqual(dangling, 0)
        # The reference from the surviving file must be visible as pending
        # risk, not silently confirmed against a deleted node.
        pending = db.conn.execute(
            "SELECT COUNT(*) FROM pending_edges WHERE dst_symbol = 'Base'"
        ).fetchone()[0]
        self.assertGreaterEqual(pending, 1)

    def test_reconcile_idempotent_after_move(self):
        self.write("pkg_a/helpers.py",
                   "class Base:\n    def run(self):\n        return 1\n")
        self.write("pkg_b/child.py",
                   "from pkg_a.helpers import Base\n\n"
                   "class Child(Base):\n"
                   "    def run(self):\n        return 2\n")
        db = self.make_db()
        self.reconcile(db)

        os.rename(self.root / "pkg_a" / "helpers.py",
                  self.root / "pkg_a" / "helpers_renamed.py")
        self.reconcile(db)

        def snapshot():
            return {
                "edges": db.conn.execute(
                    "SELECT COUNT(*) FROM graph_edges").fetchone()[0],
                "pending": db.conn.execute(
                    "SELECT COUNT(*) FROM pending_edges WHERE resolution_state"
                    " != 'AMBIGUOUS'").fetchone()[0],
            }

        first = snapshot()
        self.reconcile(db)
        second = snapshot()
        self.assertEqual(first, second,
                         "second reconcile must not churn edges or pending rows")


if __name__ == "__main__":
    unittest.main()
