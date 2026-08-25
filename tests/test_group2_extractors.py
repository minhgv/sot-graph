"""
tests/test_group2_extractors.py - Unit, AST, Call & Fallback tests for Group 2 (Zig, Julia, R, Clojure).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sot_graph._vendor.graphify.extract import extract_zig, extract_julia, extract_r, extract_clojure
from sot_graph.db import Database
from sot_graph.reconciler import Reconciler
from sot_graph.extractor import EXT_DISPATCH, LANGUAGE_MAP


class TestGroup2Extractors(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = str(self.root / ".sot" / "sot.db")
        self.db = Database(self.db_path)
        self.reconciler = Reconciler(self.db, str(self.root))

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_registered_in_dispatch(self):
        """Verify Group 2 extensions are registered in extractor dispatch."""
        self.assertIn(".zig", EXT_DISPATCH)
        self.assertIn(".jl", EXT_DISPATCH)
        self.assertIn(".r", EXT_DISPATCH)
        self.assertIn(".clj", EXT_DISPATCH)
        self.assertEqual(LANGUAGE_MAP.get(".zig"), "zig")
        self.assertEqual(LANGUAGE_MAP.get(".jl"), "julia")
        self.assertEqual(LANGUAGE_MAP.get(".r"), "r")
        self.assertEqual(LANGUAGE_MAP.get(".clj"), "clojure")

    def test_zig_ast_extraction(self):
        zig_code = """
const std = @import("std");

pub const User = struct {
    id: u32,
};

pub fn calculateTotal(a: u32, b: u32) u32 {
    return a + b;
}
"""
        zig_file = self.root / "math.zig"
        zig_file.write_text(zig_code, encoding="utf-8")
        res = extract_zig(zig_file)

        node_ids = {n["id"] for n in res["nodes"]}
        self.assertIn("calculateTotal", node_ids)

    def test_julia_ast_extraction(self):
        jl_code = """
module MathModule

struct Calculator
    rate::Float64
end

function compute_tax(amount::Float64)
    return amount * 0.1
end

end
"""
        jl_file = self.root / "math.jl"
        jl_file.write_text(jl_code, encoding="utf-8")
        res = extract_julia(jl_file)

        node_ids = {n["id"] for n in res["nodes"]}
        self.assertIn("MathModule", node_ids)

    def test_r_ast_extraction(self):
        r_code = """
calculate_sum <- function(a, b) {
  return(a + b)
}

CustomerModel <- R6Class("CustomerModel")
"""
        r_file = self.root / "script.r"
        r_file.write_text(r_code, encoding="utf-8")
        res = extract_r(r_file)

        node_ids = {n["id"] for n in res["nodes"]}
        self.assertIn("calculate_sum", node_ids)
        self.assertIn("CustomerModel", node_ids)

    def test_clojure_ast_extraction(self):
        clj_code = """
(ns com.example.service)

(defprotocol Greeter
  (greet [this]))

(defn calculate-tax [amount rate]
  (* amount rate))
"""
        clj_file = self.root / "service.clj"
        clj_file.write_text(clj_code, encoding="utf-8")
        res = extract_clojure(clj_file)

        node_ids = {n["id"] for n in res["nodes"]}
        self.assertIn("com.example.service", node_ids)
        self.assertIn("Greeter", node_ids)
        self.assertIn("calculate-tax", node_ids)

    def test_reconciliation_end_to_end_group2(self):
        zig_file = self.root / "engine.zig"
        zig_file.write_text("pub fn start() void {}", encoding="utf-8")

        jl_file = self.root / "algo.jl"
        jl_file.write_text("module Algo end", encoding="utf-8")

        r_file = self.root / "analysis.r"
        r_file.write_text("run_analysis <- function() {}", encoding="utf-8")

        clj_file = self.root / "core.clj"
        clj_file.write_text("(defn run-task [] nil)", encoding="utf-8")

        self.reconciler.reconcile(workers=1)

        nodes = self.db.conn.execute("SELECT symbol, kind, path FROM graph_nodes").fetchall()
        symbols = {n[0] for n in nodes}
        self.assertIn("start", symbols)
        self.assertIn("Algo", symbols)
        self.assertIn("run_analysis", symbols)
        self.assertIn("run-task", symbols)


if __name__ == "__main__":
    unittest.main()
