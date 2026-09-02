"""Unit tests for ScopeManifest and explicit bounded scope (coverage.py)."""

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
