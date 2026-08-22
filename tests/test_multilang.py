import unittest
import os
import shutil
import tempfile
from pathlib import Path

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler
from sot_graph.extractor import parse_file_graph


class TestMultiLanguageExtraction(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, ".sot", "test.db")
        self.db = Database(self.db_path)
        self.reconciler = Reconciler(self.db, self.test_dir)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_typescript_extraction(self):
        ts_file = Path(self.test_dir) / "userService.ts"
        ts_file.write_text(
            "export interface UserProfile {\n"
            "    id: string;\n"
            "    email: string;\n"
            "}\n\n"
            "export class UserService {\n"
            "    async fetchUser(id: string): Promise<UserProfile> {\n"
            "        return { id, email: 'test@example.com' };\n"
            "    }\n"
            "}\n"
        )
        self.reconciler.reconcile_path(str(ts_file))
        res = self.db.search_fts("UserService fetchUser")
        self.assertGreaterEqual(len(res), 1)
        self.assertTrue(any("UserService" in r["label"] for r in res))

    def test_golang_extraction(self):
        go_file = Path(self.test_dir) / "server.go"
        go_file.write_text(
            "package main\n\n"
            "type Config struct {\n"
            "    Port int\n"
            "}\n\n"
            "func StartServer(cfg Config) error {\n"
            "    return nil\n"
            "}\n"
        )
        self.reconciler.reconcile_path(str(go_file))
        res = self.db.search_fts("StartServer Config")
        self.assertGreaterEqual(len(res), 1)

    def test_rust_extraction(self):
        rs_file = Path(self.test_dir) / "engine.rs"
        rs_file.write_text(
            "pub struct QueryEngine {\n"
            "    pub workers: usize,\n"
            "}\n\n"
            "pub fn execute_query(q: &str) -> bool {\n"
            "    true\n"
            "}\n"
        )
        self.reconciler.reconcile_path(str(rs_file))
        res = self.db.search_fts("QueryEngine execute_query")
        self.assertGreaterEqual(len(res), 1)


if __name__ == "__main__":
    unittest.main()
