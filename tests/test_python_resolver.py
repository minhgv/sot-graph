"""
Comprehensive test suite for Python Resolver & AST Extractor upgrades (Sprint 2):
- TASK-P0-02: Import Alias & Local Collision Resolver
- TASK-P0-03: Multi-level Relative Import & Re-export Resolver
- TASK-P1-01: Python Receiver Type & MRO Inheritance Resolver
- Nested Function Call Attribution & Scope Isolation
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler
from sot_graph._vendor.graphify.extract import extract_python


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_nested_function_call_attribution(temp_workspace: Path):
    """Verify that inner function calls are attributed to inner function, not outer function."""
    code = '''
def outer_service(val: int) -> int:
    def inner_helper(x: int) -> int:
        return x * 2

    res = inner_helper(val)
    return res
'''
    f = temp_workspace / "service.py"
    f.write_text(code, encoding="utf-8")

    result = extract_python(f)
    nodes = {n["id"]: n for n in result["nodes"]}
    edges = result["edges"]

    # Must contain both outer_service and outer_service.inner_helper
    assert "outer_service" in nodes
    assert "outer_service.inner_helper" in nodes

    # outer_service calls inner_helper
    outer_calls = [e for e in edges if e.get("relation") == "calls" and e.get("source") == "outer_service"]
    assert any(e["target"] == "inner_helper" for e in outer_calls)

    # inner_helper must NOT inherit outer_service's calls, and outer_service must NOT doubly emit
    inner_calls = [e for e in edges if e.get("relation") == "calls" and e.get("source") == "outer_service.inner_helper"]
    assert len(inner_calls) == 0  # inner_helper has no calls inside its own body


def test_local_variable_and_param_collision(temp_workspace: Path):
    """Verify that local variables/parameters shadowing global names do NOT emit global calls."""
    code = '''
def execute_query(search, query: str):
    # 'search' is a local parameter callback
    return search(query)

def search(q: str):
    return f"results for {q}"
'''
    f = temp_workspace / "query.py"
    f.write_text(code, encoding="utf-8")

    result = extract_python(f)
    edges = result["edges"]
    call_edges = [e for e in edges if e.get("relation") == "calls" and e.get("source") == "execute_query"]
    assert len(call_edges) == 1
    assert call_edges[0]["is_shadowed"] is True

    db = Database(str(temp_workspace / ".sot" / "sot.db"))
    rec = Reconciler(db, str(temp_workspace))
    rec.reconcile(workers=1)
    # In graph_edges, execute_query should NOT have a calls edge to query.py:search
    resolved_calls = db.conn.execute(
        "SELECT src, dst FROM graph_edges WHERE relation = 'calls'"
    ).fetchall()
    assert not any("execute_query" in src and "search" in dst for src, dst in resolved_calls)
    db.close()  # release sot.db before TemporaryDirectory cleanup (Windows)

def test_import_alias_resolution(temp_workspace: Path):
    """Verify that imported aliases correctly resolve to the actual target symbol."""
    (temp_workspace / "math_lib.py").write_text('''
def calculate_metric(a: int, b: int) -> int:
    return a + b
''', encoding="utf-8")

    (temp_workspace / "consumer.py").write_text('''
from math_lib import calculate_metric as calc

def run_metric():
    return calc(10, 20)
''', encoding="utf-8")

    db = Database(str(temp_workspace / ".sot" / "sot.db"))
    rec = Reconciler(db, str(temp_workspace))
    rec.reconcile(workers=1)

    # In graph_edges, consumer.py / run_metric should call calculate_metric
    edges = db.conn.execute(
        "SELECT src, dst, relation FROM graph_edges WHERE relation = 'calls'"
    ).fetchall()
    
    # Check that the call resolved to calculate_metric
    assert any(dst == "calculate_metric" or "calculate_metric" in dst for src, dst, rel in edges)

    db.close()

def test_relative_import_and_reexport_resolution(temp_workspace: Path):
    """Verify multi-level relative imports and __init__.py re-exports."""
    pkg = temp_workspace / "pkg"
    subpkg = pkg / "subpkg"
    subpkg.mkdir(parents=True)

    (subpkg / "worker.py").write_text('''
def do_heavy_work():
    return "done"
''', encoding="utf-8")

    (subpkg / "__init__.py").write_text('''
from .worker import do_heavy_work
''', encoding="utf-8")

    (pkg / "__init__.py").write_text('''
from .subpkg import do_heavy_work
''', encoding="utf-8")

    (temp_workspace / "main.py").write_text('''
from pkg import do_heavy_work

def entrypoint():
    return do_heavy_work()
''', encoding="utf-8")

    db = Database(str(temp_workspace / ".sot" / "sot.db"))
    rec = Reconciler(db, str(temp_workspace))
    rec.reconcile(workers=1)

    # Check edges in database
    edges = db.conn.execute(
        "SELECT src, dst, relation FROM graph_edges WHERE relation = 'calls'"
    ).fetchall()
    
    # entrypoint calling do_heavy_work should be resolved
    assert any("do_heavy_work" in dst for src, dst, rel in edges)

    db.close()

def test_mro_and_receiver_inheritance_resolution(temp_workspace: Path):
    """Verify receiver method calls across class inheritance hierarchies (MRO)."""
    (temp_workspace / "models.py").write_text('''
class BaseRepository:
    def execute(self, query: str) -> str:
        return f"Executing {query}"

class UserRepository(BaseRepository):
    def find_user(self, user_id: int) -> str:
        return self.execute(f"SELECT * FROM users WHERE id = {user_id}")
''', encoding="utf-8")

    db = Database(str(temp_workspace / ".sot" / "sot.db"))
    rec = Reconciler(db, str(temp_workspace))
    rec.reconcile(workers=1)

    # find_user calling self.execute should resolve to BaseRepository.execute
    edges = db.conn.execute(
        "SELECT src, dst, relation FROM graph_edges WHERE relation = 'calls'"
    ).fetchall()

    assert any(
        "UserRepository.find_user" in src and "execute" in dst
        for src, dst, rel in edges
    )
    db.close()
