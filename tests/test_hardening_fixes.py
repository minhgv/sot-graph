"""
Unit tests verifying comprehensive bug fixes and Phase 0 hardening.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sot_graph.analytics.graph import AnalyticsGraph
from sot_graph.db import Database, CleanPlan, SCHEMA_VERSION
from sot_graph.mcp_service import resolve_and_validate_output_path, McpServiceError
from sot_graph.pack import build_bundle, PackError
from sot_graph.ts_extract import extract_ts
from sot_graph.verifier import TrustVerifier, RelevanceType


class HardeningFixesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = str(self.root / ".sot" / "sot.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_db_preserve_notes_on_schema_reset_and_clean(self):
        # 1. Insert a note node and normal code node
        with self.db.write_lock():
            with self.db.conn:
                self.db.conn.execute(
                    "INSERT INTO graph_nodes (id, path, kind, label, body, updated_at) "
                    "VALUES ('note:123', 'docs/notes.md', 'note', 'My Note', 'Note Body', 100)"
                )
                self.db.conn.execute(
                    "INSERT INTO graph_nodes (id, path, kind, label, body, updated_at) "
                    "VALUES ('code:1', 'src/app.py', 'function', 'app_func', 'def app_func(): pass', 100)"
                )

        # Apply clean with reset=True and include_notes=False
        plan = CleanPlan(mode="reset", paths=(), counts={}, errors=(), include_notes=False)
        self.db.apply_clean(plan)

        rows = self.db.conn.execute("SELECT id, kind FROM graph_nodes").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "note:123")

    def test_db_clean_deletes_auxiliary_tables(self):
        with self.db.conn:
            self.db.conn.execute(
                "INSERT INTO ui_navigation (id, route_path, component_name, file_path) "
                "VALUES ('nav1', '/dashboard', 'Dashboard', 'src/Dash.tsx')"
            )
            self.db.conn.execute(
                "INSERT INTO ui_decision_nodes (id, component_name, handler_symbol, condition_expr, branch_type, ui_effect, file_path) "
                "VALUES ('dec1', 'Dashboard', 'handleClick', 'isAdmin', 'IF', 'SHOW_MODAL', 'src/Dash.tsx')"
            )
            self.db.conn.execute(
                "INSERT INTO api_cross_bindings (id, fe_caller_symbol, http_method, normalized_uri) "
                "VALUES ('api1', 'fetchUsers', 'GET', '/api/users')"
            )
            self.db.conn.execute(
                "INSERT INTO be_execution_steps (id, service_symbol, step_order, step_name, code_statement, step_description, step_category, file_path) "
                "VALUES ('step1', 'UserService', 1, 'validate', 'assert user', 'validate user', 'VALIDATION', 'src/user.py')"
            )
            self.db.conn.execute(
                "INSERT INTO related_features_index (id, module_name, feature_name, feature_category, risk_level, short_description, key_files) "
                "VALUES ('rel1', 'Auth', 'Login', 'CORE', 'HIGH', 'User login', 'src/auth.py')"
            )
            self.db.conn.execute(
                "INSERT INTO graph_communities (community_id, label, nodes_json, created_at) "
                "VALUES (1, 'Auth Cluster', '[]', 100)"
            )

        plan = CleanPlan(mode="reset", paths=(), counts={}, errors=(), include_notes=True)
        self.db.apply_clean(plan)

        for table in [
            "ui_navigation",
            "ui_decision_nodes",
            "api_cross_bindings",
            "be_execution_steps",
            "related_features_index",
            "graph_communities",
        ]:
            count = self.db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            self.assertEqual(count, 0, f"Table {table} was not cleaned during reset")

    def test_db_mutation_gateways(self):
        res1 = self.db.transactional_mutation(lambda db: db.conn.execute("SELECT 42").fetchone()[0])
        self.assertEqual(res1, 42)
        res2 = self.db.maintenance_mutation(lambda db: 99)
        self.assertEqual(res2, 99)

    def test_ts_extract_multiple_declarators(self):
        # Test const / let (lexical_declaration)
        js_file = self.root / "test_decl.js"
        js_file.write_text("const a = () => { return 1; }, b = () => { return 2; };\n", encoding="utf-8")
        parsed = extract_ts(js_file, "javascript")
        node_ids = {n["id"] for n in parsed["nodes"]}
        self.assertIn("a", node_ids)
        self.assertIn("b", node_ids)

        # Test var (variable_declaration)
        var_file = self.root / "test_var_decl.js"
        var_file.write_text("var x = () => { return 10; }, y = () => { return 20; };\n", encoding="utf-8")
        parsed_var = extract_ts(var_file, "javascript")
        var_node_ids = {n["id"] for n in parsed_var["nodes"]}
        self.assertIn("x", var_node_ids)
        self.assertIn("y", var_node_ids)

    def test_ts_extract_variable_initializer_calls(self):
        # Test non-function variable declarators extracting calls
        js_file = self.root / "test_calls.js"
        js_file.write_text(
            "const a = foo();\n"
            "let b = bar();\n"
            "var c = baz(qux());\n",
            encoding="utf-8",
        )
        parsed = extract_ts(js_file, "javascript")
        called_targets = {e["target"] for e in parsed["edges"] if e["relation"] == "calls"}
        self.assertIn("foo", called_targets)
        self.assertIn("bar", called_targets)
        self.assertIn("baz", called_targets)
        self.assertIn("qux", called_targets)

    def test_mcp_security_path_confinement(self):
        valid = resolve_and_validate_output_path(str(self.root), "out.md")
        self.assertTrue(valid.startswith(str(self.root.resolve())))

        # Path traversal attack
        with self.assertRaises(McpServiceError) as ctx:
            resolve_and_validate_output_path(str(self.root), "../../etc/passwd")
        self.assertEqual(ctx.exception.code, "path_traversal")

    def test_pack_token_budget_cap(self):
        import hashlib
        from sot_graph.pack import render_yaml
        from sot_graph.tokenizer import estimate_tokens

        src_mod = self.root / "src" / "mod.py"
        src_mod.parent.mkdir(parents=True, exist_ok=True)
        content = "def test_fn():\n    # A function with some documentation and code\n    return 42\n"
        src_mod.write_bytes(content.encode("utf-8"))
        st = os.stat(src_mod)
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        abs_path = str(src_mod)
        # Create small graph with real file and real SHA
        with self.db.write_lock():
            with self.db.conn:
                self.db.conn.execute(
                    "INSERT INTO graph_nodes (id, path, kind, symbol, fqn, label, body, updated_at, line_start, line_end) "
                    "VALUES ('node1', ?, 'function', 'test_fn', 'mod.test_fn', 'def test_fn()', ?, 100, 1, 3)",
                    (abs_path, content),
                )
                self.db.conn.execute(
                    "INSERT INTO file_journal (path, sha256, size, mtime_ms, generation, reconciled_at) "
                    "VALUES (?, ?, ?, ?, 1, 100)",
                    (abs_path, sha, int(st.st_size), int(st.st_mtime * 1000)),
                )
        # Extremely low token budget should trigger error
        with self.assertRaises(PackError):
            build_bundle(self.db, str(self.root), "test_fn", max_tokens=10)

        # Valid token budget should produce bundle strictly within max_tokens
        bundle = build_bundle(self.db, str(self.root), "test_fn", max_tokens=300)
        rendered = render_yaml(bundle)
        tok_count = estimate_tokens(rendered)
        self.assertLessEqual(tok_count, 300)
        self.assertEqual(bundle["limits"]["tokens_estimate"], tok_count)

    def test_pack_token_budget_convergence_tight_and_small(self):
        import hashlib
        from sot_graph.pack import render_yaml
        from sot_graph.tokenizer import estimate_tokens

        src_mod = self.root / "src" / "large_mod.py"
        src_mod.parent.mkdir(parents=True, exist_ok=True)
        # Long content that will trigger several truncation loops
        lines = [f"    # Line comment {i} to increase size of source" for i in range(100)]
        content = "def large_fn():\n" + "\n".join(lines) + "\n    return 0\n"
        src_mod.write_bytes(content.encode("utf-8"))
        st = os.stat(src_mod)
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        abs_path = str(src_mod)

        with self.db.write_lock():
            with self.db.conn:
                self.db.conn.execute(
                    "INSERT INTO graph_nodes (id, path, kind, symbol, fqn, label, body, updated_at, line_start, line_end) "
                    "VALUES ('node_large', ?, 'function', 'large_fn', 'large_mod.large_fn', 'def large_fn()', ?, 100, 1, 102)",
                    (abs_path, content),
                )
                self.db.conn.execute(
                    "INSERT INTO file_journal (path, sha256, size, mtime_ms, generation, reconciled_at) "
                    "VALUES (?, ?, ?, ?, 1, 100)",
                    (abs_path, sha, int(st.st_size), int(st.st_mtime * 1000)),
                )

        # Tight token budget (e.g. 350 tokens for a ~1500 token source) should converge without infinite loop
        bundle = build_bundle(self.db, str(self.root), "large_fn", max_tokens=350)
        rendered = render_yaml(bundle)
        tok_count = estimate_tokens(rendered)
        self.assertLessEqual(tok_count, 350)
        self.assertTrue(bundle["limits"]["truncated"])

        # Extremely small budget (where even metadata alone exceeds budget, e.g. 50 tokens) should raise PackError
        with self.assertRaises(PackError) as ctx:
            build_bundle(self.db, str(self.root), "large_fn", max_tokens=50)
        self.assertEqual(ctx.exception.code, "BUDGET_TOO_SMALL")

    def test_modularity_calculation(self):
        graph = AnalyticsGraph()
        # Create 2 disjoint triangles
        # Triangle 1: n1, n2, n3
        graph.add_node("n1", "src/n1.py", "func", "n1")
        graph.add_node("n2", "src/n2.py", "func", "n2")
        graph.add_node("n3", "src/n3.py", "func", "n3")
        graph.add_edge("n1", "n2", "calls")
        graph.add_edge("n2", "n3", "calls")
        graph.add_edge("n3", "n1", "calls")

        # Triangle 2: n4, n5, n6
        graph.add_node("n4", "src/n4.py", "func", "n4")
        graph.add_node("n5", "src/n5.py", "func", "n5")
        graph.add_node("n6", "src/n6.py", "func", "n6")
        graph.add_edge("n4", "n5", "calls")
        graph.add_edge("n5", "n6", "calls")
        graph.add_edge("n6", "n4", "calls")

        node_to_comm = {
            "n1": 0, "n2": 0, "n3": 0,
            "n4": 1, "n5": 1, "n6": 1
        }
        q = graph.calculate_modularity(node_to_comm)
        # For 2 disconnected equal components, Q should be 0.5
        self.assertAlmostEqual(q, 0.5, places=2)

    def test_cli_handles_lock_busy_and_runtime_error(self):
        from unittest.mock import patch
        from sot_graph.cli import main as cli_main
        from sot_graph.locking import LockBusy

        # Test LockBusy during Database creation
        with patch("sot_graph.cli.Database", side_effect=LockBusy("Lock file held")):
            rc = cli_main(["--db", str(self.db_path), "search", "foo"])
            self.assertEqual(rc, 1)

        # Test LockBusy during command dispatch
        with patch("sot_graph.cli.cmd_search", side_effect=LockBusy("Lock file held")):
            rc = cli_main(["--db", str(self.db_path), "search", "foo"])
            self.assertEqual(rc, 1)

        # Test RuntimeError during command dispatch
        with patch("sot_graph.cli.cmd_search", side_effect=RuntimeError("Generic runtime failure")):
            rc = cli_main(["--db", str(self.db_path), "search", "foo"])
            self.assertEqual(rc, 1)

    def test_db_migration_backup_error_handling(self):
        from unittest.mock import patch
        # Force backup connection to fail and verify clean RuntimeError without handle leak
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("disk full")):
            with patch.object(self.db, "_user_version", return_value=0):
                with patch.object(self.db, "_schema_objects_present", return_value=True):
                    with self.assertRaises(RuntimeError) as ctx:
                        self.db._migrate_database()
                    self.assertIn("Database backup failed before migration", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
