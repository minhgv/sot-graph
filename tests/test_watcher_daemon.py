"""
Tests for sot_graph.watcher daemon, multi-project discovery, and lifecycle management.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sot_graph.watcher import (
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

    def test_start_and_stop_daemon(self):
        (self.root / ".sot").mkdir(parents=True, exist_ok=True)
        (self.root / ".sot" / "sot.db").touch()

        # Mock Popen to avoid running full background processes in unit test
        class DummyProc:
            pid = os.getpid()

        with patch("subprocess.Popen", return_value=DummyProc()):
            ok, msg = start_daemon(str(self.root), is_all=False)
            self.assertTrue(ok)
            self.assertIn("Started SOT Watcher daemon", msg)

            st = status_daemon(str(self.root), is_all=False)
            self.assertTrue(st["running"])
            self.assertEqual(st["pid"], os.getpid())

        # Test stop
        with patch("os.kill") as mock_kill:
            ok, msg = stop_daemon(str(self.root), is_all=False)
            self.assertTrue(ok)
            self.assertTrue(mock_kill.called)

            pid_path = self.root / ".sot" / "watch.pid"
            self.assertFalse(pid_path.exists())


if __name__ == "__main__":
    unittest.main()
