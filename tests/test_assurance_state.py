"""Unit tests for the canonical assurance state machine (state.py)."""

from sot_graph.assurance.state import (
    CANONICAL_STATUSES,
    CLAIM_PROFILES,
    STATUS_SEVERITY,
    AssuranceFacts,
    decide,
)


def _base_facts(**kwargs) -> AssuranceFacts:
    default_kwargs = {
        "identity_status": "UNIQUE",
        "snapshot_bound": True,
        "stale_files": [],
        "coverage_measured": True,
        "coverage_fraction": 0.95,
        "coverage_floor": 0.9,
        "parser_failures": 0,
        "unresolved_count": 0,
        "unresolved_budget": 0,
        "open_conflicts": 0,
        "truncated": False,
        "provider_capability_ok": True,
        "absence_claim": True,
        "gate_blocked": False,
        "dynamic_dispatch_unresolved": False,
        "claim_profile": "absence",
    }
    default_kwargs.update(kwargs)
    return AssuranceFacts(**default_kwargs)


class TestAssuranceState:
    def test_canonical_statuses_and_severity(self):
        assert "presence" in CLAIM_PROFILES and "absence" in CLAIM_PROFILES
        assert set(CANONICAL_STATUSES) == set(STATUS_SEVERITY.keys())
        assert STATUS_SEVERITY["ABSTAINED"] > STATUS_SEVERITY["UNVERIFIABLE"]
        assert STATUS_SEVERITY["UNVERIFIABLE"] > STATUS_SEVERITY["STALE"]
        assert STATUS_SEVERITY["STALE"] > STATUS_SEVERITY["CONFLICTED"]
        assert STATUS_SEVERITY["CONFLICTED"] > STATUS_SEVERITY["PARTIAL"]
        assert STATUS_SEVERITY["PARTIAL"] > STATUS_SEVERITY["ASSURED_WITHIN_SCOPE"]

    def test_all_clear_yields_assured(self):
        facts = _base_facts()
        res = decide(facts)
        assert res["status"] == "ASSURED_WITHIN_SCOPE"
        assert res["reason_codes"] == []

    def test_identity_not_found_yields_abstained(self):
        facts = _base_facts(identity_status="NOT_FOUND")
        res = decide(facts)
        assert res["status"] == "ABSTAINED"
        assert "target_not_found" in res["reason_codes"]

    def test_identity_ambiguous_yields_abstained(self):
        facts = _base_facts(identity_status="AMBIGUOUS")
        res = decide(facts)
        assert res["status"] == "ABSTAINED"
        assert "target_ambiguous" in res["reason_codes"]

    def test_unbound_snapshot_yields_unverifiable(self):
        facts = _base_facts(snapshot_bound=False)
        res = decide(facts)
        assert res["status"] == "UNVERIFIABLE"
        assert "snapshot_unbound" in res["reason_codes"]

    def test_stale_files_yields_stale(self):
        facts = _base_facts(stale_files=["src/app.py"])
        res = decide(facts)
        assert res["status"] == "STALE"
        assert "stale_sources" in res["reason_codes"]

    def test_open_conflicts_yields_conflicted(self):
        facts = _base_facts(open_conflicts=2)
        res = decide(facts)
        assert res["status"] == "CONFLICTED"
        assert "open_conflicts" in res["reason_codes"]

    def test_multiple_violations_collects_all_reasons_and_max_severity(self):
        # Stale (severity 30), parser_failures (severity 10), coverage_below_floor (severity 10)
        facts = _base_facts(
            stale_files=["src/foo.py"],
            parser_failures=1,
            coverage_measured=False,
        )
        res = decide(facts)
        assert res["status"] == "STALE"
        assert "stale_sources" in res["reason_codes"]
        assert "parser_failures" in res["reason_codes"]
        assert "coverage_below_floor" in res["reason_codes"]

    def test_abstained_dominates_unverifiable_and_partial(self):
        facts = _base_facts(
            identity_status="NOT_FOUND",
            snapshot_bound=False,
            truncated=True,
        )
        res = decide(facts)
        assert res["status"] == "ABSTAINED"
        assert set(res["reason_codes"]) == {"target_not_found", "snapshot_unbound", "transitive_truncated"}

    def test_presence_claim_allows_unmeasured_coverage(self):
        facts = _base_facts(
            absence_claim=False,
            claim_profile="presence",
            coverage_measured=False,
            coverage_fraction=None,
        )
        res = decide(facts)
        assert res["status"] == "ASSURED_WITHIN_SCOPE"
        assert res["reason_codes"] == []

    def test_dynamic_dispatch_unresolved_degrades_to_partial(self):
        facts = _base_facts(dynamic_dispatch_unresolved=True)
        res = decide(facts)
        assert res["status"] == "PARTIAL"
        assert "dynamic_dispatch_unresolved" in res["reason_codes"]
