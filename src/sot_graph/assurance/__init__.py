"""sot_graph.assurance — the shared query-assurance engine (P2).

One engine behind both surfaces:

- :mod:`.engine` — symbol resolution + pre-query assurance (snapshot
  descriptor, stale-journal detection, ledger invalidation marking).
- :mod:`.routing` — provider spec parsing + capability routing tables.
- :mod:`.orchestrator` — federated provider negotiation, typed outcomes,
  structured (JSON) wire parsing, candidate normalization, target-conflict
  adjudication.

CLI handlers and McpService import from here; no orchestration logic lives
in presentation layers. :mod:`.identity` (P4) holds the canonical symbol
identity tuple; normalization/coverage/verification modules currently
live in :mod:`sot_graph.providers` and move into this package in their
owning phases (P5-P7).
"""

from .coverage import (
    GAP_TAXONOMY,
    CoverageReport,
    CoverageState,
    coverage_note,
    completeness,
    repo_coverage,
)
from .identity import (
    Span,
    SymbolIdentity,
    dedup_by_identity,
    from_graph_row,
    from_provider_symbol,
    from_subject,
    identity_hash,
    identity_key,
)
from .engine import assured_query_context, resolve_symbol, stale_files_warning
from .ledger import ledger_rows_for_runs, receipt_from_ledger, union_evidence
from .orchestrator import (
    architecture,
    cbm_candidates_from_outcome,
    envelope_fed_kwargs,
    federated_extras,
    federation_plan,
    resolve_federated_spec,
    run_federated_query,
    search_rows_from_payload,
    target_conflicts,
    trace_edges_from_payload,
)
from .routing import (
    COMMAND_CAPABILITY,
    QUERYABLE_PROVIDERS,
    effective_provider_spec,
    parse_provider_spec,
    supports_capability,
)

__all__ = [
    "GAP_TAXONOMY",
    "ledger_rows_for_runs",
    "receipt_from_ledger",
    "union_evidence",
    "CoverageReport",
    "CoverageState",
    "coverage_note",
    "completeness",
    "repo_coverage",
    "Span",
    "assured_query_context",
    "resolve_symbol",
    "stale_files_warning",
    "architecture",
    "cbm_candidates_from_outcome",
    "envelope_fed_kwargs",
    "federated_extras",
    "federation_plan",
    "resolve_federated_spec",
    "run_federated_query",
    "search_rows_from_payload",
    "trace_edges_from_payload",
    "target_conflicts",
    "COMMAND_CAPABILITY",
    "QUERYABLE_PROVIDERS",
    "effective_provider_spec",
    "parse_provider_spec",
    "supports_capability",
]
