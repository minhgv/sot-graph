"""sot_graph.providers — Federated evidence-provider adapters (FEDERATED_CLI).

Purely additive package: adapters talk to external evidence tools
(currently Codebase Memory) over a bounded one-shot CLI wire format.
Nothing in this package is wired into the query path yet (P1 boundary);
callers opt in explicitly and must pass ``allow_external`` gating upstream.

Modules:
- ``base``: EvidenceProvider protocol, request dataclasses, run records,
  capability negotiation helpers.
- ``codebase_memory``: the Codebase Memory CLI adapter (one-shot argv,
  MCP-envelope parsing, honest abstention with ``next_action``).
- ``normalization``: versioned CBM-relation -> SOT canonical mapping table
  and trust-ceiling rules reusing existing evidence enums.
"""

from .scip import ScipProvider

__all__ = ["ScipProvider"]
