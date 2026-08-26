"""sot_graph.providers.normalization — CBM relation mapping + trust ceilings.

Versioned, table-driven normalization of Codebase Memory (CBM) evidence into
the SOT canonical vocabulary. Rules (guide §7):

- Canonical subject identity: repo_id + normalized path + span + kind +
  qualified_name; a subject without span is marked low resolution.
- One versioned mapping table (never hard-coded at call sites). Each entry
  records: provider relation, canonical relation, direct vs inferred, whether
  the provider emits a proving source span, verification condition, and the
  CBM version it was tested against.
- Trust ceilings reuse existing enums — ``ResolutionStatus`` from
  ``sot_graph.evidence`` and the verdict strings documented in
  ``sot_graph.provider_contract`` (SUPPORTED | HEURISTIC | AMBIGUOUS | STALE |
  UNVERIFIABLE). No duplicate enums are introduced here.

Ceiling order (first hit wins):
1. Snapshot binding unproven            -> UNVERIFIABLE (never SUPPORTED)
2. Source changed after index           -> STALE
3. Multiple candidate targets           -> AMBIGUOUS
4. No proving span                      -> HEURISTIC (resolution INFERRED)
5. Snapshot bound + span + unique target -> SUPPORTED (resolution EXACT)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from sot_graph.evidence import ResolutionStatus
from sot_graph.provider_contract import Subject

__all__ = [
    "CANONICAL_RELATIONS",
    "MAPPING_TABLE_VERSION",
    "TESTED_CBM_VERSION",
    "VERSION_COMPATIBLE",
    "VERSION_UNTESTED",
    "VERSION_INCOMPATIBLE",
    "VERSION_UNKNOWN",
    "RelationMapping",
    "CanonicalSubject",
    "NormalizedAssertion",
    "resolve_mapping",
    "normalize_subject",
    "trust_ceiling",
    "normalize_assertion",
]

#: Verdict vocabulary from provider_contract.VerificationResult.status.
VERDICT_SUPPORTED = "SUPPORTED"
VERDICT_HEURISTIC = "HEURISTIC"
VERDICT_AMBIGUOUS = "AMBIGUOUS"
VERDICT_STALE = "STALE"
VERDICT_UNVERIFIABLE = "UNVERIFIABLE"

#: SOT canonical relations produced by this table (v1).
CANONICAL_RELATIONS: frozenset[str] = frozenset(
    {"CALLS", "IMPORTS", "DEFINES", "IMPLEMENTS", "INHERITS"}
)

#: CBM release the mapping table below was verified against.
TESTED_CBM_VERSION = "0.10.8"

#: Wire-compatibility states for the probed provider binary (G1.5).
#: COMPATIBLE   — exact match with TESTED_CBM_VERSION (golden-verified wire).
#: UNTESTED     — same major.minor, different patch; wire *may* still match,
#:                so queries run but every verdict is capped at UNVERIFIABLE.
#: INCOMPATIBLE — different major.minor; the adapter must fail closed.
#: UNKNOWN      — probe has not produced a parsable version yet.
VERSION_COMPATIBLE = "COMPATIBLE"
VERSION_UNTESTED = "UNTESTED"
VERSION_INCOMPATIBLE = "INCOMPATIBLE"
VERSION_UNKNOWN = "UNKNOWN"

#: Version of THIS mapping table; bump when entries change semantics.
MAPPING_TABLE_VERSION = 1


@dataclass(frozen=True)
class RelationMapping:
    """One row of the versioned CBM -> SOT relation mapping table."""

    provider_relation: str  # lowercased CBM relation name
    canonical_relation: str  # one of CANONICAL_RELATIONS
    direct: bool  # True=directly resolved by extractor; False=inferred/usage
    has_span: bool  # whether CBM emits a source span proving this edge
    verification_condition: str  # what must hold for a stronger verdict
    tested_cbm_version: str = TESTED_CBM_VERSION


_RELATION_SPECS: tuple[tuple[tuple[str, ...], str, bool, bool, str], ...] = (
    # (provider aliases, canonical, direct, has_span, verification condition)
    (("call", "calls"), "CALLS", True, True,
     "snapshot bound + unique target + span on source file"),
    (("reference", "references", "usage", "uses"), "CALLS", False, False,
     "name-only usage: ceiling INFERRED even when snapshot bound"),
    (("import", "imports"), "IMPORTS", True, True,
     "snapshot bound + import statement span"),
    (("define", "defines", "definition", "definitions"), "DEFINES", True, True,
     "snapshot bound + definition span"),
    (("implements", "implementation"), "IMPLEMENTS", True, True,
     "snapshot bound + member declaration span"),
    (("inherits", "inheritance", "extends", "extends_class"), "INHERITS", True, True,
     "snapshot bound + class declaration span"),
)

RELATION_MAPPINGS: dict[str, RelationMapping] = {
    alias: RelationMapping(
        provider_relation=alias,
        canonical_relation=canonical,
        direct=direct,
        has_span=has_span,
        verification_condition=condition,
    )
    for aliases, canonical, direct, has_span, condition in _RELATION_SPECS
    for alias in aliases
}


def resolve_mapping(provider_relation: str) -> RelationMapping | None:
    """Look up the versioned mapping for a raw CBM relation name.

    Returns ``None`` for unknown relations — callers must abstain rather than
    guess a canonical form.
    """
    if not isinstance(provider_relation, str):
        return None
    return RELATION_MAPPINGS.get(provider_relation.strip().lower())


@dataclass(frozen=True)
class CanonicalSubject(Subject):
    """Canonical subject identity (guide §7), extending the contract Subject.

    Adds repository scope, language and column-precise span on top of
    ``sot_graph.provider_contract.Subject`` so both types stay interchangeable
    for envelope building.
    """

    repo_id: str = ""
    language: str = "unknown"
    start_column: int | None = None
    end_column: int | None = None


@dataclass(frozen=True)
class NormalizedAssertion:
    """A CBM assertion after mapping + ceiling application."""

    subject: CanonicalSubject | None
    relation: str  # canonical relation or "UNKNOWN" when unmapped
    targets: tuple[str, ...]
    verdict: str  # one of the VERDICT_* strings above
    resolution: ResolutionStatus
    mapping_version: int = MAPPING_TABLE_VERSION
    problems: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


_SPAN_KEYS = ("span", "range", "location")


def _extract_span(raw: Mapping[str, Any]) -> dict[str, int | None]:
    """Pull {start_line,end_line,start_column,end_column} out of a raw node."""
    span_src: Mapping[str, Any] = raw
    for key in _SPAN_KEYS:
        nested = raw.get(key)
        if isinstance(nested, Mapping):
            span_src = nested
            break
    def _int(name: str) -> int | None:
        value = span_src.get(name, raw.get(name))
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else None
    return {
        "start_line": _int("start_line"),
        "end_line": _int("end_line"),
        "start_column": _int("start_column"),
        "end_column": _int("end_column"),
    }


def normalize_subject(
    raw: Mapping[str, Any], repo_id: str | None = None
) -> tuple[CanonicalSubject | None, tuple[str, ...]]:
    """Normalize a raw CBM node dict into a :class:`CanonicalSubject`.

    Returns ``(subject, problems)``; ``subject is None`` when required fields
    are missing. Never invents values: absent spans stay ``None``, absent
    language becomes ``"unknown"``.
    """
    problems: list[str] = []
    path = raw.get("path")
    kind = raw.get("kind")
    qualified_name = raw.get("qualified_name") or raw.get("fqn") or raw.get("name")
    if not isinstance(path, str) or not path:
        problems.append("missing path")
    if not isinstance(kind, str) or not kind:
        problems.append("missing kind")
    if not isinstance(qualified_name, str) or not qualified_name:
        problems.append("missing qualified_name")
    if problems:
        return None, tuple(problems)
    assert isinstance(path, str) and isinstance(kind, str) \
        and isinstance(qualified_name, str)

    span = _extract_span(raw)
    has_span = span["start_line"] is not None and span["end_line"] is not None
    if not has_span:
        problems.append("no span: subject identity is low-resolution")

    subject = CanonicalSubject(
        kind=kind,
        qualified_name=qualified_name,
        path=path,
        start_line=span["start_line"],
        end_line=span["end_line"],
        content_hash=(
            raw.get("content_hash")
            if isinstance(raw.get("content_hash"), str)
            else None
        ),
        repo_id=repo_id if isinstance(repo_id, str) else "",
        language=(
            raw["language"] if isinstance(raw.get("language"), str) else "unknown"
        ),
        start_column=span["start_column"],
        end_column=span["end_column"],
    )
    return subject, tuple(problems)


def _sm_field(snapshot_match: Any, key: str) -> bool:
    """Read a boolean field off a duck-typed snapshot-match report."""
    if snapshot_match is None:
        return False
    if isinstance(snapshot_match, Mapping):
        return bool(snapshot_match.get(key, False))
    return bool(getattr(snapshot_match, key, False))

def trust_ceiling(
    *,
    snapshot_bound: bool,
    has_span: bool,
    unique_target: bool,
    source_changed: bool = False,
    verification: Any = None,
    snapshot_match: Any = None,
    version_compatibility: str = VERSION_COMPATIBLE,
) -> tuple[str, ResolutionStatus]:
    """Apply the ordered trust ceilings to one provable assertion.

    Returns ``(verdict, resolution)``. Unbound snapshots can never reach
    SUPPORTED; missing spans cap at HEURISTIC/INFERRED; multi-target usage is
    AMBIGUOUS regardless of other evidence.
    Evidence from an UNTESTED/UNKNOWN/INCOMPATIBLE wire (version
    gate, G1.5) caps at UNVERIFIABLE before any other rule applies.

    P2 additive parameters (both optional; ``None`` preserves the legacy
    behaviour exactly):

    ``verification``
        A :class:`~sot_graph.providers.verification.VerificationOutcome`
        (or bare status string) from re-checking the subject's span against
        current source. When provided, the verdict matrix becomes:

        * snapshot bound+fresh AND VERIFIED -> SUPPORTED/EXACT (still gated
          by ``unique_target``/``has_span`` structure).
        * bound+fresh AND SPAN_MISMATCH or MISSING -> downgraded to
          HEURISTIC/INFERRED; callers should surface the outcome's detail as
          a known gap.
        * bound+fresh AND AMBIGUOUS -> AMBIGUOUS.
        * bound+fresh AND NOT_APPLICABLE -> verifier abstains (generated/
          vendor/no-span); evidence stays structural, capped at
          HEURISTIC/INFERRED.
        * snapshot unbound or stale -> UNVERIFIABLE/STALE unchanged; source
          verification never self-elevates an unbound snapshot.

    ``snapshot_match``
        Worker-provided duck-typed binding report with shape
        ``{bound: bool, fresh: bool, detail: str}`` (mapping or attribute
        access). Absent/``None`` is treated as unbound.
    """

    if unique_target and has_span:
        resolution = ResolutionStatus.EXACT
    elif unique_target:
        resolution = ResolutionStatus.INFERRED
    else:
        resolution = ResolutionStatus.AMBIGUOUS
    if version_compatibility != VERSION_COMPATIBLE:
        # G1.5: an untested/incompatible wire contract can never publish
        # verified evidence, regardless of snapshot or span state.
        return VERDICT_UNVERIFIABLE, resolution

    if not snapshot_bound:
        # Structure still informs resolution; the verdict can never rise.
        return VERDICT_UNVERIFIABLE, resolution
    if source_changed:
        return VERDICT_STALE, resolution
    if verification is None:
        # Legacy path: no live-source evidence requested.
        if not unique_target:
            return VERDICT_AMBIGUOUS, ResolutionStatus.AMBIGUOUS
        if not has_span:
            return VERDICT_HEURISTIC, ResolutionStatus.INFERRED
        return VERDICT_SUPPORTED, ResolutionStatus.EXACT

    # P2 path: live-source verification participates in the ceiling.
    sm_bound = bool(snapshot_match is not None and _sm_field(snapshot_match, "bound"))
    if not sm_bound:
        return VERDICT_UNVERIFIABLE, resolution
    if not _sm_field(snapshot_match, "fresh"):
        return VERDICT_STALE, resolution
    v_status = (
        verification
        if isinstance(verification, str)
        else getattr(verification, "status", None)
    )
    if v_status == "VERIFIED":
        if not unique_target:
            return VERDICT_AMBIGUOUS, ResolutionStatus.AMBIGUOUS
        if not has_span:
            return VERDICT_HEURISTIC, ResolutionStatus.INFERRED
        return VERDICT_SUPPORTED, ResolutionStatus.EXACT
    if v_status in ("SPAN_MISMATCH", "MISSING"):
        return VERDICT_HEURISTIC, ResolutionStatus.INFERRED
    if v_status == "AMBIGUOUS":
        return VERDICT_AMBIGUOUS, ResolutionStatus.AMBIGUOUS
    # NOT_APPLICABLE / unknown status: verifier abstained; structural
    # evidence alone cannot claim a source-verified span.
    return VERDICT_HEURISTIC, ResolutionStatus.INFERRED


def normalize_assertion(
    *,
    raw_subject: Mapping[str, Any],
    provider_relation: str,
    targets: tuple[str, ...] | list[str],
    repo_id: str | None = None,
    snapshot_bound: bool = False,
    source_changed: bool = False,
    version_compatibility: str = VERSION_COMPATIBLE,
) -> NormalizedAssertion:
    """Map one CBM assertion to canonical form and apply trust ceilings.

    ``targets`` holds candidate target identifiers; more than one means the
    dispatch could not be uniquely resolved by the provider.
    """
    problems: list[str] = []
    subject, subject_problems = normalize_subject(raw_subject, repo_id=repo_id)
    problems.extend(subject_problems)

    mapping = resolve_mapping(provider_relation)
    if mapping is None:
        problems.append(f"unmapped provider relation: {provider_relation!r}")
        relation = "UNKNOWN"
        proves_span = bool(
            subject is not None and subject.start_line is not None
        )
    else:
        relation = mapping.canonical_relation
        # A proving span exists only when the provider emits spans for this
        # relation AND we actually recovered one on the subject.
        proves_span = mapping.has_span and subject is not None and subject.start_line is not None
        if mapping.has_span and subject is not None and subject.start_line is None:
            problems.append(
                f"relation {relation} requires a span but subject has none"
            )

    unique_targets = tuple(targets)
    verdict, resolution = trust_ceiling(
        snapshot_bound=snapshot_bound,
        has_span=proves_span,
        unique_target=len(unique_targets) == 1,
        source_changed=source_changed,
        version_compatibility=version_compatibility,
    )
    metadata: dict[str, Any] = {}
    if mapping is not None:
        metadata.update(
            {
                "mapping_version": MAPPING_TABLE_VERSION,
                "provider_relation": mapping.provider_relation,
                "direct": mapping.direct,
                "tested_cbm_version": mapping.tested_cbm_version,
            }
        )
    return NormalizedAssertion(
        subject=subject,
        relation=relation,
        targets=unique_targets,
        verdict=verdict,
        resolution=resolution,
        problems=tuple(problems),
        metadata=metadata,
    )
