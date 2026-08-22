"""Phase 2: repo map (PageRank + token budget), pack trusted tier, MCP notes."""
import argparse
import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.cli import cmd_map
from sot_graph.db import Database
from sot_graph.mcp_service import McpService
from sot_graph.pack import build_bundle, render_yaml
from sot_graph.reconciler import Reconciler
from sot_graph.repo_map import build_repo_map

HUB_PROJECT = {
    "src/app/hub.py": "def hub():\n    return 1\n",
    "src/app/a.py": "from app.hub import hub\n\ndef use_a():\n    return hub()\n",
    "src/app/b.py": "from app.hub import hub\n\ndef use_b():\n    return hub()\n",
    "src/app/leaf.py": "def leaf():\n    return 9\n",
}

PACK_PROJECT = {
    "src/app/store.py": "def fetch(key):\n    return key\n",
    "AGENTS.md": "# Project rules\nAlways run tests. MARKER_TRUSTED_123\n",
}


class RepoMapTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        for rel, content in HUB_PROJECT.items():
            target = Path(self.test_dir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.db = Database(os.path.join(self.test_dir, ".sot", "test.db"))
        Reconciler(self.db, self.test_dir).reconcile(workers=1)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _top_symbol(self, result):
        return max((s for f in result["files"] for s in f["symbols"]),
                   key=lambda s: s["rank"])["symbol"]

    def test_pagerank_ranks_hub_above_isolated_leaf(self):
        result = build_repo_map(self.db.conn, max_tokens=1024)
        self.assertEqual(self._top_symbol(result), "hub")
        ranked = sorted((s["rank"] for f in result["files"] for s in f["symbols"]))
        self.assertLess(ranked[0], ranked[-1])

    def test_focus_personalization_promotes_focused_symbol(self):
        plain = build_repo_map(self.db.conn, max_tokens=1024)
        focused = build_repo_map(self.db.conn, focus=["leaf"], max_tokens=1024)
        self.assertEqual(focused["focus"], [self._node_id("leaf")])
        included = {s["symbol"] for f in focused["files"] for s in f["symbols"]}
        self.assertIn("leaf", included)  # focus symbols are always in the map
        ranks_plain = {s["symbol"]: s["rank"] for f in plain["files"] for s in f["symbols"]}
        ranks_focus = {s["symbol"]: s["rank"] for f in focused["files"] for s in f["symbols"]}
        self.assertGreater(ranks_focus["leaf"], ranks_plain["leaf"])

    def test_token_budget_is_respected(self):
        result = build_repo_map(self.db.conn, max_tokens=24)
        self.assertLessEqual(result["tokens_estimate"], 24)
        self.assertGreaterEqual(result["symbols"], 1)

    def test_cmd_map_prints_tree_and_footer(self):
        args = argparse.Namespace(tokens=512, focus=None)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cmd_map(args, self.db, self.test_dir), 0)
        out = buf.getvalue()
        self.assertIn("src/app/hub.py:", out)
        self.assertIn("def hub", out)
        self.assertIn("Repo map", out)

    def _node_id(self, symbol):
        return self.db.conn.execute(
            "SELECT id FROM graph_nodes WHERE symbol = ?", (symbol,)
        ).fetchone()[0]


class PackTrustedTierTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        for rel, content in PACK_PROJECT.items():
            target = Path(self.test_dir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.db = Database(os.path.join(self.test_dir, ".sot", "test.db"))
        Reconciler(self.db, self.test_dir).reconcile(workers=1)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_bundle_embeds_trusted_agents_md(self):
        bundle = build_bundle(self.db, self.test_dir, "fetch")
        trusted = bundle["trusted_instructions"]
        self.assertEqual(trusted["path"], "AGENTS.md")
        self.assertFalse(trusted["content_is_untrusted"])
        self.assertIn("MARKER_TRUSTED_123", trusted["content"])
        # The global banner stays untrusted: code content is still data.
        self.assertTrue(bundle["content_is_untrusted"])

    def test_yaml_renders_trusted_block_with_explicit_flag(self):
        bundle = build_bundle(self.db, self.test_dir, "fetch")
        text = render_yaml(bundle)
        self.assertIn("trusted_instructions:", text)
        self.assertIn("content_is_untrusted: false", text)
        self.assertIn("MARKER_TRUSTED_123", text)

    def test_no_agents_md_means_no_trusted_block(self):
        os.unlink(os.path.join(self.test_dir, "AGENTS.md"))
        bundle = build_bundle(self.db, self.test_dir, "fetch")
        self.assertNotIn("trusted_instructions", bundle)


class McpMapAndNotesTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        for rel, content in HUB_PROJECT.items():
            target = Path(self.test_dir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        db = Database(os.path.join(self.test_dir, ".sot", "test.db"))
        Reconciler(db, self.test_dir).reconcile(workers=1)
        with db.conn:
            db.conn.execute(
                "INSERT INTO graph_nodes (id, path, kind, symbol, label, body, keywords, "
                "line_start, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                ("note:abc123def456", "", "note", None, "Deploy gotcha",
                 "worker count must stay 1", "deploy ops", 1, 1700000000),
            )
            db.conn.execute(
                "INSERT INTO graph_nodes (id, path, kind, symbol, label, body, keywords, "
                "line_start, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                ("note:fff000111222", "", "note", None, "Graph schema note",
                 "schema v3 drops legacy", "schema db", 1, 1700000001),
            )
        db.close()
        self.service = McpService(
            os.path.join(self.test_dir, ".sot", "test.db"), self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_mcp_repo_map(self):
        res = self.service.repo_map()
        self.assertTrue(res["ok"])
        self.assertIn("def hub", res["map"])
        focused = self.service.repo_map(focus="leaf")
        self.assertEqual(len(focused["focus"]), 1)

    def test_mcp_notes_list_and_filter(self):
        res = self.service.notes()
        self.assertEqual(res["returned"], 2)
        titles = {n["title"] for n in res["notes"]}
        self.assertEqual(titles, {"Deploy gotcha", "Graph schema note"})
        filtered = self.service.notes(query="deploy")
        self.assertEqual([n["title"] for n in filtered["notes"]], ["Deploy gotcha"])
        empty = self.service.notes(query="nothing_matches_zz")
        self.assertEqual(empty["notes"], [])


if __name__ == "__main__":
    unittest.main()
