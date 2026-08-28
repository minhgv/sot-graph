import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sot_graph.db import Database
from sot_graph.mcp_service import McpService, McpServiceError
from sot_graph.reconciler import ReconcileSummary, Reconciler


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

    def test_mcp_service_architecture_report(self):
        report = self.service.get_architecture_report()
        self.assertIn("report_markdown", report)
        self.assertIn("metrics", report)
        self.assertIn("communities", report)
        self.assertIn("god_nodes", report)
        self.assertIn("# Architectural Knowledge Graph Report", report["report_markdown"])

    def test_mcp_service_communities(self):
        comm_res = self.service.get_communities()
        self.assertIn("communities", comm_res)
        self.assertIn("community_count", comm_res)
        self.assertGreaterEqual(comm_res["community_count"], 1)

    def test_diff_impact_auto_reconciles_before_read(self):
        commands = [
            ["git", "init"],
            ["git", "config", "user.name", "sot-test"],
            ["git", "config", "user.email", "sot-test@example.invalid"],
            ["git", "add", "service.py"],
            ["git", "commit", "-m", "initial"],
        ]
        for command in commands:
            subprocess.run(
                command,
                cwd=self.test_dir,
                check=True,
                capture_output=True,
                text=True,
            )

        source = Path(self.test_dir) / "service.py"
        source.write_text(
            "class PaymentService:\n"
            "    def process_order(self, order_id: str):\n"
            "        return order_id\n"
        )
        stale = self.service.diff_impact(
            target="HEAD",
            working_tree=True,
            auto_reconcile=False,
            format="json",
        )
        self.assertIn("service.py", stale["stale_files"])

        refreshed = self.service.diff_impact(
            target="HEAD",
            working_tree=True,
            auto_reconcile=True,
            format="json",
        )
        self.assertEqual(refreshed["stale_files"], [])
        self.assertEqual(refreshed["reconcile"]["status"], "success")

    def test_diff_impact_reports_reconcile_failure_and_conflict_status(self):
        cases = (
            (ReconcileSummary(1, 0, 0, 0, 1, 0), "failed"),
            (ReconcileSummary(1, 0, 0, 0, 0, 0, conflicts=1), "conflicts"),
        )
        for summary, expected_status in cases:
            with self.subTest(expected_status=expected_status):
                with patch(
                    "sot_graph.reconciler.Reconciler.reconcile",
                    return_value=summary,
                ):
                    response = self.service.diff_impact(
                        target="HEAD",
                        auto_reconcile=True,
                        format="json",
                    )

                self.assertEqual(response["reconcile"]["status"], expected_status)
                self.assertTrue(response["ok"])
                self.assertEqual(response["status"], "success")
                self.assertEqual(response["reconcile"]["failed"], summary.failed)
                self.assertEqual(
                    response["reconcile"]["conflicts"], summary.conflicts
                )

    def test_diff_impact_reconcile_error_keeps_error_envelope(self):
        with patch(
            "sot_graph.reconciler.Reconciler.reconcile",
            side_effect=RuntimeError("not exposed"),
        ):
            with self.assertRaises(McpServiceError) as raised:
                self.service.diff_impact(
                    target="HEAD",
                    auto_reconcile=True,
                    format="json",
                )

        self.assertEqual(raised.exception.code, "reconcile_failed")


if __name__ == "__main__":
    unittest.main()
