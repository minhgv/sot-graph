"""sot_graph.providers.cross_check — builtin vs external evidence reconciliation.

READ-ONLY diagnostic (R4, reworked in SG-203): compares the builtin AST
extractor's evidence (``graph_edges`` resolved through ``graph_nodes``)
against external provider evidence (``provider_evidence`` joined to
``provider_runs``). Never writes, never invokes a provider —
classification only.

SG-203 contract — joins are identity-based, never raw-string based:

- Both sides are adapted onto canonical
  :class:`~sot_graph.assurance.identity.SymbolIdentity` tuples via
  :mod:`sot_graph.providers.identity_join` *before* any comparison. The
  legacy behavior (comparing ``graph_edges`` node IDs against provider
  symbol strings by string equality) joined different identity spaces by
  accident; a string that merely looks equal across spaces now resolves
  to nothing.
- Endpoints that cannot be canonicalized land in ``unresolved_builtin`` /
  ``unresolved_external`` — counted and sampled, never joined.

Relations from both sides are folded through
:func:`sot_graph.providers.normalization.resolve_mapping` so provider
vocabularies ("call", "call:out", "inherits", SCIP shapes) and builtin
relations ("calls", "extends", ...) compare on canonical terms; unknown
relations fall back to ``UPPER(raw)`` so novel edges still pair
deterministically.

Buckets:
- ``agreements``    — both sides claim the identity pair (or definition).
- ``builtin_only``  — the AST graph claims it, no external provider does.
- ``external_only`` — an external provider claims it, the AST graph does
  not: a candidate hallucination OR a builtin parser gap; the diagnostic
  never decides which — it surfaces them for review.
- ``conflicts``     — the sides join on identity but disagree on relation
  or span. When ``repo_root`` is given each span conflict is adjudicated
  against the filesystem: the side whose span still verifies on disk
  wins; unverifiable conflicts stay ``open``. Conflicts are surfaced,
  never silently overwritten.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from sot_graph.assurance.identity import Span
from sot_graph.providers.identity_join import (
    builtin_identity,
    cross_join_key,
    evidence_identity,
    identity_summary,
    span_conflict,
)
from sot_graph.providers.normalization import resolve_mapping

__all__ = ["canonical_relation", "cross_check"]

#: Maximum entries embedded per bucket in the returned payload; totals are
#: always exact so CI gates can use the counts while payloads stay bounded
#: (same accounting contract as the SG-107 receipt collectors).
DEFAULT_SAMPLE_LIMIT = 200

_DEFINES_RELATIONS = {"DEFINES", "DEFINITION"}


def canonical_relation(raw: Any) -> str:
    """Fold one raw relation name (builtin or provider) onto canonical terms.

    CBM direction-suffixed call relations (``call:out``/``call:in``) fold
    onto ``CALLS`` — the direction is a reporting detail of one provider,
    not a different relation.
    """
    if not isinstance(raw, str) or not raw.strip():
        return ""
    cleaned = raw.strip()
    lowered = cleaned.lower()
    if lowered.startswith("call:"):
        cleaned = "call"
    mapping = resolve_mapping(cleaned)
    if mapping is not None:
        return mapping.canonical_relation
    return cleaned.upper()


def _load_builtin_claims(
    conn: sqlite3.Connection,
    repo_root: Optional[str],
) -> Tuple[Dict[Tuple[Tuple[str, str, str], Tuple[str, str, str], str],
                 Dict[str, Any]],
           Dict[Tuple[str, str, str], Dict[str, Any]],
           List[Dict[str, Any]]]:
    """Resolve builtin edges into identity-keyed pair + definition claims.

    Returns (pair_claims, definition_claims, unresolved_samples). Pair
    claims are keyed by ``(src_join_key, dst_join_key, relation)``;
    definition claims (``defines`` edges) by the defined symbol's join
    key. Edges whose endpoints no longer resolve to nodes are unresolved.
    """
    # Definition keys are cross_join_key tuples (3-part), same as pair
    # endpoint keys — the join-key SHAPE, not a plain string.
    # Pair keys: (src join key, dst join key, relation).
    pairs: Dict[
        Tuple[Tuple[str, str, str], Tuple[str, str, str], str],
        Dict[str, Any]] = {}
    definitions: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    unresolved: List[Dict[str, Any]] = []
    query = (
        "SELECT e.src, e.dst, e.relation, "
        "ns.path, ns.fqn, ns.symbol, ns.kind, ns.line_start, ns.line_end, "
        "nd.path, nd.fqn, nd.symbol, nd.kind, nd.line_start, nd.line_end "
        "FROM graph_edges e "
        "LEFT JOIN graph_nodes ns ON e.src = ns.id "
        "LEFT JOIN graph_nodes nd ON e.dst = nd.id"
    )
    for row in conn.execute(query):
        (src_id, dst_id, relation, sp, sfqn, ssym, skind, ssl, sse,
         dp, dfqn, dsym, dkind, dsl, dse) = row
        src_node = {"path": sp, "fqn": sfqn, "symbol": ssym, "kind": skind,
                    "line_start": ssl, "line_end": sse}
        dst_node = {"path": dp, "fqn": dfqn, "symbol": dsym, "kind": dkind,
                    "line_start": dsl, "line_end": dse}
        src_idn = builtin_identity(src_node, repo_root) if sp is not None else None
        dst_idn = builtin_identity(dst_node, repo_root) if dp is not None else None
        canonical = canonical_relation(relation)
        if canonical in _DEFINES_RELATIONS:
            if dst_idn is None:
                unresolved.append({"src": src_id, "dst": dst_id,
                                   "relation": relation or ""})
                continue
            key = cross_join_key(dst_idn)
            entry = definitions.setdefault(key, {
                "identity": dst_idn, "builtin_count": 0})
            entry["builtin_count"] += 1
            continue
        if src_idn is None or dst_idn is None:
            unresolved.append({"src": src_id, "dst": dst_id,
                               "relation": relation or ""})
            continue
        key = (cross_join_key(src_idn), cross_join_key(dst_idn), canonical)
        entry = pairs.setdefault(key, {
            "src": src_idn, "dst": dst_idn, "relation": canonical,
            "builtin_count": 0})
        entry["builtin_count"] += 1
    return pairs, definitions, unresolved


def _load_external_claims(
    conn: sqlite3.Connection,
    provider: Optional[str],
    repo_root: Optional[str],
) -> Tuple[Dict[Tuple[Tuple[str, str, str], Tuple[str, str, str], str],
                 Dict[str, Any]],
           Dict[Tuple[str, str, str], Dict[str, Any]],
           Dict[str, int],
           List[Dict[str, Any]],
           int]:
    """Aggregate live provider evidence into identity-keyed claims.

    Returns (pair_claims, definition_claims, provider_counts,
    unresolved_samples, unmapped_relation_rows). Invalidated rows are
    dead evidence and excluded; destination prefers ``dst_symbol`` with
    ``target_symbol`` fallback (adapters populate either).
    """
    # Definition keys are cross_join_key tuples (3-part), same as pair
    # endpoint keys — the join-key SHAPE, not a plain string.
    # Pair keys: (src join key, dst join key, relation).
    pairs: Dict[
        Tuple[Tuple[str, str, str], Tuple[str, str, str], str],
        Dict[str, Any]] = {}
    definitions: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    counts: Dict[str, int] = {}
    unresolved: List[Dict[str, Any]] = []
    unmapped = 0
    query = (
        "SELECT pr.provider_name, pe.src_symbol, pe.symbol, "
        "COALESCE(pe.dst_symbol, pe.target_symbol), pe.relation, "
        "pe.path, pe.syntax_kind, pe.line_start, pe.line_end "
        "FROM provider_evidence pe "
        "JOIN provider_runs pr ON pe.run_id = pr.id "
        "WHERE pe.invalidated_at IS NULL"
    )
    params: Tuple[Any, ...] = ()
    if provider:
        query += " AND pr.provider_name = ?"
        params = (provider,)
    for (prov_name, src_qualified, src_bare, dst, relation, path,
         syntax_kind, line_start, line_end) in conn.execute(query, params):
        if resolve_mapping(relation) is None:
            unmapped += 1
        counts[prov_name] = counts.get(prov_name, 0) + 1
        src_symbol = src_qualified or src_bare
        span = Span(int(line_start), int(line_end)) \
            if line_start is not None else None
        canonical = canonical_relation(relation)
        if canonical in _DEFINES_RELATIONS:
            idn = evidence_identity(
                prov_name, src_symbol, path=path, kind_hint=syntax_kind,
                span=span, repo_root=repo_root,
            )
            if idn is None:
                unresolved.append({"provider": prov_name,
                                   "symbol": src_symbol or "",
                                   "relation": relation or "", "path": path or ""})
                continue
            key = cross_join_key(idn)
            entry = definitions.setdefault(key, {
                "identity": idn, "providers": set(), "count": 0})
            entry["providers"].add(prov_name)
            entry["count"] += 1
            continue
        if dst is None:
            continue  # no target identity: pairs with nothing, by contract
        src_idn = evidence_identity(
            prov_name, src_symbol, path=path, kind_hint=syntax_kind,
            span=span, repo_root=repo_root,
        )
        dst_idn = evidence_identity(
            prov_name, dst, path=path, repo_root=repo_root,
        )
        if src_idn is None or dst_idn is None:
            unresolved.append({"provider": prov_name, "symbol": src_symbol or "",
                               "target": dst, "relation": relation or "",
                               "path": path or ""})
            continue
        key = (cross_join_key(src_idn), cross_join_key(dst_idn), canonical)
        entry = pairs.setdefault(key, {
            "src": src_idn, "dst": dst_idn, "relation": canonical,
            "providers": set(), "count": 0, "span": span,
        })
        entry["providers"].add(prov_name)
        entry["count"] += 1
    return pairs, definitions, counts, unresolved, unmapped


def _adjudicate_span_conflict(
    builtin_span: Optional[Span], external_span: Optional[Span],
    path: Optional[str], fqn: str, repo_root: str,
) -> str:
    """Pick the span that still verifies on disk; never overwrite silently."""
    from sot_graph.providers.verification import verify_subject

    def _verifies(span: Optional[Span]) -> bool:
        if span is None or span.start_line is None:
            return False
        subject = {
            "path": path or "", "qualified_name": fqn, "kind": "function",
            "start_line": int(span.start_line),
            "end_line": int(span.end_line or span.start_line),
        }
        try:
            outcome = verify_subject(subject, repo_root)
        except Exception:  # noqa: BLE001 - abstain on verifier error
            return False
        return outcome is not None and outcome.status == "VERIFIED"

    builtin_ok = _verifies(builtin_span)
    external_ok = _verifies(external_span)
    if builtin_ok and not external_ok:
        return "builtin_verified"
    if external_ok and not builtin_ok:
        return "external_verified"
    return "open"


def _external_relation_for(
    builtin_pair: Dict[str, Any],
    pair_index: Dict[
        Tuple[Tuple[str, str, str], Tuple[str, str, str]],
        Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Find the external claim joining the same identity pair (any relation)."""
    src_key = cross_join_key(builtin_pair["src"])
    dst_key = cross_join_key(builtin_pair["dst"])
    return pair_index.get((src_key, dst_key))


