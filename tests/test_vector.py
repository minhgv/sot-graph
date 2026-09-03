"""Phase 4: optional hybrid retrieval — sqlite-vec + RRF fusion."""
import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler

from sot_graph.vector import HashEmbedder, _vec_blob, index_nodes, prune_orphans, reciprocal_rank_fusion

try:
    import sqlite_vec  # noqa: F401
    from sot_graph.vector import hybrid_search, index_nodes, vector_search
    HAVE_VEC = True
except ImportError:  # pragma: no cover
    HAVE_VEC = False

PROJECT = {
    "src/app/store.py": "def fetch(key):\n    return key\n",
    "src/app/backoff.py": "def retry_with_backoff():\n    return 1\n",
    "src/app/client.py": "from app.store import fetch\n\ndef handler():\n    return fetch('k')\n",
}


class HashEmbedderTests(unittest.TestCase):
    def test_deterministic_and_normalized(self):
        emb = HashEmbedder(dim=64)
        a = emb.embed_query("fetch key store")
        b = emb.embed_query("fetch key store")
        self.assertEqual(a, b)
        norm = sum(v * v for v in a) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=5)

    def test_related_text_scores_higher_than_unrelated(self):
        emb = HashEmbedder(dim=256)
        q = emb.embed_query("retry backoff")
        near = emb.embed_query("retry_with_backoff retry backoff")
        far = emb.embed_query("fetch key store")

        def cos(u, v):
            return sum(x * y for x, y in zip(u, v))

        self.assertGreater(cos(q, near), cos(q, far))


class RRFFusionTests(unittest.TestCase):
    def test_rrf_prefers_items_present_in_both_rankings(self):
        fused = reciprocal_rank_fusion(["a", "b", "c"], ["b", "d", "a"])
        # b appears in both with a top rank (1/61 + 1/62); a is 1/61 + 1/63.
        self.assertGreater(fused["b"], fused["a"])
        self.assertGreater(fused["a"], fused["c"])
        self.assertGreater(fused["a"], fused["d"])


