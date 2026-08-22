# sot-graph (Single Source of Truth Knowledge Graph)

> **Verified, self-healing knowledge layer for AI coding agents.**
> Filesystem is the Single Source of Truth — The knowledge graph is an authoritative, verified projection of reality. Zero external daemons required.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](pyproject.toml)
[![SQLite: WAL + FTS5](https://img.shields.io/badge/SQLite-FTS5%20%2B%20WAL-orange.svg)](src/sot_graph/db.py)

---

## 🎯 Purpose & The Core Problem

Traditional RAG and agent memory systems suffer from **"Phantom Anchors, Stale Context, and Dead Paths"**:
1. **Hallucinated Locations**: When files are deleted, renamed, or refactored, the agent's memory continues pointing at old paths. The agent acts on non-existent code, wasting prompt tokens and creating broken patches.
2. **Cold Start Redundancy**: Every AI coding session starts cold. Grep across repos cannot easily answer *"Did I already solve this in another project?"*, resulting in developers rebuilding the exact same utility three times.
3. **Heavy Daemon Bottlenecks**: Many graph tools require background daemons (Neo4j, vector servers, background Node runtimes) that fail silently, consume gigabytes of RAM, or drop writes under high contention.

**`sot-graph` solves this at the architectural root:**
- **Filesystem Chokepoint**: A hint (file watcher, hook, or CLI) can only say *"look at this path"*. It is never believed about what happened. The reconciler reads the actual file from disk to make the graph match.
- **Trust-Verified Search**: Every search result is **verified against disk reality** before the agent sees it. If a path is dead, it is purged immediately.
- **Single-Writer Concurrency**: A single SQLite WAL database handles dirty tracking via SHA-256 generation counters. Multiple concurrent agents editing files will always converge to the exact same state without race conditions.

---

## 🛡️ The Trust Verdict System

When an agent searches the knowledge base via `sot search "<query>"`, every candidate node is evaluated by the **Trust Verification Engine** (`sot_graph.verifier`):

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
| `[STRONG]` | **Path physically exists on disk AND actual content contains $\ge 50\%$ query tokens.** | **High Confidence**: Go straight to the referenced file and line number. |
| `[WEAK]` | **Semantic/Title match only; low lexical overlap in file content.** | **Caution**: Plausible hit; verify file context manually before editing. |
| `[REBUILT]` | **File was moved/renamed in project.** | **Auto-Healed**: Discovered by basename scan; path automatically updated. |
| `[REMOVED]` | **Path permanently deleted from disk.** | **Auto-Purged**: Node deleted from database so it never ranks again. |
| `[NOPATH]` | **Virtual knowledge note (architecture decisions, rules).** | **Knowledge Anchor**: Treat as documented guideline. |

---

## ⚙️ How It Operates (Under the Hood)

### 1. Level-Triggered Single-Writer Reconciler (`src/sot_graph/reconciler.py`)
- **Fast Dirty Check**: Compares `size`, `mtime_ms`, and `SHA-256` content hashes. Unchanged files take `< 0.1ms` to verify.
- **Atomic Commits**: For any modified file, all old nodes, edges, and pending references owned by that path are deleted and replaced in a single SQLite transaction.
- **Idempotency Guarantee**: Running `sot reconcile` 1 time or 100 times produces the exact same deterministic graph state.

### 2. Two-Way Pending Edge Resolution (`src/sot_graph/db.py`)
In monorepos or multi-file projects, File A often imports a class from File B before File B has been indexed. `sot-graph` solves this with a two-way resolution queue:
1. When File A imports `UserService` (not yet indexed), the reference is saved into `pending_edges`.
2. As soon as File B is reconciled and defines `UserService`, `sot-graph` automatically resolves the pending edge into a confirmed directed edge in both directions.

### 3. Multi-Language AST Parser (`src/sot_graph/extractor.py` & `vendor/graphify/`)
Zero external runtime dependencies. Built-in parsers extract files, functions, methods, classes, and cross-file calls for:
- **Python** (Native `ast` module with docstrings, async functions, classes, and calls)
- **JavaScript / TypeScript / JSX / TSX**
- **Go** (Functions, Structs, Interfaces)
- **Rust** (Functions, Structs, Enums, Traits)
- **C / C++** (Structs, Functions, Classes)
- **Java, Ruby, PHP, Swift, Markdown, Shell, SQL**

---

## 🚀 Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                              SOT-GRAPH                                 │
│      (Verified, Self-Healing Source-of-Truth Knowledge Graph)          │
└────────────────────────────────────────────────────────────────────────┘
                                   │
      ┌────────────────────────────┼────────────────────────────┐
      ▼                            ▼                            ▼
[ 1. Reconciler Engine ]   [ 2. Knowledge Core ]      [ 3. Trust Verdict ]
  • Single-Writer SQLite     • SQLite FTS5 (BM25)       • Lexical Coverage
  • SHA-256 Dirty Check      • AST Nodes & Edges        • Disk File Validation
  • Level-Triggered Converg  • 2-way Pending Resolver   • Auto-Rehome & Purge
  • Drift Audit (CI-Safe)    • Graph Walk (Explore)     • Labels: STRONG/WEAK
                                   │
      ┌────────────────────────────┴────────────────────────────┐
      ▼                                                         ▼
[ 4. Multi-lang AST Extract ]                       [ 5. Agent Adapters ]
  • Vendored Graphify Parser                          • OMP / Pi Agent Extension
  • 20+ Languages (Python, TS, Go, Rust...)           • OpenCode Custom Tools
  • Zero external runtime daemons                     • Claude Code Hook / Rules
```

---

## 📦 Installation & CLI Usage

### Standalone CLI
No daemon or server required. Runs directly with Python 3.10+:

```bash
# Clone the repository
git clone https://github.com/minhgv/sot-graph.git
cd sot-graph
chmod +x bin/sot

# 1. Index / Reconcile codebase
./bin/sot reconcile

# 2. Search verified knowledge (returns Trust Verdicts)
./bin/sot search "DatabasePool acquire_connection"

# 3. Explore AST relationships (Who calls what?)
./bin/sot explore "DatabasePool" --depth 2

# 4. Record a reusable architectural fix or decision
./bin/sot insert --title "ZRAM Swap Setup" --body "Set swappiness=180 on 4GB VPS" --keywords "vps,swap"

# 5. Check for drift between DB and disk (CI-safe read-only audit)
./bin/sot verify --deep

# 6. View database statistics
./bin/sot doctor
```

---

## 🤖 Agent Harness Integrations

### 1. Oh My Pi / OMP (`omp` / `pi`)
Copy the extension to your local agent configuration:
```bash
cp src/sot_graph/adapters/omp_extension.ts ~/.omp/agent/extensions/sot_graph.ts
```
Exposes 4 native agent tools: `sot_search`, `sot_explore`, `sot_reconcile`, `sot_insert`.

### 2. OpenCode / OpenCode V2 (`opencode`)
Include `src/sot_graph/adapters/opencode_tools.json` in your `.opencode.json` configuration to give subagent workers direct access to verified knowledge.

### 3. Claude Code, Antigravity CLI (`agy`), and System Prompts
Embed `src/sot_graph/adapters/AGENTS.md` into your workspace's `AGENTS.md` or `.cursorrules` to force the agent to consult existing code before generating redundant implementations.

---

## 🧪 Testing

The test suite exercises idempotency, content coverage scoring, auto-purging of dead paths, two-way edge resolution, and multi-language parsers:

```bash
python3 -m unittest discover -s tests
```

---

## 📄 License

MIT License. Copyright (c) 2026 Minh Giap.
