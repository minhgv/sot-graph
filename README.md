# sot-graph (Single Source of Truth Knowledge Graph)

> **Verified, self-healing knowledge layer for AI coding agents and codebases.**
> *Filesystem is the Single Source of Truth — The knowledge graph is an authoritative, verified projection of reality. Zero external daemons required.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](pyproject.toml)
[![SQLite: WAL + FTS5](https://img.shields.io/badge/SQLite-FTS5%20%2B%20WAL-orange.svg)](src/sot_graph/db.py)
[![Tests: 31 passed](https://img.shields.io/badge/Tests-31%2F31%20Passed-brightgreen.svg)](tests/)
[![Architecture: Zero--Daemon](https://img.shields.io/badge/Architecture-Zero--Daemon-purple.svg)](#-architecture-overview)
[![Q&A Guide: 19 Scenarios](https://img.shields.io/badge/Q%26A%20Guide-19%20Scenarios%20Docs-blueviolet.svg)](docs/QA_GUIDE.md)
[![AI SDLC Guide](https://img.shields.io/badge/AI%20SDLC%20Guide-6%20Phases-success.svg)](docs/AI_SDLC_GUIDE.md)
[![GitNexus vs sot-graph](https://img.shields.io/badge/Comparison-GitNexus%20vs%20sot--graph-orange.svg)](docs/GITNEXUS_VS_SOT_GRAPH.md)

---

## 🎯 Purpose & The Core Problem

Traditional RAG and agent memory systems suffer from **"Phantom Anchors, Stale Context, and Dead Paths"**:

1. **Hallucinated Locations**: When files are deleted, renamed, or refactored, the agent's memory continues pointing at old paths. The agent acts on non-existent code, wasting prompt tokens and generating broken patches.
2. **Cold Start Redundancy**: Every AI coding session starts cold. Grep across repos cannot easily answer *"Did I already solve this in another project?"*, resulting in developers rebuilding the exact same utility three times.
3. **Heavy Daemon Bottlenecks**: Many graph tools require heavy background daemons (Neo4j, vector servers, background Node runtimes) that fail silently, consume gigabytes of RAM, or drop writes under high concurrency.

**`sot-graph` solves this at the architectural root:**
- **Filesystem Chokepoint**: A hint (file watcher, hook, or CLI) can only say *"look at this path"*. It is never believed about what happened. The reconciler reads the actual file from disk to make the graph match.
- **Trust-Verified Search**: Every search result is **verified against disk reality** before the agent sees it. If a path is dead, it is purged immediately; if it was moved, it is auto-healed.
- **Single-Writer Concurrency**: A single SQLite WAL database handles dirty tracking via SHA-256 generation counters. Multiple concurrent agents editing files will always converge to the exact same state without race conditions.
- **Pure Zero-Daemon Footprint**: Runs completely in-process using standard Python 3.10+ and embedded SQLite ($< 25\text{MB}$ RAM).

---

## 🛡️ The Trust Verdict System

When an agent searches the knowledge base via `sot search "<query>"`, every candidate node is evaluated in real-time by the **Trust Verification Engine** (`sot_graph.verifier`):

```
                       [ Search Query / Symbol ]
                                   │
                                   ▼
                   [ SQLite FTS5 (BM25 Retrieval) ]
                                   │
                                   ▼
                   ┌───────────────────────────────┐
                   │   Trust Verification Engine   │
                   └───────────────┬───────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
   [ File Exists? ]         [ Content Coverage ]      [ File Missing? ]
   ├── Yes (Coverage >= 50%) ➔ [STRONG]              ├── Unique Basename Match?
   ├── Yes (Coverage < 50%)  ➔ [WEAK]                │   ├── Yes ➔ Auto-Heal [REBUILT]
   └── No Disk File Attached ➔ [NOPATH]              │   └── No  ➔ Auto-Purge [REMOVED]
```

| Verdict | Meaning | Agent Action |
| :--- | :--- | :--- |
| `[STRONG]` | **Path physically exists on disk AND actual content contains ≥ 50% query tokens.** | **High Confidence**: Go straight to the referenced file and line number. |
| `[WEAK]` | **Semantic/Title match only; low lexical overlap in file content.** | **Caution**: Plausible hit; verify file context manually before editing. |
| `[REBUILT]` | **File was moved/renamed in project.** | **Auto-Healed**: Discovered by basename scan; path automatically updated in database. |
| `[REMOVED]` | **Path permanently deleted from disk.** | **Auto-Purged**: Node deleted from database so it never ranks again. |
| `[NOPATH]` | **Virtual knowledge note (architecture decisions, rules).** | **Knowledge Anchor**: Treat as documented guideline. |

---

## 📚 Complete Documentation & Deep-Dive Guides

Explore comprehensive architectural analyses, real-world agent integration guides, and operational comparisons:

- 📖 **[Comprehensive Q&A Guide (`docs/QA_GUIDE.md`)](docs/QA_GUIDE.md)** — 19 detailed real-world scenarios covering self-healing, anti-hallucination mechanics, and graph analytics.
- 🚀 **[AI-Assisted SDLC Guide (`docs/AI_SDLC_GUIDE.md`)](docs/AI_SDLC_GUIDE.md)** — Deep-dive into applying `sot-graph` across all 6 phases of software development, eliminating Cold Start Redundancy and constraining Blast Radius.
- ⚖️ **[Architectural Comparison: GitNexus vs sot-graph (`docs/GITNEXUS_VS_SOT_GRAPH.md`)](docs/GITNEXUS_VS_SOT_GRAPH.md)** — Independent 8-dimensional architectural appraisal, failure mode audit, and optimal two-tier hybrid architecture pattern.
- ⚡ **[Interactive Standalone HTML Guide (Live Demo on GitHub)](https://htmlpreview.github.io/?https://github.com/minhgv/sot-graph/blob/main/sot_qa_guide.html)** — Instant search, category filters, and 1-click code copying.
- 💻 **Offline Local Browser View**:
  ```bash
  open sot_qa_guide.html        # macOS
  xdg-open sot_qa_guide.html    # Linux
  ```

### 🌟 6 Core Topic Areas Covered in Depth:
1. **Core Architecture & Anti-Hallucination**: Filesystem SSOT, Fast Dirty Check metadata ($O(1)$) + SHA-256 hashing, Trust Verdict classification (`[STRONG]`, `[WEAK]`, `[REBUILT]`, `[REMOVED]`), and atomic 2-way pending edge resolution in SQL.
2. **Self-Healing & Data Integrity**: Automatic path purging upon file deletion (`rm`), automatic rehoming on file moves/renames (`mv`), and Atomic Full-File Replacement to prevent stale node accumulation.
3. **AI Agent Integration & MCP**: Extension setup for Oh My Pi (`omp_extension.ts`), agent configuration for Claude Code/Cursor (`AGENTS.md`), 5 Read-Only MCP Stdio tools, and the 4-step Knowledge Reuse Protocol.
4. **Graph Analytics & Visualizations**: God Node detection algorithms ($\mu + \text{threshold\_sigma} \times \sigma$) with 2-hop Blast Radius, Louvain community detection / Modularity ($Q$), and multi-format exporters (Interactive HTML D3.js, GraphRAG JSON, Obsidian Vault, GraphML).
5. **Operations, Maintenance & Performance**: Safe pruning via `sot clean` & defragmentation via `sot vacuum` (with safe `--dry-run` modes), non-mutating CI/CD drift audits (`sot verify --deep`), and latency benchmarks ($< 25\text{ms}$ / 100 files, RAM $< 25\text{MB}$).
6. **Edge Cases & Incident Handling**: Ambiguity Guard against basename collisions across directories, syntax error fault tolerance during parsing, and persisting Architectural Decision Records (ADRs) with `sot insert`.
---

## 🏗️ Architecture Overview

`sot-graph` is built as an 8-layer modular pipeline with zero external daemon requirements:

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                       SOT-GRAPH                                         │
│                 (Verified, Self-Healing Source-of-Truth Knowledge Graph)                │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                             │
      ┌──────────────────────────────────────┼──────────────────────────────────────┐
      ▼                                      ▼                                      ▼
┌───────────────────────────┐  ┌───────────────────────────┐  ┌───────────────────────────┐
│   1. Reconciler Engine    │  │   2. Storage Core (DB)    │  │  3. Trust Verdict Engine  │
│ • Level-triggered sync    │  │ • SQLite WAL + FTS5 (BM25)│  │ • Physical disk validation│
│ • Adaptive pool (<16 seq) │  │ • Chunked SQL (<=500 vars)│  │ • Lexical coverage filter │
│ • SHA-256 dirty check     │  │ • 2-Way pending resolver  │  │ • Bounded auto-rehome     │
│ • Atomic single-writer    │  │ • Degree-bounded BFS walk │  │ • Auto-purge dead paths   │
└───────────────────────────┘  └───────────────────────────┘  └───────────────────────────┘
      │                                      │                                      │
      ├──────────────────────────────────────┼──────────────────────────────────────┤
      ▼                                      ▼                                      ▼
┌───────────────────────────┐  ┌───────────────────────────┐  ┌───────────────────────────┐
│ 4. Multi-Lang AST Parsers │  │ 5. Graph Analytics Core   │  │ 6. Visualizer & Exporters │
│ • Python (native ast)     │  │ • Louvain & Modularity(Q) │  │ • Standalone D3.js HTML   │
│ • TS/JS, Go, Rust, C/C++  │  │ • Community cohesion score│  │ • GraphRAG JSON format    │
│ • Java, Ruby, PHP, Swift  │  │ • God Node (2-hop blast)  │  │ • Obsidian Markdown Vault │
│ • Shell, SQL, Markdown    │  │ • Surprising connections  │  │ • GraphML XML (Gephi/Cyto)│
└───────────────────────────┘  └───────────────────────────┘  └───────────────────────────┘
      │                                                                             │
      └──────────────────────────────────────┬──────────────────────────────────────┘
                                             ▼
                      ┌─────────────────────────────────────────────┐
                      │    7. Agent Protocols & Integrations        │
                      │ • Read-Only MCP Stdio Server (5 tools)      │
                      │ • Oh My Pi / OMP Extension (sot_graph.ts)   │
                      │ • OpenCode Tool Config (opencode_tools.json)│
                      │ • System Prompt Guidance (AGENTS.md)        │
                      │ • Maintenance: sot clean, vacuum, doctor    │
                      └─────────────────────────────────────────────┘
```

---

## ⚙️ Core Subsystems Under the Hood

### 1. Level-Triggered Single-Writer Reconciler (`src/sot_graph/reconciler.py`)
- **Fast Dirty Check**: Compares `size`, `mtime_ms`, and `SHA-256` content hashes. Unchanged files take $< 0.1\text{ms}$ to verify.
- **Adaptive Worker Threshold**: Automatically runs sequential parsing for small batches ($< 16$ files) to eliminate multiprocessing fork overhead, while fanning out to parallel worker pools for large codebases.
- **Atomic Commits**: For any modified file, all old nodes, edges, and pending references owned by that path are deleted and replaced in a single SQLite transaction.
- **Idempotency Guarantee**: Running `sot reconcile` 1 time or 100 times produces the exact same deterministic graph state.

### 2. Two-Way Pending Edge Resolution (`src/sot_graph/db.py`)
In monorepos or multi-file projects, File A often imports a symbol from File B before File B has been indexed.
1. When File A imports `UserService` (not yet indexed), the reference is saved into `pending_edges`.
2. As soon as File B is reconciled and defines `UserService`, `sot-graph` automatically resolves the pending edge into a confirmed directed edge in both directions.
3. Variable batching is chunked to a maximum of 500 parameters to guarantee compatibility across all SQLite versions.

### 3. Graph Analytics & Community Detection (`src/sot_graph/analytics/`)
- **Label Propagation / Louvain Community Detection**: Pure Python graph clustering calculating modularity (Q) and cohesion scores without heavy C-extensions.
- **God Node Detection**: Automatically flags hub nodes exceeding distribution thresholds (μ + threshold_sigma × σ) and calculates their **2-hop Blast Radius**.
- **Surprising Connections**: Identifies cross-cutting architectural relationships spanning across distant modules.
- **Automated Reporting**: Generates a clean, comprehensive `GRAPH_REPORT.md` architecture review.

### 4. Interactive Visualizer & Multi-Format Exporters (`src/sot_graph/export/`)
- **Interactive Standalone HTML (`sot viz`)**: Zero-install D3.js v7 visualizer with force-directed physics, community color palettes, search filtering, node-drag pinning, and detail inspection panels.
- **GraphRAG JSON (`sot export -f graphrag`)**: Hierarchical schema output with nodes, edges, communities, and summary reports ready for Graph RAG pipelines.
- **Obsidian Markdown Vault (`sot export -f obsidian`)**: Complete vault with YAML frontmatter, community tags, and cross-entity Wikilinks `[[...]]`.
- **GraphML XML (`sot export -f graphml`)**: Industry-standard XML graph format compatible with Gephi, Cytoscape, and NetworkX.

---

## 📦 Installation & Getting Started

### Prerequisites
- **Python 3.10+** (Zero external dependencies for core functionality).
- Standard SQLite3 with FTS5 support (included with standard Python builds).

### Quick Setup

```bash
# Clone the repository
git clone https://github.com/minhgv/sot-graph.git
cd sot-graph
chmod +x bin/sot

# Optional: Install MCP dependencies if running MCP stdio server
pip install -e '.[mcp]'
```

---

## 💻 CLI Command Reference

`sot-graph` provides an intuitive, high-performance CLI for development, CI/CD, and agent environments:

```bash
usage: sot [-h] [--root ROOT] [--db DB] {search,explore,insert,reconcile,verify,doctor,clean,vacuum,report,cluster,viz,export,mcp} ...
```

### 1. Codebase Indexing & Synchronization
```bash
# Idempotently sync knowledge graph with filesystem
./bin/sot reconcile

# Custom parallel extraction workers and transaction batch sizes
./bin/sot reconcile --workers 4 --batch-size 64

# Reconcile specific directories or files
./bin/sot reconcile src/ tests/
```

### 2. Trust-Verified Knowledge Search
```bash
# Search verified symbols, functions, classes, and notes
./bin/sot search "Database acquire_connection"

# Scope search to specific subdirectories
./bin/sot search "reconcile" --scope src/sot_graph

# Output structured JSON for scripts and agents
./bin/sot search "TrustVerifier" --json
```

### 3. AST Exploration & Dependency Walk
```bash
# Explore outbound calls and inbound references of a symbol
./bin/sot explore "Reconciler"

# Traverse up to 3 hops deep in the call graph
./bin/sot explore "TrustVerifier" --depth 3
```

### 4. Architectural Reports & Community Clustering
```bash
# Generate comprehensive architectural Markdown report (GRAPH_REPORT.md)
./bin/sot report -o GRAPH_REPORT.md

# Tune God Node standard deviation sensitivity and minimum cluster size
./bin/sot report --sigma 2.0 --min-size 3 -o ARCHITECTURE.md

# Inspect detected functional clusters and cohesion scores
./bin/sot cluster
```

### 5. Interactive Visualization & Multi-Format Exports
```bash
# Generate standalone interactive HTML graph visualizer
./bin/sot viz -o graph.html

# Generate and automatically open in web browser
./bin/sot viz --open

# Export graph for GraphRAG pipelines
./bin/sot export --format graphrag -o graphrag_dataset.json

# Export graph as an Obsidian Markdown Vault
./bin/sot export --format obsidian -o obsidian_vault/

# Export graph as GraphML for Gephi / Cytoscape
./bin/sot export --format graphml -o graph.graphml
```

### 6. Knowledge Notes & Architectural Anchors
```bash
# Record an architectural decision or tricky fix
./bin/sot insert \
  --title "ZRAM Swap Configuration" \
  --body "Set swappiness=180 on low-memory VPS to prevent OOM kills." \
  --keywords "vps,zram,memory"
```

### 7. Drift Auditing & Database Maintenance
```bash
# Check for drift between DB and disk (CI-safe read-only audit)
./bin/sot verify

# Deep verification with full SHA-256 re-hashing
./bin/sot verify --deep

# Check database health and entity counts
./bin/sot doctor

# Dry-run clean stale/missing paths and orphaned edges
./bin/sot clean --dry-run --json

# Apply clean to remove missing files and dead references
./bin/sot clean --all --yes

# Compact and optimize SQLite database and checkpoint WAL
./bin/sot vacuum --analyze
```

---

## 🤖 AI Agent Harness Integrations

### 1. Oh My Pi / OMP Extension (`omp` / `pi`)
Copy the native TypeScript extension to your local agent configuration:
```bash
cp src/sot_graph/adapters/omp_extension.ts ~/.omp/agent/extensions/sot_graph.ts
```
Exposes 4 native agent tools: `sot_search`, `sot_explore`, `sot_reconcile`, `sot_insert`.

### 2. Model Context Protocol (MCP) Stdio Server
Exposes 5 read-only tools and resources over stdio for Claude Desktop, Cursor, and MCP-compatible agents:
- `sot_search`: Trust-verified search with disk validation.
- `sot_explore`: Bounded AST exploration and cross-file relations.
- `sot_verify_drift`: Read-only drift audit between graph and disk.
- `sot_architecture_report`: Complete architectural analysis with God Node detection.
- `sot_communities`: Cluster detection with modularity and cohesion metrics.
- Resources: `sot://stats`, `sot://node/{node_id}`.

```bash
# Run MCP stdio server
./bin/sot mcp
```

### 3. OpenCode & OpenCode V2 (`opencode`)
Include `src/sot_graph/adapters/opencode_tools.json` in your `.opencode.json` configuration to provide subagent workers with direct knowledge tools.

### 4. Claude Code, Cursor, and System Prompts
Include `src/sot_graph/adapters/AGENTS.md` in your workspace's `AGENTS.md` or `.cursorrules` to instruct agents to consult existing verified code before creating redundant files.

---

## ⚡ Benchmarks & Performance

`sot-graph` includes a deterministic benchmark suite across multi-language fixtures (Python, TypeScript, Go, Rust, Markdown):

```bash
# Run Reconcile Benchmark (Worker scaling & throughput)
PYTHONPATH=".:src" python3 -m benchmarks.bench_reconcile --files 100 --repeat 3

# Run Query Latency Benchmark (FTS5 & BM25 retrieval)
PYTHONPATH=".:src" python3 -m benchmarks.bench_query --files 100 --repeat 3
```

### Verified Benchmark Results (Apple M1 Max, 100 files):
- **Full Reconciliation Throughput**: `~24.1ms` (median) for full AST parsing, SHA-256 hashing, and transaction commit.
- **Query Retrieval Latency**: `~1.17ms` (P95) via SQLite FTS5 BM25 index.
- **Memory Footprint**: `< 25MB` RSS during active reconciliation.

---

## ⚖️ Architectural Comparison: `sot-graph` vs `graphify` vs `gitnexus`

| Dimension / Capability | `sot-graph` (This Project) | `graphify` | `gitnexus` |
| :--- | :--- | :--- | :--- |
| **Core Purpose** | Self-healing **Single Source of Truth** knowledge layer for AI Coding Agents in the active filesystem coding loop. | Deep multi-modal knowledge graph builder (Code, Docs, Papers) with architectural reporting and LLM semantic inference. | Client-side zero-server Code Intelligence & MCP tool running in-browser for AST & Git repository exploration. |
| **Source of Truth** | **Filesystem is the absolute truth**. Hints are only triggers; state is physically verified against disk before delivery. | **Input files + LLM inference**. Takes directory snapshots at extraction time and stores static graph JSON. | **Git Repository + Tree-sitter AST**. Indexes Git trees and in-memory call graph relationships. |
| **Anti-Hallucination Mechanism** | **Trust Verdict Engine** (`[STRONG]`, `[WEAK]`, `[REBUILT]`, `[REMOVED]`): Physical disk checks and token coverage filtering at query time. | Transparent link classification (`EXTRACTED` vs `INFERRED` vs `AMBIGUOUS`) with token cost audit trail. | Static Tree-sitter AST parsing; no runtime token coverage verification or physical disk change audits. |
| **Self-Healing Capabilities** | **Automated & Instantaneous**: Auto-detects moved/renamed files (`[REBUILT]`), purges dead paths (`[REMOVED]`), cleans orphan edges. | **Manual / Batch**: Requires re-running `/graphify --update` or full graph rebuild when the codebase changes. | **Session / Manual**: Requires repository re-indexing when new commits or branches are introduced. |
| **Storage & Query Engine** | **SQLite WAL + FTS5 (BM25)**: ACID transactions, SHA-256 generation dirty tracking, sub-millisecond query latency ($< 1.5\text{ms}$). | **JSON (`graph.json`) + Markdown Reports**: Flat files; no embedded relational or property graph database. | **In-memory / IndexedDB / WASM Browser Cache**: Data stored in browser RAM or transient Node.js process memory. |
| **Footprint & Resources** | Ultra-lightweight ($< 25\text{MB}$ RAM), **Zero external dependencies**, parallel multiprocessing (~$20\text{ms}$ / 100 files). | Incurs LLM API token costs when running `--mode deep`; best for periodic documentation rather than per-turn edits. | Dependent on Node.js/browser runtime and RAM scaling when indexing large monorepos. |
| **Clustering & God Nodes** | In-process **Louvain / Modularity ($Q$)**, Cohesion scoring, and **God Node Detection (2-hop blast radius)** with zero daemons. | Built-in **Leiden / Louvain community detection**, Cohesion scoring, and Surprising Connection discovery. | Focuses on visual inheritance, import, and call-chain graphs rather than modularity analysis. |
| **Visualization** | Standalone Interactive HTML D3.js v7 (*force-directed physics*) with community filters and node/edge inspector. | Interactive HTML D3.js + Obsidian Canvas / Vault export and GraphML. | Modern client-side interactive graphical web app running directly in the browser. |
| **Export Formats** | **GraphRAG JSON**, **Obsidian Markdown Vault**, **GraphML XML**, and **Markdown Report**. | **GraphRAG JSON**, **Obsidian Markdown Vault**, **GRAPH_REPORT.md**. | Primarily targets internal MCP stdio/SSE server and web UI. |
| **MCP Protocol Integration** | **5 Read-Only MCP Tools stdio** (`sot_search`, `sot_explore`, `sot_verify_drift`, `sot_architecture_report`, `sot_communities`). | Integrated via CLAUDE.md guidelines or external MCP wrapper servers. | **MCP-Native stdio/SSE server** providing codebase structure lookup tools. |

---

### 📌 When to Choose Which Tool? (Selection Guide)

1. **Choose `sot-graph` when:**
   - You are building or using **AI Coding Agents (OMP, Claude Code, Cursor, Windsurf, Agy)** that require an **ultra-fast, self-healing knowledge layer that eliminates dead paths and phantom anchors**.
   - You need a **Zero-Daemon, Zero-External-Dependencies** tool running on standard Python 3.10+ and embedded SQLite with sub-millisecond query latency ($< 1.5\text{ms}$).
   - You want end-to-end capabilities from trust-verified search and architectural diagnostics (God Nodes, Louvain Communities) to GraphRAG, Obsidian, and HTML visualizer exports in a single CLI.

2. **Choose `graphify` when:**
   - You need to analyze a **heterogeneous multi-modal document corpus** (combining source code, Markdown/PDF docs, research papers, and diagrams).
   - You want to leverage **LLM semantic reasoning** to discover implicit relationships (`INFERRED` edges) with explicit token cost audit trails.
   - You want to generate rich Obsidian vaults for human architectural study and documentation.

3. **Choose `gitnexus` when:**
   - You want to **rapidly explore code architecture directly in a web browser** (Zero-Server Web App) by dropping a ZIP file or pasting a GitHub repository URL.
   - You need an interactive client-side web UI for developers to inspect call chains and Git revision graphs without configuring a backend runtime.

---

## 🧪 Testing

The comprehensive test suite covers idempotency, trust scoring, pending edge resolution, community detection, exporters, and MCP protocol integration:

```bash
PYTHONPATH="src" python3 -m unittest discover -s tests -p "test_*.py" -v
```

```
Ran 31 tests in 0.98s
OK (31/31 passed)
```

---

## 📄 License

MIT License. Copyright (c) 2026 Minh Giap.
