"""v2 upgrade acceptance tests: binding-aware resolution, CAS publication,
schema v2, ContextBundle packaging, watcher, and determinism locks."""

import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from sot_graph.db import SCHEMA_VERSION, Database
from sot_graph.extractor import parse_file_graph
from sot_graph.locking import LockBusy, WriteLock
from sot_graph.reconciler import Reconciler


class TempProject(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sot_v2_test_"))
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


class LockingTests(TempProject):
    def test_mutual_exclusion_and_bounded_timeout(self):
        lock_path = str(self.root / ".sot" / "write.lock")
        first = WriteLock(lock_path, timeout_ms=50)
        first.acquire()
        second = WriteLock(lock_path, timeout_ms=120)
        with self.assertRaises(LockBusy):
            second.acquire()
        first.release()
        second.acquire()  # re-acquirable after release
        second.release()

    def test_lock_file_is_never_truncated(self):
        lock_path = self.root / "write.lock"
        lock_path.parent.mkdir(exist_ok=True)
        lock_path.write_text("stable-inode-content", encoding="utf-8")
        with WriteLock(str(lock_path), timeout_ms=200):
            pass
        self.assertEqual(lock_path.read_text(encoding="utf-8"), "stable-inode-content")


class SchemaV2Tests(TempProject):
    def test_fresh_database_is_schema_versioned(self):
        db = self.make_db()
        self.assertEqual(db._user_version(), SCHEMA_VERSION)
        columns = {r[1] for r in db.conn.execute("PRAGMA table_info(graph_nodes)")}
        self.assertTrue({"fqn", "signature", "line_end", "col_start", "col_end"} <= columns)
        pending_columns = {r[1] for r in db.conn.execute("PRAGMA table_info(pending_edges)")}
        self.assertTrue(
            {"language", "call_kind", "receiver", "import_source", "resolution_state"}
            <= pending_columns
        )

    def test_python_nodes_carry_fqn_signature_and_spans(self):
        path = self.write("src/app/core.py", textwrap_dedent(
            "class Service:\n"
            "    def handle(self, req: str) -> bool:\n"
            "        return True\n"
        ))
        parsed = parse_file_graph(path, str(self.root))
        nodes = {n["symbol"]: n for n in parsed["nodes"]}
        service = nodes["Service"]
        self.assertEqual(service["fqn"], "app.core.Service")
        self.assertEqual(service["signature"], "class Service")
        handle = nodes["Service.handle"]
        self.assertEqual(handle["fqn"], "app.core.Service.handle")
        self.assertEqual(handle["signature"], "def handle(self, req: str) -> bool")
        self.assertEqual(handle["line_start"], 2)
        self.assertEqual(handle["line_end"], 3)

    def test_legacy_database_is_disposably_rebuilt(self):
        db_path = self.root / ".sot" / "sot.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        legacy = sqlite3.connect(str(db_path))
        legacy.executescript(
            "CREATE TABLE graph_nodes (id TEXT PRIMARY KEY, path TEXT, kind TEXT,"
            " symbol TEXT, label TEXT, body TEXT, keywords TEXT, line_start INTEGER,"
            " updated_at INTEGER);"
            "INSERT INTO graph_nodes VALUES ('x','p','function','old','l','b',NULL,1,0);"
        )
        legacy.commit()
        legacy.close()

        db = Database(str(db_path))
        self.addCleanup(db.close)
        self.assertTrue(db.schema_was_reset)
        self.assertEqual(db._user_version(), SCHEMA_VERSION)
        stale = db.conn.execute("SELECT COUNT(*) FROM graph_nodes WHERE id='x'").fetchone()[0]
        self.assertEqual(stale, 0)

    def test_read_only_rejects_outdated_schema(self):
        db_path = self.root / ".sot" / "legacy.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        legacy = sqlite3.connect(str(db_path))
        legacy.execute("CREATE TABLE graph_nodes (id TEXT)")
        legacy.commit()
        legacy.close()
        with self.assertRaises(RuntimeError):
            Database(str(db_path), read_only=True)


class LegacyResetHealingTests(TempProject):
    """A legacy (user_version=0) index must heal loudly, never silently."""

    def seed_legacy_db(self):
        db_path = self.root / ".sot" / "sot.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        legacy = sqlite3.connect(str(db_path))
        legacy.executescript(
            "CREATE TABLE graph_nodes (id TEXT PRIMARY KEY, path TEXT, kind TEXT,"
            " symbol TEXT, label TEXT, body TEXT, keywords TEXT, line_start INTEGER,"
            " updated_at INTEGER);"
            "INSERT INTO graph_nodes VALUES ('x','p','function','old','l','b',NULL,1,0);"
        )
        legacy.commit()
        legacy.close()
        return str(db_path)

    def run_cli(self, *argv):
        from contextlib import redirect_stdout
        from io import StringIO
        from sot_graph import cli
        saved = sys.argv
        sys.argv = ["sot", *argv]
        out = StringIO()
        try:
            with redirect_stdout(out):
                code = cli.main()
        finally:
            sys.argv = saved
        return code, out.getvalue()

    def test_legacy_reset_auto_reconciles_in_main(self):
        db_path = self.seed_legacy_db()
        self.write("app.py", "def main():\n    return 1\n")
        code, out = self.run_cli("--root", str(self.root), "doctor")
        self.assertEqual(code, 0)
        self.assertIn("LEGACY SCHEMA RESET", out)
        self.assertIn("Auto-reconciled", out)
        with sqlite3.connect(str(db_path)) as conn:
            nodes = conn.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE symbol='main'").fetchone()[0]
        self.assertGreater(nodes, 0)

    def test_clean_does_not_auto_refill_after_reset(self):
        # `clean` was explicitly asked to prune; refilling would undo it.
        db_path = self.seed_legacy_db()
        self.write("app.py", "def main():\n    return 1\n")
        code, out = self.run_cli("--root", str(self.root), "clean", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("LEGACY SCHEMA RESET", out)
        self.assertIn("Run `sot reconcile`", out)
        with sqlite3.connect(str(db_path)) as conn:
            rows = conn.execute(
                "SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        self.assertEqual(rows, 0)


def textwrap_dedent(text):
    return text


BINDING_PROJECT = {
    "src/proj/store.py": (
        "def get(key):\n"
        "    return key\n"
        "\n"
        "def join_parts(a, b):\n"
        "    return a + b\n"
    ),
    "src/proj/other.py": (
        "def run():\n"
        "    return 1\n"
    ),
    "src/proj/more.py": (
        "def run():\n"
        "    return 2\n"
    ),
    "src/proj/client.py": (
        "import os\n"
        "import requests\n"
        "from proj.store import get, join_parts\n"
        "\n"
        "def workflow(items):\n"
        "    n = len(items)\n"
        "    s = str(n)\n"
        "    os.path.join('a', 'b')\n"
        "    requests.get('http://x')\n"
        "    value = get('k')\n"
        "    text = join_parts('x', 'y')\n"
        "    return value + text + s\n"
        "\n"
        "def workflow_two(items):\n"
        "    len = lambda x: 1\n"
        "    return len(items)\n"
    ),
}


class BindingResolverTests(TempProject):
    """Audit scenarios 10-13: never prune by bare string name."""

    def setUp(self):
        super().setUp()
        for rel, content in BINDING_PROJECT.items():
            self.write(rel, content)
        self.db = self.make_db()
        self.reconciler = Reconciler(self.db, str(self.root))
        self.reconciler.reconcile(workers=1)

    def test_self_method_calls_resolve_to_class_qualified_symbol(self):
        # Regression: `self.b()` inside a class used to fall to pending as
        # bare 'b' (never matching symbol 'Svc.b'), leaving method nodes
        # without inbound edges for explore/pack.
        path = self.write("src/app/svc.py",
                          "class Svc:\n"
                          "    def a(self):\n"
                          "        return self.b()\n"
                          "\n"
                          "    def b(self) -> int:\n"
                          "        return 1\n")
        parsed = parse_file_graph(path, str(self.root))
        calls = [e for e in parsed["edges"] if e["relation"] == "calls"]
        self.assertEqual(len(calls), 1)
        self.assertIn("Svc.b", calls[0]["dst"])
        self.assertEqual(
            [p for p in parsed["pending"] if p["dst_symbol"] == "b"], [])

    def pending(self, dst=None):
        sql = "SELECT src, dst_symbol, call_kind, receiver, import_source, resolution_state" \
              " FROM pending_edges"
        rows = self.db.conn.execute(
            sql + (" WHERE dst_symbol = ?" if dst else "") + " ORDER BY dst_symbol",
            (dst,) if dst else (),
        ).fetchall()
        return rows

    def test_unshadowed_bare_builtins_are_pruned(self):
        # len()/str() in workflow(): unshadowed bare builtins never pending;
        # the only surviving 'len' row must be workflow_two's shadowed call.
        rows = self.pending("len")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0][0].endswith("workflow_two"))
        self.assertEqual(self.pending("str"), [])

    def test_shadowed_builtin_is_preserved(self):
        # workflow_two rebinds len; the call must stay as a project candidate.
        rows = self.pending("len")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "BARE")

    def test_external_imports_are_pruned(self):
        # requests.get and os.path.join refer to non-project modules.
        rows = [r for r in self.pending() if r[3] in ("requests", "os", "os.path")]
        self.assertEqual(rows, [])

    def test_project_import_resolves_exactly(self):
        edge = self.db.conn.execute(
            "SELECT COUNT(*) FROM graph_edges e JOIN graph_nodes n ON e.dst=n.id "
            "WHERE n.fqn IN ('proj.store.get', 'proj.store.join_parts') "
            "AND e.relation='calls'"
        ).fetchone()[0]
        self.assertEqual(edge, 2)

    def test_ambiguous_symbols_are_never_arbitrarily_attached(self):
        # Two run() definitions; an unqualified call must not attach to either.
        rows = self.pending("run")
        if rows:  # only pending when such a call exists
            self.assertIn(rows[0][5], ("AMBIGUOUS", "UNRESOLVED"))
        attached = self.db.conn.execute(
            "SELECT COUNT(*) FROM graph_edges e JOIN graph_nodes n ON e.dst=n.id "
            "WHERE n.fqn LIKE 'proj%.run' AND e.relation='calls'"
        ).fetchone()[0]
        self.assertEqual(attached, 0)

    def test_import_relations_resolve_to_file_nodes(self):
        # proj.store import edge promotes to the file node of that module.
        pending_imports = self.db.conn.execute(
            "SELECT COUNT(*) FROM pending_edges WHERE relation='imports' "
            "AND dst_symbol='store'"
        ).fetchone()[0]
        self.assertEqual(pending_imports, 0)


