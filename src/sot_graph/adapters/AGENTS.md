# SOT-Graph Single Source of Truth Protocols & Rules for Agents

## 1. Filesystem as Single Source of Truth (SSOT)
- The physical filesystem is the absolute ground truth. The SOT knowledge graph (`.sot/sot.db`) is an authoritative projection of reality.
- Never assume a file path exists based on historical context without verification.

## 2. Knowledge Reuse Protocol (Mandatory Before Implementation)
Before writing any new utility, helper function, or class:
1. Run `sot search "<keyword>"` or use the `sot_search` MCP tool.
2. Check Trust Verdicts:
   - `[STRONG]`: Code physically exists and is verified on disk.
   - `[WEAK]`: Semantic match only; inspect the file.
   - `[REBUILT]`: File was moved; use the updated path.
   - `[REMOVED]`: Node deleted on disk; do NOT reference.
   - `[NOPATH]`: Virtual/inline node; verify origin.

## 3. Dependency Impact & Safe Refactoring Protocol
Before modifying, refactoring, or renaming core functions/classes:
1. Run `sot explore "<symbol>"` or `sot_explore` to inspect Outward Calls and Incoming References.
2. Run `sot usages "<symbol>"` or `sot_usages` to locate all calling sites.
3. For interfaces or abstract classes, run `sot implementations "<symbol>"` or `sot_implementations`.
4. For multi-file symbol renames, run `sot rename "<symbol>" --to "<new_name>"` to review staged changes.

## 4. Context Isolation & Subgraph Packaging Protocol
When delegating code context to subagents or prompt registers:
1. Run `sot pack "<symbol>" --depth 2 -o .sot/bundle/context.yaml` to extract a token-efficient k-hop subgraph.
2. Feed the compact YAML ContextBundle instead of full raw files to save 60-70% tokens.

## 5. Self-Healing & Drift Reconciliation
- If you create, move, or delete files, run `sot reconcile` or `sot_reconcile`.
- Run `sot verify --deep` or `sot_verify` to audit phantom anchors and dead paths.
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sot insert --title "..." --body "..." --keywords "..."`.

## 6. Architecture Analysis & Fact Bundle Protocol
When requested to review or synthesize architecture documentation:
1. Run `sot bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/`.
2. Ingest the 5 fact files (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`) along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`.
3. Output the report with 100% grounded facts, valid diagrams, and prioritized recommendations.

## Quick CLI & MCP Reference
| Category | CLI Command | MCP Tool |
| :--- | :--- | :--- |
| **Search Codebase** | `sot search "<query>" [-n 5] [--hybrid]` | `sot_search` |
| **Repository Map** | `sot map [--focus <areas>] [--tokens 1024]` | `sot_map` |
| **Trace Call Graph** | `sot explore "<symbol>" [--depth 2]` | `sot_explore` |
| **Inspect Usages** | `sot usages "<symbol>"` | `sot_usages` |
| **Implementations** | `sot implementations "<interface>"` | `sot_implementations` |
| **Rename Impact** | `sot rename "<symbol>" --to <new_name>` | `sot_rename` |
| **Pack Subgraph** | `sot pack "<symbol>" [--depth 2] [-o <file>]`| `sot_pack` |
| **Synchronize DB** | `sot reconcile [--workers 4]` | `sot_reconcile` |
| **Audit Drift** | `sot verify [--deep]` | `sot_verify` |
| **Database Doctor** | `sot doctor` | `sot_doctor` |
| **Clean Stale Data**| `sot clean [--purge-missing]` | `sot_clean` |
| **Vacuum Database** | `sot vacuum` | `sot_vacuum` |
| **Store Note** | `sot insert --title "..." --body "..."` | `sot_insert` |
| **Cluster Graph** | `sot cluster [--scope <path>]` | `sot_cluster` |
| **Architecture Report** | `sot report [-o report.md]` | `sot_report` |
| **Interactive Viz** | `sot viz [-o graph.html]` | `sot_viz` |
| **Export Graph** | `sot export -f <graphrag\|obsidian\|scip>` | `sot_export` |
| **Fact Bundler** | `sot bundle [-o .sot/bundle/]` | `sot_bundle` |
| **Full-Stack Trace** | `sot trace "<target>" [--depth 2] [-o <file>]` | `sot_trace` |
| **UI Decision Tree** | `sot ui-tree "<component>"` | `sot_ui_tree` |
| **Backend Flow** | `sot be-flow "<service>"` | `sot_backend_flow` |
| **Feature Inventory** | `sot solution inventory [module] [-o <file>]` | `sot_solution_inventory` |
| **Micro-steps Decompose** | `sot solution steps "<method>" [--format table]` | `sot_solution_steps` |
| **Solution Bundle** | `sot solution bundle [module] [-o <file>]` | `sot_solution_bundle` |
| **Embed Index** | `sot embed [--limit 5000]` | CLI |
| **File Watcher** | `sot watch [--debounce-ms 200]` | CLI (Daemon) |
| **Harness Setup** | `sot setup [--harness <name>]` | CLI |
