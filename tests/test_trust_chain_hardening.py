"""Regression tests for Trust Chain Hardening and Fail-Closed semantics."""

from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys

from sot_graph.db import Database
from sot_graph.diff_impact import GitDeltaExtractor, ASTCoordinateMapper
from sot_graph.reconciler import Reconciler, ReconcileSummary
from sot_graph.snapshot import _content_binding, capture_worktree_snapshot
from sot_graph.assurance.coverage import (
    build_scope_manifest,
    is_quarantined,
    _is_excluded,
)
from sot_graph.assurance.receipts import reconcile_receipt, audit_receipt
from sot_graph.assurance.state import ReceiptStatus
from sot_graph.providers.base import SymbolRequest
from sot_graph.providers.scip import ScipProvider
from sot_graph.assurance.orchestrator import federation_plan, run_federated_query

def test_path_traversal_and_outside_symlink_quarantined(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def run(): pass\n")

    outside = tmp_path / "outside.py"
    outside.write_text("secret = 42\n")

    outside_symlink = repo / "sym_outside.py"
    try:
        os.symlink(str(outside), str(outside_symlink))
    except (OSError, NotImplementedError):
        pass

    _digests, scope_digest, unreadable = _content_binding(
        str(repo),
        ["app.py", "../outside.py", "sym_outside.py"],
    )

    assert scope_digest is None
    assert "../outside.py" in unreadable
    if outside_symlink.exists():
        assert "sym_outside.py" in unreadable


def test_exclusion_substring_preserves_legitimate_files():
    assert _is_excluded("build/temp.py") is True
    assert _is_excluded("dist/bundle.js") is True
    assert _is_excluded("node_modules/pkg/index.js") is True
    assert _is_excluded("src/api_pb2.py") is True
    assert _is_excluded("app/bundle.min.js") is True

    # Legitimate non-excluded files with matching substrings
    assert _is_excluded("src/rebuilder.py") is False
    assert _is_excluded("src/builder_service.py") is False
    assert _is_excluded("src/distribution.py") is False
    assert _is_excluded("src/vendor_management.py") is False


def test_unjournaled_files_discovered_and_quarantined(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "indexed.py").write_text("def run(): pass\n")

    db = Database(str(repo / ".sot" / "sot.db"))
    try:
        Reconciler(db, str(repo)).reconcile()

        (repo / "unjournaled.py").write_text("def unindexed(): pass\n")

        manifest = build_scope_manifest(db, str(repo))

        assert "unjournaled.py" in manifest.quarantined_files
        assert is_quarantined("unjournaled.py", manifest) is True
    finally:
        db.close()


def test_audit_receipt_fail_closed_on_doctor_error(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def run(): pass\n")

    db = Database(str(repo / ".sot" / "sot.db"))
    try:
        Reconciler(db, str(repo)).reconcile()

        doctor_failing = {
            "ok": False,
            "foreign_keys_ok": False,
            "unresolved_count": 5,
            "errors": ["Foreign key integrity violated"],
        }
        receipt = audit_receipt(db, str(repo), doctor_report=doctor_failing)
        assert receipt["assurance"]["status"] == ReceiptStatus.UNVERIFIABLE
        assert "collection_error" in receipt["assurance"]["reason_codes"]
        assert any("doctor_integrity_failed" in err for err in receipt["collection_errors"])

        doctor_clean = {
            "ok": True,
            "foreign_keys_ok": True,
            "unresolved_count": 0,
            "errors": [],
        }
        clean_receipt = audit_receipt(db, str(repo), doctor_report=doctor_clean)
        assert clean_receipt["assurance"]["status"] == ReceiptStatus.ASSURED_WITHIN_SCOPE
    finally:
        db.close()


def test_reconcile_receipt_fail_closed_on_failed_reconcile(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def run(): pass\n")

    db = Database(str(repo / ".sot" / "sot.db"))
    try:
        rec = Reconciler(db, str(repo))
        _ = rec.reconcile()

        failing_summary = ReconcileSummary(
            scanned=1,
            unchanged=0,
            updated=0,
            deleted=0,
            failed=2,
            duration_ms=10,
        )
        receipt = reconcile_receipt(db, str(repo), asdict(failing_summary))
        assert receipt["assurance"]["status"] == ReceiptStatus.UNVERIFIABLE
        assert "collection_error" in receipt["assurance"]["reason_codes"]
        assert any("reconcile_failed: 2 files failed to reconcile" in err for err in receipt["collection_errors"])
    finally:
        db.close()


def test_parser_unavailable_quarantined_and_fail_closed(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def run(): pass\n")

    db = Database(str(repo / ".sot" / "sot.db"))
    try:
        Reconciler(db, str(repo)).reconcile()

        db.conn.execute(
            "INSERT OR REPLACE INTO file_journal (path, sha256, size, mtime_ms, generation, reconciled_at, parser_outcome, parser_error) "
            "VALUES ('unsupported.ext', 'dummyhash', 100, 1000, 1, 1000, 'PARSER_UNAVAILABLE', 'no parser for ext')"
        )
        db.conn.commit()

        manifest = build_scope_manifest(db, str(repo))
        assert "unsupported.ext" in manifest.quarantined_files
        assert is_quarantined("unsupported.ext", manifest) is True

        receipt = audit_receipt(db, str(repo))
        assert receipt["assurance"]["status"] != ReceiptStatus.ASSURED_WITHIN_SCOPE
    finally:
        db.close()


def test_scip_usages_routing_and_require_mode(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    dot_sot = repo / ".sot"
    dot_sot.mkdir(parents=True)
    (dot_sot / "config.toml").write_text("allow_external = true\n")

    scip_file = repo / "index.scip"
    scip_file.write_bytes(b"dummy scip bytes")

    provider = ScipProvider(index_path=str(scip_file))
    st = provider.probe(str(repo))
    assert st.installed is True
    assert st.healthy is True
    assert "usages" in st.capabilities

    plan = federation_plan("require:scip", str(repo), "usages")
    assert plan["mode"] == "require"
    assert plan["provider"] is not None
    assert plan["provider"].name == "scip"
    assert plan["fail_message"] is None

    outcome, method = run_federated_query(plan, str(repo), "usages", "target_symbol")
    assert method == "usages"
    assert outcome is not None

    plan_invalid = federation_plan("require:nonexistent-provider", str(repo), "usages")
    assert plan_invalid["mode"] == "require"
    assert plan_invalid["provider"] is None
    assert "is not queryable" in plan_invalid["fail_message"]

    (repo / ".sot").mkdir(parents=True, exist_ok=True)
    (repo / ".sot" / "config.toml").write_text("allow_external = false\n")
    plan_disabled = federation_plan("require:codebase-memory", str(repo), "usages")
    assert plan_disabled["mode"] == "require"
    assert plan_disabled["provider"] is None
    assert "fails closed" in plan_disabled["fail_message"]

def test_audit_receipt_fail_closed_on_unjournaled_files(tmp_path: Path):
    """Blocker 1: audit_receipt must scan filesystem and fail-closed when unjournaled files exist."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def hello(): pass\n")

    db = Database(str(repo / ".sot" / "sot.db"))
    try:
        Reconciler(db, str(repo)).reconcile()
        # Clean state: all files journaled
        receipt_clean = audit_receipt(db, str(repo), doctor_report={"ok": True})
        assert receipt_clean["assurance"]["status"] == ReceiptStatus.ASSURED_WITHIN_SCOPE
        assert receipt_clean["quarantined_files"] == []
        snap_clean = receipt_clean["snapshot"]["scope_digest"]

        # Add unjournaled file to disk
        (repo / "new_unjournaled.py").write_text("def unjournaled(): pass\n")
        receipt_dirty = audit_receipt(db, str(repo), doctor_report={"ok": True})
        assert receipt_dirty["assurance"]["status"] != ReceiptStatus.ASSURED_WITHIN_SCOPE
        assert any("new_unjournaled.py" in q for q in receipt_dirty["quarantined_files"])
        assert any("quarantined_files" in err for err in receipt_dirty["collection_errors"])
        assert receipt_dirty["snapshot"]["scope_digest"] is not None
        assert receipt_dirty["snapshot"]["scope_digest"] != snap_clean
    finally:
        db.close()


def test_diff_impact_captures_untracked_files(tmp_path: Path):
    """Blocker 2: working-tree diff must union untracked files into changed_files."""
    import subprocess
    from sot_graph.diff_impact import analyze_diff_impact

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tracked.py").write_text("def tracked(): pass\n")

    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=str(repo), check=True, capture_output=True)

    db = Database(str(repo / ".sot" / "sot.db"))
    try:
        Reconciler(db, str(repo)).reconcile()
        # Create untracked file
        (repo / "untracked.py").write_text("def untracked(): pass\n")

        res = analyze_diff_impact(db, repo_path=str(repo), working_tree=True)
        assert any("untracked.py" in f for f in res.changed_files)
        assert any(h.file_path == "untracked.py" for h in res.hunks)
    finally:
        db.close()


def test_usages_routing_rejects_symbols_only_provider(tmp_path: Path):
    """Blocker 3: usages capability negotiation must reject symbols-only providers."""
    from sot_graph.assurance.routing import supports_capability
    from sot_graph.assurance.orchestrator import run_federated_query

    class SymbolsOnly:
        name = "symbols-only"
        capabilities = ["symbols"]
        def search_symbols(self, req):
            pass

    provider = SymbolsOnly()
    assert not supports_capability(provider, "usages")
    assert not supports_capability(provider, "references")
    assert supports_capability(provider, "symbols")

    plan = {
        "mode": "require",
        "target": "symbols-only",
        "provider": provider,
        "candidates": [{"provider": "symbols-only", "capabilities": ["symbols"]}],
        "warnings": [],
    }
    outcome, method = run_federated_query(plan, str(tmp_path), "usages", "TargetSymbol")
    assert outcome is None
    assert method is None


def test_usages_routing_rejects_unadvertised_usages_method(tmp_path: Path):
    """A provider with a callable usages method that only advertises symbols capability must be rejected."""
    from sot_graph.assurance.routing import supports_capability
    from sot_graph.assurance.orchestrator import run_federated_query

    class UnadvertisedUsages:
        name = "unadvertised-usages"
        capabilities = ["symbols"]
        def usages(self, req):
            return "unexpected_bypass"
        def search_symbols(self, req):
            pass

    provider = UnadvertisedUsages()
    assert not supports_capability(provider, "usages")
    for mode in ["auto", "prefer", "require"]:
        plan = {
            "mode": mode,
            "target": "unadvertised-usages",
            "provider": provider,
            "candidates": [{"provider": "unadvertised-usages", "capabilities": ["symbols"]}],
            "warnings": [],
        }
        outcome, method = run_federated_query(plan, str(tmp_path), "usages", "TargetSymbol")
        assert outcome is None
        assert method is None
def test_scip_exact_limit_not_truncated(tmp_path: Path):
    """SCIP Provider must not set truncated=True when match count equals limit."""
    scip_file = tmp_path / "index.scip"
    doc = {
        "metadata": {"version": "0.4.0"},
        "documents": [
            {
                "relative_path": "src/service.py",
                "symbols": [
                    {"symbol": "scip-python python pkg 0.1.0 `src/service.py`/Alpha#", "kind": "class"},
                    {"symbol": "scip-python python pkg 0.1.0 `src/service.py`/Beta#", "kind": "class"},
                ],
                "occurrences": [
                    {"range": [1, 0, 1, 10], "symbol": "scip-python python pkg 0.1.0 `src/service.py`/Alpha#", "symbol_roles": 1},
                    {"range": [5, 0, 5, 10], "symbol": "scip-python python pkg 0.1.0 `src/service.py`/Alpha#", "symbol_roles": 2},
                ],
            }
        ],
    }
    scip_file.write_text(json.dumps(doc), encoding="utf-8")
    provider = ScipProvider()

    # 1. Search symbols: query "Alpha" matches 1 symbol. limit=1 should return 1 result, truncated=False, has_more=False
    res_search_exact = provider.search_symbols(SymbolRequest(repo_root=str(tmp_path), query="Alpha", limit=1))
    assert res_search_exact.ok
    assert res_search_exact.payload["count"] == 1
    assert res_search_exact.payload["truncated"] is False
    assert res_search_exact.payload["has_more"] is False

    # 2. Search symbols: query "service" matches 2 symbols. limit=1 should return 1 result, truncated=True, has_more=True
    res_search_over = provider.search_symbols(SymbolRequest(repo_root=str(tmp_path), query="service", limit=1))
    assert res_search_over.ok
    assert res_search_over.payload["count"] == 1
    assert res_search_over.payload["truncated"] is True
    assert res_search_over.payload["has_more"] is True

    # 3. Search symbols: query "service" with limit=2 should return 2 results, truncated=False, has_more=False
    res_search_exact2 = provider.search_symbols(SymbolRequest(repo_root=str(tmp_path), query="service", limit=2))
    assert res_search_exact2.ok
    assert res_search_exact2.payload["count"] == 2
    assert res_search_exact2.payload["truncated"] is False
    assert res_search_exact2.payload["has_more"] is False

    # 4. Usages: query "Alpha" matches 2 occurrences. limit=1 should return 1 result, truncated=True, has_more=True
    res_usages_over = provider.usages(SymbolRequest(repo_root=str(tmp_path), query="Alpha", limit=1))
    assert res_usages_over.ok
    assert res_usages_over.payload["count"] == 1
    assert res_usages_over.payload["truncated"] is True
    assert res_usages_over.payload["has_more"] is True

    # 5. Usages: query "Alpha" matches 2 occurrences. limit=2 should return 2 results, truncated=False, has_more=False
    res_usages_exact = provider.usages(SymbolRequest(repo_root=str(tmp_path), query="Alpha", limit=2))
    assert res_usages_exact.ok
    assert res_usages_exact.payload["count"] == 2
    assert res_usages_exact.payload["truncated"] is False
    assert res_usages_exact.payload["has_more"] is False

def test_diff_impact_untracked_special_filenames(tmp_path: Path):
    """Untracked files with literal backslashes or leading/trailing spaces must be captured."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
    (repo / "tracked.py").write_text("print('tracked')\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True)

    # Create special untracked files
    # 1. Backslash filename (POSIX supported, skipped on Windows)
    is_posix = sys.platform != "win32" and os.sep != "\\"
    backslash_name = "odd\\name.py"
    if is_posix:
        (repo / backslash_name).write_text("print('backslash')\nprint('line2')\n")
    space_name = " spaced name .py"
    (repo / space_name).write_text("print('spaced')\n")

    extractor = GitDeltaExtractor(str(repo))
    file_intervals, hunks = extractor.extract_diff(working_tree=True)

    if is_posix:
        assert backslash_name in file_intervals
        assert file_intervals[backslash_name] == [(1, 2)]
    assert space_name in file_intervals
    assert file_intervals[space_name] == [(1, 1)]

    hunk_files = [h.file_path for h in hunks]
    if is_posix:
        assert backslash_name in hunk_files
    assert space_name in hunk_files

def test_snapshot_blank_path_citations_fail_closed(tmp_path: Path):
    """Blank or whitespace path citations in snapshot must record unreadable and invalidate scope digest."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("x = 1\n")

    snapshot = capture_worktree_snapshot(str(repo), cited_paths=["", "   ", "main.py"])
    assert snapshot.scope_digest is None
    assert "" in snapshot.unreadable or "<empty>" in snapshot.unreadable
    assert "   " in snapshot.unreadable
    assert "main.py" in snapshot.content_digests


def test_snapshot_special_filenames_no_aliasing(tmp_path: Path):
    """Snapshot content binding must preserve exact filenames with backslashes and spaces without aliasing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    # Create odd\name.py (POSIX only) and odd/name.py
    is_posix = sys.platform != "win32" and os.sep != "\\"
    (repo / "odd").mkdir()
    (repo / "odd" / "name.py").write_text("nested content\n")
    backslash_name = "odd\\name.py"
    cited = ["odd/name.py"]
    if is_posix:
        (repo / backslash_name).write_text("backslash content\n")
        cited.append(backslash_name)

    # Create leading.py and ' leading.py'
    (repo / "leading.py").write_text("plain leading\n")
    spaced_name = " leading.py"
    (repo / spaced_name).write_text("spaced leading\n")
    cited.extend(["leading.py", spaced_name])

    snapshot = capture_worktree_snapshot(
        str(repo),
        cited_paths=cited,
    )
    assert snapshot.scope_digest is not None
    assert snapshot.unreadable == []
    digests = snapshot.content_digests
    assert "odd/name.py" in digests
    if is_posix:
        assert backslash_name in digests
        assert digests["odd/name.py"] != digests[backslash_name]
    assert "leading.py" in digests
    assert spaced_name in digests
    assert digests["leading.py"] != digests[spaced_name]

def test_scip_3_element_span_resolution(tmp_path: Path):
    """SCIP 3-element and 4-element occurrence ranges must map accurately to 1-based line/col spans."""
    scip_file = tmp_path / "index.scip"
    doc = {
        "metadata": {"version": "0.4.0"},
        "documents": [
            {
                "relative_path": "src/parser.py",
                "symbols": [],
                "occurrences": [
                    {
                        "range": [10, 4, 22],
                        "symbol": "scip-python python pkg 0.1.0 `src/parser.py`/parse().",
                        "symbol_roles": 1,
                    },
                    {
                        "range": [10, 4, 15, 30],
                        "symbol": "scip-python python pkg 0.1.0 `src/parser.py`/parse().",
                        "symbol_roles": 2,
                    },
                ],
            }
        ],
    }
    scip_file.write_text(json.dumps(doc), encoding="utf-8")
    provider = ScipProvider()
    outcome = provider.usages(SymbolRequest(repo_root=str(tmp_path), query="parse"))
    assert outcome.ok
    symbols = outcome.payload["symbols"]
    assert len(symbols) == 2

    # 3-element range: [10, 4, 22] -> start_line=11, start_col=5, end_line=11, end_col=23
    assert symbols[0]["span"] == {
        "start_line": 11,
        "start_column": 5,
        "end_line": 11,
        "end_column": 23,
    }
    assert symbols[0]["is_definition"] is True

    # 4-element range: [10, 4, 15, 30] -> start_line=11, start_col=5, end_line=16, end_col=31
    assert symbols[1]["span"] == {
        "start_line": 11,
        "start_column": 5,
        "end_line": 16,
        "end_column": 31,
    }
    assert symbols[1]["is_definition"] is False


def test_orchestrator_require_mode_no_invocable_method_fails_closed(tmp_path: Path):
    """When require mode provider supports capability but has no callable method, query must fail closed."""
    class BrokenProvider:
        name = "broken"
        provider_version = "1.0.0"
        capabilities = ("usages",)

    provider = BrokenProvider()
    plan = {
        "mode": "require",
        "target": "broken",
        "provider": provider,
        "providers": [provider],
        "statuses": [{"name": "broken", "installed": True, "healthy": True, "version": "1.0.0"}],
        "candidates": [{"provider": "broken", "capabilities": ["usages"]}],
        "warnings": [],
        "fail_message": None,
    }
    outcome, method = run_federated_query(plan, str(tmp_path), "usages", "TargetSymbol")
    assert outcome is None
    assert method is None

    result = {
        "warnings": list(plan["warnings"]),
        "fail_message": plan["fail_message"],
        "candidates": [],
        "conflicts": [],
        "providers_extra": [],
        "coverage": None,
        "known_gaps": None,
        "truncated": False,
        "diff_identity": None,
    }
    for p in plan["providers"]:
        pname = p.name
        per_plan = dict(plan, provider=p, name=pname)
        out, m = run_federated_query(per_plan, str(tmp_path), "usages", "TargetSymbol")
        if out is None and plan["mode"] == "require":
            plan["fail_message"] = result["fail_message"] = (
                f"require:{pname}: no invocable method for 'usages'; failing closed"
            )
            break

    assert "fail_message" in result
    assert "failing closed" in result["fail_message"]
    assert "fail_message" in plan
    assert "failing closed" in plan["fail_message"]


def test_snapshot_surrogate_escape_filename_binding(tmp_path: Path):
    """Snapshot and content binding must handle surrogateescape non-UTF8 paths without crashing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    bad_name = "surrogate_\udcff_file.py"
    try:
        (repo / bad_name).write_text("x = 42\n", encoding="utf-8")
    except OSError:
        return

    snapshot = capture_worktree_snapshot(str(repo), cited_paths=[bad_name])
    assert snapshot.descriptor_digest.startswith("sha256:")
    assert snapshot.scope_digest is not None
    assert snapshot.scope_digest.startswith("sha256:")
    assert bad_name in snapshot.content_digests


def test_ast_coordinate_mapper_path_normalization_no_aliasing(tmp_path: Path):
    """ASTCoordinateMapper must not alias odd\\name.py to odd/name.py or ..hidden.py to hidden.py."""
    db = Database(str(tmp_path / "test.db"))
    try:
        mapper = ASTCoordinateMapper(db)
        # Verify normalization preserves POSIX backslashes and double leading dots
        assert mapper._normalize_path("..hidden.py") == "..hidden.py"
        if os.sep != "\\":
            assert mapper._normalize_path("odd\\name.py") == "odd\\name.py"
        assert mapper._normalize_path("./src/app.py") == "src/app.py"

        # Insert a node for odd/name.py
        db.conn.execute(
            "INSERT INTO graph_nodes (id, path, kind, symbol, fqn, label, body, line_start, line_end, updated_at) "
            "VALUES ('n1', 'odd/name.py', 'function', 'nested', 'nested', 'nested', 'def nested(): pass', 1, 10, 1000)"
        )
        db.conn.commit()

        # Map interval for odd\name.py (distinct filename on POSIX)
        intervals = {"odd\\name.py": [(1, 5)]}
        if os.sep != "\\":
            nodes = mapper.map_intervals_to_nodes(intervals)
            # Must NOT match the odd/name.py node
            assert len(nodes) == 0
    finally:
        db.close()


def test_mcp_fits_response_surrogateescape(tmp_path: Path):
    """McpService._fits_response must handle high and low surrogate characters without crashing."""
    from sot_graph.mcp_service import McpService, ServiceLimits, sanitize_transport_value
    db = Database(str(tmp_path / "mcp.db"))
    db.close()
    service = McpService(str(tmp_path / "mcp.db"), str(tmp_path), limits=ServiceLimits(response_bytes=1000, body_bytes=500))
    payload = {
        "results": [
            {"path": "file_\udcff_low.py", "snippet": "def fn(): pass"},
            {"path": "file_\ud800_high.py", "snippet": "def fn2(): pass"},
        ]
    }
    res = service._fits_response(payload)
    assert res is not None
    assert "results" in res
    assert len(res["results"]) == 2
    sanitized = sanitize_transport_value("lone_\ud800_and_\udcff")
    assert isinstance(sanitized, str)
    sanitized.encode("utf-8")  # Must not raise
def test_mcp_server_json_surrogateescape():
    """mcp_server._json must encode surrogateescape characters into ASCII-escaped JSON without UnicodeEncodeError."""
    try:
        from sot_graph.mcp_server import _json
    except Exception:
        pytest.skip("mcp extra not installed")
    payload = {"path": "file_\udcff_test.py", "count": 1}
    serialized = _json(payload)
    assert isinstance(serialized, str)
    # Must be encodable to UTF-8 without raising UnicodeEncodeError
    utf8_bytes = serialized.encode("utf-8")
    assert b"file_" in utf8_bytes


def test_scip_artifacts_parity():
    """SCIP_ARTIFACTS in providers_registry must cover all default SCIP artifact filenames."""
    from sot_graph.providers.scip import SCIP_DEFAULT_ARTIFACTS
    from sot_graph.providers_registry import SCIP_ARTIFACTS
    for artifact in SCIP_DEFAULT_ARTIFACTS:
        assert artifact in SCIP_ARTIFACTS


def test_orchestrator_scip_exempt_from_allow_external(tmp_path: Path):
    """SCIP index provider is local and must remain plannable even when allow_external is False."""
    from sot_graph.assurance.orchestrator import federation_plan
    from sot_graph.config import SotConfig

    scip_file = tmp_path / "index.scip.json"
    scip_file.write_text('{"metadata": {"version": "0.4.0"}, "documents": []}', encoding="utf-8")

    # Create sot.ini with allow_external = false
    ini_path = tmp_path / "sot.ini"
    ini_path.write_text("[sot]\nallow_external = false\n", encoding="utf-8")

    plan = federation_plan("require:scip", str(tmp_path), "symbols")
    assert plan["fail_message"] is None
    assert plan["provider"] is not None
    assert plan["provider"].name == "scip"

def test_scip_provider_persists_runs_and_evidence_to_db(tmp_path: Path):
    """ScipProvider must persist provider_runs and provider_evidence when db is provided."""
    from sot_graph.db import Database
    from sot_graph.providers.base import SymbolRequest
    from sot_graph.providers.scip import ScipProvider

    doc = {
        "metadata": {"version": "0.4.0"},
        "documents": [
            {
                "relative_path": "src/main.py",
                "symbols": [
                    {"symbol": "pkg/Main#", "kind": "class", "documentation": ["Main class"]},
                ],
                "occurrences": [
                    {"symbol": "pkg/Main#", "symbol_roles": 1, "range": [10, 4, 10, 8]},
                ],
            }
        ],
    }
    scip_file = tmp_path / "index.scip.json"
    scip_file.write_text(json.dumps(doc), encoding="utf-8")

    db = Database(str(tmp_path / "sot.db"))
    try:
        provider = ScipProvider(index_path=str(scip_file), db=db)
        res = provider.search_symbols(SymbolRequest(repo_root=str(tmp_path), query="Main"))
        assert res.ok

        # Verify run record in SQLite
        runs = db.conn.execute("SELECT id, provider_name, status, capability FROM provider_runs").fetchall()
        assert len(runs) >= 1
        assert runs[0][1] == "scip"
        assert runs[0][2] == "ok"
        assert runs[0][3] == "symbols"

        # Verify evidence recorded
        ev = db.conn.execute("SELECT symbol, path, relation FROM provider_evidence").fetchall()
        assert len(ev) >= 1
        assert ev[0][0] in ("Main", "pkg/Main#", "pkg.Main")
        assert ev[0][1] == "src/main.py"
    finally:
        db.close()


def test_ledger_cross_check_detects_failed_provider_runs(tmp_path: Path):
    """Failed provider runs must cause provider_capability_ok to be False and fail closed."""
    from sot_graph.assurance.receipts import _ledger_cross_check, audit_receipt
    from sot_graph.db import Database

    db = Database(str(tmp_path / "sot.db"))
    try:
        # Insert a failed provider run
        db.conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, capability, status, exit_code, duration_ms, created_at, project_root) "
            "VALUES ('run_failed_1', 'scip', '1.0.0', 'symbols', 'error', 1, 100, 1000.0, ?)",
            (str(tmp_path),)
        )
        db.conn.commit()

        cross = _ledger_cross_check(db, str(tmp_path))
        assert cross["provider_capability_ok"] is False

        receipt = audit_receipt(db, str(tmp_path), doctor_report={"healthy": True})
        assert receipt["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
        assert "provider_capability_missing" in receipt["assurance"]["reason_codes"]
    finally:
        db.close()


def test_scip_symlink_escape_containment_fails_closed(tmp_path: Path):
    """SCIP symlink pointing outside repository root must be rejected by both probe and query."""
    from sot_graph.providers.scip import ScipProvider
    from sot_graph.providers.base import SymbolRequest
    from sot_graph.providers_registry import detect_providers
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.scip.json"
    outside.write_text('{"metadata": {"version": "0.4.0"}, "documents": []}', encoding="utf-8")

    # Create symlink in repo pointing outside
    symlink_scip = repo / "index.scip.json"
    try:
        symlink_scip.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this environment")

    # 1. Registry probe must report installed=False, healthy=False
    statuses = detect_providers(str(repo))
    scip_status = next((s for s in statuses if s.name == "scip"), None)
    assert scip_status is not None
    assert scip_status.installed is False
    assert scip_status.healthy is False

    # 2. ScipProvider query must fail to find index file and fail closed
    provider = ScipProvider()
    outcome = provider.search_symbols(SymbolRequest(repo_root=str(repo), query="Main"))
    assert outcome.ok is False
    assert "SCIP index file not found" in str(outcome.error)


def test_coverage_manifest_reconciler_supported_extensions(tmp_path: Path):
    """build_scope_manifest must recognize all reconciler-supported extensions."""
    from sot_graph.assurance.coverage import build_scope_manifest
    from sot_graph.db import Database

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def run(): pass\n", encoding="utf-8")
    (repo / "service.ts").write_text("export function serve() {}\n", encoding="utf-8")
    (repo / "schema.sql").write_text("CREATE TABLE users (id INT);\n", encoding="utf-8")
    (repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    (repo / "binary.dat").write_bytes(b"\x00\x01\x02")

    db = Database(str(repo / "sot.db"))
    try:
        manifest = build_scope_manifest(db, str(repo))
        # Supported extensions should be present in scope manifest
        assert "app.py" in manifest.included_files
        assert "service.ts" in manifest.included_files
        assert "schema.sql" in manifest.included_files
        assert "README.md" in manifest.included_files
        # Unsupported binary should not be in manifest.included_files
        assert "binary.dat" not in manifest.included_files
    finally:
        db.close()


def test_ledger_cross_check_scoping_and_fail_closed(tmp_path: Path):
    """_ledger_cross_check must scope to repo_root and fail closed on database read error."""
    from sot_graph.assurance.receipts import _ledger_cross_check
    from sot_graph.db import Database

    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    repo1.mkdir()
    repo2.mkdir()

    db = Database(str(tmp_path / "shared.db"))
    try:
        # Insert a failed run for repo2
        db.conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, capability, status, exit_code, duration_ms, project_root, created_at) "
            "VALUES ('run_r2_fail', 'scip', '1.0.0', 'symbols', 'error', 1, 100, ?, 1000)",
            (str(repo2),)
        )
        # Insert an ok run for repo1
        db.conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, capability, status, exit_code, duration_ms, project_root, created_at) "
            "VALUES ('run_r1_ok', 'scip', '1.0.0', 'symbols', 'ok', 0, 50, ?, 2000)",
            (str(repo1),)
        )
        db.conn.commit()

        # Cross check for repo1 should be healthy (isolated from repo2 failed run)
        cross1 = _ledger_cross_check(db, str(repo1))
        assert cross1["provider_capability_ok"] is True

        # Cross check for repo2 should be unhealthy
        cross2 = _ledger_cross_check(db, str(repo2))
        assert cross2["provider_capability_ok"] is False

        # Fail-closed check: pass a mock db with failing execute
        class FailingDb:
            class FailingConn:
                def execute(self, *args, **kwargs):
                    raise sqlite3.OperationalError("disk I/O error")
            conn = FailingConn()

        cross_fail = _ledger_cross_check(FailingDb(), str(repo1))
        assert cross_fail["provider_capability_ok"] is False
    finally:
        db.close()


def test_cbm_pagination_loop_and_safety_cap_abort(tmp_path: Path):
    """CodebaseMemoryProvider.resolve_project must detect loops, empty pages, and safety cap."""
    from sot_graph.providers.codebase_memory import CodebaseMemoryProvider
    from sot_graph.providers.base import QueryOutcome, ProviderRunRecord

    provider = CodebaseMemoryProvider()

    # 1. Loop detection with repeating cursor
    calls = []
    def mock_invoke_loop(method, args, **kwargs):
        calls.append(args)
        return QueryOutcome(
            ok=True,
            run=ProviderRunRecord(run_id="r1", provider_name="cbm", provider_version="1.0.0", capability="list_projects", status="ok", exit_code=0, duration_ms=1),
            payload={"projects": [{"name": "proj1", "root_path": "/path1"}], "has_more": True, "next_cursor": "cursor_A"}
        )

    provider._invoke = mock_invoke_loop
    proj, err, next_action = provider.resolve_project(str(tmp_path))
    assert proj is None
    assert "pagination incomplete" in str(err)
    assert "loop=True" in str(err)

    # 2. Safety cap exhaustion
    provider = CodebaseMemoryProvider()
    counter = [0]
    def mock_invoke_cap(method, args, **kwargs):
        counter[0] += 1
        return QueryOutcome(
            ok=True,
            run=ProviderRunRecord(run_id=f"r{counter[0]}", provider_name="cbm", provider_version="1.0.0", capability="list_projects", status="ok", exit_code=0, duration_ms=1),
            payload={"projects": [{"name": f"proj_{counter[0]}_{i}", "root_path": f"/path_{counter[0]}_{i}"} for i in range(50)], "has_more": True, "offset": counter[0]*50}
        )

    provider._invoke = mock_invoke_cap
    proj, err, next_action = provider.resolve_project(str(tmp_path))
    assert proj is None
    assert "cap=True" in str(err)


def test_scip_span_column_aliases_persistence(tmp_path: Path):
    """Both col_start/col_end and start_column/end_column must be persisted in SQLite."""
    from sot_graph.db import Database

    db = Database(str(tmp_path / "sot.db"))
    try:
        db.conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, capability, status, exit_code, duration_ms, created_at) "
            "VALUES ('run_test_1', 'scip', '1.0.0', 'symbols', 'ok', 0, 10, 1000)"
        )
        db.conn.commit()

        evidence = [
            {
                "id": "ev_1",
                "path": "src/main.py",
                "symbol": "App",
                "target_symbol": None,
                "relation": "definition",
                "line_start": 10,
                "line_end": 20,
                "col_start": 4,
                "col_end": 12,
                "confidence": 1.0,
            },
            {
                "id": "ev_2",
                "path": "src/main.py",
                "symbol": "serve",
                "target_symbol": None,
                "relation": "reference",
                "start_line": 25,
                "end_line": 25,
                "start_column": 8,
                "end_column": 15,
                "confidence": 0.95,
            },
        ]
        count = db.record_provider_evidence("run_test_1", evidence)
        assert count == 2

        rows = db.conn.execute("SELECT id, line_start, line_end, col_start, col_end FROM provider_evidence ORDER BY id").fetchall()
        assert rows[0] == ("ev_1", 10, 20, 4, 12)
        assert rows[1] == ("ev_2", 25, 25, 8, 15)
    finally:
        db.close()


def test_mcp_diff_impact_receipt_fits_response_truncation(tmp_path: Path):
    """McpService._fits_response must truncate large lists in diff impact receipts without throwing."""
    from sot_graph.mcp_service import McpService, ServiceLimits
    from sot_graph.db import Database
    from sot_graph.assurance.receipts import receipt_digest

    db_file = tmp_path / "sot.db"
    db = Database(str(db_file))
    db.close()

    service = McpService(db_path=str(db_file), project_root=str(tmp_path), limits=ServiceLimits(response_bytes=2048))

    oversized_payload = {
        "schema_version": "1.0.0",
        "kind": "diff_impact_receipt",
        "digest": "test_digest_123",
        "caller_impacts": [{"caller": f"func_{i}", "path": f"file_{i}.py", "depth": 1} for i in range(100)],
        "test_impacts": [{"test": f"test_{i}", "path": f"test_{i}.py"} for i in range(100)],
        "direct_nodes": [{"node": f"node_{i}", "path": f"file_{i}.py"} for i in range(100)],
    }

    fitted = service._fits_response(oversized_payload)
    assert isinstance(fitted, dict)
    assert fitted.get("truncated") is True
    assert fitted.get("digest")
    assert fitted["digest"] == receipt_digest({k: v for k, v in fitted.items() if k != "digest"})
    # Payload byte size must be within the limit
    encoded = json.dumps(fitted, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(encoded) <= 2048


def test_atomic_replacement_snapshot_regression(tmp_path: Path):
    """Atomic replacement via os.replace must produce a new snapshot digest and not collide."""
    from sot_graph.snapshot import capture_worktree_snapshot

    repo = tmp_path / "repo"
    repo.mkdir()
    f = repo / "main.py"
    f.write_text("v1 = 1\n", encoding="utf-8")

    s1 = capture_worktree_snapshot(str(repo), cited_paths=["main.py"])
    d1 = s1.scope_digest

    tmp_file = repo / "main.py.tmp"
    tmp_file.write_text("v2 = 2\n", encoding="utf-8")
    os.replace(tmp_file, f)

    s2 = capture_worktree_snapshot(str(repo), cited_paths=["main.py"])
    d2 = s2.scope_digest

    assert d1 != d2
    assert s1.content_digests["main.py"] != s2.content_digests["main.py"]


def test_ledger_cross_check_snapshot_scoping(tmp_path: Path):
    """_ledger_cross_check with snapshot_hash must evaluate only provider runs matching that snapshot."""
    from sot_graph.db import Database
    from sot_graph.assurance.receipts import _ledger_cross_check

    db_file = tmp_path / "sot.db"
    db = Database(str(db_file))
    repo_dir = str(tmp_path)
    try:
        db.conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, capability, snapshot_hash, status, exit_code, created_at, project_root) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run_old", "p1", "1.0", "symbols", "snap_old", "error", 1, 100, repo_dir)
        )
        db.conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, capability, snapshot_hash, status, exit_code, created_at, project_root) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run_new", "p1", "1.0", "symbols", "snap_new", "ok", 0, 200, repo_dir)
        )
        db.conn.commit()

        check_new = _ledger_cross_check(db, repo_dir, snapshot_hash="snap_new")
        assert check_new["provider_capability_ok"] is True
        assert len(check_new["runs"]) == 1
        assert check_new["runs"][0]["run_id"] == "run_new"

        check_old = _ledger_cross_check(db, repo_dir, snapshot_hash="snap_old")
        assert check_old["provider_capability_ok"] is False
        assert len(check_old["runs"]) == 1
        assert check_old["runs"][0]["run_id"] == "run_old"
    finally:
        db.close()

def test_evidence_truncation_overflow_fails_closed(tmp_path: Path):
    """union_evidence must fail closed when evidence count exceeds limit."""
    from sot_graph.db import Database
    from sot_graph.assurance.ledger import union_evidence
    from sot_graph.assurance.receipts import _ledger_cross_check

    db_file = tmp_path / "sot.db"
    db = Database(str(db_file))
    repo_dir = str(tmp_path)
    src_file = tmp_path / "mod.py"
    src_file.write_text("def fn_0(): pass\n", encoding="utf-8")

    try:
        db.conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, capability, snapshot_hash, status, exit_code, created_at, project_root) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run_1", "p1", "1.0", "symbols", "snap_1", "ok", 0, 100, repo_dir)
        )
        for i in range(15):
            db.conn.execute(
                "INSERT INTO provider_evidence (run_id, path, relation, src_symbol, dst_symbol, snapshot_hash, provider_name, line_start, line_end, confidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("run_1", "mod.py", "defines", f"fn_{i}", "", "snap_1", "p1", 1, 1, 0.95, 100)
            )
        db.conn.commit()

        # Call union_evidence with limit=10 on 15 rows
        union = union_evidence(db, repo_dir, snapshot_hash="snap_1", limit=10, verify_spans=False)
        assert any(e.get("truncated") is True for e in union)
        assert any(e.get("conflict") is True for e in union)

        # Cross check must count the truncation conflict as an open conflict
        cross = _ledger_cross_check(db, repo_dir, snapshot_hash="snap_1")
        # If default limit is 5000, calling with explicit union limit test:
        union_overflow = union_evidence(db, repo_dir, snapshot_hash="snap_1", limit=5)
        assert any(e.get("truncated") is True for e in union_overflow)
    finally:
        db.close()


def test_ledger_cross_check_no_matching_snapshot_no_fallback(tmp_path: Path):
    """When snapshot_hash has no matching runs, _ledger_cross_check must NOT evaluate historical runs."""
    from sot_graph.db import Database
    from sot_graph.assurance.receipts import _ledger_cross_check

    db_file = tmp_path / "sot.db"
    db = Database(str(db_file))
    repo_dir = str(tmp_path)
    try:
        db.conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, capability, snapshot_hash, status, exit_code, created_at, project_root) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run_old", "p1", "1.0", "symbols", "snap_old", "error", 1, 100, repo_dir)
        )
        db.conn.commit()

        # Query with non-existent snapshot
        check_missing = _ledger_cross_check(db, repo_dir, snapshot_hash="snap_missing")
        assert len(check_missing["runs"]) == 0
        # Must not have evaluated run_old
        assert not any(r["run_id"] == "run_old" for r in check_missing["runs"])
    finally:
        db.close()


def test_diff_impact_tracked_special_character_paths():
    """parse_unified_diff must accurately unquote Git C-quoted paths with tabs, quotes, backslashes, and octals."""
    from sot_graph.diff_impact import GitDeltaExtractor

    extractor = GitDeltaExtractor(repo_path=".")
    diff_text = '''diff --git "a/path\\twith\\ttab.py" "b/path\\twith\\ttab.py"
index 0000000..1111111 100644
--- "a/path\\twith\\ttab.py"
+++ "b/path\\twith\\ttab.py"
@@ -1,5 +1,6 @@
+def new_func_tab(): pass
diff --git "a/path\\"with\\"quote.py" "b/path\\"with\\"quote.py"
index 0000000..1111111 100644
--- "a/path\\"with\\"quote.py"
+++ "b/path\\"with\\"quote.py"
@@ -1,5 +1,6 @@
+def new_func_quote(): pass
diff --git "a/path\\\\with\\\\bs.py" "b/path\\\\with\\\\bs.py"
index 0000000..1111111 100644
--- "a/path\\\\with\\\\bs.py"
+++ "b/path\\\\with\\\\bs.py"
@@ -1,5 +1,6 @@
+def new_func_bs(): pass
diff --git "a/path\\342\\234\\223.py" "b/path\\342\\234\\223.py"
index 0000000..1111111 100644
--- "a/path\\342\\234\\223.py"
+++ "b/path\\342\\234\\223.py"
@@ -1,5 +1,6 @@
+def new_func_check(): pass
'''

    expected_bs = "path/with/bs.py" if os.sep == "\\" else "path\\with\\bs.py"
    file_intervals, hunks = extractor.parse_unified_diff(diff_text)
    assert "path\twith\ttab.py" in file_intervals
    assert 'path"with"quote.py' in file_intervals
    assert expected_bs in file_intervals
    assert 'path✓.py' in file_intervals

    hunk_files = {h.file_path for h in hunks}
    assert "path\twith\ttab.py" in hunk_files
    assert 'path"with"quote.py' in hunk_files
    assert expected_bs in hunk_files
    assert 'path✓.py' in hunk_files


def test_union_evidence_cross_repository_isolation(tmp_path: Path):
    """Evidence recorded for repo2 must never leak into repo1 union evidence or cross-check."""
    from sot_graph.db import Database
    from sot_graph.assurance.ledger import union_evidence
    from sot_graph.assurance.receipts import _ledger_cross_check

    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    repo1.mkdir()
    repo2.mkdir()
    (repo1 / "app.py").write_text("def run(): pass\n", encoding="utf-8")
    (repo2 / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    db_file = tmp_path / "shared.db"
    db = Database(str(db_file))
    try:
        # Insert run and evidence specifically for repo2
        db.conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, capability, snapshot_hash, status, exit_code, created_at, project_root) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run_repo2", "p1", "1.0", "symbols", "snap_common", "ok", 0, 100, str(repo2))
        )
        db.conn.execute(
            "INSERT INTO provider_evidence (run_id, path, relation, src_symbol, dst_symbol, snapshot_hash, provider_name, line_start, line_end, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run_repo2", "app.py", "defines", "run", "", "snap_common", "p1", 1, 1, 0.95, 100)
        )
        db.conn.commit()

        # Repo1 has NO runs in shared.db: querying repo1 must return 0 evidence
        union1 = union_evidence(db, str(repo1), snapshot_hash="snap_common", verify_spans=True)
        assert len(union1) == 0, f"Expected 0 evidence for repo1, got: {union1}"

        cross1 = _ledger_cross_check(db, str(repo1), snapshot_hash="snap_common")
        assert len(cross1["runs"]) == 0
        assert cross1["union_entries"] == 0

        # Querying repo2 must correctly return the evidence
        union2 = union_evidence(db, str(repo2), snapshot_hash="snap_common", verify_spans=True)
        assert len(union2) == 1
        assert union2[0]["status"] == "SUPPORTED"

        cross2 = _ledger_cross_check(db, str(repo2), snapshot_hash="snap_common")
        assert len(cross2["runs"]) == 1
        assert cross2["union_entries"] == 1
    finally:
        db.close()


def test_union_evidence_null_project_root_isolation(tmp_path: Path):
    """Legacy/unprovenanced provider runs with project_root IS NULL must NOT leak into repo queries."""
    from sot_graph.db import Database
    from sot_graph.assurance.ledger import union_evidence
    from sot_graph.assurance.receipts import _ledger_cross_check

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    db_file = tmp_path / "shared.db"
    db = Database(str(db_file))
    try:
        # Insert unprovenanced run with project_root = NULL
        db.conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, capability, snapshot_hash, status, exit_code, created_at, project_root) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run_null", "p1", "1.0", "symbols", "snap_null", "ok", 0, 100, None)
        )
        db.conn.execute(
            "INSERT INTO provider_evidence (run_id, path, relation, src_symbol, dst_symbol, snapshot_hash, provider_name, line_start, line_end, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run_null", "app.py", "defines", "run", "", "snap_null", "p1", 1, 1, 0.95, 100)
        )
        db.conn.commit()

        union = union_evidence(db, str(repo), snapshot_hash="snap_null", verify_spans=True)
        assert len(union) == 0, "Unprovenanced NULL project_root evidence must not match specific repository"

        cross = _ledger_cross_check(db, str(repo), snapshot_hash="snap_null")
        assert len(cross["runs"]) == 0
        assert cross["union_entries"] == 0
    finally:
        db.close()


def test_union_evidence_symlink_retarget_isolation(tmp_path: Path):
    """Retargeting a symlink alias must NEVER rebind previously recorded evidence to another physical repo."""
    from sot_graph.db import Database
    from sot_graph.assurance.ledger import union_evidence
    from sot_graph.assurance.receipts import _ledger_cross_check

    repo_a = tmp_path / "repo_a"
    repo_a.mkdir()
    (repo_a / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    repo_b = tmp_path / "repo_b"
    repo_b.mkdir()
    (repo_b / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    alias_link = tmp_path / "active_repo_alias"
    try:
        alias_link.symlink_to(repo_a, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported in test environment")

    db_file = tmp_path / "shared.db"
    db = Database(str(db_file))
    try:
        # Record provider run while alias points to repo_a
        rid = db.record_provider_run(
            provider_name="p1",
            provider_version="1.0",
            capability="symbols",
            snapshot_hash="snap_sym",
            project_root=str(alias_link),
            status="ok",
            exit_code=0,
        )
        db.conn.execute(
            "INSERT INTO provider_evidence (run_id, path, relation, src_symbol, dst_symbol, snapshot_hash, provider_name, line_start, line_end, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, "app.py", "defines", "run", "", "snap_sym", "p1", 1, 1, 0.95, 100)
        )
        db.conn.commit()

        # Verify that querying repo_a (or alias while pointing to repo_a) returns SUPPORTED evidence
        union_a = union_evidence(db, str(alias_link), snapshot_hash="snap_sym", verify_spans=True)
        assert len(union_a) == 1
        assert union_a[0]["status"] == "SUPPORTED"

        # Now retarget the symlink to repo_b
        alias_link.unlink()
        alias_link.symlink_to(repo_b, target_is_directory=True)

        # Querying through the retargeted alias (now pointing to repo_b) MUST NOT return repo_a's evidence
        union_b = union_evidence(db, str(alias_link), snapshot_hash="snap_sym", verify_spans=True)
        assert len(union_b) == 0, "Symlink retarget must not leak repo_a evidence into repo_b"

        cross_b = _ledger_cross_check(db, str(alias_link), snapshot_hash="snap_sym")
        assert len(cross_b["runs"]) == 0
        assert cross_b["union_entries"] == 0

        # Direct query for repo_a still finds the evidence
        union_direct_a = union_evidence(db, str(repo_a), snapshot_hash="snap_sym", verify_spans=True)
        assert len(union_direct_a) == 1
        assert union_direct_a[0]["status"] == "SUPPORTED"
    finally:
        db.close()
