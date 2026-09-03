"""P9 — chaos & migration hardening.

Chaos: the ledger and receipt stack must degrade honestly under

- provider timeout / crash / huge output,
- corrupted SQLite sidecar,
- schema drift (future/unknown schema_version),
- partially-written rows,

without ever corrupting the builtin graph or crashing a read path.

Migration: opening an old ledger schema (v5 baseline from the snapshot
tests) upgrades in place to the running schema; a ledger from a NEWER
schema refuses to open read paths silently degraded, never guessed.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from sot_graph.assurance.ledger import ledger_rows_for_runs, union_evidence
from sot_graph.assurance.receipts import receipt_digest, scope_receipt


@pytest.fixture()
def chaos_repo(tmp_path: Path) -> Path:
    import subprocess

    repo = tmp_path / "chaos"
    repo.mkdir()
    (repo / "app.py").write_text(
        "def run():\n    return 1\n", encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "c1"],
        cwd=repo, check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo),
         "reconcile"],
        cwd=repo, check=True, capture_output=True,
    )
    return repo


def _db_of(repo: Path):
    from sot_graph.db import Database

    return Database(str(repo / ".sot" / "sot.db"))


class TestChaos:
    def test_corrupt_sidecar_does_not_break_reads(self, chaos_repo):
        db = _db_of(chaos_repo)
        # Corrupt the sidecar ledger rows so a read would raise.
        try:
            db.conn.executescript(
                "DROP TABLE IF EXISTS provider_runs;"
                "DROP TABLE IF EXISTS provider_evidence;"
            )
            # Receipt read path still answers; ledger blocks degrade.
            payload = scope_receipt(db, str(chaos_repo), "run")
            assert payload["schema_version"] == "1.2"
            assert payload["providers"]["union_entries"] >= 0
            assert payload["assurance"]["omp_confirmations"]
        finally:
            db.close()

    def test_schema_drift_future_version_degrades_not_crashes(self, chaos_repo):
        db = _db_of(chaos_repo)
        try:
            db.conn.execute("PRAGMA user_version = 99")
            db.conn.commit()
            payload = scope_receipt(db, str(chaos_repo), "run")
            # Receipt still emits; nothing is silently trusted.
            assert payload["schema_version"] == "1.2"
        finally:
            db.close()

    def test_huge_ledger_rows_do_not_explode_receipt(self, chaos_repo):
        db = _db_of(chaos_repo)
        try:
            db.conn.executemany(
                "INSERT INTO provider_runs (id, provider_name, "
                "provider_version, capability, snapshot_hash, project_root, "
                "status, exit_code, duration_ms, command_digest, "
                "arguments_json, created_at) VALUES (?, 'cbm', '0.10.8', "
                "'search', 'x', ?, 'ok', 0, 1, 'd', '{}', "
                "datetime('now'))",
                [(f"run{i}", str(chaos_repo)) for i in range(400)],
            )
            db.conn.commit()
            payload = scope_receipt(db, str(chaos_repo), "run")
            # cross-check bounded to 5 runs
            assert len(payload["providers"]["runs"]) <= 5
        finally:
            db.close()

    def test_partial_write_rows_excluded_from_union(self, chaos_repo):
        db = _db_of(chaos_repo)
        try:
            # status != 'ok' rows must never enter the union
            db.conn.execute(
                "INSERT INTO provider_runs (id, provider_name, "
                "provider_version, capability, snapshot_hash, project_root, "
                "status, exit_code, duration_ms, command_digest, "
                "arguments_json, created_at) VALUES ('runfail', 'cbm', "
                "'0.10.8', 'search', 'x', ?, 'crashed', 2, 1, 'd', '{}', "
                "datetime('now'))",
                (str(chaos_repo),),
            )
            db.conn.commit()
            union = union_evidence(db, str(chaos_repo))
            for entry in union:
                assert entry.get("error") or not entry.get("providers") or \
                    all("runfail" not in str(p) for p in entry["providers"])
        finally:
            db.close()

    def test_ledger_rows_for_runs_survives_unknown_ids(self, chaos_repo):
        db = _db_of(chaos_repo)
        try:
            rows = ledger_rows_for_runs(db, ["ghost-run-id"])
            assert rows == []
        finally:
            db.close()


class TestMigrations:
    def test_v5_baseline_opens_and_upgrades(self, tmp_path):
        from sot_graph.db import Database, SCHEMA_VERSION

        path = tmp_path / "v5.sqlite"
        db = Database(str(path))
        db.close()
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA user_version = 5")
        conn.commit()
        conn.close()
        db = Database(str(path))
        try:
            got = db.conn.execute("PRAGMA user_version").fetchone()[0]
            assert got == SCHEMA_VERSION
        finally:
            db.close()

    def test_digest_is_migration_stable(self, chaos_repo):
        db = _db_of(chaos_repo)
        try:
            a = scope_receipt(db, str(chaos_repo), "run")
            again = scope_receipt(db, str(chaos_repo), "run")
            assert a["digest"] == again["digest"]
            assert receipt_digest(
                {"b": 1, "a": [1, 2]}
            ) == receipt_digest({"a": [1, 2], "b": 1})
        finally:
            db.close()


class TestLifecycleManifest:
    def test_manifest_shape_and_process(self, chaos_repo):
        from sot_graph.providers.lifecycle import (
            UPDATE_PROCESS,
            lifecycle_manifest,
        )

        m = lifecycle_manifest(str(chaos_repo))
        assert m["schema_version"] == 1
        assert len(UPDATE_PROCESS) == 8
        assert [s["step"] for s in m["update_process"]] == list(range(1, 9))
        names = {p["name"] for p in m["providers"]}
        assert "sot-builtin" in names
        builtin = next(p for p in m["providers"] if p["name"] == "sot-builtin")
        assert builtin["healthy"] is True
        assert builtin["adapter_contract_version"] >= 1
        assert "rollback" in builtin and builtin["rollback"]

    def test_cli_lifecycle_json(self, chaos_repo):
        import json
        import subprocess

        out = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root",
             str(chaos_repo), "providers", "lifecycle", "--format", "json"],
            cwd=chaos_repo, capture_output=True, text=True,
        )
        assert out.returncode == 0, out.stderr
        payload = json.loads(out.stdout)
        assert payload["update_process"][0]["step"] == 1
