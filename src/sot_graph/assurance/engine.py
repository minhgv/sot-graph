"""sot_graph.assurance.engine - shared query-assurance engine (P2, P0).

CLI and MCP both call :func:`assured_query_context` before returning
graph-derived answers, so snapshot capture and stale-evidence detection can
never drift between surfaces.
"""

from __future__ import annotations

import sys
from typing import Iterable, Optional, Tuple

__all__ = [
    "resolve_symbol",
    "resolve_symbol_identity",
    "assured_query_context",
    "stale_files_warning",
]


def resolve_symbol(db, query: str):
    """Resolve a query to one node row: ``(id, label, kind, path, line, symbol)``.

    Prefers exact symbol matches over file/doc nodes whose labels merely
    mention the query text.
    """
    row = db.conn.execute(
        "SELECT id, label, kind, path, line_start, symbol FROM graph_nodes "
        "WHERE symbol = ? LIMIT 1", (query,)
    ).fetchone()
    if not row:
        row = db.conn.execute(
            "SELECT id, label, kind, path, line_start, symbol FROM graph_nodes "
            "WHERE kind != 'file' AND (label LIKE ? OR fqn LIKE ?) "
            "ORDER BY kind LIMIT 1", (f"%{query}%", f"%{query}%")
        ).fetchone()
    return row


def resolve_symbol_identity(db, query: str) -> dict:
    """Resolve a query to a DECISION identity (P0 Contract 3).

    Exact match only: ``symbol == query`` OR ``fqn == query``. No LIKE,
    no ``LIMIT 1`` - ambiguity is surfaced, never buried.

    Returns ``{"status": "UNIQUE"|"AMBIGUOUS"|"NOT_FOUND",
    "candidates": [row-dict...], "selected": row-dict|None}``. Receipt
    decision paths use this; navigation callers keep :func:`resolve_symbol`.
    """
    columns = ("id", "label", "kind", "path", "line_start", "symbol", "fqn")
    try:
        rows = db.conn.execute(
            "SELECT id, label, kind, path, line_start, symbol, fqn "
            "FROM graph_nodes WHERE symbol = ? OR fqn = ?",
            (query, query),
        ).fetchall()
    except Exception:  # noqa: BLE001 - a broken graph resolves to NOT_FOUND
        rows = []
    candidates = [dict(zip(columns, r)) for r in rows]
    if not candidates:
        return {"status": "NOT_FOUND", "candidates": [], "selected": None}
    if len(candidates) > 1:
        return {
            "status": "AMBIGUOUS",
            "candidates": candidates,
            "selected": None,
        }
    return {
        "status": "UNIQUE",
        "candidates": candidates,
        "selected": candidates[0],
    }


def assured_query_context(
    db, root: str, cited_paths: Iterable[str] = (), *,
    mark_ledger: bool = True,
) -> Tuple[dict, list]:
    """P1.b/P1.c/P1.e shared pre-query assurance for builtin read paths.

    Captures the common worktree snapshot descriptor (HEAD sha, tri-state
    dirty flag, dirty fingerprint — read-only, no ledger write on a read
    path) and validates every cited file against the file journal. Stale
    files are MARKED in the evidence ledger (never deleted) so the ledger
    can distinguish pre-change from post-change evidence.

    ``cited_paths`` also feed the P0 content binding (Contract 2): each
    path is hashed into the snapshot's ``scope_digest`` so a receipt can
    prove WHICH file content it was captured against.

    ``mark_ledger=False`` is for read-only connections (MCP ``mode=ro``):
    staleness is still detected and reported, the ledger is not written.
    """
    from sot_graph.snapshot import capture_worktree_snapshot

    unique = sorted({str(p) for p in cited_paths if p})
    snapshot = capture_worktree_snapshot(root, cited_paths=unique or None)
    stale = db.stale_journal_files(unique, root=root) if unique else []
    if stale and mark_ledger:
        try:
            marked = db.mark_evidence_stale(
                stale, reason="journal mismatch: file changed since last reconcile"
            )
            if marked:
                print(
                    f"  ⚠ Marked {marked} evidence row(s) stale "
                    f"({len(stale)} file(s) changed since last reconcile)",
                    file=sys.stderr,
                )
        except Exception as exc:  # pragma: no cover - ledger marking is best-effort
            print(f"  ⚠ Evidence invalidation failed: {exc}", file=sys.stderr)
    return snapshot.as_dict(), stale


def stale_files_warning(stale: list) -> Optional[str]:
    if not stale:
        return None
    shown = ", ".join(stale[:5]) + ("…" if len(stale) > 5 else "")
    return (
        f"{len(stale)} cited file(s) changed since last reconcile ({shown}); "
        "run 'sot reconcile' — evidence for these paths is UNVERIFIABLE until then"
    )
