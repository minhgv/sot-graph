from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler
from sot_graph.verifier import RelevanceType, TrustVerifier


def test_evaluator_catches_shadowing_defect():
    """Verify that if shadowing occurs without check, evaluator catches it."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        py_file = ws / "test_shadow.py"
        py_file.write_text("""
from math import sqrt

def test_func(x: int, sqrt: int) -> int:
    return sqrt + x
""", encoding="utf-8")

        db = Database(str(ws / "sot.db"))
        rec = Reconciler(db, str(ws))
        rec.reconcile(workers=1)

        # Check if there is an edge from test_func to sqrt
        edge = db.conn.execute("""
            SELECT e.relation FROM graph_edges e
            JOIN graph_nodes s ON e.src = s.id
            JOIN graph_nodes t ON e.dst = t.id
            WHERE s.symbol = 'test_func' AND t.symbol = 'sqrt'
        """).fetchone()

        # It must NOT create confirmed call edge
        assert edge is None, "Shadowed parameter created false confirmed call edge!"


def test_evaluator_catches_false_exact_span():
    """Verify that non-declaration lines (comments, regex) are rejected from EXACT_SPAN."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        ts_file = ws / "test.ts"
        ts_file.write_text("""
// function target() {}
const re = /function target/;
const s = "function target() {}";
""", encoding="utf-8")

        # Test line 2 (comment)
        cand_comment = {"path": str(ts_file), "symbol": "target", "line": 2, "line_start": 2}
        ev_comment = TrustVerifier.verify_evidence(cand_comment, {"target"}, str(ws))
        assert ev_comment.relevance != RelevanceType.EXACT_SPAN

        # Test line 3 (regex)
        cand_regex = {"path": str(ts_file), "symbol": "target", "line": 3, "line_start": 3}
        ev_regex = TrustVerifier.verify_evidence(cand_regex, {"target"}, str(ws))
        assert ev_regex.relevance != RelevanceType.EXACT_SPAN
