"""
Unit tests for Sprint 4 (Phase 3): Compass UX, Hop Renderer, Live-Verified Context Pack, and Token Budgeting.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.cli import cmd_explore
from sot_graph.db import Database, _EXPLORE_CHUNK
from sot_graph.mcp_service import McpService
from sot_graph.pack import PackError, build_bundle
from sot_graph.reconciler import Reconciler
from sot_graph.repo_map import build_repo_map
from sot_graph.tokenizer import (
    estimate_tokens,
    fit_lines_to_token_budget,
    truncate_to_token_budget,
)


def _reference_explore_node(db, node_id, depth=1, limit=None):
    """Differential oracle: the pre-R5 per-node BFS, kept verbatim.

    explore_node must produce byte-identical output to this one-query-per-
    node loop (R5 batched the fetch per LEVEL without changing semantics).
    Note: edge ties with identical (direction, target id) have unspecified
    order in both implementations, so test graphs use at most one edge per
    (src, dst) pair.
    """
    if depth < 0 or (limit is not None and limit <= 0):
        return []
    visited = set()
    result = []
    queue = [(node_id, 0, None, None, None)]
    sql = (
        "SELECT 'outward' AS dir, e.relation, n.id, n.label, n.path, n.line_start, n.kind "
        "FROM graph_edges e JOIN graph_nodes n ON e.dst=n.id "
        "WHERE e.src=? AND e.relation != 'defines' "
        "UNION ALL "
        "SELECT 'inward' AS dir, e.relation, n.id, n.label, n.path, n.line_start, n.kind "
        "FROM graph_edges e JOIN graph_nodes n ON e.src=n.id "
        "WHERE e.dst=? AND e.relation != 'defines' "
        "ORDER BY dir DESC, n.id"
    )
    while queue and (limit is None or len(result) < limit):
        current, current_depth, via_id, via_label, via_path = queue.pop(0)
        if current in visited or current_depth >= depth:
            continue
        visited.add(current)
        rows = db.conn.execute(sql, (current, current)).fetchall()
        for direction, rel, target, label, path, line, kind in rows:
            if target == node_id:
                continue
            rel_label = rel if direction == "outward" else f"used_by ({rel})"
            hop_num = current_depth + 1
            result.append({
                "direction": direction,
                "relation": rel_label,
                "target_id": target,
                "label": label,
                "path": path,
                "line": line,
                "kind": kind,
                "depth": hop_num,
                "hop": hop_num,
                "via_id": via_id if hop_num > 1 else None,
                "via_label": via_label if hop_num > 1 else None,
                "via_path": via_path if hop_num > 1 else None,
            })
            if target not in visited and hop_num < depth:
                queue.append((target, hop_num, target, label, path))
            if limit is not None and len(result) >= limit:
                break
    return result


class ExploreNodeLevelBatchTests(unittest.TestCase):
    """R5: level-batched BFS must exactly match the per-node reference."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="sot-explore-batch-")
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)
        self.db = Database(os.path.join(self.test_dir, "test.db"))
        self.addCleanup(self.db.close)

    def _add_node(self, node_id, updated_at=0):
        self.db.conn.execute(
            "INSERT INTO graph_nodes (id, path, kind, symbol, label, body, "
            "keywords, line_start, updated_at) "
            "VALUES (?, ?, 'function', ?, ?, '', '', 1, ?)",
            (node_id, f"{node_id.lower()}.py", node_id, node_id, updated_at),
        )

    def _add_edge(self, src, dst, relation="calls", line=1):
        self.db.conn.execute(
            "INSERT INTO graph_edges (path, src, dst, relation, line) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"{src.lower()}.py", src, dst, relation, line),
        )

    def _commit(self):
        self.db.conn.commit()

    def test_deep_chain_matches_reference(self):
        for node in ("A", "B", "C", "D", "E"):
            self._add_node(node)
        for src, dst in (("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")):
            self._add_edge(src, dst)
        self._commit()
        for depth in (1, 2, 3, 4, 6):
            with self.subTest(depth=depth):
                self.assertEqual(
                    self.db.explore_node("A", depth=depth),
                    _reference_explore_node(self.db, "A", depth=depth),
                )

    def test_wide_fanout_across_chunks_matches_reference(self):
        # root -> 600 children (spans 3 chunks of 250), each child -> leaf.
        self._add_node("root")
        children = [f"C{i:03d}" for i in range(600)]
        for i, child in enumerate(children):
            self._add_node(child, updated_at=i)
            self._add_node(f"L{i:03d}", updated_at=i)
            self._add_edge(child, f"L{i:03d}")
        for child in children:
            self._add_edge("root", child)
        self._commit()
        explored = self.db.explore_node("root", depth=2)
        reference = _reference_explore_node(self.db, "root", depth=2)
        self.assertEqual(len(explored), 1200)
        self.assertEqual(explored, reference)
        # Level batching: 1 node at hop 0 + 600 nodes at hop 1 across
        # ceil(600 / chunk) chunks => exactly that many chunked IN queries.
        class _CountingConn:
            def __init__(self, conn):
                self._conn = conn
                self.queries = []

            def execute(self, sql, *args):
                self.queries.append(sql)
                return self._conn.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self._conn, name)

        counting = _CountingConn(self.db.conn)
        original_conn = self.db.conn
        self.db.conn = counting
        try:
            self.db.explore_node("root", depth=2)
        finally:
            self.db.conn = original_conn
        in_queries = [s for s in counting.queries if " IN (" in s]
        self.assertEqual(len(in_queries), 1 + math.ceil(600 / _EXPLORE_CHUNK))

    def test_random_graphs_match_reference_across_depths_and_limits(self):
        import random

        rng = random.Random(20260903)
        nodes = [f"n{i:02d}" for i in range(80)]
        for node in nodes:
            self._add_node(node)
        # One edge max per (src, dst) pair: tie order is unspecified in
        # both implementations, so differential graphs avoid ties.
        pairs = {(s, d) for s in nodes for d in nodes if s != d}
        chosen = rng.sample(sorted(pairs), 200)
        for src, dst in chosen:
            self._add_edge(src, dst, relation=rng.choice(["calls", "imports"]))
        self._commit()
        for start in ("n00", "n17", "n63", "missing_node"):
            for depth in (0, 1, 2, 3):
                for limit in (None, 1, 7, 500):
                    with self.subTest(start=start, depth=depth, limit=limit):
                        self.assertEqual(
                            self.db.explore_node(start, depth=depth, limit=limit),
                            _reference_explore_node(self.db, start, depth=depth, limit=limit),
                        )

    def test_hop_bound_and_limit_respected(self):
        for node in ("A", "B", "C", "D", "E"):
            self._add_node(node)
        for src, dst in (("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")):
            self._add_edge(src, dst)
        self._commit()
        bounded = self.db.explore_node("A", depth=2)
        self.assertTrue(bounded)
        self.assertTrue(all(r["hop"] <= 2 for r in bounded))
        truncated = self.db.explore_node("A", depth=4, limit=2)
        self.assertEqual(len(truncated), 2)
        self.assertEqual(truncated, _reference_explore_node(self.db, "A", depth=4, limit=2))
        # Unbounded default (limit=None) still drains the whole component —
        # identical to the per-node reference at any depth.
        unbounded = self.db.explore_node("A", depth=10)
        self.assertEqual(unbounded, _reference_explore_node(self.db, "A", depth=10))
        self.assertGreater(len(unbounded), len(bounded))


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

    def test_pack_budget_too_small_raises_pack_error(self):
        """Verify build_bundle raises PackError with code BUDGET_TOO_SMALL when max_tokens < 32."""
        with self.assertRaises(PackError) as ctx:
            build_bundle(self.db, self.test_dir, "MainService.process", max_tokens=15)
        self.assertEqual(ctx.exception.code, "BUDGET_TOO_SMALL")

    def test_pack_untrusted_repo_content_policy(self):
        """Verify pack context bundle marks repo-derived source content as untrusted."""
        bundle = build_bundle(self.db, self.test_dir, "MainService.process")
        self.assertTrue(bundle.get("content_is_untrusted"))

    def test_atomic_rehome_content_hash(self):
        """Verify content-hash atomic rehome when a file is renamed."""
        old_path = os.path.join(self.test_dir, "pkg", "leaf.py")
        new_path = os.path.join(self.test_dir, "pkg", "leaf_renamed.py")
        os.rename(old_path, new_path)
        
        self.reconciler.reconcile(workers=1)
        
        # Verify node paths moved to new_path
        nodes = self.db.conn.execute("SELECT path FROM graph_nodes WHERE path LIKE '%leaf_renamed.py'").fetchall()
        self.assertGreaterEqual(len(nodes), 1)
        old_nodes = self.db.conn.execute("SELECT path FROM graph_nodes WHERE path LIKE '%pkg/leaf.py'").fetchall()
        self.assertEqual(len(old_nodes), 0)
        # Verify DB integrity check passes with 0 orphan edges
        integrity = self.db.integrity_check()
        self.assertTrue(integrity["is_healthy"])
        self.assertEqual(integrity["quick_check"], "ok")

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
