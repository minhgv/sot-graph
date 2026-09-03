"""Query-plan regression locks for per-file commit deletes.

``graph_edges`` and ``pending_edges`` carry composite PRIMARY KEYs whose
leftmost column is ``path`` (db.py schema), so the implicit
``sqlite_autoindex`` must keep serving ``DELETE ... WHERE path = ?`` via
an index SEARCH. If a future schema change reshapes those PKs, every
per-file commit delete would silently degrade to a full table scan;
these tests fail loudly before that ships. Redundant explicit indexes
are deliberately NOT added — they would only slow writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from sot_graph.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(str(tmp_path / "sot.db"))
    yield database
    database.close()


def _plans(db: Database, sql: str) -> list[str]:
    rows = db.conn.execute(
        "EXPLAIN QUERY PLAN " + sql, ("/repo/x.py",)
    ).fetchall()
    return [str(row[3]) for row in rows]


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM graph_edges WHERE path = ?",
        "DELETE FROM pending_edges WHERE path = ?",
    ],
)
def test_per_path_delete_uses_index_not_scan(db, sql):
    plans = _plans(db, sql)
    assert plans, f"no query plan produced for: {sql}"
    for plan in plans:
        assert "USING INDEX" in plan, f"{sql} -> {plan}"
        assert "SCAN" not in plan, f"{sql} -> {plan}"
