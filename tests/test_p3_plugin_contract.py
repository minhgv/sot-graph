"""P3.4 — versioned plugin contract for evidence providers.

Contract rules under test:
- Adapters declare ``contract_version``; the loader gate rejects version
  mismatches fail-closed instead of shimming.
- A new adapter must pass the golden-capture contract checks: drifted
  wire payloads fail CLOSED, read paths never auto-install, and every
  method is bounded (failures as data, never exceptions).
- Entry-point discovery is read-only: no install, no query; one broken
  plugin degrades to an unhealthy status without breaking detection.
- The orchestrator core is untouched by plugins (no plugin imports).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sot_graph.providers.base import (  # noqa: E402
    ArchitectureRequest,
    CoverageRequest,
    IndexRequest,
    ProviderRunRecord,
    ProviderStatus,
    SymbolRequest,
    TraceRequest,
    QueryOutcome,
)
from sot_graph.providers.codebase_memory import CodebaseMemoryProvider  # noqa: E402
from sot_graph.providers.contract import (  # noqa: E402
    PROVIDER_CONTRACT_VERSION,
    ProviderContractError,
    run_contract_checks,
    static_contract_problems,
    validate_entry_point_provider,
)
from tests.test_cbm_adapter import make_exe  # noqa: E402

DRIFTED = "total: 1\nhas_more: false\n"  # text report, not JSON


def _stub_run(name="good-plugin"):
    return ProviderRunRecord(
        run_id="r", provider_name=name, provider_version="1",
        capability="query", status="abstained", exit_code=None, duration_ms=0,
    )


def _drift_binary(tmp_path: Path) -> str:
    """Answers list_projects with valid JSON; search_graph with a text
    report (the golden drift capture for format=json queries)."""
    body = (
        "import json, os, sys\n"
        "argv = sys.argv[1:]\n"
        "tool = argv[argv.index('--json') + 1]\n"
        "if tool == 'list_projects':\n"
        "    payload = {'projects': [{'name': 'p', 'root_path': os.getcwd()}],"
        " 'total': 1, 'has_more': False}\n"
        "    text = json.dumps(payload)\n"
        "else:\n"
        f"    text = {DRIFTED!r}\n"
        "env = {'content': [{'type': 'text', 'text': text}],"
        " 'isError': False, 'structuredContent': {}}\n"
        "print(json.dumps(env))\n"
    )
    return make_exe(tmp_path, "cbm-contract", body)


class TestReferenceAdapterPasses:
    def test_codebase_memory_passes_golden_contract(self, tmp_path):
        exe = _drift_binary(tmp_path)
        problems = run_contract_checks(
            lambda payload: CodebaseMemoryProvider(command=[exe]),
            drifted_search_payload=DRIFTED,
            repo_root=str(tmp_path),
        )
        assert problems == []

    def test_cbm_declares_current_contract_version(self):
        assert CodebaseMemoryProvider.contract_version == PROVIDER_CONTRACT_VERSION
        assert CodebaseMemoryProvider.name == "codebase-memory"


class _GoodPlugin:
    contract_version = PROVIDER_CONTRACT_VERSION
    name = "good-plugin"
    capabilities = ("symbols",)

    def probe(self, repo_root: str) -> ProviderStatus:
        return ProviderStatus(name=self.name, installed=True, healthy=True,
                              version="1", detail="ok", capabilities=self.capabilities)

    def ensure_index(self, request: IndexRequest) -> ProviderRunRecord:
        return ProviderRunRecord(run_id="r", provider_name=self.name,
                                 provider_version="1", capability="index_repository",
                                 status="abstained", exit_code=None, duration_ms=0)

    def search_symbols(self, request: SymbolRequest) -> QueryOutcome:
        return QueryOutcome(ok=False, run=_stub_run(), error="no wire")

    def trace(self, request: TraceRequest) -> QueryOutcome:
        return QueryOutcome(ok=False, run=_stub_run(), error="no wire")

    def impact(self, request) -> QueryOutcome:
        return QueryOutcome(ok=False, run=_stub_run(), error="no wire")

    def architecture(self, request: ArchitectureRequest) -> QueryOutcome:
        return QueryOutcome(ok=False, run=_stub_run(), error="no wire")

    def coverage(self, request: CoverageRequest) -> QueryOutcome:
        return QueryOutcome(ok=False, run=_stub_run(), error="no wire")


class _VersionMismatchPlugin(_GoodPlugin):
    contract_version = 0


class _SilentMethodPlugin(_GoodPlugin):
    # advertises 'symbols' but search_symbols is not callable
    search_symbols = None


class TestContractGate:
    def test_good_plugin_passes_static_gate(self):
        assert static_contract_problems(_GoodPlugin()) == []
        assert validate_entry_point_provider(_GoodPlugin) is _GoodPlugin

    def test_version_mismatch_rejected_fail_closed(self):
        problems = static_contract_problems(_VersionMismatchPlugin())
        assert any("contract_version mismatch" in p for p in problems)
        with pytest.raises(ProviderContractError) as err:
            validate_entry_point_provider(_VersionMismatchPlugin)
        assert "contract_version mismatch" in str(err.value)

    def test_missing_advertised_method_rejected(self):
        problems = static_contract_problems(_SilentMethodPlugin())
        assert any("search_symbols" in p for p in problems)


class TestReadPathNeverInstalls:
    def test_entry_point_discovery_is_read_only(self, monkeypatch):
        from sot_graph import providers_registry as reg

        def boom(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("discovery must not spawn processes")

        monkeypatch.setattr(reg, "run_command", boom)
        statuses = reg.discover_plugin_providers()
        assert isinstance(statuses, list)  # no plugins installed -> empty, no crash

    def test_broken_plugin_degrades_to_unhealthy_status(self, monkeypatch):
        import importlib.metadata
        from sot_graph import providers_registry as reg

        class _FakeEP:
            name = "broken-plugin"

            def load(self):
                raise ImportError("boom")

        monkeypatch.setattr(
            importlib.metadata, "entry_points", lambda group=None: [_FakeEP()],
        )

        class _FakeEP:
            name = "broken-plugin"

            def load(self):
                raise ImportError("boom")

        statuses = reg.discover_plugin_providers()
        assert len(statuses) == 1
        assert statuses[0].name == "broken-plugin"
        assert statuses[0].healthy is False
        assert "load failed" in statuses[0].detail

    def test_orchestrator_core_has_no_plugin_imports(self):
        import sot_graph.assurance.orchestrator as orch

        source = Path(orch.__file__).read_text(encoding="utf-8")
        assert "providers.contract" not in source
        assert "entry_points" not in source
        assert "discover_plugin" not in source
