"""sot_graph.assurance.state - canonical assurance state machine (P0 / P1).

The ONE decision function behind every assurance surface (CLI receipts,
MCP tools, tests). No surface computes its own status vocabulary: facts
go in, the canonical status + reason codes come out. Fail-closed: any
missing or below-threshold fact downgrades the verdict - there is no
default path that upgrades toward ASSURED_WITHIN_SCOPE.

Contract 1 (plan P0/P1 trust-chain, 2026-08-28):
Gathers all active failure reasons and reduces to the highest-severity
status via the canonical severity lattice:
  ABSTAINED > UNVERIFIABLE > STALE > CONFLICTED > PARTIAL > ASSURED_WITHIN_SCOPE
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
__all__ = [
    "CANONICAL_STATUSES",
    "CLAIM_PROFILES",
    "STATUS_SEVERITY",
    "ReceiptStatus",
    "CanonicalReceiptStatus",
    "AssuranceFacts",
    "decide",
]

#: Canonical receipt-status vocabulary (Contract 1).
CANONICAL_STATUSES = (
    "ASSURED_WITHIN_SCOPE",
    "PARTIAL",
    "CONFLICTED",
    "STALE",
    "UNVERIFIABLE",
    "ABSTAINED",
)

class ReceiptStatus:
    ASSURED_WITHIN_SCOPE = "ASSURED_WITHIN_SCOPE"
    PARTIAL = "PARTIAL"
    CONFLICTED = "CONFLICTED"
    STALE = "STALE"
    UNVERIFIABLE = "UNVERIFIABLE"
    ABSTAINED = "ABSTAINED"


#: Alias for ReceiptStatus
CanonicalReceiptStatus = ReceiptStatus

#: Claim profiles
CLAIM_PROFILES = (
    "presence",
    "absence",
    "exhaustive",
)

#: Statuses that claim fully assured (within-scope) evidence. Any other
#: canonical status means completeness is NOT proven — gates must fail
#: closed on these (Contract 1: no surface invents its own vocabulary).
ASSURED_STATUSES = frozenset(
    s for s in CANONICAL_STATUSES if s.startswith("ASSURED")
)

#: Status severity ranking (highest to lowest).
STATUS_SEVERITY: Dict[str, int] = {
    "ABSTAINED": 50,
    "UNVERIFIABLE": 40,
    "STALE": 30,
    "CONFLICTED": 20,
    "PARTIAL": 10,
    "ASSURED_WITHIN_SCOPE": 0,
}


@dataclass(frozen=True)
class AssuranceFacts:
    """Every fact the verdict may rest on. Pure data, no I/O."""

    #: Target identity resolution: "UNIQUE" | "NOT_FOUND" | "AMBIGUOUS"
    identity_status: str
    #: scope_digest present and binds the current content
    snapshot_bound: bool = True
    #: Collection/tool/DB errors during evidence collection
    collection_error: bool = False
    stale_files: List[str] = field(default_factory=list)
    #: coverage basis == "measured"
    coverage_measured: bool = False
    coverage_fraction: Optional[float] = None
    coverage_floor: float = 0.9
    parser_failures: int = 0
    #: evidence ledger entries below SUPPORTED
    unresolved_count: int = 0
    unresolved_budget: int = 0
    open_conflicts: int = 0
    truncated: bool = False
    #: SG-107: ids of the capped collections that ACTUALLY truncated
    #: (e.g. "edges_cap_500", "transitive_cap_200"). Non-empty implies
    #: ``truncated``; each source degrades the verdict to PARTIAL. The
    #: legacy shape (``truncated`` set, no sources — transport trim,
    #: pre-1.4 callers) keeps the historical "transitive_truncated" code.
    truncation_sources: Tuple[str, ...] = ()
    #: SG-108: every in-scope file was enumerated (no unjournaled
    #: eligible files, no walk errors, journal readable). None =
    #: unmeasured, which fails closed under an absence/exhaustive/
    #: relation claim exactly like False.
    enumeration_complete: Optional[bool] = None
    #: SG-108: every in-scope journaled file was parsed by the full
    #: parser (no PARTIAL_AST/PARSE_ERROR/PARSER_UNAVAILABLE ceilings;
    #: legacy NULL-outcome rows count as capable). None = unmeasured
    #: (journal unreadable) and fails closed like False.
    parser_capability_complete: Optional[bool] = None
    #: SG-108: at least one in-scope journaled file sits at the
    #: PARTIAL_AST regex-fallback ceiling — named ceiling because a
    #: partial parse never allows an ASSURED relation/absence claim,
    #: even when coverage averages look high.
    partial_ast_present: bool = False
    provider_capability_ok: bool = True
    #: receipt rests on a negative claim (e.g. "0 callers").
    #: Fail-closed default: assume an absence claim unless proven otherwise.
    absence_claim: bool = True
    #: rename/delete gate
    gate_blocked: bool = False
    #: dynamic constructs that could not be statically resolved
    dynamic_dispatch_unresolved: bool = False
    #: Claim profile: "presence" | "absence" | "exhaustive"
    claim_profile: str = "absence"


def decide(facts: AssuranceFacts) -> Dict[str, Any]:
    """Pure decision over :class:`AssuranceFacts` with severity join.

    Collects ALL triggered reason codes, then selects the final status
    with the highest severity in ``STATUS_SEVERITY``.
    Returns ``{"status": str, "reason_codes": [str, ...]}``.
    """
    reasons: List[str] = []
    candidate_statuses: List[str] = []

    # 1. identity check
    # 0. collection / tool error
    if facts.collection_error:
        reasons.append("collection_error")
        candidate_statuses.append("UNVERIFIABLE")

    if facts.identity_status != "UNIQUE":
        reason = (
            "target_not_found"
            if facts.identity_status == "NOT_FOUND"
            else "target_ambiguous"
        )
        reasons.append(reason)
        candidate_statuses.append("ABSTAINED")

    # 2. snapshot binding
    if not facts.snapshot_bound:
        reasons.append("snapshot_unbound")
        candidate_statuses.append("UNVERIFIABLE")

    # 3. stale sources
    if facts.stale_files:
        reasons.append("stale_sources")
        candidate_statuses.append("STALE")

    # 4. open conflicts
    if facts.open_conflicts > 0:
        reasons.append("open_conflicts")
        candidate_statuses.append("CONFLICTED")

    # 5. rename/delete gate
    if facts.gate_blocked:
        reasons.append("rename_gate_blocked")
        candidate_statuses.append("PARTIAL")

    # 6. truncation (bounded-collection caps, SG-107). Legacy shape —
    # ``truncated`` without source ids (the SG-104 transport trim and
    # pre-1.4 callers) — keeps the historical "transitive_truncated"
    # reason. With sources, each capped collection that actually cut
    # emits its own code: the transitive source keeps its historical
    # reason code (backward compat with live tests), every other source
    # emits ``collection_truncated:<source>``. Truncated facts still cap
    # the candidate at PARTIAL.
    if facts.truncation_sources:
        for source in facts.truncation_sources:
            if source == "transitive_cap_200":
                reasons.append("transitive_truncated")
            else:
                reasons.append(f"collection_truncated:{source}")
            candidate_statuses.append("PARTIAL")
    elif facts.truncated:
        reasons.append("transitive_truncated")
        candidate_statuses.append("PARTIAL")

    # 7. parser failures
    if facts.parser_failures > 0:
        reasons.append("parser_failures")
        candidate_statuses.append("PARTIAL")

    # 8. unresolved over budget
    if facts.unresolved_count > facts.unresolved_budget:
        reasons.append("unresolved_over_budget")
        candidate_statuses.append("PARTIAL")

    # 9. dynamic dispatch unresolved
    if facts.dynamic_dispatch_unresolved:
        reasons.append("dynamic_dispatch_unresolved")
        candidate_statuses.append("PARTIAL")

    # 10. absence/exhaustive/relation claims need measured coverage at or
    # above the floor AND an exhausted, fully parser-capable enumeration
    # universe (SG-108). Each condition is evaluated independently and
    # appends its own reason: an absence claim is only as strong as the
    # weakest fact behind it.
    requires_absence = facts.absence_claim or facts.claim_profile in (
        "absence", "exhaustive", "relation",
    )
    if requires_absence and (
        not facts.coverage_measured
        or facts.coverage_fraction is None
        or facts.coverage_fraction < facts.coverage_floor
    ):
        reasons.append("coverage_below_floor")
        candidate_statuses.append("PARTIAL")

    # 10b. SG-108 exhaustion facts. None (unmeasured) fails closed
    # exactly like False — "cannot prove the universe was fully
    # enumerated" must never read as "fully enumerated".
    if requires_absence and facts.enumeration_complete is not True:
        reasons.append("enumeration_incomplete")
        candidate_statuses.append("PARTIAL")

    if requires_absence and facts.parser_capability_complete is not True:
        reasons.append("parser_capability_incomplete")
        candidate_statuses.append("PARTIAL")

    # 10c. SG-108 partial-AST ceiling: PARTIAL_AST files never allow an
    # ASSURED relation/absence claim even when coverage averages look
    # high — the parse itself is incomplete, so absence over it would be
    # fabricated.
    if requires_absence and facts.partial_ast_present:
        reasons.append("partial_ast_ceiling")
        candidate_statuses.append("PARTIAL")

    # 11. provider capability
    if not facts.provider_capability_ok:
        reasons.append("provider_capability_missing")
        candidate_statuses.append("PARTIAL")

    # Final reduction by severity
    if not candidate_statuses:
        return {"status": "ASSURED_WITHIN_SCOPE", "reason_codes": []}

    final_status = max(candidate_statuses, key=lambda s: STATUS_SEVERITY.get(s, 0))
    return {"status": final_status, "reason_codes": reasons}
