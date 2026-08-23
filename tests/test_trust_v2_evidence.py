"""
tests/test_trust_v2_evidence.py - Unit and integration tests for Trust Model v2.

Tests:
- TASK-P0-03: Multi-dimensional Trust Evidence Schema v2 (Freshness, Relevance, Resolution, Completeness, Confidence).
- TASK-P1-03: Pure Read API (No silent auto-purge during search) & Atomic File Rehome by Hash.
- TASK-P0-05: Honest Zero-Result Semantics for Usages & Call Graph.
"""

import os
import tempfile

import pytest
from sot_graph.db import Database
from sot_graph.evidence import (
    CompletenessStatus,
    FreshnessStatus,
    RelevanceType,
    ResolutionStatus,
    TrustEvidence,
)
from sot_graph.reconciler import Reconciler
from sot_graph.verifier import TrustVerifier, VerificationResult, tokenize


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "sot.db")
        db = Database(db_path)
        yield tmpdir, db
        db.close()


def test_trust_evidence_schema_and_serialization():
    ev = TrustEvidence(
        freshness=FreshnessStatus.FRESH,
        relevance=RelevanceType.EXACT_SPAN,
        resolution=ResolutionStatus.EXACT,
        completeness=CompletenessStatus.COMPLETE,
        confidence=0.98,
        provenance="trust_verifier:v2",
        file_path="src/foo.py",
        file_hash="abcd1234efgh5678",
        coverage=0.9,
    )
    assert ev.to_legacy_verdict() == "STRONG"
    assert ev.is_grounded is True
    d = ev.to_dict()
    assert d["freshness"] == "FRESH"
    assert d["relevance"] == "EXACT_SPAN"
    assert d["confidence"] == 0.98
    assert d["legacy_verdict"] == "STRONG"


def test_trust_evidence_stale_missing_verdict():
    ev_stale = TrustEvidence(
        freshness=FreshnessStatus.STALE,
        relevance=RelevanceType.UNKNOWN,
        resolution=ResolutionStatus.UNRESOLVED,
        completeness=CompletenessStatus.PARTIAL,
        confidence=0.0,
        provenance="trust_verifier:v2",
    )
    assert ev_stale.to_legacy_verdict() == "STALE"
    assert ev_stale.is_grounded is False

    ev_missing = TrustEvidence(
        freshness=FreshnessStatus.MISSING,
        relevance=RelevanceType.UNKNOWN,
        resolution=ResolutionStatus.UNRESOLVED,
        completeness=CompletenessStatus.PARTIAL,
        confidence=0.0,
        provenance="trust_verifier:v2",
    )
    assert ev_missing.to_legacy_verdict() == "STALE"


def test_verifier_exact_span_and_symbol(temp_workspace):
    tmpdir, db = temp_workspace
    file_path = os.path.join(tmpdir, "sample.py")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("# sample file\n\ndef calculate_metric(a: int, b: int) -> int:\n    return a + b\n")
    rec = Reconciler(db, tmpdir)
    rec.reconcile(workers=1)

    cand = {
        "id": f"{file_path}#fn:calculate_metric",
        "path": file_path,
        "symbol": "calculate_metric",
        "kind": "function",
        "line_start": 3,
    }

    q_toks = tokenize("calculate_metric")
    res = TrustVerifier.verify_hit(db, cand, q_toks, tmpdir, auto_heal=False)

    assert isinstance(res, VerificationResult)
    verdict, cov, path = res
    assert verdict == "STRONG"
    assert cov == 1.0
    assert path == file_path

    ev = res.evidence
    assert ev.freshness == FreshnessStatus.FRESH
    assert ev.relevance == RelevanceType.EXACT_SPAN
    assert ev.resolution == ResolutionStatus.EXACT
    assert ev.completeness in (CompletenessStatus.COMPLETE, CompletenessStatus.COMPLETE_WITHIN_INDEX_CAPABILITY)
    assert ev.confidence >= 0.95
    assert ev.file_hash is not None


def test_verifier_missing_file_pure_read_no_db_mutation(temp_workspace):
    tmpdir, db = temp_workspace
    non_existent = os.path.join(tmpdir, "deleted_module.py")

    # Insert node into DB
    db.commit_file(
        path=non_existent,
        sha256="dummyhash",
        size=100,
        mtime_ms=1000,
        nodes=[{
            "id": f"{non_existent}#fn:ghost_func",
            "path": non_existent,
            "kind": "function",
            "symbol": "ghost_func",
            "label": "ghost_func",
            "body": "def ghost_func(): pass",
            "line_start": 1,
            "line_end": 1,
            "col_start": 0,
            "col_end": 20,
        }],
        edges=[],
        pending=[],
    )

    # Verify node exists in DB
    assert len(db.search_fts("ghost_func")) == 1

    cand = {
        "id": f"{non_existent}#fn:ghost_func",
        "path": non_existent,
        "symbol": "ghost_func",
        "kind": "function",
        "line_start": 1,
    }

    # Verify with auto_heal=False (Pure Read)
    res = TrustVerifier.verify_hit(db, cand, {"ghost_func"}, tmpdir, auto_heal=False)
    verdict, cov, path = res
    assert verdict == "STALE"
    assert res.evidence.freshness == FreshnessStatus.MISSING
    assert res.evidence.confidence == 0.0

    # Assert database WAS NOT modified (Pure Read guarantee)
    assert len(db.search_fts("ghost_func")) == 1
    assert db.get_file_journal(non_existent) is not None


