# sot-graph (Single Source of Truth Knowledge Graph)

> **Verified, self-healing knowledge layer for AI coding agents and engineering teams.**
> *Filesystem is the Single Source of Truth — The knowledge graph is an authoritative, verified projection of reality. Zero external daemons required.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](pyproject.toml)
[![SQLite: WAL + FTS5](https://img.shields.io/badge/SQLite-FTS5%20%2B%20WAL-orange.svg)](src/sot_graph/db.py)
[![Tests: 199 passed](https://img.shields.io/badge/Tests-199%2F199%20Passed-brightgreen.svg)](tests/)
[![Architecture: Zero-Daemon](https://img.shields.io/badge/Architecture-Zero--Daemon-purple.svg)](#-database-architecture--project-isolation)
[![Tree-Sitter: 12+ Languages](https://img.shields.io/badge/Tree--Sitter-12%2B%20Languages-success.svg)](src/sot_graph/ts_extract.py)

---

## 🎯 What is sot-graph?

`sot-graph` is an ultra-fast, zero-daemon knowledge graph and symbol navigation engine designed specifically for **Autonomous AI Coding Agents** (Oh My Pi / OMP, Claude Code, Cursor, Windsurf, OpenCode, Google Antigravity / Gemini CLI).

Traditional agent memory and RAG tools suffer from **Phantom Anchors and Hallucinated Paths**—pointing to files that were moved, deleted, or refactored during multi-turn coding sessions. `sot-graph` solves this at the architectural root:

1. **Filesystem as Single Source of Truth (SSOT)**: Physical disk reality is absolute truth. The knowledge graph is an auto-synchronizing projection.
2. **Trust Verdict System**: Every search result is physically checked against the filesystem before the agent sees it (`[STRONG]`, `[WEAK]`, `[REBUILT]`, `[REMOVED]`, `[NOPATH]`).
3. **Two-Tiered Hybrid AST Engine**:
   - **Tier 1 (High-Fidelity Tree-Sitter)**: Real concrete syntax tree parsing for **PHP (5.4–8.3), TypeScript, TSX, JavaScript, Python (3.8–3.12+), C# (.NET), Go, Rust, Java, Kotlin, Swift**.
   - **Tier 2 (Zero-Dependency State Machine)**: Resilient fallback engine handling codebases even without native compiled grammar libraries installed.
4. **Binding-Aware Dependency Tracing**: Cross-file edges resolve via lexical scopes, call types, receivers, and import aliases—never by bare string matching.
5. **LLM Context Optimization (`sot pack` / `sot bundle`)**: Slices k-hop subgraphs into bounded, untrusted-flagged YAML/Markdown context bundles, saving up to 70% of LLM prompt tokens compared to dumping raw source files.
6. **Sub-millisecond Performance**: SQLite WAL mode + FTS5 full-text search ($< 1.5\text{ ms}$ retrieval), bounded connection caches ($\le 8\text{MB}$), zero background daemons.

---

## ⚡ Quick Start & Installation

### Prerequisites
- **Python 3.10+** (Zero external dependencies for core CLI and regex indexing).
- Standard **SQLite3 with FTS5** (built into standard Python distributions).

### Installation Options

#### 1. Core Installation (Zero-Dependency Core)
```bash
# Clone the repository
git clone https://github.com/minhgv/sot-graph.git
cd sot-graph
chmod +x bin/sot

# Install core package in editable mode
pip install -e .
```

#### 2. Full Tree-Sitter & AI Agent Extras (Recommended)
```bash
# Install with Tree-Sitter AST grammars, MCP server, Graph Analytics & Hybrid Vector search
pip install -e '.[tree-sitter,mcp,analytics,vector,watch]'

# Or using uv (ultra-fast Python package installer)
uv pip install -e '.[tree-sitter,mcp,analytics,vector,watch]'
```

---

## 🤖 1-Command AI Agent Harness Provisioning (`sot setup`)

`sot-graph` includes automated provisioning for all major AI coding harnesses to instantly configure MCP tools, extensions, and SSOT agent rules:

```bash
# Provision all supported harnesses at once (Global + Workspace)
./bin/sot setup --harness all

# Or provision specific harnesses
./bin/sot setup --harness omp          # Oh My Pi (OMP)
./bin/sot setup --harness opencode     # OpenCode
./bin/sot setup --harness claude       # Claude Code & Cursor
./bin/sot setup --harness antigravity  # Google Antigravity / Gemini CLI

# Scope configuration to current workspace only
./bin/sot setup --harness all --workspace-only
```

### Supported Harnesses & Deployed Integrations

| Harness | Configuration Files & Artifacts | Integration Highlights |
| :--- | :--- | :--- |
| **Oh My Pi (OMP)** | `~/.omp/agent/extensions/sot-graph.ts`<br>`.omp/extensions/sot-graph.ts`<br>`.omp/skills/sot-graph/SKILL.md`<br>`.omp/RULES.md` | **10 Native TypeScript Agent Tools** (`sot_search`, `sot_explore`, `sot_reconcile`, `sot_verify`, `sot_insert`, `sot_cluster`, `sot_report`, `sot_viz`, `sot_export`, `sot_bundle`). Enforces SSOT Knowledge Reuse Rules. |
| **OpenCode** | `~/.config/opencode/skill/sot-graph/SKILL.md`<br>`.opencode/skills/sot-graph/SKILL.md`<br>`opencode.json` (auto-merged)<br>`opencode_plugin.ts` | **JSON Auto-Merge & Background Sync Plugin**. Auto-reconciles project index on `session.created` and `file.edited` lifecycle hooks. |
| **Claude Code & Cursor** | `.mcp.json`<br>`.cursor/mcp.json`<br>`.claude/CLAUDE.md`<br>`AGENTS.md` | **Standard MCP Stdio Server (2025-06-18 spec)** and Knowledge Reuse Protocol embedded directly into agent context instructions. |
| **Google Antigravity & Gemini CLI** | `~/.gemini/settings.json`<br>`.gemini/settings.json`<br>`~/.gemini/skills/sot-graph/SKILL.md`<br>`GEMINI.md` | **Settings Auto-Merge & Custom Skills**. Configures MCP server and appends SSOT prompt rules. |

---

## 🛡️ Agent Protocol & Trust Verdict System

When an agent executes `sot search` or calls `sot_search`, every candidate result is verified live against disk reality before being returned to the LLM:

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

### Trust Verdict Definitions & Agent Actions

| Verdict | Meaning | Mandatory Agent Action |
| :--- | :--- | :--- |
| `[STRONG]` | Path physically exists on disk AND content matches query tokens ($\ge 50\%$). | **High Confidence**: Proceed directly to referenced file and line number. |
| `[WEAK]` | Semantic / index match only; low lexical overlap in current file content. | **Caution**: Inspect line ranges using targeted reading before making edits. |
| `[REBUILT]` | File was moved or renamed elsewhere in the project. | **Auto-Healed**: Database automatically updated to new path. Use new path. |
| `[REMOVED]` | Path was permanently deleted from disk. | **Auto-Purged**: Node removed from index immediately. Do not reference. |
| `[NOPATH]` | Virtual knowledge note (Architectural Decision Records, conventions). | **Knowledge Anchor**: Treat as strict project rule/decision. |

---

## 📋 Mandatory Agent Instructions (Rules for AI Prompts)

Copy and add these instructions to your agent rules (`AGENTS.md`, `CLAUDE.md`, `.omp/RULES.md`, or system prompt):

```markdown
# SOT-Graph Knowledge Reuse Protocol (SSOT)

## 1. Filesystem as Single Source of Truth (SSOT)
- The physical filesystem is the absolute ground truth. The SOT knowledge graph (`.sot/sot.db`) is an authoritative projection.
- Never assume a file path exists based on historical context without verification.

## 2. Knowledge Reuse Protocol (Mandatory Before Implementation)
Before writing any new utility, helper function, or class:
1. Run `sot search "<keyword>"` or use the `sot_search` tool.
2. Check Trust Verdicts:
   - `[STRONG]`: Code physically exists and is verified on disk.
   - `[WEAK]`: Semantic match only; inspect the file range first.
   - `[REBUILT]`: File was moved; use the updated path.

## 3. Dependency Impact & Blast Radius Tracing
Before modifying or refactoring core functions, classes, or API contracts:
1. Run `sot explore "<symbol>"` or use `sot_explore` to inspect both Outward Calls and Incoming References.
2. Ensure you understand all upstream callers before changing signatures.

## 4. Self-Healing & Drift
- If you create, move, or delete files, run `sot reconcile` or `sot_reconcile` tool.
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sot insert --title "..." --body "..." --keywords "..."`.

## 5. Architecture Analysis & Fact Bundle Extraction
When requested to review or synthesize architecture documentation for a repository:
1. Run `sot bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/`.
2. Ingest the 5 fact files along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md` to produce grounded reports without reading raw files sequentially.
```

---

## 💻 CLI & Agent Tool Usage Reference

### 1. Codebase Indexing & Synchronization
```bash
# Full indexing / self-healing sync with filesystem
./bin/sot reconcile

# Multi-worker parallel sync for large codebases
./bin/sot reconcile --workers 4 --batch-size 64

# Real-time file watcher (debounced 200ms, CAS write-lock gated)
./bin/sot watch
```

### 2. Verified Search & Symbol Discovery
```bash
# Search functions, classes, methods, and files
./bin/sot search "Database acquire_connection"

# Scoped search within a specific module with structured JSON output
./bin/sot search "reconcile" --scope src/sot_graph --json

# Hybrid search (FTS5 BM25 + Vector Cosine via RRF fusion)
./bin/sot embed && ./bin/sot search "retry with backoff" --hybrid
```

### 3. Dependency Graph & Blast Radius Exploration
```bash
# Explore callers and callees up to 2 hops
./bin/sot explore "Reconciler" --depth 2

# Find all references grouped by caller (with bare-name renaming risk)
./bin/sot usages "commit_file_batch"

# Find implementations and interface extensions in both directions
./bin/sot implementations "BaseStore"

# Dry-run rename impact analysis (non-destructive)
./bin/sot rename "explore_node" --to "walk_node"
```

### 4. Context Bundling for Agent Prompts (`sot pack`)
```bash
# Package exact target span (L0) + 1-hop contracts (L1) + 2-hop signature stubs (L2)
./bin/sot pack "Database.commit_file_batch" -o .sot/bundle.yaml

# Token-budgeted repository map ranked by personalized PageRank
./bin/sot map --tokens 1024 --focus "Database.commit_file_batch"
```

### 5. Architecture Fact Bundles & SDLC Documentation
```bash
# Extract 5 high-density fact files into .sot/bundle/ for LLM documentation
./bin/sot bundle -o .sot/bundle

# Generate human-readable Markdown architecture report
./bin/sot report -o ARCHITECTURE_REPORT.md

# Run Louvain community detection to evaluate modularity (Q) and cohesion
./bin/sot cluster
```

### 6. Interactive Visualizer & Knowledge Graph Export
```bash
# Launch zero-server D3.js interactive force-directed visualizer
./bin/sot viz --open

# Export graph for GraphRAG pipelines (JSON)
./bin/sot export --format graphrag -o graphrag_dataset.json

# Export Obsidian Markdown Vault with [[wikilinks]]
./bin/sot export --format obsidian -o obsidian_vault/

# Export GraphML for Gephi / Cytoscape
./bin/sot export --format graphml -o graph.graphml
```

### 7. Integrity Audit, Health & Vacuum
```bash
# Deep drift audit between disk and index (CI-safe read-only)
./bin/sot verify --deep

# System health diagnostics, entity statistics, and SQLite page usage
./bin/sot doctor

# Purge stale references and vacuum database
./bin/sot clean --all --yes
./bin/sot vacuum --analyze
```

---

## 🔌 MCP Server Configuration (Model Context Protocol)

`sot-graph` implements a compliant, read-only MCP server over `stdio` (`sot mcp` or `python3 -m sot_graph.mcp_server`).

### MCP Stdio Configuration (`.mcp.json` / `claude_desktop_config.json` / Cursor)

```json
{
  "mcpServers": {
    "sot-graph": {
      "command": "python3",
      "args": ["-m", "sot_graph.mcp_server"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

### Exposed MCP Tools (Read-Only)

| MCP Tool | Description | Input Parameters |
| :--- | :--- | :--- |
| `sot_search` | Trust-verified search across symbols, functions, classes, and notes with live disk checks. | `query` (string, required), `scope` (string, optional) |
| `sot_explore` | Graph BFS traversal showing callers, callees, and Blast Radius. | `name` (string, required), `depth` (integer, default: 1) |
| `sot_verify_drift` | Non-mutating integrity audit checking disk-to-database synchronization. | `deep` (boolean, default: false) |
| `sot_architecture_report`| Generates structured architectural analysis (God Nodes, Louvain modularity). | `scope` (string, optional) |
| `sot_communities` | Returns detected functional communities and cohesion scores. | `scope` (string, optional) |
| `sot_bundle` | Extracts 5 standardized fact markdown/JSON files for LLM report synthesis. | `output_dir` (string, optional) |
| `sot_pack` | Packages a k-hop ContextBundle (YAML) around one symbol (exact span + 1-hop contracts). | `target` (string, required), `max_hops`, `max_nodes`, `max_bytes` |

---

## 📁 Database Architecture & Project Isolation

`sot-graph` maintains a fully isolated, local SQLite database inside each project directory:

```text
<project-root>/
├── .sot/
│   ├── sot.db          # Primary SQLite database (nodes, edges, FTS5 index)
│   ├── sot.db-wal      # SQLite Write-Ahead Log
│   ├── sot.db-shm      # Shared-memory index for concurrent WAL reads
│   └── write.lock      # Cross-platform publication lock (never truncated)
├── src/
└── README.md
```

- **Default Location**: `<project-root>/.sot/sot.db`
- **Zero Central Daemons**: No background daemon, socket, or global database shared across repos.
- **Versioned Schema (v3)**: `graph_nodes` stores FQNs, signatures, and exact spans; `pending_edges` stores call contexts (kind/receiver/import source).
- **Disposable Index**: The filesystem is the single source of truth. If `.sot/sot.db` is deleted, running `sot reconcile` reconstructs the entire graph index in milliseconds.

Add `.sot/` to your `.gitignore`:
```gitignore
# sot-graph local index
.sot/
```

---

## 🧪 Testing & Verification

The test suite covers idempotency, trust scoring, AST extractions across 12+ languages, CAS publication under write lock, schema migration, ContextBundle packaging, file watch daemon, community determinism, exporters, and MCP protocol integration:

```bash
# Run full test suite with uv
uv run --all-extras --with pytest --with pytest-asyncio pytest tests/ -v
```

```text
======================= 199 passed, 30 subtests passed in 5.82s =======================
```

---

## 📜 Attribution & Third-Party Credits

`sot-graph` builds upon the foundational work of the open-source community:

1. **[Graphify](https://github.com/voidshard/graphify)** (MIT License): AST extraction logic foundation (`src/sot_graph/_vendor/graphify/`).
2. **[Tree-sitter](https://tree-sitter.github.io/tree-sitter/)** (MIT License): Incremental parsing system for high-fidelity syntax tree extraction.
3. **[D3.js](https://d3js.org/)** (ISC / BSD-3-Clause License): Standalone force-directed graph visualizer (`sot viz`).
4. **[SQLite](https://www.sqlite.org/)** (Public Domain): Relational, FTS5 full-text indexing, and Write-Ahead Logging (WAL) engine.

---

## 📄 License

MIT License. Copyright (c) 2026 Minh Giap.
