"""Tests for reconcile --force and code-file content previews.

File nodes previously carried no content preview for code files, so
full-text search could not find strings living inside source (e.g.
Vietnamese labels in PHP controllers). --force is the upgrade path that
re-extracts every file on an existing index without touching notes.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.db import Database
from sot_graph.extractor import parse_file_graph
from sot_graph.reconciler import Reconciler

PROJECT = {
    "app/pay.php": (
        "<?php\n"
        "class Pay {\n"
        "    public function label() {\n"
        "        return 'khách hàng';\n"
        "    }\n"
        "}\n"
    ),
    "app/util.py": "def helper():\n    return 'util value'\n",
}


class ForceReindexTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sot_force_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for rel, content in PROJECT.items():
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.db = Database(str(self.root / ".sot" / "sot.db"))
        self.addCleanup(self.db.close)
        self.reconciler = Reconciler(self.db, str(self.root))

    def test_code_file_node_carries_preview(self):
        parsed = parse_file_graph(str(self.root / "app" / "util.py"), str(self.root))
        file_node = next(n for n in parsed["nodes"] if n["kind"] == "file")
        self.assertIn("util value", file_node["body"])

    def test_preview_budget_env_override(self):
        big = self.root / "app" / "big.py"
        big.write_text("# pad\n" * 2000 + "needle_marker = 1\n", encoding="utf-8")
        try:
            os.environ["SOT_PREVIEW_BYTES"] = "32768"
            parsed = parse_file_graph(str(big), str(self.root))
            body = next(n for n in parsed["nodes"] if n["kind"] == "file")["body"]
            self.assertIn("needle_marker", body)
        finally:
            os.environ.pop("SOT_PREVIEW_BYTES", None)

        parsed = parse_file_graph(str(big), str(self.root))
        body = next(n for n in parsed["nodes"] if n["kind"] == "file")["body"]
        self.assertNotIn("needle_marker", body, "default budget must stay bounded")

    def test_force_reextracts_everything_and_is_idempotent(self):
        first = self.reconciler.reconcile(workers=1)
        self.assertGreater(first.updated, 0)

        steady = self.reconciler.reconcile(workers=1)
        self.assertEqual(steady.updated, 0, "second reconcile should be a no-op")

        forced = self.reconciler.reconcile(workers=1, force=True)
        self.assertEqual(forced.updated, first.scanned,
                         "force must re-extract every discovered file")

        again = self.reconciler.reconcile(workers=1)
        self.assertEqual(again.updated, 0, "force must leave a consistent journal")

    def test_preview_surfaces_in_search(self):
        self.reconciler.reconcile(workers=1)
        hits = self.db.search_fts("khách hàng", limit=10)
        self.assertTrue(
            any(h["kind"] == "file" and h["path"].endswith("pay.php") for h in hits),
            f"Vietnamese label in PHP source must be searchable: {hits}")

    def test_force_preserves_notes(self):
        self.reconciler.reconcile(workers=1)
        with self.db.conn:
            self.db.conn.execute(
                "INSERT INTO graph_nodes (id, path, kind, symbol, label, body, "
                "keywords, line_start, updated_at) VALUES "
                "('note:test1', '', 'note', NULL, 'smoke note', 'body text', "
                "'', 1, 0)")

        self.reconciler.reconcile(workers=1, force=True)

        kept = self.db.conn.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE id = 'note:test1'").fetchone()[0]
        self.assertEqual(kept, 1)


if __name__ == "__main__":
    unittest.main()
