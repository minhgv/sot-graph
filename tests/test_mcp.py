import unittest
import os
import shutil
import tempfile
from pathlib import Path

from sot_graph.db import Database
from sot_graph.mcp_service import McpService, McpServiceError
from sot_graph.reconciler import Reconciler


class TestMcpService(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, ".sot", "test.db")
        db = Database(self.db_path)
        rec = Reconciler(db, self.test_dir)

        # Create sample source file
        py_file = Path(self.test_dir) / "service.py"
        py_file.write_text(
            "class PaymentService:\n"
            "    def process_order(self, order_id: str):\n"
            "        return True\n"
        )
        rec.reconcile_path(str(py_file))
        db.close()

        self.service = McpService(self.db_path, self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_mcp_service_stats(self):
        stats = self.service.stats()
        self.assertGreaterEqual(stats["paths"], 1)
        self.assertGreaterEqual(stats["nodes"], 1)

    def test_mcp_service_search(self):
        res = self.service.search(query="PaymentService", limit=5)
        self.assertIn("results", res)
        self.assertGreaterEqual(len(res["results"]), 1)
        hit = res["results"][0]
        self.assertEqual(hit["verdict"], "STRONG")
        self.assertIn("PaymentService", hit["label"])

    def test_mcp_service_explore(self):
        res = self.service.explore("PaymentService", depth=2)
        self.assertIn("node", res)
        self.assertEqual(res["node"]["symbol"], "PaymentService")
        self.assertIn("relations", res)

    def test_mcp_service_verify_drift(self):
        drift_report = self.service.verify_drift(deep=True)
        self.assertEqual(len(drift_report["drift"]), 0)
        self.assertFalse(drift_report["truncated"])


if __name__ == "__main__":
    unittest.main()
