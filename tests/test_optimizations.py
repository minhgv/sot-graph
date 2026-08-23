"""
tests/test_optimizations.py
Comprehensive unit tests for the 5 architectural optimizations:
1. UI Controller filtering & route detection precision in architecture.py.
2. Test/Mock path detection & exclusion in bundle.py / architecture.py.
3. AST line_end resilience across extractors.
4. Batch Multi-Repo Reconcile with per-repo SQLite isolation.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.analytics.architecture import (
    ArchitecturalLayer,
    extract_routing_architecture,
    is_test_or_mock_path,
)
from sot_graph.analytics.bundle import ArchitectureBundler
from sot_graph.analytics.graph import AnalyticsGraph
from sot_graph.cli import (
    _discover_repos,
    _reconcile_single_repo,
    build_parser,
    cmd_batch_reconcile,
)
from sot_graph.db import Database
from sot_graph.extractor import parse_file_graph


class TestOptimizations(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="sot_test_opt_")

    def tearDown(self):
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. UI Controller filtering & Route Detection
    def test_ui_controller_and_presentation_filtering(self):
        graph = AnalyticsGraph()
        # Node 1: Flutter UI controller
        graph.add_node(
            "node_ctrl",
            label="class TextEditingController",
            path="lib/presentation/controllers/search_controller.dart",
            kind="symbol",
            line_start=15,
        )
        # Node 2: Flutter ScrollController
        graph.add_node(
            "node_scroll",
            label="class ScrollController",
            path="lib/widgets/scroll.dart",
            kind="symbol",
            line_start=30,
        )
        # Node 3: True HTTP Controller
        graph.add_node(
            "node_api",
            label="def get_user_profile(user_id: str)",
            path="app/api/v1/users.py",
            kind="symbol",
            line_start=45,
        )
        # Node 4: UI Page
        graph.add_node(
            "node_page",
            label="class ProfileScreen extends StatelessWidget",
            path="lib/ui/profile_screen.dart",
            kind="symbol",
            line_start=10,
        )

        node_layers = {
            "node_ctrl": ArchitecturalLayer.PRESENTATION,
            "node_scroll": ArchitecturalLayer.PRESENTATION,
            "node_api": ArchitecturalLayer.DATA,
            "node_page": ArchitecturalLayer.PRESENTATION,
        }

        routing = extract_routing_architecture(
            graph, node_layers, primary_lang="Dart", pattern_name="Clean Architecture"
        )

        http_handlers = [r.handler for r in routing.http_routes]
        self.assertIn("def get_user_profile(user_id: str)", http_handlers)
        self.assertNotIn("class TextEditingController", http_handlers)
        self.assertNotIn("class ScrollController", http_handlers)
        self.assertNotIn("class ProfileScreen extends StatelessWidget", http_handlers)

        # UI Page should be captured in ui_routes with line_start
        ui_handlers = [r.handler for r in routing.ui_routes]
        self.assertIn("class ProfileScreen extends StatelessWidget", ui_handlers)
        profile_route = next(r for r in routing.ui_routes if "ProfileScreen" in r.handler)
        self.assertEqual(profile_route.line, 10)
        self.assertEqual(profile_route.file_anchor, "lib/ui/profile_screen.dart:10")

    # 2. Test & Mock Path Exclusion
    def test_is_test_or_mock_path(self):
        self.assertTrue(is_test_or_mock_path("tests/test_api.py"))
        self.assertTrue(is_test_or_mock_path("src/module/tests/sub_test.py"))
        self.assertTrue(is_test_or_mock_path("lib/integration_test/app_test.dart"))
        self.assertTrue(is_test_or_mock_path("src/mocks/mock_auth.ts"))
        self.assertTrue(is_test_or_mock_path("frontend/src/components/button.spec.tsx"))
        self.assertTrue(is_test_or_mock_path("backend/api_test.go"))
        self.assertTrue(is_test_or_mock_path("test_something.py"))

        self.assertFalse(is_test_or_mock_path("src/core/models/user.py"))
        self.assertFalse(is_test_or_mock_path("lib/screens/contest_page.dart"))
        self.assertFalse(is_test_or_mock_path("app/controllers/testing_center_controller.py"))

    def test_bundle_test_exclusion(self):
        graph = AnalyticsGraph()
        # Production node
        graph.add_node(
            "node_prod",
            label="def create_order()",
            path="src/services/order_service.py",
            kind="symbol",
            line_start=10,
        )
        # Test node
        graph.add_node(
            "node_test",
            label="def test_create_order()",
            path="tests/test_order_service.py",
            kind="symbol",
            line_start=20,
        )

        bundler_no_tests = ArchitectureBundler(
            root_dir=self.tmp_dir, graph=graph, include_tests=False
        )
        bundle_no_tests = bundler_no_tests.extract_bundle(
            os.path.join(self.tmp_dir, "bundle_no_tests")
        )

        # Test node should NOT be present in 01_module_inventory.md or 02_routing_endpoints.md
        self.assertNotIn("test_order_service.py", bundle_no_tests["01_module_inventory.md"])
        self.assertNotIn("test_create_order", bundle_no_tests["02_routing_endpoints.md"])

        # With include_tests=True
        bundler_with_tests = ArchitectureBundler(
            root_dir=self.tmp_dir, graph=graph, include_tests=True
        )
        bundle_with_tests = bundler_with_tests.extract_bundle(
            os.path.join(self.tmp_dir, "bundle_with_tests")
        )
        self.assertIn("test_order_service.py", bundle_with_tests["01_module_inventory.md"])

    # 3. AST line_end Resilience
    def test_ast_line_end_resilience(self):
        sample_py = Path(self.tmp_dir) / "sample.py"
        sample_py.write_text(
            "def calculate_total(price, tax):\n"
            "    subtotal = price\n"
            "    return subtotal + tax\n\n"
            "class InvoiceCalculator:\n"
            "    def compute(self):\n"
            "        return 42\n",
            encoding="utf-8",
        )

        data = parse_file_graph(str(sample_py), self.tmp_dir)
        nodes = data.get("nodes", [])

        # Check file node
        file_node = next(n for n in nodes if n.get("kind") == "file")
        self.assertEqual(file_node.get("line_start"), 1)
        self.assertEqual(file_node.get("line_end"), 8)

        # Check function / class symbol nodes
        for node in nodes:
            if node.get("kind") != "file":
                self.assertIsNotNone(node.get("line_start"))
                self.assertIsNotNone(node.get("line_end"))
                self.assertGreaterEqual(node["line_end"], node["line_start"])

    # 4. Batch Multi-Repo Reconcile
    def test_batch_reconcile_and_repo_discovery(self):
        # Create 2 mock repo folders with .git
        repo_a = Path(self.tmp_dir) / "repo_a"
        repo_a.mkdir(parents=True)
        (repo_a / ".git").mkdir()
        (repo_a / "main.py").write_text("def hello(): pass\n", encoding="utf-8")

        repo_b = Path(self.tmp_dir) / "repo_b"
        repo_b.mkdir(parents=True)
        (repo_b / "package.json").write_text('{"name": "b"}', encoding="utf-8")
        (repo_b / "index.js").write_text("function foo() {}\n", encoding="utf-8")

        # Discover repos
        repos = _discover_repos(self.tmp_dir)
        self.assertEqual(len(repos), 2)
        repos_normalized = [os.path.realpath(r) for r in repos]
        self.assertIn(os.path.realpath(str(repo_a)), repos_normalized)
        self.assertIn(os.path.realpath(str(repo_b)), repos_normalized)

        # Reconcile single repo
        res_a = _reconcile_single_repo(str(repo_a), force=True, workers=1)
        self.assertEqual(res_a["status"], "ok")
        self.assertGreaterEqual(res_a["updated"], 1)

        # Check SQLite DB exists inside repo_a/.sot/sot.db
        db_a_path = repo_a / ".sot" / "sot.db"
        self.assertTrue(db_a_path.exists())

        # Test batch command
        parser = build_parser()
        args = parser.parse_args(["batch-reconcile", self.tmp_dir, "--workers", "2", "--json"])
        code = cmd_batch_reconcile(args, self.tmp_dir)
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
