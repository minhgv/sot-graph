"""P2 source/span verification tests — verifier, ceiling matrix, CLI wiring.

Covers: VERIFIED happy path against the real fixture repo, span drift after
edit (SPAN_MISMATCH), deleted files (MISSING), intra-span same-name
ambiguity (AMBIGUOUS), path-traversal rejection, generated/vendor
NOT_APPLICABLE + known gaps, the trust_ceiling verdict matrix (including the
verification=None backward-compat regression), and the CLI candidate /
conflict wiring with fake CBM outcomes.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from sot_graph.evidence import ResolutionStatus
from sot_graph.providers import verification as vmod
from sot_graph.providers.normalization import (
    VERDICT_AMBIGUOUS,
    VERDICT_HEURISTIC,
    VERDICT_STALE,
    VERDICT_SUPPORTED,
    VERDICT_UNVERIFIABLE,
    trust_ceiling,
)
from sot_graph.providers.verification import (
    AMBIGUOUS,
    MISSING,
    NOT_APPLICABLE,
    SPAN_MISMATCH,
    VERIFIED,
    VerificationOutcome,
    verify_edge,
    verify_subject,
)

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "cbm_sample_repo"

COMPUTE_TOTAL = {
    "qualified_name": "core.service.compute_total",
    "kind": "function",
    "path": "core/service.py",
    "start_line": 6,
    "end_line": 9,
}


def _search_payload(*rows: str, has_more: bool = False) -> str:
    text = "\n".join(rows) + f"\nhas_more: {'true' if has_more else 'false'}\n"
    return text


def _fake_outcome(payload: str, snapshot_match=None, ok: bool = True):
    ns = SimpleNamespace(ok=ok, payload=payload, metadata={}, error=None,
                         next_action=None)
    if snapshot_match is not None:
        ns.snapshot_match = snapshot_match
    return ns


# ---------------------------------------------------------------------------
# verify_subject — unit level on the real fixture repo
# ---------------------------------------------------------------------------


class TestVerifySubject:
    def test_verified_happy_path_on_fixture_repo(self):
        outcome = verify_subject(COMPUTE_TOTAL, str(FIXTURE_REPO))
        assert outcome.status == VERIFIED
        assert "compute_total" in outcome.detail

    def test_span_shifted_after_edit_is_span_mismatch(self):
        drifted = dict(COMPUTE_TOTAL, start_line=100, end_line=105)
        outcome = verify_subject(drifted, str(FIXTURE_REPO))
        assert outcome.status == SPAN_MISMATCH

    def test_span_without_definition_is_span_mismatch(self):
        # Span covers the module docstring only; token absent entirely.
        subject = dict(COMPUTE_TOTAL, start_line=1, end_line=1)
        outcome = verify_subject(subject, str(FIXTURE_REPO))
        assert outcome.status == SPAN_MISMATCH

    def test_deleted_file_is_missing(self):
        ghost = dict(COMPUTE_TOTAL, path="core/deleted_long_ago.py")
        outcome = verify_subject(ghost, str(FIXTURE_REPO))
        assert outcome.status == MISSING

    def test_path_traversal_outside_root_is_rejected(self):
        evil = dict(COMPUTE_TOTAL, path="../../etc/passwd")
        outcome = verify_subject(evil, str(FIXTURE_REPO))
        assert outcome.status == MISSING
        assert "escapes repository root" in outcome.detail

    def test_absolute_path_outside_root_is_rejected(self):
        evil = dict(COMPUTE_TOTAL, path="/etc/passwd")
        outcome = verify_subject(evil, str(FIXTURE_REPO))
        assert outcome.status == MISSING
        assert "escapes" in outcome.detail

    def test_generated_pb2_file_not_applicable_with_known_gap(self):
        gen = dict(COMPUTE_TOTAL, path="generated/models_pb2.py")
        outcome = verify_subject(gen, str(FIXTURE_REPO))
        assert outcome.status == NOT_APPLICABLE
        assert outcome.known_gaps

    def test_vendor_dir_not_applicable(self):
        vendored = dict(COMPUTE_TOTAL, path="node_modules/pkg/mod.py")
        assert verify_subject(vendored, str(FIXTURE_REPO)).status == NOT_APPLICABLE

    def test_no_span_is_not_applicable(self):
        bare = {"qualified_name": "core.service.compute_total", "kind": "function",
                "path": "core/service.py"}
        outcome = verify_subject(bare, str(FIXTURE_REPO))
        assert outcome.status == NOT_APPLICABLE

    def test_same_name_twice_inside_one_span_is_ambiguous(self, tmp_path):
        (tmp_path / "dupes.py").write_text(
            "def format_label(a, b):\n    return a\n\n\n"
            "def format_label(c, d):\n    return c\n",
            encoding="utf-8",
        )
        subject = {
            "qualified_name": "dupes.format_label", "kind": "function",
            "path": "dupes.py", "start_line": 1, "end_line": 6,
        }
        outcome = verify_subject(subject, str(tmp_path))
        assert outcome.status == AMBIGUOUS
        assert "not unique" in outcome.detail


class TestVerifyEdge:
    def test_edge_source_without_span_is_not_applicable(self):
        edge = SimpleNamespace(subject={
            "qualified_name": "x.y", "kind": "function", "path": "core/service.py",
        })
        outcome = verify_edge(edge, str(FIXTURE_REPO))
        assert outcome.status == NOT_APPLICABLE

    def test_edge_with_span_delegates_to_verify_subject(self):
        edge = SimpleNamespace(subject=dict(COMPUTE_TOTAL))
        assert verify_edge(edge, str(FIXTURE_REPO)).status == VERIFIED


# ---------------------------------------------------------------------------
# trust_ceiling — P2 verdict matrix (+ legacy regression)
# ---------------------------------------------------------------------------

FRESH_MATCH = {"bound": True, "fresh": True, "detail": "head sha ok"}
STALE_MATCH = {"bound": True, "fresh": False, "detail": "head moved"}
UNBOUND_MATCH = {"bound": False, "fresh": True, "detail": "no snapshot"}
PROVEN = dict(snapshot_bound=True, has_span=True, unique_target=True)


class TestTrustCeilingMatrix:
    # -- legacy behaviour preserved when verification is None ---------------
    def test_legacy_supported_exact_unchanged(self):
        assert trust_ceiling(**PROVEN) == (
            VERDICT_SUPPORTED, ResolutionStatus.EXACT
        )

    def test_legacy_unbound_never_supported(self):
        verdict, resolution = trust_ceiling(
            snapshot_bound=False, has_span=True, unique_target=True
        )
        assert verdict == VERDICT_UNVERIFIABLE
        assert resolution is ResolutionStatus.EXACT  # structure still informs

    def test_legacy_stale_and_heuristic_paths_unchanged(self):
        assert trust_ceiling(
            snapshot_bound=True, has_span=True, unique_target=True,
            source_changed=True,
        ) == (VERDICT_STALE, ResolutionStatus.EXACT)
        assert trust_ceiling(
            snapshot_bound=True, has_span=False, unique_target=True
        ) == (VERDICT_HEURISTIC, ResolutionStatus.INFERRED)
        assert trust_ceiling(
            snapshot_bound=True, has_span=True, unique_target=False
        ) == (VERDICT_AMBIGUOUS, ResolutionStatus.AMBIGUOUS)

    # -- bound+fresh matrix --------------------------------------------------
    def test_bound_fresh_verified_is_supported_exact(self):
        live = verify_subject(COMPUTE_TOTAL, str(FIXTURE_REPO))
        assert live.status == VERIFIED
        assert trust_ceiling(**PROVEN, verification=live,
                             snapshot_match=FRESH_MATCH) == (
            VERDICT_SUPPORTED, ResolutionStatus.EXACT
        )

    def test_bound_fresh_span_mismatch_downgrades_to_heuristic(self):
        drifted = dict(COMPUTE_TOTAL, start_line=100, end_line=105)
        live = verify_subject(drifted, str(FIXTURE_REPO))
        assert live.status == SPAN_MISMATCH
        verdict, resolution = trust_ceiling(
            **PROVEN, verification=live, snapshot_match=FRESH_MATCH
        )
        assert verdict == VERDICT_HEURISTIC
        assert resolution is ResolutionStatus.INFERRED

    def test_bound_fresh_missing_file_downgrades_to_heuristic(self):
        live = verify_subject(dict(COMPUTE_TOTAL, path="core/gone.py"),
                              str(FIXTURE_REPO))
        verdict, resolution = trust_ceiling(
            **PROVEN, verification=live, snapshot_match=FRESH_MATCH
        )
        assert (verdict, resolution) == (
            VERDICT_HEURISTIC, ResolutionStatus.INFERRED
        )

    def test_bound_fresh_ambiguous_is_ambiguous(self):
        live = VerificationOutcome(AMBIGUOUS, "two defs in span")
        assert trust_ceiling(**PROVEN, verification=live,
                             snapshot_match=FRESH_MATCH) == (
            VERDICT_AMBIGUOUS, ResolutionStatus.AMBIGUOUS
        )

    def test_bound_fresh_not_applicable_stays_structural_only(self):
        live = VerificationOutcome(NOT_APPLICABLE, "generated file")
        verdict, resolution = trust_ceiling(
            **PROVEN, verification=live, snapshot_match=FRESH_MATCH
        )
        assert verdict == VERDICT_HEURISTIC
        assert resolution is ResolutionStatus.INFERRED

    # -- never self-elevate --------------------------------------------------
    def test_stale_snapshot_keeps_stale_even_when_verified(self):
        live = VerificationOutcome(VERIFIED, "on disk ok")
        assert trust_ceiling(**PROVEN, verification=live,
                             snapshot_match=STALE_MATCH)[0] == VERDICT_STALE

    def test_unbound_snapshot_match_cannot_elevate(self):
        live = VerificationOutcome(VERIFIED, "on disk ok")
        assert trust_ceiling(**PROVEN, verification=live,
                             snapshot_match=UNBOUND_MATCH)[0] == (
            VERDICT_UNVERIFIABLE
        )

    def test_missing_snapshot_match_report_is_unbound(self):
        live = VerificationOutcome(VERIFIED, "on disk ok")
        assert trust_ceiling(**PROVEN, verification=live,
                             snapshot_match=None)[0] == VERDICT_UNVERIFIABLE

    def test_snapshot_match_accepts_attribute_objects(self):
        match = SimpleNamespace(bound=True, fresh=True, detail="ok")
        live = VerificationOutcome(VERIFIED, "ok")
        assert trust_ceiling(**PROVEN, verification=live,
                             snapshot_match=match)[0] == VERDICT_SUPPORTED

    def test_verification_accepts_bare_status_string(self):
        assert trust_ceiling(**PROVEN, verification=VERIFIED,
                             snapshot_match=FRESH_MATCH)[0] == VERDICT_SUPPORTED


# ---------------------------------------------------------------------------
# CLI wiring — fake executable outcomes, no subprocess
# ---------------------------------------------------------------------------


class TestCandidatesWiring:
    def test_verified_candidate_reaches_supported_when_fresh(self):
        from sot_graph.assurance import cbm_candidates_from_outcome

        payload = _search_payload(
            "core.service.compute_total function core/service.py 6-9 0.98"
        )
        outcome = _fake_outcome(payload, snapshot_match=FRESH_MATCH)
        candidates, truncated, gap_note = cbm_candidates_from_outcome(
            outcome, "search", "codebase-memory", repo_root=str(FIXTURE_REPO)
        )
        assert truncated is False and gap_note is None
        cand = candidates[0]
        assert cand["verdict"] == VERDICT_SUPPORTED
        assert cand["resolution"] == "EXACT"
        assert cand["verified"] == VERIFIED
        assert isinstance(cand["detail"], str) and cand["detail"]

    def test_adapter_metadata_freshness_reaches_supported(self):
        """P2 adapter travels the binding in metadata, not an attribute."""
        from sot_graph.assurance import cbm_candidates_from_outcome

        payload = _search_payload(
            "core.service.compute_total function core/service.py 6-9 0.98"
        )
        outcome = SimpleNamespace(
            ok=True, payload=payload,
            metadata={"freshness": "FRESH", "snapshot_bound": True,
                      "source_changed": False},
            error=None, next_action=None,
        )
        candidates, _, gap_note = cbm_candidates_from_outcome(
            outcome, "search", "codebase-memory", repo_root=str(FIXTURE_REPO)
        )
        cand = candidates[0]
        assert cand["verified"] == VERIFIED
        assert cand["verdict"] == VERDICT_SUPPORTED
        assert cand["resolution"] == "EXACT"

    def test_adapter_metadata_stale_yields_stale(self):
        from sot_graph.assurance import cbm_candidates_from_outcome

        payload = _search_payload(
            "core.service.compute_total function core/service.py 6-9 0.98"
        )
        outcome = SimpleNamespace(
            ok=True, payload=payload,
            metadata={"freshness": "STALE", "snapshot_bound": True,
                      "source_changed": True},
            error=None, next_action=None,
        )
        candidates, _, _ = cbm_candidates_from_outcome(
            outcome, "search", "codebase-memory", repo_root=str(FIXTURE_REPO)
        )
        assert candidates[0]["verdict"] == VERDICT_STALE

    def test_adapter_metadata_unbound_caps_at_unverifiable(self):
        from sot_graph.assurance import cbm_candidates_from_outcome

        payload = _search_payload(
            "core.service.compute_total function core/service.py 6-9 0.98"
        )
        outcome = SimpleNamespace(
            ok=True, payload=payload,
            metadata={"freshness": "UNBOUND", "snapshot_bound": False},
            error=None, next_action=None,
        )
        candidates, _, _ = cbm_candidates_from_outcome(
            outcome, "search", "codebase-memory", repo_root=str(FIXTURE_REPO)
        )
        assert candidates[0]["verdict"] == VERDICT_UNVERIFIABLE

    def test_metadata_without_binding_markers_stays_p1(self):
        from sot_graph.assurance import cbm_candidates_from_outcome

        payload = _search_payload(
            "core.service.compute_total function core/service.py 6-9 0.98"
        )
        candidates, _, _ = cbm_candidates_from_outcome(
            SimpleNamespace(ok=True, payload=payload,
                            metadata={"wire_status": "ok"}, error=None,
                            next_action=None),
            "search", "codebase-memory", repo_root=str(FIXTURE_REPO),
        )
        assert candidates[0]["verdict"] == VERDICT_UNVERIFIABLE
        assert candidates[0]["verified"] == VERIFIED

    def test_drifted_candidate_is_downgraded_not_supported(self):
        from sot_graph.assurance import cbm_candidates_from_outcome

        payload = _search_payload(
            "app.main.build_invoice function app/main.py 50-60 0.91"
        )
        outcome = _fake_outcome(payload, snapshot_match=FRESH_MATCH)
        candidates, _, _ = cbm_candidates_from_outcome(
            outcome, "search", "codebase-memory", repo_root=str(FIXTURE_REPO)
        )
        cand = candidates[0]
        assert cand["verified"] in (SPAN_MISMATCH, MISSING)
        assert cand["verdict"] == VERDICT_HEURISTIC
        assert cand["resolution"] == "INFERRED"

    def test_no_snapshot_match_attr_caps_at_unverifiable(self):
        from sot_graph.assurance import cbm_candidates_from_outcome

        payload = _search_payload(
            "core.service.compute_total function core/service.py 6-9 0.98"
        )
        candidates, _, _ = cbm_candidates_from_outcome(
            _fake_outcome(payload), "search", "codebase-memory",
            repo_root=str(FIXTURE_REPO),
        )
        cand = candidates[0]
        assert cand["verified"] == VERIFIED  # on-disk evidence recorded…
        assert cand["verdict"] == VERDICT_UNVERIFIABLE  # …but cannot elevate

    def test_stale_snapshot_yields_stale_verdict(self):
        from sot_graph.assurance import cbm_candidates_from_outcome

        payload = _search_payload(
            "core.service.compute_total function core/service.py 6-9 0.98"
        )
        outcome = _fake_outcome(payload, snapshot_match=STALE_MATCH)
        candidates, _, _ = cbm_candidates_from_outcome(
            outcome, "search", "codebase-memory", repo_root=str(FIXTURE_REPO)
        )
        assert candidates[0]["verdict"] == VERDICT_STALE

    def test_repo_root_none_preserves_p1_behaviour(self):
        from sot_graph.assurance import cbm_candidates_from_outcome

        payload = _search_payload(
            "core.service.compute_total function core/service.py 6-9 0.98"
        )
        outcome = _fake_outcome(payload, snapshot_match=FRESH_MATCH)
        candidates, _, _ = cbm_candidates_from_outcome(
            outcome, "search", "codebase-memory", repo_root=None
        )
        cand = candidates[0]
        assert cand["verdict"] == VERDICT_UNVERIFIABLE
        assert "verified" not in cand


class TestTargetConflicts:
    def _cand(self, qn, path, line, verified=None):
        cand = {
            "provider": "codebase-memory",
            "subject": {"qualified_name": qn, "kind": "function",
                        "path": path, "start_line": line, "end_line": line},
        }
        if verified is not None:
            cand["verified"] = verified
        return cand

    def test_cbm_verified_wins_and_builtin_contradicted(self):
        from sot_graph.assurance import target_conflicts

        conflicts = target_conflicts(
            ("format_label", "core/service.py", 99),  # builtin span stale
            [self._cand("core.labels.format_label", "core/labels.py", 4)],
            repo_root=str(FIXTURE_REPO),
        )
        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict["kind"] == "target_mismatch"
        assert conflict["resolution"] == "source_verified"
        assert conflict["resolved"]["path"] == "core/labels.py"
        assert conflict["contradicted"]["path"] == "core/service.py"
        assert conflict["resolved"]["verified"] == VERIFIED
        # Still listed — never silently dropped:
        assert conflict["builtin"]["line"] == 99

    def test_builtin_verified_wins_when_cbm_span_drifted(self):
        from sot_graph.assurance import target_conflicts

        conflicts = target_conflicts(
            ("compute_total", "core/service.py", 6),
            [self._cand("core.service.compute_total",
                        "core/service.py", 100)],
            repo_root=str(FIXTURE_REPO),
        )
        conflict = conflicts[0]
        assert conflict["resolution"] == "source_verified"
        assert conflict["resolved"]["line"] == 6
        assert conflict["contradicted"]["line"] == 100

    def test_both_sides_unverified_stays_recorded_not_resolved(self):
        from sot_graph.assurance import target_conflicts

        conflicts = target_conflicts(
            ("compute_total", "core/nowhere.py", 3),
            [self._cand("core.service.compute_total",
                        "core/elsewhere.py", 3)],
            repo_root=str(FIXTURE_REPO),
        )
        assert conflicts[0]["resolution"] == "recorded-not-resolved"
        assert "resolved" not in conflicts[0]

    def test_both_sides_verified_does_not_adjudicate(self):
        # Same-name symbol genuinely defined on both sides (format_label x2):
        # neither side is contradicted by source, so no silent pick.
        from sot_graph.assurance import target_conflicts

        conflicts = target_conflicts(
            ("format_label", "core/service.py", 12),
            [self._cand("core.labels.format_label", "core/labels.py", 4)],
            repo_root=str(FIXTURE_REPO),
        )
        assert conflicts[0]["resolution"] == "recorded-not-resolved"

    def test_end_to_end_pipeline_conflict_via_fake_binary(self):
        """Full flow: parse report -> verify -> ceiling -> conflict."""
        from sot_graph.assurance import cbm_candidates_from_outcome, target_conflicts

        payload = _search_payload(
            "core.service.compute_total function core/service.py 42-45 0.95"
        )
        outcome = _fake_outcome(payload, snapshot_match=FRESH_MATCH)
        candidates, _, gap_note = cbm_candidates_from_outcome(
            outcome, "search", "codebase-memory", repo_root=str(FIXTURE_REPO)
        )
        assert gap_note is None
        cand = candidates[0]
        assert cand["verified"] == SPAN_MISMATCH
        assert cand["verdict"] == VERDICT_HEURISTIC

        conflicts = target_conflicts(
            ("compute_total", "core/service.py", 6),
            candidates, repo_root=str(FIXTURE_REPO),
        )
        assert conflicts[0]["resolution"] == "source_verified"
        assert conflicts[0]["resolved"]["line"] == 6
        assert conflicts[0]["contradicted"]["line"] == 42


class TestFederatedExtrasGaps:
    """known_gaps honesty at the federated_extras level (plan mocked)."""

    @pytest.fixture()
    def wired_cli(self, monkeypatch):
        import sot_graph.assurance.orchestrator as orch

        def run(outcome):
            monkeypatch.setattr(
                orch, "federation_plan",
                lambda spec, root, kind: {
                    "mode": "prefer", "warnings": [], "fail_message": None,
                    "status": {"name": "cbm", "version": "0.10.8"},
                    "name": "cbm", "provider": object(),
                },
            )
            monkeypatch.setattr(
                orch, "run_federated_query",
                lambda plan, root, kind, sym: (outcome, "search"),
            )
            return orch.federated_extras(
                "prefer:cbm", str(FIXTURE_REPO), "explore", "compute_total"
            )

        return run

    def test_gaps_reflect_snapshot_state_and_verification(self, wired_cli):
        payload = _search_payload(
            "core.service.compute_total function core/service.py 6-9 0.98",
            "app.main.dispatch function app/main.py 900-902 0.80",
        )
        fed = wired_cli(_fake_outcome(payload, snapshot_match=FRESH_MATCH))
        assert not any("snapshot binding unproven" in g for g in fed["known_gaps"])
        joined = "\n".join(fed["known_gaps"])
        assert "source verification SPAN_MISMATCH" in joined or (
            "source verification MISSING" in joined
        )

    def test_unbound_snapshot_keeps_binding_gap_and_cap(self, wired_cli):
        payload = _search_payload(
            "core.service.compute_total function core/service.py 6-9 0.98"
        )
        outcome = _fake_outcome(payload, snapshot_match=UNBOUND_MATCH)
        fed = wired_cli(outcome)
        assert any("snapshot binding unproven" in g for g in fed["known_gaps"])
        assert fed["candidates"][0]["verdict"] == VERDICT_UNVERIFIABLE

    def test_federated_extras_accepts_adapter_metadata_shape(self, wired_cli):
        from sot_graph.assurance import cbm_candidates_from_outcome  # noqa: F401

        payload = _search_payload(
            "core.service.compute_total function core/service.py 6-9 0.98"
        )
        outcome = SimpleNamespace(
            ok=True, payload=payload,
            metadata={"freshness": "FRESH", "snapshot_bound": True},
            error=None, next_action=None,
        )
        fed = wired_cli(outcome)
        assert not any("snapshot binding unproven" in g
                       for g in fed["known_gaps"])
        assert fed["candidates"][0]["verdict"] == VERDICT_SUPPORTED
