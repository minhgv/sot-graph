# OpenCode Agent Rules

## SOT-Graph Knowledge Reuse Protocol (SSOT v0.3.0)
- **Zero Hallucinated Anchors**: The filesystem is the single source of truth. Always ground symbol existence using `sot search` or `sot_search` (Pure-Read Search; never mutates SQLite, Schema v8).
- **Multi-Provider Verification**: Inspect `providers` in the standardized North-Star response envelope to distinguish fast regex/AST heuristics from compiler-backed SCIP indices.
- **Pre-Implementation Verification**: Before writing new helper utilities, search if a verified implementation exists (`[STRONG]` verdict with `confidence ≥ 0.9`).
- **Architectural Blast Radius (Honest Usages)**: Before changing core functions/classes, run `sot explore "<symbol>" --depth 2` or `sot_explore` / `sot_usages`. If `status == "PARTIAL"`, do not assume 0 callers; inspect pending candidates first.
- **Compiler Index Ingestion**: For 100% exact cross-file symbol resolution, run `sot import-scip <path_to_index.scip>`.
- **Graph-First Symbol & God Node Auditing**: Always query `sot explore` or Fact Bundles before inspecting code. Do NOT run blind `glob`/`grep` across the repository when `sot.db` exists.
- **Token-Bounded Subgraph Packaging**: When delegating work to subagents, use `sot pack "<symbol>" --tokens 1500 --json` to produce live-verified context bundles with hard token ceilings without token waste.
- **Drift Synchronization & Storage Health**: After refactoring, renaming, or deleting files, run `sot reconcile` for atomic content-hash rehoming. Run `sot doctor` to audit schema v5 health. User notes (`kind == 'note'`) are strictly preserved across index resets.
