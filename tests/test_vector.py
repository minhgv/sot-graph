"""Phase 4: optional hybrid retrieval — sqlite-vec + RRF fusion."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler

from sot_graph.vector import HashEmbedder, reciprocal_rank_fusion

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
        cos = lambda u, v: sum(x * y for x, y in zip(u, v))
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
        self.indexed = index_nodes(self.db.conn)
        if not self.indexed:
            self.skipTest("vec0 table unavailable")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_index_and_vector_search(self):
        self.assertGreaterEqual(self.indexed, 3)
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


if __name__ == "__main__":
    unittest.main()
