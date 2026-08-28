"""sot_graph.assurance.receipts — impact receipts with schema + digest (P7).

Two receipt kinds, never interchangeable:

- :func:`scope_receipt` (PRE-change): the bounded, evidenced picture of
  a target BEFORE an edit — resolved identity, snapshot binding, source
  anchors, direct callers/callees, relations, bounded transitive
  impact, affected files, candidate tests, ledger cross-check, coverage
  and gaps, risk-based assurance rules, and the OMP confirmations the
  operator still owes. Its ``proof_scope`` is ``pre_change_only``: it
  can never substitute for post-change proof.
- :func:`diff_impact_receipt` (POST-change): wraps the diff-impact
  engine result with a post-change snapshot, invalidated-evidence
  markers, reconcile outcome, remaining gaps, and an explicit closure
  decision.

Both carry ``schema_version`` and a deterministic ``digest`` (canonical
JSON → sha256) so a receipt can be stored, diffed, and re-verified.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence

from dataclasses import asdict
from .coverage import coverage_note, repo_coverage
from .engine import assured_query_context, resolve_symbol_identity
from .ledger import union_evidence
from .state import CANONICAL_STATUSES, AssuranceFacts, decide

__all__ = [
    "receipt_digest",
    "scope_receipt",
    "diff_impact_receipt",
    "classify_change_risk",
    "check_rename_gate",
    "omp_confirmations_for",
    "decide",
    "AssuranceFacts",
    "CANONICAL_STATUSES",
    "resolve_symbol_identity",
    "RECEIPT_SCHEMA_VERSION",
]
RECEIPT_SCHEMA_VERSION = "1.1"  # minor bump: canonical status vocabulary (P0)


_RELATION_FAMILIES = {
    "imports": ("imports",),
    "inheritance": ("extends", "implements"),
}

_TEST_PATH_MARKERS = ("test", "spec")


#: Snapshot fields that change between captures of the SAME worktree
#: state (wall clock, generated id). They stay in the payload for
#: operators but never enter the digest: two receipts of one unchanged
#: state must share a digest (final gate: 100 lifecycle integrity runs).
_VOLATILE_SNAPSHOT_KEYS = ("captured_at", "snapshot_id")


def _strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _strip_volatile(v)
            for k, v in value.items()
            if k not in _VOLATILE_SNAPSHOT_KEYS
        }
    if isinstance(value, list):
        return [_strip_volatile(v) for v in value]
    return value


def receipt_digest(payload: Dict[str, Any]) -> str:
    """Deterministic digest over canonical JSON (sorted keys, no spaces).

    Wall-clock fields (snapshot captured_at, generated snapshot ids) are
    excluded: the digest describes the evidenced STATE, not the moment
    of capture.
    """
    canonical = json.dumps(_strip_volatile(payload), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False,
                           default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _node_row(db: Any, symbol: str) -> Optional[Dict[str, Any]]:
    row = db.get_node_by_symbol(symbol)
    if row is None:
        return None
    return row


def _edges_of(db: Any, node_id: str, direction: str,
              relations: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """One-hop edges by direction; optionally filtered by relation."""
    if direction == "out":
        sql = ("SELECT e.relation, e.line, n.id, n.path, n.kind, n.symbol "
               "FROM graph_edges e JOIN graph_nodes n ON e.dst = n.id "
               "WHERE e.src = ?")
    else:
        sql = ("SELECT e.relation, e.line, n.id, n.path, n.kind, n.symbol "
               "FROM graph_edges e JOIN graph_nodes n ON e.src = n.id "
               "WHERE e.dst = ?")
    params: List[Any] = [node_id]
    if relations:
        marks = ",".join("?" for _ in relations)
        sql += f" AND e.relation IN ({marks})"
        params.extend(relations)
    sql += " ORDER BY n.path, n.symbol LIMIT 500"
    try:
        rows = db.conn.execute(sql, params).fetchall()
    except Exception:  # noqa: BLE001 - receipt must not crash on storage
        return []
    return [
        {"relation": r[0], "line": r[1], "id": r[2],
         "path": r[3], "kind": r[4], "symbol": r[5]}
        for r in rows
    ]


def _looks_like_test(path: str, symbol: str) -> bool:
    low = path.replace("\\", "/").lower()
    return any(m in low for m in _TEST_PATH_MARKERS) or symbol.startswith("test_")


def _ledger_cross_check(db: Any, repo_root: str, limit: int = 5) -> Dict[str, Any]:
    """Recent successful provider runs + union conflicts for the receipt."""
    try:
        runs = db.conn.execute(
            "SELECT id, provider_name, provider_version, capability, "
            "snapshot_hash, status FROM provider_runs "
            "WHERE status = 'ok' ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    except Exception:  # noqa: BLE001
        runs = []
    union = union_evidence(db, repo_root)
    usable = [e for e in union if not e.get("error")]
    conflicts = [e for e in usable if e.get("conflict")]
    # P0 Contract 1: any union entry not fully SUPPORTED is unresolved
    # evidence (source_verified?/CONFLICT/etc.) and counts against the
    # evidence budget.
    unresolved = len([e for e in usable if e.get("status") != "SUPPORTED"])
    return {
        "runs": [
            {"run_id": r[0], "provider": r[1], "version": r[2],
             "capability": r[3], "snapshot": r[4]}
            for r in runs
        ],
        "union_entries": len(usable),
        "open_conflicts": len(conflicts),
        "unresolved_count": unresolved,
    }


def classify_change_risk(*, kind_of_change: str, symbol_kind: str = "",
                         touches_auth: bool = False,
                         dynamic_heavy: bool = False) -> Dict[str, Any]:
    """Risk-based assurance rules (roadmap §R7.3).

    Returns the required assurance level, whether a security reviewer is
    needed, and whether absence claims are forbidden for this change.
    """
    if touches_auth:
        return {
            "level": "audit", "security_reviewer": True,
            "absence_assurance": False,
            "rule": "auth/tenant → audit + security reviewer",
        }
    if dynamic_heavy:
        return {
            "level": "audit", "security_reviewer": False,
            "absence_assurance": False,
            "rule": "dynamic-heavy → no absence assurance",
        }
    if kind_of_change in ("rename", "delete", "public-api"):
        return {
            "level": "audit", "security_reviewer": False,
            "absence_assurance": True,
            "rule": "public API/rename/delete → audit",
        }
    if symbol_kind in ("class", "interface", "trait", "struct"):
        return {
            "level": "audit", "security_reviewer": False,
            "absence_assurance": True,
            "rule": "type surface (class/interface) → audit",
        }
    return {
        "level": "verify", "security_reviewer": False,
        "absence_assurance": True,
        "rule": "local body → verify",
    }


def check_rename_gate(db: Any, repo_root: str, symbol: str) -> Dict[str, Any]:
    """Blocking gate for public renames (P7 exit gate).

    A rename is blocked while CALLER COVERAGE is insufficient: '0
    callers' may only be claimed inside a bounded assured scope with
    measured coverage — never as a repo-wide negative claim.
    """
    row = _node_row(db, symbol)
    if row is None:
        return {
            "symbol": symbol, "resolved": False,
            "blocked": True,
            "reason": f"target {symbol!r} not found in graph; cannot bound "
                      "the rename scope",
        }
    node_id = str(row.get("id") or row.get("node_id") or "")
    callers = _edges_of(db, node_id, "in", ("calls", "call_reference", "usage"))
    report = repo_coverage(db, repo_root)
    covered = report.covered_fraction
    files_touched = {row.get("path")} | {c["path"] for c in callers}
    scoped = repo_coverage(db, repo_root, paths=sorted(
        p for p in files_touched if p))
    scoped_fraction = scoped.covered_fraction
    sufficient = (
        covered is not None and covered >= 0.9
        and (scoped_fraction is None or scoped_fraction >= 0.9)
    )
    zero_callers = len(callers) == 0
    if zero_callers and not sufficient:
        return {
            "symbol": symbol, "resolved": True, "blocked": True,
            "callers_found": 0,
            "coverage": covered, "scoped_coverage": scoped_fraction,
            "reason": "0 callers is NOT claimable: index coverage below "
                      "floor — absence only holds within a bounded, "
                      "measured scope",
        }
    return {
        "symbol": symbol, "resolved": True, "blocked": False,
        "callers_found": len(callers),
        "coverage": covered, "scoped_coverage": scoped_fraction,
        "reason": (
            f"{len(callers)} caller(s) resolved inside covered scope"
            if not zero_callers
            else "0 callers within bounded assured scope (coverage floor met)"
        ),
    }


def omp_confirmations_for(risk: Dict[str, Any], gate: Dict[str, Any]) -> List[str]:
    """Confirmations the OMP operator still owes before/after the edit."""
    items: List[str] = []
    if gate.get("blocked"):
        items.append(
            f"resolve rename gate for {gate.get('symbol')!r}: {gate.get('reason')}"
        )
    if risk.get("security_reviewer"):
        items.append("security reviewer sign-off required (auth/tenant touched)")
    if not risk.get("absence_assurance"):
        items.append(
            "no absence claims: dynamic-heavy scope forbids '0 callers'-style "
            "statements"
        )
    items.append("run targeted tests and attach the post-change diff receipt")
    return items


def scope_receipt(
    db: Any,
    repo_root: str,
    target: str,
    *,
    depth: int = 2,
    kind_of_change: str = "local-body",
    touches_auth: bool = False,
    dynamic_heavy: bool = False,
) -> Dict[str, Any]:
    """PRE-change receipt for one edit target (P7.1, P0 Contract 1+3).

    Identity resolution is a DECISION (UNIQUE/AMBIGUOUS/NOT_FOUND, exact
    match only); an ambiguous or missing target ABSTAINS the receipt with
    an explicit reason code instead of silently picking ``LIMIT 1``.
    """
    identity = resolve_symbol_identity(db, target)
    identity_status = identity["status"]
    row = identity["selected"]
    cited_paths = [row["path"]] if row else []
    snapshot_dict, stale_files = assured_query_context(
        db, repo_root, cited_paths,
    )
    # P0 Contract 2 (A2 wires content binding): scope_digest present and
    # non-null means the snapshot bound the cited file CONTENT; absent key
    # (pre-A2 snapshot) is legacy-safe pass-through.
    snapshot_bound = (
        bool(snapshot_dict.get("scope_digest"))
        if "scope_digest" in snapshot_dict else True
    )
    node_id = str((row or {}).get("id") or (row or {}).get("node_id") or "")
    callers = _edges_of(db, node_id, "in") if node_id else []
    callees = _edges_of(db, node_id, "out") if node_id else []
    relations: Dict[str, List[Dict[str, Any]]] = {
        name: (
            _edges_of(db, node_id, "out", rels) + _edges_of(db, node_id, "in", rels)
            if node_id else []
        )
        for name, rels in _RELATION_FAMILIES.items()
    }
    transitive: List[Dict[str, Any]] = []
    if node_id:
        try:
            transitive = db.explore_node(node_id, depth=depth, limit=200)
        except Exception:  # noqa: BLE001
            transitive = []
    affected_files = sorted({
        (row or {}).get("path"),
        *(c["path"] for c in callers + callees),
        *(r["path"] for r in transitive if r.get("path")),
    } - {None})
    candidate_tests = sorted({
        c["path"] for c in callers
        if _looks_like_test(str(c.get("path") or ""), str(c.get("symbol") or ""))
    } | {
        f for f in affected_files if _looks_like_test(f, "")
    })
    cov = repo_coverage(db, repo_root)
    ledger = _ledger_cross_check(db, repo_root)
    risk = classify_change_risk(
        kind_of_change=kind_of_change,
        symbol_kind=(row or {}).get("kind") or "",
        touches_auth=touches_auth,
        dynamic_heavy=dynamic_heavy,
    )
    gate = (check_rename_gate(db, repo_root, target)
            if kind_of_change in ("rename", "delete") else
            {"symbol": target, "resolved": row is not None, "blocked": False,
             "reason": "rename gate not applicable"})
    truncated = len(transitive) >= 200
    # Absence claim: the receipt's conclusion would rest on a negative
    # claim (rename/delete gate with 0 callers, or a kind whose rule
    # permits absence assurance) while the graph shows no callers.
    absence_claim = bool(risk.get("absence_assurance")) and len(callers) == 0
    facts = AssuranceFacts(
        identity_status=identity_status,
        snapshot_bound=snapshot_bound,
        stale_files=list(stale_files),
        coverage_measured=cov.basis == "measured",
        coverage_fraction=cov.covered_fraction,
        parser_failures=0,  # no parser-status source yet (P0 honest default)
        unresolved_count=int(ledger.get("unresolved_count") or 0),
        unresolved_budget=0,
        open_conflicts=int(ledger.get("open_conflicts") or 0),
        truncated=truncated,
        provider_capability_ok=True,  # no provider policy wired into receipts
        absence_claim=absence_claim,
        gate_blocked=bool(gate.get("blocked")),
    )
    decision = decide(facts)
    payload: Dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "kind": "scope",
        "proof_scope": "pre_change_only",
        "request": {
            "target": target,
            "kind_of_change": kind_of_change,
            "depth": depth,
            "touches_auth": touches_auth,
            "dynamic_heavy": dynamic_heavy,
        },
        "identity": {
            "status": identity_status,
            "candidates": identity["candidates"],
            "selected": row,
        },
        "assurance_facts": asdict(facts),
        "snapshot": snapshot_dict,
        "stale_files": stale_files,
        "source_anchors": (
            [{"path": row["path"], "line_start": row.get("line_start"),
              "line_end": row.get("line_end"), "symbol": row.get("symbol")}]
            if row else []
        ),
        "direct_callers": callers,
        "direct_callees": callees,
        "relations": relations,
        "transitive_impact": {
            "depth": depth,
            "nodes": transitive,
            "truncated": truncated,
        },
        "affected_files": affected_files,
        "candidate_tests": candidate_tests,
        "providers": ledger,
        "coverage": {
            "note": coverage_note(cov),
            "basis": cov.basis,
            "gaps": sorted(cov.gaps),
        },
        "assurance": {
            "risk": risk,
            "rename_gate": gate,
            "omp_confirmations": omp_confirmations_for(risk, gate),
            "status": decision["status"],
            "reason_codes": decision["reason_codes"],
            "decision": decision,
        },
    }
    payload["digest"] = receipt_digest(
        {k: v for k, v in payload.items() if k != "digest"}
    )
    return payload


def _jsonable(value: Any) -> Any:
    """Normalize an engine row to a JSON-safe dict (P0 contract sync)."""
    to_dict = getattr(value, "to_dict", None)
    return to_dict() if callable(to_dict) else value


def diff_impact_receipt(
    db: Any,
    repo_root: str,
    *,
    target: str = "HEAD~1",
    depth: int = 2,
    staged: bool = False,
    working_tree: bool = False,
    pre_receipt: Optional[Dict[str, Any]] = None,
    pre_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """POST-change receipt wrapping the diff-impact engine (P7.2, P0).

    The pre-change receipt may be attached for cross-reference only —
    its ``proof_scope`` forbids using it as post-change proof; this
    receipt always binds a fresh post-change snapshot, with the changed
    files as cited paths so ``scope_digest`` pins the POST-change file
    content (P0 Contract 2). ``pre_snapshot`` (captured BEFORE
    auto-reconcile) is embedded volatile-stripped for digest cross-ref.
    """
    from sot_graph.diff_impact import analyze_diff_impact
    from sot_graph.snapshot import capture_worktree_snapshot

    result = analyze_diff_impact(
        db, repo_path=repo_root, target=target, depth=depth,
        staged=staged, working_tree=working_tree,
    )
    changed_files = [str(p) for p in (getattr(result, "changed_files", None) or [])]
    post_snapshot = capture_worktree_snapshot(
        repo_root, role="post_change",
        cited_paths=changed_files[:200] or None,
    )
    # Evidence invalidated by the diff: rows bound to changed paths.
    invalidated: List[Dict[str, Any]] = []
    try:
        for path in changed_files[:200]:
            rows = db.conn.execute(
                "SELECT id, provider_name, snapshot_hash FROM provider_evidence "
                "WHERE path = ? LIMIT 50", (path,),
            ).fetchall()
            invalidated.extend(
                {"id": r[0], "provider": r[1], "snapshot": r[2], "path": path}
                for r in rows
            )
    except Exception:  # noqa: BLE001
        pass

    test_impacts = getattr(result, "test_impacts", None) or []
    summary = getattr(result, "summary", None)
    summary_dict = summary if isinstance(summary, dict) else getattr(
        summary, "to_dict", lambda: {} )()
    open_omp = []
    # P0 Contract 2: post snapshot binds content only when cited paths
    # were supplied AND all were readable; empty diff -> nothing to bind.
    post_ps = (
        post_snapshot if isinstance(post_snapshot, dict)
        else post_snapshot.as_dict()
    )
    snapshot_bound = bool(post_ps.get("scope_digest"))
    facts = AssuranceFacts(
        identity_status="UNIQUE",  # diff target is a revision, not a symbol
        snapshot_bound=snapshot_bound,
        stale_files=list(changed_files),  # post-change: cited disk state vs journal
        coverage_measured=False,  # coverage is a pre-change scope concept
        coverage_fraction=None,
        parser_failures=0,  # no parser-status source yet (P0 honest default)
        unresolved_count=len(invalidated),
        unresolved_budget=0,
        open_conflicts=0,
        truncated=False,
        provider_capability_ok=True,
        absence_claim=False,
        gate_blocked=False,
    )
    decision = decide(facts)
    if pre_receipt is not None:
        open_omp = list(
            pre_receipt.get("assurance", {}).get("omp_confirmations", [])
        )
    remaining_gaps: List[str] = []
    if invalidated:
        remaining_gaps.append(
            f"{len(invalidated)} provider-evidence row(s) invalidated by the "
            "diff; re-run the owning provider before trusting federated "
            "verdicts"
        )
    if open_omp:
        remaining_gaps.append(f"{len(open_omp)} OMP confirmation(s) still open")
    closure = "closed" if decision["status"] == "ASSURED_WITHIN_SCOPE" else "open"
    payload: Dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "kind": "diff_impact",
        "proof_scope": "post_change",
        "diff_identity": {
            "target": target, "staged": staged, "working_tree": working_tree,
        },
        "changed_files": changed_files,
        "direct_nodes": [_jsonable(n) for n in
                         (getattr(result, "direct_nodes", None) or [])],
        "caller_impacts": [_jsonable(c) for c in
                           (getattr(result, "caller_impacts", None) or [])],
        "test_impacts": [_jsonable(t) for t in test_impacts],
        "api_impacts": [_jsonable(a) for a in
                        (getattr(result, "api_impacts", None) or [])],
        "tests_to_run": sorted({
            str(t.get("test_file") if isinstance(t, dict)
               else getattr(t, "test_file", None))
            for t in test_impacts
        } - {""}) if test_impacts else [],

        "invalidated_evidence": invalidated,
        "post_change_snapshot": (
            post_snapshot if isinstance(post_snapshot, dict)
            else post_snapshot.as_dict()
        ),
        "reconcile": {"required": True,
                      "note": "run `sot reconcile` to bind the post-change "
                              "snapshot to a fresh index generation"},
        "summary": summary_dict,
        "pre_receipt_digest": (pre_receipt or {}).get("digest"),
        "pre_change_snapshot": (
            _strip_volatile(pre_snapshot) if pre_snapshot else None
        ),
        "remaining_gaps": remaining_gaps,
        "closure_decision": closure,
        "omp_confirmations_remaining": open_omp,
        "assurance_facts": asdict(facts),
        "assurance": {
            "status": decision["status"],
            "reason_codes": decision["reason_codes"],
            "decision": decision,
        },
    }
    payload["digest"] = receipt_digest(
        {k: v for k, v in payload.items() if k != "digest"}
    )
    return payload
