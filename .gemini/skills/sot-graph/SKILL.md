---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Multi-Dimensional Trust Evidence v2 ([STRONG], [WEAK], [REBUILT]), Pure-Read Search, Honest Usages & Call Graph Semantics, Compass 2-Hop Exploration, Live-Verified Hard-Budget Context Packaging, Zero-Daemon SQLite Storage (with PRAGMA health checks & atomic content-hash rehoming), and 2-stage fact bundle extraction for LLM architecture reports.
---

# /sot-graph (Single Source of Truth Knowledge Layer v0.2.0)

When to use:
- **Top-down orientation**: Map repository architecture without token waste (`sot map` / `sot_map`).
- **Before writing or implementing code**: Search if utilities or existing solutions already exist (`sot search` / `sot_search`). Pure-read search never mutates SQLite.
- **Before modifying core functions or classes**: Trace upstream/downstream dependencies (`sot explore` / `sot_explore`) with 2-Hop Compass UX and inspect exact call-sites (`sot usages` / `sot_usages`) with honest pending candidate semantics.
- **Polymorphism & interface inspection**: Inspect concrete implementations (`sot implementations` / `sot_implementations`).
- **Safe symbol refactoring**: Plan or execute multi-file renames (`sot rename`).
- **Token-bounded context packaging**: Extract k-hop subgraphs into live-verified YAML ContextBundles with hard token ceilings (`sot pack` / `sot_pack`).
- **Verifying disk consistency**: Audit phantom anchors and drift (`sot verify` / `sot_verify_drift`).
- **Database health & storage diagnostics**: Inspect SQLite PRAGMA quick_check, foreign keys, and journal consistency (`sot doctor` / `sot_doctor`).
- **Recording knowledge**: Record non-obvious architecture choices or critical bug solutions (`sot insert` / `sot_notes`).
- **Architecture analysis & reports**: Extract 5 fact bundle files (`sot bundle` / `sot_bundle`), generate visual graphs, community clustering, or health reports (`sot cluster`, `sot report`, `sot viz`, `sot export`).
- **Database maintenance**: Purge stale records and vacuum freelists (`sot clean`, `sot vacuum`, `sot reconcile`).

---

## 1. Multi-Dimensional Trust Evidence v2

Search results provide structured, multi-dimensional trust evidence instead of raw string tags:

```json
{
  "verdict": "STRONG",
  "evidence": {
    "freshness": "FRESH",
    "relevance": "EXACT_SPAN",
    "resolution": "EXACT",
    "completeness": "COMPLETE",
    "confidence": 0.95,
    "provenance": "tree_sitter:v2"
  }
}
```

- **Verdict Summary**:
  - `[STRONG]`: 100% physically verified against disk reality. File exists, hash matches journal, exact AST span confirmed.
  - `[WEAK]`: Semantic or partial token match. Inspect the file snippet before relying on it.
  - `[REBUILT]`: File has moved location on disk; path updated automatically via content-hash matching.
  - `[REMOVED]`: Node deleted on disk; do NOT reference or hallucinate.
  - `[NOPATH]`: Virtual/inline node without a direct physical file backing.
- **Freshness**: `FRESH` (mtime & hash match) | `STALE` (file modified) | `MISSING` (file missing).
- **Relevance**: `EXACT_SPAN` (AST node span matched) | `EXACT_SYMBOL` (symbol name matched) | `FILE_TOKEN` (lexical token matched).
- **Resolution**: `EXACT` (direct resolved edge) | `INFERRED` (receiver type / MRO inferred) | `AMBIGUOUS` (multiple targets) | `UNRESOLVED` (pending edge).

---

## 2. Agent Workflows & Decision Protocols

### Workflow A: Orientation & Exploration
1. Run `sot map --tokens 1024` to obtain an initial Personalized PageRank architecture map.
2. For specific modules, run `sot explore "<symbol>" --depth 2` to view 1-hop direct dependencies and 2-hop transitive paths. High in-degree nodes (>20 callers) are automatically collapsed.

### Workflow B: Safe Implementation & Knowledge Reuse
1. **Never write new helpers from scratch.** Search first: `sot search "<keyword>"`.
2. Inspect `verdict` and `confidence`:
   - If `[STRONG]` with `confidence ≥ 0.9`: Reuse existing function/class directly.
   - If `[WEAK]`: Use `read` with line range (`file.py:10-40`) to inspect implementation before deciding.

### Workflow C: Blast Radius & Safe Refactoring (Honest Usages)
1. Before changing a function/method signature, run `sot usages "<symbol>"`.
2. **Evaluate Status**:
   - If `status == "COMPLETE"` and `confirmed_callers` is empty: Symbol has 0 callers with complete graph coverage.
   - If `status == "PARTIAL"`: System detected `unresolved_candidates` in `pending_edges`. Agent MUST NOT assume zero callers; inspect candidate locations or verify dynamic calls before deleting or modifying signatures.

