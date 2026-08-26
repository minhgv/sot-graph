---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Multi-Provider Evidence Ledger (Schema v8), SCIP Compiler Indexing, North-Star Response Envelopes, Pure-Read Search, Honest Usages & Call Graph Semantics, Compass 2-Hop Exploration, Live-Verified Hard-Budget Context Packaging, Zero-Daemon SQLite Storage (with PRAGMA health checks & atomic content-hash rehoming), and 2-stage fact bundle extraction for LLM architecture reports.
---

# /sot-graph (Single Source of Truth Knowledge Layer v0.3.0)

When to use:
- **Top-down orientation**: Map repository architecture without token waste (`sot map` / `sot_map`).
- **Before writing or implementing code**: Search if utilities or existing solutions already exist (`sot search` / `sot_search`). Pure-read search never mutates SQLite.
- **Before modifying core functions or classes**: Trace upstream/downstream dependencies (`sot explore` / `sot_explore`) with 2-Hop Compass UX and inspect exact call-sites (`sot usages` / `sot_usages`) with honest pending candidate semantics.
- **Compiler-level accuracy**: Import SCIP index for 100% exact cross-file symbol resolution (`sot import-scip`).
- **Polymorphism & interface inspection**: Inspect concrete implementations (`sot implementations` / `sot_implementations`).
- **Safe symbol refactoring**: Plan or execute multi-file renames (`sot rename`).
- **Token-bounded context packaging**: Extract k-hop subgraphs into live-verified YAML or JSON ContextBundles with hard token ceilings (`sot pack` / `sot_pack`).
- **Verifying disk consistency**: Audit phantom anchors and drift (`sot verify` / `sot_verify_drift`).
- **Database health & storage diagnostics**: Inspect SQLite PRAGMA quick_check, foreign keys, and schema v5 consistency (`sot doctor` / `sot_doctor`).
- **Recording knowledge**: Record non-obvious architecture choices or critical bug solutions (`sot insert` / `sot_notes`).
- **Architecture analysis & reports**: Extract 5 fact bundle files (`sot bundle` / `sot_bundle`), generate visual graphs, community clustering, or health reports (`sot cluster`, `sot report`, `sot viz`, `sot export`).
- **Database maintenance**: Purge stale records and vacuum freelists with note preservation (`sot clean`, `sot vacuum`, `sot reconcile`).

---

## 1. Multi-Provider Evidence Ledger & Trust Veracity (Schema v8)

All query results provide structured **Multi-Provider Evidence** distinguishing static heuristic AST extractions from compiler-backed semantic indices:

```json
{
  "verdict": "STRONG",
  "evidence": {
    "freshness": "FRESH",
    "relevance": "EXACT_SPAN",
    "resolution": "EXACT",
    "completeness": "COMPLETE_WITHIN_INDEX_CAPABILITY",
    "confidence": 1.0,
    "provenance": "ast_visitor:exact_span",
    "file_path": "src/module/service.py",
    "file_hash": "sha256:...",
    "details": { "mtime_ms": 1787548621000, "stale": false }
  }
}
```

- **Verdict Hierarchy**:
  - `[STRONG]`: 100% physically verified against disk reality. File exists, hash matches journal, exact span confirmed.
  - `[WEAK]`: Semantic or partial token match. Agent MUST inspect the file snippet before relying on it.
  - `[REBUILT]`: File moved location on disk; path updated automatically via content-hash matching.
  - `[REMOVED]`: Node deleted on disk; do NOT reference or hallucinate.
  - `[NOPATH]`: Virtual/inline node without a direct physical file backing.
- **Multi-Provider Capabilities**:
  - `AST_HEURISTIC_PARSER` (`tree-sitter-ast`): Fast regex/AST heuristic extraction across 10+ languages.
  - `COMPILER_SCIP_INDEX` (`scip-importer`): Exact compiler-verified symbol occurrences, documentation, and cross-package references.

---

## 2. North-Star Response Envelope Contract

All CLI commands with `--json` (`search`, `explore`, `usages`, `pack`) and 100% MCP tool responses wrap data inside a standardized envelope:

```json
{
  "schema_version": "2.0.0",
  "snapshot_generation": 1,
  "manifest_digest": "sha256:...",
  "completeness": "COMPLETE_WITHIN_INDEX_CAPABILITY",
  "providers": [
    { "name": "tree-sitter-ast", "version": "0.26.0", "capability": "AST_HEURISTIC_PARSER" }
  ],
  "fallbacks_applied": [],
  "conflicts_detected": [],
  "data": { ... }
}
```

- **Agent Rule**: Agents consuming JSON MUST extract payload from `.data` while checking `.completeness` and `.providers` to understand if results were inferred via fallback AST heuristics or verified compiler indices.

---

## 3. Agent Workflows & Decision Protocols

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

### Workflow D: Compiler Index Ingestion (SCIP)
1. For projects with TypeScript, Go, Java, Rust, or Python where exact cross-file types/definitions are required:
2. Run `sot import-scip <path_to_index.scip> --provider-version <version>`.
3. SOT-Graph atomically stores SCIP occurrences and definitions into the `provider_evidence` ledger under single-writer write-lock.

### Workflow E: Token-Bounded Subagent Context Handoff
1. When delegating multi-file tasks to subagents (`task` / `worker`), avoid raw sequential file reads.
2. Run `sot pack "<symbol>" --tokens 1500 --json` (or `xd://sot_pack`).
3. SOT-Graph packs 1-hop callers, 2-hop callees, and type dependencies with physical line hash validation and hard token bounding ($\le 5\%$ error margin).

