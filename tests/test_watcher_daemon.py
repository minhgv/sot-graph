"""
Tests for sot_graph.watcher daemon, multi-project discovery, and lifecycle management.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sot_graph.db import Database
from sot_graph.locking import LockBusy
from sot_graph.reconciler import Reconciler
from sot_graph.watcher import (
    _process_identity,
    _reconcile_quietly,
    discover_sot_projects,
    is_pid_alive,
    pick_backend,
    start_daemon,
    status_daemon,
    stop_daemon,
)

class TestWatcherDaemon(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name).resolve()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_pick_backend_fallback(self):
        backend = pick_backend("poll")
        self.assertEqual(backend, "poll")

        auto_backend = pick_backend("auto")
        self.assertIn(auto_backend, ("watchfiles", "poll"))

    def test_is_pid_alive(self):
        self.assertTrue(is_pid_alive(os.getpid()))
        self.assertFalse(is_pid_alive(-1))
        self.assertFalse(is_pid_alive(99999999))

    def test_discover_sot_projects(self):
        proj1 = self.root / "proj1"
        proj1.mkdir()
        (proj1 / ".sot").mkdir()
        (proj1 / ".sot" / "sot.db").touch()

        proj2 = self.root / "nested" / "proj2"
        proj2.mkdir(parents=True)
        (proj2 / ".sot").mkdir()
        (proj2 / ".sot" / "sot.db").touch()

        non_sot = self.root / "other"
        non_sot.mkdir()

        discovered = discover_sot_projects(str(self.root))
        self.assertEqual(len(discovered), 2)
        self.assertIn(str(proj1), discovered)
        self.assertIn(str(proj2), discovered)
        self.assertNotIn(str(non_sot), discovered)

    def test_status_daemon_when_stopped(self):
        st = status_daemon(str(self.root), is_all=False)
        self.assertFalse(st["running"])
        self.assertIsNone(st["pid"])
    def test_process_identity_uses_posix_proc_metadata(self):
        stat_fields = ["S"] + [str(index) for index in range(1, 24)]
        stat_line = "123 (python) " + " ".join(stat_fields)

        with (
            patch("sot_graph.watcher.sys.platform", "linux"),
            patch.object(Path, "is_dir", return_value=True),
            patch.object(
                Path,
                "read_bytes",
                return_value=b"python\0-m\0sot_graph.cli\0watch\0",
            ),
            patch.object(Path, "read_text", return_value=stat_line),
            patch("sot_graph.watcher.subprocess.check_output") as check_output,
        ):
            identity = _process_identity(123)

        self.assertEqual(
            identity,
            {
                "command": "python -m sot_graph.cli watch",
                "start": "19",
            },
        )
        check_output.assert_not_called()

    def test_process_identity_windows_queries_cim_and_degrades_to_none(self):
        # Windows now derives identity from CIM cmdlets so daemon start is
        # verifiable; when no query tool exists it must still return None
        # (unverifiable — never manufactured).
        with (
            patch("sot_graph.watcher.sys.platform", "win32"),
            patch.object(Path, "is_dir", return_value=False),
            patch(
                "sot_graph.watcher.subprocess.check_output",
                side_effect=FileNotFoundError,
            ) as check_output,
        ):
            identity = _process_identity(os.getpid())

        self.assertIsNone(identity)
        self.assertGreaterEqual(check_output.call_count, 1)

    def test_start_daemon_does_not_publish_unverifiable_windows_identity(self):
        class DummyProc:
            pid = 424242

            def __init__(self):
                self.terminated = False

            def terminate(self):
                self.terminated = True

        proc = DummyProc()
        with (
            patch("sot_graph.watcher.sys.platform", "win32"),
            patch.object(Path, "is_dir", return_value=False),
            patch(
                "sot_graph.watcher.subprocess.check_output",
                side_effect=FileNotFoundError,
            ) as check_output,
            patch("sot_graph.watcher.subprocess.Popen", return_value=proc) as popen,
        ):
            ok, message = start_daemon(str(self.root))

        self.assertFalse(ok)
        self.assertIn("identity could not be verified", message)
        self.assertTrue(proc.terminated)
        popen.assert_called_once()
        # CIM query was attempted (win32 path) and its failure made the
        # launch unverifiable → aborted without publishing a PID file.
        self.assertGreaterEqual(check_output.call_count, 1)
        self.assertFalse((self.root / ".sot" / "watch.pid").exists())

        status = status_daemon(str(self.root))
        self.assertFalse(status["running"])
        self.assertIsNone(status["pid"])

    def test_start_and_stop_daemon(self):
        (self.root / ".sot").mkdir(parents=True, exist_ok=True)
        (self.root / ".sot" / "sot.db").touch()

        class DummyProc:
            pid = os.getpid()

        identity = {
            "command": (
                f"{sys.executable} -m sot_graph.cli watch "
                "--debounce-ms 200 --interval-ms 500 --backend auto"
            ),
            "start": "test-start",
        }
        with (
            patch("subprocess.Popen", return_value=DummyProc()),
            patch("sot_graph.watcher._process_identity", return_value=identity),
            patch("sot_graph.watcher._process_cwd", return_value=str(self.root)),
        ):
            ok, msg = start_daemon(str(self.root), is_all=False)
            self.assertTrue(ok)
            self.assertIn("Started SOT Watcher daemon", msg)

            st = status_daemon(str(self.root), is_all=False)
            self.assertTrue(st["running"])
            self.assertEqual(st["pid"], os.getpid())

        with (
            patch("os.kill") as mock_kill,
            patch(
                "sot_graph.watcher.is_pid_alive",
                side_effect=[True, False, False],
            ),
            patch("sot_graph.watcher._process_identity", return_value=identity),
            patch("sot_graph.watcher._process_cwd", return_value=str(self.root)),
        ):
            ok, msg = stop_daemon(str(self.root), is_all=False)
            self.assertTrue(ok)
            self.assertTrue(mock_kill.called)

            pid_path = self.root / ".sot" / "watch.pid"
            self.assertFalse(pid_path.exists())


class TestBatchJanitor(unittest.TestCase):
    """The watcher batch must run global janitors once, not once per file.

    A git checkout touching N files used to run resolve_all_pending_edges
    + cleanup_orphan_edges N times (one full-graph pass per file commit);
    reconcile_paths batches them into a single pass while per-file
    commits stay individual.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name).resolve()
        (self.root / ".sot").mkdir()
        self.db = Database(str(self.root / ".sot" / "sot.db"))
        self.resolver_calls = []
        original_resolver = self.db.resolve_all_pending_edges

        def counting_resolver():
            self.resolver_calls.append(1)
            return original_resolver()

        self.db.resolve_all_pending_edges = counting_resolver
        self.reconciler = Reconciler(self.db, str(self.root))

    def tearDown(self):
        self.db.close()
        self.tmp_dir.cleanup()

    def _write_py(self, name, body):
        path = self.root / name
        path.write_text(body, encoding="utf-8")
        return str(path)

    def test_batch_runs_janitor_once_for_many_files(self):
        paths = [
            self._write_py(f"mod{i}.py", f"def fn{i}(x):\n    return x + {i}\n")
            for i in range(4)
        ]
        published, deferred = _reconcile_quietly(self.reconciler, set(paths))
        self.assertEqual(published, 4)
        self.assertEqual(deferred, set())
        self.assertEqual(self.resolver_calls, [1])
        # Per-file commits stay individual: every file is journaled.
        for path in paths:
            self.assertIsNotNone(self.db.get_file_journal(path))

    def test_batch_skips_janitor_when_nothing_published(self):
        logo = self.root / "logo.png"
        logo.write_bytes(b"\x89PNG\r\n\x1a\nnot-really-an-image")
        published, deferred = _reconcile_quietly(self.reconciler, {str(logo)})
        self.assertEqual(published, 0)
        self.assertEqual(deferred, set())
        self.assertEqual(self.resolver_calls, [])

    def test_batch_defers_lockbusy_paths(self):
        ok_path = self._write_py("ok.py", "def ok():\n    return 1\n")
        busy_path = self._write_py("busy.py", "def busy():\n    return 2\n")
        original = self.reconciler.reconcile_path

        def flaky(path, **kwargs):
            if path == busy_path:
                raise LockBusy("locked by another writer")
            return original(path, **kwargs)

        self.reconciler.reconcile_path = flaky
        published, deferred = _reconcile_quietly(
            self.reconciler, {ok_path, busy_path}
        )
        self.assertEqual(published, 1)
        self.assertEqual(deferred, {busy_path})
        # The published file still got exactly one janitor pass.
        self.assertEqual(self.resolver_calls, [1])

    def test_fallback_per_file_loop_for_legacy_reconcilers(self):
        class LegacyFake:
            def __init__(self):
                self.calls = []

            def reconcile_path(self, path):
                self.calls.append(path)
                if path.endswith("b.py"):
                    raise LockBusy("busy")
                return "indexed"

        fake = LegacyFake()
        published, deferred = _reconcile_quietly(
            fake, {"a.py", "b.py", "c.py"}
        )
        self.assertEqual(published, 2)
        self.assertEqual(deferred, {"b.py"})
        # Deterministic sorted order, one call per file.
        self.assertEqual(fake.calls, ["a.py", "b.py", "c.py"])


if __name__ == "__main__":
    unittest.main()
