"""Tests for sot_graph.providers.scip (Federated SCIP Evidence Provider).
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from sot_graph.assurance.orchestrator import federation_plan
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
    scip_path = tmp_path / "index.scip"
    scip_path.write_bytes(b"")

    monkeypatch.setenv("SOT_PROVIDERS_ALLOW_EXTERNAL", "1")

    plan = federation_plan("require:scip", str(tmp_path), "usages")
    assert plan["fail_message"] is None
    assert plan["provider"] is not None
    assert plan["provider"].name == "scip"
