"""Federated provider orchestration (P2).

Moved — not copied — from private CLI helpers so CLI and MCP drive ONE
engine: plan negotiation, capability routing, typed provider outcomes,
candidate normalization, target-conflict adjudication, and the shared
federation result contract.
"""

from __future__ import annotations

import os
import re
from typing import Mapping, Optional

from .routing import (
    COMMAND_CAPABILITY,
    QUERYABLE_PROVIDERS,
    effective_provider_spec,
    parse_provider_spec,
    supports_capability,
)

__all__ = [
    "federation_plan",
    "run_federated_query",
    "federated_extras",
    "cbm_candidates_from_outcome",
    "target_conflicts",
    "envelope_fed_kwargs",
]

_SEARCH_ROW_LINES = re.compile(r"^\d+-\d+$")


def federation_plan(provider_spec: Optional[str], root: str, command_kind: str) -> dict:
    """Resolve one provider spec into an executable plan.

    builtin/absent never spawns anything; every other mode is gated behind
    ``allow_external`` and probing. ``require:<name>`` fails closed (returns
    ``fail_message``) when blocked or unhealthy; the other modes degrade to
    an honest builtin-only fallback with a warning.
    """
    from sot_graph.config import load_config
    from sot_graph.providers.codebase_memory import CodebaseMemoryProvider
    from sot_graph.providers_registry import resolve_capability

    try:
        mode, name = parse_provider_spec(provider_spec)
    except ValueError as exc:
        return {"mode": "invalid", "name": None, "warnings": [],
                "fail_message": str(exc), "provider": None, "status": None}
    plan: dict = {"mode": mode, "name": name, "warnings": [],
                  "fail_message": None, "provider": None, "status": None}
    if mode == "builtin":
        return plan

    cfg = load_config(root)
    if not cfg.allow_external:
        msg = "external providers disabled (allow_external=false)"
        if mode == "require":
            plan["fail_message"] = f"{msg}: require:{name} fails closed"
        else:
            plan["warnings"].append(f"{msg}; using sot-builtin only")
        return plan

    if mode in ("prefer", "require"):
        names = [name]
    else:  # auto | all: registry-ranked external providers for this command
        ranked = [
            st.name for st in resolve_capability(root, COMMAND_CAPABILITY[command_kind], cfg)
            if st.name != "sot-builtin"
        ]
        names = [n for n in ranked if n in QUERYABLE_PROVIDERS]
        if mode == "auto":
            names = names[:1]
    if not names:
        plan["warnings"].append(
            f"no queryable external provider for '{command_kind}'; using sot-builtin only"
        )
        return plan

    target = names[0]
    assert target is not None
    pcfg = cfg.providers.get(target)
    if (
        pcfg is None or pcfg.enabled is False
        or pcfg.integration != "cli" or target not in QUERYABLE_PROVIDERS
    ):
        msg = f"provider '{target}' is not queryable through an adapter in P1"
        if mode == "require":
            plan["fail_message"] = msg
        else:
            plan["warnings"].append(f"{msg}; using sot-builtin only")
    provider = CodebaseMemoryProvider(config=pcfg)
    st = provider.probe(root)
    plan["status"] = {
        "name": target, "installed": st.installed, "healthy": st.healthy,
        "version": st.version, "detail": st.detail,
    }
    if not (st.installed and st.healthy):
        msg = f"provider '{target}' unavailable ({st.detail})"
        if mode == "require":
            plan["fail_message"] = f"{msg}: failing closed"
        else:
            plan["warnings"].append(f"{msg}; using sot-builtin only")
        return plan
    plan["provider"] = provider
    return plan


def run_federated_query(plan: dict, root: str, command_kind: str, symbol: str):
    """Invoke the negotiated provider method; returns ``(outcome, method)``."""
    from sot_graph.providers.base import ImpactRequest, SymbolRequest, TraceRequest

    provider = plan["provider"]
    if command_kind == "diff-impact":
        method = "impact" if supports_capability(provider, "impact") else None
    elif supports_capability(provider, "trace"):
        method = "trace"
    elif supports_capability(provider, "search_symbols"):
        method = "search_symbols"
    else:
        method = None
    if method is None:
        return None, None
    if method == "impact":
        outcome = provider.impact(ImpactRequest(repo_root=root, path=root))
    elif method == "trace":
        outcome = provider.trace(TraceRequest(repo_root=root, symbol=symbol))
    else:
        outcome = provider.search_symbols(
            SymbolRequest(repo_root=root, query=symbol)
        )
    return outcome, method


