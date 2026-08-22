"""Unit tests for ArchitectureBundler, CLI sot bundle, and MCP integration."""

import asyncio
import json
import os
import shutil
import tempfile
import unittest

from sot_graph.analytics.bundle import ArchitectureBundler
from sot_graph.analytics.graph import AnalyticsGraph
from sot_graph.cli import build_parser, cmd_bundle
from sot_graph.db import Database
from sot_graph.mcp_service import McpService
from sot_graph.reconciler import Reconciler


class TestArchitectureBundler(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, ".sot", "sot.db")
        self.db = Database(self.db_path)

        # Create sample project structure
        self.src_dir = os.path.join(self.test_dir, "src", "sample_app")
        os.makedirs(self.src_dir, exist_ok=True)

        # Create controller
        with open(os.path.join(self.src_dir, "controller.py"), "w") as f:
            f.write(
                "class UserController:\n"
                "    def get_users(self):\n"
                "        return []\n"
                "\n"
                "    def create_user(self, data):\n"
                "        return {'id': 1}\n"
            )

        # Create service
        with open(os.path.join(self.src_dir, "service.py"), "w") as f:
            f.write(
                "class UserService:\n"
                "    def process_signup(self, email):\n"
                "        # transitions: draft -> pending -> active\n"
                "        return True\n"
            )

        # Create model
        with open(os.path.join(self.src_dir, "models.py"), "w") as f:
            f.write(
                "class User:\n"
                "    def __init__(self, name):\n"
                "        self.name = name\n"
            )

        # Reconcile project into database
        reconciler = Reconciler(self.db, self.test_dir)
        reconciler.reconcile(workers=1)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_bundler_extract_bundle(self):
        bundler = ArchitectureBundler(db=self.db, root_dir=self.test_dir)
        bundle_dir = os.path.join(self.test_dir, ".sot", "bundle")
        generated = bundler.extract_bundle(bundle_dir)

        self.assertIn("01_module_inventory.md", generated)
        self.assertIn("02_routing_endpoints.md", generated)
        self.assertIn("03_workflows_states.md", generated)
        self.assertIn("04_dependencies_violations.md", generated)
        self.assertIn("05_system_metrics.json", generated)

        for filename in generated.keys():
            filepath = os.path.join(bundle_dir, filename)
            self.assertTrue(os.path.exists(filepath), f"File {filepath} does not exist")
            self.assertGreater(os.path.getsize(filepath), 0, f"File {filepath} is empty")

        # Verify metrics JSON content
        metrics_file = os.path.join(bundle_dir, "05_system_metrics.json")
        with open(metrics_file, "r") as f:
            metrics = json.load(f)
            self.assertIn("project_root", metrics)
            self.assertIn("modularity_score_q", metrics)
            self.assertIn("total_nodes", metrics)
            self.assertIn("total_edges", metrics)

    def test_bundler_with_graph_instance(self):
        graph = AnalyticsGraph.from_database(self.db)
        bundler = ArchitectureBundler(root_dir=self.test_dir, graph=graph)
        out_dir = os.path.join(self.test_dir, "custom_bundle")
        generated = bundler.extract_bundle(out_dir)

        self.assertEqual(len(generated), 5)
        self.assertTrue(os.path.exists(os.path.join(out_dir, "01_module_inventory.md")))

    def test_cli_cmd_bundle(self):
        parser = build_parser()
        args = parser.parse_args(["bundle", "-o", os.path.join(self.test_dir, "cli_bundle")])
        code = cmd_bundle(args, self.db, self.test_dir)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "cli_bundle", "01_module_inventory.md")))

    def test_mcp_service_bundle_sync_and_async(self):
        service = McpService(self.db_path, self.test_dir)

        # Sync test
        out_dir = os.path.join(self.test_dir, "mcp_bundle")
        res = service.get_architecture_bundle(output_dir=out_dir)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["files"]), 5)
        self.assertIn("metrics", res)

        # Async test
        async def run_async():
            return await service.aget_architecture_bundle(output_dir=os.path.join(self.test_dir, "mcp_async_bundle"))

        async_res = asyncio.run(run_async())
        self.assertTrue(async_res["ok"])
        self.assertEqual(len(async_res["files"]), 5)


if __name__ == "__main__":
    unittest.main()
