"""sot_graph.assurance — the shared query-assurance engine (P2).

One engine behind both surfaces:

- :mod:`.engine` — symbol resolution + pre-query assurance (snapshot
  descriptor, stale-journal detection, ledger invalidation marking).
- :mod:`.routing` — provider spec parsing + capability routing tables.
- :mod:`.orchestrator` — federated provider negotiation, typed outcomes,
  candidate normalization, target-conflict adjudication.

CLI handlers and McpService import from here; no orchestration logic lives
in presentation layers. identity/normalization/coverage/verification
modules currently live in :mod:`sot_graph.providers` and move into this
package in their owning phases (P4-P7).
"""

from .engine import assured_query_context, resolve_symbol, stale_files_warning
from .orchestrator import (
    cbm_candidates_from_outcome,
    envelope_fed_kwargs,
    federated_extras,
    federation_plan,
    resolve_federated_spec,
    run_federated_query,
    target_conflicts,
)
from .routing import (
    COMMAND_CAPABILITY,
    QUERYABLE_PROVIDERS,
    effective_provider_spec,
    parse_provider_spec,
    supports_capability,
)

__all__ = [
    "assured_query_context",
    "resolve_symbol",
    "stale_files_warning",
    "cbm_candidates_from_outcome",
    "envelope_fed_kwargs",
    "federated_extras",
    "federation_plan",
    "resolve_federated_spec",
    "run_federated_query",
    "target_conflicts",
    "COMMAND_CAPABILITY",
    "QUERYABLE_PROVIDERS",
    "effective_provider_spec",
    "parse_provider_spec",
    "supports_capability",
]
