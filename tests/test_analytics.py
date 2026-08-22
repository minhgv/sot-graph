from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sot_graph.analytics.diagnostics import (
    analyze_graph,
    calculate_graph_metrics,
)
from sot_graph.analytics.graph import AnalyticsGraph
from sot_graph.analytics.report import generate_markdown_report
from sot_graph.cli import build_parser, cmd_cluster, cmd_report
from sot_graph.db import Database
from sot_graph.reconciler import Reconciler


class AnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.mkdtemp(prefix="sot-analytics-")
        self.root = Path(self._temp_dir)
        self.db_path = self.root / ".sot" / "sot.db"
        self.db = Database(str(self.db_path))

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _populate_mock_project(self) -> None:
        """Create a mock codebase with two distinct modules and a cross-cutting god node."""
        src_auth = self.root / "src" / "auth"
        src_auth.mkdir(parents=True, exist_ok=True)
        (src_auth / "login.py").write_text(
            "class LoginService:\n"
            "    def authenticate(self, user, pwd):\n"
            "        return True\n"
            "    def issue_token(self, user):\n"
            "        return 'tok_123'\n"
        )
        (src_auth / "session.py").write_text(
            "from auth.login import LoginService\n"
            "class SessionManager:\n"
            "    def __init__(self):\n"
            "        self.svc = LoginService()\n"
        )

        src_billing = self.root / "src" / "billing"
        src_billing.mkdir(parents=True, exist_ok=True)
        (src_billing / "invoice.py").write_text(
            "class InvoiceManager:\n"
            "    def generate_invoice(self, amount):\n"
            "        return {'amount': amount}\n"
        )
        (src_billing / "payment.py").write_text(
            "from billing.invoice import InvoiceManager\n"
            "from auth.login import LoginService\n"
            "class PaymentProcessor:\n"
            "    def process(self):\n"
            "        LoginService().authenticate('admin', 'pwd')\n"
            "        InvoiceManager().generate_invoice(100)\n"
        )

        reconciler = Reconciler(self.db, str(self.root))
        reconciler.reconcile()

    def test_analytics_graph_construction_and_metrics(self) -> None:
        self._populate_mock_project()
        graph = AnalyticsGraph.from_database(self.db)

        self.assertGreater(len(graph.nodes), 4)
        self.assertGreater(len(graph.edges), 2)

        res = graph.detect_communities(min_community_size=1)
        self.assertGreaterEqual(len(res.communities), 1)
        self.assertIn(res.modularity, res.__dict__.values())

        metrics = calculate_graph_metrics(graph, res)
        self.assertGreater(metrics.node_count, 0)
        self.assertGreater(metrics.edge_count, 0)
        self.assertGreaterEqual(metrics.density, 0.0)

    def test_god_nodes_and_surprising_connections(self) -> None:
        self._populate_mock_project()
        graph = AnalyticsGraph.from_database(self.db)

        analysis = analyze_graph(graph, min_community_size=1, threshold_sigma=0.5)
        self.assertIsNotNone(analysis.metrics)
        self.assertIsNotNone(analysis.community_result)

        # Generate markdown report and assert section headers
        report = generate_markdown_report(analysis, project_name="MockProject")
        self.assertIn("# Architectural Knowledge Graph Report: MockProject", report)
        self.assertIn("## 1. Executive Summary & Graph Topology", report)
        self.assertIn("## 2. Architectural Communities & Module Breakdown", report)
        self.assertIn("## 3. Critical God Nodes & Architectural Bottlenecks", report)
        self.assertIn("## 5. Actionable Recommendations & Focus Areas", report)

    def test_db_community_persistence_and_retrieval(self) -> None:
        sample_communities = [
            {
                "community_id": 0,
                "label": "Auth Module (login, session)",
                "cohesion_score": 0.85,
                "node_count": 4,
                "nodes": ["auth:login", "auth:session", "auth:LoginService", "auth:SessionManager"],
            },
            {
                "community_id": 1,
                "label": "Billing Module (invoice, payment)",
                "cohesion_score": 0.72,
                "node_count": 3,
                "nodes": ["billing:invoice", "billing:payment", "billing:InvoiceManager"],
            },
        ]

        self.db.save_communities(sample_communities)
        stored = self.db.get_communities()
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0]["label"], "Auth Module (login, session)")
        self.assertEqual(len(stored[0]["nodes"]), 4)

        single = self.db.get_community(1)
        self.assertIsNotNone(single)
        assert single is not None
        self.assertEqual(single["community_id"], 1)
        self.assertEqual(single["label"], "Billing Module (invoice, payment)")

    def test_cli_report_and_cluster_commands(self) -> None:
        self._populate_mock_project()
        parser = build_parser()

        # Test 'sot cluster' JSON
        args_cluster_json = parser.parse_args(["cluster", "--json"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cmd_cluster(args_cluster_json, self.db)
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("communities_count", data)
        self.assertIn("communities", data)

        # Test 'sot report' JSON
        args_report_json = parser.parse_args(["report", "--json"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cmd_report(args_report_json, self.db, str(self.root))
        self.assertEqual(code, 0)
        rep_data = json.loads(buf.getvalue())
        self.assertIn("metrics", rep_data)
        self.assertIn("communities", rep_data)
        self.assertIn("god_nodes", rep_data)

        # Test 'sot report' Markdown file write
        report_file = self.root / "TEST_REPORT.md"
        args_report_md = parser.parse_args(["report", "-o", str(report_file)])
        with redirect_stdout(io.StringIO()):
            code = cmd_report(args_report_md, self.db, str(self.root))
        self.assertEqual(code, 0)
        self.assertTrue(report_file.exists())
        content = report_file.read_text(encoding="utf-8")
        self.assertIn("# Architectural Knowledge Graph Report", content)


if __name__ == "__main__":
    unittest.main()
