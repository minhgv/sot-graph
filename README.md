# sot-graph (Single Source of Truth Knowledge Graph)

> **Verified, self-healing knowledge layer for AI coding agents and codebases.**
> *Filesystem is the Single Source of Truth — The knowledge graph is an authoritative, verified projection of reality. Zero external daemons required.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](pyproject.toml)
[![SQLite: WAL + FTS5](https://img.shields.io/badge/SQLite-FTS5%20%2B%20WAL-orange.svg)](src/sot_graph/db.py)
[![Tests: 138 passed](https://img.shields.io/badge/Tests-138%2F138%20Passed-brightgreen.svg)](tests/)
[![Architecture: Zero-Daemon](https://img.shields.io/badge/Architecture-Zero--Daemon-purple.svg)](#-database-architecture--project-isolation)

---

## 🎯 What is sot-graph?

`sot-graph` is an ultra-lightweight, zero-daemon knowledge graph designed specifically for **AI Coding Agents** (Oh My Pi / OMP, Claude Code, Cursor, Windsurf, OpenCode, Gemini CLI / Google Antigravity).

Traditional agent memory and RAG tools suffer from **Phantom Anchors and Dead Paths**—pointing to files that were moved, deleted, or refactored. `sot-graph` solves this at the architectural root:
- **Filesystem Chokepoint**: Disk reality is absolute truth. Hints only say *"look at this path"*; the reconciler verifies the actual file on disk.
- **Trust Verdict System**: Every search result is physically checked before the agent sees it (`[STRONG]`, `[WEAK]`, `[REBUILT]`, `[REMOVED]`).
- **Binding-Aware Call Graph**: Cross-file edges resolve via lexical scope, call kind, receivers, and import modules — never by bare name matching — so `requests.get()` or `db.execute()` are never confused with project symbols.
- **ContextBundle Packaging**: `sot pack <symbol>` slices a k-hop subgraph (exact source span + 1-hop contracts + 2-hop signature stubs) into a capped, `content_is_untrusted` YAML artifact for agent prompt registers; repo-root `AGENTS.md` rides along as an explicitly `content_is_trusted` instruction block.
- **Symbol Navigation**: `sot usages` (find-all-references grouped by caller, with unresolved bare-name renaming risk), `sot implementations` (extends/implements both directions) and `sot rename` (report-only impact plan).
- **Repo Map**: `sot map [--tokens N] [--focus a,b]` — token-budgeted symbol map ranked by personalized PageRank for cheap agent orientation.
- **MCP 2025-06-18**: 11 read-only tools with structured output (`outputSchema`/`structuredContent`), Resource Links for lazy node fetches, `resources/subscribe` push when the graph generation changes, and cursor pagination.
- **Optional Hybrid Retrieval**: `[vector]` extra fuses FTS5 BM25 with sqlite-vec cosine via reciprocal-rank fusion (`sot embed` + `sot search --hybrid`); the zero-dep core keeps BM25 as the floor.
- **Optional tree-sitter Breadth**: `[tree-sitter]` extra upgrades Go/Rust/Java/Kotlin/Swift from regex fallbacks to real AST extraction through the same resolution pipeline.
- **Conflict-Safe Concurrency**: All mutations pass a stable `.sot/write.lock` plus per-path generation compare-and-swap; stale writers get deterministic `CONFLICT` verdicts instead of corrupting newer publications.
- **Sub-millisecond Performance**: SQLite WAL + FTS5 (BM25, unicode61) search in $< 1.5\text{ ms}$, bounded reader/writer caches ($\le 8\text{MB}$ per connection), zero external server daemons.

---

## ⚡ Quick Start & Installation

### Prerequisites
- **Python 3.10+** (Zero external dependencies for core CLI and indexing).
- Standard **SQLite3 with FTS5** (included with standard Python distributions).

### Installation

```bash
# Clone the repository
git clone https://github.com/minhgv/sot-graph.git
cd sot-graph
chmod +x bin/sot

# Optional: Install MCP dependencies if running MCP stdio server
pip install -e '.[mcp]'

# Optional: Real-time watcher backend (inotify/kqueue); stdlib polling fallback is built in
pip install -e '.[watch]'
```

---

## 🤖 1-Command AI Agent Harness Provisioning (`sot setup`)

`sot-graph` includes automated provisioning for all major AI coding harnesses:

```bash
# Provision all supported harnesses at once
./bin/sot setup --harness all

# Or provision specific harnesses
./bin/sot setup --harness omp
./bin/sot setup --harness opencode
./bin/sot setup --harness claude
./bin/sot setup --harness antigravity

# Scope configuration to current workspace only (omit to provision global configs)
./bin/sot setup --harness all --workspace-only
```

### Supported Harnesses & Deployed Artifacts

| Harness | Configuration Files & Tools | Integration Highlights |
| :--- | :--- | :--- |
| **Oh My Pi (OMP)** | `~/.omp/agent/extensions/sot-graph.ts`<br>`.omp/extensions/sot-graph.ts`<br>`.omp/skills/sot-graph/SKILL.md`<br>`.omp/RULES.md` | **10 Native TypeScript Agent Tools** (`sot_search`, `sot_explore`, `sot_reconcile`, `sot_verify`, `sot_insert`, `sot_cluster`, `sot_report`, `sot_viz`, `sot_export`, `sot_bundle`). Enforces Filesystem SSOT rules. |
| **OpenCode** | `~/.config/opencode/skill/sot-graph/SKILL.md`<br>`.opencode/skills/sot-graph/SKILL.md`<br>`opencode.json` (auto-merged)<br>`opencode_plugin.ts` | **JSON Auto-Merge & Background Sync Plugin**. Auto-reconciles project index on `session.created` and `file.edited` lifecycle events. |
| **Claude Code & Cursor** | `.mcp.json`<br>`.cursor/mcp.json`<br>`.claude/CLAUDE.md`<br>`AGENTS.md` | **Standard MCP Stdio Server** and Knowledge Reuse Protocol rules embedded in agent instructions. |
| **Google Antigravity & Gemini CLI** | `~/.gemini/settings.json`<br>`.gemini/settings.json`<br>`~/.gemini/skills/sot-graph/SKILL.md`<br>`GEMINI.md` | **Settings Auto-Merge & Custom Skills**. Configures MCP stdio server and appends SSOT prompt rules. |

---

## 🔌 MCP Server Configuration (Model Context Protocol)

`sot-graph` provides a standardized, read-only MCP server over `stdio` (`sot mcp` or `python3 -m sot_graph.mcp_server`).

### Standard Configuration (`.mcp.json` / `claude_desktop_config.json` / Cursor)

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
| `sot_search` | Trust-verified search across symbols, functions, classes, and notes with disk integrity checks. | `query` (string, required), `scope` (string, optional) |
| `sot_explore` | Graph BFS traversal showing callers, callees, and Blast Radius. | `name` (string, required), `depth` (integer, default: 1) |
| `sot_verify_drift` | Non-mutating integrity audit checking disk-to-database synchronization. | `deep` (boolean, default: false) |
| `sot_architecture_report` | Generates structured architectural analysis (God Nodes, Louvain modularity). | `scope` (string, optional) |
| `sot_communities` | Returns detected functional communities and cohesion scores. | `scope` (string, optional) |
| `sot_bundle` | Extracts 5 standardized fact markdown/JSON files for LLM architectural report synthesis. | `output_dir` (string, optional) |
| `sot_pack` | Packages a k-hop ContextBundle (YAML) around one symbol: 1-hop caller/callee contracts + 2-hop signature stubs. All content flagged `content_is_untrusted`. | `target` (string, required), `max_hops`, `max_nodes`, `max_bytes` (optional) |

---

## 🛡️ Agent Protocol & Trust Verdict System

When an agent searches via `sot search` or `sot_search`, every result is verified live against disk before returning:

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

### Trust Verdict Meanings

| Verdict | Meaning | Agent Action |
| :--- | :--- | :--- |
| `[STRONG]` | Path physically exists on disk AND content matches query tokens ($\ge 50\%$). | **High Confidence**: Go directly to referenced file and line. |
| `[WEAK]` | Semantic match only; low lexical overlap in file content. | **Caution**: Verify file context before editing. |
| `[REBUILT]` | File was moved or renamed in the project. | **Auto-Healed**: Database automatically updated to new path. |
| `[REMOVED]` | Path was permanently deleted from disk. | **Auto-Purged**: Node removed from index immediately. |
| `[NOPATH]` | Virtual knowledge note (Architectural Decision Records, rules). | **Knowledge Anchor**: Treat as project convention. |

### 5-Step Knowledge Reuse Protocol for Agents

Agents should follow this standard protocol before implementing new code:
1. **Search Existing Solutions**: `sot search "<what you are looking for>"`
2. **Follow Trust Verdicts**: Prioritize `[STRONG]` references; inspect `[WEAK]` matches.
3. **Trace Blast Radius**: `sot explore "<symbol_name>"` to see incoming callers before breaking APIs.
4. **Pack Working Context**: `sot pack "<symbol>"` to load the exact source span + caller/callee contracts (capped, untrusted-flagged) instead of dumping whole files into the prompt.
5. **Persist Architecture Decisions**: `sot insert --title "<topic>" --body "<details>" --keywords "k1,k2"`

---

## 💻 Developer & Agent CLI Reference

```bash
usage: sot [-h] [--root ROOT] [--db DB]
           {search,explore,insert,reconcile,verify,doctor,clean,vacuum,mcp,report,cluster,viz,export,bundle,setup,pack,watch} ...
```

### 1. Codebase Indexing & Sync
```bash
# Sync knowledge graph with filesystem
./bin/sot reconcile

# Multi-worker parallel sync for large repositories
./bin/sot reconcile --workers 4 --batch-size 64
```

Concurrent reconciles are serialized behind `.sot/write.lock` with per-path generation CAS: if a file changed mid-parse, that path is reported as a conflict (re-queued for the next pass) instead of overwriting the newer version.

### 2. Search & Code Exploration
```bash
# Search verified symbols and functions
./bin/sot search "Database acquire_connection"

# Search within specific subfolder with JSON output
./bin/sot search "reconcile" --scope src/sot_graph --json

# Explore call graph (callees & callers up to 2 hops)
./bin/sot explore "Reconciler" --depth 2
```

### 3. Context Bundles for Agent Prompts (`sot pack`)
```bash
# Package a k-hop ContextBundle: exact source span of the target (level 0),
# full caller/callee contracts (1-hop), folded signature stubs (2-hop).
./bin/sot pack "Database.commit_file_batch" -o .sot/bundle.yaml

# Fail-closed guarantees: AMBIGUOUS_TARGET / TARGET_NOT_FOUND /
# TARGET_TOO_LARGE / STALE_SNAPSHOT instead of silent truncation.
```

### 4. Navigation & Orientation
```bash
# Find-all-references grouped by caller + unresolved bare-name risk
./bin/sot usages "commit_file_batch"

# extends/implements edges in both directions
./bin/sot implementations "BaseStore"

# Report-only rename impact plan (no files modified)
./bin/sot rename "explore_node" --to walk_node

# Token-budgeted repo map ranked by personalized PageRank (Aider recipe)
./bin/sot map --tokens 1024 --focus "Database.commit_file_batch"
```

### 5. Optional Extras
```bash
pip install 'sot-graph[vector]'        # sqlite-vec hybrid search
./bin/sot embed && ./bin/sot search "retry logic" --hybrid

pip install 'sot-graph[tree-sitter]'   # real ASTs for Go/Rust/Java/Kotlin/Swift

# Event-driven sync without a daemon: reconcile after merge/checkout
./bin/sot setup --hooks

# SCIP interop for editors/Sourcegraph
./bin/sot export --format scip

# Deterministic context-cost benchmark (pack vs whole-file reads)
python3 scripts/benchmark_context.py
```

### 6. Real-Time Sync Daemon (`sot watch`)
```bash
# Watch filesystem and reconcile on change (debounced 200ms, CAS-gated)
./bin/sot watch

# Explicit backend: watchfiles (if installed) or stdlib polling
./bin/sot watch --backend poll --interval-ms 500
```

### 7. Architecture Fact Bundle & Reports
```bash
# Extract 5 standardized fact files (.sot/bundle/) for LLM architecture generation
./bin/sot bundle -o .sot/bundle

# Generate comprehensive human-readable Markdown architecture report
./bin/sot report -o ARCHITECTURE_REPORT.md

# Inspect detected functional communities and Louvain Modularity (Q)
./bin/sot cluster
```

### 8. Interactive Visualizer & Exporters
```bash
# Open interactive zero-server D3.js force-directed visualizer
./bin/sot viz --open

# Export graph for GraphRAG pipelines
./bin/sot export --format graphrag -o graphrag_dataset.json

# Export Obsidian Markdown Vault with wikilinks [[...]]
./bin/sot export --format obsidian -o obsidian_vault/

# Export GraphML for Gephi / Cytoscape
./bin/sot export --format graphml -o graph.graphml
```

### 9. Integrity Verification & Maintenance
```bash
# Check for drift between database and filesystem (CI-safe read-only audit)
./bin/sot verify --deep

# Check database health and entity counts
./bin/sot doctor

# Clean stale/missing paths and vacuum database
./bin/sot clean --all --yes
./bin/sot vacuum --analyze
```

---

## 📁 Database Architecture & Project Isolation

`sot-graph` maintains a fully isolated, local SQLite database inside each project directory:

```text
<project-root>/
├── .sot/
│   ├── sot.db          # Primary SQLite database (nodes, edges, FTS5 index)
│   ├── sot.db-wal      # SQLite Write-Ahead Log
│   ├── sot.db-shm      # Shared-memory index for concurrent WAL reads
│   └── write.lock      # Stable cross-platform publication lock (never truncated)
├── src/
└── README.md
```

- **Default Location**: `<project-root>/.sot/sot.db`
- **Zero Central Daemons**: No background daemon, socket, or global database shared across repos. (`sot watch` is an opt-in foreground helper, not a required service.)
- **Versioned Schema (v3)**: `graph_nodes` stores FQNs, signatures, and exact spans; `pending_edges` stores call context (kind/receiver/import source). Schema upgrades are tracked via `PRAGMA user_version` — an outdated database is dropped and rebuilt by the next `sot reconcile` (the index is disposable by design).
- **Recommended `.gitignore`**:
  ```gitignore
  # sot-graph local index
  .sot/
  ```
- **Disposable Index**: The filesystem is the single source of truth. If `.sot/sot.db` is deleted, running `sot reconcile` reconstructs the entire graph index in milliseconds.

---

## 📚 Component Documentation & Deep Dives

For comprehensive guides, benchmarks, failure mode analyses, and architectural comparisons, see our specialized docs:

- 📖 **[Comprehensive Q&A Guide (`docs/QA_GUIDE.md`)](docs/QA_GUIDE.md)** — 19 detailed real-world scenarios covering self-healing, anti-hallucination mechanics, and edge case handling.
- 🚀 **[AI-Assisted SDLC Guide (`docs/AI_SDLC_GUIDE.md`)](docs/AI_SDLC_GUIDE.md)** — Deep-dive applying `sot-graph` across all 6 phases of software development, eliminating Cold Start Redundancy.
- ⚖️ **[Architectural Comparisons: sot-graph vs graphify vs gitnexus (`docs/COMPARISONS.md`)](docs/COMPARISONS.md)** — Multi-dimensional comparison matrix and tool selection guide.
- 📊 **[Benchmarks & Performance Guide (`docs/BENCHMARKS.md`)](docs/BENCHMARKS.md)** — Throughput benchmarks, worker scaling, query latency, and memory footprint validation.
- 🔬 **[GitNexus vs sot-graph Deep Dive (`docs/GITNEXUS_VS_SOT_GRAPH.md`)](docs/GITNEXUS_VS_SOT_GRAPH.md)** — In-depth 8-dimensional comparison, failure mode audit, and two-tier hybrid architecture.
- 🏛️ **[Project Architecture Report (`docs/ARCHITECTURE_REPORT.md`)](docs/ARCHITECTURE_REPORT.md)** — Comprehensive architecture audit of `sot-graph` generated via the 2-stage Fact Bundle pipeline.
- 📋 **[Architecture Report Template (`src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`)](src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md)** — Standardized 6-section prompt template for LLM architecture report generation.

---

## 🧪 Testing

The comprehensive test suite covers idempotency, trust scoring, binding-aware pending edge resolution, CAS publication under the write lock, schema migration, ContextBundle packaging, the watch daemon, community determinism, exporters, and MCP protocol integration:

```bash
PYTHONPATH="src" python3 -m unittest discover -s tests -p "test_*.py" -v
```

```text
Ran 93 tests in 5.3s
OK (93/93 passed)
```

---

## 📜 Attribution & Third-Party Credits

`sot-graph` stands on the shoulders of the open-source community:

1. **[Graphify](https://github.com/voidshard/graphify)** (MIT License): AST extraction logic foundation (`src/sot_graph/_vendor/graphify/`).
2. **[D3.js](https://d3js.org/)** (ISC / BSD-3-Clause License): Standalone force-directed graph visualizer (`sot viz`).
3. **[SQLite](https://www.sqlite.org/)** (Public Domain): Relational, FTS5 full-text indexing, and Write-Ahead Logging (WAL) engine.

---

## 📄 License

MIT License. Copyright (c) 2026 Minh Giap.
