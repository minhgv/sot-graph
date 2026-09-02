"""sot_graph.providers.base — EvidenceProvider protocol and request vocabulary.

Contract notes:
- Every adapter method is *bounded*: it never raises on provider failure; it
  returns an outcome carrying the failure as data (mirrors ``sot_graph.proc``).
- Capability negotiation happens BEFORE invocation: a caller checks
  :func:`supports_method` so optional methods may be absent on a provider
  without breaking the protocol (guide §6, "Không ép mọi provider hỗ trợ
  mọi method").
- Unknown values are ``None`` or ``"unknown"`` — never fabricated defaults.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "IndexRequest",
    "SymbolRequest",
    "TraceRequest",
    "ImpactRequest",
    "ArchitectureRequest",
    "CoverageRequest",
    "ProviderStatus",
    "ProviderRunRecord",
    "QueryOutcome",
    "EvidenceProvider",
    "supports_method",
]

#: Maps an EvidenceProvider method to the capability string a provider must
#: advertise for that method to be invocable. ``None`` means every provider
#: may be asked (the adapter itself decides to abstain).
METHOD_CAPABILITIES: dict[str, str | None] = {
    "probe": None,
    "ensure_index": None,
    "search_symbols": "symbols",
    "usages": "usages",
    "trace": "trace",
    "impact": "impact",
    "architecture": "architecture",
    "coverage": None,
}


@dataclass(frozen=True)
class IndexRequest:
    """Ask a provider to make sure its index covers ``repo_root``."""

    repo_root: str
    force: bool = False
    timeout_seconds: float | None = None  # None -> adapter default


@dataclass(frozen=True)
class SymbolRequest:
    """Search symbols by free-text query."""

    repo_root: str
    query: str
    limit: int = 20
    language: str | None = None
    project: str | None = None  # explicit provider-side project name override
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class TraceRequest:
    """Trace call paths around one symbol."""

    repo_root: str
    symbol: str
    direction: str = "both"  # callers | callees | both
    max_depth: int = 5
    project: str | None = None  # explicit provider-side project name override
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class ImpactRequest:
    """Estimate blast radius of a change set (P3.1: git-ref scoped).

    ``since`` is the git ref CBM compares from (e.g. ``HEAD~1``); the wire
    tool diffs ``since...HEAD``. Staged/working-tree scopes are NOT
    representable on that wire and must surface as a scope conflict, never
    silently merged.
    """

    repo_root: str
    path: str
    since: str | None = None
    depth: int = 2
    staged: bool = False
    working_tree: bool = False
    project: str | None = None  # explicit provider-side project name override
    timeout_seconds: float | None = None

@dataclass(frozen=True)
class ArchitectureRequest:
    """Fetch coarse module/architecture structure of the repository."""

    repo_root: str
    project: str | None = None  # explicit provider-side project name override
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class CoverageRequest:
    """Check index coverage for explicit paths (empty tuple = whole repo)."""

    repo_root: str
    paths: tuple[str, ...] = ()
    project: str | None = None  # explicit provider-side project name
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class ProviderStatus:
    """Outcome of probing one provider executable (adapter-level view)."""

    name: str
    installed: bool
    healthy: bool
    version: str | None
    detail: str
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderRunRecord:
    """One provider invocation, ready for the ``provider_runs`` ledger.

    ``arguments_redacted`` is safe to persist: sensitive flag values are
    replaced with ``***REDACTED***`` by the adapter before this record exists.
    """

    run_id: str
    provider_name: str
    provider_version: str | None
    capability: str
    status: str  # ok | error | timeout | spawn_failed | truncated | abstained | ...
    exit_code: int | None
    duration_ms: int
    arguments_redacted: tuple[str, ...] = ()
    next_action: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class QueryOutcome:
    """Honest result of one evidence query.

    Either ``payload`` holds the extracted JSON payload from the provider, or
    the outcome is an abstention: ``ok=False`` plus ``error`` and, when the
    provider could not serve because its index is missing/stale, a
    ``next_action`` telling the operator how to fix it. Adapters NEVER return
    fabricated evidence.
    """

    ok: bool
    run: ProviderRunRecord
    payload: Any = None
    error: str | None = None
    next_action: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EvidenceProvider(Protocol):
    """Protocol every federated evidence provider implements.

    Methods MAY be unimplemented: negotiate via :func:`supports_method`
    (backed by ``capabilities`` advertised by the concrete provider) before
    invoking. Implementations must never raise for provider-side failures.
    """

    capabilities: tuple[str, ...]

    def probe(self, repo_root: str) -> ProviderStatus: ...

    def ensure_index(self, request: IndexRequest) -> ProviderRunRecord: ...

    def search_symbols(self, request: SymbolRequest) -> QueryOutcome: ...

    def trace(self, request: TraceRequest) -> QueryOutcome: ...

    def impact(self, request: ImpactRequest) -> QueryOutcome: ...

    def architecture(self, request: ArchitectureRequest) -> QueryOutcome: ...

    def coverage(self, request: CoverageRequest) -> QueryOutcome: ...


def supports_method(provider: Any, method: str) -> bool:
    """Capability negotiation: may ``method`` be invoked on ``provider``?

    Returns False when the provider does not advertise the capability required
    by ``method``, or when the attribute/method itself is absent. Callers use
    this to fall back honestly instead of crashing on partial adapters.
    """
    required = METHOD_CAPABILITIES.get(method)
    if not callable(getattr(provider, method, None)):
        return False
    if required is None:
        return True
    return required in tuple(getattr(provider, "capabilities", ()) or ())