def parse_cbm_search_report(text: str) -> tuple:
    """Parse a search_graph text report; returns (rows, has_more)."""
    rows: list = []
    has_more = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.lower().startswith("has_more:"):
            has_more = line.split(":", 1)[1].strip().lower() == "true"
            continue
        tokens = line.split()
        if len(tokens) < 5 or not _SEARCH_ROW_LINES.match(tokens[-2]):
            continue
        rank = tokens[-1]
        try:
            float(rank)
        except ValueError:
            continue
        start_s, _, end_s = tokens[-2].partition("-")
        rows.append({
            "qualified_name": " ".join(tokens[:-4]),
            "kind": tokens[-4],
            "path": tokens[-3],
            "start_line": int(start_s),
            "end_line": int(end_s),
        })
    return rows, has_more


def parse_cbm_trace_report(text: str) -> list:
    """Parse a trace_path text report; returns rows of group/name/hop/direction."""
    section = None
    group = None
    rows: list = []
    for raw in text.splitlines():
        line = raw.strip()
        low = line.lower()
        if low.startswith(("callees_total:", "callers_total:")):
            section = "callees" if low.startswith("callees_total:") else "callers"
            group = None
            continue
        if low.startswith(("function:", "direction:", "callees:", "callers:")):
            continue
        if line.endswith(":"):
            group = line[:-1].strip()
            continue
        parts = line.split()
        if group and section and len(parts) == 2 and parts[1].isdigit():
            rows.append({
                "group_qn": group, "name": parts[0],
                "hop": int(parts[1]), "direction": section,
            })
    return rows


def _candidate_entry(assertion, provider_name: str) -> dict:
    subj = assertion.subject
    resolution = getattr(assertion.resolution, "value", assertion.resolution)
    return {
        "provider": provider_name,
        "relation": assertion.relation,
        "verdict": assertion.verdict,
        "resolution": str(resolution),
        "subject": {
            "qualified_name": getattr(subj, "qualified_name", None),
            "kind": getattr(subj, "kind", None),
            "path": getattr(subj, "path", None),
            "start_line": getattr(subj, "start_line", None),
            "end_line": getattr(subj, "end_line", None),
        },
        "targets": list(assertion.targets),
        "problems": list(assertion.problems),
    }


def snapshot_match_of(outcome):
    """Read the snapshot-binding report off a provider outcome, tolerantly.

    Preferred shape: duck-typed ``outcome.snapshot_match`` with
    ``{bound, fresh, detail}``. An adapter may instead travel the verdict in
    ``metadata`` (``freshness`` FRESH/STALE/UNKNOWN/UNBOUND +
    ``snapshot_bound``); derive the same shape from it so a bound+fresh
    adapter outcome is never silently capped at UNVERIFIABLE. Returns
    ``None`` when neither shape is present (treated as unbound).
    """
    match = getattr(outcome, "snapshot_match", None)
    if match is not None:
        return match
    metadata = getattr(outcome, "metadata", None) or {}
    if not isinstance(metadata, Mapping):
        return None
    if "freshness" not in metadata and "snapshot_bound" not in metadata:
        return None
    freshness = str(metadata.get("freshness") or "")
    return {
        "bound": bool(metadata.get("snapshot_bound")),
        "fresh": freshness == "FRESH",
        "detail": f"adapter freshness marker: {freshness or 'absent'}",
    }


