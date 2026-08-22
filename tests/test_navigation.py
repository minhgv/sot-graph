"""Navigation table-stakes: usages / implementations / rename plan."""
import argparse
import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.cli import cmd_implementations, cmd_rename, cmd_usages
from sot_graph.db import Database
from sot_graph.mcp_service import McpService, McpServiceError
from sot_graph.reconciler import Reconciler

NAV_PROJECT = {
    "src/app/store.py": "def fetch(key):\n    return key\n",
    "src/app/run_a.py": "def run():\n    return 1\n",
    "src/app/run_b.py": "def run():\n    return 2\n",
    "src/app/base.py": (
        "class BaseStore:\n"
        "    def get(self, key):\n"
        "        return None\n"
    ),
    "src/app/sql.py": (
        "from app.base import BaseStore\n"
        "\n"
        "class SqlStore(BaseStore):\n"
        "    def load(self, key):\n"
        "        return key\n"
    ),
    "src/app/client.py": (
        "from app.store import fetch\n"
        "\n"
        "def handler():\n"
        "    run()\n"
        "    return fetch('k')\n"
    ),
}


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        for rel, content in NAV_PROJECT.items():
            target = Path(self.test_dir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.db = Database(os.path.join(self.test_dir, ".sot", "test.db"))
        self.reconciler = Reconciler(self.db, self.test_dir)
        self.reconciler.reconcile(workers=1)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _node_id(self, symbol: str) -> str:
        row = self.db.conn.execute(
            "SELECT id FROM graph_nodes WHERE symbol = ?", (symbol,)
        ).fetchone()
        self.assertIsNotNone(row, f"symbol {symbol} missing from graph")
        return row[0]

    def test_usages_lists_resolved_callers_grouped(self):
        data = self.db.usages(self._node_id("fetch"), "fetch")
        # Two legitimate usages: the import in client.py and the call in handler().
        self.assertEqual(len(data["callers"]), 2)
        by_kind = {c["kind"]: c for c in data["callers"]}
        self.assertIn("imports", [s["relation"] for s in by_kind["file"]["sites"]])
        self.assertEqual(by_kind["function"]["sites"], [{"relation": "calls", "line": 5}])
        self.assertIn("handler", by_kind["function"]["label"])
        self.assertEqual([r for r in data["risk"] if r["dst_symbol"] == "fetch"], [])

    def test_usages_reports_ambiguous_bare_name_risk(self):
        data = self.db.usages(self._node_id("run"), "run")
        self.assertEqual(data["callers"], [])
        self.assertTrue(any(r["dst_symbol"] == "run" and r["state"] == "AMBIGUOUS"
                            for r in data["risk"]))

    def test_implementations_resolves_both_directions(self):
        base = self.db.inheritance_edges(self._node_id("BaseStore"), "BaseStore")
        self.assertEqual(len(base["derived"]), 1)
        self.assertIn("SqlStore", base["derived"][0]["label"])
        self.assertEqual(base["derived"][0]["relation"], "extends")
        derived = self.db.inheritance_edges(self._node_id("SqlStore"), "SqlStore")
        self.assertEqual(len(derived["bases"]), 1)
        self.assertIn("BaseStore", derived["bases"][0]["label"])

    def _run_cmd(self, func, **kwargs) -> str:
        args = argparse.Namespace(target=kwargs.pop("target"), to=kwargs.pop("to", None), **kwargs)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = func(args, self.db)
        self.assertEqual(code, 0)
        return buf.getvalue()

    def test_cmd_usages_output(self):
        out = self._run_cmd(cmd_usages, target="fetch")
        self.assertIn("Usages of", out)
        self.assertIn("handler", out)
        self.assertIn("calls", out)

    def test_cmd_implementations_output(self):
        out = self._run_cmd(cmd_implementations, target="BaseStore")
        self.assertIn("SqlStore", out)
        self.assertIn("Derived types", out)

    def test_cmd_rename_plan_is_report_only(self):
        out = self._run_cmd(cmd_rename, target="fetch", to="lookup")
        self.assertIn("report-only", out)
        self.assertIn("store.py", out)   # definition
        self.assertIn("client.py", out)  # usage site

    def test_cmd_rename_flags_ambiguous_risk(self):
        out = self._run_cmd(cmd_rename, target="run")
        self.assertIn("AMBIGUOUS", out)


class McpNavigationTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        for rel, content in NAV_PROJECT.items():
            target = Path(self.test_dir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        db = Database(os.path.join(self.test_dir, ".sot", "test.db"))
        Reconciler(db, self.test_dir).reconcile(workers=1)
        db.close()
        self.service = McpService(
            os.path.join(self.test_dir, ".sot", "test.db"), self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_mcp_usages(self):
        res = self.service.usages("fetch")
        self.assertEqual(res["target"]["symbol"], "fetch")
        handler = [c for c in res["callers"] if c["kind"] == "function"]
        self.assertEqual(len(handler), 1)
        self.assertEqual(handler[0]["sites"], [{"relation": "calls", "line": 5}])

    def test_mcp_usages_not_found(self):
        with self.assertRaises(McpServiceError) as ctx:
            self.service.usages("does_not_exist_xyz")
        self.assertEqual(ctx.exception.code, "not_found")

    def test_mcp_implementations(self):
        res = self.service.implementations("BaseStore")
        self.assertEqual(len(res["derived"]), 1)
        self.assertIn("SqlStore", res["derived"][0]["label"])
        empty = self.service.implementations("fetch")
        self.assertEqual(empty["bases"], [])
        self.assertEqual(empty["derived"], [])


if __name__ == "__main__":
    unittest.main()
