"""Tests for sot_graph.providers.normalization — mapping table + trust ceilings.

Verifies the versioned CBM -> SOT relation mapping, canonical subject
normalization, and the ordered trust ceilings (unbound snapshot can never
reach SUPPORTED; missing span caps at INFERRED/HEURISTIC; multi-target is
AMBIGUOUS).
"""
from __future__ import annotations

import pytest

from sot_graph.evidence import ResolutionStatus
from sot_graph.providers.normalization import (
    CANONICAL_RELATIONS,
    MAPPING_TABLE_VERSION,
    RELATION_MAPPINGS,
    TESTED_CBM_VERSION,
    CanonicalSubject,
    NormalizedAssertion,
    normalize_assertion,
    normalize_subject,
    resolve_mapping,
    VERSION_UNTESTED,
    VERSION_UNKNOWN,
    trust_ceiling,
)

FULL_SPAN_SUBJECT = {
    "path": "src/pkg/file.py",
    "language": "python",
    "kind": "function",
    "qualified_name": "pkg.file.fn",
    "start_line": 10,
    "end_line": 18,
    "content_hash": "abc123",
}


class TestMappingTable:
    def test_table_is_versioned_and_pins_tested_cbm_release(self):
        assert MAPPING_TABLE_VERSION >= 1
        assert TESTED_CBM_VERSION == "0.10.8"
        for mapping in RELATION_MAPPINGS.values():
            assert mapping.tested_cbm_version == TESTED_CBM_VERSION
            assert mapping.canonical_relation in CANONICAL_RELATIONS
            assert mapping.verification_condition

    @pytest.mark.parametrize("alias,canonical,direct", [
        ("call", "CALLS", True),
        ("calls", "CALLS", True),
        ("reference", "CALLS", False),
        ("usage", "CALLS", False),
        ("import", "IMPORTS", True),
        ("defines", "DEFINES", True),
        ("implements", "IMPLEMENTS", True),
        ("inherits", "INHERITS", True),
        ("extends", "INHERITS", True),
    ])
    def test_known_aliases_map_to_canonical_relations(self, alias, canonical,
                                                      direct):
        mapping = resolve_mapping(alias)
        assert mapping is not None
        assert mapping.canonical_relation == canonical
        assert mapping.direct is direct

    def test_lookup_is_case_insensitive(self):
        assert resolve_mapping(" CALLS ") is not None

    def test_unknown_relation_abstains(self):
        assert resolve_mapping("teleports") is None
        assert resolve_mapping("") is None
        assert resolve_mapping(None) is None  # type: ignore[arg-type]


class TestCanonicalSubject:
    def test_full_span_subject_normalizes(self):
        subject, problems = normalize_subject(FULL_SPAN_SUBJECT, repo_id="r1")
        assert subject is not None
        assert isinstance(subject, CanonicalSubject)
        assert (subject.repo_id, subject.language) == ("r1", "python")
        assert (subject.start_line, subject.end_line) == (10, 18)
        assert problems == ()

    def test_missing_span_flags_low_resolution_identity(self):
        raw = {k: v for k, v in FULL_SPAN_SUBJECT.items()
               if not k.startswith(("start_", "end_"))}
        subject, problems = normalize_subject(raw)
        assert subject is not None
        assert subject.start_line is None and subject.end_line is None
        assert any("span" in p for p in problems)

    def test_required_fields_missing_yields_no_subject(self):
        subject, problems = normalize_subject({"path": "a.py"})
        assert subject is None
        assert "missing kind" in problems
        assert "missing qualified_name" in problems

    def test_nested_span_object_is_unpacked(self):
        raw = dict(FULL_SPAN_SUBJECT, span={"start_line": 1, "end_line": 2})
        raw.pop("start_line"), raw.pop("end_line")
        subject, _ = normalize_subject(raw)
        assert subject is not None
        assert (subject.start_line, subject.end_line) == (1, 2)


