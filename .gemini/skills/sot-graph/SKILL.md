---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, and graph analytics (Louvain clustering, God Node detection, HTML/GraphRAG/Obsidian export, Fact Bundles).
---

# /sot-graph (Single Source of Truth Knowledge Layer for Google Antigravity / Gemini CLI)

Ground Gemini and Antigravity agent actions in physical filesystem reality using the SOT knowledge layer.

## When to Use SOT-Graph
- **Top-down orientation**: Map repository architecture without token waste (`sot map` / `sot_map`).
- **Before writing or implementing code**: Search if utilities or existing solutions already exist (`sot search` / `sot_search`).
- **Before modifying core functions or classes**: Trace upstream/downstream dependencies (`sot explore` / `sot_explore`, `sot usages` / `sot_usages`).
- **Polymorphism & interface inspection**: Inspect concrete implementations (`sot implementations` / `sot_implementations`).
- **Safe symbol refactoring**: Plan or execute multi-file renames (`sot rename` / `sot_rename`).
- **Token-efficient context packaging**: Extract k-hop subgraphs into YAML ContextBundles (`sot pack` / `sot_pack`).
- **Verifying disk consistency**: Audit phantom anchors and drift (`sot verify` / `sot_verify`).
- **Recording knowledge**: Record non-obvious architecture choices or critical bug solutions (`sot insert` / `sot_insert`).
- **Architecture analysis & reports**: Extract 5 fact bundle files (`sot bundle` / `sot_bundle`), generate visual graphs, community clustering, or health reports (`sot cluster`, `sot report`, `sot viz`, `sot export`).
- **Database maintenance**: Purge stale records and vacuum freelists (`sot clean`, `sot vacuum`, `sot doctor`).

## Trust Verdicts
| Verdict | Meaning | Action |
| :--- | :--- | :--- |
| `[STRONG]` | File exists on disk, symbol exists in AST, token coverage verified. | **Proceed directly.** 100% reliable anchor. |
| `[WEAK]` | Semantic or partial match; low lexical coverage. | **Inspect snippet range** before relying on symbol. |
| `[REBUILT]` | File moved or renamed; auto-rehomed by reconciler. | **Use updated path** reported in result. |
| `[REMOVED]` | Node deleted on disk; scheduled for purge. | **Do NOT use.** Symbol no longer exists. |
| `[NOPATH]` | Virtual or inline node without a physical file backing. | **Context-only.** Verify origin. |

## Quick CLI & MCP Tool Reference
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
| **Export Graph** | `sot export -f <graphrag/obsidian/scip>` | `sot_export` |
| **Fact Bundler** | `sot bundle [-o .sot/bundle/]` | `sot_bundle` |
| **Embed Index** | `sot embed [--limit 5000]` | CLI |
| **File Watcher** | `sot watch [--debounce-ms 200]` | CLI (Daemon) |
| **Harness Setup** | `sot setup [--harness <name>]` | CLI |