### Workflow F: Disk Drift & Self-Healing
1. If files are modified, created, or deleted during edits:
   - Run `sot reconcile` (or native tool `xd://sot_reconcile`).
   - SOT-Graph performs atomic content-hash rehoming in 1 transaction without losing edge relationships.
2. Periodically verify graph health with `sot doctor`.

### Workflow G: Symbol & God Node Auditing (Zero Blind Discovery)
1. When asked to audit, inspect, or understand God Nodes, Classes, or Modules:
   - **Step 1 (Graph Query):** Run `sot explore "<symbol>" --depth 2` or `sot usages "<symbol>"` (or inspect `.sot/bundle/` fact files). Extract method inventories, callers, and blast radius instantly (0.1s).
   - **Step 2 (Zero Blind File Discovery):** Do NOT spawn Scouts to run `glob`/`grep` across the repository when `sot.db` exists.
   - **Step 3 (Pinpointed Range Reads):** Scouts MUST ONLY read exact line numbers (`file:start-end`) for methods requiring deep body logic verification.

---

## 4. CLI & Native Tool Device Reference

| Category | CLI Command | Native Tool Device | Description |
| :--- | :--- | :--- | :--- |
| **Search Codebase** | `sot search "<query>" [-n 5] [--json]` | `xd://sot_search` | Pure-read verified AST symbol & knowledge search with North-Star envelope |
| **Repository Map** | `sot map [--focus <areas>] [--tokens 1024]` | `xd://sot_map` | PageRank-ranked repository architecture map |
| **Trace Call Graph** | `sot explore "<symbol>" [--depth 2] [--json]` | `xd://sot_explore` | 2-Hop Compass call graph with in-degree collapsing & envelope |
| **Inspect Usages** | `sot usages "<symbol>" [--json]` | `xd://sot_usages` | Honest call-site inspection with pending candidate tracking & envelope |
| **Import SCIP Index**| `sot import-scip <path> [--provider-version v1]`| CLI | Ingest compiler-backed SCIP index into multi-provider evidence ledger |
| **Implementations** | `sot implementations "<interface>"` | `xd://sot_implementations` | Traversal of concrete class & interface implementations |
| **Rename Impact** | `sot rename "<symbol>" [--to <new_name>]` | `xd://sot_rename` | Safe structural symbol rename blast radius planning |
| **Pack Subgraph** | `sot pack "<symbol>" [--tokens 1500] [--json]`| `xd://sot_pack` | Hard-budget live-verified ContextBundle packaging (YAML / JSON) |
| **Synchronize DB** | `sot reconcile [--workers 4] [--force]` | `xd://sot_reconcile` | Atomic single-writer hash-based self-healing & schema v5 sync |
| **Batch Reconcile** | `sot batch-reconcile <dir> [--workers 4]` | CLI | Parallel directory reconciliation for monorepos |
| **Audit Drift** | `sot verify [--deep]` | `xd://sot_verify` | Read-only disk drift audit |
| **Database Doctor** | `sot doctor [--json]` | `xd://sot_doctor` | PRAGMA quick_check, foreign keys, schema v5 health & page count |
| **Clean Stale Data**| `sot clean [--all] [--include-notes]` | `xd://sot_clean` | Purge unreferenced nodes (user notes preserved by default) |
| **Vacuum Database** | `sot vacuum [--analyze]` | `xd://sot_vacuum` | SQLite freelist compaction with WAL checkpointing |
| **Store Note** | `sot insert --title "..." --body "..."` | `xd://sot_insert` | Persistent knowledge recording preserved across index resets |
| **Cluster Graph** | `sot cluster [--scope <path>]` | `xd://sot_cluster` | Louvain / Label Propagation community detection with Newman-Girvan Q |
| **Architecture Report** | `sot report [-o GRAPH_REPORT.md]` | `xd://sot_report` | God Node detection & modularity assessment |
| **Interactive Viz** | `sot viz [-o graph.html]` | `xd://sot_viz` | Standalone interactive D3.js knowledge graph visualizer |
| **Export Graph** | `sot export -f <graphrag/obsidian/scip>` | `xd://sot_export` | Export to GraphRAG JSON, Obsidian vault, SCIP |
| **Fact Bundler** | `sot bundle [-o .sot/bundle/]` | `xd://sot_bundle` | Extract 5 fact files for LLM architecture reports (confined path) |
| **Full-Stack Trace** | `sot trace "<target>" [--depth 2]` | `xd://sot_trace` | End-to-end full-stack call & data flow trace |
| **UI Decision Tree** | `sot ui-tree "<component>"` | `xd://sot_ui_tree` | Hierarchical frontend component & state decomposition |
| **Backend Flow** | `sot be-flow "<service>"` | `xd://sot_backend_flow` | Service-to-database transaction flow extraction |
| **Feature Inventory** | `sot solution inventory [module]` | `xd://sot_solution_inventory` | Stage-1 feature cataloging for Solution Docs |
| **Micro-steps Decompose** | `sot solution steps "<method>"` | `xd://sot_solution_steps` | Granular AST execution step decomposition |
| **Solution Bundle** | `sot solution bundle [module]` | `xd://sot_solution_bundle` | Complete ContextBundle extraction for downstream docs |
