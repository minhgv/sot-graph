# Agent Rules & Protocols (SOT-Graph SSOT v0.3.0)

## SOT-Graph Knowledge Reuse & Multi-Provider Protocol

Before implementing any new feature, fix, or refactoring:
1. Check existing work across projects using the Single Source of Truth search:
   `sot search "<what you are looking for>" --scope <optional-dir> [--json]`
2. Follow Multi-Provider Trust Verdict Guidance:
   - `[STRONG]`: High confidence — file and symbols physically verified on disk (Schema v8).
   - `[WEAK]`: Semantic match only — inspect the file snippet before relying on it.
   - `[REBUILT]`: File has moved location; use the updated reported path.
   - `[REMOVED]`: Node deleted on disk; do NOT reference or hallucinate.
3. Check `providers` in response envelope to distinguish AST heuristic extractions from compiler-backed SCIP indices.
4. Trace architectural impact before modifying core symbols:
   `sot explore "<symbol_or_function_name>" --depth 2`
5. Ingest compiler indices for 100% exact cross-file references:
   `sot import-scip <path_to_index.scip>`
6. Package subgraphs for subagents under strict token ceilings:
   `sot pack "<symbol>" --tokens 1500 --json`
7. After completing reusable work, architecture choices, or tricky fixes, persist it:
   `sot insert --title "<topic>" --body "<details>" --keywords "k1,k2"`
   *(User notes are permanently preserved even when resetting disposable graph indexes).*

# SOT-Graph Single Source of Truth Protocols & Rules for Agents (SSOT v0.3.0)

## 1. Filesystem as Single Source of Truth (SSOT)
- The physical filesystem is the absolute ground truth. The SOT knowledge graph (`.sot/sot.db`) is an authoritative projection of reality (Schema v8).
- Never assume a file path exists based on historical context without verification.

## 2. Knowledge Reuse & Multi-Provider Protocol (Mandatory Before Implementation)
Before writing any new utility, helper function, or class:
1. Run `sot search "<keyword>" [--json]` or use the `sot_search` MCP tool (Pure-Read Search; never mutates SQLite).
2. Check Multi-Provider Trust Verdicts:
   - `[STRONG]`: Code physically exists and is verified on disk (`confidence ≥ 0.9`).
   - `[WEAK]`: Semantic match only; inspect the file snippet before relying on it.
   - `[REBUILT]`: File was moved; use the updated path.
   - `[REMOVED]`: Node deleted on disk; do NOT reference.
   - `[NOPATH]`: Virtual/inline node; verify origin.
3. Inspect `providers` metadata to distinguish `AST_HEURISTIC_PARSER` vs. `COMPILER_SCIP_INDEX`.

## 3. Dependency Impact & Safe Refactoring Protocol (Honest Usages)
Before modifying, refactoring, or renaming core functions/classes:
1. Run `sot explore "<symbol>" [--depth 2] [--json]` or `sot_explore` to inspect Outward Calls and Incoming References.
2. Run `sot usages "<symbol>" [--json]` or `sot_usages` to locate all calling sites.
3. For interfaces or abstract classes, run `sot implementations "<symbol>"` or `sot_implementations`.
4. For compiler-exact cross-package symbol resolution, run `sot import-scip <path_to_index.scip>`.
5. For multi-file symbol renames, run `sot rename "<symbol>" --to "<new_name>"` to review staged changes.
6. Before submitting PRs or finalizing diffs, run `sot diff-impact [target]` or `sot_diff_impact` to evaluate blast radius, upstream inward callers, API contract impacts, and affected test suites.
7. Inspect git commit history risk scores and impacted symbols via `sot log` or `sot_git_history`.
## 4. Context Isolation & Hard-Budget Subgraph Packaging Protocol
When delegating code context to subagents or prompt registers:
1. Run `sot pack "<symbol>" --tokens 1500 --json` (or `sot_pack`) to extract a token-efficient k-hop subgraph with hard token ceiling.
2. Feed the compact ContextBundle instead of full raw files to save 60-70% tokens.

