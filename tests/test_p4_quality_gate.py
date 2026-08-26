"""P4.5 — release-floor quality gate (measured, not asserted by vibes).

Reads the committed oracle baseline (benchmarks/oracle/builtin-
baseline.json) and enforces the P4 floor PER TIER-A LANGUAGE:

- top-k recall: hit@10 >= 0.90 (and unique-query hit@5 >= 0.90)
- confirmed direct-call precision: calls precision >= 0.95
- project-local recall: overall recall >= 0.80

Release floor, not a global claim: the oracle corpus is adversarial by
construction (same-name scopes, cross-file modules, aliases), and the
gate fails whenever a change regresses any measured cell. The
"provider union never reduces verified precision" floor lands with the
P6 evidence ledger; it is recorded here as a pending gate, not claimed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "benchmarks" / "oracle" / "builtin-baseline.json"

TIER_A = ("python", "java", "typescript", "go", "rust")


def _baseline() -> dict:
    with BASELINE.open(encoding="utf-8") as fh:
        return json.load(fh)


class TestReleaseFloor:
    def test_topk_recall_floor(self):
        s = _baseline()["search_topk"]
        assert s["hit_at_10"] >= 0.90, f"top-k recall regressed: {s}"
        assert s["unique_hit_at_5"] >= 0.90, f"unique hit@5 regressed: {s}"
        # monotonicity of the hit ladder is part of the contract
        assert s["hit_at_1"] <= s["hit_at_5"] <= s["hit_at_10"]

    def test_direct_call_precision_floor_per_tier_a_language(self):
        per_lang = _baseline()["builtin"]["per_language"]
        for lang in TIER_A:
            calls = per_lang[lang].get("calls")
            assert calls is not None, f"{lang} has no measured calls cell"
            assert calls["precision"] >= 0.95, (
                f"{lang} direct-call precision {calls['precision']} < 0.95"
            )

    def test_project_local_recall_floor_per_tier_a_language(self):
        per_lang = _baseline()["builtin"]["per_language"]
        for lang in TIER_A:
            overall = per_lang[lang]["overall"]
            assert overall["recall"] >= 0.80, (
                f"{lang} overall recall {overall['recall']} < 0.80"
            )

    def test_gate_is_measured_not_missing(self):
        doc = _baseline()
        # A missing section must fail the gate loudly, never pass vacuously.
        assert doc["search_topk"]["queries"] >= 15
        counts = doc["builtin"]["counts"]
        assert counts["true_positives"] + counts["false_negatives"] >= 1000
