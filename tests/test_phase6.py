"""Phase 6: SCIP export, git hooks provisioning, benchmark harness."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler

REPO_ROOT = Path(__file__).resolve().parent.parent

PROJECT = {
    "src/app/base.py": "class BaseStore:\n    def get(self, key):\n        return None\n",
    "src/app/store.py": (
        "from app.base import BaseStore\n"
        "\n"
        "class SqlStore(BaseStore):\n"
        "    def fetch(self, key):\n"
        "        return key\n"
        "\n"
        "    def load(self, key):\n"
        "        return self.fetch(key)\n"
    ),
    "src/app/client.py": (
        "from app.store import SqlStore\n"
        "from app import legacy\n"
        "\n"
        "def handler(key):\n"
        "    s = SqlStore()\n"
        "    value = s.load(key)\n"
        "    return legacy.a(value)\n"
    ),
    "src/app/legacy.py": (
        "def a(value):\n"
        "    '''First legacy stage: normalizes and forwards.'''\n"
        "    normalized = value.strip().lower()\n" + "".join(
            f"    normalized = normalized.replace('{c}', '')\n" for c in "abcdef"
        ) +
        "    return b(normalized)\n"
        "\n"
        "def b(value):\n"
        "    '''Second legacy stage: buffers and transforms.'''\n"
        "    buffer = []\n" + "".join(f"    buffer.append(value[:{i}])\n" for i in range(8)) +
        "    return c(''.join(buffer))\n"
        "\n"
        "def c(value):\n"
        "    '''Third legacy stage: final reduction.'''\n"
        "    total = 0\n" + "".join(f"    total += ord(ch) % {n}\n" for n in (3, 5, 7, 11, 13, 17, 19, 23)) +
        "    return total\n"
    ),
}


class ScipExportTests(unittest.TestCase):
    def setUp(self):
        from sot_graph.export.scip import _varint

        self._varint = _varint
        self.test_dir = tempfile.mkdtemp()
        for rel, content in PROJECT.items():
            target = Path(self.test_dir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.db = Database(os.path.join(self.test_dir, ".sot", "test.db"))
        Reconciler(self.db, self.test_dir).reconcile(workers=1)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_varint_encoding(self):
        self.assertEqual(self._varint(0), b"\x00")
        self.assertEqual(self._varint(1), b"\x01")
        self.assertEqual(self._varint(300), b"\xac\x02")

    def _walk_fields(self, payload: bytes):
        """Minimal protobuf wire-format reader: yields (field, wire, value)."""
        i = 0
        while i < len(payload):
            tag = 0
            shift = 0
            while True:
                byte = payload[i]
                i += 1
                tag |= (byte & 0x7F) << shift
                shift += 7
                if not byte & 0x80:
                    break
            field, wire = tag >> 3, tag & 7
            if wire == 0:
                value = 0
                shift = 0
                while True:
                    byte = payload[i]
                    i += 1
                    value |= (byte & 0x7F) << shift
                    shift += 7
                    if not byte & 0x80:
                        break
                yield field, wire, value
            elif wire == 2:
                length = 0
                shift = 0
                while True:
                    byte = payload[i]
                    i += 1
                    length |= (byte & 0x7F) << shift
                    shift += 7
                    if not byte & 0x80:
                        break
                yield field, wire, payload[i:i + length]
                i += length
            else:
                raise ValueError(f"unexpected wire type {wire}")

    def test_index_structure_and_counts(self):
        from sot_graph.export.scip import build_scip_index

        payload = build_scip_index(self.db, self.test_dir)
        self.assertTrue(payload)
        fields = list(self._walk_fields(payload))
        self.assertEqual(fields[0][0], 1)  # metadata first
        docs = [v for f, w, v in fields if f == 2]
        self.assertEqual(len(docs), len(PROJECT))

        doc_paths = set()
        total_occurrences = 0
        total_symbols = 0
        for doc in docs:
            for f, w, v in self._walk_fields(doc):
                if f == 1:
                    doc_paths.add(v.decode())
                elif f == 2:
                    total_occurrences += 1
                elif f == 3:
                    total_symbols += 1
        self.assertEqual(doc_paths, {"src/app/base.py", "src/app/store.py",
                                     "src/app/client.py", "src/app/legacy.py"})
        # definitions + call/import reference occurrences
        self.assertGreaterEqual(total_occurrences, total_symbols)
        self.assertGreaterEqual(total_symbols, 4)  # BaseStore, SqlStore, fetch, handler...

    def test_export_scip_writes_file(self):
        from sot_graph.export.scip import export_scip

        out = os.path.join(self.test_dir, "out", "index.scip")
        size = export_scip(self.db, self.test_dir, out)
        self.assertGreater(size, 0)
        self.assertTrue(os.path.isfile(out))


class GitHooksTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q"], cwd=self.test_dir, check=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_hooks_installed_and_idempotent(self):
        from sot_graph.adapters.hooks import HOOK_MARKER, install_git_hooks

        installed = install_git_hooks(Path(self.test_dir))
        self.assertEqual({h.name for h in installed}, {"post-merge", "post-checkout"})
        for hook in installed:
            content = hook.read_text(encoding="utf-8")
            self.assertIn(HOOK_MARKER, content)
            self.assertEqual(content.count(HOOK_MARKER), 1)
            self.assertTrue(os.access(hook, os.X_OK))

        # Second run must not duplicate the block.
        install_git_hooks(Path(self.test_dir))
        for hook in installed:
            self.assertEqual(hook.read_text(encoding="utf-8").count(HOOK_MARKER), 1)

    def test_hooks_respect_existing_content(self):
        from sot_graph.adapters.hooks import HOOK_MARKER, install_git_hooks

        hook = Path(self.test_dir) / ".git" / "hooks" / "post-merge"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\necho custom\n", encoding="utf-8")
        install_git_hooks(Path(self.test_dir))
        content = hook.read_text(encoding="utf-8")
        self.assertIn("#!/bin/sh", content)
        self.assertIn(HOOK_MARKER, content)


class BenchmarkScriptTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        for rel, content in PROJECT.items():
            target = Path(self.test_dir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        db = Database(os.path.join(self.test_dir, ".sot", "test.db"))
        Reconciler(db, self.test_dir).reconcile(workers=1)
        db.close()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_script_reports_savings(self):
        # Micro-fixtures make YAML overhead dominate whole-file reads; the
        # unit contract is a sane, complete metric row — real-repo savings
        # are smoke-checked in docs/BENCHMARKS.md numbers.
        os.rename(os.path.join(self.test_dir, ".sot", "test.db"),
                  os.path.join(self.test_dir, ".sot", "sot.db"))
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "benchmark_context.py"),
             "--targets", "SqlStore.load", "--json", "--root", self.test_dir],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)["results"][0]
        self.assertGreater(data["pack_tokens"], 0)
        self.assertGreater(data["naive_tokens"], 0)
        self.assertGreaterEqual(data["naive_files"], 1)
        self.assertIsInstance(data["saved_percent"], float)


if __name__ == "__main__":
    unittest.main()
