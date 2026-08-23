---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, graph analytics (Louvain clustering, God Node detection, HTML/GraphRAG/Obsidian export), and 2-stage fact bundle extraction for comprehensive LLM architecture reports.
---

# /sot-graph (Single Source of Truth Knowledge Layer)

When to use:
- **Top-down orientation**: Map repository architecture without token waste (`sot map` / `sot_map`).
- **Before writing or implementing code**: Search if utilities or existing solutions already exist (`sot search` / `sot_search`).
- **Before modifying core functions or classes**: Trace upstream/downstream dependencies (`sot explore` / `sot_explore`) and exact call-sites (`sot usages` / `sot_usages`).
- **Polymorphism & interface inspection**: Inspect concrete implementations (`sot implementations` / `sot_implementations`).
- **Safe symbol refactoring**: Plan or execute multi-file renames (`sot rename`).
- **Token-efficient context packaging**: Extract k-hop subgraphs into YAML ContextBundles (`sot pack` / `sot_pack`).
- **Verifying disk consistency**: Audit phantom anchors and drift (`sot verify` / `sot_verify_drift`).
- **Recording knowledge**: Record non-obvious architecture choices or critical bug solutions (`sot insert` / `sot_notes`).
- **Architecture analysis & reports**: Extract 5 fact bundle files (`sot bundle` / `sot_bundle`), generate visual graphs, community clustering, or health reports (`sot cluster`, `sot report`, `sot viz`, `sot export`).
- **Database maintenance**: Purge stale records and vacuum freelists (`sot clean`, `sot vacuum`, `sot doctor`).

## Trust Verdicts
- `[STRONG]`: 100% verified against disk reality. File exists, symbol exists, token coverage matches.
- `[WEAK]`: Semantic or partial match. Inspect the file snippet before relying on it.
- `[REBUILT]`: File has moved location; use the updated path reported by the reconciler.
- `[REMOVED]`: Node deleted on disk; do NOT reference or hallucinate.
- `[NOPATH]`: Virtual/inline node without a direct physical file backing.

## Quick CLI Reference
| Category | CLI Command | Native Tool Device |
| :--- | :--- | :--- |
| **Search Codebase** | `sot search "<query>" [-n 5] [--hybrid]` | `xd://sot_search` |
| **Repository Map** | `sot map [--focus <areas>] [--tokens 1024]` | `xd://sot_map` |
| **Trace Call Graph** | `sot explore "<symbol>" [--depth 2]` | `xd://sot_explore` |
| **Inspect Usages** | `sot usages "<symbol>"` | `xd://sot_usages` |
| **Implementations** | `sot implementations "<interface>"` | `xd://sot_implementations` |
| **Rename Impact** | `sot rename "<symbol>" [--to <new_name>]` | `xd://sot_rename` |
| **Pack Subgraph** | `sot pack "<symbol>" [--depth 2] [-o <file>]`| `xd://sot_pack` |
| **Synchronize DB** | `sot reconcile [--workers 4]` | `xd://sot_reconcile` |
| **Audit Drift** | `sot verify [--deep]` | `xd://sot_verify` |
| **Database Doctor** | `sot doctor` | `xd://sot_doctor` |
| **Clean Stale Data**| `sot clean [--all] [--include-notes]` | `xd://sot_clean` |
| **Vacuum Database** | `sot vacuum [--analyze]` | `xd://sot_vacuum` |
| **Store Note** | `sot insert --title "..." --body "..."` | `xd://sot_insert` |
| **Cluster Graph** | `sot cluster [--scope <path>]` | `xd://sot_cluster` |
| **Architecture Report** | `sot report [-o GRAPH_REPORT.md]` | `xd://sot_report` |
| **Interactive Viz** | `sot viz [-o graph.html]` | `xd://sot_viz` |
| **Export Graph** | `sot export -f <graphrag|obsidian|scip>` | `xd://sot_export` |
| **Fact Bundler** | `sot bundle [-o .sot/bundle/]` | `xd://sot_bundle` |