## 5. Self-Healing, Note Preservation & Storage Integrity
- If you create, move, or delete files, run `sot reconcile`.
- Run `sot doctor` to audit database health, schema v5, and page allocations.
- `sot clean --all` purges disposable graph records while permanently preserving user notes (`kind == 'note'`).
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sot insert --title "..." --body "..." --keywords "..."`.

## 6. Architecture Analysis & Fact Bundle Protocol
When requested to review or synthesize architecture documentation:
1. Run `sot bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/` (MCP output paths are strictly confined to project root).
2. Ingest the 5 fact files (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`) along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`.
3. Output the report with facts grounded ONLY in the bundle files (mark anything beyond them as [INFERENCE]), valid diagrams, and prioritized recommendations.

## Quick CLI & MCP Reference
| Category | CLI Command | MCP Tool |
| :--- | :--- | :--- |
| **Search Codebase** | `sot search "<query>" [-n 5] [--json]` | `sot_search` |
| **Repository Map** | `sot map [--focus <areas>] [--tokens 1024]` | `sot_map` |
| **Trace Call Graph** | `sot explore "<symbol>" [--depth 2] [--json]` | `sot_explore` |
| **Inspect Usages** | `sot usages "<symbol>" [--json]` | `sot_usages` |
| **Import SCIP Index**| `sot import-scip <path> [--provider-version v1]` | CLI |
| **Implementations** | `sot implementations "<interface>"` | `sot_implementations` |
| **Rename Impact** | `sot rename "<symbol>" --to <new_name>` | `CLI only` |
| **Pack Subgraph** | `sot pack "<symbol>" [--tokens 1500] [--json]` | `sot_pack` |
| **Synchronize DB** | `sot reconcile [--workers 4] [--force]` | `CLI only` |
| **Audit Drift** | `sot verify [--deep]` | `sot_verify_drift` |
| **Database Doctor** | `sot doctor [--json]` | `CLI only` |
| **Clean Stale Data**| `sot clean [--all] [--include-notes]` | `CLI only` |
| **Vacuum Database** | `sot vacuum [--analyze]` | `CLI only` |
| **Store Note** | `sot insert --title "..." --body "..."` | `CLI only` |
| **Cluster Graph** | `sot cluster [--scope <path>]` | `sot_communities` |
| **Architecture Report** | `sot report [-o report.md]` | `sot_architecture_report` |
| **Interactive Viz** | `sot viz [-o graph.html]` | `CLI only` |
| **Export Graph** | `sot export -f <graphrag\|obsidian\|scip>` | `CLI only` |
| **Fact Bundler** | `sot bundle [-o .sot/bundle/]` | `sot_bundle` |
| **Full-Stack Trace** | `sot trace "<target>" [--depth 2] [-o <file>]` | `sot_trace` |
| **UI Decision Tree** | `sot ui-tree "<component>"` | `sot_ui_tree` |
| **Backend Flow** | `sot be-flow "<service>"` | `sot_backend_flow` |
| **Feature Inventory** | `sot solution inventory [module] [-o <file>]` | `sot_solution_inventory` |
| **Micro-steps Decompose** | `sot solution steps "<method>" [--format table]` | `sot_solution_steps` |
| **Solution Bundle** | `sot solution bundle [module] [-o <file>]` | `sot_solution_bundle` |
| **Diff Impact** | `sot diff-impact [target] [--staged] [--depth 2]` | `sot_diff_impact` |
| **Commit History** | `sot log [-n 10] [--author <name>] [--since <date>]` | `sot_git_history` |
| **Embed Index** | `sot embed [--limit 5000]` | CLI |
| **File Watcher** | `sot watch [--debounce-ms 200]` | CLI (Daemon) |
| **Harness Setup** | `sot setup [--harness <name>]` | CLI |

# SOT-Graph Single Source of Truth Protocols & Rules for Agents (SSOT v0.3.0)

## 1. Filesystem as Single Source of Truth (SSOT)
- The physical filesystem is the absolute ground truth. The SOT knowledge graph (`.sot/sot.db`) is an authoritative projection of reality (Schema v8).
- Never assume a file path exists based on historical context without verification.

## 2. Knowledge Reuse & Multi-Provider Protocol (Mandatory Before Implementation)
Before writing any new utility, helper function, or class:
1. Run `sot search "<keyword>" [--json]` or use the `sot_search` MCP tool (Pure-Read Search; never mutates SQLite).
2. Check Multi-Provider Trust Verdicts:
   - `[STRONG]`: Code physically exists and is verified on disk (`confidence ≥ 0.9`).
   - `[WEAK]`: Semantic match only; inspect the file snippet before relying on it.
   - `[REBUILT]`: File was moved; use the updated path.
   - `[REMOVED]`: Node deleted on disk; do NOT reference.
   - `[NOPATH]`: Virtual/inline node; verify origin.
3. Inspect `providers` metadata to distinguish `AST_HEURISTIC_PARSER` vs. `COMPILER_SCIP_INDEX`.

## 3. Dependency Impact & Safe Refactoring Protocol (Honest Usages)
Before modifying, refactoring, or renaming core functions/classes:
1. Run `sot explore "<symbol>" [--depth 2] [--json]` or `sot_explore` to inspect Outward Calls and Incoming References.
2. Run `sot usages "<symbol>" [--json]` or `sot_usages` to locate all calling sites.
3. For interfaces or abstract classes, run `sot implementations "<symbol>"` or `sot_implementations`.
4. For compiler-exact cross-package symbol resolution, run `sot import-scip <path_to_index.scip>`.
5. For multi-file symbol renames, run `sot rename "<symbol>" --to "<new_name>"` to review staged changes.
6. Before submitting PRs or finalizing diffs, run `sot diff-impact [target]` or `sot_diff_impact` to evaluate blast radius, upstream inward callers, API contract impacts, and affected test suites.
7. Inspect git commit history risk scores and impacted symbols via `sot log` or `sot_git_history`.
## 4. Context Isolation & Hard-Budget Subgraph Packaging Protocol
When delegating code context to subagents or prompt registers:
1. Run `sot pack "<symbol>" --tokens 1500 --json` (or `sot_pack`) to extract a token-efficient k-hop subgraph with hard token ceiling.
2. Feed the compact ContextBundle instead of full raw files to save 60-70% tokens.

## 5. Self-Healing, Note Preservation & Storage Integrity
- If you create, move, or delete files, run `sot reconcile`.
- Run `sot doctor` to audit database health, schema v5, and page allocations.
- `sot clean --all` purges disposable graph records while permanently preserving user notes (`kind == 'note'`).
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sot insert --title "..." --body "..." --keywords "..."`.

