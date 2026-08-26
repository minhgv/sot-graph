"""Unit tests for sot_graph.ignore engine and heuristics."""

import os
import tempfile
import unittest
from pathlib import Path

from sot_graph.ignore import (
    DEFAULT_IGNORED_DIRS,
    GitIgnoreMatcher,
    is_virtualenv_dir,
    pattern_to_regex,
)
from sot_graph.reconciler import Reconciler
from sot_graph.db import Database


class TestIgnoreEngine(unittest.TestCase):
    """Test suite for pattern conversion and GitIgnoreMatcher."""

    def test_pattern_to_regex_basic(self):
        regex = pattern_to_regex("*.pyc")
        self.assertTrue(regex.search("foo.pyc"))
        self.assertTrue(regex.search("bar/baz.pyc"))
        self.assertFalse(regex.search("foo.py"))

    def test_pattern_to_regex_directory(self):
        regex = pattern_to_regex("build/")
        self.assertTrue(regex.search("build"))
        self.assertTrue(regex.search("src/build"))

    def test_pattern_to_regex_anchored(self):
        regex = pattern_to_regex("/root_only.txt")
        self.assertTrue(regex.search("root_only.txt"))
        self.assertFalse(regex.search("sub/root_only.txt"))

    def test_pattern_to_regex_doublestar(self):
        regex = pattern_to_regex("foo/**/bar.js")
        self.assertTrue(regex.search("foo/bar.js"))
        self.assertTrue(regex.search("foo/a/b/c/bar.js"))
        self.assertFalse(regex.search("baz/bar.js"))

    def test_gitignore_matcher_file_and_negation(self):
        with tempfile.TemporaryDirectory() as td:
            gitignore = Path(td) / ".gitignore"
            gitignore.write_text("*.log\n!important.log\nsecret/\n")

            matcher = GitIgnoreMatcher(root_dir=td)
            self.assertTrue(matcher.is_ignored("app.log"))
            self.assertTrue(matcher.is_ignored("nested/dir/app.log"))
            self.assertFalse(matcher.is_ignored("important.log"))
            self.assertTrue(matcher.is_ignored("secret/keys.json", is_dir=False))
            self.assertTrue(matcher.is_ignored("secret", is_dir=True))

    def test_sotignore_custom_rules(self):
        with tempfile.TemporaryDirectory() as td:
            sotignore = Path(td) / ".sotignore"
            sotignore.write_text("legacy_dump/\n*.bak\n")

            matcher = GitIgnoreMatcher(root_dir=td)
            self.assertTrue(matcher.is_ignored("legacy_dump", is_dir=True))
            self.assertTrue(matcher.is_ignored("legacy_dump/old.py"))
            self.assertTrue(matcher.is_ignored("data.bak"))
            self.assertFalse(matcher.is_ignored("data.py"))

    def test_default_ignored_dirs(self):
        self.assertIn(".git", DEFAULT_IGNORED_DIRS)
        self.assertIn("node_modules", DEFAULT_IGNORED_DIRS)
        self.assertIn("__pycache__", DEFAULT_IGNORED_DIRS)
        self.assertIn("graphify-out", DEFAULT_IGNORED_DIRS)

    def test_is_virtualenv_dir_heuristics(self):
        with tempfile.TemporaryDirectory() as td:
            custom_env = Path(td) / "my_custom_env"
            custom_env.mkdir()
            (custom_env / "pyvenv.cfg").write_text("home = /usr/bin\n")

            self.assertTrue(is_virtualenv_dir(str(custom_env)))

            custom_env_bin = Path(td) / "custom_env_bin"
            custom_env_bin.mkdir()
            bin_dir = custom_env_bin / "bin"
            bin_dir.mkdir()
            (bin_dir / "activate").write_text("# bash activate script\n")

            self.assertTrue(is_virtualenv_dir(str(custom_env_bin)))

            normal_dir = Path(td) / "src"
            normal_dir.mkdir()
            self.assertFalse(is_virtualenv_dir(str(normal_dir)))

    def test_reconciler_walk_respects_ignore(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "test.db"
            db = Database(str(db_path))

            # Create normal files
            (root / "main.py").write_text("print('hello')\n")
            src_dir = root / "src"
            src_dir.mkdir()
            (src_dir / "util.py").write_text("def util(): pass\n")

            # Create ignored directories and files
            (root / ".gitignore").write_text("ignored_folder/\n*.tmp\n")
            ignored_folder = root / "ignored_folder"
            ignored_folder.mkdir()
            (ignored_folder / "file.py").write_text("def secret(): pass\n")
            (root / "test.tmp").write_text("temporary\n")

            # Create default ignored folder (e.g. node_modules)
            node_modules = root / "node_modules"
            node_modules.mkdir()
            (node_modules / "pkg.js").write_text("console.log(1);\n")

            reconciler = Reconciler(db, str(root))
            walked_files = reconciler._walk(str(root))
            walked_relative = [os.path.relpath(p, str(root)) for p in walked_files]

            self.assertIn("main.py", walked_relative)
            self.assertIn(os.path.join("src", "util.py"), walked_relative)
            self.assertNotIn(os.path.join("ignored_folder", "file.py"), walked_relative)
            self.assertNotIn("test.tmp", walked_relative)
            self.assertNotIn(os.path.join("node_modules", "pkg.js"), walked_relative)
            db.close()


if __name__ == "__main__":
    unittest.main()
