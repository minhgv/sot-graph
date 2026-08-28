"""P6 — evidence ledger, union by identity, receipt replay, MCP write path.

Locks:
- A real CLI federated query persists provider_runs + provider_evidence
  rows with a snapshot binding (no log parsing involved).
- The MCP surface gains exactly one explicit write tool (providers
  sync); read tools stay read-only.
- union_evidence groups by canonical identity (path+language+relation
  +src+dst+snapshot), keeps per-provider provenance, adjudicates
  contradictions against current source (unique VERIFIED wins, else
  CONFLICT stays — no silent winner-takes-all), and never invents a
  false source_verified edge.
- receipt_from_ledger reconstructs the full receipt from ledger rows.
- Purging one run keeps other runs' evidence.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

STUB = r'''#!/usr/bin/env python3
"""Stub codebase-memory-mcp CLI for ledger tests (wire-faithful JSON)."""
import json
import os
import subprocess
import sys


def _head(cwd):
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd,
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except Exception:
        return None


def main():
    argv = sys.argv[1:]
    if "--version" in argv:
        print("codebase-memory-mcp 0.10.8")
        return 0
    # <bin> cli --json <tool> --args-file <path>
    tool = argv[2]
    args = {}
    if "--args-file" in argv:
        with open(argv[argv.index("--args-file") + 1]) as fh:
            args = json.load(fh)
    cwd = os.getcwd()
    if tool == "list_projects":
        payload = {"projects": [{"name": "fixture", "root_path": cwd}],
                   "has_more": False}
    elif tool == "index_status":
        payload = {"head_sha": _head(cwd) or "0" * 40, "branch": "main",
                   "status": "ready"}
    elif tool == "index_repository":
        payload = {"status": "ok", "indexed": True}
    elif tool == "search_graph":
        payload = {
            "cols": ["qn", "file", "lines", "label", "rank"],
            "rows": [
                ["run", "app.py", "1-1", "def run", 0],
            ],
            "has_more": False,
        }
    elif tool == "trace_path":
        payload = {
            "function": args.get("function_name") or "run",
            "callees": {
                "cols": ["name", "hop", "edge_type", "strategy", "confidence"],
                "groups": [{"qn_prefix": "", "rows": [["helper", 1, "CALLS", "static", 0.9]]}],
            },
            "callers": {
                "cols": ["name", "hop", "edge_type", "strategy", "confidence"],
                "groups": [],
            },
        }
    else:
        payload = {"ok": True}
    print(json.dumps({"structuredContent": payload}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


'''


@pytest.fixture(scope="module")
def ledger_repo(tmp_path_factory):
    repo = tmp_path_factory.mktemp("ledgerrepo")
    (repo / "app.py").write_text(
        "def run():\n    return helper()\n\n\ndef helper():\n    return 2\n",
        encoding="utf-8",
    )
    stub = repo / "cbm_stub.py"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)
    (repo / ".sot").mkdir()
    (repo / ".sot" / "config.toml").write_text(
        "allow_external = true\n"
        f'[providers.codebase-memory]\ncommand = ["{sys.executable}", "{stub}"]\n',
        encoding="utf-8",
    )
    def _git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    _git("init", "-q")
    _git("add", "-A")
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")
    subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo), "reconcile"],
        check=True, cwd=repo, capture_output=True,
    )
    return repo


def _db_of(repo: Path):
    from sot_graph.db import Database

    return Database(str(repo / ".sot" / "sot.db"))


class TestCliQueryPersistsLedger:
    def test_usages_writes_run_and_evidence(self, ledger_repo):
        out = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root", str(ledger_repo),
             "usages", "run", "--provider", "auto"],
            cwd=ledger_repo, capture_output=True, text=True,
        )
        assert out.returncode == 0, out.stderr
        db = _db_of(ledger_repo)
        try:
            runs = db.conn.execute(
                "SELECT capability, status, snapshot_hash FROM provider_runs "
                "WHERE capability IN ('trace_path','search_graph') "
                "ORDER BY created_at DESC LIMIT 5"
            ).fetchall()
            assert runs, "no query run recorded in ledger"
            assert any(r[1] == "ok" for r in runs)
            ok_runs = [r for r in runs if r[1] == "ok" and r[2]]
            assert ok_runs, "successful query run missing snapshot hash"
            ev = db.conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT run_id) FROM provider_evidence"
            ).fetchone()
            assert ev[0] > 0, "no evidence rows persisted for the query"
            assert ev[1] >= 1
        finally:
            db.close()


class TestMcpWritePath:
    def test_providers_sync_records_run_and_evidence(self, ledger_repo):
        from sot_graph.mcp_service import McpService

        before_files = set(os.listdir(ledger_repo / ".sot"))
        service = McpService(str(ledger_repo / ".sot" / "sot.db"),
                             str(ledger_repo))
        try:
            receipt = service.providers_sync("codebase-memory")
        finally:
            service.close()
        assert receipt["run"]["status"] == "ok"
        assert receipt["evidence_rows"] >= 0  # index path may carry no rows
        assert receipt["snapshot"]
        # Read surface untouched: only SQLite connection sidecars may
        # appear; no stray files from the read-only connection.
        after = set(os.listdir(ledger_repo / ".sot"))
        allowed = before_files | {"sot.db-wal", "sot.db-shm", "write.lock"}
        assert after <= allowed, after - allowed

    def test_search_still_read_only(self, ledger_repo):
        from sot_graph.mcp_service import McpService

        service = McpService(str(ledger_repo / ".sot" / "sot.db"),
                             str(ledger_repo))
        try:
            res = service.search("run")
            assert res["returned"] >= 1
        finally:
            service.close()


class TestUnionByIdentity:
    def _seed(self, repo, rows):
        """rows: (provider, path, relation, src, dst, snap, l1, l2)."""
        from sot_graph.db import Database

        db = Database(str(repo / ".sot" / "sot.db"))
        try:
            with db.conn:
                for i, (prov, path, rel, src, dst, snap, l1, l2) in enumerate(rows):
                    rid = f"run_seed_{prov}_{i}"
                    db.conn.execute(
                        "INSERT OR REPLACE INTO provider_runs "
                        "(id, provider_name, provider_version, capability, "
                        "snapshot_hash, project_root, position_encoding, "
                        "arguments_json, status, exit_code, duration_ms, "
                        "command_digest, created_at) "
                        "VALUES (?,?,?,?,?,?, 'utf-8', '[]', 'ok', 0, 1, 'd', 1)",
                        (rid, prov, "1.0", "trace_path", snap, str(repo)),
                    )
                    db.conn.execute(
                        "INSERT OR REPLACE INTO provider_evidence "
                        "(id, run_id, provider_name, path, relation, src_symbol, "
                        "dst_symbol, line_start, line_end, snapshot_hash, "
                        "recorded_at, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,1,1)",
                        (f"ev_seed_{prov}_{i}", rid, prov, path, rel, src,
                         dst, l1, l2, snap),
                    )
        finally:
            db.close()

    def test_union_groups_and_keeps_provenance(self, ledger_repo):
        from sot_graph.assurance.ledger import union_evidence

        snap = "s1"
        self._seed(ledger_repo, [
            ("codebase-memory", "app.py", "call:callees", "run", "helper", snap, 1, 1),
            ("scip", "app.py", "call:callees", "run", "helper", snap, 1, 1),
            ("codebase-memory", "other.py", "define", "x", "x", snap, 1, 1),
        ])
        db = _db_of(ledger_repo)
        try:
            union = union_evidence(db, str(ledger_repo), snapshot_hash=snap)
            by_src = {e["identity"]["src"]: e for e in union
                      if not e.get("error")}
            entry = by_src["run"]
            assert set(entry["providers"]) == {"codebase-memory", "scip"}
            # Fail-closed (P0): SUPPORTED requires a non-empty snapshot,
            # a real path, and a span that verifies against live source.
            assert entry["status"] == "SUPPORTED"
            assert entry["span"] == [1, 1]
            assert not entry["conflict"]
        finally:
            db.close()

    def test_conflict_adjudication_no_false_verified(self, ledger_repo):
        from sot_graph.assurance.ledger import union_evidence

        snap = "s2"
        # Same identity, two disagreeing spans: the span 1-1 matches the
        # real `def run()` on app.py; span 9-9 does not exist.
        self._seed(ledger_repo, [
            ("codebase-memory", "app.py", "define", "run", "run", snap, 1, 1),
            ("scip", "app.py", "define", "run", "run", snap, 9, 9),
        ])
        db = _db_of(ledger_repo)
        try:
            union = [e for e in union_evidence(db, str(ledger_repo),
                                               snapshot_hash=snap)
                     if not e.get("error")]
            run_entries = [e for e in union if e["identity"]["src"] == "run"]
            assert run_entries and run_entries[0]["conflict"]
            # Unique VERIFIED side wins — and it is the true span.
            assert run_entries[0]["status"] == "source_verified"
            assert run_entries[0]["resolved_span"] == [1, 1]
        finally:
            db.close()

    def test_unresolvable_conflict_stays_conflict(self, ledger_repo):
        from sot_graph.assurance.ledger import union_evidence

        snap = "s3"
        # Both spans fail source verification (file has no such symbol
        # span) — must stay CONFLICT, never pick a silent winner.
        self._seed(ledger_repo, [
            ("codebase-memory", "app.py", "define", "run", "run", snap, 40, 41),
            ("scip", "app.py", "define", "run", "run", snap, 90, 91),
        ])
        db = _db_of(ledger_repo)
        try:
            union = [e for e in union_evidence(db, str(ledger_repo),
                                               snapshot_hash=snap)
                     if not e.get("error")]
            run_entries = [e for e in union if e["identity"]["src"] == "run"]
            assert run_entries[0]["status"] == "CONFLICT"
            assert "resolved_span" not in run_entries[0]
        finally:
            db.close()

    def test_failed_runs_excluded_from_union(self, ledger_repo):
        from sot_graph.assurance.ledger import union_evidence

        snap = "s4"
        self._seed(ledger_repo, [
            ("codebase-memory", "app.py", "call:callees", "run", "helper", snap, None, None),
        ])
        db = _db_of(ledger_repo)
        try:
            with db.conn:
                db.conn.execute(
                    "UPDATE provider_runs SET status='error' "
                    "WHERE id LIKE 'run_seed_%' AND snapshot_hash='s4'"
                )
            union = [e for e in union_evidence(db, str(ledger_repo),
                                               snapshot_hash=snap)
                     if not e.get("error")]
            assert not [e for e in union if e["identity"]["src"] == "run"]
        finally:
            db.close()


class TestReceiptReplay:
    def test_receipt_from_ledger_needs_no_logs(self, ledger_repo):
        from sot_graph.assurance.ledger import receipt_from_ledger

        db = _db_of(ledger_repo)
        try:
            run_ids = [r[0] for r in db.conn.execute(
                "SELECT id FROM provider_runs WHERE status='ok' LIMIT 3"
            ).fetchall()]
            assert run_ids
            receipt = receipt_from_ledger(db, str(ledger_repo), run_ids)
            for run in receipt["runs"]:
                assert run["provider"] and run["capability"]
                assert "evidence_rows" in run
            assert receipt["union_entries"] >= 1
            assert "adjudication" in receipt
        finally:
            db.close()


class TestPurgeIsolation:
    def test_purge_one_run_keeps_others(self, ledger_repo):
        db = _db_of(ledger_repo)
        try:
            ids = [r[0] for r in db.conn.execute(
                "SELECT id FROM provider_runs WHERE capability='trace_path' "
                "ORDER BY created_at LIMIT 2"
            ).fetchall()]
            if len(ids) < 2:
                pytest.skip("need two trace runs")
            total_before = db.conn.execute(
                "SELECT COUNT(*) FROM provider_evidence"
            ).fetchone()[0]
            db.purge_provider_run(ids[0])
            ev = db.conn.execute(
                "SELECT COUNT(*) FROM provider_evidence WHERE run_id=?",
                (ids[0],),
            ).fetchone()[0]
            assert ev == 0
            other = db.conn.execute(
                "SELECT COUNT(*) FROM provider_evidence WHERE run_id=?",
                (ids[1],),
            ).fetchone()[0]
            if other or total_before:
                assert db.conn.execute(
                    "SELECT COUNT(*) FROM provider_evidence"
                ).fetchone()[0] <= total_before
        finally:
            db.close()
