"""Regression tests for TrustVerifier re-homing (REBUILT verdict).

find_rehome matches by basename only; in layouts where sibling packages ship
files with the same name (Odoo addons each having hooks.py), re-homing used
to attach deleted symbols onto a foreign addon's file. The rehome now
requires the symbol to appear in the candidate file's text.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler
from sot_graph.verifier import TrustVerifier, tokenize


class RehomeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sot_rehome_"))
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

    def _candidate_for(self, db, symbol):
        for cand in db.search_fts(symbol, limit=20):
            if cand["symbol"] == symbol:
                return cand
        raise AssertionError(f"no candidate for symbol {symbol}")

    def test_colliding_basename_does_not_steal_symbol(self):
        self.write("pkg_a/hooks.py", "def setup_hook():\n    return 'a'\n")
        self.write("pkg_b/hooks.py", "def teardown_hook():\n    return 'b'\n")
        db = self.make_db()
        Reconciler(db, str(self.root)).reconcile()

        (self.root / "pkg_a" / "hooks.py").unlink()
        cand = self._candidate_for(db, "setup_hook")
        verdict, _, path = TrustVerifier.verify_hit(
            db, cand, tokenize("setup_hook"), str(self.root))

        self.assertEqual(verdict, "REMOVED")
        self.assertFalse(Path(path).exists() or path.endswith("pkg_b"))

        stolen = db.conn.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE symbol = 'setup_hook' "
            "AND path LIKE '%pkg_b%'").fetchone()[0]
        self.assertEqual(stolen, 0,
                         "setup_hook must not be re-homed onto pkg_b/hooks.py")
        kept = db.conn.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE symbol = 'teardown_hook'"
        ).fetchone()[0]
        self.assertEqual(kept, 1, "unrelated pkg_b symbol must survive")

    def test_rehome_succeeds_when_symbol_present(self):
        self.write("pkg_a/service.py",
                   "class Gateway:\n    def charge(self):\n        return True\n")
        db = self.make_db()
        Reconciler(db, str(self.root)).reconcile()

        moved = self.root / "pkg_c" / "service.py"
        moved.parent.mkdir(parents=True, exist_ok=True)
        (self.root / "pkg_a" / "service.py").rename(moved)
        cand = self._candidate_for(db, "Gateway")
        verdict, _, path = TrustVerifier.verify_hit(
            db, cand, tokenize("Gateway"), str(self.root))

        self.assertEqual(verdict, "REBUILT")
        self.assertTrue(str(path).endswith("pkg_c/service.py"), path)

    def test_read_only_mode_reports_stale_without_mutation(self):
        self.write("pkg_a/service.py",
                   "class Gateway:\n    def charge(self):\n        return True\n")
        db = self.make_db()
        Reconciler(db, str(self.root)).reconcile()

        (self.root / "pkg_a" / "service.py").unlink()
        cand = self._candidate_for(db, "Gateway")
        verdict, _, _ = TrustVerifier.verify_hit(
            db, cand, tokenize("Gateway"), str(self.root), auto_heal=False)

        self.assertEqual(verdict, "STALE")
        alive = db.conn.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE symbol = 'Gateway'"
        ).fetchone()[0]
        self.assertEqual(alive, 1, "read-only verify must not purge nodes")

    def test_file_node_rehome_keeps_working(self):
        self.write("pkg_a/notes.py", "X = 1\n")
        db = self.make_db()
        Reconciler(db, str(self.root)).reconcile()

        moved = self.root / "pkg_b" / "notes.py"
        moved.parent.mkdir(parents=True, exist_ok=True)
        (self.root / "pkg_a" / "notes.py").rename(moved)
        cand = db.search_fts("notes.py", limit=20)[0]
        verdict, _, path = TrustVerifier.verify_hit(
            db, cand, tokenize("notes"), str(self.root))

        self.assertEqual(verdict, "REBUILT")
        self.assertTrue(str(path).endswith("pkg_b/notes.py"), path)


if __name__ == "__main__":
    unittest.main()