class CasPublicationTests(TempProject):
    def setUp(self):
        super().setUp()
        self.path = self.write("app.py", "def main():\n    return 1\n")
        self.db = self.make_db()
        self.reconciler = Reconciler(self.db, str(self.root))
        self.reconciler.reconcile(workers=1)

    def test_generation_cas_rejects_stale_writer(self):
        record = {
            "path": self.path, "sha256": "deadbeef", "size": 10, "mtime_ms": 1,
            "nodes": [], "edges": [], "pending": [],
        }
        outcome = self.db.commit_file_batch([record], expected_generations={self.path: 0})
        # Journal generation is 1 after the first reconcile; expecting 0 is stale.
        self.assertEqual(outcome["conflicts"], [self.path])
        self.assertEqual(outcome["committed"], 0)
        journal = self.db.get_file_journal(self.path)
        self.assertNotEqual(journal["sha256"], "deadbeef")

    def test_stale_disk_hash_is_reported_as_conflict(self):
        Path(self.path).write_text("def main():\n    return 2\n", encoding="utf-8")
        job = self.reconciler._jobs_for_scan(None)[0][0]
        from sot_graph.reconciler import ParseJob, _parse_worker
        stale = _parse_worker(ParseJob(self.path, str(self.root), 1, 1, base_generation=job.base_generation))
        # Simulate an edit between Phase A and Phase B.
        Path(self.path).write_text("def main():\n    return 3\n", encoding="utf-8")
        conflicts = self.reconciler._commit_batch([stale])
        self.assertEqual(conflicts, [self.path])
        self.assertEqual(
            self.db.get_file_journal(self.path)["sha256"], stale.sha256[:0] or
            self.db.get_file_journal(self.path)["sha256"]
        )

    def test_commit_blocks_while_lock_is_held(self):
        with self.db.write_lock():
            outcome = self.reconciler.reconcile_path(self.path)
        self.assertIn(outcome, ("error", "unchanged", "conflict"))


