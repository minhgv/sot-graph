"""Unit tests for ScopeManifest and explicit bounded scope (coverage.py)."""

import os
import sys
import pytest

from sot_graph.assurance.coverage import (
    ScopeManifest,
    build_scope_manifest,
    is_quarantined,
)


class DummyDB:
    def __init__(self, rows):
        self._rows = rows
        self.conn = self

    def execute(self, _sql, _params=()):
        class Cursor:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

            def fetchone(self):
                return self._rows[0] if self._rows else None

        return Cursor(self._rows)


class TestScopeManifest:
    def test_build_scope_manifest_excludes_generated_and_marks_errors(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "app.py").write_text("def app(): pass\n", encoding="utf-8")
        (src_dir / "broken.py").write_text("def broken(: pass\n", encoding="utf-8")
        (src_dir / "util.py").write_text("def util(): pass\n", encoding="utf-8")
        nm_dir = tmp_path / "node_modules" / "pkg"
        nm_dir.mkdir(parents=True, exist_ok=True)
        (nm_dir / "index.js").write_text("console.log('hi');\n", encoding="utf-8")

        rows = [
            (str(src_dir / "app.py"), "COMPLETE", None),
            (str(src_dir / "broken.py"), "PARSE_ERROR", "SyntaxError"),
            (str(nm_dir / "index.js"), "COMPLETE", None),
            (str(src_dir / "util.py"), "COMPLETE", None),
        ]
        db = DummyDB(rows)
        manifest = build_scope_manifest(db, str(tmp_path))
        assert isinstance(manifest, ScopeManifest)

        assert "src/app.py" in manifest.included_files
        assert "src/util.py" in manifest.included_files
        assert "src/broken.py" in manifest.included_files
        assert "node_modules/pkg/index.js" not in manifest.included_files

        assert "src/broken.py" in manifest.parser_error_files
        assert is_quarantined("src/broken.py", manifest) is True
        assert is_quarantined("src/app.py", manifest) is False

        assert manifest.manifest_digest.startswith("sha256:")
        d = manifest.to_dict()
        assert d["manifest_digest"] == manifest.manifest_digest
        assert "src/broken.py" in d["quarantined_files"]

    def test_explicit_target_paths_restriction(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "app.py").write_text("def app(): pass\n", encoding="utf-8")
        (src_dir / "util.py").write_text("def util(): pass\n", encoding="utf-8")
        (src_dir / "other.py").write_text("def other(): pass\n", encoding="utf-8")

        rows = [
            (str(src_dir / "app.py"), "COMPLETE", None),
            (str(src_dir / "util.py"), "COMPLETE", None),
            (str(src_dir / "other.py"), "COMPLETE", None),
        ]
        db = DummyDB(rows)
        manifest = build_scope_manifest(db, str(tmp_path), target_paths=["src/app.py"])

        assert manifest.included_files == ["src/app.py"]
        assert is_quarantined("src/app.py", manifest) is False

    def test_missing_file_quarantined_fail_closed(self, tmp_path):
        rows = [
            ("src/ghost.py", "COMPLETE", None),
        ]
        db = DummyDB(rows)
        manifest = build_scope_manifest(db, str(tmp_path))
        assert "src/ghost.py" in manifest.parser_error_files
        assert "src/ghost.py" in manifest.quarantined_files
        assert any("missing_source" in c for c in manifest.unsupported_constructs)
        assert is_quarantined("src/ghost.py", manifest) is True

    def test_path_traversal_relative_and_absolute_quarantined_fail_closed(self, tmp_path):
        rows = [
            ("../outside.py", "COMPLETE", None),
            ("src/../../escape.py", "COMPLETE", None),
            ("/tmp/absolute_outside.py", "COMPLETE", None),
        ]
        db = DummyDB(rows)
        manifest = build_scope_manifest(db, str(tmp_path))
        assert "../outside.py" in manifest.parser_error_files
        assert "src/../../escape.py" in manifest.parser_error_files
        assert "/tmp/absolute_outside.py" in manifest.parser_error_files
        assert any("path_traversal_out_of_repo" in c for c in manifest.unsupported_constructs)
        assert is_quarantined("../outside.py", manifest) is True
        assert is_quarantined("src/../../escape.py", manifest) is True
        assert is_quarantined("/tmp/absolute_outside.py", manifest) is True
    def test_exclusion_does_not_strip_valid_substring_paths(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "rebuilder.py").write_text("def rebuild(): pass\n", encoding="utf-8")
        build_dir = tmp_path / "build"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "output.py").write_text("def gen(): pass\n", encoding="utf-8")

        rows = [
            (str(src_dir / "rebuilder.py"), "COMPLETE", None),
            (str(build_dir / "output.py"), "COMPLETE", None),
        ]
        db = DummyDB(rows)
        manifest = build_scope_manifest(db, str(tmp_path), excluded_patterns=["build"])
        assert "src/rebuilder.py" in manifest.included_files
        assert "build/output.py" not in manifest.included_files

    def test_unjournaled_files_on_disk_are_quarantined(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "journaled.py").write_text("def j(): pass\n", encoding="utf-8")
        (src_dir / "unjournaled.py").write_text("def unj(): pass\n", encoding="utf-8")

        rows = [
            (str(src_dir / "journaled.py"), "COMPLETE", None),
        ]
        db = DummyDB(rows)
        manifest = build_scope_manifest(db, str(tmp_path))
        assert "src/journaled.py" in manifest.included_files
        assert "src/unjournaled.py" in manifest.included_files
        assert "src/unjournaled.py" in manifest.parser_error_files
        assert "src/unjournaled.py" in manifest.quarantined_files
        assert any("unjournaled_file" in c for c in manifest.unsupported_constructs)
    def test_outside_directory_symlink_quarantined_fail_closed(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "valid.py").write_text("def v(): pass\n", encoding="utf-8")

        outside_dir = tmp_path.parent / "outside_dir_target"
        outside_dir.mkdir(parents=True, exist_ok=True)
        (outside_dir / "secret.py").write_text("def secret(): pass\n", encoding="utf-8")

        symlink_dir = src_dir / "external_symlink"
        try:
            symlink_dir.symlink_to(outside_dir, target_is_directory=True)
        except OSError:
            return  # skip if symlinks not supported on OS

        rows = [
            (str(src_dir / "valid.py"), "COMPLETE", None),
        ]
        db = DummyDB(rows)
        manifest = build_scope_manifest(db, str(tmp_path))
        assert "src/valid.py" in manifest.included_files
        assert "src/external_symlink" in manifest.quarantined_files
        assert any("src/external_symlink:outside_symlink" in c for c in manifest.unsupported_constructs)

    @pytest.mark.skipif(sys.platform == "win32" or os.sep == "\\", reason="Literal backslash filenames not supported on Windows")
    def test_scope_manifest_special_filename_not_aliased(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "odd").mkdir(parents=True, exist_ok=True)
        (src_dir / "odd" / "name.py").write_text("def nested(): pass\n", encoding="utf-8")
        backslash_file = src_dir / "odd\\name.py"
        backslash_file.write_text("def backslash(): pass\n", encoding="utf-8")

        # Only the directory-nested file is in the journal
        rows = [
            (str(src_dir / "odd" / "name.py"), "COMPLETE", None),
        ]
        db = DummyDB(rows)
        manifest = build_scope_manifest(db, str(tmp_path))

        assert "src/odd/name.py" in manifest.included_files
        assert "src/odd/name.py" not in manifest.quarantined_files

        # The literal backslash file on disk is unjournaled and MUST be quarantined, not aliased to src/odd/name.py
        assert "src/odd\\name.py" in manifest.included_files
        assert "src/odd\\name.py" in manifest.quarantined_files

    @pytest.mark.skipif(sys.platform == "win32" or os.sep == "\\", reason="Literal backslash filenames not supported on Windows")
    def test_scope_manifest_node_modules_backslash_not_excluded_as_dir(self, tmp_path):
        root_file = tmp_path / "node_modules\\live.py"
        try:
            root_file.write_text("def live(): pass\n", encoding="utf-8")
        except OSError:
            return  # skip if literal backslash not supported in filename

        db = DummyDB([])
        manifest = build_scope_manifest(db, str(tmp_path))
        # Must not be excluded as a generated node_modules directory
        assert "node_modules\\live.py" in manifest.included_files
        assert "node_modules\\live.py" in manifest.quarantined_files
        assert any("unjournaled_file" in c for c in manifest.unsupported_constructs)
    def test_scope_manifest_custom_directory_exclusions(self, tmp_path):
        custom_dir = tmp_path / "custom_ignored"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "file.py").write_text("def custom(): pass\n", encoding="utf-8")
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "valid.py").write_text("def valid(): pass\n", encoding="utf-8")

        rows = [(str(src_dir / "valid.py"), "COMPLETE", None)]
        db = DummyDB(rows)
        manifest = build_scope_manifest(
            db, str(tmp_path), excluded_patterns=["custom_ignored", "custom_ignored/*"]
        )
        assert "src/valid.py" in manifest.included_files
        assert "custom_ignored/file.py" not in manifest.included_files
        assert "custom_ignored/file.py" not in manifest.quarantined_files

    def test_scope_manifest_surrogate_escape_undecodable_filename(self, tmp_path):
        # Non-UTF8 byte sequence in filename (POSIX surrogateescape)
        bad_name = "invalid_\udcff_file.py"
        try:
            (tmp_path / bad_name).write_text("x = 1\n", encoding="utf-8")
        except OSError:
            return
        db = DummyDB([])
        manifest = build_scope_manifest(db, str(tmp_path))
        assert bad_name in manifest.included_files
        assert bad_name in manifest.quarantined_files
        assert manifest.manifest_digest.startswith("sha256:")
