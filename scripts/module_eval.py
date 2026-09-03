#!/usr/bin/env python3
"""Module-scope evaluation harness for sot-graph.

Runs per-scope quality gates plus behavioral bug probes so fixes can be
verified per functional module instead of on the whole tree at once.

Scopes (functional module groups):
  core-storage    db, locking, snapshot, evidence, envelope, config, proc,
                  modutil, tokenizer, vector
  extraction      extractor, ts_extract, parser_outcome, ignore, providers/,
                  providers_registry, importer/scip
  sync-healing    reconciler, verifier, watcher
  query-analytics pack, repo_map, trace, diff_impact, solution, analytics/
  surfaces        cli, mcp_server, mcp_service, adapters/, export/
  assurance       assurance/

Gates per scope: ruff (file-attributed), pyright (file-attributed),
pytest (scope-mapped test files).  Probes are small, deterministic,
self-contained detectors for audited defects: probe FAILING means the bug
is still present.  Exit codes: 0 = all selected gates pass (probes
informational), 1 = gate failure, 2 = --strict-probes and a probe detects
a bug or a probe/gate crashed (fail-closed: an unrunnable check can never
prove absence of its bug).
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

SRC = "src/sot_graph"

SCOPES: Dict[str, Dict[str, List[str]]] = {
    "core-storage": {
        "files": [
            f"{SRC}/db.py", f"{SRC}/locking.py", f"{SRC}/snapshot.py",
            f"{SRC}/evidence.py", f"{SRC}/envelope.py", f"{SRC}/config.py",
            f"{SRC}/proc.py", f"{SRC}/modutil.py", f"{SRC}/tokenizer.py",
            f"{SRC}/vector.py",
        ],
        "tests": [
            "test_storage_integrity.py", "test_config_loader.py",
            "test_proc_runner.py", "test_proc_process_group.py",
            "test_proc_streaming_cap.py", "test_proc_windows_job.py", "test_vector.py",
            "test_p9_chaos_migration.py", "test_v2_upgrade.py",
            "test_maintenance.py", "test_optimizations.py",
            "test_core_safety_fixes.py",
        ],
    },
    "extraction": {
        "files": [
            f"{SRC}/extractor.py", f"{SRC}/ts_extract.py",
            f"{SRC}/parser_outcome.py", f"{SRC}/ignore.py",
            f"{SRC}/providers_registry.py", f"{SRC}/importer/scip.py",
            f"{SRC}/providers/",
        ],
        "tests": [
            "test_group1_extractors.py", "test_group2_extractors.py",
            "test_group3_extractors.py", "test_c_cpp_extractor.py",
            "test_dart_extractor.py", "test_java_extractor.py",
            "test_php_extractor.py", "test_treesitter.py",
            "test_multilang.py", "test_python_resolver.py",
            "test_python_scope_extended.py",
            "test_python_semantic_resolver.py",
            "test_import_resolution.py", "test_ignore.py",
            "test_cbm_adapter.py", "test_cbm_golden.py",
            "test_cbm_normalization.py", "test_cbm_snapshot_p2.py",
            "test_cbm_verification.py", "test_scip_provider.py",
            "test_scip_truncation.py",
            "test_phase1_scip_and_schema_v5.py", "test_p3_scip_binding.py",
            "test_provider_contract.py", "test_p3_plugin_contract.py",
            "test_providers_registry.py", "test_p3_builtin_recall.py",
            "test_precision_and_metamorphic.py", "test_edge_lifecycle.py",
        ],
    },
    "sync-healing": {
        "files": [f"{SRC}/reconciler.py", f"{SRC}/verifier.py", f"{SRC}/watcher.py"],
        "tests": [
            "test_reconcile_audit_receipts.py", "test_jit_reconcile.py",
            "test_verifier.py", "test_watcher_daemon.py",
            "test_parallel_reconciler.py", "test_force_reindex.py",
            "test_p0_freshness_semantics.py", "test_snapshot_binding.py",
            "test_snapshot_content_binding.py",
        ],
    },
    "query-analytics": {
        "files": [
            f"{SRC}/pack.py", f"{SRC}/repo_map.py", f"{SRC}/trace.py",
            f"{SRC}/diff_impact.py", f"{SRC}/solution.py", f"{SRC}/analytics/",
        ],
        "tests": [
            "test_diff_impact.py", "test_analytics.py", "test_bundle.py",
            "test_repo_map.py", "test_solution_trace.py",
            "test_sprint4_compass_and_pack.py", "test_navigation.py",
            "test_oracle_selfcheck.py", "test_p4_identity.py",
        ],
    },
    "surfaces": {
        "files": [
            f"{SRC}/cli.py", f"{SRC}/mcp_server.py", f"{SRC}/mcp_service.py",
            f"{SRC}/adapters/", f"{SRC}/export/",
        ],
        "tests": [
            "test_cli_smoke.py", "test_cli_provider_wiring.py", "test_mcp.py",
            "test_mcp_modern.py", "test_mcp_receipt_tools.py",
            "test_adapters.py", "test_p3_adapters.py", "test_export.py",
            "test_p4_ranking.py", "test_p4_search_safety.py",
            "test_p4_quality_gate.py", "test_phase6.py",
            "test_adapter_docs_consistency.py",
        ],
    },
    "assurance": {
        "files": [f"{SRC}/assurance/"],
        "tests": [
            "test_assurance_state.py", "test_p2_orchestrator.py",
            "test_p5_coverage_verification.py", "test_p6_ledger.py",
            "test_p7_receipts.py", "test_p8_omp_integration.py",
            "test_omp_integration.py", "test_coverage_manifest.py",
            "test_trust_chain_hardening.py", "test_trust_v2_evidence.py",
            "test_truthfulness.py", "test_p1_snapshot_trust.py",
            "test_hardening_fixes.py",
        ],
    },
}


# --------------------------------------------------------------------------
# Bug probes.  Each returns (status, detail) where status is "BUG_PRESENT",
# "OK" (bug fixed / absent) or "PROBE_ERROR" (probe itself could not run).
# --------------------------------------------------------------------------

def _probe_journal_like_wildcard() -> Tuple[str, str]:
    """P1 db.py:676 — unescaped LIKE fallback binds the wrong journal row."""
    from sot_graph.db import Database
    with tempfile.TemporaryDirectory() as td:
        db = Database(os.path.join(td, "t.db"))
        db.conn.execute(
            "INSERT INTO file_journal (path, sha256, size, mtime_ms, reconciled_at) "
            "VALUES ('repo/src/pkg/utils.py', 'x', 1, 1, 1)"
        )
        db.conn.commit()
        # real-world shape: journal keeps abs/aliased spelling, caller asks for
        # the root-relative one; '_' in the queried name is a LIKE wildcard
        row = db.get_file_journal("src/pkg/util_.py")
        db.close()
        if row is not None:
            return "BUG_PRESENT", (
                "get_file_journal('src/pkg/util_.py') returned the journal row "
                "of 'repo/src/pkg/utils.py' via the unescaped LIKE fallback — "
                "wrong sha256 can drive false unchanged/STALE verdicts"
            )
        return "OK", "wildcard path did not match a different journal row"


def _probe_manifest_digest_collapse() -> Tuple[str, str]:
    """P1 envelope.py — storage errors must NOT collapse to one constant.

    Fail-open contract bug: every erroring state (closed connection,
    missing schema, transient lock) used to return the SAME
    'sha256:unknown' digest, so snapshot comparisons treated distinct
    broken states as equal. Fixed contract: errors either raise
    (fail-closed) or produce state-distinct values — never one constant.
    """
    from sot_graph.envelope import compute_manifest_digest
    with tempfile.TemporaryDirectory() as td:
        outcomes = []
        # state A: connection closed before digesting
        conn_a = sqlite3.connect(os.path.join(td, "a.db"))
        conn_a.execute(
            "CREATE TABLE file_journal (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, "
            "size INTEGER NOT NULL, mtime_ms INTEGER NOT NULL, generation INTEGER, "
            "reconciled_at INTEGER NOT NULL, parser_outcome TEXT, parser_error TEXT)"
        )
        conn_a.execute(
            "INSERT INTO file_journal (path, sha256, size, mtime_ms, reconciled_at) "
            "VALUES ('one.py', 'a', 1, 1, 1)"
        )
        conn_a.commit()
        conn_a.close()
        try:
            outcomes.append(("closed-conn", compute_manifest_digest(conn_a)))
        except Exception as exc:
            outcomes.append(("closed-conn", f"<raised:{type(exc).__name__}>"))
        # state B: different DB, schema missing entirely
        conn_b = sqlite3.connect(os.path.join(td, "b.db"))
        try:
            outcomes.append(("no-schema", compute_manifest_digest(conn_b)))
        except Exception as exc:
            outcomes.append(("no-schema", f"<raised:{type(exc).__name__}>"))
        finally:
            conn_b.close()
        digests = {d for _label, d in outcomes}
        if "sha256:unknown" in digests or len(digests) == 1:
            return "BUG_PRESENT", (
                f"distinct failure states share one digest {sorted(digests)} — "
                "fail-open constant still present"
            )
        return "OK", f"fail-closed, states distinguishable: {sorted(digests)}"


def _probe_nested_gitignore() -> Tuple[str, str]:
    """P2 ignore.py:101,184 — scoped prefix over-match + nested files unloaded."""
    from sot_graph.ignore import GitIgnoreMatcher
    with tempfile.TemporaryDirectory() as td:
        sub = Path(td, "sub", "dir")
        sub.mkdir(parents=True)
        Path(td, "sub", ".gitignore").write_text("nested_secret.txt\n")
        m = GitIgnoreMatcher(td)
        m.add_pattern("secret/", base_dir="sub/dir")
        bugs = []
        if m.is_ignored(os.path.join(td, "sub", "diraneous", "x.txt")):
            bugs.append(
                "rule scoped to 'sub/dir' also matches 'sub/diraneous/…' "
                "(startswith prefix match)"
            )
        if not m.is_ignored(os.path.join(td, "sub", "nested_secret.txt")):
            bugs.append("nested sub/.gitignore rules are never loaded")
        if bugs:
            return "BUG_PRESENT", "; ".join(bugs)
        return "OK", "scoped rules anchored correctly and nested files loaded"


def _probe_solution_fabricated_template() -> Tuple[str, str]:
    """P1 solution.py:426 — fabricated 10-step domain template for any symbol."""
    from sot_graph.db import Database
    from sot_graph.solution import extract_execution_steps
    with tempfile.TemporaryDirectory() as td:
        db = Database(os.path.join(td, "t.db"))
        try:
            res = extract_execution_steps(db, "GhostService.nonexistent")
        except Exception as exc:  # probe must not crash the harness
            db.close()
            return "PROBE_ERROR", f"extract_execution_steps raised {exc!r}"
        db.close()
        text = json.dumps(res, ensure_ascii=False, default=str)
        if "POSTPAID_LIMIT_EXCEEDED" in text or "msisdn" in text:
            return "BUG_PRESENT", (
                "unknown symbol is answered with the hardcoded Unipay 10-step "
                "payment template instead of a NOT_FOUND result"
            )
        return "OK", "no fabricated template for unknown symbol"


def _probe_repo_map_dead_helper() -> Tuple[str, str]:
    """P2 repo_map.py:133 — _estimate_tokens references undefined constant."""
    from sot_graph import repo_map
    try:
        repo_map._estimate_tokens("x" * 100)
    except NameError as exc:
        return "BUG_PRESENT", f"NameError: {exc}"
    return "OK", "_estimate_tokens resolves its constant"


def _probe_cli_hybrid_scope_ignored() -> Tuple[str, str]:
    """P1 cli.py:210 — `sot search --hybrid` silently drops --scope."""
    from sot_graph.cli import build_parser
    from sot_graph.vector import hybrid_search
    parser = build_parser()
    args = parser.parse_args(["search", "anything", "--hybrid", "--scope", "pkg"])
    has_scope = bool(getattr(args, "scope", None))
    sig = inspect.signature(hybrid_search)
    accepts_scope = "scope" in sig.parameters
    if has_scope and not accepts_scope:
        return "BUG_PRESENT", (
            "parser accepts --scope together with --hybrid but hybrid_search() "
            "has no scope parameter — scope is silently ignored"
        )
    return "OK", "hybrid search honors scope (or rejects the combination)"


def _probe_coverage_mtime_false_stale() -> Tuple[str, str]:
    """P1 assurance/coverage.py:229 — mtime term reintroduces false STALE."""
    from sot_graph.assurance.coverage import CoverageState, repo_coverage
    from sot_graph.db import Database
    with tempfile.TemporaryDirectory() as td:
        f = Path(td, "app.py")
        content = b"def main():\n    pass\n"
        f.write_bytes(content)
        sha = hashlib.sha256(content).hexdigest()
        size = len(content)
        mtime_ms = int(f.stat().st_mtime * 1000)
        db = Database(os.path.join(td, "t.db"))
        db.conn.execute(
            "INSERT INTO file_journal (path, sha256, size, mtime_ms, reconciled_at, "
            "parser_outcome) VALUES ('app.py', ?, ?, ?, ?, 'OK')",
            (sha, size, mtime_ms - 120_000, 1),  # identical content, old mtime
        )
        db.conn.commit()
        report = repo_coverage(db, td)
        db.close()
        state = next(
            (fc.state for fc in report.files if fc.path == "app.py"), None
        )
        # sha+size identical => clean per db.stale_journal_files semantics
        if state == CoverageState.STALE:
            return "BUG_PRESENT", (
                "app.py has identical sha256+size but mtime drift >2s marks it "
                "STALE — contradicts the sha-only staleness fixed in db.py "
                "(commit 7dd9e54); receipts get double-teamed by two verdicts"
            )
        return "OK", f"state={state} (sha-based staleness consistent)"


def _probe_tests_to_run_none() -> Tuple[str, str]:
    """P1 receipts.py:563 — tests_to_run must read the real field 'path'.

    Wiring probe: TestImpact's only path-ish field is ``path`` (see
    diff_impact.py dataclass); the receipt expression must read it, not a
    nonexistent ``test_file`` (which renders as literal 'None').
    """
    import sot_graph.assurance.receipts as receipts_mod
    from sot_graph.diff_impact import TestImpact
    fields = {f for f in TestImpact.__dataclass_fields__}
    source = inspect.getsource(receipts_mod)
    uses_test_file = "test_file" in source
    reads_path = 't.get("path")' in source or "getattr(t, \"path\"" in source
    if "test_file" not in fields and (uses_test_file or not reads_path):
        return "BUG_PRESENT", (
            "receipts.py still references the nonexistent 'test_file' field "
            f"(TestImpact fields: {sorted(fields)}) — tests_to_run renders "
            "literal 'None' instead of real test paths"
        )
    return "OK", "tests_to_run reads TestImpact.path; no 'test_file' reference"


def _probe_polling_deferred_drop() -> Tuple[str, str]:
    """P1 watcher.py — polling backend drops LockBusy-deferred paths.

    The polling loop advances its disk-state baseline (``current = fresh``)
    BEFORE reconciling, so a path deferred by LockBusy can never re-enter
    the changed set via diffing — its bytes do not change a second time.
    Without an explicit carry-over into the next cycle (the watchfiles
    backend's ``pending`` contract), a write lock held longer than the
    0.2s in-loop retry window (CLI migration, provider sync) voids the
    event until the file happens to change again.
    """
    import threading

    from sot_graph import watcher as watcher_mod
    from sot_graph.locking import LockBusy

    class _FakeReconciler:
        def __init__(self, app: str) -> None:
            self.app = app
            self.locked_until = time.monotonic() + 0.6  # > 0.2s retry window
            self.published: List[str] = []

        def scan(self, _paths=None):  # polling snapshot() feed
            return [self.app]

        def reconcile_path(self, path: str) -> str:
            if time.monotonic() < self.locked_until:
                raise LockBusy("simulated migration lock")
            self.published.append(path)
            return "indexed"

    with tempfile.TemporaryDirectory() as td:
        app = Path(td, "app.py")
        app.write_text("def f():\n    return 1\n", encoding="utf-8")
        fake = _FakeReconciler(str(app))
        stop = threading.Event()
        thread = threading.Thread(
            target=watcher_mod._run_polling,
            args=(fake, td, 20, lambda message: None),
            kwargs={"interval_ms": 40, "stop_event": stop},
            daemon=True,
        )
        thread.start()
        # Touch the file AFTER the loop's initial snapshot so the next
        # diff actually raises a change event.
        time.sleep(0.15)
        app.write_text("def f():\n    return 2\n", encoding="utf-8")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not fake.published:
            time.sleep(0.05)
        stop.set()
        thread.join(timeout=2.0)
        if not fake.published:
            return "BUG_PRESENT", (
                "app.py deferred by LockBusy (lock held 0.6s > 0.2s retry "
                "window) was never re-enqueued — polling advances its "
                "baseline past the event and the DB stays stale until the "
                "next disk change"
            )
        return "OK", "LockBusy-deferred path re-published via cross-cycle carry-over"


def _probe_watchfiles_pending_carryover() -> Tuple[str, str]:
    """P1 watcher.py — watchfiles backend must carry pending across batches.

    _reconcile_quietly's contract: LockBusy paths are DEFERRED, never
    dropped, and must be re-enqueued into the next debounce batch. The
    watchfiles backend honors it by unioning ``pending`` into the next
    batch and reassigning ``pending`` from the deferred return — this
    probe guards both halves of that wiring against regression.
    """
    import sot_graph.watcher as watcher_mod
    src = inspect.getsource(watcher_mod._run_watchfiles)
    unions = "paths |= pending" in src
    reassigns = "_published, pending = _reconcile_quietly" in src
    if not (unions and reassigns):
        return "BUG_PRESENT", (
            f"watchfiles backend lost the LockBusy pending carry-over "
            f"(union present: {unions}, reassign present: {reassigns}) — "
            "deferred events would drop at the next batch"
        )
    return "OK", "pending is unioned into the next batch and fed from deferred"


def _probe_watcher_unsupported_churn() -> Tuple[str, str]:
    """P2 reconciler.py:508 — watcher-fed binaries must be excluded, not churned.

    Watcher events can name unsupported/binary files (logos, data blobs).
    Without the ``_supported()`` gate in reconcile_path they get indexed
    into FTS (mojibake previews), then the next full reconcile's deletion
    sweep removes them, then the next touch re-indexes them — an
    add/delete churn cycle per event.
    """
    from sot_graph.db import Database
    from sot_graph.reconciler import Reconciler
    from sot_graph.watcher import _reconcile_quietly

    with tempfile.TemporaryDirectory() as td:
        logo = Path(td, "logo.png")
        logo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        db = Database(os.path.join(td, "t.db"))
        try:
            rec = Reconciler(db, td)
            published, _deferred = _reconcile_quietly(rec, {str(logo)})
            journaled = db.get_file_journal(str(logo)) is not None
            rec.reconcile(workers=1)  # full pass must not sweep/re-add either
            journaled_after = db.get_file_journal(str(logo)) is not None
        finally:
            db.close()
        if published > 0 or journaled or journaled_after:
            return "BUG_PRESENT", (
                f"logo.png published={published}, journal row before/after "
                f"full reconcile: {journaled}/{journaled_after} — unsupported "
                "binary rides the index/delete churn cycle"
            )
        return "OK", "unsupported binary excluded at the gate; never journaled"


def _probe_jit_fresh_despite_failed_reconcile() -> Tuple[str, str]:
    """P1 verifier.py — jit FRESH must track the reconcile outcome.

    verify_evidence(jit_reconcile=True) used to stamp FRESH right after
    invoking Reconciler, whatever the reconcile achieved: a conflicted or
    failed commit laundered into a FRESH verdict on content that was
    never re-indexed. FRESH is only honest when nothing failed AND the
    post-reconcile journal sha matches the disk hash.
    """
    from types import SimpleNamespace

    import sot_graph.reconciler as reconciler_mod
    from sot_graph.db import Database
    from sot_graph.reconciler import Reconciler
    from sot_graph.verifier import FreshnessStatus, TrustVerifier, tokenize

    class _FailingReconciler:
        def __init__(self, db, root):  # noqa: ARG002 (verifier wiring)
            pass

        def reconcile(self, paths=None, workers=1):  # noqa: ARG002
            return SimpleNamespace(failed=1)

    with tempfile.TemporaryDirectory() as td:
        svc = Path(td, "svc.py")
        svc.write_text("def alpha():\n    return 42\n", encoding="utf-8")
        db = Database(os.path.join(td, "t.db"))
        try:
            Reconciler(db, td).reconcile(workers=1)
            node = db.get_node_by_symbol("svc.alpha")
            if node is None:
                return "PROBE_ERROR", "fixture broken: svc.alpha not indexed"
            svc.write_text("def beta():\n    return 100\n", encoding="utf-8")
            cand = {
                "id": node["id"], "path": "svc.py", "symbol": "svc.alpha",
                "line_start": 1, "kind": "function",
            }
            real = reconciler_mod.Reconciler
            reconciler_mod.Reconciler = _FailingReconciler
            try:
                evidence = TrustVerifier.verify_evidence(
                    cand, tokenize("alpha"), td, db=db,
                    auto_heal=False, jit_reconcile=True,
                )
            finally:
                reconciler_mod.Reconciler = real
        finally:
            db.close()
        if evidence.freshness == FreshnessStatus.FRESH:
            return "BUG_PRESENT", (
                "reconcile reported failed=1 and the journal sha predates "
                "the disk edit, yet jit_reconcile returned FRESH — failed "
                "commits must not be laundered into FRESH verdicts"
            )
        return "OK", f"freshness={evidence.freshness} gated on reconcile outcome"


PROBES: Dict[str, List[Tuple[str, str, Callable[[], Tuple[str, str]]]]] = {
    "core-storage": [
        ("journal-like-wildcard", "P1 db.py:676", _probe_journal_like_wildcard),
        ("manifest-digest-collapse", "P1 envelope.py:29", _probe_manifest_digest_collapse),
    ],
    "extraction": [
        ("nested-gitignore", "P2 ignore.py:101,184", _probe_nested_gitignore),
    ],
    "query-analytics": [
        ("solution-fabricated-template", "P1 solution.py:426", _probe_solution_fabricated_template),
        ("repo-map-dead-helper", "P2 repo_map.py:133", _probe_repo_map_dead_helper),
    ],
    "surfaces": [
        ("cli-hybrid-scope-ignored", "P1 cli.py:210", _probe_cli_hybrid_scope_ignored),
    ],
    "assurance": [
        ("coverage-mtime-false-stale", "P1 coverage.py:229", _probe_coverage_mtime_false_stale),
        ("tests-to-run-none", "P1 receipts.py:563", _probe_tests_to_run_none),
    ],
    "sync-healing": [
        ("polling-deferred-drop", "P1 watcher.py:154", _probe_polling_deferred_drop),
        ("watchfiles-pending-carryover", "P1 watcher.py:76", _probe_watchfiles_pending_carryover),
        ("watcher-unsupported-churn", "P2 reconciler.py:508", _probe_watcher_unsupported_churn),
        ("jit-fresh-despite-failed-reconcile", "P1 verifier.py:416", _probe_jit_fresh_despite_failed_reconcile),
    ],
}


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------

@dataclass
class ScopeResult:
    name: str
    ruff: Optional[Dict[str, Any]] = None
    pyright: Optional[Dict[str, Any]] = None
    pytest: Optional[Dict[str, Any]] = None
    probes: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def gates_pass(self) -> bool:
        # None = gate intentionally skipped (--skip); a dict without an
        # explicit pass=True is a crash artifact and must fail closed.
        for g in (self.ruff, self.pyright, self.pytest):
            if g is not None and not g.get("pass", False):
                return False
        return True

    @property
    def bugs_present(self) -> int:
        return sum(1 for p in self.probes if p["status"] == "BUG_PRESENT")


def _run(cmd: List[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout
    )


def _diagnostics_by_scope(raw: Dict[str, Any], key: str) -> Dict[str, List[Dict[str, Any]]]:
    """Group ruff/pyright JSON diagnostics per scope by file path."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for diag in raw.get("generalDiagnostics", raw.get(key, [])):
        f = diag.get("file", "").replace(str(REPO_ROOT) + "/", "")
        for scope, cfg in SCOPES.items():
            for pattern in cfg["files"]:
                p = pattern.rstrip("/")
                if f == p or f.startswith(p.rstrip("/*.py") if p.endswith(".py") else p):
                    out.setdefault(scope, []).append(diag)
                    break
            else:
                continue
            break
    return out


def run_static_gates(selected: List[str], skip: set) -> Dict[str, ScopeResult]:
    results = {s: ScopeResult(name=s) for s in selected}

    if "ruff" not in skip:
        print("== ruff (single pass, attributed per scope)")
        proc = _run(["uv", "run", "ruff", "check", "src/sot_graph/",
                     "--output-format", "json"])
        if proc.returncode not in (0, 1):
            print(f"   ruff crashed: {proc.stderr[:200]}")
            for res in results.values():
                res.ruff = {"pass": False,
                            "detail": f"ruff crashed (rc={proc.returncode})"}
        else:
            diags = json.loads(proc.stdout or "[]")
            by_scope: Dict[str, List[Dict[str, Any]]] = {}
            for d in diags:
                f = d.get("path", d.get("filename", ""))
                for scope, cfg in SCOPES.items():
                    if any(f == pat.rstrip("/") or f.startswith(pat.rstrip("/"))
                           for pat in cfg["files"] if pat.endswith("/")) or \
                       any(f == pat for pat in cfg["files"] if not pat.endswith("/")):
                        by_scope.setdefault(scope, []).append(d)
                        break
            for scope, res in results.items():
                ds = by_scope.get(scope, [])
                res.ruff = {
                    "pass": not ds,
                    "count": len(ds),
                    "items": [
                        f"{d.get('path', '?')}:{d.get('location', {}).get('row', '?')}"
                        f" [{d.get('code', '?')}] {d.get('message', '')[:120]}"
                        for d in ds[:10]
                    ],
                }

    if "pyright" not in skip:
        print("== pyright (single pass, attributed per scope)")
        proc = _run(["uv", "run", "pyright", "src/sot_graph/", "--outputjson"])
        try:
            raw = json.loads(proc.stdout)
            grouped = _diagnostics_by_scope(raw, "diagnostics")
            summary = raw.get("summary", {})
            print(f"   total errors={summary.get('errorCount')} "
                  f"warnings={summary.get('warningCount')}")
            for scope, res in results.items():
                ds = [d for d in grouped.get(scope, [])
                      if d.get("severity") == "error"]
                res.pyright = {
                    "pass": not ds,
                    "count": len(ds),
                    "items": [
                        f"{d['file'].replace(str(REPO_ROOT) + '/', '')}"
                        f":{d['range']['start']['line'] + 1} {d.get('message', '')[:120]}"
                        for d in ds[:10]
                    ],
                }
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"   pyright output unusable ({exc}); stderr tail:")
            print("   " + proc.stderr[-300:].replace("\n", "\n   "))
            for res in results.values():
                res.pyright = {"pass": False,
                               "detail": f"pyright output unusable ({exc})"}

    return results