@unittest.skipUnless(HAVE_VEC, "sqlite-vec extra not installed")
class HybridSearchTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        for rel, content in PROJECT.items():
            target = Path(self.test_dir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.db = Database(os.path.join(self.test_dir, ".sot", "test.db"))
        Reconciler(self.db, self.test_dir).reconcile(workers=1)
        self.index_stats = index_nodes(self.db.conn)
        if not self.index_stats["embedded"]:
            self.skipTest("vec0 table unavailable")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_index_and_vector_search(self):
        self.assertGreaterEqual(self.index_stats["embedded"], 3)
        hits = vector_search(self.db.conn, "backoff")
        self.assertTrue(hits, "expected at least one vector hit")
        top_id = hits[0][0]
        row = self.db.conn.execute(
            "SELECT symbol FROM graph_nodes WHERE id = ?", (top_id,)
        ).fetchone()
        self.assertIn("backoff", (row[0] or "").lower())

    def test_hybrid_search_fuses_and_reports_sources(self):
        res = hybrid_search(self.db, "backoff", limit=5)
        self.assertEqual(res["mode"], "hybrid")
        self.assertGreaterEqual(res["returned"], 1)
        top = res["results"][0]
        self.assertIn("fused_score", top)
        self.assertIn("bm25", top["sources"])
        self.assertIn("vector", top["sources"])

    def test_hybrid_falls_back_to_bm25_without_vectors(self):
        self.db.conn.execute("DELETE FROM graph_vec")
        self.db.conn.commit()
        res = hybrid_search(self.db, "backoff", limit=5)
        self.assertEqual(res["mode"], "bm25")
        self.assertGreaterEqual(res["returned"], 1)
        self.assertEqual(res["results"][0]["sources"], ["bm25"])

    def test_index_nodes_is_deterministic_subset(self):
        """With cap below the node count, the same capped ids are kept."""
        first = index_nodes(self.db.conn, cap=2)
        ids_first = {
            r[0] for r in self.db.conn.execute("SELECT node_id FROM graph_vec")
        }
        second = index_nodes(self.db.conn, cap=2)
        ids_second = {
            r[0] for r in self.db.conn.execute("SELECT node_id FROM graph_vec")
        }
        self.assertEqual(len(ids_first), 2)
        # setUp already embedded these nodes; incremental keeps them as-is
        # and prunes everything rotated out of the capped selection.
        self.assertEqual(first["unchanged"], 2)
        self.assertGreaterEqual(first["pruned"], 1)
        # R5: the second call must be a no-op re-embed (incremental).
        self.assertEqual(second["embedded"], 0)
        self.assertEqual(second["unchanged"], 2)
        self.assertTrue(second["truncated"],
                        "3 embeddable nodes under cap=2 must report truncated")
        self.assertEqual(ids_first, ids_second,
                         "same cap must select the same deterministic subset")

    def test_reconcile_prunes_orphaned_vector_rows(self):
        """Deleting a source file and reconciling must drop its embeddings."""
        before = self.db.conn.execute("SELECT COUNT(*) FROM graph_vec").fetchone()[0]
        self.assertGreater(before, 0)
        victim = next(iter(PROJECT))
        os.remove(os.path.join(self.test_dir, victim))
        Reconciler(self.db, self.test_dir).reconcile(workers=1)
        orphan = self.db.conn.execute(
            "SELECT COUNT(*) FROM graph_vec WHERE node_id NOT IN "
            "(SELECT id FROM graph_nodes)"
        ).fetchone()[0]
        self.assertEqual(orphan, 0, "vector rows must not outlive their nodes")

    def test_prune_orphans_and_empty_rebuild_clear_table(self):
        # Simulate rows for nodes that no longer exist.
        with self.db.conn:
            self.db.conn.execute(
                "INSERT INTO graph_vec(node_id, embedding) VALUES (?, ?)",
                ("ghost:node", _vec_blob(HashEmbedder().embed_query("x"))),
            )
        pruned = prune_orphans(self.db.conn)
        self.assertGreaterEqual(pruned, 1)
        remaining = self.db.conn.execute("SELECT COUNT(*) FROM graph_vec").fetchone()[0]
        all_ids = {
            r[0] for r in self.db.conn.execute("SELECT id FROM graph_nodes")
        }
        self.assertEqual(remaining, len(all_ids & {
            r[0] for r in self.db.conn.execute("SELECT node_id FROM graph_vec")
        }))
        # An empty graph must also clear the vector table (the early return
        # used to leave stale rows behind forever).
        with self.db.conn:
            self.db.conn.execute("DELETE FROM graph_nodes WHERE kind != 'note'")
        stats = index_nodes(self.db.conn)
        left = self.db.conn.execute("SELECT COUNT(*) FROM graph_vec").fetchone()[0]
        self.assertEqual(stats["embedded"], 0)
        self.assertEqual(left, 0)


class _CountingEmbedder(HashEmbedder):
    """Spy embedder recording every embed() batch (R5 incremental checks)."""

    def __init__(self, dim: int = 64):
        super().__init__(dim=dim)
        self.batches: list = []

    def embed(self, texts):
        self.batches.append(list(texts))
        return super().embed(texts)

    @property
    def embedded_count(self):
        return sum(len(b) for b in self.batches)


@unittest.skipUnless(HAVE_VEC, "sqlite-vec extra not installed")
class IncrementalEmbedTests(unittest.TestCase):
    """R5: index_nodes is incremental, prunes vanished nodes, warns on cap."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)
        self.db = Database(os.path.join(self.test_dir, "test.db"))

    def _insert_node(self, node_id, label, body, updated_at):
        self.db.conn.execute(
            "INSERT INTO graph_nodes (id, path, kind, symbol, label, body, "
            "keywords, line_start, updated_at) VALUES (?, ?, 'function', ?, ?, ?, '', 1, ?)",
            (node_id, f"{node_id}.py", node_id, label, body, updated_at),
        )
        self.db.conn.commit()

    def test_second_call_reembeds_only_changed_node(self):
        for i in range(3):
            self._insert_node(f"n{i}", f"label{i}", f"body {i}", i)
        first = index_nodes(self.db.conn, cap=100)
        self.assertEqual(first["embedded"], 3)
        self.assertEqual(first["unchanged"], 0)
        self.assertFalse(first["truncated"])

        spy = _CountingEmbedder(dim=256)
        unchanged_call = index_nodes(self.db.conn, embedder=spy, cap=100)
        self.assertEqual(unchanged_call["embedded"], 0)
        self.assertEqual(unchanged_call["unchanged"], 3)
        self.assertEqual(spy.embedded_count, 0, "unchanged nodes must not be re-embedded")

        # Change exactly one node's content (and touch updated_at).
        self.db.conn.execute(
            "UPDATE graph_nodes SET body = 'brand new body', updated_at = 99 "
            "WHERE id = 'n1'"
        )
        self.db.conn.commit()
        spy2 = _CountingEmbedder(dim=256)
        second = index_nodes(self.db.conn, embedder=spy2, cap=100)
        self.assertEqual(second["embedded"], 1, "only the changed node re-embeds")
        self.assertEqual(second["unchanged"], 2)
        self.assertEqual(spy2.embedded_count, 1)
        vec_ids = {r[0] for r in self.db.conn.execute("SELECT node_id FROM graph_vec")}
        self.assertEqual(vec_ids, {"n0", "n1", "n2"})

    def test_vanished_nodes_are_pruned_from_vec_and_state(self):
        for i in range(3):
            self._insert_node(f"n{i}", f"label{i}", f"body {i}", i)
        index_nodes(self.db.conn)
        with self.db.conn:
            self.db.conn.execute("DELETE FROM graph_nodes WHERE id = 'n1'")
        stats = index_nodes(self.db.conn)
        self.assertGreaterEqual(stats["pruned"], 1)
        vec_ids = {r[0] for r in self.db.conn.execute("SELECT node_id FROM graph_vec")}
        state_ids = {r[0] for r in self.db.conn.execute("SELECT node_id FROM vector_index_state")}
        self.assertNotIn("n1", vec_ids)
        self.assertNotIn("n1", state_ids)

    def test_cap_sets_truncated_flag_and_warns_on_stderr(self):
        for i in range(5):
            self._insert_node(f"n{i}", f"label{i}", f"body {i}", i)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            stats = index_nodes(self.db.conn, cap=3)
        self.assertTrue(stats["truncated"])
        self.assertEqual(stats["embedded"], 3)
        self.assertEqual(stats["total_nodes"], 5)
        self.assertEqual(stats["cap"], 3)
        self.assertIn("truncated", err.getvalue())
        self.assertIn("3 of 5", err.getvalue())
        vec_count = self.db.conn.execute("SELECT COUNT(*) FROM graph_vec").fetchone()[0]
        self.assertEqual(vec_count, 3)

        # Under the cap the flag stays off and nothing is warned.
        err2 = io.StringIO()
        with contextlib.redirect_stderr(err2):
            stats2 = index_nodes(self.db.conn, cap=10)
        self.assertFalse(stats2["truncated"])
        self.assertEqual(stats2["total_nodes"], 5)
        self.assertEqual(err2.getvalue(), "")

    def test_cap_keeps_newest_nodes_by_updated_at(self):
        for i in range(4):
            self._insert_node(f"old{i}", f"label{i}", f"body {i}", i)
        self._insert_node("new", "fresh label", "newest body", 1000)
        stats = index_nodes(self.db.conn, cap=2)
        self.assertTrue(stats["truncated"])
        vec_ids = {r[0] for r in self.db.conn.execute("SELECT node_id FROM graph_vec")}
        self.assertEqual(vec_ids, {"new", "old3"}, "cap must keep the newest nodes")


if __name__ == "__main__":
    unittest.main()
