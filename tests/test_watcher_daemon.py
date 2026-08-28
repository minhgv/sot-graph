"""
Tests for sot_graph.watcher daemon, multi-project discovery, and lifecycle management.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sot_graph.watcher import (
    _process_identity,
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

    def test_process_identity_refuses_windows_without_proc_or_ps(self):
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
        check_output.assert_not_called()

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
        check_output.assert_not_called()
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


if __name__ == "__main__":
    unittest.main()
