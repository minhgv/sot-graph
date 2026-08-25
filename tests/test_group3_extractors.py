"""
tests/test_group3_extractors.py - Unit, AST & Reconciler tests for Group 3 (Vue/Svelte SFC, SQL DDL, GraphQL).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sot_graph._vendor.graphify.extract import extract_sfc, extract_sql, extract_graphql
from sot_graph.db import Database
from sot_graph.reconciler import Reconciler
from sot_graph.extractor import EXT_DISPATCH, LANGUAGE_MAP


class TestGroup3Extractors(unittest.TestCase):
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
        """Verify Group 3 extensions are registered in extractor dispatch."""
        self.assertIn(".vue", EXT_DISPATCH)
        self.assertIn(".svelte", EXT_DISPATCH)
        self.assertIn(".sql", EXT_DISPATCH)
        self.assertIn(".graphql", EXT_DISPATCH)
        self.assertIn(".gql", EXT_DISPATCH)
        self.assertEqual(LANGUAGE_MAP.get(".vue"), "vue")
        self.assertEqual(LANGUAGE_MAP.get(".svelte"), "svelte")
        self.assertEqual(LANGUAGE_MAP.get(".sql"), "sql")
        self.assertEqual(LANGUAGE_MAP.get(".graphql"), "graphql")

    def test_vue_sfc_ts_script_extraction(self):
        vue_code = """
<template>
  <button @click="handleClick">{{ label }}</button>
</template>

<script lang="ts">
import { defineComponent } from 'vue';

export default defineComponent({
  name: 'UserButton',
  methods: {
    handleClick() {
      console.log('clicked');
    }
  }
});
</script>
"""
        vue_file = self.root / "UserButton.vue"
        vue_file.write_text(vue_code, encoding="utf-8")
        res = extract_sfc(vue_file)

        node_ids = {n["id"] for n in res["nodes"]}
        self.assertIn("handleClick", node_ids)

    def test_svelte_sfc_script_extraction(self):
        svelte_code = """
<script>
  let count = 0;
  function increment() {
    count += 1;
  }
</script>

<button on:click={increment}>
  Clicks: {count}
</button>
"""
        svelte_file = self.root / "Counter.svelte"
        svelte_file.write_text(svelte_code, encoding="utf-8")
        res = extract_sfc(svelte_file)

        node_ids = {n["id"] for n in res["nodes"]}
        self.assertIn("increment", node_ids)

    def test_sql_ddl_extraction(self):
        sql_code = """
CREATE TABLE users (
    id INT PRIMARY KEY,
    name VARCHAR(255)
);

CREATE TABLE orders (
    id INT PRIMARY KEY,
    user_id INT
);
"""
        sql_file = self.root / "schema.sql"
        sql_file.write_text(sql_code, encoding="utf-8")
        res = extract_sql(sql_file)

        node_ids = {n["id"] for n in res["nodes"]}
        self.assertIn("users", node_ids)
        self.assertIn("orders", node_ids)

    def test_graphql_schema_extraction(self):
        gql_code = """
type User {
  id: ID!
  name: String!
}

type Query {
  getUser(id: ID!): User
}
"""
        gql_file = self.root / "schema.graphql"
        gql_file.write_text(gql_code, encoding="utf-8")
        res = extract_graphql(gql_file)

        node_ids = {n["id"] for n in res["nodes"]}
        self.assertIn("User", node_ids)
        self.assertIn("Query", node_ids)

    def test_reconciliation_end_to_end_group3(self):
        vue_file = self.root / "App.vue"
        vue_file.write_text("""
<script>
function onMounted() {}
</script>
""", encoding="utf-8")

        sql_file = self.root / "init.sql"
        sql_file.write_text("CREATE TABLE products (id INT);", encoding="utf-8")

        gql_file = self.root / "api.gql"
        gql_file.write_text("type Product { id: ID! }", encoding="utf-8")

        self.reconciler.reconcile(workers=1)

        nodes = self.db.conn.execute("SELECT symbol, kind, path FROM graph_nodes").fetchall()
        symbols = {n[0] for n in nodes}
        self.assertIn("onMounted", symbols)
        self.assertIn("products", symbols)
        self.assertIn("Product", symbols)


if __name__ == "__main__":
    unittest.main()
