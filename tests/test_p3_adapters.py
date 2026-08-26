"""P3.1 — structured provider adapters.

The exit gate: no production evidence parser depends on whitespace text
reports. search/trace/impact speak format=json end-to-end; drift abstains;
directed trace edges keep direction/hop/strategy/confidence; detect_changes
scopes to git refs with a shared diff_identity; staged/working-tree scopes
record a scope conflict instead of merging.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sot_graph.assurance import (  # noqa: E402
    cbm_candidates_from_outcome,
    federated_extras,
    search_rows_from_payload,
    trace_edges_from_payload,
)
from sot_graph.db import Database  # noqa: E402
from sot_graph.reconciler import Reconciler  # noqa: E402
from sot_graph.providers.base import ImpactRequest  # noqa: E402
from sot_graph.providers_registry import BUILTIN_LANGUAGE_SCORECARD  # noqa: E402


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "app.py").write_text(
        "def target():\n    return 1\n\n\ndef caller():\n    return target()\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    db = Database(str(repo / ".sot" / "sot.db"))
    try:
        Reconciler(db, str(repo)).reconcile()
    finally:
        db.close()
    return repo


SEARCH_OK = {
    "total": 1, "search_mode": "bm25",
    "cols": ["qn", "label", "file", "lines", "rank"],
    "rows": [["proj.core.compute_total", "Function", "core/service.py", "6-9", -22.19]],
    "has_more": False,
}

TRACE_OK = {
    "function": "compute_total", "direction": "both",
    "callees_total": 1,
    "callees": {"cols": ["name", "hop", "strategy", "confidence"],
                "groups": [{"qn_prefix": "proj.core",
                            "rows": [["format_label", 1, "lsp", 0.97]]}]},
    "callers_total": 1,
    "callers": {"cols": ["name", "hop", "strategy", "confidence"],
                "groups": [{"qn_prefix": "proj.app",
                            "rows": [["dispatch", 1, "heuristic", 0.61]]}]},
}


class _Outcome:
    def __init__(self, payload, ok=True):
        self.ok = ok
        self.payload = payload
        self.metadata = {"wire_status": "ok", "version_compatibility": "COMPATIBLE"}
        self.error = None
        self.next_action = None


class TestSearchStructuredParse:
    def test_keeps_qualified_name_span_rank(self):
        rows, has_more, drift = search_rows_from_payload(SEARCH_OK)
        assert drift is False and has_more is False
        row = rows[0]
        assert row["qualified_name"] == "proj.core.compute_total"
        assert (row["start_line"], row["end_line"]) == (6, 9)
        assert row["rank"] == -22.19

    def test_no_short_name_normalization(self):
        rows, _, _ = search_rows_from_payload(SEARCH_OK)
        # the FULL qualified name is preserved; nothing collapses to a short name
        assert "." in rows[0]["qualified_name"]
        assert rows[0]["qualified_name"].endswith("compute_total")

    def test_missing_cols_abstains(self):
        rows, _, drift = search_rows_from_payload({"rows": [["x"]], "has_more": False})
        assert drift is True and rows == []

    def test_missing_qn_col_abstains(self):
        bad = dict(SEARCH_OK, cols=["label", "file", "lines", "rank"])
        rows, _, drift = search_rows_from_payload(bad)
        assert drift is True and rows == []

    def test_short_row_skipped_never_guessed(self):
        bad = dict(SEARCH_OK, rows=[["only-qn"]])
        rows, _, drift = search_rows_from_payload(bad)
        assert drift is False and rows == []

    def test_non_structured_payload_abstains_in_candidates(self):
        cands, _, note = cbm_candidates_from_outcome(
            _Outcome("total: 1\nhas_more: false"), "search_symbols", "codebase-memory"
        )
        assert cands == []
        assert note and "text-report parsing was removed" in note

    def test_lines_cell_drift_yields_no_span(self):
        bad = dict(SEARCH_OK, rows=[["qn", "Function", "f.py", "6-?", -1.0]])
        rows, _, drift = search_rows_from_payload(bad)
        assert drift is False
        assert rows[0]["start_line"] is None  # low-resolution, never invented


class TestTraceStructuredParse:
    def test_directed_edges_with_evidence(self):
        edges = trace_edges_from_payload(TRACE_OK)
        by_direction = {e["direction"]: e for e in edges}
        callee = by_direction["callees"]
        caller = by_direction["callers"]
        # root -> callee: far side is the callee qn, root preserved
        assert callee["qualified_name"] == "proj.core.format_label"
        assert callee["root"] == "compute_total"
        assert callee["hop"] == 1 and callee["strategy"] == "lsp"
        assert callee["confidence"] == 0.97
        # caller -> root
        assert caller["qualified_name"] == "proj.app.dispatch"
        assert caller["strategy"] == "heuristic" and caller["confidence"] == 0.61

    def test_candidates_carry_direction_and_strategy(self):
        cands, _, note = cbm_candidates_from_outcome(
            _Outcome(TRACE_OK), "trace", "codebase-memory", repo_root=None
        )
        assert note is None
        kinds = {(c["direction"], c["strategy"]) for c in cands}
        assert ("callees", "lsp") in kinds and ("callers", "heuristic") in kinds
        # far side is the subject; the traced root is the single target
        for cand in cands:
            assert cand["targets"] == ["compute_total"]

    def test_missing_sections_yield_no_edges(self):
        assert trace_edges_from_payload({"function": "x"}) == []

    def test_edge_type_column_travels_when_present(self):
        payload = json.loads(json.dumps(TRACE_OK))
        payload["callees"]["cols"] = ["name", "hop", "edge_type"]
        payload["callees"]["groups"][0]["rows"] = [["format_label", 1, "CALL_REFERENCE"]]
        edges = trace_edges_from_payload(payload)
        assert edges[0]["edge_type"] == "CALL_REFERENCE"
        assert edges[0]["strategy"] is None  # absent column stays None


class TestImpactScoping:
    def test_staged_scope_conflicts_not_merges(self, repo):
        fed = federated_extras(
            "prefer:codebase-memory", str(repo), "diff-impact", "HEAD~1",
            staged=True,
        )
        assert fed is not None
        assert any("scope conflict" in w for w in fed["warnings"])
        assert fed["candidates"] == []
        assert any("scope conflict" in g for g in fed["known_gaps"] or [])

    def test_working_tree_scope_conflicts_not_merges(self, repo):
        fed = federated_extras(
            "prefer:codebase-memory", str(repo), "diff-impact", "HEAD~1",
            working_tree=True,
        )
        assert any("scope conflict" in w for w in fed["warnings"])

    def test_diff_identity_pins_commit_pair(self, repo):
        (repo / "extra.py").write_text("def another():\n    return 2\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "second")
        fed = federated_extras(
            "prefer:codebase-memory", str(repo), "diff-impact", "HEAD~1",
        )
        assert fed is not None
        assert fed["diff_identity"] and ".." in fed["diff_identity"]
        base, head = fed["diff_identity"].split("..")
        assert len(base) == 12 and len(head) == 12 and base != head

    def test_diff_identity_unresolvable_ref_declares_gap(self, repo):
        fed = federated_extras(
            "prefer:codebase-memory", str(repo), "diff-impact", "no-such-ref",
        )
        assert fed["diff_identity"] is None
        assert any("cannot resolve diff identity" in w for w in fed["warnings"])

    def test_impact_request_maps_target_to_since(self):
        request = ImpactRequest(
            repo_root="/r", path="/r", since="HEAD~5", depth=3,
        )
        assert request.since == "HEAD~5" and request.depth == 3

    def test_impact_candidates_from_structured_payload(self):
        payload = {
            "changed_files": [{"path": "a.py"}],
            "impacted": [{"path": "b.py"}, {"path": "c.py"}],
            "truncated": True,
        }
        cands, truncated, note = cbm_candidates_from_outcome(
            _Outcome(payload), "impact", "codebase-memory", repo_root=None
        )
        assert {t for c in cands for t in c["targets"]} == {"b.py", "c.py"}
        # detect_changes has no canonical relation mapping by design: the
        # candidates stay advisory (UNKNOWN) with the unmapped-relation problem.
        assert all(c["relation"] == "UNKNOWN" for c in cands)
        assert any("unmapped provider relation" in p for c in cands for p in c["problems"])
        assert truncated is True
        assert any("missing kind" in p for c in cands for p in c["problems"])


class TestBuiltinCapabilityHonesty:
    """P3.3: builtin declares per language x relation strength (oracle P0)."""

    def test_scorecard_declared_on_status(self, repo):
        from sot_graph.config import load_config
        from sot_graph.providers_registry import (
            BUILTIN_LANGUAGE_SCORECARD,
            detect_providers,
        )

        cfg = load_config(str(repo))
        builtin = next(
            s for s in detect_providers(str(repo), cfg) if s.name == "sot-builtin"
        )
        assert builtin.language_capability == BUILTIN_LANGUAGE_SCORECARD
        assert "weak:" in builtin.detail
        assert "rust.implements" in builtin.detail and "java.implements" in builtin.detail
        assert "rust.calls" not in builtin.detail  # P3.3b fixed Go/TS/Rust call recall

    def test_scorecard_matches_oracle_baseline_numbers(self):
        baseline = json.loads(
            (Path(__file__).parent.parent / "benchmarks" / "oracle"
             / "builtin-baseline.json").read_text(encoding="utf-8")
        )
        per_language = baseline["builtin"]["per_language"]
        for lang, relations in BUILTIN_LANGUAGE_SCORECARD.items():
            for rel, f1 in relations.items():
                measured = per_language[lang][rel]["f1"]
                assert abs(f1 - round(measured, 3)) < 1e-9, (
                    f"{lang}.{rel}: declared {f1} vs measured {measured}"
                )
