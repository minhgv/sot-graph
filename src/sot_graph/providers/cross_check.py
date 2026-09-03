"""sot_graph.providers.cross_check — builtin vs external evidence reconciliation.

READ-ONLY diagnostic (R4): compares the builtin AST extractor's evidence
(``graph_edges``) against external provider evidence (``provider_evidence``
joined to ``provider_runs`` for provider identity) on the overlap set of
``(src, dst, relation)``-shaped pairs. Never writes, never invokes a
provider — classification only.

Relations from both sides are folded through
:func:`sot_graph.providers.normalization.resolve_mapping` so provider
vocabularies ("call", "inherits", "definition", SCIP shapes) and builtin
relations ("calls", "extends", ...) compare on canonical terms; relations
unknown to the mapping table fall back to ``UPPER(raw)`` so novel edges
still pair deterministically instead of silently disagreeing.

Buckets:
- ``agreements``    — both the builtin graph and an external provider claim the pair.
- ``builtin_only``  — AST found it, no external provider did (typical for
  builtin-only indexes; uninteresting unless an external provider is synced).
- ``external_only`` — an external provider claims it, the AST graph does
  not. Each such pair is a candidate hallucination OR a builtin parser
  gap; the diagnostic never decides which — it surfaces them for review.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from sot_graph.providers.normalization import resolve_mapping

__all__ = ["canonical_relation", "cross_check"]

#: Maximum pairs embedded per bucket in the returned payload; totals are
#: always exact so CI gates can use the counts while payloads stay bounded.
DEFAULT_SAMPLE_LIMIT = 200


def canonical_relation(raw: Any) -> str:
    """Fold one raw relation name (builtin or provider) onto canonical terms."""
    if not isinstance(raw, str) or not raw.strip():
        return ""
    mapping = resolve_mapping(raw)
    if mapping is not None:
        return mapping.canonical_relation
    return raw.strip().upper()


def _load_builtin_pairs(conn: sqlite3.Connection) -> Dict[Tuple[str, str, str], int]:
    pairs: Dict[Tuple[str, str, str], int] = {}
    for src, dst, relation in conn.execute("SELECT src, dst, relation FROM graph_edges"):
        key = (str(src), str(dst), canonical_relation(relation))
        pairs[key] = pairs.get(key, 0) + 1
    return pairs


def _load_external_pairs(
    conn: sqlite3.Connection,
    provider: Optional[str],
) -> Tuple[Dict[Tuple[str, str, str], int], Dict[str, int], int]:
    """Aggregate live provider evidence into canonical pairs.

    Returns (pairs, per-provider counts, unmapped-relation row count).
    Rows with ``invalidated_at`` set are dead evidence and are excluded;
    the destination symbol prefers ``dst_symbol`` and falls back to
    ``target_symbol`` (adapters populate either).
    """
    pairs: Dict[Tuple[str, str, str], int] = {}
    counts: Dict[str, int] = {}
    unmapped = 0
    query = (
        "SELECT pr.provider_name, pe.src_symbol, "
        "COALESCE(pe.dst_symbol, pe.target_symbol), pe.relation "
        "FROM provider_evidence pe "
        "JOIN provider_runs pr ON pe.run_id = pr.id "
        "WHERE pe.invalidated_at IS NULL"
    )
    params: Tuple[Any, ...] = ()
    if provider:
        query += " AND pr.provider_name = ?"
        params = (provider,)
    for prov_name, src, dst, relation in conn.execute(query, params):
        if resolve_mapping(relation) is None:
            unmapped += 1
        counts[prov_name] = counts.get(prov_name, 0) + 1
        if dst is None:
            continue  # an evidence row without any target identity pairs with nothing
        key = (str(src), str(dst), canonical_relation(relation))
        pairs[key] = pairs.get(key, 0) + 1
    return pairs, counts, unmapped


def cross_check(
    db: Any,
    provider: Optional[str] = None,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> Dict[str, Any]:
    """Classify builtin vs external edge evidence into reconciliation buckets.

    Read-only: opens a cursor on ``db.conn`` (or accepts a raw connection)
    and never mutates state. ``provider`` restricts the external side to
    one provider name; ``sample_limit`` bounds each bucket's embedded
    sample (totals stay exact).
    """
    conn = db if isinstance(db, sqlite3.Connection) else db.conn

    builtin = _load_builtin_pairs(conn)
    external, provider_counts, unmapped = _load_external_pairs(conn, provider)

    agreements: List[Dict[str, Any]] = []
    builtin_only: List[Dict[str, Any]] = []
    external_only: List[Dict[str, Any]] = []

    # Which providers back each agreement — one pass over the external map.
    agreement_keys = builtin.keys() & external.keys()
    for key in sorted(agreement_keys):
        src, dst, relation = key
        agreements.append({
            "src": src, "dst": dst, "relation": relation,
            "builtin_count": builtin[key],
            "external_count": external[key],
        })
    for key in sorted(builtin.keys() - external.keys()):
        src, dst, relation = key
        builtin_only.append({"src": src, "dst": dst, "relation": relation})
    for key in sorted(external.keys() - builtin.keys()):
        src, dst, relation = key
        external_only.append({
            "src": src, "dst": dst, "relation": relation,
            "external_count": external[key],
        })

    def _sample(bucket: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return bucket[:sample_limit] if sample_limit and len(bucket) > sample_limit else bucket

    return {
        "read_only": True,
        "provider_filter": provider,
        "builtin_pair_count": len(builtin),
        "external_pair_count": len(external),
        "agreements": _sample(agreements),
        "builtin_only": _sample(builtin_only),
        "external_only": _sample(external_only),
        "totals": {
            "agreements": len(agreements),
            "builtin_only": len(builtin_only),
            "external_only": len(external_only),
            "sample_limit": sample_limit,
            "unmapped_external_relations": unmapped,
        },
        "provider_counts": dict(sorted(provider_counts.items())),
    }
