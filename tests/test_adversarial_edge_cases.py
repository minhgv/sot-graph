"""Comprehensive Adversarial Edge-Case Test Suite for SOT-Graph.

Tests tricky language AST extractors (Java sealed/permits, enum, record; TypeScript barrel/merging;
Python decorators; PHP traits), SQLite FTS5 query escaping, broken symlinks, Unicode filenames,
deep circular graphs, zero-edge modularity, and multi-thread concurrency.
"""
from __future__ import annotations

import concurrent.futures
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph._vendor.graphify.extract import extract_java
from sot_graph.analytics.graph import AnalyticsGraph
from sot_graph.db import Database
from sot_graph.mcp_service import McpService
from sot_graph.reconciler import Reconciler

class AdversarialLanguageExtractionTests(unittest.TestCase):
    """Test AST extraction on tricky syntax and language constructs."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="sot-adv-lang-")
        self.root = Path(self.temp_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_java_enum_and_record_with_implements(self) -> None:
        """Java enum and record implementing interfaces must extract definition nodes and implements edges."""
        java_code = """
package com.example;

import java.io.Serializable;

public enum PaymentStatus implements CodeProvider, Serializable {
    PENDING, SUCCESS, FAILED;

    public int getCode() { return 1; }
}

public record PaymentDto(String id, double amount) implements Serializable, Validatable {
    public boolean isValid() { return amount > 0; }
}
"""
        target = self.root / "Payment.java"
        target.write_text(java_code, encoding="utf-8")

        result = extract_java(target)
        node_names = [n.get("id") or n.get("label", "") for n in result["nodes"]]

        # Both PaymentStatus and PaymentDto must be present as definition nodes
        self.assertTrue(any("PaymentStatus" in name for name in node_names), "PaymentStatus enum node should be extracted")
        self.assertTrue(any("PaymentDto" in name for name in node_names), "PaymentDto record node should be extracted")
        # Check implements edges
        implements_edges = [
            (e["source"], e["target"])
            for e in result["edges"]
            if e["relation"] == "implements"
        ]
        self.assertIn(("PaymentStatus", "CodeProvider"), implements_edges)
        self.assertIn(("PaymentStatus", "Serializable"), implements_edges)
        self.assertIn(("PaymentDto", "Serializable"), implements_edges)
        self.assertIn(("PaymentDto", "Validatable"), implements_edges)

    def test_java_sealed_class_with_permits_clause(self) -> None:
        """Java sealed class with permits clause must not pollute implements relation."""
        java_code = """
package com.example;

public sealed class PaymentGateway implements IPayment, IAuditable permits MomoGateway, ZaloGateway {
    public void pay() {}
}

