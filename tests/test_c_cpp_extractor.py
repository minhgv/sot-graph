"""
tests/test_c_cpp_extractor.py - Unit, AST, Inheritance, Call and Fallback tests for C and C++.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sot_graph._vendor.graphify.extract import extract_c, extract_cpp
from sot_graph.db import Database
from sot_graph.reconciler import Reconciler


class TestCCppExtractor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = str(self.root / ".sot" / "sot.db")
        self.db = Database(self.db_path)
        self.reconciler = Reconciler(self.db, str(self.root))

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_c_ast_extraction(self):
        c_code = """
#include <stdio.h>
#include "crypto.h"

struct HashContext {
    int state;
};

enum HashMode {
    MD5,
    SHA256
};

int compute_hash(int val) {
    return val * 42;
}

int* hash_buffer(void) {
    compute_hash(100);
    return NULL;
}
"""
        c_file = self.root / "crypto.c"
        c_file.write_text(c_code, encoding="utf-8")
        res = extract_c(c_file)

        node_ids = {n["id"] for n in res["nodes"]}
        self.assertIn("HashContext", node_ids)
        self.assertIn("HashMode", node_ids)
        self.assertIn("compute_hash", node_ids)
        self.assertIn("hash_buffer", node_ids)

        calls = [
            (e["source"], e["relation"], e["target"])
            for e in res["edges"]
            if e["relation"] == "calls"
        ]
        self.assertIn(("hash_buffer", "calls", "compute_hash"), calls)

        imports = [
            e["target"]
            for e in res["edges"]
            if e["relation"] == "imports"
        ]
        self.assertIn("stdio", imports)
        self.assertIn("crypto", imports)

    def test_cpp_ast_inheritance_and_calls(self):
        cpp_code = """
#include <iostream>
#include "engine.hpp"

namespace GameEngine {
    class BaseService {
    public:
        virtual void initialize() {}
    };

    class AudioService : public BaseService {
    public:
        void play() {
            initialize();
            AudioCodec::decode();
        }
        ~AudioService() {}
    };
}
"""
        cpp_file = self.root / "audio.cpp"
        cpp_file.write_text(cpp_code, encoding="utf-8")
        res = extract_cpp(cpp_file)

        node_ids = {n["id"] for n in res["nodes"]}
        self.assertIn("GameEngine", node_ids)
        self.assertIn("GameEngine.BaseService", node_ids)
        self.assertIn("GameEngine.AudioService", node_ids)
        self.assertIn("BaseService.initialize", node_ids)
        self.assertIn("AudioService.play", node_ids)
        self.assertIn("AudioService.~AudioService", node_ids)

        # Inheritance edge
        extends_edges = [
            (e["source"], e["relation"], e["target"])
            for e in res["edges"]
            if e["relation"] == "extends"
        ]
        self.assertIn(("GameEngine.AudioService", "extends", "BaseService"), extends_edges)

        # Call edge
        call_edges = [
            (e["source"], e["relation"], e["target"])
            for e in res["edges"]
            if e["relation"] == "calls"
        ]
        self.assertIn(("AudioService.play", "calls", "initialize"), call_edges)
        self.assertIn(("AudioService.play", "calls", "decode"), call_edges)

    def test_c_cpp_reconciliation_end_to_end(self):
        c_file = self.root / "math_util.c"
        c_file.write_text("""
int add(int a, int b) {
    return a + b;
}
""", encoding="utf-8")

        main_file = self.root / "main.cpp"
        main_file.write_text("""
#include "math_util.c"

int run_app() {
    return add(10, 20);
}
""", encoding="utf-8")

        self.reconciler.reconcile(workers=1)

        # Verify nodes exist in database
        nodes = self.db.conn.execute("SELECT symbol, kind, path FROM graph_nodes").fetchall()
        symbols = {n[0] for n in nodes}
        self.assertIn("add", symbols)
        self.assertIn("run_app", symbols)

        # Verify cross-file call edge resolved
        edges = self.db.conn.execute("""
            SELECT s.symbol, e.relation, t.symbol
            FROM graph_edges e
            JOIN graph_nodes s ON e.src = s.id
            JOIN graph_nodes t ON e.dst = t.id
            WHERE e.relation = 'calls'
        """).fetchall()
        self.assertIn(("run_app", "calls", "add"), edges)

    def test_c_cpp_fallback_without_treesitter(self):
        c_file = self.root / "fallback.c"
        c_file.write_text("""
struct Point { int x; int y; };
int compute_point(int a) { return a; }
""", encoding="utf-8")

        with patch("sot_graph.ts_extract.extract_ts", return_value={"nodes": [], "edges": [], "error": "mocked error"}):
            res = extract_c(c_file)
            node_ids = {n["id"] for n in res["nodes"]}
            self.assertIn("Point", node_ids)
            self.assertIn("compute_point", node_ids)


if __name__ == "__main__":
    unittest.main()
