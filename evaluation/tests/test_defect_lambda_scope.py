from __future__ import annotations

from pathlib import Path
import tempfile
import pytest

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler

def test_lambda_parameter_shadowing_defect():
    """Verify lambda parameter shadow does not prevent unshadowed outer calls from resolving."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        math_file = ws / "my_math.py"
        math_file.write_text("""
def my_sqrt(x: int) -> int:
    return int(x ** 0.5)
""", encoding="utf-8")

        py_file = ws / "test_lambda.py"
        py_file.write_text("""
from my_math import my_sqrt

def outer_wrapper(val: int) -> int:
    # Lambda parameter my_sqrt shadows my_math.my_sqrt inside lambda only
    f = lambda my_sqrt: my_sqrt * 2
    # Outer call should resolve to my_math.my_sqrt
    return int(my_sqrt(val))
""", encoding="utf-8")

        db = Database(str(ws / "sot.db"))
        rec = Reconciler(db, str(ws))
        rec.reconcile(workers=1)

        # There should be an edge from outer_wrapper to my_sqrt
        edge = db.conn.execute("""
            SELECT e.relation FROM graph_edges e
            JOIN graph_nodes s ON e.src = s.id
            JOIN graph_nodes t ON e.dst = t.id
            WHERE s.symbol = 'outer_wrapper' AND t.symbol = 'my_sqrt'
        """).fetchone()

        assert edge is not None, "Outer call to my_sqrt was incorrectly blocked or not resolved!"
