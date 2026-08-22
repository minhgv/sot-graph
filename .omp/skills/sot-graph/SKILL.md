---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, and graph analytics (Louvain clustering, God Node detection, HTML/GraphRAG/Obsidian export).
---

# /sot-graph (Single Source of Truth Knowledge Layer)

When to use:
- **Before writing or implementing code**: Search if utilities or existing solutions already exist (`sot search` / `sot_search`).
- **Before modifying core functions or classes**: Trace upstream/downstream dependencies (`sot explore` / `sot_explore`).
- **Verifying disk consistency**: Audit phantom anchors and drift (`sot verify` / `sot_verify`).
- **Recording knowledge**: Record non-obvious architecture choices or critical bug solutions (`sot insert` / `sot_insert`).
- **Architecture analysis**: Generate visual graphs or community reports (`sot cluster`, `sot report`, `sot viz`, `sot export`).

## Trust Verdicts
- `[STRONG]`: 100% verified against disk reality. File exists, symbol exists, content matches.
- `[WEAK]`: Semantic or partial match. Inspect the file before relying on it.
- `[REBUILT]`: File has moved location; use the updated path reported by the reconciler.

## Quick CLI Reference
| Task | CLI Command | Native Tool Equivalent |
| :--- | :--- | :--- |
| **Search Codebase** | `./bin/sot search "<query>" [-n 5]` | `sot_search(query="...")` |
| **Trace Call Graph** | `./bin/sot explore "<symbol>" [--depth 2]` | `sot_explore(target="...")` |
| **Synchronize DB** | `./bin/sot reconcile [--workers 4]` | `sot_reconcile()` |
| **Audit Drift** | `./bin/sot verify [--deep]` | `sot_verify()` |
| **Database Doctor** | `./bin/sot doctor` | `sot_doctor()` |
| **Store Note** | `./bin/sot insert --title "..." --body "..."` | `sot_insert(...)` |
| **Cluster Communities** | `./bin/sot cluster` | `sot_cluster()` |
| **Export Graph** | `./bin/sot export --format obsidian` | `sot_export(...)` |
