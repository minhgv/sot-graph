"""P3.2 — SCIP importer: qualified identity + snapshot binding.

Invariants under test:
- src/dst carry the qualified identity; bare names ride the symbol/target
  alias columns so both lookup shapes resolve (no short-name normalization).
- A plain occurrence is recorded as a reference — never upgraded to a call.
- Each run binds to the reconciler's file journal via a manifest digest;
  index content that disagrees with the journal is invalidated immediately.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sot_graph.db import Database  # noqa: E402
from sot_graph.importer.scip import ScipImporter  # noqa: E402
from sot_graph.reconciler import Reconciler  # noqa: E402


def _index_doc(path: str, occurrences, symbols=(), text=None):
    return {
        "metadata": {"tool_info": {"name": "scip-test", "version": "1.0"}},
        "documents": [
            {
                "relative_path": path,
                **({"text": text} if text is not None else {}),
                "occurrences": occurrences,
                "symbols": list(symbols),
            }
        ],
    }


def _def(symbol, line):
    return {"symbol": symbol, "symbol_roles": 1, "range": [line, 0, line, 8]}


def _ref(symbol, line):
    return {"symbol": symbol, "symbol_roles": 0, "range": [line, 2, line, 8]}


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "core").mkdir()
    (ws / "core" / "service.py").write_text(
        "def compute():\n    return helper()\n", encoding="utf-8"
    )
    db = Database(str(ws / ".sot" / "sot.db"))
    try:
        Reconciler(db, str(ws)).reconcile()
    finally:
        db.close()
    return ws


class TestQualifiedIdentity:
    def test_src_dst_are_qualified_bare_rides_alias(self, workspace):
        db = Database(str(workspace / ".sot" / "sot.db"))
        try:
            ScipImporter(db, project_root=str(workspace)).import_index(
                _index_doc(
                    "core/service.py",
                    [
                        _def("scip-python python pkg 1.0 core/service#compute().", 0),
                        _ref("scip-python python pkg 1.0 core/service#helper().", 1),
                    ],
                )
            )
            rows = db.conn.execute(
                "SELECT symbol, src_symbol, target_symbol, dst_symbol, relation "
                "FROM provider_evidence WHERE relation = 'references'"
            ).fetchall()
            assert rows, "reference evidence expected"
            symbol, src, target, dst, relation = rows[0]
            assert src == "core.service.compute" and symbol == "compute"
            assert dst == "core.service.helper" and target == "helper"
        finally:
            db.close()

    def test_both_lookup_shapes_resolve(self, workspace):
        db = Database(str(workspace / ".sot" / "sot.db"))
        try:
            ScipImporter(db, project_root=str(workspace)).import_index(
                _index_doc(
                    "core/service.py",
                    [
                        _def("scip-python python pkg 1.0 core/service#compute().", 0),
                        _ref("scip-python python pkg 1.0 core/service#helper().", 1),
                    ],
                )
            )
            by_bare = db.get_symbol_evidence("helper")
            by_fqn = db.get_symbol_evidence("core.service.helper")
            assert by_bare and by_fqn
            assert {r["id"] for r in by_bare} == {r["id"] for r in by_fqn}
        finally:
            db.close()

    def test_plain_occurrence_never_becomes_call(self, workspace):
        db = Database(str(workspace / ".sot" / "sot.db"))
        try:
            ScipImporter(db, project_root=str(workspace)).import_index(
                _index_doc(
                    "core/service.py",
                    [
                        _def("scip-python python pkg 1.0 core/service#compute().", 0),
                        _ref("scip-python python pkg 1.0 core/service#helper().", 1),
                    ],
                )
            )
            relations = {
                r[0] for r in db.conn.execute(
                    "SELECT DISTINCT relation FROM provider_evidence"
                ).fetchall()
            }
            assert "calls" not in relations
            assert "references" in relations
        finally:
            db.close()


class TestSnapshotBinding:
    def _index_for_current_disk(self, workspace):
        text = (workspace / "core" / "service.py").read_text(encoding="utf-8")
        return _index_doc(
            "core/service.py",
            [
                _def("scip-python python pkg 1.0 core/service#compute().", 0),
                _ref("scip-python python pkg 1.0 core/service#helper().", 1),
            ],
            text=text,
        )

    def test_fresh_index_binds_to_journal_manifest(self, workspace):
        db = Database(str(workspace / ".sot" / "sot.db"))
        try:
            result = ScipImporter(db, project_root=str(workspace)).import_index(
                self._index_for_current_disk(workspace)
            )
            assert result["journal_bound"] is True
            assert result["manifest_digest"].startswith("manifest:")
            assert result["stale_files"] == []
            assert result["stale_marked"] == 0
        finally:
            db.close()

    def test_stale_index_text_is_invalidated_not_kept(self, workspace):
        db = Database(str(workspace / ".sot" / "sot.db"))
        try:
            # index snapshot from BEFORE an edit: text disagrees with journal
            old_text = "def compute():\n    return helper()\n"
            (workspace / "core" / "service.py").write_text(
                "def compute():\n    return helper() + 1\n", encoding="utf-8"
            )
            db2 = Database(str(workspace / ".sot" / "sot.db"))
            try:
                Reconciler(db2, str(workspace)).reconcile()
            finally:
                db2.close()
            result = ScipImporter(db, project_root=str(workspace)).import_index(
                _index_doc(
                    "core/service.py",
                    [_def("scip-python python pkg 1.0 core/service#compute().", 0)],
                    text=old_text,
                )
            )
            assert "core/service.py" in result["stale_files"]
            assert result["stale_marked"] >= 1
            flagged = db.conn.execute(
                "SELECT COUNT(*) FROM provider_evidence "
                "WHERE invalidated_at IS NOT NULL"
            ).fetchone()[0]
            assert flagged >= 1
            reason = db.conn.execute(
                "SELECT DISTINCT invalidation_reason FROM provider_evidence "
                "WHERE invalidated_at IS NOT NULL"
            ).fetchone()[0]
            assert "file_journal" in reason
        finally:
            db.close()

    def test_unjournaled_repo_is_unbound_not_stale(self, tmp_path):
        ws = tmp_path / "bare"
        ws.mkdir()
        (ws / "m.py").write_text("x = 1\n", encoding="utf-8")
        db = Database(str(ws / ".sot" / "sot.db"))
        try:
            result = ScipImporter(db, project_root=str(ws)).import_index(
                _index_doc("m.py", [_def("scip-python python pkg 1.0 m#x.", 0)])
            )
            # never indexed ≠ stale: evidence recorded, run unbound
            assert result["journal_bound"] is False
            assert result["manifest_digest"] is None
            assert result["stale_files"] == []
            assert result["evidence_recorded"] >= 1
        finally:
            db.close()

    def test_relationship_edges_carry_fqn_pair(self, workspace):
        db = Database(str(workspace / ".sot" / "sot.db"))
        try:
            ScipImporter(db, project_root=str(workspace)).import_index(
                _index_doc(
                    "core/service.py",
                    [_def("scip-python python pkg 1.0 core/service#compute().", 0)],
                    symbols=[
                        {
                            "symbol": "scip-python python pkg 1.0 core/service#compute().",
                            "kind": 3,
                            "relationships": [
                                {
                                    "symbol": "scip-python python pkg 1.0 core/service#Base.",
                                    "is_implementation": True,
                                }
                            ],
                        }
                    ],
                )
            )
            row = db.conn.execute(
                "SELECT src_symbol, dst_symbol, symbol, target_symbol, relation "
                "FROM provider_evidence WHERE relation = 'implements'"
            ).fetchone()
            assert row is not None
            assert row[0] == "core.service.compute"
            assert row[1] == "core.service.Base"
            assert row[2] == "compute" and row[3] == "Base"
        finally:
            db.close()
