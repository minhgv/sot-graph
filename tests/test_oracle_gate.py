"""SG-106: exact-oracle metric gate (--gate) and baseline path normalization.

The gate compares a fresh oracle payload against the committed baseline and
must fail on (a) any overall or per language×relation precision/recall drop
beyond a small absolute tolerance and (b) any previously-clean bucket that
now shows errors. All gate tests run on fabricated payloads — no full corpus
run — except one CLI smoke test.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_TMP = "/var/folders/47/ql/tmpABC123/oracle-corpus-v1"


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


def _slot(tp=10, fp=0, fn=0, tn=5, precision=1.0, recall=1.0):
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": 1.0}


def _payload(precision=1.0, recall=1.0, per_language=None):
    return {
        "oracle_version": "2.0.0",
        "corpus": {"repo": "oracle-corpus-v1", "digest": "a" * 64},
        "builtin": {
            "counts": {"precision": precision, "recall": recall},
            "per_language": per_language if per_language is not None else {
                "python": {"calls": _slot(), "overall": _slot()},
            },
            "confusion": [],
        },
        "search_topk": {"hit_at_1": 0.6, "details": []},
    }


class TestPathNormalization:
    def test_strip_temp_prefix_keeps_corpus_relative_path(self, evaluator):
        p = f"{LEGACY_TMP}/py_pkg/core/math_ops.py"
        assert evaluator.normalize_corpus_path(p) == "py_pkg/core/math_ops.py"

    def test_already_relative_and_unrelated_strings_unchanged(self, evaluator):
        assert evaluator.normalize_corpus_path("py_pkg/core/math_ops.py") == \
            "py_pkg/core/math_ops.py"
        assert evaluator.normalize_corpus_path("py_pkg.core.math_ops.compute_tax") == \
            "py_pkg.core.math_ops.compute_tax"
        assert evaluator.normalize_corpus_path("") == ""

    def test_payload_walker_is_recursive_and_idempotent(self, evaluator):
        payload = _payload()
        payload["search_topk"]["details"] = [
            {"query": "compute_tax",
             "top3": [{"fqn": "py_pkg.core.math_ops.compute_tax",
                       "path": f"{LEGACY_TMP}/py_pkg/core/math_ops.py",
                       "symbol": "compute_tax"}]},
        ]
        once = evaluator.normalize_payload_paths(payload)
        assert once["search_topk"]["details"][0]["top3"][0]["path"] == \
            "py_pkg/core/math_ops.py"
        assert evaluator.normalize_payload_paths(once) == once

    def test_legacy_absolute_baseline_loads_equal_to_normalized_fresh(
            self, evaluator, tmp_path):
        """A committed baseline with legacy absolute paths must normalize to
        exactly the fresh payload, so the gate compares equal."""
        fresh = _payload()
        fresh["search_topk"]["details"] = [
            {"query": "compute_tax",
             "top3": [{"fqn": "py_pkg.core.math_ops.compute_tax",
                       "path": "py_pkg/core/math_ops.py",
                       "symbol": "compute_tax"}]},
        ]
        legacy = copy.deepcopy(fresh)
        legacy["search_topk"]["details"][0]["top3"][0]["path"] = \
            f"{LEGACY_TMP}/py_pkg/core/math_ops.py"
        baseline_file = tmp_path / "legacy-baseline.json"
        baseline_file.write_text(json.dumps(legacy), encoding="utf-8")

        loaded = evaluator.load_baseline_doc(str(baseline_file))
        assert loaded == evaluator.normalize_payload_paths(fresh)
        passed, failures, _ = evaluator.evaluate_gate(loaded, fresh)
        assert passed, failures


class TestGateVerdicts:
    def test_gate_passes_when_fresh_equals_baseline(self, evaluator):
        baseline = _payload(precision=0.998, recall=0.9951)
        passed, failures, lines = evaluator.evaluate_gate(
            baseline, copy.deepcopy(baseline))
        assert passed, failures
        assert not failures
        assert any("overall" in ln and "PASS" in ln for ln in lines)

    def test_gate_fails_when_overall_recall_drops_beyond_budget(self, evaluator):
        baseline = _payload(precision=1.0, recall=0.9951)
        fresh = copy.deepcopy(baseline)
        fresh["builtin"]["counts"]["recall"] = 0.9800
        passed, failures, _ = evaluator.evaluate_gate(baseline, fresh)
        assert not passed
        assert any("overall recall" in f for f in failures)

    def test_gate_fails_when_overall_precision_drops_beyond_budget(self, evaluator):
        baseline = _payload(precision=0.998, recall=1.0)
        fresh = copy.deepcopy(baseline)
        fresh["builtin"]["counts"]["precision"] = 0.9500
        passed, failures, _ = evaluator.evaluate_gate(baseline, fresh)
        assert not passed
        assert any("overall precision" in f for f in failures)

    def test_gate_fails_when_bucket_recall_drops_beyond_budget(self, evaluator):
        baseline = _payload(per_language={
            "rust": {"calls": _slot(tp=65, fn=2, precision=1.0, recall=0.9847),
                     "overall": _slot()},
        })
        fresh = copy.deepcopy(baseline)
        fresh["builtin"]["per_language"]["rust"]["calls"] = _slot(
            tp=60, fn=7, precision=1.0, recall=0.8955)
        passed, failures, lines = evaluator.evaluate_gate(baseline, fresh)
        assert not passed
        assert any("rust/calls" in f and "recall" in f for f in failures)
        assert any("rust/calls" in ln and "FAIL" in ln for ln in lines)

    def test_gate_tolerates_sub_budget_drift(self, evaluator):
        # 0.003 drop < default 0.005 tolerance must stay green.
        baseline = _payload(per_language={
            "python": {"calls": _slot(tp=1000, fn=1, precision=0.999, recall=0.999),
                       "overall": _slot()},
        })
        fresh = copy.deepcopy(baseline)
        fresh["builtin"]["per_language"]["python"]["calls"]["recall"] = 0.996
        passed, failures, _ = evaluator.evaluate_gate(baseline, fresh)
        assert passed, failures

    def test_gate_fails_when_clean_bucket_gains_errors(self, evaluator):
        baseline = _payload(per_language={
            "go": {"calls": _slot(tp=30, fp=0, fn=0),
                   "overall": _slot(tp=30, fp=0, fn=0)},
        })
        fresh = copy.deepcopy(baseline)
        fresh["builtin"]["per_language"]["go"]["calls"] = _slot(tp=29, fp=1, fn=1)
        passed, failures, _ = evaluator.evaluate_gate(baseline, fresh)
        assert not passed
        assert any("previously clean" in f and "go/calls" in f for f in failures)

    def test_gate_fails_on_new_error_bucket_absent_from_baseline(self, evaluator):
        baseline = _payload()
        fresh = copy.deepcopy(baseline)
        fresh["builtin"]["per_language"]["java"] = {
            "implements": _slot(tp=5, fp=2, fn=1)}
        passed, failures, _ = evaluator.evaluate_gate(baseline, fresh)
        assert not passed
        assert any("new error bucket" in f and "java/implements" in f
                   for f in failures)

    def test_gate_passes_on_new_clean_bucket(self, evaluator):
        baseline = _payload()
        fresh = copy.deepcopy(baseline)
        fresh["builtin"]["per_language"]["java"] = {
            "implements": _slot(tp=5, fp=0, fn=0)}
        passed, failures, _ = evaluator.evaluate_gate(baseline, fresh)
        assert passed, failures

    def test_gate_fails_when_fresh_bucket_missing(self, evaluator):
        baseline = _payload(per_language={
            "rust": {"calls": _slot(), "overall": _slot()},
        })
        fresh = copy.deepcopy(baseline)
        del fresh["builtin"]["per_language"]["rust"]
        passed, failures, _ = evaluator.evaluate_gate(baseline, fresh)
        assert not passed
        assert any("rust/calls: bucket missing" in f for f in failures)

    def test_min_recall_override_tightens_overall_floor(self, evaluator):
        baseline = _payload(precision=1.0, recall=0.90)
        fresh = copy.deepcopy(baseline)
        fresh["builtin"]["counts"]["recall"] = 0.897  # within default budget
        ok_default, _, _ = evaluator.evaluate_gate(baseline, fresh)
        assert ok_default
        ok_tight, failures, _ = evaluator.evaluate_gate(
            baseline, fresh, min_recall=0.95)
        assert not ok_tight
        assert any("overall recall" in f for f in failures)

    def test_min_precision_override_accepts_clean_fresh(self, evaluator):
        baseline = _payload(precision=0.90, recall=1.0)
        fresh = copy.deepcopy(baseline)
        ok, _, _ = evaluator.evaluate_gate(baseline, fresh, min_precision=0.5)
        assert ok


class TestGateExitCodes:
    def test_run_gate_returns_zero_on_pass_and_one_on_fail(self, evaluator, capsys):
        baseline = _payload()
        assert evaluator.run_gate(baseline, copy.deepcopy(baseline)) == 0
        assert "gate verdict: PASS" in capsys.readouterr().out
        fresh = copy.deepcopy(baseline)
        fresh["builtin"]["counts"]["recall"] = 0.5
        assert evaluator.run_gate(baseline, fresh) == 1
        out = capsys.readouterr().out
        assert "gate verdict: FAIL" in out
        assert "overall recall" in out

    def test_cli_gate_smoke_exits_zero_against_committed_baseline(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "sot_evaluator.py"), "--gate"],
            capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "gate verdict: PASS" in result.stdout
