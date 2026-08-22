# In-Depth Architectural Comparison: GitNexus vs sot-graph

> **Architectural Appraisal & Feature-by-Feature Evaluation**  
> *Authored as an independent Architectural Advisor & Reviewer appraisal based on source code analysis, technical specifications, and production operational histories of both systems.*

---

## 📑 Table of Contents
1. [Executive Verdict](#1-executive-verdict)
2. [Direct Comparison Matrix (8 Architectural Dimensions)](#2-direct-comparison-matrix-8-architectural-dimensions)
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
5. [Decision Tree: Choosing the Right Tool](#5-decision-tree-choosing-the-right-tool)
6. [Recommended Two-Tier Hybrid Architecture Pattern](#6-recommended-two-tier-hybrid-architecture-pattern)

---

## 🎯 1. Executive Verdict

> **There is no single universal winner because both systems optimize for fundamentally different Objective Functions:**
>
> 1. **`GitNexus` is a Code-Intelligence & Semantic Graph Engine:** Excels at deep Tree-sitter AST extraction, expressive Cypher graph querying, Leiden clustering, execution flow tracing, and rich browser/WASM visualization.
> 2. **`sot-graph` is an Authoritative Trust, Freshness & Operational Governance Layer:** Excels at instantaneous freshness synchronization (Filesystem SSOT), on-disk physical verification at query time to eradicate Phantom Anchors, zero-daemon lightweight SQLite WAL architecture, and strict Read-Only MCP protocol boundaries.

**The Decisive Decision Rule:**  
Do you require **deep semantic relationship analysis (choose GitNexus)**, or do you require **instant physical grounding to ensure AI Agents never hallucinate stale paths (choose sot-graph)**?

---

## 📊 2. Direct Comparison Matrix (8 Architectural Dimensions)

| Dimension | `GitNexus` (TypeScript / Node.js) | `sot-graph` (Python 3.10+ / SQLite) | Architectural Appraisal |
| :--- | :--- | :--- | :--- |
| **1. Design Philosophy & Core Invariants** | **Graph-First Philosophy**: Uses knowledge graphs to explain context, execution flows, and impact to AI agents. Prioritizes semantic depth. | **Filesystem is the Single Source of Truth (SSOT)**: Graph is a disposable, verified projection. Prioritizes freshness and recoverability. | GitNexus wins on **semantic depth**. sot-graph wins on **freshness and self-healing reliability**. |
| **2. Storage & Database Engine** | Embedded **LadybugDB** (formerly KùzuDB native/WASM). Property Graph model with Cypher queries. Stored in `.gitnexus/lbug`. | In-process **SQLite WAL + FTS5** inverted index. `synchronous=NORMAL`, 5s busy timeout. Stored in `.sot/sot.db`. | GitNexus wins on **natural graph query expressiveness**. sot-graph wins on **zero-daemon simplicity and zero external build dependencies**. |
| **3. Ingestion & Reconciliation** | Multi-stage pipeline: Tree-sitter AST $\rightarrow$ Scope resolution $\rightarrow$ Call chain $\rightarrow$ Leiden clustering. `analyze` / `augment` triggers. | $O(N)$ metadata scan $\rightarrow$ fast dirty check $\rightarrow$ SHA-256 validation $\rightarrow$ ProcessPool parsing $\rightarrow$ serialized SQLite commit. | GitNexus extracts richer multi-stage semantics. sot-graph achieves faster microsecond incremental reconciliation. |
| **4. Fact Grounding & Anti-Hallucination** | Relies on AST graph state generated at parse time. No active on-disk physical validation at search time. | **Active on-disk verification at query time** (`verifier.py`). Emits 5 authoritative verdicts: `[STRONG]`, `[WEAK]`, `[REBUILT]`, `[REMOVED]`, `[NOPATH]`. | **sot-graph decisively wins on anti-hallucination**. Automatically heals moved paths (`Auto-Rehome`) and purges dead paths. |
| **5. Query, Traversal & Graph Analytics** | Expressive **Cypher queries**, execution flow tracing, call hierarchies, **Leiden clustering**, dynamic impact assessment. | **FTS5 BM25** candidate lookup ($< 1.2\text{ms}$), BFS traversal, **Louvain / Modularity $Q$**, **God Node** ($\mu + 1.5\sigma$), and 2-hop Blast Radius. | GitNexus wins on **deep recursive graph queries**. sot-graph is optimized for **sub-millisecond lexical search combined with shallow boundary checks**. |
| **6. Agent Integration & MCP Protocol** | Full MCP tools (`query`, `explore`, `impact`, `context`). Provides `PreToolUse` / `PostToolUse` hooks to enrich agent context. | MCP Stdio Server in **Strictly Read-Only Mode** (5 tools, 2 resources). Enforces hard timeouts and payload caps (256KB, depth 4). | GitNexus provides a **richer autonomous agent loop**. sot-graph provides **safer, non-blocking operational boundaries**. |
| **7. Multi-Language & Visualization** | Comprehensive Tree-sitter grammars (12+ languages: TS/JS, Python, Go, Rust, Java, C/C++, C#, Ruby, PHP, Swift...). Interactive WASM Web UI. | In-process AST parsers for major language families (Python, Go, Rust, TS/JS, Java, C/C++...). Multi-format export: **HTML D3.js, GraphRAG JSON, Obsidian, GraphML**. | GitNexus wins on **AST parsing breadth**. sot-graph wins on **independent, open export format versatility**. |
| **8. Fault Tolerance & Failure Modes** | Potential file lock contention between MCP Server and Hooks (`#1492`). Native WAL crash risks during multi-repo loads (`#1480`). Requires Node.js bindings. | SQLite single-writer constraint. Disk I/O overhead on massive monorepos. 100% self-healing by deleting DB and re-running `sot reconcile`. | sot-graph has a **smaller, deterministic failure blast radius**. GitNexus is more expressive but requires strict process lifecycle management. |

---

## 🔬 3. Detailed Dimensional Analysis

### Dimension 1: Design Philosophy & Invariants
- **GitNexus:** Treats the code property graph as the primary entity. Indexes call chains, type hierarchies, and module boundaries into graph relationships. Ideal for answering *"How does data flow through this system?"*
- **sot-graph:** Treats the physical filesystem as the only unassailable reality. The SQLite database is treated as an ephemeral index that can be destroyed and reconstructed from scratch at any moment.

### Dimension 2: Storage & Database Engine
- **GitNexus:** Leverages LadybugDB (embedded property graph DB) enabling flexible Cypher queries (`MATCH (f:Function)-[:CALLS]->(g) RETURN g`). Requires platform-specific binary bindings.
- **sot-graph:** Built entirely on standard library CPython `sqlite3` configured with Write-Ahead Logging (`PRAGMA journal_mode=WAL;`). Pure Python, zero native compilation flags, zero platform-specific binaries.

### Dimension 3: Ingestion & Reconciliation Pipeline
- **GitNexus:** Executes an end-to-end AST resolution pipeline. Provides `gitnexus augment` to incrementally index diffs and keep the graph updated.
- **sot-graph:** Employs an $O(1)$ **Fast Dirty Check** comparing `(size, mtime_ms)`. If metadata matches, parsing is bypassed entirely. When dirty, uses a bounded `ProcessPoolExecutor` for parsing and commits atomically through a serialized SQLite coordinator.

### Dimension 4: Fact Grounding & Anti-Hallucination
- **GitNexus:** Queries return graph nodes as parsed during the last index run. If a file was renamed or deleted without triggering `augment`, the agent may receive a stale path.
- **sot-graph:** Every search candidate is intercepted by `verifier.py`:
  - If the file exists and content matches: emits `[STRONG]`.
  - If the file was moved: executes `Auto-Rehome` by scanning project basenames, updates SQLite, and returns `[REBUILT]`.
  - If the file was deleted: executes `Auto-Purge`, deletes the node from SQLite, and returns `[REMOVED]`.

### Dimension 5: Query, Traversal & Graph Analytics
- **GitNexus:** Features rich graph analysis tools including execution flow tracking, call hierarchy tracing, and Leiden community detection.
- **sot-graph:** Integrates SQLite FTS5 with BM25 ranking for sub-millisecond lexical search, combined with Louvain community detection (Modularity $Q$), Cohesion scores ($C$), and automated God Node detection ($\mu + 1.5\sigma$) with 2-hop Blast Radius calculations.

### Dimension 6: Agent Integration & MCP Protocol
- **GitNexus:** Highly automated integration with Claude Code and Codex via CLI hooks (`PreToolUse` and `PostToolUse`) that automatically enrich prompts with graph context.
- **sot-graph:** Exposes a standard MCP Stdio Server operating in **Strictly Read-Only Mode** (`mode=ro`). Guarantees that concurrent agent queries can never corrupt or lock the database.

### Dimension 7: Multi-Language & Visualization
- **GitNexus:** Extensive multi-language support powered by Tree-sitter grammars and an interactive WebAssembly UI for in-browser graph exploration.
- **sot-graph:** Multi-language extraction engine supporting major languages, with built-in export to standalone D3.js HTML, GraphRAG JSON, Obsidian Markdown vaults (with `[[wikilinks]]`), and GraphML.

### Dimension 8: Fault Tolerance & Operational Failure Modes
- **GitNexus (Known Failure Modes):**
  - Lock contention on `.gitnexus/lbug` when Hooks and MCP Server access the database concurrently (`Issue #1492`).
  - Native segfault/crash risks during multi-repository concurrent serving (`Issue #1480`).
  - WAL corruption risks on abrupt process termination (`Issue #1402`, `#1361`).
- **sot-graph (Known Constraints):**
  - SQLite single-writer constraint requires mutation tasks to be serialized through the Coordinator.
  - Full-tree SHA-256 verification on massive monorepos (> 50,000 files) is bounded by disk I/O throughput.
  - BFS graph traversal currently queries nodes sequentially, which is not designed for 10–15 hop recursive graph queries.

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

## 🌲 5. Decision Tree: Choosing the Right Tool

```
                       WHAT DOES YOUR SYSTEM REQUIRE?
                                      │
        ┌─────────────────────────────┴─────────────────────────────┐
        ▼                                                           ▼
[ DEEP GRAPH INTELLIGENCE ]                                 [ GROUNDED REALITY & SAFETY ]
• Complex Cypher graph queries.                             • Agents hallucinate stale/dead paths.
• Tracing deep execution call flows.                        • Frequent refactoring, renames, and moves.
• Polyglot monorepos (C#, Ruby, Swift...).                  • Zero-daemon architecture (< 25MB RAM).
• In-browser interactive WASM visualization.                • Storing ADRs & bug notes (`sot insert`).
        │                                                           │
        ▼                                                           ▼
 CHOOSE GITNEXUS                                             CHOOSE SOT-GRAPH
```

---

## 🏛️ 6. Recommended Two-Tier Hybrid Architecture Pattern

For engineering teams seeking both deep semantic exploration and strict execution safety:

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
                                                    │   (Executes 100% Safe Modifications)    │
                                                    └─────────────────────────────────────────┘
```

1. **Tier 1 (GitNexus - Exploration Plane):** Used during the scoping and architectural design phase to map complex cross-module dependencies and visualize execution flows.
2. **Tier 2 (sot-graph - Grounding & Execution Gatekeeper):** Before the AI Agent applies edits or generates patches, `sot-graph` performs on-disk physical verification, auto-rehoming moved files (`[REBUILT]`) or purging deleted paths (`[REMOVED]`) to guarantee zero broken patches.

---

## 📄 License
MIT License. Copyright (c) 2026 Minh Giap.