def cbm_candidates_from_outcome(outcome, method: str, provider_name: str,
                                repo_root: Optional[str] = None):
    """Normalize a provider QueryOutcome into candidate entries.

    Returns ``(candidates, truncated, gap_note)``. When the outcome carries
    a snapshot binding report (see :func:`snapshot_match_of`) and
    ``repo_root`` is given, each candidate's subject span is re-verified
    against current source via :func:`verify_subject`; only VERIFIED +
    bound+fresh candidates may reach SUPPORTED. Candidates gain ``verified``
    and ``detail`` fields describing the on-disk verification result.
    """
    from sot_graph.providers.normalization import (
        VERSION_COMPATIBLE,
        normalize_assertion,
        trust_ceiling,
    )
    from sot_graph.providers.verification import verify_subject

    snapshot_match = snapshot_match_of(outcome)
    version_compatibility = (
        (outcome.metadata or {}).get("version_compatibility")
        or VERSION_COMPATIBLE
    )

    def _finish(assertion):
        cand = _candidate_entry(assertion, provider_name)
        if repo_root is None:
            return cand
        subject = assertion.subject
        verification = (
            verify_subject(subject, repo_root)
            if getattr(subject, "path", None)
            else None
        )
        has_span = getattr(subject, "start_line", None) is not None
        verdict, resolution = trust_ceiling(
            snapshot_bound=(
                bool(snapshot_match.get("bound"))
                if isinstance(snapshot_match, Mapping)
                else bool(getattr(snapshot_match, "bound", False))
            ),
            has_span=has_span,
            unique_target=len(assertion.targets) == 1,
            verification=verification,
            snapshot_match=snapshot_match,
            version_compatibility=version_compatibility,
        )
        cand["verdict"] = verdict
        cand["resolution"] = str(getattr(resolution, "value", resolution))
        cand["verified"] = (
            getattr(verification, "status", None) if verification else None
        )
        cand["detail"] = getattr(verification, "detail", "") if verification else ""
        return cand

    candidates: list = []
    truncated = bool((outcome.metadata or {}).get("wire_status") == "truncated")
    payload = outcome.payload

    if method == "impact":
        # detect_changes carries no mappable relation; record each impacted
        # path as an explicitly UNMAPPED advisory candidate.
        paths = payload.get("impacted") if isinstance(payload, dict) else None
        paths = paths if isinstance(paths, list) else []
        for entry in paths:
            path = entry.get("path") if isinstance(entry, dict) else entry
            if not isinstance(path, str):
                continue
            assertion = normalize_assertion(
                raw_subject={"path": path},
                provider_relation="detect_changes",
                targets=(path,),
                snapshot_bound=False,
                version_compatibility=version_compatibility,
            )
            candidates.append(_finish(assertion))
        return candidates, truncated, None

    if not isinstance(payload, str):
        return candidates, truncated, "unexpected CBM payload type; ignored"

    if method == "trace":
        for row in parse_cbm_trace_report(payload):
            qn = f"{row['group_qn']}.{row['name']}"
            assertion = normalize_assertion(
                raw_subject={"qualified_name": qn, "kind": "unknown"},
                provider_relation="call",
                targets=(qn,),
                snapshot_bound=False,
                version_compatibility=version_compatibility,
            )
            candidates.append(_finish(assertion))
        return candidates, truncated, None

    rows, has_more = parse_cbm_search_report(payload)
    for row in rows:
        assertion = normalize_assertion(
            raw_subject={
                "qualified_name": row["qualified_name"], "kind": row["kind"],
                "path": row["path"],
                "span": {"start_line": row["start_line"], "end_line": row["end_line"]},
            },
            provider_relation="define",
            targets=(row["qualified_name"],),
            snapshot_bound=False,
            version_compatibility=version_compatibility,
        )
        candidates.append(_finish(assertion))
    return candidates, (truncated or has_more), None


def target_conflicts(builtin_target, candidates: list,
                     repo_root: Optional[str] = None) -> list:
    """Record builtin vs external target disagreements.

    ``builtin_target`` is ``(label, path, line)`` from the local graph, or
    None. A conflict is recorded when an external candidate claiming the
    same symbol name lands on a different file/span.

    When ``repo_root`` is given, both sides are checked against current
    source: if exactly ONE side's span verifies (status VERIFIED), that side
    becomes the recorded resolution (``resolution="source_verified"``) and
    the other is marked contradicted. The conflict is still listed — never
    silently dropped. Without a decisive verification the conflict stays
    ``recorded-not-resolved``.
    """
    from sot_graph.providers.verification import VERIFIED, verify_subject

    conflicts: list = []
    if not builtin_target:
        return conflicts
    label, bpath, bline = builtin_target
    for cand in candidates:
        subj = cand["subject"]
        qn = subj.get("qualified_name") or ""
        if label and qn.rsplit(".", 1)[-1] != label:
            continue
        cpath, cline = subj.get("path"), subj.get("start_line")
        if not cpath:
            continue
        differs = os.path.normpath(cpath) != os.path.normpath(bpath or "")
        span_differs = (
            not differs and bline is not None and cline is not None
            and int(cline) != int(bline)
        )
        if not (differs or span_differs):
            continue

        conflict = {
            "kind": "target_mismatch",
            "symbol": label,
            "builtin": {"path": bpath, "line": bline},
            "external": {
                "provider": cand["provider"],
                "qualified_name": qn, "path": cpath, "line": cline,
            },
            "policy": "recorded-not-resolved",
            "resolution": "recorded-not-resolved",
        }

        if repo_root:
            cbm_status = cand.get("verified")
            if cbm_status is None and subj.get("path"):
                cbm_status = verify_subject(subj, repo_root).status
            builtin_status = None
            if bpath:
                builtin_subject = {
                    "qualified_name": label, "kind": "unknown",
                    "path": bpath, "start_line": bline,
                }
                builtin_status = verify_subject(builtin_subject, repo_root).status

            external_side = dict(conflict["external"])
            builtin_side = dict(conflict["builtin"])
            if cbm_status == VERIFIED and builtin_status != VERIFIED:
                conflict["resolution"] = "source_verified"
                conflict["resolved"] = external_side | {"verified": cbm_status}
                conflict["contradicted"] = builtin_side | {"verified": builtin_status}
            elif builtin_status == VERIFIED and cbm_status != VERIFIED:
                conflict["resolution"] = "source_verified"
                conflict["resolved"] = builtin_side | {"verified": builtin_status}
                conflict["contradicted"] = external_side | {"verified": cbm_status}

        conflicts.append(conflict)
    return conflicts


