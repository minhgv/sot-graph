# CLAUDE Agent Rules

## SOT-Graph Knowledge Reuse Protocol (SSOT v0.3.0)
- **Zero Hallucinated Anchors**: The filesystem is the single source of truth. Always ground symbol existence using `sot search` or MCP `sot_search` (Pure-Read Search; never mutates SQLite, Schema v5).
- **Multi-Provider Evidence**: Inspect `providers` in response envelopes to verify whether evidence is `AST_HEURISTIC_PARSER` or `COMPILER_SCIP_INDEX`.
- **Pre-Implementation Verification**: Before writing new helper utilities, search if a verified implementation exists (`[STRONG]` verdict with `confidence ≥ 0.9`).
- **Architectural Blast Radius (Honest Usages)**: Before changing core functions/classes, run `sot explore "<symbol>" --depth 2` or MCP `sot_explore` / `sot_usages`. If `status == "PARTIAL"`, do not assume 0 callers; inspect pending candidates first.
- **Compiler-Backed Semantic Accuracy**: When exact cross-package definitions are required, import SCIP indices via `sot import-scip <path_to_index.scip>`.
- **Graph-First Symbol & God Node Auditing**: Always query `sot explore` or Fact Bundles before inspecting code. Do NOT run blind `glob`/`grep` across the repository when `sot.db` exists.
- **Token-Bounded Subgraph Packaging**: When delegating work to subagents, use `sot pack "<symbol>" --tokens 1500 --json` (or `xd://sot_pack`) to produce live-verified context bundles without token waste.
- **Drift Synchronization & Note Preservation**: After refactoring, renaming, or deleting files, run `sot reconcile` for atomic content-hash rehoming. Run `sot doctor` to audit schema v5 health. User notes (`kind == 'note'`) are strictly preserved across index resets.
- **Diff & Revision Impact Analysis**: Before finalizing changes or opening pull requests, run `sot diff-impact` (or `sot_diff_impact` / `xd://sot_diff_impact`) to evaluate blast radius, upstream inward callers, API contract impacts, and affected test suites.
- **Git Commit History & Risk Scoring**: Inspect commit risk and impacted symbols via `sot log` (or `sot_git_history` / `xd://sot_git_history`).