def run_tests(results: Dict[str, ScopeResult], skip: set) -> None:
    if "tests" in skip:
        return
    for scope, res in results.items():
        test_files = [f"tests/{t}" for t in SCOPES[scope]["tests"]
                      if (REPO_ROOT / "tests" / t).exists()]
        missing = [t for t in SCOPES[scope]["tests"]
                   if not (REPO_ROOT / "tests" / t).exists()]
        if missing:
            print(f"   [warn] {scope}: mapped tests missing on disk: {missing}")
        if not test_files:
            res.pytest = {"pass": False, "detail": "no mapped test files found"}
            continue
        print(f"== pytest [{scope}] ({len(test_files)} files)")
        proc = _run(["uv", "run", "pytest", "-q", "--strict-markers", "-p", "no:cacheprovider",
                     "--no-header", *test_files])
        tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()][-1] if proc.stdout else ""
        res.pytest = {
            "pass": proc.returncode == 0,
            "detail": tail[:200] or (proc.stderr or "").strip().splitlines()[-1][:200],
        }


def run_probes(results: Dict[str, ScopeResult], skip: set) -> None:
    if "probes" in skip:
        return
    for scope, res in results.items():
        for name, bugref, fn in PROBES.get(scope, []):
            t0 = time.monotonic()
            try:
                status, detail = fn()
            except Exception as exc:  # probe infrastructure failure
                status, detail = "PROBE_ERROR", f"{type(exc).__name__}: {exc}"
            res.probes.append({
                "name": name, "bug": bugref, "status": status, "detail": detail,
                "ms": int((time.monotonic() - t0) * 1000),
            })


