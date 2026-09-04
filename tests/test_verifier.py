"""Regression tests for TrustVerifier re-homing (REBUILT verdict).

find_rehome matches by basename only; in layouts where sibling packages ship
files with the same name (Odoo addons each having hooks.py), re-homing used
to attach deleted symbols onto a foreign addon's file. The rehome now
requires the symbol to appear in the candidate file's text.

R5: the basename scan is cached per project root (one bounded walk shared
across the missing-file lookups of a heal pass) with use-time existence
validation and single rebuild on staleness — covered by RehomeCacheTests.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sot_graph.verifier as verifier_mod
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
            db, cand, tokenize("setup_hook"), str(self.root), auto_heal=True)

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
            db, cand, tokenize("Gateway"), str(self.root), auto_heal=True)

        self.assertEqual(verdict, "REBUILT")
        self.assertTrue(str(path).replace("\\", "/").endswith("pkg_c/service.py"), path)

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
            db, cand, tokenize("notes"), str(self.root), auto_heal=True)

        self.assertEqual(verdict, "REBUILT")
        self.assertTrue(str(path).replace("\\", "/").endswith("pkg_b/notes.py"), path)


class RehomeCacheTests(unittest.TestCase):
    """R5: one bounded walk per heal pass, invalidated on stale paths."""

    def setUp(self):
        verifier_mod._reset_rehome_index()
        self.addCleanup(verifier_mod._reset_rehome_index)
        self.root = Path(tempfile.mkdtemp(prefix="sot_rehome_cache_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def _walk_spy(self):
        """os.walk patch counting only walks rooted at THIS test's tree.

        os.walk is patched process-wide, so background threads from other
        suites must not inflate the count.
        """
        real_walk = os.walk
        counted = {"n": 0}

        def counting_walk(top, *args, **kwargs):
            if os.path.abspath(str(top)) == str(self.root):
                counted["n"] += 1
            return real_walk(top, *args, **kwargs)

        return patch.object(verifier_mod.os, "walk", side_effect=counting_walk), counted

    def test_multiple_missing_files_walk_repo_once(self):
        # Three moved files: heal pass over 3 missing basenames must cost
        # exactly one os.walk (the per-file walk was O(missing x repo)).
        for name in ("svc_one.py", "svc_two.py", "svc_three.py"):
            (self.root / name).write_text("x = 1\n")
        spy, counted = self._walk_spy()
        with spy:
            p1 = TrustVerifier.find_rehome(str(self.root), "svc_one.py")
            p2 = TrustVerifier.find_rehome(str(self.root), "svc_two.py")
            p3 = TrustVerifier.find_rehome(str(self.root), "svc_three.py")
        self.assertEqual(counted["n"], 1, "cache must serve the pass with one walk")
        self.assertTrue(str(p1).replace(os.sep, "/").endswith("svc_one.py"))
        self.assertTrue(str(p2).replace(os.sep, "/").endswith("svc_two.py"))
        self.assertTrue(str(p3).replace(os.sep, "/").endswith("svc_three.py"))

    def test_stale_cached_path_invalidates_and_rebuilds_once(self):
        old = self.root / "old_dir"
        old.mkdir()
        (old / "only.py").write_text("x = 1\n")
        spy, counted = self._walk_spy()
        with spy:
            first = TrustVerifier.find_rehome(str(self.root), "only.py")
            self.assertTrue(str(first).replace(os.sep, "/").endswith("old_dir/only.py"))
            # The cached candidate vanished; a new one appeared elsewhere.
            (old / "only.py").unlink()
            new_dir = self.root / "new_dir"
            new_dir.mkdir()
            (new_dir / "only.py").write_text("x = 2\n")
            second = TrustVerifier.find_rehome(str(self.root), "only.py")
        self.assertEqual(counted["n"], 2,
                         "stale hit must trigger exactly one rebuild")
        self.assertTrue(str(second).replace(os.sep, "/").endswith("new_dir/only.py"), second)

    def test_absent_basename_never_answered_from_cache(self):
        (self.root / "real.py").write_text("x = 1\n")
        spy, counted = self._walk_spy()
        with spy:
            self.assertIsNone(TrustVerifier.find_rehome(str(self.root), "ghost.py"))
            # Still absent on the next ask: answered fresh, not from cache.
            self.assertIsNone(TrustVerifier.find_rehome(str(self.root), "ghost.py"))
            # And a positive lookup afterwards still resolves.
            found = TrustVerifier.find_rehome(str(self.root), "real.py")
        self.assertTrue(str(found).replace(os.sep, "/").endswith("real.py"))
        self.assertGreaterEqual(counted["n"], 2,
                                "absence decisions must come from fresh walks")

    def test_ambiguous_basename_stays_uncached(self):
        (self.root / "pkg_a").mkdir()
        (self.root / "pkg_b").mkdir()
        (self.root / "pkg_a" / "dup.py").write_text("a = 1\n")
        (self.root / "pkg_b" / "dup.py").write_text("b = 1\n")
        self.assertIsNone(TrustVerifier.find_rehome(str(self.root), "dup.py"),
                          "ambiguous match must not guess")
        # Collision resolved by deletion: the fresh rebuild may rehome.
        (self.root / "pkg_b" / "dup.py").unlink()
        found = TrustVerifier.find_rehome(str(self.root), "dup.py")
        self.assertTrue(str(found).replace(os.sep, "/").endswith("pkg_a/dup.py"), found)

    def test_heal_pass_over_two_missing_files_costs_one_walk(self):
        db = Database(str(self.root / ".sot" / "sot.db"))
        self.addCleanup(db.close)
        for name in ("alpha.py", "beta.py"):
            (self.root / name).write_text(f"def {name.split('.')[0]}():\n    return 1\n")
        Reconciler(db, str(self.root)).reconcile(workers=1)
        # Move both files: the index entries become stale candidates.
        moved = self.root / "moved"
        moved.mkdir()
        (self.root / "alpha.py").rename(moved / "alpha.py")
        (self.root / "beta.py").rename(moved / "beta.py")

        def candidates_for(symbol):
            for cand in db.search_fts(symbol, limit=20):
                if cand["symbol"] == symbol:
                    return cand
            raise AssertionError(f"no candidate for {symbol}")

        spy, counted = self._walk_spy()
        with spy:
            for symbol in ("alpha", "beta"):
                verdict, _, path = TrustVerifier.verify_hit(
                    db, candidates_for(symbol), tokenize(symbol),
                    str(self.root), auto_heal=True)
                self.assertEqual(verdict, "REBUILT", symbol)
                self.assertTrue(str(path).replace(os.sep, "/").endswith(f"moved/{symbol}.py"), path)
        self.assertEqual(counted["n"], 1,
                         "both heal lookups must share one index build")


if __name__ == "__main__":
    unittest.main()
