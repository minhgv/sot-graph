from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler


def test_python_global_and_nonlocal_scope_shadowing():
    """Verify that global and nonlocal declarations correctly influence resolution."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        helper_file = ws / "helper.py"
        helper_file.write_text("""
def helper_func(x: int) -> int:
    return x * 10
""", encoding="utf-8")

        app_file = ws / "app.py"
        app_file.write_text("""
from helper import helper_func

helper_func = 123  # module level re-assignment

def call_global_helper(v: int) -> int:
    # If helper_func is shadowed at module level by non-function, it should not resolve as function call
    return helper_func + v

def call_with_nested_nonlocal(v: int) -> int:
    helper_func = lambda x: x + 1
    def inner():
        nonlocal helper_func
        # inner calls helper_func which is local lambda, not external helper.helper_func
        return helper_func(v)
    return inner()
""", encoding="utf-8")

        db = Database(str(ws / "sot.db"))
        rec = Reconciler(db, str(ws))
        rec.reconcile(workers=1)

        # There should NOT be an external calls edge from inner or call_with_nested_nonlocal to helper.helper_func
        edge = db.conn.execute("""
            SELECT e.relation FROM graph_edges e
            JOIN graph_nodes s ON e.src = s.id
            JOIN graph_nodes t ON e.dst = t.id
            WHERE e.relation = 'calls' AND t.symbol = 'helper_func' AND t.path LIKE '%helper.py'
        """).fetchone()

        assert edge is None, "Nonlocal / shadowed helper created unexpected external calls edge!"
        db.close()
