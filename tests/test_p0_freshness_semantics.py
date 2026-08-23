"""
tests/test_p0_freshness_semantics.py — Regression suite for SOT-P0-01:
Hash-based freshness, AST declaration span verification, and pure-read defaults.
"""

import os
import tempfile
import pytest

from sot_graph.db import Database
from sot_graph.evidence import FreshnessStatus, RelevanceType
from sot_graph.reconciler import Reconciler
from sot_graph.verifier import TrustVerifier, tokenize


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, ".sot", "sot.db")
        db = Database(db_path)
        yield tmpdir, db
        db.close()


def test_stale_file_not_reported_fresh_or_strong(temp_workspace):
    """
    Counter-example 1 from reassessment report:
    1. Index file containing function alpha
    2. Modify file to function beta without reconcile
    3. Verify hit for alpha -> must be STALE, not FRESH, and legacy verdict must NOT be STRONG.
    """
    tmpdir, db = temp_workspace
    file_path = os.path.join(tmpdir, "service.py")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("def alpha():\n    return 42\n")

    rec = Reconciler(db, tmpdir)
    rec.reconcile(workers=1)

    # Confirm index has alpha
    node = db.get_node_by_symbol("service.alpha")
    assert node is not None

    # Step 2: Modify file to beta without reconciling
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("def beta():\n    return 100\n")

    # Step 3: Verify candidate alpha
    cand = {
        "id": node["id"],
        "path": "service.py",
        "symbol": "service.alpha",
        "line_start": 1,
        "kind": "function",
    }
    evidence = TrustVerifier.verify_evidence(
        cand, tokenize("alpha"), tmpdir, db=db, auto_heal=False, jit_reconcile=False
    )

    assert evidence.freshness == FreshnessStatus.STALE
    assert evidence.relevance != RelevanceType.EXACT_SPAN
    assert evidence.confidence <= 0.4
    assert evidence.to_legacy_verdict() == "STALE"
    assert evidence.to_legacy_verdict() != "STRONG"


def test_comment_replacement_not_exact_span_or_strong(temp_workspace):
    """
    Counter-example 2 from reassessment report:
    1. Index alpha
    2. Replace file with comment 'alpha was removed' and function beta
    3. Verify hit alpha -> must NOT be EXACT_SPAN and legacy verdict must NOT be STRONG.
    """
    tmpdir, db = temp_workspace
    file_path = os.path.join(tmpdir, "calc.py")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("def alpha():\n    return 1\n")

    rec = Reconciler(db, tmpdir)
    rec.reconcile(workers=1)

    # Replace with comment containing 'alpha'
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("# alpha was removed\ndef beta():\n    return 2\n")

    cand = {
        "id": "calc.alpha",
        "path": "calc.py",
        "symbol": "calc.alpha",
        "line_start": 1,
        "kind": "function",
    }
    evidence = TrustVerifier.verify_evidence(
        cand, tokenize("alpha"), tmpdir, db=db, auto_heal=False, jit_reconcile=False
    )

    assert evidence.relevance != RelevanceType.EXACT_SPAN
    assert evidence.to_legacy_verdict() != "STRONG"


def test_fresh_intact_declaration_is_exact_span_and_strong(temp_workspace):
    """
    When file hash matches journal and declaration is physically intact at the span:
    Freshness must be FRESH, relevance EXACT_SPAN, confidence >= 0.95, legacy STRONG.
    """
    tmpdir, db = temp_workspace
    file_path = os.path.join(tmpdir, "auth.py")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("def authenticate_user(username, password):\n    return True\n")

    rec = Reconciler(db, tmpdir)
    rec.reconcile(workers=1)

    node = db.get_node_by_symbol("auth.authenticate_user")
    assert node is not None

    cand = {
        "id": node["id"],
        "path": "auth.py",
        "symbol": "auth.authenticate_user",
        "line_start": 1,
        "kind": "function",
    }
    evidence = TrustVerifier.verify_evidence(
        cand, tokenize("authenticate_user"), tmpdir, db=db, auto_heal=False
    )

    assert evidence.freshness == FreshnessStatus.FRESH
    assert evidence.relevance == RelevanceType.EXACT_SPAN
    assert evidence.confidence >= 0.95
    assert evidence.to_legacy_verdict() == "STRONG"
    assert evidence.is_grounded is True


def test_missing_file_is_missing(temp_workspace):
    """Missing file must yield MISSING freshness and confidence 0.0."""
    tmpdir, db = temp_workspace
    cand = {
        "id": "deleted.py",
        "path": "deleted.py",
        "symbol": "deleted.func",
        "line_start": 1,
        "kind": "function",
    }
    evidence = TrustVerifier.verify_evidence(cand, set(), tmpdir, db=db, auto_heal=False)
    assert evidence.freshness == FreshnessStatus.MISSING
    assert evidence.confidence == 0.0
    assert evidence.to_legacy_verdict() == "STALE"


def test_untracked_file_without_journal_is_unknown(temp_workspace):
    """File on disk but not in journal must be UNKNOWN freshness, not FRESH."""
    tmpdir, db = temp_workspace
    file_path = os.path.join(tmpdir, "untracked.py")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("def helper(): pass\n")

    cand = {
        "id": "untracked.helper",
        "path": "untracked.py",
        "symbol": "untracked.helper",
        "line_start": 1,
        "kind": "function",
    }
    evidence = TrustVerifier.verify_evidence(cand, set(), tmpdir, db=db, auto_heal=False)
    assert evidence.freshness == FreshnessStatus.UNKNOWN
    assert evidence.to_legacy_verdict() == "WEAK"


def test_pure_read_default_does_not_mutate_db(temp_workspace):
    """verify_hit with default auto_heal=False must never write to the database."""
    tmpdir, db = temp_workspace
    file_path = os.path.join(tmpdir, "mod.py")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("def func(): pass\n")

    rec = Reconciler(db, tmpdir)
    rec.reconcile(workers=1)

    os.remove(file_path)

    node = db.get_node_by_symbol("mod.func")
    assert node is not None

    # Call verify_hit with default parameters
    verdict, _, _ = TrustVerifier.verify_hit(
        db, node, tokenize("func"), tmpdir
    )
    assert verdict == "STALE"

    # Node must still exist in DB (no silent delete)
    node_after = db.get_node_by_symbol("mod.func")
    assert node_after is not None
