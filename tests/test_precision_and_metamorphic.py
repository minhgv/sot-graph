"""
test_precision_and_metamorphic.py - Property, Metamorphic, and Differential Tests for SOT-Graph.

Covers:
1. Differential AST/Regex verifier: comment/string stripped span integrity.
2. Metamorphic Python binding shadowing: param/local aliases vs global calls.
3. SCIP enclosing symbol caller attribution and drift freshness.
4. JIT reconcile removed-node purge idempotency.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest
from sot_graph.db import Database
from sot_graph.importer.scip import ScipImporter
from sot_graph.reconciler import Reconciler
from sot_graph.verifier import FreshnessStatus, RelevanceType, TrustVerifier


@pytest.fixture
def workspace():
    d = tempfile.mkdtemp(prefix="sot_meta_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def test_comment_and_string_exact_span_prevention(workspace: Path):
    """Metamorphic test: changing code to comment or string literal MUST downgrade EXACT_SPAN."""
    code_real = '''
function processPayment(amount) {
    return amount * 1.1;
}
'''
    code_commented = '''
// function processPayment(amount) {
//     return amount * 1.1;
// }
function helper() {}
'''
    code_string = '''
const dummy = "function processPayment(amount) {}";
function helper() {}
'''
    p1 = workspace / "real.js"
    p1.write_text(code_real, encoding="utf-8")

    db = Database(str(workspace / ".sot" / "sot.db"))
    rec = Reconciler(db, str(workspace))
    rec.reconcile(paths=[str(p1)], workers=1)

    node = db.conn.execute("SELECT id, path, symbol, line_start FROM graph_nodes WHERE symbol = 'processPayment'").fetchone()
    assert node is not None
    cand = {"id": node[0], "path": str(p1), "symbol": node[2], "line_start": node[3]}
    ev_real = TrustVerifier.verify_hit(db, cand, {"processPayment"}, str(workspace)).evidence
    assert ev_real.relevance == RelevanceType.EXACT_SPAN

    # Metamorphic transform 1: comment out function
    p1.write_text(code_commented, encoding="utf-8")
    ev_comment = TrustVerifier.verify_hit(db, cand, {"processPayment"}, str(workspace), jit_reconcile=False).evidence
    assert ev_comment.relevance != RelevanceType.EXACT_SPAN

    # Metamorphic transform 2: place into string literal
    p1.write_text(code_string, encoding="utf-8")
    ev_str = TrustVerifier.verify_hit(db, cand, {"processPayment"}, str(workspace), jit_reconcile=False).evidence
    assert ev_str.relevance != RelevanceType.EXACT_SPAN

def test_python_parameter_shadowing_metamorphic(workspace: Path):
    """Metamorphic test: adding local param shadowing imported alias removes false intra-file edge."""
    # Case A: unshadowed alias -> generates call
    f_lib = workspace / "math_lib.py"
    f_lib.write_text("def compute(x): return x * 2\n", encoding="utf-8")

    f_app = workspace / "app.py"
    f_app.write_text('''
from math_lib import compute as calc

def worker():
    return calc(10)
''', encoding="utf-8")

    db = Database(str(workspace / ".sot" / "sot.db"))
    rec = Reconciler(db, str(workspace))
    rec.reconcile(workers=1)

    calls = db.conn.execute("SELECT src, dst FROM graph_edges WHERE relation = 'calls'").fetchall()
    assert any("worker" in src and "compute" in dst for src, dst in calls)

    # Case B: shadowed by parameter -> must NOT emit call to compute
    f_app.write_text('''
from math_lib import compute as calc

def worker(calc):
    return calc(10)
''', encoding="utf-8")
    rec.reconcile(workers=1)
    calls2 = db.conn.execute("SELECT src, dst FROM graph_edges WHERE relation = 'calls'").fetchall()
    assert not any("worker" in src and "compute" in dst for src, dst in calls2)


def test_jit_reconcile_purged_node_evidence(workspace: Path):
    """Verify that JIT reconcile detects deleted symbol on disk and returns removed evidence."""
    f = workspace / "service.py"
    f.write_text("def target_func(): return 1\n", encoding="utf-8")

    db = Database(str(workspace / ".sot" / "sot.db"))
    rec = Reconciler(db, str(workspace))
    rec.reconcile(workers=1)

    node = db.conn.execute("SELECT id, path, symbol, line_start FROM graph_nodes WHERE symbol = 'target_func'").fetchone()
    cand = {"id": node[0], "path": str(f), "symbol": node[2], "line_start": node[3]}

    # Delete function from file on disk
    f.write_text("def another_func(): return 2\n", encoding="utf-8")
    res = TrustVerifier.verify_hit(db, cand, {"target_func"}, str(workspace), jit_reconcile=True)
    verdict, cov, real_path = res
    assert verdict == "REMOVED"
    assert res.evidence.provenance == "jit_reconcile:purged"
    assert res.evidence.confidence == 0.0
def test_scip_enclosing_symbol_attribution(workspace: Path):
    """Verify that SCIP reference occurrences inside a definition get attributed to the enclosing symbol."""
    scip_data = {
        "metadata": {
            "version": 1,
            "tool_info": {"name": "scip-python", "version": "0.1.0"},
            "project_root": str(workspace),
            "text_document_encoding": 1,
        },
        "documents": [
            {
                "relative_path": "src/client.py",
                "occurrences": [
                    # Definition of process_data at L10
                    {
                        "symbol": "scip-python python package 0.1.0 client/process_data().",
                        "symbol_roles": 1,  # Definition
                        "range": [10, 4, 10, 16],
                    },
                    # Reference to helper inside process_data body at L12
                    {
                        "symbol": "scip-python python package 0.1.0 utils/helper().",
                        "symbol_roles": 0,  # Reference
                        "range": [12, 8, 12, 14],
                    },
                ],
            }
        ],
    }
    db = Database(str(workspace / ".sot" / "sot.db"))
    importer = ScipImporter(db, project_root=str(workspace))
    importer.import_index(scip_data)

    ev_rows = db.conn.execute(
        "SELECT src_symbol, dst_symbol, relation, line_start FROM provider_evidence WHERE relation = 'references'"
    ).fetchall()
    assert len(ev_rows) == 1
    assert ev_rows[0][0] == "process_data"  # Enclosing symbol attributed, not raw file path!
    assert ev_rows[0][1] == "helper"