class TestTrustCeiling:
    def test_fully_proven_assertion_is_supported_exact(self):
        verdict, resolution = trust_ceiling(
            snapshot_bound=True, has_span=True, unique_target=True,
        )
        assert (verdict, resolution) == ("SUPPORTED", ResolutionStatus.EXACT)

    def test_unbound_snapshot_never_reaches_supported(self):
        verdict, resolution = trust_ceiling(
            snapshot_bound=False, has_span=True, unique_target=True,
        )
        assert verdict == "UNVERIFIABLE"

    def test_source_changed_after_index_is_stale(self):
        verdict, _ = trust_ceiling(
            snapshot_bound=True, has_span=True, unique_target=True,
            source_changed=True,
        )
        assert verdict == "STALE"

    def test_multiple_targets_are_ambiguous(self):
        verdict, resolution = trust_ceiling(
            snapshot_bound=True, has_span=True, unique_target=False,
        )
        assert verdict == "AMBIGUOUS"
        assert resolution is ResolutionStatus.AMBIGUOUS

    def test_missing_span_caps_at_heuristic_inferred(self):
        verdict, resolution = trust_ceiling(
            snapshot_bound=True, has_span=False, unique_target=True,
        )
        assert verdict == "HEURISTIC"
        assert resolution is ResolutionStatus.INFERRED

    def test_untested_wire_caps_at_unverifiable(self):
        verdict, resolution = trust_ceiling(
            snapshot_bound=True, has_span=True, unique_target=True,
            version_compatibility=VERSION_UNTESTED,
        )
        assert verdict == "UNVERIFIABLE"
        assert resolution == ResolutionStatus.EXACT

    def test_unknown_wire_caps_at_unverifiable(self):
        verdict, _ = trust_ceiling(
            snapshot_bound=True, has_span=True, unique_target=True,
            version_compatibility=VERSION_UNKNOWN,
        )
        assert verdict == "UNVERIFIABLE"

    def test_default_version_compatibility_preserves_legacy(self):
        verdict, _ = trust_ceiling(
            snapshot_bound=True, has_span=True, unique_target=True,
        )
        assert verdict == "SUPPORTED"


class TestNormalizeAssertion:
    def test_direct_call_with_binding_and_span_is_supported(self):
        result = normalize_assertion(
            raw_subject=FULL_SPAN_SUBJECT,
            provider_relation="call",
            targets=("callee.fn",),
            repo_id="r1",
            snapshot_bound=True,
        )
        assert isinstance(result, NormalizedAssertion)
        assert result.relation == "CALLS"
        assert result.verdict == "SUPPORTED"
        assert result.resolution is ResolutionStatus.EXACT
        assert result.metadata["direct"] is True
        assert result.metadata["mapping_version"] == MAPPING_TABLE_VERSION

    def test_name_only_usage_stays_inferred_even_when_bound(self):
        raw = {k: v for k, v in FULL_SPAN_SUBJECT.items()
               if k != "start_line"}
        result = normalize_assertion(
            raw_subject=raw,
            provider_relation="usage",
            targets=("maybe.fn",),
            snapshot_bound=True,
        )
        # usage: no proving span by table definition -> ceiling HEURISTIC.
        assert result.relation == "CALLS"
        assert result.verdict == "HEURISTIC"
        assert result.resolution is ResolutionStatus.INFERRED
        assert result.metadata["direct"] is False

    def test_multi_target_call_is_ambiguous(self):
        result = normalize_assertion(
            raw_subject=FULL_SPAN_SUBJECT,
            provider_relation="calls",
            targets=("a.fn", "b.fn"),
            snapshot_bound=True,
        )
        assert result.relation == "CALLS"
        assert result.verdict == "AMBIGUOUS"
        assert result.targets == ("a.fn", "b.fn")

    def test_unbound_binding_caps_everything_at_unverifiable(self):
        result = normalize_assertion(
            raw_subject=FULL_SPAN_SUBJECT,
            provider_relation="call",
            targets=("callee.fn",),
            snapshot_bound=False,
        )
        assert result.verdict == "UNVERIFIABLE"

    def test_unknown_provider_relation_abstains_to_unknown(self):
        result = normalize_assertion(
            raw_subject=FULL_SPAN_SUBJECT,
            provider_relation="teleports",
            targets=("x",),
            snapshot_bound=True,
        )
        assert result.relation == "UNKNOWN"
        assert any("unmapped" in p for p in result.problems)
