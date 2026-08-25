from __future__ import annotations

import json
from pathlib import Path

import pytest

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler


def test_python_local_import_should_resolve_edge():
    """Verify that a local import inside a function resolves to confirmed call edge."""
    ws = Path(__file__).resolve().parent.parent / "fixtures"
    # We want process_with_local_import -> discount to be resolved
    with pytest.MonkeyPatch.context() as mp:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            db = Database(str(Path(td) / "sot.db"))
            rec = Reconciler(db, str(ws / "python"))
            rec.reconcile(workers=1)

            edge = db.conn.execute("""
                SELECT e.relation FROM graph_edges e
                JOIN graph_nodes s ON e.src = s.id
                JOIN graph_nodes t ON e.dst = t.id
                WHERE s.symbol = 'process_with_local_import' AND t.symbol = 'discount'
            """).fetchone()

            assert edge is not None, "Local import failed to create confirmed call edge!"


def test_python_comprehension_target_does_not_leak_to_outer_call():
    """Verify comprehension binding does not leak to outer scope call."""
    ws = Path(__file__).resolve().parent.parent / "fixtures"
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        db = Database(str(Path(td) / "sot.db"))
        rec = Reconciler(db, str(ws / "python"))
        rec.reconcile(workers=1)

        edge = db.conn.execute("""
            SELECT e.relation FROM graph_edges e
            JOIN graph_nodes s ON e.src = s.id
            JOIN graph_nodes t ON e.dst = t.id
            WHERE s.symbol = 'process_with_comprehension' AND t.symbol = 'add'
        """).fetchone()

        assert edge is not None, "Outer call after comprehension target failed to resolve!"
