"""P0 oracle self-checks: the exact 6-tuple oracle must discriminate defects.

Two layers:
  1. Synthetic matcher tests (no production code, deterministic forever):
     a wrong-target edge and a bare name on a different edge are NEVER true
     positives, while the pre-v2 loose matcher counts them — proving the
     oracle catches the defect class the old metric hid.
  2. One integration run over the real corpus asserting the machine-readable
     baseline contract (per-language breakdown, line-anchored confusion set,
     consistent counts, search top-k section).
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ANCHOR_RE = re.compile(r"^.+:\d+ .+ -> .+ \(.+\) \[.+\]")
def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def evaluator():
    return _load_module("sot_evaluator")


class TestSyntheticDiscrimination:
    """Oracle logic only — plain data in, verdicts out."""

    def test_wrong_target_same_bare_name_is_not_tp(self, evaluator):
        # The DB binds the call to a DIFFERENT symbol that merely shares the
        # bare name "Check" (defined in another file) — never a true positive.
        truths = [evaluator.EdgeTruth(
            evaluator.CORPUS_REPO_ID, "pkg/a.go", "caller", "calls",
            "Worker.Check", "pkg/b.go", 10, "go", "static_positive", "call")]
        db = [evaluator.DbEdge("pkg/a.go", "caller", "calls", "Check", "pkg/c.go", 10)]
        report = evaluator.evaluate_edges(truths, db, [])
        assert report.counts["true_positives"] == 0
        assert report.counts["false_negatives"] == 1
        assert any("wrong_target_same_bare_name" in c for c in report.confusion)
        # The wrong-binding edge is itself a false claim from a covered source.

    def test_bare_name_on_different_edge_does_not_inflate_recall(self, evaluator):
        # Same bare names src/dst, but DB binds the target to another file.
        truths = [evaluator.EdgeTruth(
            evaluator.CORPUS_REPO_ID, "pkg/a.py", "run_stage", "calls",
            "Stage.process", "pkg/a.py", 12, "python", "static_positive", "call")]
        db = [evaluator.DbEdge("pkg/a.py", "run_stage", "calls", "process", "pkg/other.py", 12)]
        report = evaluator.evaluate_edges(truths, db, [])
        assert report.counts["true_positives"] == 0
        # The legacy loose diagnostic MUST match it — that is exactly the
        # inflation the old metric produced and the oracle now exposes.
        assert report.diagnostics["legacy_loose_recall_diagnostic"] == 1.0
        assert report.diagnostics["identity_only_recall"] == 0.0

    def test_exact_edge_is_tp(self, evaluator):
        truths = [evaluator.EdgeTruth(
            evaluator.CORPUS_REPO_ID, "pkg/a.go", "caller", "calls",
            "Worker.Check", "pkg/b.go", 10, "go", "static_positive", "call")]
        db = [evaluator.DbEdge("pkg/a.go", "caller", "calls", "Worker.Check", "pkg/b.go", 10)]
        report = evaluator.evaluate_edges(truths, db, [])
        assert report.counts["true_positives"] == 1
        assert report.counts["false_positives"] == 0

    def test_span_mismatch_is_fn_with_reason(self, evaluator):
        truths = [evaluator.EdgeTruth(
            evaluator.CORPUS_REPO_ID, "pkg/a.go", "caller", "calls",
            "Worker.Check", "pkg/b.go", 10, "go", "static_positive", "call")]
        db = [evaluator.DbEdge("pkg/a.go", "caller", "calls", "Worker.Check", "pkg/b.go", 42)]
        report = evaluator.evaluate_edges(truths, db, [])
        assert report.counts["true_positives"] == 0
        assert any("span_mismatch" in c for c in report.confusion)

    def test_call_site_collapse_counts_each_truth(self, evaluator):
        truths = [
            evaluator.EdgeTruth(
                evaluator.CORPUS_REPO_ID, "pkg/a.ts", "callBoth", "calls",
                "fmt", "pkg/a.ts", 7, "typescript", "static_positive", "overload"),
            evaluator.EdgeTruth(
                evaluator.CORPUS_REPO_ID, "pkg/a.ts", "callBoth", "calls",
                "fmt", "pkg/a.ts", 7, "typescript", "static_positive", "overload"),
        ]
        db = [evaluator.DbEdge("pkg/a.ts", "callBoth", "calls", "fmt", "pkg/a.ts", 7)]
        report = evaluator.evaluate_edges(truths, db, [])
        assert report.counts["true_positives"] == 2

    def test_negative_edge_present_is_fp(self, evaluator):
        truths = [evaluator.EdgeTruth(
            evaluator.CORPUS_REPO_ID, "pkg/a.py", "shadower", "calls",
            "add", "pkg/b.py", None, "python", "static_negative", "shadowed_param")]
        db = [evaluator.DbEdge("pkg/a.py", "shadower", "calls", "add", "pkg/b.py", 3)]
        report = evaluator.evaluate_edges(truths, db, [])
        assert report.counts["false_positives"] == 1
        assert report.counts["true_negatives"] == 0

    def test_identity_unqualified_vs_wrong_target_distinction(self, evaluator):
        # DB stores the right symbol in the right file but under-qualified.
        truths = [evaluator.EdgeTruth(
            evaluator.CORPUS_REPO_ID, "pkg/a.rs", "run_stage", "calls",
            "Stage.process", "pkg/a.rs", 9, "rust", "static_positive", "call")]
        db = [evaluator.DbEdge("pkg/a.rs", "run_stage", "calls", "process", "pkg/a.rs", 9)]
        report = evaluator.evaluate_edges(truths, db, [])
        assert any("identity_unqualified" in c for c in report.confusion)
        # And the under-qualified edge is not double-punished as unexpected.
        assert not any("unexpected_edge" in c for c in report.confusion)

    def test_selfcheck_subcommand_passes(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "sot_evaluator.py"), "--selfcheck"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "self-check: OK" in result.stdout


class TestRealCorpusBaseline:
    """Integration: one full oracle run must emit the baseline contract."""

    @pytest.fixture(scope="class")
    def baseline(self, evaluator):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "builtin-baseline.json"
            payload = evaluator.run_benchmark_suite(str(out))
            assert out.exists()
            return payload, json.loads(out.read_text(encoding="utf-8"))

    def test_json_contract(self, baseline):
        payload, doc = baseline
        assert doc["oracle_version"] == payload["oracle_version"] == "2.0.0"
        corpus = doc["corpus"]
        assert corpus["repo"] == "oracle-corpus-v1"
        assert corpus["digest"] and len(corpus["digest"]) == 64
        assert set(corpus["languages"]) == {"python", "typescript", "go", "rust", "java"}
        assert corpus["counts"]["static_positive"] > 200
        assert corpus["counts"]["static_negative"] >= 50
        assert corpus["counts"]["dynamic_positive"] >= 20

        counts = doc["builtin"]["counts"]
        assert counts["true_positives"] + counts["false_negatives"] == counts["static_positive"]
        neg_fp = counts["false_positive_negative_matches"]
        assert neg_fp + counts["true_negatives"] == counts["static_negative"]
        assert counts["false_positives"] == (
            neg_fp + counts["false_positive_unexpected_edges"]
        )
        assert 0.0 <= counts["precision"] <= 1.0 and 0.0 <= counts["recall"] <= 1.0

    def test_per_language_breakdown(self, baseline):
        _payload, doc = baseline
        per_lang = doc["builtin"]["per_language"]
        assert set(per_lang) == {"python", "typescript", "go", "rust", "java"}
        for lang, rels in per_lang.items():
            assert "calls" in rels and "overall" in rels
            for rel, s in rels.items():
                assert s["tp"] + s["fn"] >= 0
                assert 0.0 <= s["precision"] <= 1.0
                assert 0.0 <= s["recall"] <= 1.0

    def test_confusion_entries_are_line_anchored(self, baseline):
        _payload, doc = baseline
        confusion = doc["builtin"]["confusion"]
        assert confusion, "real corpus is known defective; confusion must be non-empty"
        for entry in confusion:
            assert ANCHOR_RE.match(entry), f"not line-anchored: {entry}"

    def test_oracle_exposes_known_go_ts_defects(self, baseline):
        """The exact oracle must show the Go/TS recall defect the legacy
        loose metric hid: exact recall strictly below the loose diagnostic."""
        _payload, doc = baseline
        per_lang = doc["builtin"]["per_language"]
        loose = doc["builtin"]["diagnostics"]["legacy_loose_recall_diagnostic"]
        exact = doc["builtin"]["counts"]["recall"]
        assert exact <= loose, "exact recall can never exceed the loose fallback ladder"
        # Known defect class (roadmap R3.3): method-call identity in Go.
        assert per_lang["go"]["overall"]["recall"] < 0.9
        assert per_lang["go"]["overall"]["recall"] < loose

    def test_search_topk_section(self, baseline):
        _payload, doc = baseline
        s = doc["search_topk"]
        assert s["queries"] >= 15
        for k in ("hit_at_1", "hit_at_5", "hit_at_10"):
            assert 0.0 <= s[k] <= 1.0
        assert s["hit_at_1"] <= s["hit_at_5"] <= s["hit_at_10"]
        assert len(s["details"]) == s["queries"]