def _sample(bucket: List[Dict[str, Any]],
            sample_limit: int) -> Tuple[List[Dict[str, Any]], bool]:
    if sample_limit and len(bucket) > sample_limit:
        return bucket[:sample_limit], True
    return bucket, False


def cross_check(
    db: Any,
    provider: Optional[str] = None,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    repo_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Classify builtin vs external evidence into reconciliation buckets.

    Read-only: opens a cursor on ``db.conn`` (or accepts a raw connection)
    and never mutates state. ``provider`` restricts the external side to
    one provider name; ``sample_limit`` bounds each bucket's embedded
    sample (totals stay exact); ``repo_root`` enables repo-relative path
    normalization, CBM mangled-prefix stripping and span-conflict
    adjudication against the filesystem.
    """
    conn = db if isinstance(db, sqlite3.Connection) else db.conn

    builtin_pairs, builtin_defs, builtin_unresolved = _load_builtin_claims(
        conn, repo_root)
    ext_pairs, ext_defs, provider_counts, ext_unresolved, unmapped = \
        _load_external_claims(conn, provider, repo_root)

    agreements: List[Dict[str, Any]] = []
    builtin_only: List[Dict[str, Any]] = []
    external_only: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []

    # Index external pairs by identity pair (relation-free) so same-pair
    # relation disagreements surface as conflicts instead of two
    # disjoint "only" entries.
    ext_pair_index: Dict[
        Tuple[Tuple[str, str, str], Tuple[str, str, str]],
        Dict[str, Any]] = {}
    for entry in ext_pairs.values():
        ext_pair_index[
            (cross_join_key(entry["src"]), cross_join_key(entry["dst"]))
        ] = entry

    matched_external_keys = set()

    def _pair_payload(b_entry: Dict[str, Any], external: Optional[Dict[str, Any]]
                      ) -> Dict[str, Any]:
        payload = {
            "claim_type": "edge",
            "relation": b_entry["relation"] if external is None
            else external["relation"],
            "src": identity_summary(b_entry["src"]),
            "dst": identity_summary(b_entry["dst"]),
            "builtin_count": b_entry["builtin_count"],
        }
        if external is not None:
            payload["external_count"] = external["count"]
            payload["providers"] = sorted(external["providers"])
            payload["external_span"] = (
                [external["span"].start_line, external["span"].end_line]
                if external.get("span") and external["span"].start_line is not None
                else None
            )
            payload["builtin_span"] = [
                b_entry["src"].span.start_line if b_entry["src"].span else None,
                b_entry["src"].span.end_line if b_entry["src"].span else None,
            ]
        return payload

    for key, b_entry in builtin_pairs.items():
        external = ext_pairs.get(key)
        if external is not None:
            matched_external_keys.add(key)
            agreements.append(_pair_payload(b_entry, external))
            continue
        same_pair = _external_relation_for(b_entry, ext_pair_index)
        if same_pair is not None:
            matched_external_keys.add(
                (cross_join_key(same_pair["src"]),
                 cross_join_key(same_pair["dst"]), same_pair["relation"]))
            conflict = _pair_payload(b_entry, same_pair)
            conflict["conflict"] = {
                "reason": "relation_mismatch",
                "builtin_relation": b_entry["relation"],
                "external_relation": same_pair["relation"],
                "adjudication": "relation_mismatch",
            }
            conflicts.append(conflict)
            continue
        payload = _pair_payload(b_entry, None)
        payload["src"].pop("span", None)
        payload["dst"].pop("span", None)
        builtin_only.append(payload)

    for key, entry in ext_pairs.items():
        if key in matched_external_keys:
            continue
        external_only.append({
            "claim_type": "edge",
            "relation": entry["relation"],
            "src": identity_summary(entry["src"]),
            "dst": identity_summary(entry["dst"]),
            "external_count": entry["count"],
            "providers": sorted(entry["providers"]),
        })

    # Definition claims: joined on the single identity key.
    for key, b_entry in builtin_defs.items():
        external = ext_defs.get(key)
        if external is not None:
            agreements.append({
                "claim_type": "definition",
                "relation": "DEFINES",
                "identity": identity_summary(b_entry["identity"]),
                "builtin_count": b_entry["builtin_count"],
                "external_count": external["count"],
                "providers": sorted(external["providers"]),
            })
        else:
            summary = identity_summary(b_entry["identity"])
            summary.pop("span", None)
            builtin_only.append({
                "claim_type": "definition", "relation": "DEFINES",
                "identity": summary,
            })
    for key, entry in ext_defs.items():
        if key in builtin_defs:
            continue
        external_only.append({
            "claim_type": "definition", "relation": "DEFINES",
            "identity": identity_summary(entry["identity"]),
            "external_count": entry["count"],
            "providers": sorted(entry["providers"]),
        })

    # Span conflicts among edge agreements: same identity pair, disagreeing
    # spans — adjudicated against the current filesystem when possible.
    for agreement in agreements:
        if agreement.get("claim_type") != "edge":
            continue
        ext_span = agreement.get("external_span")
        builtin_span = agreement.get("builtin_span")
        if not ext_span or not builtin_span or builtin_span[0] is None:
            continue
        if not span_conflict(
            Span(builtin_span[0], builtin_span[1]),
            Span(ext_span[0], ext_span[1]),
        ):
            continue
        adjudication = "open"
        if repo_root:
            adjudication = _adjudicate_span_conflict(
                Span(builtin_span[0], builtin_span[1]),
                Span(ext_span[0], ext_span[1]),
                agreement["src"].get("path"),
                agreement["src"].get("fqn") or "", repo_root,
            )
        conflict = dict(agreement)
        conflict["conflict"] = {
            "reason": "span_disagreement",
            "builtin_span": builtin_span,
            "external_span": ext_span,
            "adjudication": adjudication,
        }
        conflicts.append(conflict)

    agreements.sort(key=lambda a: (
        a.get("claim_type", ""),
        (a.get("src") or a.get("identity") or {}).get("fqn", ""),
    ))
    builtin_only.sort(key=lambda a: (
        a.get("claim_type", ""),
        (a.get("src") or a.get("identity") or {}).get("fqn", ""),
    ))
    external_only.sort(key=lambda a: (
        a.get("claim_type", ""),
        (a.get("src") or a.get("identity") or {}).get("fqn", ""),
    ))

    sampled_agreements, ag_trunc = _sample(agreements, sample_limit)
    sampled_builtin, bo_trunc = _sample(builtin_only, sample_limit)
    sampled_external, eo_trunc = _sample(external_only, sample_limit)
    sampled_conflicts, cf_trunc = _sample(conflicts, sample_limit)
    sampled_bunres, bu_trunc = _sample(builtin_unresolved, sample_limit)
    sampled_eunres, eu_trunc = _sample(ext_unresolved, sample_limit)

    # Claims are deduplicated by identity key, so raw rows can exceed
    # distinct claims (e.g. two `defines` edges for one symbol). Surface
    # both sides of that arithmetic — never let rows silently vanish.
    builtin_edges_scanned = (
        sum(e["builtin_count"] for e in builtin_pairs.values())
        + sum(e["builtin_count"] for e in builtin_defs.values())
        + len(builtin_unresolved)
    )
    builtin_duplicate_edges = (
        sum(e["builtin_count"] - 1 for e in builtin_pairs.values())
        + sum(e["builtin_count"] - 1 for e in builtin_defs.values())
    )
    external_rows_scanned = sum(provider_counts.values())
    external_duplicate_rows = (
        sum(e["count"] - 1 for e in ext_pairs.values())
        + sum(e["count"] - 1 for e in ext_defs.values())
    )

    return {
        "read_only": True,
        "provider_filter": provider,
        "repo_root": repo_root,
        "identity_join": True,
        "builtin_pair_count": len(builtin_pairs),
        "builtin_definition_count": len(builtin_defs),
        "external_pair_count": len(ext_pairs),
        "external_definition_count": len(ext_defs),
        "agreements": sampled_agreements,
        "builtin_only": sampled_builtin,
        "external_only": sampled_external,
        "conflicts": sampled_conflicts,
        "unresolved_builtin": sampled_bunres,
        "unresolved_external": sampled_eunres,
        "totals": {
            "agreements": len(agreements),
            "builtin_only": len(builtin_only),
            "external_only": len(external_only),
            "conflicts": len(conflicts),
            "unresolved_builtin": len(builtin_unresolved),
            "unresolved_external": len(ext_unresolved),
            "builtin_pairs": len(builtin_pairs),
            "builtin_definitions": len(builtin_defs),
            "external_pairs": len(ext_pairs),
            "external_definitions": len(ext_defs),
            "builtin_edges_scanned": builtin_edges_scanned,
            "builtin_duplicate_edges": builtin_duplicate_edges,
            "external_rows_scanned": external_rows_scanned,
            "external_duplicate_rows": external_duplicate_rows,
            "sample_limit": sample_limit,
            "truncated": {
                "agreements": ag_trunc, "builtin_only": bo_trunc,
                "external_only": eo_trunc, "conflicts": cf_trunc,
                "unresolved_builtin": bu_trunc,
                "unresolved_external": eu_trunc,
            },
            "unmapped_external_relations": unmapped,
        },
        "provider_counts": dict(sorted(provider_counts.items())),
    }