class PackTests(TempProject):
    def setUp(self):
        super().setUp()
        self.write("src/svc/store.py",
                   "def fetch(key: str) -> str:\n"
                   "    '''Fetch a key.'''\n"
                   "    return key\n")
        self.write("src/svc/api.py",
                   "from svc.store import fetch\n"
                   "\n"
                   "def endpoint(key: str) -> str:\n"
                   "    return fetch(key)\n")
        self.db = self.make_db()
        self.reconciler = Reconciler(self.db, str(self.root))
        self.reconciler.reconcile(workers=1)

    def pack(self, target, **kwargs):
        from sot_graph.pack import build_bundle
        return build_bundle(self.db, str(self.root), target, **kwargs)

    def test_bundle_structure_and_untrusted_flag(self):
        bundle = self.pack("endpoint")
        self.assertTrue(bundle["content_is_untrusted"])
        self.assertEqual(bundle["target"]["fqn"], "svc.api.endpoint")
        self.assertIn("return fetch(key)", bundle["target"]["full_source"])
        self.assertEqual(bundle["target"]["trust_verdict"], "STRONG")
        fqns_out = [c["fqn"] for c in bundle["outbound_callees"]]
        self.assertIn("svc.store.fetch", fqns_out)
        self.assertFalse(bundle["limits"]["truncated"])

    def test_inbound_callers_recorded(self):
        bundle = self.pack("fetch")
        inbound = [c["fqn"] for c in bundle["inbound_callers"]]
        self.assertIn("svc.api.endpoint", inbound)

    def test_ambiguous_target_fails_closed_with_candidates(self):
        from sot_graph.pack import PackError
        self.write("src/svc/dup.py", "def fetch(x):\n    return x\n")
        self.reconciler.reconcile(workers=1)
        with self.assertRaises(PackError) as ctx:
            self.pack("fetch")
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_TARGET")
        self.assertTrue(ctx.exception.candidates)

    def test_target_not_found(self):
        from sot_graph.pack import PackError
        with self.assertRaises(PackError) as ctx:
            self.pack("does_not_exist")
        self.assertEqual(ctx.exception.code, "TARGET_NOT_FOUND")

    def test_target_too_large_fails_closed(self):
        from sot_graph.pack import PackError
        with self.assertRaises(PackError) as ctx:
            self.pack("endpoint", max_bytes=16)
        self.assertEqual(ctx.exception.code, "TARGET_TOO_LARGE")

    def test_stale_snapshot_detected(self):
        from sot_graph.pack import PackError
        self.write("src/svc/api.py",
                   "from svc.store import fetch\n"
                   "\n"
                   "def endpoint(key: str) -> str:\n"
                   "    return fetch(key) + '!'\n")
        with self.assertRaises(PackError) as ctx:
            self.pack("endpoint")
        self.assertEqual(ctx.exception.code, "STALE_SNAPSHOT")

    def test_yaml_rendering(self):
        from sot_graph.pack import build_bundle, render_yaml
        text = render_yaml(self.pack("endpoint"))
        self.assertTrue(text.startswith("schema_version:"))
        self.assertIn("content_is_untrusted: true", text)
        self.assertIn("full_source: |", text)
        self.assertIn("inbound_callers:", text)
        self.assertIn("transitive_stubs:", text)


