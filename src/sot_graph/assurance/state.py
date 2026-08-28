"""sot_graph.assurance.state - canonical assurance state machine (P0).

The ONE decision function behind every assurance surface (CLI receipts,
MCP tools, tests). No surface computes its own status vocabulary: facts
go in, the canonical status + reason codes come out. Fail-closed: any
missing or below-threshold fact downgrades the verdict - there is no
default path that upgrades toward ASSURED_WITHIN_SCOPE.

Contract 1 (plan P0 trust-chain, 2026-08-28). Evaluation order is
first-hit wins; each branch carries exactly one reason code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

__all__ = ["CANONICAL_STATUSES", "AssuranceFacts", "decide"]

#: Canonical receipt-status vocabulary (Contract 1). ``ASSURED`` alone no
#: longer exists; every status emitted by receipts must be a member.
CANONICAL_STATUSES = (
    "ASSURED_WITHIN_SCOPE",
    "PARTIAL",
    "CONFLICTED",
    "STALE",
    "UNVERIFIABLE",
    "ABSTAINED",
)


@dataclass(frozen=True)
class AssuranceFacts:
    """Every fact the verdict may rest on. Pure data, no I/O."""

    #: UNIQUE | AMBIGUOUS | NOT_FOUND (Contract 3 resolver)
    identity_status: str
    #: scope_digest present and binds the current content
    snapshot_bound: bool
    stale_files: List[str] = field(default_factory=list)
    #: coverage basis == "measured"
    coverage_measured: bool = False
    coverage_fraction: float | None = None
    coverage_floor: float = 0.9
    parser_failures: int = 0
    #: evidence ledger entries below SUPPORTED
    unresolved_count: int = 0
    unresolved_budget: int = 0
    open_conflicts: int = 0
    truncated: bool = False
    provider_capability_ok: bool = True
    #: receipt rests on a negative claim (e.g. "0 callers").
    #: Fail-closed default: assume an absence claim unless proven otherwise.
    absence_claim: bool = True
    #: rename/delete gate
    gate_blocked: bool = False


def decide(facts: AssuranceFacts) -> dict:
    """Pure decision over :class:`AssuranceFacts` (Contract 1 order).

    Returns ``{"status": str, "reason_codes": [str, ...]}``. First-hit
    wins: exactly one branch fires.
    """
    # 1. identity
    if facts.identity_status != "UNIQUE":
        reason = (
            "target_not_found"
            if facts.identity_status == "NOT_FOUND"
            else "target_ambiguous"
        )
        return {"status": "ABSTAINED", "reason_codes": [reason]}
    # 2. snapshot binding
    if not facts.snapshot_bound:
        return {"status": "UNVERIFIABLE", "reason_codes": ["snapshot_unbound"]}
    # 3. stale sources
    if facts.stale_files:
        return {"status": "STALE", "reason_codes": ["stale_sources"]}
    # 4. rename/delete gate
    if facts.gate_blocked:
        return {"status": "PARTIAL", "reason_codes": ["rename_gate_blocked"]}
    # 5. open conflicts
    if facts.open_conflicts > 0:
        return {"status": "CONFLICTED", "reason_codes": ["open_conflicts"]}
    # 6. truncation
    if facts.truncated:
        return {"status": "PARTIAL", "reason_codes": ["transitive_truncated"]}
    # 7. parser failures
    if facts.parser_failures > 0:
        return {"status": "PARTIAL", "reason_codes": ["parser_failures"]}
    # 8. unresolved over budget
    if facts.unresolved_count > facts.unresolved_budget:
        return {"status": "PARTIAL", "reason_codes": ["unresolved_over_budget"]}
    # 9. absence claim without measured coverage at/above floor
    if facts.absence_claim and (
        not facts.coverage_measured
        or facts.coverage_fraction is None
        or facts.coverage_fraction < facts.coverage_floor
    ):
        return {"status": "PARTIAL", "reason_codes": ["coverage_below_floor"]}
    # 10. provider capability
    if not facts.provider_capability_ok:
        return {"status": "PARTIAL", "reason_codes": ["provider_capability_missing"]}
    # 11. all clear
    return {"status": "ASSURED_WITHIN_SCOPE", "reason_codes": []}
