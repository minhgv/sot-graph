"""Java extractor acceptance tests: inheritance edges on both parse paths.

The tree-sitter path is covered in test_treesitter.py; here we pin the
zero-dependency regex fallback and the end-to-end resolution of
extends/implements into the graph (implementations command feeds off it).
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from sot_graph._vendor.graphify.extract import extract_java
from sot_graph.db import Database
from sot_graph.reconciler import Reconciler

JAVA_FIXTURE = """package com.unitel.sso.services;

public interface MpsService {
    void sync();
}

public interface Combo extends MpsService {}

public class BaseService {}

public class MpsServiceImpl extends BaseService
        implements MpsService, Combo {}

public class GenericRepo extends com.unitel.BaseRepo<java.util.Map<String, String>> {}
"""

EXPECTED_INHERITANCE = {
    ("Combo", "MpsService", "extends"),
    ("MpsServiceImpl", "BaseService", "extends"),
    ("MpsServiceImpl", "MpsService", "implements"),
    ("MpsServiceImpl", "Combo", "implements"),
    ("GenericRepo", "BaseRepo", "extends"),
}


class TempProject(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sot_java_test_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel_path, content):
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)


class JavaRegexInheritanceTests(TempProject):
    def test_regex_fallback_emits_inheritance_edges(self):
        import sot_graph.ts_extract as ts_extract
        path = self.write("MpsServiceImpl.java", JAVA_FIXTURE)
        original = ts_extract.extract_ts
        ts_extract.extract_ts = lambda p, language: (_ for _ in ()).throw(
            ImportError("forced regex fallback"))
        try:
            result = extract_java(Path(path))
        finally:
            ts_extract.extract_ts = original
        found = {(e["source"], e["target"], e["relation"])
                 for e in result["edges"]
                 if e["relation"] in ("extends", "implements")}
        self.assertEqual(found, EXPECTED_INHERITANCE)

    def test_generics_debris_is_never_emitted_as_a_base(self):
        # Map<String, String> must not leak 'String' or '>>' targets.
        path = self.write("Debris.java", JAVA_FIXTURE)
        import sot_graph.ts_extract as ts_extract
        original = ts_extract.extract_ts
        ts_extract.extract_ts = lambda p, language: (_ for _ in ()).throw(
            ImportError("forced regex fallback"))
        try:
            result = extract_java(Path(path))
        finally:
            ts_extract.extract_ts = original
        targets = {e["target"] for e in result["edges"]
                   if e["relation"] in ("extends", "implements")}
        self.assertNotIn("String", targets)
        self.assertTrue(all(t.isidentifier() for t in targets))


class JavaInheritanceEndToEndTests(TempProject):
    def test_implementations_surface_java_relations(self):
        iface = self.write("MpsService.java", JAVA_FIXTURE)
        self.db = Database(str(self.root / ".sot" / "sot.db"))
        self.addCleanup(self.db.close)
        Reconciler(self.db, str(self.root)).reconcile(workers=1)

        iface_row = self.db.conn.execute(
            "SELECT id FROM graph_nodes WHERE symbol = 'MpsService' AND path = ?",
            (iface,)).fetchone()
        self.assertIsNotNone(iface_row, "interface node must exist")
        impl = self.db.inheritance_edges(iface_row[0], "MpsService")
        derived = {e["label"] for e in impl["derived"]}
        self.assertTrue(
            any("MpsServiceImpl" in label for label in derived),
            f"MpsServiceImpl must implement MpsService: {impl}")
        self.assertTrue(
            any("Combo" in label for label in derived),
            f"interface-extends must count as inheritance: {impl}")


if __name__ == "__main__":
    unittest.main()
