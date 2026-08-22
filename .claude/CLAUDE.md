# CLAUDE Agent Rules

## SOT-Graph Knowledge Reuse Protocol (SSOT)
- **Zero Hallucinated Anchors**: The filesystem is the single source of truth. Always ground symbol existence using `sot search` or MCP `sot_search`.
- **Pre-Implementation Verification**: Before writing new helper utilities, search if a verified implementation exists (`[STRONG]` verdict).
- **Architectural Blast Radius**: Before changing core functions/classes, run `sot explore "<symbol>"` or MCP `sot_explore` to verify all incoming references.
- **Drift Synchronization**: After refactoring, renaming, or deleting files, run `sot reconcile` to purge dead paths.
