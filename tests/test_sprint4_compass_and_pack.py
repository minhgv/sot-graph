"""
Unit tests for Sprint 4 (Phase 3): Compass UX, Hop Renderer, Live-Verified Context Pack, and Token Budgeting.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.cli import cmd_explore
from sot_graph.db import Database
from sot_graph.mcp_service import McpService
from sot_graph.pack import build_bundle
from sot_graph.reconciler import Reconciler
from sot_graph.repo_map import build_repo_map
from sot_graph.tokenizer import (
    estimate_tokens,
    fit_lines_to_token_budget,
    truncate_to_token_budget,
)


class Sprint4CompassAndPackTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.project_files = {
            "pkg/__init__.py": "# pkg root\n",
            "pkg/leaf.py": "def leaf_func():\n    return 42\n",
            "pkg/intermediate.py": (
                "from pkg.leaf import leaf_func\n\n"
                "def helper_func():\n"
                "    return leaf_func()\n"
            ),
            "pkg/main_service.py": (
                "from pkg.intermediate import helper_func\n\n"
                "class MainService:\n"
                "    def process(self):\n"
                "        return helper_func()\n"
            ),
            "pkg/caller.py": (
                "from pkg.main_service import MainService\n\n"
                "def run_app():\n"
                "    svc = MainService()\n"
                "    return svc.process()\n"
            ),
            "AGENTS.md": "# Agent Instructions\nAlways verify token budgets and live files.\n",
        }
        for rel, content in self.project_files.items():
            path = Path(self.test_dir) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        self.db_path = os.path.join(self.test_dir, ".sot", "test.db")
        self.db = Database(self.db_path)
        self.reconciler = Reconciler(self.db, self.test_dir)
        self.reconciler.reconcile(workers=1)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_tokenizer_calibrated_estimation_and_truncation(self):
        """Verify token estimation and line/token truncation utilities."""
        sample_code = (
            "def compute_metrics(x: int, y: int) -> float:\n"
            "    # Calculate weighted harmonic mean\n"
            "    return (2.0 * x * y) / (x + y)\n"
        )
        tok_count = estimate_tokens(sample_code)
        self.assertGreater(tok_count, 5)
        self.assertLess(tok_count, 50)

        # Truncation to budget
        trunc_text, is_trunc, final_toks = truncate_to_token_budget(sample_code, max_tokens=10)
        self.assertTrue(is_trunc)
        self.assertIn("TRUNCATED", trunc_text)
        self.assertLessEqual(final_toks, 20)

        # Line fitting
        lines = ["line 1\n", "line 2\n", "line 3\n", "line 4\n"]
        chosen, truncated, count = fit_lines_to_token_budget(lines, max_tokens=6)
        self.assertTrue(len(chosen) <= len(lines))

    def test_db_explore_node_hop_separation(self):
        """Verify explore_node separates 1-hop direct vs 2-hop transitive edges with via metadata."""
        # Find MainService.process node id
        row = self.db.conn.execute(
            "SELECT id FROM graph_nodes WHERE symbol = 'MainService.process' OR symbol = 'process'"
        ).fetchone()
        self.assertIsNotNone(row)
        node_id = row[0]

        explored = self.db.explore_node(node_id, depth=2)
        self.assertGreaterEqual(len(explored), 1)

        # Inspect hops
        hop1_items = [e for e in explored if e["hop"] == 1]
        hop2_items = [e for e in explored if e["hop"] == 2]

        self.assertTrue(len(hop1_items) >= 1)
        for h1 in hop1_items:
            self.assertEqual(h1["depth"], 1)
            self.assertIsNone(h1["via_id"])

        for h2 in hop2_items:
            self.assertEqual(h2["depth"], 2)
            self.assertIsNotNone(h2["via_id"])
            self.assertIsNotNone(h2["via_label"])

    def test_cli_explore_hop_rendering_and_json(self):
        """Verify CLI explore command formats 1-hop and 2-hop sections clearly."""
        args_text = argparse.Namespace(target="MainService.process", depth=2, all=False, json=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ret = cmd_explore(args_text, self.db)
        self.assertEqual(ret, 0)
        output = buf.getvalue()
        self.assertIn("1-Hop Direct", output)

        # Test JSON mode
        args_json = argparse.Namespace(target="MainService.process", depth=2, all=False, json=True)
        buf_json = io.StringIO()
        with contextlib.redirect_stdout(buf_json):
            ret_json = cmd_explore(args_json, self.db)
        self.assertEqual(ret_json, 0)
        data = json.loads(buf_json.getvalue())
        self.assertIn("target", data)
        self.assertIn("hop_summary", data)
        self.assertIn("1_hop_direct", data["hop_summary"])

    def test_mcp_explore_structured_hops(self):
        """Verify MCP service explore returns hop_summary and via fields."""
        mcp = McpService(self.db_path, project_root=self.test_dir)
        res = mcp.explore("MainService.process", depth=2)
        self.assertIn("node", res)
        self.assertIn("relations", res)
        self.assertIn("hop_summary", res)
        for rel in res["relations"]:
            self.assertIn("hop", rel)

    def test_pack_live_neighbor_verification_fresh_stale_missing(self):
        """Verify neighbor files are live-verified: FRESH when matching, STALE when edited, MISSING when deleted."""
        # 1. Fresh state
        bundle = build_bundle(self.db, self.test_dir, "MainService.process")
        self.assertEqual(bundle["target"]["trust_verdict"], "STRONG")
        for caller in bundle["inbound_callers"]:
            self.assertEqual(caller["trust_verdict"], "FRESH")

        # 2. Modify neighbor file on disk without reconciling
        caller_file = Path(self.test_dir) / "pkg/caller.py"
        caller_file.write_text(caller_file.read_text() + "\n# Modified on disk\n")

        bundle_stale = build_bundle(self.db, self.test_dir, "MainService.process")
        stale_callers = [c for c in bundle_stale["inbound_callers"] if c["trust_verdict"] == "STALE"]
        self.assertGreaterEqual(len(stale_callers), 1)
        warnings = bundle_stale["limits"]["warnings"]
        self.assertTrue(any("neighbor_stale" in w for w in warnings))

        # 3. Delete neighbor file on disk without reconciling
        caller_file.unlink()
        bundle_missing = build_bundle(self.db, self.test_dir, "MainService.process")
        missing_callers = [c for c in bundle_missing["inbound_callers"] if c["trust_verdict"] == "MISSING"]
        self.assertGreaterEqual(len(missing_callers), 1)
        self.assertTrue(any("neighbor_missing" in w for w in bundle_missing["limits"]["warnings"]))

    def test_pack_hard_token_budget_pruning(self):
        """Verify build_bundle strictly enforces max_tokens by dropping stubs/callees and truncating."""
        # Request a tight budget e.g. 350 tokens
        tight_budget = 350
        bundle_tight = build_bundle(self.db, self.test_dir, "MainService.process", max_tokens=tight_budget)
        tight_tokens = bundle_tight["limits"]["tokens_estimate"]
        self.assertTrue(bundle_tight["limits"]["truncated"])
        # Should be within tight budget + small YAML framing tolerance <= 25 tokens
        self.assertLessEqual(tight_tokens, tight_budget + 25)
    def test_repo_map_language_breakdown_and_token_fit(self):
        """Verify repo map calculates language breakdown and fits token budget."""
        result = build_repo_map(self.db.conn, max_tokens=500, root=self.test_dir)
        self.assertIn("language_breakdown", result)
        self.assertIn("ranking_method", result)
        self.assertIn("py", result["language_breakdown"])
        self.assertEqual(result["language_breakdown"]["py"], 100.0)
        self.assertLessEqual(result["tokens_estimate"], 500)


if __name__ == "__main__":
    unittest.main()
