"""test_provider_identity_oracle.py — SG-203 identity join oracle guard.

Runs the real benchmark (scripts/bench_provider_identity.py) in-process
against the git-tracked fixture corpus and asserts the measured gates:
exact joins (no invented pairs, no missed both-claimed pairs), span
conflict adjudication against the live file, zero accidental joins from
the node-ID collision probe, and honest builtin-gap surfacing.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "bench_provider_identity.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "bench_provider_identity", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_selfcheck_planted_truth_is_consistent():
    mod = _load()
    assert mod.selfcheck() == []


def test_oracle_measured_gates(tmp_path):
    mod = _load()
    artifact_path = tmp_path / "provider-identity.json"
    rc = mod.main([str("--json"), str(artifact_path), "--gate"])
    assert rc == 0, "benchmark gate failed — see artifact for details"

    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["benchmark"] == "provider-identity-oracle"
    assert artifact["gates"]["passed"] is True

    m = artifact["metrics"]
    # Exact joins: no invented pairs, no missed both-claimed pairs.
    assert m["join_precision"] == 1.0
    assert m["join_recall"] == 1.0
    assert m["accidental_joins"] == 0
    assert artifact["observed"]["false_joins"] == []
    assert artifact["observed"]["missed_calls"] == []
    assert artifact["observed"]["missed_definitions"] == []

    # The span probe must surface AND adjudicate against the live file.
    assert m["span_conflict_detected"] >= 1
    assert m["span_conflict_adjudicated_builtin"] >= 1

    # The attribute-call builtin parser gap is REPORTED, not hidden.
    assert m["builtin_gap_calls_surfaced"] >= 1
    assert any(
        "app.main.build_invoice -> core.service.format_label" in gap
        for gap in artifact["observed"]["builtin_gap_calls"]
    )


def test_committed_artifact_is_current():
    """The checked-in artifact must match a fresh measured run."""
    mod = _load()
    committed = _REPO / "benchmarks" / "provider-identity.json"
    if not committed.exists():
        return  # not committed yet — the measured-run test above covers it
    fresh_path = committed.with_suffix(".fresh")
    fresh = mod.run_benchmark(fresh_path)
    try:
        old = json.loads(committed.read_text(encoding="utf-8"))
        # Volatile fields excluded: environment + observed.totals carry
        # platform/paths; the MEASURED claims must be identical.
        assert old["metrics"] == fresh["metrics"], (
            "benchmarks/provider-identity.json is stale — re-run "
            "scripts/bench_provider_identity.py")
        assert old["gates"]["checks"] == fresh["gates"]["checks"]
        assert old["corpus"]["truth_definitions"] == \
            fresh["corpus"]["truth_definitions"]
    finally:
        fresh_path.unlink(missing_ok=True)
