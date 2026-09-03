"""Tests for sot_graph.providers.scip (Federated SCIP Evidence Provider).
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from sot_graph.assurance.orchestrator import (
    cbm_candidates_from_outcome,
    federation_plan,
    run_federated_query,
)
from sot_graph.providers.base import CoverageRequest, SymbolRequest
from sot_graph.providers.scip import ScipProvider

def test_scip_provider_probe_missing(tmp_path: Path):
    provider = ScipProvider()
    status = provider.probe(str(tmp_path))
    assert not status.installed
    assert not status.healthy
    assert "no SCIP index" in status.detail


def test_scip_provider_probe_present(tmp_path: Path):
    scip_file = tmp_path / "index.scip.json"
    doc = {
        "metadata": {"version": "0.4.0"},
        "documents": [
            {
                "relative_path": "src/main.py",
                "symbols": [{"symbol": "scip-python python main 0.1.0 `src/main.py`/main()."}],
                "occurrences": [],
            }
        ],
    }
    scip_file.write_text(json.dumps(doc), encoding="utf-8")

    provider = ScipProvider(index_path="index.scip.json")
    status = provider.probe(str(tmp_path))
    assert status.installed
    assert status.healthy
    assert "SCIP index loaded (1 documents)" in status.detail


def test_scip_provider_search_and_usages(tmp_path: Path):
    scip_file = tmp_path / "index.scip"
    doc = {
        "metadata": {"version": "0.4.0"},
        "documents": [
            {
                "relative_path": "src/user_service.py",
                "symbols": [
                    {
                        "symbol": "scip-python python user_service 0.1.0 `src/user_service.py`/UserService#",
                        "kind": "class",
                        "documentation": ["User service class documentation"],
                    }
                ],
                "occurrences": [
                    {
                        "range": [10, 0, 10, 20],
                        "symbol": "scip-python python user_service 0.1.0 `src/user_service.py`/UserService#",
                        "symbol_roles": 1,  # Definition
                    },
                    {
                        "range": [25, 4, 25, 15],
                        "symbol": "scip-python python user_service 0.1.0 `src/user_service.py`/UserService#",
                        "symbol_roles": 0,  # Reference
                    },
                ],
            }
        ],
    }
    scip_file.write_text(json.dumps(doc), encoding="utf-8")

    provider = ScipProvider()
    # 1. Search symbols
    res_search = provider.search_symbols(SymbolRequest(repo_root=str(tmp_path), query="UserService"))
    assert res_search.ok
    assert isinstance(res_search.payload, dict)
    assert len(res_search.payload["symbols"]) >= 1
    assert any("UserService" in sym["symbol"] for sym in res_search.payload["symbols"])

    # 2. Usages
    res_usages = provider.usages(SymbolRequest(repo_root=str(tmp_path), query="UserService"))
    assert res_usages.ok
    assert isinstance(res_usages.payload, dict)
    assert len(res_usages.payload["symbols"]) >= 2
    assert any(sym["is_definition"] for sym in res_usages.payload["symbols"])
    assert any(not sym["is_definition"] for sym in res_usages.payload["symbols"])

    # 3. Coverage
    res_cov = provider.coverage(CoverageRequest(repo_root=str(tmp_path), paths=("src/user_service.py",)))
    assert res_cov.ok
    assert isinstance(res_cov.payload, dict)
    assert "src/user_service.py" in res_cov.payload["covered_paths"]


def test_scip_orchestrator_federation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    scip_path = tmp_path / "index.scip.json"
    scip_path.write_text(json.dumps({"metadata": {"version": "0.4.0"}, "documents": [{"relative_path": "a.py", "symbols": [{"symbol": "sym"}], "occurrences": []}]}), encoding="utf-8")

    monkeypatch.setenv("SOT_PROVIDERS_ALLOW_EXTERNAL", "1")

    plan = federation_plan("require:scip", str(tmp_path), "usages")
    assert plan["fail_message"] is None
    assert plan["provider"] is not None
    assert plan["provider"].name == "scip"

    # Diff-impact requires "impact" capability which SCIP does not advertise
    plan_impact = federation_plan("require:scip", str(tmp_path), "diff-impact")
    assert plan_impact["fail_message"] is not None
    assert "does not support required capability 'impact'" in plan_impact["fail_message"]

def test_scip_usages_routing_candidates_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    scip_file = tmp_path / "index.scip.json"
    doc = {
        "metadata": {"version": "0.4.0"},
        "documents": [
            {
                "relative_path": "src/user_service.py",
                "symbols": [
                    {
                        "symbol": "scip-python python user_service 0.1.0 `src/user_service.py`/UserService#",
                        "documentation": ["User service implementation"],
                    }
                ],
                "occurrences": [
                    {
                        "symbol": "scip-python python user_service 0.1.0 `src/user_service.py`/UserService#",
                        "range": [10, 6, 10, 17],
                        "symbol_roles": 1,
                    },
                    {
                        "symbol": "scip-python python user_service 0.1.0 `src/user_service.py`/UserService#",
                        "range": [25, 12, 25, 23],
                        "symbol_roles": 0,
                    },
                ],
            }
        ],
    }
    scip_file.write_text(json.dumps(doc), encoding="utf-8")

    monkeypatch.setenv("SOT_PROVIDERS_ALLOW_EXTERNAL", "1")
    plan = federation_plan("require:scip", str(tmp_path), "usages")
    outcome, method = run_federated_query(plan, str(tmp_path), "usages", "UserService")
    assert method == "usages"
    assert outcome is not None
    assert outcome.ok is True
    assert "symbols" in outcome.payload
    candidates, truncated, gap = cbm_candidates_from_outcome(outcome, method, "scip", str(tmp_path))
    assert len(candidates) >= 2
    assert any(c["relation"] == "DEFINES" and c.get("provider_relation") == "define" for c in candidates)
    assert any(c["relation"] == "CALLS" and c.get("provider_relation") == "references" for c in candidates)
def test_require_mode_rejects_symbols_only_provider_for_usages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SOT_PROVIDERS_ALLOW_EXTERNAL", "1")

    class SymbolsOnlyProvider:
        name = "dummy-symbols"
        capabilities = ["symbols"]
        def search_symbols(self, req):
            from sot_graph.providers.base import ProviderOutcome
            return ProviderOutcome(ok=True, payload={"symbols": []}, provider_name="dummy-symbols")

    # Federation plan with required provider lacking usages must fail
    from sot_graph.assurance.routing import supports_capability

    provider = SymbolsOnlyProvider()
    assert not supports_capability(provider, "usages")
    assert not supports_capability(provider, "references")
    assert supports_capability(provider, "symbols")

    plan = {
        "mode": "require",
        "target": "dummy-symbols",
        "provider": provider,
        "candidates": [{"provider": "dummy-symbols", "capabilities": ["symbols"]}],
        "warnings": [],
    }
    outcome, method = run_federated_query(plan, str(tmp_path), "usages", "UserService")
    assert outcome is None
    assert method is None
