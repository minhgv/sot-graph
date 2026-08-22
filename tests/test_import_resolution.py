"""Regression tests for relative-import resolution and super() call edges.

Field-tested against a multi-package Odoo-style layout: sibling packages that
each define ``hooks.py`` used to collapse into one AMBIGUOUS pending edge set
because relative dots were stripped before the resolver ever saw them.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.db import Database
from sot_graph.modutil import resolve_relative
from sot_graph.reconciler import Reconciler


class TempProject(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sot_import_test_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel_path, content):
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)

    def make_db(self):
        db = Database(str(self.root / ".sot" / "sot.db"))
        self.addCleanup(db.close)
        return db


class ResolveRelativeUnitTests(unittest.TestCase):
    def test_package_init_level_one(self):
        self.assertEqual(resolve_relative(".hooks", "pkg_a", True), "pkg_a.hooks")

    def test_plain_module_level_one(self):
        self.assertEqual(resolve_relative(".helpers", "pkg_a.mod", False), "pkg_a.helpers")

    def test_package_init_level_two(self):
        self.assertEqual(resolve_relative("..pkg_b", "pkg_a.sub", True), "pkg_a.pkg_b")

    def test_from_dot_import_returns_package(self):
        self.assertEqual(resolve_relative(".", "pkg_a", True), "pkg_a")

    def test_absolute_import_untouched(self):
        self.assertEqual(resolve_relative("os.path", "pkg_a", True), "os.path")

    def test_none_and_empty(self):
        self.assertEqual(resolve_relative(None, "pkg_a", True), "")
        self.assertEqual(resolve_relative("", "pkg_a", True), "")

    def test_climb_past_root_is_empty(self):
        self.assertEqual(resolve_relative("..x", "pkg", True), "")


class RelativeImportResolutionTests(TempProject):
    def _reconcile(self, db):
        return Reconciler(db, str(self.root)).reconcile()

    def _dst_paths_for(self, db, src_path, relation):
        rows = db.conn.execute(
            "SELECT n2.path FROM graph_edges e "
            "JOIN graph_nodes n1 ON e.src = n1.id "
            "JOIN graph_nodes n2 ON e.dst = n2.id "
            "WHERE n1.path = ? AND e.relation = ?", (src_path, relation)
        ).fetchall()
        return [r[0] for r in rows]

    def test_sibling_packages_resolve_own_hooks(self):
        for pkg in ("pkg_a", "pkg_b"):
            self.write(f"{pkg}/hooks.py", "def setup_hook():\n    return 1\n")
            self.write(f"{pkg}/__init__.py",
                       "from .hooks import setup_hook\n")
        db = self.make_db()
        self._reconcile(db)

        for pkg in ("pkg_a", "pkg_b"):
            src = str(self.root / pkg / "__init__.py")
            dsts = self._dst_paths_for(db, src, "imports")
            self.assertEqual(
                dsts, [str(self.root / pkg / "hooks.py")],
                f"{pkg} must import its own hooks.py, got {dsts}")

        ambiguous = db.conn.execute(
            "SELECT COUNT(*) FROM pending_edges WHERE resolution_state = 'AMBIGUOUS'"
        ).fetchone()[0]
        self.assertEqual(ambiguous, 0)

    def test_from_dot_import_resolves_to_module_file(self):
        self.write("pkg_a/helpers.py",
                   "class Base:\n    def run(self):\n        return 1\n")
        self.write("pkg_a/__init__.py", "from . import helpers\n")
        db = self.make_db()
        self._reconcile(db)

        dsts = self._dst_paths_for(
            db, str(self.root / "pkg_a" / "__init__.py"), "imports")
        self.assertEqual(dsts, [str(self.root / "pkg_a" / "helpers.py")])

    def test_from_dot_import_binding_resolves_calls(self):
        self.write("pkg_a/helpers.py",
                   "def run_all():\n    return 2\n")
        self.write("pkg_a/__init__.py",
                   "from . import helpers\n\ndef trigger():\n    return helpers.run_all()\n")
        db = self.make_db()
        self._reconcile(db)

        dsts = self._dst_paths_for(
            db, str(self.root / "pkg_a" / "__init__.py"), "calls")
        self.assertIn(str(self.root / "pkg_a" / "helpers.py"), dsts)

    def test_super_call_does_not_self_loop(self):
        self.write("pkg_c/base.py",
                   "class Base:\n    def run(self):\n        return 1\n")
        self.write("pkg_c/child.py",
                   "from pkg_c.base import Base\n\n"
                   "class Child(Base):\n"
                   "    def run(self):\n"
                   "        return super().run() + 1\n")
        db = self.make_db()
        self._reconcile(db)

        self_loops = db.conn.execute(
            "SELECT COUNT(*) FROM graph_edges WHERE src = dst").fetchone()[0]
        self.assertEqual(self_loops, 0)

    def test_chained_same_name_call_does_not_self_loop(self):
        # Odoo idiom: user.sudo().write(...) inside write() targets another
        # record, not the enclosing method.
        self.write("pkg_c/records.py",
                   "class ResUsers:\n"
                   "    def write(self, vals):\n"
                   "        user = self.env.user\n"
                   "        user.sudo().write(vals)\n"
                   "        return True\n")
        db = self.make_db()
        self._reconcile(db)

        self_loops = db.conn.execute(
            "SELECT COUNT(*) FROM graph_edges WHERE src = dst").fetchone()[0]
        self.assertEqual(self_loops, 0)

    def test_self_recursion_edge_is_kept(self):
        self.write("pkg_c/loop.py",
                   "class ResUsers:\n"
                   "    def write(self, vals):\n"
                   "        return self.write(vals)\n")
        db = self.make_db()
        self._reconcile(db)

        kept = db.conn.execute(
            "SELECT COUNT(*) FROM graph_edges e "
            "JOIN graph_nodes n ON e.src = n.id "
            "WHERE n.symbol = 'ResUsers.write' AND e.src = e.dst"
        ).fetchone()[0]
        self.assertEqual(kept, 1)

    def test_absolute_import_still_resolves(self):
        self.write("pkg_a/helpers.py",
                   "class Base:\n    def run(self):\n        return 1\n")
        self.write("pkg_b/child.py",
                   "from pkg_a.helpers import Base\n\n"
                   "class Child(Base):\n"
                   "    def run(self):\n        return 2\n")
        db = self.make_db()
        self._reconcile(db)

        dsts = self._dst_paths_for(
            db, str(self.root / "pkg_b" / "child.py"), "extends")
        self.assertEqual(dsts, [str(self.root / "pkg_a" / "helpers.py")])

    def test_external_import_is_pruned(self):
        self.write("pkg_e/mod.py", "from odoo import api, models\n")
        db = self.make_db()
        self._reconcile(db)

        leftover = db.conn.execute(
            "SELECT COUNT(*) FROM pending_edges WHERE dst_symbol IN ('api', 'models')"
        ).fetchone()[0]
        edges = db.conn.execute(
            "SELECT COUNT(*) FROM graph_edges WHERE relation = 'imports'"
        ).fetchone()[0]
        self.assertEqual(leftover, 0)
        self.assertEqual(edges, 0)


if __name__ == "__main__":
    unittest.main()