## 6. Architecture Analysis & Fact Bundle Protocol
When requested to review or synthesize architecture documentation:
1. Run `sot bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/` (MCP output paths are strictly confined to project root).
2. Ingest the 5 fact files (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`) along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`.
3. Output the report with facts grounded ONLY in the bundle files (mark anything beyond them as [INFERENCE]), valid diagrams, and prioritized recommendations.

## Quick CLI & MCP Reference
| Category | CLI Command | MCP Tool |
| :--- | :--- | :--- |
| **Search Codebase** | `sot search "<query>" [-n 5] [--json]` | `sot_search` |
| **Repository Map** | `sot map [--focus <areas>] [--tokens 1024]` | `sot_map` |
| **Trace Call Graph** | `sot explore "<symbol>" [--depth 2] [--json]` | `sot_explore` |
| **Inspect Usages** | `sot usages "<symbol>" [--json]` | `sot_usages` |
| **Import SCIP Index**| `sot import-scip <path> [--provider-version v1]` | CLI |
| **Implementations** | `sot implementations "<interface>"` | `sot_implementations` |
| **Rename Impact** | `sot rename "<symbol>" --to <new_name>` | `CLI only` |
| **Pack Subgraph** | `sot pack "<symbol>" [--tokens 1500] [--json]` | `sot_pack` |
| **Synchronize DB** | `sot reconcile [--workers 4] [--force]` | `CLI only` |
| **Audit Drift** | `sot verify [--deep]` | `sot_verify_drift` |
| **Database Doctor** | `sot doctor [--json]` | `CLI only` |
| **Clean Stale Data**| `sot clean [--all] [--include-notes]` | `CLI only` |
| **Vacuum Database** | `sot vacuum [--analyze]` | `CLI only` |
| **Store Note** | `sot insert --title "..." --body "..."` | `CLI only` |
| **Cluster Graph** | `sot cluster [--scope <path>]` | `sot_communities` |
| **Architecture Report** | `sot report [-o report.md]` | `sot_architecture_report` |
| **Interactive Viz** | `sot viz [-o graph.html]` | `CLI only` |
| **Export Graph** | `sot export -f <graphrag\|obsidian\|scip>` | `CLI only` |
| **Fact Bundler** | `sot bundle [-o .sot/bundle/]` | `sot_bundle` |
| **Full-Stack Trace** | `sot trace "<target>" [--depth 2] [-o <file>]` | `sot_trace` |
| **UI Decision Tree** | `sot ui-tree "<component>"` | `sot_ui_tree` |
| **Backend Flow** | `sot be-flow "<service>"` | `sot_backend_flow` |
| **Feature Inventory** | `sot solution inventory [module] [-o <file>]` | `sot_solution_inventory` |
| **Micro-steps Decompose** | `sot solution steps "<method>" [--format table]` | `sot_solution_steps` |
| **Solution Bundle** | `sot solution bundle [module] [-o <file>]` | `sot_solution_bundle` |
| **Diff Impact** | `sot diff-impact [target] [--staged] [--depth 2]` | `sot_diff_impact` |
| **Commit History** | `sot log [-n 10] [--author <name>] [--since <date>]` | `sot_git_history` |
| **Embed Index** | `sot embed [--limit 5000]` | CLI |
| **File Watcher** | `sot watch [--debounce-ms 200]` | CLI (Daemon) |
| **Harness Setup** | `sot setup [--harness <name>]` | CLI |

# SOT-Graph Single Source of Truth Protocols & Rules for Agents (SSOT v0.3.0)

## 1. Filesystem as Single Source of Truth (SSOT)
- The physical filesystem is the absolute ground truth. The SOT knowledge graph (`.sot/sot.db`) is an authoritative projection of reality (Schema v8).
- Never assume a file path exists based on historical context without verification.

## 2. Knowledge Reuse & Multi-Provider Protocol (Mandatory Before Implementation)
Before writing any new utility, helper function, or class:
1. Run `sot search "<keyword>" [--json]` or use the `sot_search` MCP tool (Pure-Read Search; never mutates SQLite).
2. Check Multi-Provider Trust Verdicts:
   - `[STRONG]`: Code physically exists and is verified on disk (`confidence ≥ 0.9`).
   - `[WEAK]`: Semantic match only; inspect the file snippet before relying on it.
   - `[REBUILT]`: File was moved; use the updated path.
   - `[REMOVED]`: Node deleted on disk; do NOT reference.
   - `[NOPATH]`: Virtual/inline node; verify origin.
3. Inspect `providers` metadata to distinguish `AST_HEURISTIC_PARSER` vs. `COMPILER_SCIP_INDEX`.

## 3. Dependency Impact & Safe Refactoring Protocol (Honest Usages)
Before modifying, refactoring, or renaming core functions/classes:
1. Run `sot explore "<symbol>" [--depth 2] [--json]` or `sot_explore` to inspect Outward Calls and Incoming References.
2. Run `sot usages "<symbol>" [--json]` or `sot_usages` to locate all calling sites.
3. For interfaces or abstract classes, run `sot implementations "<symbol>"` or `sot_implementations`.
4. For compiler-exact cross-package symbol resolution, run `sot import-scip <path_to_index.scip>`.
5. For multi-file symbol renames, run `sot rename "<symbol>" --to "<new_name>"` to review staged changes.
6. Before submitting PRs or finalizing diffs, run `sot diff-impact [target]` or `sot_diff_impact` to evaluate blast radius, upstream inward callers, API contract impacts, and affected test suites.
7. Inspect git commit history risk scores and impacted symbols via `sot log` or `sot_git_history`.
## 4. Context Isolation & Hard-Budget Subgraph Packaging Protocol
When delegating code context to subagents or prompt registers:
1. Run `sot pack "<symbol>" --tokens 1500 --json` (or `sot_pack`) to extract a token-efficient k-hop subgraph with hard token ceiling.
2. Feed the compact ContextBundle instead of full raw files to save 60-70% tokens.

## 5. Self-Healing, Note Preservation & Storage Integrity
- If you create, move, or delete files, run `sot reconcile`.
- Run `sot doctor` to audit database health, schema v5, and page allocations.
- `sot clean --all` purges disposable graph records while permanently preserving user notes (`kind == 'note'`).
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sot insert --title "..." --body "..." --keywords "..."`.

## 6. Architecture Analysis & Fact Bundle Protocol
When requested to review or synthesize architecture documentation:
1. Run `sot bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/` (MCP output paths are strictly confined to project root).
2. Ingest the 5 fact files (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`) along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`.
3. Output the report with facts grounded ONLY in the bundle files (mark anything beyond them as [INFERENCE]), valid diagrams, and prioritized recommendations.

## Quick CLI & MCP Reference
| Category | CLI Command | MCP Tool |
| :--- | :--- | :--- |
| **Search Codebase** | `sot search "<query>" [-n 5] [--json]` | `sot_search` |
| **Repository Map** | `sot map [--focus <areas>] [--tokens 1024]` | `sot_map` |
| **Trace Call Graph** | `sot explore "<symbol>" [--depth 2] [--json]` | `sot_explore` |
| **Inspect Usages** | `sot usages "<symbol>" [--json]` | `sot_usages` |
| **Import SCIP Index**| `sot import-scip <path> [--provider-version v1]` | CLI |
| **Implementations** | `sot implementations "<interface>"` | `sot_implementations` |
| **Rename Impact** | `sot rename "<symbol>" --to <new_name>` | `CLI only` |
| **Pack Subgraph** | `sot pack "<symbol>" [--tokens 1500] [--json]` | `sot_pack` |
| **Synchronize DB** | `sot reconcile [--workers 4] [--force]` | `CLI only` |
| **Audit Drift** | `sot verify [--deep]` | `sot_verify_drift` |
| **Database Doctor** | `sot doctor [--json]` | `CLI only` |
| **Clean Stale Data**| `sot clean [--all] [--include-notes]` | `CLI only` |
| **Vacuum Database** | `sot vacuum [--analyze]` | `CLI only` |
| **Store Note** | `sot insert --title "..." --body "..."` | `CLI only` |
| **Cluster Graph** | `sot cluster [--scope <path>]` | `sot_communities` |
| **Architecture Report** | `sot report [-o report.md]` | `sot_architecture_report` |
| **Interactive Viz** | `sot viz [-o graph.html]` | `CLI only` |
| **Export Graph** | `sot export -f <graphrag\|obsidian\|scip>` | `CLI only` |
| **Fact Bundler** | `sot bundle [-o .sot/bundle/]` | `sot_bundle` |
| **Full-Stack Trace** | `sot trace "<target>" [--depth 2] [-o <file>]` | `sot_trace` |
| **UI Decision Tree** | `sot ui-tree "<component>"` | `sot_ui_tree` |
| **Backend Flow** | `sot be-flow "<service>"` | `sot_backend_flow` |
| **Feature Inventory** | `sot solution inventory [module] [-o <file>]` | `sot_solution_inventory` |
| **Micro-steps Decompose** | `sot solution steps "<method>" [--format table]` | `sot_solution_steps` |
| **Solution Bundle** | `sot solution bundle [module] [-o <file>]` | `sot_solution_bundle` |
| **Diff Impact** | `sot diff-impact [target] [--staged] [--depth 2]` | `sot_diff_impact` |
| **Commit History** | `sot log [-n 10] [--author <name>] [--since <date>]` | `sot_git_history` |
| **Embed Index** | `sot embed [--limit 5000]` | CLI |
| **File Watcher** | `sot watch [--debounce-ms 200]` | CLI (Daemon) |
| **Harness Setup** | `sot setup [--harness <name>]` | CLI |

