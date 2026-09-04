# In-Depth Architectural Comparison: GitNexus vs sot-graph

> **Objective Technical Comparison & Feature Evaluation**  
> *Comparative engineering analysis based on source code architectures, storage data models, operational trade-offs, and failure mode profiles of both systems.*

---

## 📑 Table of Contents
1. [Architectural Overview](#1-architectural-overview)
2. [Technical Comparison Matrix (8 Architectural Dimensions)](#2-technical-comparison-matrix-8-architectural-dimensions)
3. [Detailed Dimensional Analysis](#3-detailed-dimensional-analysis)
   - [Dimension 1: Design Philosophy & Invariants](#dimension-1-design-philosophy--invariants)
   - [Dimension 2: Storage & Database Engine](#dimension-2-storage--database-engine)
   - [Dimension 3: Ingestion & Reconciliation Pipeline](#dimension-3-ingestion--reconciliation-pipeline)
   - [Dimension 4: Fact Grounding & Anti-Hallucination](#dimension-4-fact-grounding--anti-hallucination)
   - [Dimension 5: Query, Traversal & Graph Analytics](#dimension-5-query-traversal--graph-analytics)
   - [Dimension 6: Agent Integration & MCP Protocol](#dimension-6-agent-integration--mcp-protocol)
   - [Dimension 7: Multi-Language & Visualization](#dimension-7-multi-language--visualization)
   - [Dimension 8: Fault Tolerance & Operational Failure Modes](#dimension-8-fault-tolerance--operational-failure-modes)
4. [Token Economics & Operational Efficiency](#4-token-economics--operational-efficiency)
5. [Decision Matrix: Choosing the Right Tool](#5-decision-matrix-choosing-the-right-tool)
6. [Two-Tier Hybrid Architecture Pattern](#6-two-tier-hybrid-architecture-pattern)

---

## 🎯 1. Architectural Overview

> **Both systems optimize for fundamentally different engineering objective functions:**
>
> 1. **`GitNexus` is a Code-Intelligence & Semantic Graph Engine:** Focuses on deep Tree-sitter AST extraction, expressive Cypher graph querying via LadybugDB, Leiden community clustering, execution flow tracing, and client-side browser/WASM visualization.
> 2. **`sot-graph` is a Trust, Freshness & Operational Governance Layer:** Focuses on instantaneous freshness synchronization (Filesystem SSOT), on-disk physical verification at query time to eliminate phantom anchors, a zero-daemon embedded SQLite WAL architecture, and strict Read-Only MCP protocol boundaries.

**Core Architectural Distinction:**  
- **GitNexus** is designed for **deep semantic relationship analysis and call graph exploration**.
- **sot-graph** is designed for **real-time physical grounding and self-healing index synchronization**.

---

## 📊 2. Technical Comparison Matrix (8 Architectural Dimensions)

| Dimension | `GitNexus` (TypeScript / Node.js) | `sot-graph` (Python 3.10+ / SQLite) | Engineering Trade-offs |
| :--- | :--- | :--- | :--- |
| **1. Design Philosophy & Core Invariants** | **Graph-First Philosophy**: Uses knowledge graphs to model context, execution flows, and impact. Prioritizes semantic graph depth. | **Filesystem is the Single Source of Truth (SSOT)**: Graph is a disposable, verified projection of disk state. Prioritizes freshness and instant recoverability. | GitNexus emphasizes **semantic depth**. sot-graph emphasizes **freshness and self-healing reliability**. |
| **2. Storage & Database Engine** | Embedded **LadybugDB** (formerly KùzuDB native/WASM). Property Graph model with Cypher queries. Stored in `.gitnexus/lbug`. | In-process **SQLite WAL + FTS5** inverted index. `synchronous=NORMAL`, 5s busy timeout. Stored in `.sot/sot.db`. | GitNexus enables **declarative graph querying via Cypher**. sot-graph ensures **zero-daemon simplicity and zero external compilation dependencies**. |
| **3. Ingestion & Reconciliation** | Multi-stage pipeline: Tree-sitter AST → Scope resolution → Call chain → Leiden clustering. `analyze` / `augment` triggers. | O(N) metadata scan → fast dirty check → SHA-256 validation → ProcessPool parsing → serialized SQLite commit. | GitNexus extracts richer multi-stage AST semantics. sot-graph achieves lower-latency incremental reconciliation via metadata dirty checking. |
| **4. Fact Grounding & Anti-Hallucination** | Relies on AST graph state generated at parse time. No active on-disk physical validation at search time. | **Active on-disk verification at query time** (`verifier.py`). Emits 5 trust verdicts: `[STRONG]`, `[WEAK]`, `[REBUILT]`, `[REMOVED]`, `[NOPATH]`. | sot-graph provides **active on-disk verification**, automatically healing moved paths (`Auto-Rehome`) and purging dead paths (`Auto-Purge`). |
| **5. Query, Traversal & Graph Analytics** | Expressive **Cypher queries**, execution flow tracing, call hierarchies, **Leiden clustering**, dynamic impact assessment. | **FTS5 BM25** candidate lookup (< 1.2ms), BFS traversal, **Louvain / Modularity Q**, **God Node** (μ + 1.5σ), and 2-hop Blast Radius. | GitNexus is optimized for **deep recursive graph queries**. sot-graph is optimized for **sub-millisecond lexical search and shallow boundary diagnostics**. |
| **6. Agent Integration & MCP Protocol** | Full MCP tools (`query`, `explore`, `impact`, `context`). Provides `PreToolUse` / `PostToolUse` hooks to enrich agent context. | MCP Stdio Server in **Strictly Read-Only Mode** (5 tools, 2 resources). Enforces hard timeouts and payload caps (256KB, depth 4). | GitNexus provides **automated prompt hook enrichment**. sot-graph enforces **deterministic, non-blocking operational boundaries**. |
| **7. Multi-Language & Visualization** | Comprehensive Tree-sitter grammars (12+ languages: TS/JS, Python, Go, Rust, Java, C/C++, C#, Ruby, PHP, Swift...). Interactive WASM Web UI. | In-process AST parsers for major language families (Python, Go, Rust, TS/JS, Java, C/C++...). Multi-format export: **HTML D3.js, GraphRAG JSON, Obsidian, GraphML**. | GitNexus provides **broader native Tree-sitter grammar coverage**. sot-graph provides **multi-format open export capabilities (HTML, GraphRAG, Obsidian, GraphML)**. |
| **8. Fault Tolerance & Failure Modes** | Potential file lock contention between MCP Server and Hooks (`#1492`). Native WAL crash risks during multi-repo loads (`#1480`). Requires Node.js bindings. | SQLite single-writer constraint. Disk I/O overhead on massive monorepos. Full rebuild recovery by deleting DB and re-running `sot reconcile`. | sot-graph has a **smaller failure blast radius** due to disposable index design. GitNexus provides higher expressiveness with higher process runtime requirements. |

---

## 🔬 3. Detailed Dimensional Analysis

### Dimension 1: Design Philosophy & Invariants
- **GitNexus:** Treats the code property graph as the primary entity. Indexes call chains, type hierarchies, and module boundaries into graph relationships. Suitable for answering queries about multi-step execution flows across packages.
- **sot-graph:** Treats the physical filesystem as the only ground truth. The SQLite database is an ephemeral, disposable index that can be dropped and reconstructed from source files at any time.

### Dimension 2: Storage & Database Engine
- **GitNexus:** Leverages LadybugDB (embedded property graph DB) enabling flexible Cypher queries (`MATCH (f:Function)-[:CALLS]->(g) RETURN g`). Requires platform-specific binary bindings.
- **sot-graph:** Built entirely on standard library CPython `sqlite3` configured with Write-Ahead Logging (`PRAGMA journal_mode=WAL;`). Pure Python, zero native compilation flags, zero platform-specific binaries.

### Dimension 3: Ingestion & Reconciliation Pipeline
- **GitNexus:** Executes an end-to-end AST resolution pipeline. Provides `gitnexus augment` to incrementally index diffs and keep the graph updated.
- **sot-graph:** Employs an O(1) **Fast Dirty Check** comparing `(size, mtime_ms)`. If metadata matches, parsing is bypassed entirely. When dirty, uses a bounded `ProcessPoolExecutor` for parsing and commits atomically through a serialized SQLite coordinator.

### Dimension 4: Fact Grounding & Anti-Hallucination
- **GitNexus:** Queries return graph nodes as parsed during the last index run. If a file was renamed or deleted without triggering `augment`, query results may reference stale paths.
- **sot-graph:** Every search candidate is intercepted by `verifier.py`:
  - If the file exists and content matches: emits `[STRONG]`.
  - If the file was moved: executes `Auto-Rehome` by scanning project basenames, updates SQLite, and returns `[REBUILT]`.
  - If the file was deleted: executes `Auto-Purge`, deletes the node from SQLite, and returns `[REMOVED]`.

### Dimension 5: Query, Traversal & Graph Analytics
- **GitNexus:** Features rich graph analysis tools including execution flow tracking, call hierarchy tracing, and Leiden community detection.
- **sot-graph:** Integrates SQLite FTS5 with BM25 ranking for sub-millisecond lexical search, combined with Louvain community detection (Modularity Q), Cohesion scores (C), and automated God Node detection (μ + 1.5σ) with 2-hop Blast Radius calculations.

### Dimension 6: Agent Integration & MCP Protocol
- **GitNexus:** Automated integration with Claude Code and Codex via CLI hooks (`PreToolUse` and `PostToolUse`) that automatically enrich prompts with graph context.
- **sot-graph:** Exposes a standard MCP Stdio Server operating in **Strictly Read-Only Mode** (`mode=ro`). The tool surface is read-only by construction, so concurrent agent queries cannot lock or corrupt the database through MCP.

### Dimension 7: Multi-Language & Visualization
- **GitNexus:** Extensive multi-language support powered by Tree-sitter grammars and an interactive WebAssembly UI for in-browser graph exploration.
- **sot-graph:** Multi-language extraction engine supporting major languages, with built-in export to standalone D3.js HTML, GraphRAG JSON, Obsidian Markdown vaults (with `[[wikilinks]]`), and GraphML.

### Dimension 8: Fault Tolerance & Operational Failure Modes
- **GitNexus (Operational Considerations):**
  - Lock contention on `.gitnexus/lbug` when Hooks and MCP Server access the database concurrently (`Issue #1492`).
  - Native segfault/crash risks during multi-repository concurrent serving (`Issue #1480`).
  - WAL corruption risks on abrupt process termination (`Issue #1402`, `#1361`).
- **sot-graph (Operational Constraints):**
  - SQLite single-writer constraint requires mutation tasks to be serialized through the Coordinator.
  - Full-tree SHA-256 verification on massive monorepos (> 50,000 files) is bounded by disk I/O throughput.
  - BFS graph traversal currently queries nodes sequentially, optimized for bounded hop traversal rather than deep recursive queries.

---

## 💰 4. Token Economics & Operational Efficiency

| Evaluation Metric | `GitNexus` | `sot-graph` |
| :--- | :--- | :--- |
| **Operational LLM Token Overhead** | **0 Tokens** (Runs Tree-sitter & LadybugDB locally) | **0 Tokens** (Runs AST, SQLite FTS5 & Python locally) |
| **Search Query Latency** | ~5 – 15 ms (Graph DB Cypher lookup) | **1.17 ms P95** (SQLite FTS5 BM25) |
| **Reconcile Speed (100 files)** | Dependent on hook scope / full `analyze` | **~24.1 ms** (with Fast Dirty Check) |
| **Memory Footprint (RAM RSS)** | ~80 – 250 MB (Node.js runtime + native engine) | **< 25 MB** (Embedded SQLite WAL) |
| **External Dependencies** | Node.js, LadybugDB/KùzuDB binaries | **Zero external dependencies** (CPython 3.10+ stdlib) |

---

## 🌲 5. Decision Matrix: Choosing the Right Tool

```
                       SYSTEM REQUIREMENTS BREAKDOWN
                                      │
        ┌─────────────────────────────┴─────────────────────────────┐
        ▼                                                           ▼
[ DEEP GRAPH INTELLIGENCE ]                                 [ GROUNDED REALITY & REPRODUCIBILITY ]
• Complex Cypher graph queries.                             • Risk of agents referencing stale/dead paths.
• Tracing deep recursive call flows.                        • Frequent refactoring, renames, and moves.
• Polyglot monorepos (C#, Ruby, Swift...).                  • Zero-daemon architecture (< 25MB RAM).
• In-browser interactive WASM visualization.                • Storing ADRs & bug notes (`sot insert`).
        │                                                           │
        ▼                                                           ▼
 USE GITNEXUS                                                USE SOT-GRAPH
```

---

## 🏛️ 6. Two-Tier Hybrid Architecture Pattern

Engineering teams can combine both systems into a complementary two-tier pipeline:

```
                      ┌─────────────────────────────────────────┐
                      │           PROJECT CODEBASE              │
                      └─────────────────────────────────────────┘
                                           │
         ┌─────────────────────────────────┴─────────────────────────────────┐
         │                                                                   │
         ▼                                                                   ▼
┌─────────────────────────────────────────┐         ┌─────────────────────────────────────────┐
│     TIER 1: GITNEXUS EXPLORATION        │         │       TIER 2: SOT-GRAPH GATEKEEPER      │
│  (Deep Architecture & Semantic Plane)   │         │    (Trust & Freshness Safety Gate)      │
├─────────────────────────────────────────┤         ├─────────────────────────────────────────┤
│ • Cypher queries & Call Chains          │         │ • Fast Dirty Check (< 25ms reconcile)   │
│ • Leiden functional clustering          │ ──────> │ • Physical on-disk verification         │
│ • Rich execution flow analysis          │         │ • [STRONG] / [WEAK] / [REBUILT] labels  │
│ • Interactive Web UI visualization      │         │ • Auto-Rehome & Auto-Purge mechanisms   │
└─────────────────────────────────────────┘         └─────────────────────────────────────────┘
                                                                         │
                                                                         ▼
                                                    ┌─────────────────────────────────────────┐
                                                    │            AI CODING AGENT              │
                                                    │   (Executes Grounded Modifications)     │
                                                    └─────────────────────────────────────────┘
```

1. **Tier 1 (GitNexus - Exploration Plane):** Used during scoping and architectural design to map complex cross-module dependencies and visualize execution flows.
2. **Tier 2 (sot-graph - Grounding & Execution Gatekeeper):** Before an AI Agent applies edits or generates patches, `sot-graph` performs on-disk physical verification, auto-rehoming moved files (`[REBUILT]`) or purging deleted paths (`[REMOVED]`) to prevent invalid file operations.

---

## 📄 License
MIT License. Copyright (c) 2026 Minh Giap.
