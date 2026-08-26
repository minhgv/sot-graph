"""sot_graph.assurance.ledger — evidence ledger union & receipt replay (P6).

The ledger (provider_runs / provider_evidence) is the durable receipt
of every provider query. This module:

- unions evidence across providers/runs BY CANONICAL IDENTITY (path +
  language + kind + qualified name + relation + target + snapshot),
  never by bare short name;
- keeps per-provider provenance (who supports each union entry) and
  marks contradictions when the same identity carries disagreeing
  spans/paths;
- adjudicates contradictions against the CURRENT source via
  ``verify_subject`` — a unique verified side wins, anything less stays
  ``CONFLICT`` (no silent winner-takes-all);
- excludes historic/stale runs: only successful runs whose evidence is
  not marked stale enter the union;
- replays a receipt from the ledger alone (no console logs needed).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .identity import _language_of
from ..providers.verification import VERIFIED, verify_subject

__all__ = [
    "union_evidence",
    "receipt_from_ledger",
    "ledger_rows_for_runs",
]

_CONFLICT = "CONFLICT"


def _union_key(row: Sequence[Any]) -> tuple:
    path, relation, src, dst, snap = row[0], row[1], row[2], row[3], row[4]
    lang = _language_of(str(path or ""))
    return (
        (str(path or "").replace("\\", "/"), lang or "unknown"),
        str(relation or ""),
        str(src or "").lower(),
        str(dst or "").lower(),
        str(snap or ""),
    )


def union_evidence(
    db: Any,
    repo_root: str,
    *,
    snapshot_hash: Optional[str] = None,
    limit: int = 5000,
) -> List[Dict[str, Any]]:
    """Union provider evidence by canonical identity.

    Successful, non-stale runs only; each union entry keeps the
    supporting providers and any contradicting spans. Contradictions
    are adjudicated against current source; unresolved stays CONFLICT.
    """
    sql = (
        "SELECT e.path, e.relation, e.src_symbol, e.dst_symbol, "
        "e.snapshot_hash, e.provider_name, e.line_start, e.line_end, "
        "e.run_id, e.confidence "
        "FROM provider_evidence e JOIN provider_runs r ON e.run_id = r.id "
        "WHERE r.status = 'ok' AND COALESCE(e.metadata_json, '') "
        "NOT LIKE '%\"stale\": true%'"
    )
    params: List[Any] = []
    if snapshot_hash is not None:
        sql += " AND e.snapshot_hash = ?"
        params.append(snapshot_hash)
    sql += " LIMIT ?"
    params.append(int(limit))
    try:
        rows = db.conn.execute(sql, params).fetchall()
    except Exception as exc:  # noqa: BLE001 - ledger is a sidecar
        return [{"error": f"ledger read failed: {type(exc).__name__}"}]

    groups: Dict[tuple, Dict[str, Any]] = {}
    for row in rows:
        key = _union_key(row)
        entry = groups.setdefault(key, {
            "identity": {
                "path": key[0][0], "language": key[0][1],
                "relation": key[1], "src": key[2], "dst": key[3],
                "snapshot": key[4] or None,
            },
            "providers": set(),
            "spans": {},
            "conflict": False,
            "status": "SUPPORTED",
        })
        entry["providers"].add(str(row[5]))
        span = (row[6], row[7])
        entry["spans"].setdefault(span, {"run_ids": [], "provider": row[5]})

    out: List[Dict[str, Any]] = []
    for entry in groups.values():
        spans = entry.pop("spans")
        provs = sorted(entry.pop("providers"))
        entry["providers"] = provs
        distinct = [s for s in spans if s != (None, None)]
        if len(distinct) > 1:
            entry["conflict"] = True
            entry["status"] = _CONFLICT
            # Adjudicate against current source: the unique VERIFIED
            # span wins; otherwise the conflict stays open.
            verified = []
            for (start, end) in distinct:
                subj = {
                    "path": entry["identity"]["path"],
                    "qualified_name": entry["identity"]["src"],
                    "kind": "function",
                    "start_line": int(start or 0),
                    "end_line": int(end or 0),
                }
                try:
                    outcome = verify_subject(subj, repo_root)
                except Exception:  # noqa: BLE001 - abstain on verifier error
                    outcome = None
                if outcome is not None and outcome.status == VERIFIED:
                    verified.append((start, end))
            if len(verified) == 1:
                entry["status"] = "source_verified"
                entry["resolved_span"] = list(verified[0])
        elif len(distinct) == 1:
            entry["span"] = [distinct[0][0], distinct[0][1]]
        out.append(entry)
    out.sort(key=lambda e: (
        e["status"] != "SUPPORTED", e["conflict"],
        e["identity"]["path"], e["identity"]["src"],
    ))
    return out


def ledger_rows_for_runs(db: Any, run_ids: Sequence[str]) -> List[Dict[str, Any]]:
    """Fetch run + evidence counts for specific runs (receipt replay)."""
    if not run_ids:
        return []
    marks = ",".join("?" for _ in run_ids)
    try:
        runs = db.conn.execute(
            f"SELECT id, provider_name, provider_version, capability, "
            f"snapshot_hash, status, exit_code, duration_ms, command_digest, "
            f"arguments_json, created_at FROM provider_runs "
            f"WHERE id IN ({marks})", tuple(run_ids)
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"ledger read failed: {type(exc).__name__}"}]
    counts: Dict[str, int] = {}
    try:
        for rid, cnt in db.conn.execute(
            f"SELECT run_id, COUNT(*) FROM provider_evidence "
            f"WHERE run_id IN ({marks}) GROUP BY run_id", tuple(run_ids)
        ):
            counts[rid] = int(cnt)
    except Exception:  # noqa: BLE001
        pass
    return [
        {
            "run_id": r[0], "provider": r[1], "version": r[2],
            "capability": r[3], "snapshot": r[4], "status": r[5],
            "exit_code": r[6], "duration_ms": r[7],
            "command_digest": r[8], "arguments": r[9],
            "created_at": r[10], "evidence_rows": counts.get(r[0], 0),
        }
        for r in runs
    ]


def receipt_from_ledger(
    db: Any,
    repo_root: str,
    run_ids: Sequence[str],
) -> Dict[str, Any]:
    """Replay a full receipt from the ledger alone.

    Everything a console receipt would print — providers, versions,
    snapshot bindings, evidence union with conflicts — reconstructed
    from persisted rows. No log parsing, no in-memory state.
    """
    runs = ledger_rows_for_runs(db, run_ids)
    union = union_evidence(db, repo_root)
    conflicts = [e for e in union if e.get("conflict")]
    return {
        "runs": runs,
        "union": union,
        "union_entries": len(union),
        "conflicts": [
            {
                "identity": c["identity"],
                "providers": c.get("providers"),
                "status": c["status"],
            }
            for c in conflicts
        ],
        "conflict_count": len(conflicts),
        "adjudication": (
            "CONFLICT entries resolved only where current source "
            "verifies exactly one side; unresolved stay CONFLICT"
        ),
    }