### Workflow D: Token-Bounded Subagent Context Handoff
1. When delegating multi-file tasks to subagents (`task` / `worker`), avoid raw sequential file reads.
2. Run `sot pack "<symbol>" --tokens 1500 -o context.yaml`.
3. SOT-Graph packs 1-hop callers, 2-hop callees, and type dependencies with physical line hash validation and hard token bounding ($\le 5\%$ error margin).

### Workflow E: Disk Drift & Self-Healing
1. If files are modified, created, or deleted during edits:
   - Run `sot reconcile` (or native tool `xd://sot_reconcile`).
   - SOT-Graph performs atomic content-hash rehoming in 1 transaction without losing edge relationships.
2. Periodically verify graph health with `sot doctor`.

### Workflow F: Symbol & God Node Auditing (Zero Blind Discovery)
1. When asked to audit, inspect, or understand God Nodes, Classes, or Modules:
   - **Step 1 (Graph Query):** Run `sot explore "<symbol>" --depth 2` or `sot usages "<symbol>"` (or inspect `.sot/bundle/` fact files). Extract method inventories, callers, and blast radius instantly (0.1s).
   - **Step 2 (Zero Blind File Discovery):** Do NOT spawn Scouts to run `glob`/`grep` across the repository when `sot.db` exists.
   - **Step 3 (Pinpointed Range Reads):** Scouts MUST ONLY read exact line numbers (`file:start-end`) for methods requiring deep body logic verification.

---

## 3. CLI & Native Tool Device Reference

| Category | CLI Command | Native Tool Device | Description |
| :--- | :--- | :--- | :--- |
| **Search Codebase** | `sot search "<query>" [-n 5] [--hybrid]` | `xd://sot_search` | Pure-read verified AST symbol & knowledge search |
| **Repository Map** | `sot map [--focus <areas>] [--tokens 1024]` | `xd://sot_map` | PageRank-ranked repository architecture map |
| **Trace Call Graph** | `sot explore "<symbol>" [--depth 2]` | `xd://sot_explore` | 2-Hop Compass call graph with in-degree collapsing |
| **Inspect Usages** | `sot usages "<symbol>"` | `xd://sot_usages` | Honest call-site inspection with pending candidate tracking |
| **Implementations** | `sot implementations "<interface>"` | `xd://sot_implementations` | Traversal of concrete class & interface implementations |
| **Rename Impact** | `sot rename "<symbol>" [--to <new_name>]` | `xd://sot_rename` | Safe structural symbol rename blast radius planning |
| **Pack Subgraph** | `sot pack "<symbol>" [--tokens 1500] [-o <file>]`| `xd://sot_pack` | Hard-budget live-verified ContextBundle packaging |
| **Synchronize DB** | `sot reconcile [--workers 4]` | `xd://sot_reconcile` | Atomic single-writer hash-based self-healing |
| **Batch Reconcile** | `sot batch-reconcile <dir> [--workers 4]` | CLI | Parallel directory reconciliation for monorepos |
| **Audit Drift** | `sot verify [--deep]` | `xd://sot_verify` | Read-only disk drift audit |
| **Database Doctor** | `sot doctor [--json]` | `xd://sot_doctor` | PRAGMA quick_check, foreign keys, schema health |
| **Clean Stale Data**| `sot clean [--all] [--include-notes]` | `xd://sot_clean` | Purge unreferenced nodes and journal artifacts |
| **Vacuum Database** | `sot vacuum [--analyze]` | `xd://sot_vacuum` | SQLite freelist compaction & query optimizer analyze |
| **Store Note** | `sot insert --title "..." --body "..."` | `xd://sot_insert` | Persistent knowledge recording for future sessions |
| **Cluster Graph** | `sot cluster [--scope <path>]` | `xd://sot_cluster` | Louvain / Label Propagation community detection |
| **Architecture Report** | `sot report [-o GRAPH_REPORT.md]` | `xd://sot_report` | God Node detection & modularity assessment |
| **Interactive Viz** | `sot viz [-o graph.html]` | `xd://sot_viz` | Standalone interactive D3.js knowledge graph visualizer |
| **Export Graph** | `sot export -f <graphrag/obsidian/scip>` | `xd://sot_export` | Export to GraphRAG JSON, Obsidian vault, SCIP |
| **Fact Bundler** | `sot bundle [-o .sot/bundle/]` | `xd://sot_bundle` | Extract 5 fact files for LLM architecture reports |
| **Full-Stack Trace** | `sot trace "<target>" [--depth 2]` | `xd://sot_trace` | End-to-end full-stack call & data flow trace |
| **UI Decision Tree** | `sot ui-tree "<component>"` | `xd://sot_ui_tree` | Hierarchical frontend component & state decomposition |
| **Backend Flow** | `sot be-flow "<service>"` | `xd://sot_backend_flow` | Service-to-database transaction flow extraction |
| **Feature Inventory** | `sot solution inventory [module]` | `xd://sot_solution_inventory` | Stage-1 feature cataloging for Solution Docs |
| **Micro-steps Decompose** | `sot solution steps "<method>"` | `xd://sot_solution_steps` | Granular AST execution step decomposition |
| **Solution Bundle** | `sot solution bundle [module]` | `xd://sot_solution_bundle` | Complete ContextBundle extraction for downstream docs |
