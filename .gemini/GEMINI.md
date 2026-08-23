# Gemini Agent Rules

## SOT-Graph Knowledge Reuse Protocol (SSOT v0.2.0)
- **Zero Hallucinated Anchors**: The filesystem is the single source of truth. Always ground symbol existence using `sot search` or `sot_search` (Pure-Read Search; never mutates SQLite).
- **Pre-Implementation Verification**: Before writing new helper utilities, search if a verified implementation exists (`[STRONG]` verdict with `confidence ≥ 0.9`).
- **Architectural Blast Radius (Honest Usages)**: Before changing core functions/classes, run `sot explore "<symbol>" --depth 2` or `sot_explore` / `sot_usages`. If `status == "PARTIAL"`, do not assume 0 callers; inspect pending candidates first.
- **Token-Bounded Subgraph Packaging**: When delegating work to subagents, use `sot pack "<symbol>" --tokens 1500` to produce live-verified YAML context bundles without token waste.
- **Drift Synchronization**: After refactoring, renaming, or deleting files, run `sot reconcile` for atomic content-hash rehoming. Verify graph health with `sot doctor`.
