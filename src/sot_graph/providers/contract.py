"""sot_graph.providers.contract — versioned plugin contract (P3.4).

A federated evidence provider joins sot-graph through a VERSIONED
contract instead of orchestrator changes:

1. The adapter class declares ``contract_version`` (must equal
   :data:`PROVIDER_CONTRACT_VERSION`).
2. It implements the :class:`~sot_graph.providers.base.EvidenceProvider`
   protocol — capability-negotiated, bounded methods.
3. It passes the golden-capture contract checks
   (:func:`run_contract_checks`): schema drift fails CLOSED (never a
   lenient text parse), read paths never spawn index/install work, and
   no method raises on provider-side failure.

The entry-point loader (:func:`validate_entry_point_provider`) enforces
the same rules for adapters discovered via the ``sot_graph.providers``
entry-point group. Loading never installs anything and never issues a
query — installation is the explicit ``sot providers sync`` path only.
"""

from __future__ import annotations

from typing import Any, Callable, List

from .base import (
    ArchitectureRequest,
    CoverageRequest,
    IndexRequest,
    SymbolRequest,
)

#: Version of the provider plugin contract. Bump on any breaking change
#: to the EvidenceProvider protocol, request dataclasses, or the
#: fail-closed semantics checked below. Adapters declare the version they
#: were built against; mismatches are rejected, not shimmed.
PROVIDER_CONTRACT_VERSION = 1

#: Entry-point group scanned for third-party evidence providers.
ENTRY_POINT_GROUP = "sot_graph.providers"


class ProviderContractError(Exception):
    """A provider does not satisfy the versioned plugin contract."""

    def __init__(self, provider_name: str, problems: List[str]):
        self.provider_name = provider_name
        self.problems = problems
        super().__init__(
            f"provider '{provider_name}' violates contract v{PROVIDER_CONTRACT_VERSION}: "
            + "; ".join(problems)
        )


def static_contract_problems(provider: Any) -> List[str]:
    """Cheap, spawn-free contract checks usable at load time."""
    problems: List[str] = []
    declared = getattr(provider, "contract_version", None)
    if declared != PROVIDER_CONTRACT_VERSION:
        problems.append(
            f"contract_version mismatch: declared {declared!r}, "
            f"required {PROVIDER_CONTRACT_VERSION!r}"
        )
    caps = getattr(provider, "capabilities", None)
    if not isinstance(caps, (tuple, list)):
        problems.append("capabilities must be a tuple/list of capability strings")
    elif not all(isinstance(c, str) for c in caps):
        problems.append("capabilities entries must be strings")
    for method in ("probe", "ensure_index"):
        if not callable(getattr(provider, method, None)):
            problems.append(f"required method missing: {method}")
    for method, cap in (("search_symbols", "symbols"), ("trace", "trace"),
                        ("impact", "impact"), ("architecture", "architecture")):
        # Advertise-without-method is a contract violation; a callable
        # method without the capability is fine (negotiation decides at
        # call time — adapters may implement more than they advertise).
        if cap in tuple(caps or ()) and not callable(getattr(provider, method, None)):
            problems.append(f"advertises {cap!r} but {method} is not callable")
    return problems


def run_contract_checks(
    build_provider: Callable[[str], Any],
    *,
    drifted_search_payload: str,
    repo_root: str,
    query: str = "anything",
) -> List[str]:
    """Golden-capture contract checks (G1 pattern) for one adapter.

    ``build_provider`` returns a fresh provider instance whose wire is
    captured to reply ``drifted_search_payload`` (raw text — NOT valid
    JSON) to a ``format=json`` search query. A compliant adapter fails
    closed on that capture: ``ok=False`` with ``wire_status
    schema_drift`` in metadata, never a lenient text parse.

    Returns a list of contract problems; empty means the adapter passes.
    """
    problems: List[str] = []
    provider = build_provider(drifted_search_payload)
    problems.extend(f"static: {p}" for p in static_contract_problems(provider))

    # 1. Schema drift fails closed (golden capture of a text-report reply).
    if callable(getattr(provider, "search_symbols", None)):
        outcome = provider.search_symbols(
            SymbolRequest(repo_root=repo_root, query=query)
        )
        if outcome is None or outcome.ok:
            problems.append(
                "drifted search payload must fail closed (ok=False), "
                "not parse leniently"
            )
        elif outcome.metadata.get("wire_status") != "schema_drift":
            problems.append(
                "drifted search payload must set metadata.wire_status='schema_drift'"
            )

    # 2. Read paths never auto-install: ensure_index must abstain, never
    #    spawn an index build during a query-context contract run.
    record = provider.ensure_index(IndexRequest(repo_root=repo_root))
    if record is None:
        problems.append("ensure_index must return a ProviderRunRecord")
    elif record.status not in ("abstained", "ok"):
        problems.append(
            f"ensure_index in read context must abstain or no-op, got {record.status!r}"
        )

    # 3. Bounded methods: provider-side failures surface as data, never
    #    as exceptions (protocol contract from sot_graph.providers.base).
    for label, call in (
        ("trace", lambda: provider.trace(_trace_request(repo_root))),
        ("impact", lambda: provider.impact(_impact_request(repo_root))),
        ("architecture", lambda: provider.architecture(
            ArchitectureRequest(repo_root=repo_root)
        )),
        ("coverage", lambda: provider.coverage(CoverageRequest(repo_root=repo_root))),
        ("probe", lambda: provider.probe(repo_root)),
    ):
        method = label
        if not callable(getattr(provider, method, None)):
            continue
        try:
            result = call()
        except Exception as exc:  # noqa: BLE001 - contract violation, reported
            problems.append(f"{method} raised {type(exc).__name__} (must be bounded)")
            continue
        if result is None:
            problems.append(f"{method} returned None (must return outcome/record)")

    if problems:
        name = getattr(provider, "name", type(provider).__name__)
        raise ProviderContractError(str(name), problems)
    return problems


def validate_entry_point_provider(cls: type) -> Any:
    """Validate one entry-point provider class; raise on violation.

    Loader-side gate: static checks only (no spawn, no query, no install).
    The golden-capture checks run in the provider's own contract tests —
    a new adapter must ship those (pattern G1) before registration.
    """
    problems = static_contract_problems(cls)
    if problems:
        raise ProviderContractError(getattr(cls, "name", cls.__name__), problems)
    return cls


def _trace_request(repo_root: str):
    from .base import TraceRequest

    return TraceRequest(repo_root=repo_root, symbol="anything")


def _impact_request(repo_root: str):
    from .base import ImpactRequest

    return ImpactRequest(repo_root=repo_root, path=repo_root)


__all__ = [
    "PROVIDER_CONTRACT_VERSION",
    "ENTRY_POINT_GROUP",
    "ProviderContractError",
    "static_contract_problems",
    "run_contract_checks",
    "validate_entry_point_provider",
]