def render_markdown(results: Dict[str, ScopeResult], meta: Dict[str, Any]) -> str:
    lines = ["# Module-Scope Evaluation Report", "",
             f"Generated: {meta['generated']}  |  commit: `{meta['commit']}`", ""]
    total_bugs = sum(r.bugs_present for r in results.values())
    total_probe_errors = sum(
        1 for r in results.values() for p in r.probes
        if p["status"] == "PROBE_ERROR")
    lines += ["| Scope | ruff | pyright | pytest | probes (bugs) | gate |",
              "|---|---|---|---|---|---|"]
    for r in results.values():
        def mark(g): return "—" if g is None else ("✅" if g["pass"] else "❌")
        gate = "PASS" if r.gates_pass else "FAIL"
        lines.append(
            f"| {r.name} | {mark(r.ruff)} | {mark(r.pyright)} | {mark(r.pytest)} "
            f"| {len(r.probes)} ({r.bugs_present}) | {gate} |")
    lines += ["", f"**Probes: {total_bugs} bug(s) still present, "
              f"{total_probe_errors} probe error(s).**", ""]
    for r in results.values():
        if not r.probes:
            continue
        lines.append(f"## Probes — {r.name}")
        for p in r.probes:
            icon = {"BUG_PRESENT": "🐞", "OK": "✅", "PROBE_ERROR": "⚠️"}[p["status"]]
            lines.append(f"- {icon} `{p['name']}` — {p['bug']} — {p['status']} ({p['ms']}ms)")
            lines.append(f"  - {p['detail']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--scope", action="append", choices=sorted(SCOPES),
                    help="limit evaluation to given scope (repeatable)")
    ap.add_argument("--skip", action="append", default=[],
                    choices=["ruff", "pyright", "tests", "probes"],
                    help="skip a gate class (repeatable)")
    ap.add_argument("--json", default="evaluation/module_scope/report.json")
    ap.add_argument("--markdown", default="evaluation/module_scope/report.md")
    ap.add_argument("--strict-probes", action="store_true",
                    help="exit 2 when any probe still detects its bug or any probe crashed")
    args = ap.parse_args(argv)

    selected = args.scope or sorted(SCOPES)
    skip = set(args.skip)
    print(f"Module-scope evaluation — scopes: {', '.join(selected)}; skipped: "
          f"{', '.join(sorted(skip)) or 'none'}")

    results = run_static_gates(selected, skip)
    run_tests(results, skip)
    run_probes(results, skip)

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            cwd=REPO_ROOT, capture_output=True, text=True)
    meta = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "commit": commit.stdout.strip(),
        "scopes": selected,
        "skipped": sorted(skip),
    }
    out = {"meta": meta,
           "scopes": {k: v.__dict__ for k, v in results.items()}}

    md = render_markdown(results, meta)
    for path, payload in ((args.json, json.dumps(out, indent=2, default=str)),
                          (args.markdown, md)):
        p = REPO_ROOT / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(payload, encoding="utf-8")
        print(f"report → {p}")

    gate_fail = [r.name for r in results.values() if not r.gates_pass]
    bugs = sum(r.bugs_present for r in results.values())
    probe_errors = sum(
        1 for r in results.values()
        for p in r.probes if p["status"] == "PROBE_ERROR")
    print(f"\nGates: {'ALL PASS' if not gate_fail else 'FAIL: ' + ', '.join(gate_fail)}"
          f" | Probes: {bugs} bug(s) present, {probe_errors} probe error(s)")
    if gate_fail:
        return 1
    if args.strict_probes and (bugs or probe_errors):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
