"""P4.4 — query parser hardening: FTS injection + wildcard/path ambiguity.

Security property under test: the FTS5 MATCH string only ever contains
QUOTED prefix phrases of sanitized tokens — FTS operator syntax
(*, ^, ", (), {}, :, column filters, NEAR) never reaches MATCH as an
operator, and LIKE scope filters escape %/_ so a scope can not widen to
every row. A row returned for a hostile query always matches a clean
prefix of that query (no match-everything escape).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from sot_graph.db import Database  # noqa: E402


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    d = Database(str(tmp_path / "sot.db"))
    for path, symbol, kind, body in (
        ("src/app.py", "run_server", "function", "def run_server(): start app"),
        ("src/util.py", "parse_config", "function", "def parse_config(cfg): load"),
        ("src/model.py", "OrderRow", "class", "class OrderRow: row model"),
    ):
        d.conn.execute(
            "INSERT INTO graph_nodes (id, path, kind, symbol, fqn, label, body,"
            " keywords, line_start, line_end, col_start, col_end, updated_at)"
+            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"{path}:{symbol}", path, kind, symbol, f"src.{symbol}", symbol,
             body, "", 1, 2, 0, 0, 0),
        )
    # trg_nodes_ai keeps graph_fts in sync on insert
    return d


def _clean_prefixes(vector: str) -> list[str]:
    """Mirror search_fts tokenization to get the legal match prefixes."""
    prefixes: set[str] = set()
    for raw in vector.split():
        cleaned = re.sub(r"[\*\^\"(){}:;,=/<>!#&|'+\[\]]", "", raw)
        cleaned = cleaned.strip("\"'")
        if not cleaned:
            continue
        if len(cleaned) >= 2:
            prefixes.add(cleaned.lower())
        for part in re.split(r"[_\.\-:\$@\s]+", cleaned):
            if len(part) >= 2:
                prefixes.add(part.lower())
            stripped = part.strip("_")
            if len(stripped) >= 2:
                prefixes.add(stripped.lower())
    return sorted(prefixes)


INJECTION_VECTORS = [
    'run" OR 1=1 --',
    "NEAR(run server, 5)",
    "run^*",
    "{body}:run",
    "label : run",
    "a*b*c",
    "AND OR NOT",
    "run AND (SELECT 1)",
    '"run_server"',
    "run;",
    "run--",
    "/* comment */run",
    "run_server' --",
]


class TestFtsInjection:
    @pytest.mark.parametrize("vector", INJECTION_VECTORS)
    def test_never_raises_and_stays_bounded(self, db, vector):
        rows = db.search_fts(vector, limit=10)
        prefixes = _clean_prefixes(vector)
        for r in rows:
            text = f"{r['symbol'] or ''} {r['label'] or ''} {r['fqn'] or ''}".lower()
            assert any(p in text for p in prefixes), (
                f"row {r['symbol']!r} matched without any clean prefix of {vector!r}"
            )

    def test_operator_only_query_returns_nothing(self, db):
        for vector in ('***', '"""', '(:)', '^', '*', '{}'):
            assert db.search_fts(vector, limit=5) == []

    def test_prefix_still_works_after_hardening(self, db):
        rows = db.search_fts("run_ser", limit=5)
        assert rows and rows[0]["symbol"] == "run_server"

    def test_match_string_is_quoted_phrases_only(self, db):
        import sqlite3

        captured: list[str] = []
        real_execute = db.conn.execute

        class _SpyConn:
            def execute(self, sql, params=()):
                if "MATCH" in sql:
                    captured.extend(p for p in params if isinstance(p, str))
                return real_execute(sql, params)

            def __getattr__(self, name):
                return getattr(real_execute, name)

        original = db.__dict__.get("conn")
        object.__setattr__(db, "conn", _SpyConn())
        try:
            db.search_fts('run" OR 1=1 -- NEAR(x y) {body}:z', limit=5)
        finally:
            object.__setattr__(db, "conn", original)
        assert captured, "no MATCH parameter captured"
        for phrase in captured[0].split(" OR "):
            assert re.fullmatch(r'"[^"]+"\*', phrase), (
                f"unquoted FTS term reached MATCH: {phrase!r}"
            )


class TestScopeWildcardAmbiguity:
    def test_percent_scope_matches_nothing_literal(self, db):
        # no path/body contains a literal '%' — unescaped it would match all
        assert db.search_fts("run_server", limit=5, scope="%") == []

    def test_underscore_scope_stays_literal(self, db):
        rows = db.search_fts("parse_config", limit=5, scope="_")
        # only rows whose path/body literally contain '_' may return
        for r in rows:
            assert "_" in r["path"] or "_" in (r["body"] or "")

    def test_impossible_scope_returns_nothing(self, db):
        assert db.search_fts("run_server", limit=5, scope="__NO__MATCH__") == []

    def test_normal_scope_still_filters(self, db):
        rows = db.search_fts("parse", limit=5, scope="util")
        assert rows and all("util" in r["path"] for r in rows)
        assert any(r["symbol"] == "parse_config" for r in rows)