def test_atomic_file_rehome_in_db(temp_workspace):
    tmpdir, db = temp_workspace
    old_path = os.path.join(tmpdir, "old_name.py")
    new_path = os.path.join(tmpdir, "new_name.py")

    # Commit initial state
    db.commit_file(
        path=old_path,
        sha256="content_hash_123",
        size=250,
        mtime_ms=5000,
        nodes=[{
            "id": f"{old_path}#fn:service_init",
            "path": old_path,
            "kind": "function",
            "symbol": "service_init",
            "label": "service_init",
            "body": "def service_init(): return True",
            "line_start": 1,
            "line_end": 2,
            "col_start": 0,
            "col_end": 30,
        }],
        edges=[{
            "path": old_path,
            "src": f"{old_path}#fn:service_init",
            "dst": f"{old_path}#mod:old_name",
            "relation": "member_of",
            "line": 1,
        }],
        pending=[{
            "path": old_path,
            "src": f"{old_path}#fn:service_init",
            "dst_symbol": "external_lib",
            "relation": "calls",
            "line": 2,
        }],
    )

    # Perform atomic rehome
    success = db.rehome_file_atomically(
        old_path=old_path,
        new_path=new_path,
        new_sha256="content_hash_123",
        new_mtime_ms=6000,
        new_size=250,
    )
    assert success is True

    # 1. Check file_journal updated
    assert db.get_file_journal(old_path) is None
    new_j = db.get_file_journal(new_path)
    assert new_j is not None
    assert new_j["sha256"] == "content_hash_123"
    assert new_j["generation"] == 2

    # 2. Check graph_nodes updated
    nodes = db.conn.execute("SELECT id, path, label FROM graph_nodes WHERE path = ?", (new_path,)).fetchall()
    assert len(nodes) == 1
    assert nodes[0][0] == f"{new_path}#fn:service_init"
    assert nodes[0][1] == new_path

    # Old path nodes should be 0
    old_nodes = db.conn.execute("SELECT id FROM graph_nodes WHERE path = ?", (old_path,)).fetchall()
    assert len(old_nodes) == 0

    # 3. Check graph_edges updated
    edges = db.conn.execute("SELECT path, src, dst FROM graph_edges WHERE path = ?", (new_path,)).fetchall()
    assert len(edges) == 1
    assert edges[0][0] == new_path
    assert new_path in edges[0][1]

    # 4. Check pending_edges updated
    pending = db.conn.execute("SELECT path, src FROM pending_edges WHERE path = ?", (new_path,)).fetchall()
    assert len(pending) == 1
    assert pending[0][0] == new_path
    assert new_path in pending[0][1]

    # 5. Check integrity
    diag = db.integrity_check()
    assert diag["ok"] is True
    assert diag["quick_check"] == "ok"

def test_honest_zero_result_usages_semantics(temp_workspace):
    tmpdir, db = temp_workspace
    file_path = os.path.join(tmpdir, "core.py")
    caller_path = os.path.join(tmpdir, "caller.py")

    target_id = f"{file_path}#fn:migrate_data"

    # Commit target definition with NO confirmed callers
    db.commit_file(
        path=file_path,
        sha256="hash1",
        size=100,
        mtime_ms=1000,
        nodes=[{
            "id": target_id,
            "path": file_path,
            "kind": "function",
            "symbol": "migrate_data",
            "label": "migrate_data",
            "body": "def migrate_data(): pass",
            "line_start": 1,
            "line_end": 2,
            "col_start": 0,
            "col_end": 20,
        }],
        edges=[],
        pending=[],
    )

    # Commit another file with an UNRESOLVED pending edge to migrate_data
    db.commit_file(
        path=caller_path,
        sha256="hash2",
        size=200,
        mtime_ms=1000,
        nodes=[{
            "id": f"{caller_path}#fn:run_migration_job",
            "path": caller_path,
            "kind": "function",
            "symbol": "run_migration_job",
            "label": "run_migration_job",
            "body": "def run_migration_job(): migrate_data()",
            "line_start": 5,
            "line_end": 6,
            "col_start": 0,
            "col_end": 35,
        }],
        edges=[],
        pending=[{
            "path": caller_path,
            "src": f"{caller_path}#fn:run_migration_job",
            "dst_symbol": "migrate_data",
            "relation": "calls",
            "line": 6,
        }],
    )

    # Query usages
    usages_result = db.usages(target_id, "migrate_data")

    # Honest semantics assertion:
    # 0 confirmed callers, but status is PARTIAL because 1 unresolved candidate exists
    assert len(usages_result["callers"]) == 0
    assert usages_result["resolved_count"] == 0
    assert usages_result["unresolved_count"] == 1
    assert usages_result["status"] == "PARTIAL"
    assert len(usages_result["risk"]) == 1
    assert usages_result["risk"][0]["dst_symbol"] == "migrate_data"
    assert len(usages_result["next_steps"]) > 0
