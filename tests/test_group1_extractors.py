"""
tests/test_group1_extractors.py - Unit, AST, Call, Inheritance & Fallback tests for Group 1 (Scala, Elixir, Lua).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sot_graph._vendor.graphify.extract import extract_scala, extract_elixir, extract_lua
from sot_graph.db import Database
from sot_graph.reconciler import Reconciler
from sot_graph.extractor import EXT_DISPATCH, LANGUAGE_MAP


class TestGroup1Extractors(unittest.TestCase):
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
        """Verify .scala, .ex, .lua are properly registered in extractor dispatch."""
        self.assertIn(".scala", EXT_DISPATCH)
        self.assertIn(".ex", EXT_DISPATCH)
        self.assertIn(".lua", EXT_DISPATCH)
        self.assertEqual(LANGUAGE_MAP.get(".scala"), "scala")
        self.assertEqual(LANGUAGE_MAP.get(".ex"), "elixir")
        self.assertEqual(LANGUAGE_MAP.get(".lua"), "lua")

    def test_scala_ast_and_inheritance(self):
        scala_code = """
package com.demo.service

import com.demo.core.MathLib

trait BaseCalculator {
  def compute(x: Int): Int
}

class FastCalculator extends BaseCalculator {
  def compute(x: Int): Int = {
    MathLib.calculate(x)
  }
}
"""
        scala_file = self.root / "Calculator.scala"
        scala_file.write_text(scala_code, encoding="utf-8")
        res = extract_scala(scala_file)

        node_ids = {n["id"] for n in res["nodes"]}
        self.assertIn("BaseCalculator", node_ids)
        self.assertIn("BaseCalculator.compute", node_ids)
        self.assertIn("FastCalculator", node_ids)
        self.assertIn("FastCalculator.compute", node_ids)

        # Inheritance edge
        extends_edges = [
            (e["source"], e["relation"], e["target"])
            for e in res["edges"]
            if e["relation"] == "extends"
        ]
        self.assertIn(("FastCalculator", "extends", "BaseCalculator"), extends_edges)

    def test_elixir_ast_modules_and_calls(self):
        elixir_code = """
defmodule Commerce.OrderService do
  alias Commerce.Inventory
  import Commerce.Utils

  def process_order(order_id, amount) do
    Inventory.check_stock(order_id)
  end

  defp log_audit(msg) do
    Logger.info(msg)
  end
end
"""
        elixir_file = self.root / "order_service.ex"
        elixir_file.write_text(elixir_code, encoding="utf-8")
        res = extract_elixir(elixir_file)

        node_ids = {n["id"] for n in res["nodes"]}
        self.assertIn("OrderService", node_ids)
        self.assertIn("OrderService.process_order", node_ids)
        self.assertIn("OrderService.log_audit", node_ids)

        calls = [
            (e["source"], e["relation"], e["target"])
            for e in res["edges"]
            if e["relation"] == "calls"
        ]
        self.assertIn(("OrderService.process_order", "calls", "check_stock"), calls)

    def test_lua_ast_functions_and_calls(self):
        lua_code = """
local MathUtil = {}

function MathUtil.double(x)
    return x * 2
end

function MathUtil:triple(x)
    return x * 3
end

local function compute(val)
    return MathUtil.double(val)
end
"""
        lua_file = self.root / "math_util.lua"
        lua_file.write_text(lua_code, encoding="utf-8")
        res = extract_lua(lua_file)

        node_ids = {n["id"] for n in res["nodes"]}
        self.assertIn("double", node_ids)
        self.assertIn("triple", node_ids)
        self.assertIn("compute", node_ids)

    def test_reconciliation_end_to_end_group1(self):
        scala_file = self.root / "Service.scala"
        scala_file.write_text("""
class AppService {
  def start(): Unit = {}
}
""", encoding="utf-8")

        elixir_file = self.root / "worker.ex"
        elixir_file.write_text("""
defmodule AppWorker do
  def run() do
    :ok
  end
end
""", encoding="utf-8")

        lua_file = self.root / "engine.lua"
        lua_file.write_text("""
local function start_engine()
    return true
end
""", encoding="utf-8")

        self.reconciler.reconcile(workers=1)

        nodes = self.db.conn.execute("SELECT symbol, kind, path FROM graph_nodes").fetchall()
        symbols = {n[0] for n in nodes}
        self.assertIn("AppService", symbols)
        self.assertIn("AppWorker", symbols)
        self.assertIn("start_engine", symbols)

    def test_fallbacks_without_treesitter(self):
        with patch("sot_graph.ts_extract.extract_ts", return_value={"nodes": [], "edges": [], "error": "mocked"}):
            scala_file = self.root / "fb.scala"
            scala_file.write_text("class FallbackScala {}", encoding="utf-8")
            res_sc = extract_scala(scala_file)
            self.assertIn("FallbackScala", {n["id"] for n in res_sc["nodes"]})

            ex_file = self.root / "fb.ex"
            ex_file.write_text("defmodule FallbackElixir do def compute() do end end", encoding="utf-8")
            res_ex = extract_elixir(ex_file)
            self.assertIn("FallbackElixir", {n["id"] for n in res_ex["nodes"]})

            lua_file = self.root / "fb.lua"
            lua_file.write_text("function fallback_lua() end", encoding="utf-8")
            res_lua = extract_lua(lua_file)
            self.assertIn("fallback_lua", {n["id"] for n in res_lua["nodes"]})


if __name__ == "__main__":
    unittest.main()
