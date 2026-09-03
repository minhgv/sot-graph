"""Ledger history retention: ``Database.purge_history``.

``provider_runs`` / ``provider_evidence`` / ``snapshots`` are
INSERT-only and deliberately survive ``clean --all``, so unbounded
growth is bounded here instead: per-provider run retention with
cascaded evidence deletion, plus snapshot retention that never drops a
snapshot an active ledger run still references.
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


def _insert_snapshot(db, snap_id, captured_at, repo_root="/repo"):
    db.conn.execute(
        "INSERT INTO snapshots (id, repo_root, commit_sha, dirty, captured_at) "
        "VALUES (?, ?, NULL, 0, ?)",
        (snap_id, repo_root, captured_at),
    )


def _insert_run(db, run_id, provider_name, created_at, snapshot_id=None):
    db.conn.execute(
        "INSERT INTO provider_runs (id, provider_name, capability, created_at, "
        "snapshot_id) VALUES (?, ?, 'search_graph', ?, ?)",
        (run_id, provider_name, created_at, snapshot_id),
    )


def _insert_evidence(db, ev_id, run_id):
    db.conn.execute(
        "INSERT INTO provider_evidence (id, run_id, path, src_symbol, relation, "
        "created_at) VALUES (?, ?, 'a.py', 'foo', 'CALLS', 1)",
        (ev_id, run_id),
    )


@pytest.fixture()
def seeded(db):
    """8 alpha + 7 beta runs (3 evidence rows each), 30 snapshots.

    The three referenced snapshots are the OLDEST ones, so survival can
    only come from the ledger reference, never from recency.
    """
    for i in range(30):
        _insert_snapshot(db, f"snap_{i:02d}", captured_at=i + 1)
    runs = [(f"run_a_{i:02d}", "alpha", 1000 + i) for i in range(8)]
    runs += [(f"run_b_{i:02d}", "beta", 1000 + i) for i in range(7)]
    # FK order: snapshots exist already, runs may reference them.
    refs = {
        "run_a_07": "snap_00",
        "run_a_06": "snap_01",
        "run_b_06": "snap_02",
    }
    for run_id, provider, created_at in runs:
        _insert_run(
            db, run_id, provider, created_at, snapshot_id=refs.get(run_id)
        )
        for j in range(3):
            _insert_evidence(db, f"ev_{run_id}_{j}", run_id)
    db.conn.commit()
    return db


def test_purge_history_enforces_retention_and_protects_references(seeded):
    counts = seeded.purge_history(keep_runs=4, keep_snapshots=5)

    # alpha: 8 -> 4, beta: 7 -> 4; each deleted run drops 3 evidence rows.
    assert counts == {
        "provider_runs": 7,
        "provider_evidence": 21,
        "snapshots": 22,
    }
    per_provider = dict(
        seeded.conn.execute(
            "SELECT provider_name, COUNT(*) FROM provider_runs GROUP BY provider_name"
        ).fetchall()
    )
    assert per_provider == {"alpha": 4, "beta": 4}
    kept_alpha = {
        row[0] for row in seeded.conn.execute(
            "SELECT id FROM provider_runs WHERE provider_name = 'alpha'"
        )
    }
    assert kept_alpha == {"run_a_04", "run_a_05", "run_a_06", "run_a_07"}
    kept_beta = {
        row[0] for row in seeded.conn.execute(
            "SELECT id FROM provider_runs WHERE provider_name = 'beta'"
        )
    }
    assert kept_beta == {"run_b_03", "run_b_04", "run_b_05", "run_b_06"}

    # Evidence survives only for surviving runs.
    orphan_evidence = seeded.conn.execute(
        "SELECT COUNT(*) FROM provider_evidence WHERE run_id NOT IN "
        "(SELECT id FROM provider_runs)"
    ).fetchone()[0]
    assert orphan_evidence == 0
    remaining_evidence = seeded.conn.execute(
        "SELECT COUNT(*) FROM provider_evidence"
    ).fetchone()[0]
    assert remaining_evidence == (4 + 4) * 3

    # Newest 5 snapshots survive by recency, the 3 referenced ones by
    # reference (they are the OLDEST — recency cannot explain them).
    surviving = {
        row[0] for row in seeded.conn.execute("SELECT id FROM snapshots")
    }
    assert surviving == {
        f"snap_{i:02d}" for i in range(25, 30)
    } | {"snap_00", "snap_01", "snap_02"}


def test_purge_history_is_idempotent_when_within_retention(seeded):
    seeded.purge_history(keep_runs=4, keep_snapshots=5)
    second_pass = seeded.purge_history(keep_runs=4, keep_snapshots=5)
    assert second_pass == {
        "provider_runs": 0,
        "provider_evidence": 0,
        "snapshots": 0,
    }
    assert seeded.conn.execute(
        "SELECT COUNT(*) FROM provider_runs"
    ).fetchone()[0] == 8


def test_purge_history_keeps_newest_per_repo_root(db):
    for i in range(4):
        _insert_snapshot(db, f"left_{i}", captured_at=i + 1, repo_root="/left")
        _insert_snapshot(db, f"right_{i}", captured_at=i + 1, repo_root="/right")
    counts = db.purge_history(keep_runs=10, keep_snapshots=2)
    assert counts == {"provider_runs": 0, "provider_evidence": 0, "snapshots": 4}
    surviving = {
        row[0] for row in db.conn.execute("SELECT id FROM snapshots")
    }
    assert surviving == {"left_2", "left_3", "right_2", "right_3"}


def test_purge_history_empty_ledger_is_a_noop(db):
    assert db.purge_history() == {
        "provider_runs": 0,
        "provider_evidence": 0,
        "snapshots": 0,
    }
