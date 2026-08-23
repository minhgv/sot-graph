import unittest
import os
import shutil
import tempfile
from pathlib import Path

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler
from sot_graph.verifier import TrustVerifier, tokenize


class TestSotGraphReconciler(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, ".sot", "test.db")
        self.db = Database(self.db_path)
        self.reconciler = Reconciler(self.db, self.test_dir)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_reconcile_and_idempotency(self):
        # Create a Python source file
        py_file = Path(self.test_dir) / "auth.py"
        py_file.write_text(
            "class AuthManager:\n"
            "    def authenticate_user(self, token: str):\n"
            "        return True\n"
        )

        # 1. First reconcile -> indexed
        action = self.reconciler.reconcile_path(str(py_file))
        self.assertEqual(action, "indexed")

        # 2. Second reconcile without modification -> unchanged
        action2 = self.reconciler.reconcile_path(str(py_file))
        self.assertEqual(action2, "unchanged")

        # 3. Check DB records
        stats = self.db.stats()
        self.assertEqual(stats["paths"], 1)
        self.assertGreaterEqual(stats["nodes"], 2)  # file + class + method

    def test_trust_verdict_scoring(self):
        py_file = Path(self.test_dir) / "database.py"
        py_file.write_text(
            "class DatabasePool:\n"
            "    def acquire_connection(self):\n"
            "        pass\n"
        )
        self.reconciler.reconcile_path(str(py_file))

        # Search for tokens in disk file
        cand = self.db.search_fts("DatabasePool acquire_connection")[0]
        q_toks = tokenize("DatabasePool acquire_connection")
        verdict, cov, real_path = TrustVerifier.verify_hit(self.db, cand, q_toks, self.test_dir)

        self.assertEqual(verdict, "STRONG")
        self.assertGreaterEqual(cov, 0.5)
        self.assertEqual(real_path, str(py_file))

    def test_dead_path_auto_purge(self):
        temp_file = Path(self.test_dir) / "temporary.py"
        temp_file.write_text("def temporary_cleanup(): pass")
        self.reconciler.reconcile_path(str(temp_file))

        cand = self.db.search_fts("temporary_cleanup")[0]

        # Delete physical file on disk
        temp_file.unlink()

        # Verify should detect missing, auto-purge, and return REMOVED
        verdict, cov, real_path = TrustVerifier.verify_hit(
            self.db, cand, tokenize("temporary_cleanup"), self.test_dir, auto_heal=True
        )
        self.assertEqual(verdict, "REMOVED")

        # Confirm node is purged from DB
        remaining = self.db.search_fts("temporary_cleanup")
        self.assertEqual(len(remaining), 0)

    def test_two_way_pending_edge_resolution(self):
        # File A calls helper from File B before File B exists
        file_a = Path(self.test_dir) / "service.py"
        file_a.write_text(
            "def run_service():\n"
            "    return calculate_tax(100)\n"
        )
        self.reconciler.reconcile_path(str(file_a))

        stats_before = self.db.stats()
        self.assertGreaterEqual(stats_before["pending"], 1)

        # Now File B defines calculate_tax
        file_b = Path(self.test_dir) / "calculator.py"
        file_b.write_text(
            "def calculate_tax(amount):\n"
            "    return amount * 0.1\n"
        )
        self.reconciler.reconcile_path(str(file_b))

        stats_after = self.db.stats()
        # Pending edge should be promoted to confirmed graph edge
        self.assertEqual(stats_after["pending"], 0)
        self.assertGreaterEqual(stats_after["edges"], 1)


if __name__ == "__main__":
    unittest.main()
