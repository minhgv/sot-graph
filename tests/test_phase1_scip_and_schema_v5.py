"""
test_phase1_scip_and_schema_v5.py — Verification of Phase 1 SOT-Graph Integrations:
1. Schema v5 with Multi-Provider Evidence Storage & Non-Destructive v4->v5 Migration.
2. SCIP Importer Engine (protobuf & JSON formats, position encoding, evidence ingestion).
3. North-Star Response Envelope (CLI & MCP).
4. CLI `import-scip` command with JSON envelope and table outputs.
5. MCP Service providers discovery and metadata inclusion.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict

from sot_graph.cli import cmd_explore, cmd_import_scip, cmd_search, cmd_usages
from sot_graph.db import SCHEMA_VERSION, Database
from sot_graph.envelope import wrap_envelope
from sot_graph.export.scip import export_scip
from sot_graph.importer.scip import ScipImporter, parse_scip_symbol
from sot_graph.mcp_service import McpService
from sot_graph.reconciler import Reconciler


class Phase1SchemaV5AndScipTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="sot_phase1_test_")
        self.root = Path(self.tmpdir)
        self.db_path = str(self.root / ".sot" / "sot.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write(self, rel_path: str, content: str) -> str:
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)

    # -------------------------------------------------------------------------
    # 1. Schema v5 & Migration Tests
    # -------------------------------------------------------------------------

    def test_schema_tables_and_indices_present(self):
        """Verify that Database initializes current schema with provider tables."""
        db = Database(self.db_path)
        self.assertEqual(db._user_version(), SCHEMA_VERSION)

        tables = {
            r[0]
            for r in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertIn("provider_runs", tables)
        self.assertIn("provider_evidence", tables)
        self.assertIn("graph_nodes", tables)
        self.assertIn("graph_edges", tables)
        self.assertIn("file_journal", tables)
        self.assertIn("snapshots", tables)

        # Check provider_evidence columns
        evidence_cols = {
            r[1] for r in db.conn.execute("PRAGMA table_info(provider_evidence)").fetchall()
        }
        expected_cols = {
            "id", "run_id", "provider_name", "file_path", "symbol", "role",
            "line_start", "col_start", "line_end", "col_end", "syntax_kind",
            "documentation", "target_symbol", "confidence", "recorded_at"
        }
        self.assertTrue(expected_cols <= evidence_cols)
        db.close()

    def test_migration_from_v4_to_v5_preserves_notes_and_nodes(self):
        """Simulate a v4 database with user notes and data, then verify seamless v5 migration."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA user_version = 4")
        conn.execute("""
        CREATE TABLE graph_nodes (
            id TEXT PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL, symbol TEXT,
            fqn TEXT, signature TEXT, label TEXT NOT NULL, body TEXT NOT NULL, keywords TEXT,
            line_start INTEGER, line_end INTEGER, col_start INTEGER, col_end INTEGER,
            updated_at INTEGER NOT NULL
        );
        """)
        conn.execute("""
        CREATE TABLE file_journal (
            path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
            mtime_ms INTEGER NOT NULL, generation INTEGER DEFAULT 1, reconciled_at INTEGER NOT NULL
        );
        """)
        # Insert a user note
        conn.execute(
            "INSERT INTO graph_nodes (id, path, kind, symbol, label, body, keywords, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("note_123", "notes/arch.md", "note", "ArchitectureRule", "Architecture Rule", "Do not bypass gateway", "rule,arch", int(time.time()))
        )
        conn.commit()
        conn.close()

        # Open with Database -> triggers _migrate_database() to v5
        db = Database(self.db_path)
        self.assertEqual(db._user_version(), SCHEMA_VERSION)

        # Verify note is fully preserved
        node = db.get_node("note_123")
        self.assertIsNotNone(node)
        self.assertEqual(node["label"], "Architecture Rule")
        self.assertEqual(node["body"], "Do not bypass gateway")
        # Verify provider tables exist and have all canonical columns
        migrated_cols = {
            r[1] for r in db.conn.execute("PRAGMA table_info(provider_evidence)").fetchall()
        }
        canonical_cols = {
            "id", "run_id", "provider_name", "file_path", "path", "symbol",
            "src_symbol", "target_symbol", "dst_symbol", "role", "relation",
            "line_start", "line_end", "col_start", "col_end", "syntax_kind",
            "documentation", "confidence", "metadata_json", "recorded_at"
        }
        self.assertTrue(canonical_cols <= migrated_cols, f"Missing columns: {canonical_cols - migrated_cols}")

        # Verify insert_provider_evidence alias
        db.record_provider_run("test-provider", "1.0.0", run_id="run_v5_test")
        inserted = db.insert_provider_evidence("run_v5_test", [{
            "path": "test.py",
            "src_symbol": "foo",
            "relation": "defines",
            "syntax_kind": "function",
            "documentation": "test doc",
        }])
        self.assertEqual(inserted, 1)
        evidence = db.get_provider_evidence(run_id="run_v5_test")
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["syntax_kind"], "function")
        self.assertEqual(evidence[0]["documentation"], "test doc")
        db.close()

    # -------------------------------------------------------------------------
    # 2. SCIP Parser & Importer Tests
    # -------------------------------------------------------------------------

    def test_parse_scip_symbol_string_and_backtick_escaping(self):
        """Test SCIP symbol descriptor parsing into structured dictionary with backtick escaping."""
        # Method symbol
        sym = "scip-python python package 0.1.0 core/service/PaymentProcessor#process_charge()."
        parsed = parse_scip_symbol(sym)
        self.assertEqual(parsed["scheme"], "scip-python")
        self.assertEqual(parsed["manager"], "python")
        self.assertEqual(parsed["package"], "package")
        self.assertEqual(parsed["version"], "0.1.0")
        self.assertEqual(parsed["name"], "process_charge")
        self.assertEqual(parsed["kind"], "method")
        self.assertEqual(parsed["parent"], "PaymentProcessor")

        # Class symbol
        sym_class = "scip-typescript npm @org/pkg 1.2.3 src/OrderRepo#OrderRepository#"
        parsed_class = parse_scip_symbol(sym_class)
        self.assertEqual(parsed_class["name"], "OrderRepository")
        self.assertEqual(parsed_class["kind"], "class")

        # Backtick-escaped symbol with whitespace in descriptors and package
        sym_backtick = "scip-python python `my package` `1.0.0 beta` `bar baz`/`My Class`#`special method`()."
        parsed_bt = parse_scip_symbol(sym_backtick)
        self.assertEqual(parsed_bt["package"], "my package")
        self.assertEqual(parsed_bt["version"], "1.0.0 beta")
        self.assertEqual(parsed_bt["name"], "special method")
        self.assertEqual(parsed_bt["bare_name"], "special method")
        self.assertEqual(parsed_bt["parent"], "My Class")
        self.assertEqual(parsed_bt["kind"], "method")
        self.assertEqual(parsed_bt["fqn"], "bar baz.My Class.special method")

    def test_scip_position_encoding_utf16_and_spans(self):
        """Test UTF-16 position encoding coordinate translation for start and end columns."""
        from sot_graph.importer.scip import translate_scip_range
        source_text = "def 🚀_launch_mission(param: str):\n    return 'done'\n"
        # In UTF-16, emoji '🚀' takes 2 code units.
        # Range in UTF-16 code units: line 0, start_col 4, end_col 22
        range_utf16 = [0, 4, 22]
        spans_utf16 = translate_scip_range(range_utf16, encoding=2, source_text=source_text)
        self.assertEqual(spans_utf16["line_start"], 1)
        self.assertEqual(spans_utf16["line_end"], 1)
        self.assertEqual(spans_utf16["col_start"], 4)
        self.assertEqual(spans_utf16["col_end"], 21) # 1 character shorter because surrogate pair collapsed to 1 char
    def test_scip_json_importer_and_evidence_lifecycle(self):
        """Test importing SCIP JSON index and querying provider evidence."""
        self.write("src/core.py", "def helper():\n    return 42\n")
        self.write("src/main.py", "from src.core import helper\n\ndef run():\n    return helper()\n")

        db = Database(self.db_path)
        reconciler = Reconciler(db, str(self.root))
        reconciler.reconcile()

        scip_json_payload = {
            "documents": [
                {
                    "relative_path": "src/core.py",
                    "language": "python",
                    "occurrences": [
                        {
                            "range": [0, 4, 10], # line 0 (1-based line 1), col 4-10: 'helper'
                            "symbol": "scip-python python test 0.1.0 src/core/helper().",
                            "symbol_roles": 1, # ROLE_DEFINITION
                            "syntax_kind": "IdentifierFunction",
                        }
                    ],
                    "symbols": [
                        {
                            "symbol": "scip-python python test 0.1.0 src/core/helper().",
                            "documentation": ["Returns 42"],
                            "relationships": []
                        }
                    ]
                },
                {
                    "relative_path": "src/main.py",
                    "language": "python",
                    "occurrences": [
                        {
                            "range": [3, 11, 17], # line 3 (1-based line 4), col 11-17: 'helper'
                            "symbol": "scip-python python test 0.1.0 src/core/helper().",
                            "symbol_roles": 0, # ROLE_REFERENCE
                        }
                    ],
                    "symbols": []
                }
            ]
        }
        json_file = self.write(".sot/index.scip.json", json.dumps(scip_json_payload))

        importer = ScipImporter(db, project_root=str(self.root))
        receipt = importer.import_file(json_file, provider_name="scip-python-test", provider_version="0.1.0")

        self.assertEqual(receipt["documents_count"], 2)
        self.assertEqual(receipt["occurrences_count"], 2)
        self.assertEqual(receipt["evidence_recorded"], 2)

        # Query provider evidence
        evidence = db.get_provider_evidence(provider_name="scip-python-test")
        self.assertEqual(len(evidence), 2)
        roles = {e["role"] for e in evidence}
        self.assertEqual(roles, {"defines", "references"})

        # Verify symbol evidence lookup
        sym_evidence = db.get_symbol_evidence("helper")
        self.assertGreaterEqual(len(sym_evidence), 1)

        db.close()

    def test_scip_protobuf_roundtrip_export_and_import(self):
        """Test full end-to-end roundtrip: code -> AST reconciler -> SCIP export -> SCIP import -> evidence."""
        self.write("pkg/math.py", "def add(x, y):\n    return x + y\n")
        self.write("pkg/service.py", "from pkg.math import add\n\ndef compute(a, b):\n    return add(a, b)\n")

        db = Database(self.db_path)
        reconciler = Reconciler(db, str(self.root))
        reconciler.reconcile()

        scip_binary = str(self.root / ".sot" / "exported.scip")
        bytes_out = export_scip(db, str(self.root), scip_binary)
        self.assertGreater(bytes_out, 0)
        self.assertTrue(os.path.isfile(scip_binary))

        # Import the exported binary index back into the multi-provider ledger
        importer = ScipImporter(db, project_root=str(self.root))
        receipt = importer.import_file(scip_binary, provider_name="scip-compiler-ast")

        self.assertGreater(receipt["documents_count"], 0)
        self.assertGreater(receipt["evidence_recorded"], 0)

        runs = db.get_provider_runs()
        self.assertTrue(any(r["provider_name"] == "scip-compiler-ast" for r in runs))
        db.close()

    # -------------------------------------------------------------------------
    # 3. North-Star Response Envelope Tests
    # -------------------------------------------------------------------------

    def test_wrap_envelope_structure(self):
        """Verify standard envelope format contracts."""
        db = Database(self.db_path)
        data = {"query": "auth", "results": [{"label": "AuthService"}]}
        envelope = wrap_envelope(data, db=db, project_root=str(self.root))

        self.assertEqual(envelope["schema_version"], "2.0.0")
        self.assertIsInstance(envelope["snapshot_generation"], int)
        self.assertEqual(envelope["completeness"], "COMPLETE_WITHIN_INDEX_CAPABILITY")
        self.assertIsInstance(envelope["providers"], list)
        self.assertEqual(envelope["data"], data)
        db.close()

    # -------------------------------------------------------------------------
    # 4. CLI Commands & Envelope Formatting Tests
    # -------------------------------------------------------------------------

    def test_cli_import_scip_command(self):
        """Verify `sot import-scip` command execution with stdout and JSON envelope."""
        self.write("lib/util.py", "def greet(name):\n    return f'Hello, {name}'\n")

        db = Database(self.db_path)
        reconciler = Reconciler(db, str(self.root))
        reconciler.reconcile()

        scip_path = str(self.root / ".sot" / "cli_test.scip")
        export_scip(db, str(self.root), scip_path)

        # Test CLI invocation (text output)
        args = argparse.Namespace(
            index_file=scip_path,
            provider_name="scip-cli-provider",
            provider_version="1.0.0",
            json=False
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = cmd_import_scip(args, db, str(self.root))
        self.assertEqual(ret, 0)
        self.assertIn("SCIP index imported successfully", buf.getvalue())

        # Test CLI invocation (JSON envelope)
        args_json = argparse.Namespace(
            index_file=scip_path,
            provider_name="scip-cli-provider-json",
            provider_version="1.0.0",
            json=True
        )
        buf_json = io.StringIO()
        with redirect_stdout(buf_json):
            ret_json = cmd_import_scip(args_json, db, str(self.root))
        self.assertEqual(ret_json, 0)
        payload = json.loads(buf_json.getvalue())
        self.assertEqual(payload["schema_version"], "2.0.0")
        self.assertEqual(payload["data"]["provider_name"], "scip-cli-provider-json")
        db.close()

    def test_cli_search_and_explore_json_envelope(self):
        """Verify CLI search and explore with --json return standard envelope."""
        self.write("app/calc.py", "def calculate_discount(price: float) -> float:\n    return price * 0.9\n")

        db = Database(self.db_path)
        reconciler = Reconciler(db, str(self.root))
        reconciler.reconcile()

        # Search JSON
        args_search = argparse.Namespace(
            query="calculate_discount",
            limit=5,
            mode="bm25",
            hybrid=False,
            json=True,
            threshold=0.3
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = cmd_search(args_search, db, str(self.root))
        self.assertEqual(ret, 0)
        search_env = json.loads(buf.getvalue())
        self.assertEqual(search_env["schema_version"], "2.0.0")
        self.assertIn("results", search_env["data"])

        # Explore JSON
        args_explore = argparse.Namespace(
            target="calculate_discount",
            depth=1,
            show_all=True,
            json=True
        )
        buf_exp = io.StringIO()
        with redirect_stdout(buf_exp):
            ret_exp = cmd_explore(args_explore, db)
        self.assertEqual(ret_exp, 0)
        exp_env = json.loads(buf_exp.getvalue())
        self.assertEqual(exp_env["schema_version"], "2.0.0")
        self.assertIn("target", exp_env["data"])

        db.close()
    def test_cli_pack_json_envelope(self):
        """Verify `sot pack` with --json returns a valid North-Star response envelope."""
        from sot_graph.cli import cmd_pack
        self.write("pkg/calc.py", "def compute_total(price: float, tax: float) -> float:\n    return price + tax\n")

        db = Database(self.db_path)
        reconciler = Reconciler(db, str(self.root))
        reconciler.reconcile()

        args_pack = argparse.Namespace(
            target="compute_total",
            output=None,
            max_hops=2,
            max_nodes=10,
            max_bytes=10000,
            max_tokens=None,
            json=True,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = cmd_pack(args_pack, db, str(self.root))
        self.assertEqual(ret, 0)
        pack_env = json.loads(buf.getvalue())
        self.assertEqual(pack_env["schema_version"], "2.0.0")
        self.assertIn("target", pack_env["data"])
        self.assertIn("bundle_id", pack_env["data"])
        self.assertIsInstance(pack_env["providers"], list)
        db.close()

    # -------------------------------------------------------------------------
    # 5. MCP Service Providers Discovery Tests
    # -------------------------------------------------------------------------

    def test_mcp_service_includes_providers_in_responses(self):
        """Verify MCP Service responses contain providers metadata."""
        self.write("pkg/token.py", "def generate_token():\n    return 'secret'\n")

        db = Database(self.db_path)
        reconciler = Reconciler(db, str(self.root))
        reconciler.reconcile()

        # Record SCIP provider
        db.record_provider_run("scip-python-mcp", "0.5.0", run_id="mcp_run_1")

        # Initialize McpService
        mcp = McpService(self.db_path, str(self.root))

        # Test search
        res = mcp.search("generate_token")
        self.assertIn("providers", res)
        self.assertTrue(any(p["provider_name"] == "scip-python-mcp" for p in res["providers"]))

        # Test explore
        target_node = res["results"][0]["id"]
        exp_res = mcp.explore(target_node)
        self.assertIn("providers", exp_res)
        # Test empty search tokens return providers metadata
        empty_res = mcp.search("***")
        self.assertEqual(empty_res["returned"], 0)
        self.assertIn("providers", empty_res)
        self.assertTrue(len(empty_res["providers"]) >= 1)

        # Test repo_map
        repo_res = mcp.repo_map()
        self.assertIn("providers", repo_res)

        # Test notes
        notes_res = mcp.notes()
        self.assertIn("providers", notes_res)

        # Test graph_generation
        gen_res = mcp.graph_generation()
        self.assertIn("providers", gen_res)

        # Test node
        node_res = mcp.node(target_node)
        self.assertIn("providers", node_res)

        # Test verify_drift
        drift_res = mcp.verify_drift()
        self.assertIn("providers", drift_res)

        # Test stats
        stats_res = mcp.stats()
        self.assertIn("providers", stats_res)

        # Test get_architecture_bundle
        bundle_res = mcp.get_architecture_bundle()
        self.assertIn("providers", bundle_res)

        # Test solution_inventory
        sol_inv = mcp.solution_inventory()
        self.assertIn("providers", sol_inv)

        # Test solution_bundle
        sol_bun = mcp.solution_bundle()
        self.assertIn("providers", sol_bun)

        mcp.close()

    def test_scip_provider_parse_cache(self):
        """_parse_index caches by (realpath, mtime_ns, size): repeated calls
        within a provider run must not re-parse the index, and rewriting the
        file must invalidate the cache."""
        from unittest import mock

        from sot_graph.providers.scip import ScipProvider

        with tempfile.TemporaryDirectory() as tmp:
            index_path = os.path.join(tmp, "index.json")
            with open(index_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {"metadata": {"version": 1}, "documents": [{"path": "a.py"}]},
                    fh,
                )

            provider = ScipProvider(index_path=index_path)
            import sot_graph.providers.scip as scip_mod

            calls = {"n": 0}
            real_json_parse = scip_mod.parse_scip_json

            def wrapped(raw: str):
                calls["n"] += 1
                return real_json_parse(raw)

            with mock.patch.object(scip_mod, "parse_scip_json", side_effect=wrapped):
                meta1, docs1 = provider._parse_index(index_path)
                meta2, docs2 = provider._parse_index(index_path)
            self.assertEqual(calls["n"], 1, "second call must hit the cache")
            self.assertEqual(docs1, docs2)

            # Mutating the returned list must not poison the cache.
            docs2.append({"path": "injected.py"})
            meta3, docs3 = provider._parse_index(index_path)
            self.assertEqual(len(docs3), 1)

            # Rewrite the index (different size/mtime) — cache must miss.
            time.sleep(0.01)
            with open(index_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {"metadata": {"version": 2},
                     "documents": [{"path": "a.py"}, {"path": "b.py"}]},
                    fh,
                )
            with mock.patch.object(scip_mod, "parse_scip_json", side_effect=wrapped):
                meta4, docs4 = provider._parse_index(index_path)
            self.assertEqual(calls["n"], 2, "changed file must re-parse")
            self.assertEqual(len(docs4), 2)
            self.assertEqual(meta4["version"], 2)
            self.assertEqual(meta1["version"], 1)


if __name__ == "__main__":
    unittest.main()