public final class MomoGateway extends PaymentGateway {}
public final class ZaloGateway extends PaymentGateway {}
"""
        target = self.root / "SealedGateway.java"
        target.write_text(java_code, encoding="utf-8")

        result = extract_java(target)
        implements_edges = [
            (e["source"], e["target"])
            for e in result["edges"]
            if e["relation"] == "implements"
        ]

        # Must implement IPayment and IAuditable
        self.assertIn(("PaymentGateway", "IPayment"), implements_edges)
        self.assertIn(("PaymentGateway", "IAuditable"), implements_edges)

        # Must NOT emit implements for MomoGateway or ZaloGateway (those are permitted subclasses)
        self.assertNotIn(("PaymentGateway", "MomoGateway"), implements_edges)
        self.assertNotIn(("PaymentGateway", "ZaloGateway"), implements_edges)

    def test_typescript_declaration_and_reexports(self) -> None:
        """TypeScript barrel re-exports and interface/function patterns."""
        db_path = self.root / ".sot" / "sot.db"
        src_dir = self.root / "src"
        src_dir.mkdir(parents=True, exist_ok=True)

        (src_dir / "types.ts").write_text(
            "export interface UserProfile { id: string; name: string; }\n"
            "export interface UserSettings { theme: string; }\n",
            encoding="utf-8",
        )
        (src_dir / "index.ts").write_text(
            "export * from './types';\n"
            "import { UserProfile } from './types';\n"
            "export function formatUser(u: UserProfile): string { return u.name; }\n",
            encoding="utf-8",
        )

        db = Database(str(db_path))
        reconciler = Reconciler(db, str(self.root))
        reconciler.reconcile()

        nodes = db.conn.execute("SELECT symbol, kind FROM graph_nodes WHERE kind != 'file'").fetchall()
        symbols = {row[0] for row in nodes}

        self.assertIn("UserProfile", symbols)
        self.assertIn("formatUser", symbols)
        db.close()

    def test_python_stacked_decorators_and_inner_imports(self) -> None:
        """Python functions with complex decorators and inner scoped imports."""
        db_path = self.root / ".sot" / "sot.db"
        src_dir = self.root / "app"
        src_dir.mkdir(parents=True, exist_ok=True)

        (src_dir / "service.py").write_text(
            "import functools\n\n"
            "class OrderService:\n"
            "    @property\n"
            "    def active(self) -> bool:\n"
            "        return True\n\n"
            "    @functools.lru_cache(maxsize=128)\n"
            "    def calculate_tax(self, amount: float) -> float:\n"
            "        import math\n"
            "        return math.ceil(amount * 0.1)\n",
            encoding="utf-8",
        )

        db = Database(str(db_path))
        reconciler = Reconciler(db, str(self.root))
        reconciler.reconcile()

        nodes = db.conn.execute("SELECT symbol, kind FROM graph_nodes WHERE kind != 'file'").fetchall()
        symbols = {row[0] for row in nodes}
        self.assertIn("OrderService", symbols)
        self.assertTrue(any("active" in s for s in symbols), "active property should be extracted")
        self.assertTrue(any("calculate_tax" in s for s in symbols), "calculate_tax method should be extracted")
        db.close()


class AdversarialFilesystemAndUnicodeTests(unittest.TestCase):
    """Test filesystem edge cases: Unicode/Vietnamese names, broken symlinks."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="sot-adv-fs-")
        self.root = Path(self.temp_dir)
        self.db_path = self.root / ".sot" / "sot.db"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_vietnamese_unicode_filenames_and_symbols(self) -> None:
        """Files and symbols with Vietnamese diacritics."""
        src_dir = self.root / "nghiệp_vụ"
        src_dir.mkdir(parents=True, exist_ok=True)

        file_path = src_dir / "thanh_toán_hóa_đơn.py"
        file_path.write_text(
            "def xử_lý_giao_dịch(mã_đơn: str) -> bool:\n"
            "    \"\"\"Xử lý thanh toán hóa đơn khách hàng.\"\"\"\n"
            "    return True\n",
            encoding="utf-8",
        )

        db = Database(str(self.db_path))
        reconciler = Reconciler(db, str(self.root))
        summary = reconciler.reconcile()

        self.assertEqual(summary.failed, 0)
        self.assertGreaterEqual(summary.scanned, 1)

        # FTS5 search with Vietnamese characters
        results = db.search_fts("giao_dịch")
        self.assertTrue(len(results) > 0, "FTS5 should match Vietnamese symbol")

        service = McpService(str(self.db_path), str(self.root))
        search_res = service.search("xử_lý_giao_dịch")
        self.assertTrue(len(search_res["results"]) > 0)
        self.assertIn("STRONG", search_res["results"][0]["verdict"])
        service.close()
        db.close()
    def test_broken_symlink_does_not_crash_reconciler(self) -> None:
        """Broken symlinks pointing to deleted targets must be skipped safely."""
        src_dir = self.root / "src"
        src_dir.mkdir(parents=True, exist_ok=True)

        valid_file = src_dir / "valid.py"
        valid_file.write_text("def valid_fn(): return 1\n", encoding="utf-8")

        broken_link = src_dir / "broken_link.py"
        try:
            os.symlink(str(self.root / "non_existent_target.py"), str(broken_link))
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks not supported on this platform/filesystem")

        db = Database(str(self.db_path))
        reconciler = Reconciler(db, str(self.root))
        summary = reconciler.reconcile()
        # Reconciler should complete successfully and index the valid file
        self.assertGreaterEqual(summary.scanned, 1)
        self.assertGreaterEqual(summary.updated, 1)
        nodes = db.conn.execute("SELECT symbol FROM graph_nodes WHERE kind != 'file'").fetchall()
        symbols = [r[0] for r in nodes]
        self.assertIn("valid_fn", symbols)
        db.close()