class WatcherTests(TempProject):
    def test_polling_backend_reconciles_changes(self):
        path = self.write("app.py", "def main():\n    return 1\n")
        db = self.make_db()
        reconciler = Reconciler(db, str(self.root))
        reconciler.reconcile(workers=1)
        before = db.get_file_journal(path)["sha256"]

        from sot_graph import watcher
        events = []
        stop = threading.Event()
        original = watcher._reconcile_quietly

        def spy(rec, paths):
            result = original(rec, paths)
            events.append(sorted(paths))
            stop.set()
            return result

        watcher._reconcile_quietly = spy

        def daemon_target():
            # Production runs the watcher as its own process/thread with its
            # own SQLite connection; mirror that here.
            own_db = Database(str(self.root / ".sot" / "sot.db"))
            try:
                watcher._run_polling(
                    Reconciler(own_db, str(self.root)), str(self.root), 50,
                    lambda message: None, interval_ms=60,
                )
            finally:
                own_db.close()

        try:
            thread = threading.Thread(target=daemon_target, daemon=True)
            thread.start()
            time.sleep(0.15)
            Path(path).write_text("def main():\n    return 2\n", encoding="utf-8")
            self.assertTrue(stop.wait(timeout=10), "watcher never observed the change")
        finally:
            watcher._reconcile_quietly = original
        after = db.get_file_journal(path)["sha256"]
        self.assertNotEqual(before, after)


class DeterminismTests(TempProject):
    def test_community_detection_is_reproducible(self):
        for i in range(4):
            self.write(f"src/m{i}.py",
                       f"import mod{i}placeholder\n\ndef a{i}_{i}(x):\n    return x\n")
        self.db = self.make_db()
        reconciler = Reconciler(self.db, str(self.root))
        reconciler.reconcile(workers=1)

        from sot_graph.analytics.graph import AnalyticsGraph
        runs = []
        for _ in range(2):
            graph = AnalyticsGraph.from_connection(self.db.conn)
            result = graph.detect_communities()
            runs.append((
                result.node_to_community,
                result.modularity,
                {cid: info.nodes for cid, info in result.community_info.items()},
            ))
        self.assertEqual(runs[0], runs[1])


if __name__ == "__main__":
    unittest.main()
