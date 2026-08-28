"""Focused regressions for core graph, path, lock, and watcher safety."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from sot_graph.cli import default_db_path
from sot_graph.db import Database
from sot_graph.reconciler import Reconciler
from sot_graph.watcher import (
    _read_pid_metadata,
    _write_pid_metadata,
    start_daemon,
    status_daemon,
    stop_daemon,
)


class CoreSafetyFixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="sot-core-safety-")
        self.root = Path(self.temp_dir)
        self.db = Database(str(self.root / ".sot" / "sot.db"))

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_rehome_updates_hashed_ids_and_all_edge_endpoints(self) -> None:
        old_path = str(self.root / "old.py")
        new_path = str(self.root / "new.py")
        caller_path = str(self.root / "caller.py")
        old_namespace = hashlib.sha256(old_path.encode()).hexdigest()[:12]
        new_namespace = hashlib.sha256(new_path.encode()).hexdigest()[:12]
        old_file = f"file:{old_namespace}"
        old_symbol = f"sym:{old_namespace}:old_fn"
        new_file = f"file:{new_namespace}"
        new_symbol = f"sym:{new_namespace}:old_fn"

        self.db.commit_file(
            old_path,
            "old-hash",
            1,
            1,
            [
                {"id": old_file, "path": old_path, "kind": "file", "symbol": "old"},
                {
                    "id": old_symbol,
                    "path": old_path,
                    "kind": "function",
                    "symbol": "old_fn",
                    "label": "old_fn",
                },
            ],
            [
                {"path": old_path, "src": old_file, "dst": old_symbol, "relation": "contains"},
            ],
            [],
        )
        self.db.commit_file(
            caller_path,
            "caller-hash",
            1,
            1,
            [{"id": "file:caller", "path": caller_path, "kind": "file", "symbol": "caller"}],
            [{"path": caller_path, "src": "file:caller", "dst": old_symbol, "relation": "calls"}],
            [{"path": caller_path, "src": "file:caller", "dst_symbol": "old_fn", "relation": "calls"}],
        )

        self.assertTrue(self.db.rehome_file_atomically(old_path, new_path))
        node_ids = {row[0] for row in self.db.conn.execute("SELECT id FROM graph_nodes")}
        self.assertIn(new_file, node_ids)
        self.assertIn(new_symbol, node_ids)
        self.assertNotIn(old_file, node_ids)
        self.assertNotIn(old_symbol, node_ids)
        edges = list(self.db.conn.execute("SELECT path, src, dst FROM graph_edges"))
        self.assertTrue(any(edge[1] == "file:caller" and edge[2] == new_symbol for edge in edges))
        self.assertFalse(any(old_namespace in str(edge) for edge in edges))
        pending = list(self.db.conn.execute("SELECT path, src FROM pending_edges"))
        self.assertEqual(pending, [(caller_path, "file:caller")])
        self.assertEqual(self.db.integrity_check()["ok"], True)
    def test_rehome_relative_path_forms_do_not_rewrite_destination_again(self) -> None:
        old_path = "./old.py"
        new_path = "./old.py.bak"
        old_id = f"{old_path}#fn:service"

        self.db.commit_file(
            old_path,
            "old-hash",
            1,
            1,
            [
                {
                    "id": old_id,
                    "path": old_path,
                    "kind": "function",
                    "symbol": "service",
                    "label": f"source={old_path}",
                    "body": f"body={old_path}",
                },
            ],
            [],
            [],
        )

        self.assertTrue(self.db.rehome_file_atomically(old_path, new_path))
        row = self.db.conn.execute(
            "SELECT id, path, label, body FROM graph_nodes"
        ).fetchone()
        self.assertEqual(
            row,
            (
                f"{new_path}#fn:service",
                new_path,
                f"source={new_path}",
                f"body={new_path}",
            ),
        )

    def test_reconcile_purges_legacy_internal_symlink_alias_rows(self) -> None:
        target = self.root / "target.py"
        alias = self.root / "alias.py"
        target.write_text("def target():\n    return 1\n", encoding="utf-8")
        try:
            alias.symlink_to(target)
        except OSError:
            self.skipTest("symlinks are unavailable")

        reconciler = Reconciler(self.db, str(self.root))
        initial = reconciler.reconcile(workers=1)
        self.assertEqual(initial.updated, 1)

        legacy_id = "file:legacy-alias"
        self.db.commit_file(
            str(alias),
            "legacy-hash",
            1,
            1,
            [
                {
                    "id": legacy_id,
                    "path": str(alias),
                    "kind": "file",
                    "symbol": "alias",
                    "label": "alias",
                },
            ],
            [],
            [],
        )
        self.assertIn(str(alias), self.db.all_journal_paths())

        summary = reconciler.reconcile(workers=1)

        self.assertEqual(summary.deleted, 1)
        self.assertTrue(alias.is_symlink())
        self.assertTrue(target.is_file())
        self.assertNotIn(str(alias), self.db.all_journal_paths())
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE path = ?", (str(alias),)
            ).fetchone()[0],
            0,
        )
        self.assertGreater(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE path = ?", (str(target),)
            ).fetchone()[0],
            0,
        )


    def test_delete_path_removes_inbound_residue_and_requeues_once(self) -> None:
        target_path = str(self.root / "target.py")
        caller_path = str(self.root / "caller.py")
        target_id = "target-node"
        caller_id = "caller-node"
        self.db.commit_file(
            target_path,
            "target-hash",
            1,
            1,
            [{"id": target_id, "path": target_path, "kind": "function", "symbol": "target"}],
            [],
            [],
        )
        self.db.commit_file(
            caller_path,
            "caller-hash",
            1,
            1,
            [{"id": caller_id, "path": caller_path, "kind": "function", "symbol": "caller"}],
            [{"path": caller_path, "src": caller_id, "dst": target_id, "relation": "calls"}],
            [],
        )
        self.db.delete_path(target_path)
        self.db.delete_path(target_path)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0], 0)
        pending = list(self.db.conn.execute("SELECT path, src, dst_symbol FROM pending_edges"))
        self.assertEqual(pending, [(caller_path, caller_id, "target")])

    def test_reconciler_rejects_external_symlink_and_keeps_internal_file(self) -> None:
        external = Path(self.temp_dir).parent / "sot-core-safety-outside.py"
        external.write_text("def outside(): pass\n", encoding="utf-8")
        self.addCleanup(external.unlink, missing_ok=True)
        escaped = self.root / "escaped.py"
        internal = self.root / "internal.py"
        alias = self.root / "alias.py"
        internal.write_text("def inside(): pass\n", encoding="utf-8")
        try:
            escaped.symlink_to(external)
            alias.symlink_to(internal)
        except OSError:
            self.skipTest("symlinks are unavailable")
        reconciler = Reconciler(self.db, str(self.root))
        self.assertIsNone(reconciler._normalise_path(str(escaped)))
        self.assertEqual(reconciler._normalise_path(str(alias)), str(internal))
        self.assertEqual(reconciler.reconcile_path(str(escaped)), "error")
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0], 0)

    def test_full_reconcile_purges_indexed_external_symlink_without_reading_target(self) -> None:
        tracked = self.root / "tracked.py"
        tracked.write_text("def tracked():\n    return 1\n", encoding="utf-8")
        external = self.root.parent / f"{self.root.name}-outside.py"
        external.write_text("def outside():\n    return 2\n", encoding="utf-8")
        self.addCleanup(external.unlink, missing_ok=True)

        reconciler = Reconciler(self.db, str(self.root))
        initial = reconciler.reconcile(workers=1)
        self.assertEqual(initial.updated, 1)
        self.assertIn(str(tracked), self.db.all_journal_paths())

        tracked.unlink()
        try:
            tracked.symlink_to(external)
        except OSError:
            self.skipTest("symlinks are unavailable")

        real_open = open

        def guarded_open(file, *args, **kwargs):
            if (
                isinstance(file, (str, bytes, os.PathLike))
                and os.fspath(file) == os.fspath(external)
            ):
                raise AssertionError("external target was opened")
            return real_open(file, *args, **kwargs)

        with patch("builtins.open", side_effect=guarded_open):
            summary = reconciler.reconcile(workers=1)

        self.assertEqual(summary.deleted, 1)
        self.assertEqual(summary.failed, 0)
        for table in ("file_journal", "graph_nodes", "graph_edges", "pending_edges"):
            count = self.db.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE path = ?", (str(tracked),)
            ).fetchone()[0]
            self.assertEqual(count, 0, table)

    def test_explicit_reconcile_purges_external_symlink_but_rejects_path(self) -> None:
        tracked = self.root / "explicit.py"
        tracked.write_text("def explicit():\n    return 1\n", encoding="utf-8")
        external = self.root.parent / f"{self.root.name}-explicit-outside.py"
        external.write_text("def outside():\n    return 2\n", encoding="utf-8")
        self.addCleanup(external.unlink, missing_ok=True)

        reconciler = Reconciler(self.db, str(self.root))
        initial = reconciler.reconcile(workers=1)
        self.assertEqual(initial.updated, 1)
        self.assertIn(str(tracked), self.db.all_journal_paths())

        tracked.unlink()
        try:
            tracked.symlink_to(external)
        except OSError:
            self.skipTest("symlinks are unavailable")

        real_open = open

        def guarded_open(file, *args, **kwargs):
            if (
                isinstance(file, (str, bytes, os.PathLike))
                and os.fspath(file) == os.fspath(external)
            ):
                raise AssertionError("external target was opened")
            return real_open(file, *args, **kwargs)

        with patch("builtins.open", side_effect=guarded_open):
            result = reconciler.reconcile_path(str(tracked))

        self.assertEqual(result, "error")
        for table in ("file_journal", "graph_nodes", "graph_edges", "pending_edges"):
            count = self.db.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE path = ?", (str(tracked),)
            ).fetchone()[0]
            self.assertEqual(count, 0, table)


    def test_default_db_path_rejects_outside_symlink(self) -> None:
        probe_root = Path(tempfile.mkdtemp(prefix="sot-db-root-"))
        self.addCleanup(shutil.rmtree, probe_root, ignore_errors=True)
        sot_dir = probe_root / ".sot"
        outside_dir = Path(tempfile.mkdtemp(prefix="sot-db-outside-"))
        self.addCleanup(shutil.rmtree, outside_dir, ignore_errors=True)
        try:
            sot_dir.symlink_to(outside_dir, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks are unavailable")
        with self.assertRaises(ValueError):
            default_db_path(str(probe_root))

        sot_dir.unlink()
        sot_dir.mkdir()
        outside_db = outside_dir / "sot.db"
        outside_db.touch()
        (sot_dir / "sot.db").symlink_to(outside_db)
        with self.assertRaises(ValueError):
            default_db_path(str(probe_root))

    def test_watcher_does_not_signal_unrelated_pid(self) -> None:
        pid_path = self.root / ".sot" / "watch.pid"
        metadata = {
            "pid": os.getpid(),
            "scope": "single",
            "root": str(self.root),
            "identity": {"command": "python -m unrelated", "start": "foreign"},
        }
        _write_pid_metadata(pid_path, metadata)
        self.assertEqual(_read_pid_metadata(pid_path)["pid"], os.getpid())
        foreign_identity = {"command": "python -m unrelated", "start": "foreign"}
        with (
            patch("sot_graph.watcher.is_pid_alive", return_value=True),
            patch("sot_graph.watcher._process_identity", return_value=foreign_identity),
            patch("sot_graph.watcher._process_cwd", return_value=str(self.root)),
            patch("os.kill") as mock_kill,
        ):
            ok, message = stop_daemon(str(self.root))
            self.assertFalse(ok)
            self.assertIn("identity mismatch", message)
            mock_kill.assert_not_called()
        self.assertFalse(pid_path.exists())

    def test_concurrent_starts_publish_one_pid(self) -> None:
        class DummyProc:
            pid = 424242

        identity = {
            "command": (
                f"{sys.executable} -m sot_graph.cli watch "
                "--debounce-ms 200 --interval-ms 500 --backend auto"
            ),
            "start": "test-start",
        }
        results = []
        barrier = threading.Barrier(2)

        def launch() -> None:
            barrier.wait()
            results.append(start_daemon(str(self.root)))

        with (
            patch("subprocess.Popen", return_value=DummyProc()) as popen,
            patch("sot_graph.watcher.is_pid_alive", return_value=True),
            patch("sot_graph.watcher._process_identity", return_value=identity),
            patch("sot_graph.watcher._process_cwd", return_value=str(self.root)),
        ):
            threads = [threading.Thread(target=launch) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)
        self.assertEqual(sum(1 for ok, _ in results if ok), 1)
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(_read_pid_metadata(self.root / ".sot" / "watch.pid")["pid"], 424242)


if __name__ == "__main__":
    unittest.main()