class AdversarialDatabaseAndFtsTests(unittest.TestCase):
    """Test FTS5 special character escaping, punctuation, and injection attempts."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="sot-adv-fts-")
        self.root = Path(self.temp_dir)
        self.db_path = self.root / ".sot" / "sot.db"
        self.db = Database(str(self.db_path))

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_fts5_queries_with_special_characters_do_not_throw(self) -> None:
        """FTS5 search should gracefully sanitize SQL/FTS syntax without exceptions."""
        service = McpService(str(self.db_path), str(self.root))

        dangerous_queries = [
            "__proto__",
            "$state_manager",
            "kebab-case-identifier",
            "\"unclosed quote",
            "AND OR NOT NEAR",
            "SELECT * FROM graph_nodes; --",
            "())(*&^%$#@!",
            "   ",
            ":::colon::scope",
            "a" * 300,
        ]

        for q in dangerous_queries:
            with self.subTest(query=q):
                try:
                    res_db = self.db.search_fts(q)
                    self.assertIsInstance(res_db, list)
                    if q.strip():
                        res_mcp = service.search(q)
                        self.assertIsInstance(res_mcp, dict)
                        self.assertIn("results", res_mcp)
                except Exception as exc:
                    self.fail(f"Search raised exception for query '{q}': {exc}")


class AdversarialGraphAnalyticsTests(unittest.TestCase):
    def test_zero_edges_modularity_and_diagnostics(self) -> None:
        """AnalyticsGraph with nodes but 0 edges must not raise ZeroDivisionError."""
        graph = AnalyticsGraph()
        graph.add_node("n1", label="Node1", path="a.py", kind="function")
        graph.add_node("n2", label="Node2", path="b.py", kind="function")
        graph.add_node("n3", label="Node3", path="c.py", kind="function")
        # Modularity with 0 edges
        mod = graph.calculate_modularity({"n1": 0, "n2": 1, "n3": 2})
        self.assertEqual(mod, 0.0)

        # Detect communities on zero edges
        comm_result = graph.detect_communities()
        self.assertEqual(len(comm_result.communities), 3)

    def test_circular_dependency_exploration(self) -> None:
        """Circular call chain (A -> B -> C -> A) in explore_node."""
        temp_dir = tempfile.mkdtemp(prefix="sot-adv-circ-")
        db_path = Path(temp_dir) / "test.db"
        db = Database(str(db_path))

        # Insert circular graph
        db.conn.execute("INSERT INTO graph_nodes (id, path, kind, symbol, label, body, updated_at) VALUES ('A', 'a.py', 'function', 'fnA', 'fnA', '', 0)")
        db.conn.execute("INSERT INTO graph_nodes (id, path, kind, symbol, label, body, updated_at) VALUES ('B', 'b.py', 'function', 'fnB', 'fnB', '', 0)")
        db.conn.execute("INSERT INTO graph_nodes (id, path, kind, symbol, label, body, updated_at) VALUES ('C', 'c.py', 'function', 'fnC', 'fnC', '', 0)")

        db.conn.execute("INSERT INTO graph_edges (path, src, dst, relation, line) VALUES ('a.py', 'A', 'B', 'calls', 10)")
        db.conn.execute("INSERT INTO graph_edges (path, src, dst, relation, line) VALUES ('b.py', 'B', 'C', 'calls', 20)")
        db.conn.execute("INSERT INTO graph_edges (path, src, dst, relation, line) VALUES ('c.py', 'C', 'A', 'calls', 30)")
        db.conn.commit()

        # Depth 5 exploration on circular graph
        explored = db.explore_node("A", depth=5)
        self.assertIsInstance(explored, list)
        self.assertTrue(len(explored) > 0)

        # Ensure no infinite loop occurred and result size is bounded
        self.assertLessEqual(len(explored), 10)

        db.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


class AdversarialConcurrencyTests(unittest.TestCase):
    """Test multi-threaded concurrent readers and writers on SQLite in WAL mode."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="sot-adv-conc-")
        self.root = Path(self.temp_dir)
        self.db_path = self.root / ".sot" / "sot.db"

        # Populate a few files
        src = self.root / "src"
        src.mkdir(parents=True, exist_ok=True)
        for i in range(10):
            (src / f"mod_{i}.py").write_text(
                f"def func_{i}():\n    return {i}\n",
                encoding="utf-8",
            )

        db = Database(str(self.db_path))
        reconciler = Reconciler(db, str(self.root))
        reconciler.reconcile()
        db.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_concurrent_search_and_reconcile_stress(self) -> None:
        """Concurrent readers and reconcilers must not throw database locked exceptions."""
        errors: list[Exception] = []

        def reader_task(worker_id: int) -> None:
            try:
                service = McpService(str(self.db_path), str(self.root))
                for _ in range(10):
                    res = service.search(f"func_{worker_id % 10}")
                    self.assertIsInstance(res, dict)
            except Exception as e:
                errors.append(e)

        def writer_task(worker_id: int) -> None:
            try:
                db = Database(str(self.db_path))
                reconciler = Reconciler(db, str(self.root))
                # Modify a file
                target = self.root / "src" / f"mod_{worker_id % 10}.py"
                target.write_text(f"def func_{worker_id % 10}():\n    return 'updated_{worker_id}'\n", encoding="utf-8")
                reconciler.reconcile()
                db.close()
            except Exception as e:
                errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = []
            for i in range(12):
                if i % 2 == 0:
                    futures.append(executor.submit(reader_task, i))
                else:
                    futures.append(executor.submit(writer_task, i))
            concurrent.futures.wait(futures)

        self.assertEqual(len(errors), 0, f"Concurrent workers encountered errors: {errors}")