def federated_extras(
    provider_spec: Optional[str],
    root: str,
    command_kind: str,
    symbol: str,
    builtin_target=None,
) -> Optional[dict]:
    """Run the optional external-provider evidence path for one command.

    Returns ``None`` for an absent/builtin spec so the caller proceeds
    completely untouched; otherwise a dict with warnings, fail_message,
    candidates, conflicts, providers_extra, coverage, known_gaps, truncated.
    """
    plan = federation_plan(provider_spec, root, command_kind)
    result = {
        "warnings": list(plan["warnings"]), "fail_message": plan["fail_message"],
        "candidates": [], "conflicts": [], "providers_extra": [],
        "coverage": None, "known_gaps": None, "truncated": False,
    }
    if plan["mode"] == "builtin":
        return None
    if plan["fail_message"]:
        return result

    status = plan["status"] or {}
    pname = status.get("name", plan["name"] or "codebase-memory")
    result["providers_extra"] = [{
        "name": pname, "version": status.get("version"),
        "role": "candidate-evidence",
    }] if status else []
    gaps: list = []
    # The snapshot-binding gap is only reported when a query actually ran
    # and the outcome still lacks a bound+fresh snapshot_match report.
    result["coverage"] = {pname: {"queried": False}}

    provider = plan["provider"]
    if provider is None:
        result["known_gaps"] = gaps
        return result

    outcome, method = run_federated_query(plan, root, command_kind, symbol)
    cov = {"queried": bool(outcome is not None and outcome.ok), "method": method}
    if outcome is None:
        gaps.append("capability negotiation found no invocable CBM method")
        cov["error"] = "no invocable method"
    elif not outcome.ok:
        cov["error"] = outcome.error
        if outcome.next_action:
            gaps.append(f"{pname}: {outcome.next_action}")
        if plan["mode"] == "require":
            plan["fail_message"] = result["fail_message"] = (
                f"require:{pname}: query failed ({outcome.error}); "
                "failing closed"
            )
            result["coverage"] = {pname: cov}
            result["known_gaps"] = gaps
            return result
        result["warnings"].append(
            f"{pname} query failed ({outcome.error}); using sot-builtin only"
        )
    else:
        sm = snapshot_match_of(outcome)
        sm_bound = (
            bool(sm.get("bound")) if isinstance(sm, dict)
            else bool(getattr(sm, "bound", False))
        )
        if not sm_bound:
            gaps.append(
                "snapshot binding unproven: "
                f"{pname} candidates are capped at UNVERIFIABLE"
            )
        candidates, truncated, gap_note = cbm_candidates_from_outcome(
            outcome, method or "search_symbols", pname, repo_root=root
        )
        result["candidates"] = candidates
        result["truncated"] = truncated
        if gap_note:
            gaps.append(gap_note)
        for cand in candidates:
            verified = cand.get("verified")
            detail = cand.get("detail") or ""
            if verified is not None and verified != "VERIFIED":
                qn = cand["subject"].get("qualified_name") or "<unknown>"
                gaps.append(
                    f"{pname}: {qn}: source verification {verified}"
                    + (f" ({detail})" if detail else "")
                )
        result["conflicts"] = target_conflicts(
            builtin_target, candidates, repo_root=root
        )
    result["coverage"] = {pname: cov}
    result["known_gaps"] = gaps
    return result


def envelope_fed_kwargs(db, fed: dict) -> dict:
    """Keyword additions for wrap_envelope reflecting one federation run."""
    from sot_graph.envelope import get_active_providers

    providers = get_active_providers(db) + fed["providers_extra"]
    return {
        "providers": providers,
        "coverage": fed["coverage"],
        "known_gaps": fed["known_gaps"],
        "truncated": fed["truncated"],
        "conflicts_detected": fed["conflicts"],
    }


def resolve_federated_spec(explicit: Optional[str], root: str) -> Optional[str]:
    """Effective spec for one command: explicit wins, then config auto (P2.c')."""
    from sot_graph.config import load_config

    cfg = load_config(root)
    return effective_provider_spec(explicit, cfg.providers_mode, cfg.allow_external)
