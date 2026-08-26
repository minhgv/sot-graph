"""sot_graph.providers.lifecycle — provider lifecycle manifest (P9.3).

Roadmap §8.1: every evidence provider declares a lifecycle manifest —
probe, health, capability, contract/wire versions, upgrade and rollback
policy — derived live from the registry (never hand-maintained), so the
operator and CI can decide, before trusting a provider, whether it is
the version this adapter was built against and what to do when it is
not.

Read-only by construction: reuses :mod:`providers_registry` probes.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sot_graph.providers_registry import detect_providers

__all__ = ["lifecycle_manifest", "UPDATE_PROCESS"]

#: Roadmap §8.2 — the 8-step provider update process. Documentation
#: constant: mirrored in docs/PROVIDER_LIFECYCLE.md; CI can assert the
#: steps unchanged via this value.
UPDATE_PROCESS: List[Dict[str, Any]] = [
    {"step": 1, "action": "freeze evidence",
     "detail": "stop trusting federated verdicts: set provider_policy "
               "builtin_only for new queries; ledger keeps existing rows"},
    {"step": 2, "action": "record pre-state",
     "detail": "sot providers detect --format json > pre.json (versions, "
               "health, contract version)"},
    {"step": 3, "action": "upgrade the provider binary",
     "detail": "install the new version out of band; nothing in sot-graph "
               "auto-updates providers"},
    {"step": 4, "action": "re-probe",
     "detail": "sot providers detect: confirm installed+healthy and note "
               "the new version"},
    {"step": 5, "action": "contract check",
     "detail": "adapter compares provider version against the "
               "contract_version it was built for; mismatch → abstain "
               "(never guess the wire)"},
    {"step": 6, "action": "shadow one query",
     "detail": "run one federated query via CLI; inspect schema_drift / "
               "abstain outcomes before widening"},
    {"step": 7, "action": "re-index explicitly",
     "detail": "sot providers sync --provider <name> under the write "
               "lock; ledger records the new run + snapshot binding"},
    {"step": 8, "action": "restore policy + audit ledger",
     "detail": "re-enable the provider policy; receipt_from_ledger to "
               "audit runs/evidence and resolve conflicts"},
]

#: Rollback = steps 3-7 with the OLD version; the ledger is append-only
#: so pre-upgrade evidence stays queryable (P6 invariant).
ROLLBACK_NOTE = (
    "rollback: reinstall the previous version and repeat steps 4-7; "
    "ledger history is append-only, so pre-upgrade evidence rows remain "
    "auditable (purge_provider_run is the only removal path)"
)


def lifecycle_manifest(repo_root: str) -> Dict[str, Any]:
    """Live lifecycle manifest for every configured provider."""
    from sot_graph.providers.contract import PROVIDER_CONTRACT_VERSION

    statuses = detect_providers(repo_root)
    providers: List[Dict[str, Any]] = []
    for st in statuses:
        providers.append({
            "name": st.name,
            "mode": st.mode,
            "installed": st.installed,
            "healthy": st.healthy,
            "version": st.version,
            "capabilities": st.capabilities,
            "probe_engine": st.probe_engine,
            "detail": st.detail,
            "adapter_contract_version": PROVIDER_CONTRACT_VERSION,
            "wire_compatible": (
                st.name != "codebase-memory"
                or (st.version or "").startswith("0.10.")
            ),
            "upgrade": (
                "follow docs/PROVIDER_LIFECYCLE.md §8.2 8-step process"
            ),
            "rollback": ROLLBACK_NOTE,
        })
    return {
        "schema_version": 1,
        "generated_by": f"codebase-memory adapter contract v{PROVIDER_CONTRACT_VERSION}",
        "builtin_scorecard_source": "providers_registry.BUILTIN_LANGUAGE_SCORECARD",
        "providers": providers,
        "update_process": UPDATE_PROCESS,
    }
