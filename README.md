# sot-graph (Single Source of Truth Knowledge Graph)

> **Verified, self-healing knowledge layer for AI coding agents.**
> Filesystem is the Single Source of Truth — The knowledge graph is an authoritative, verified projection of reality. Zero external daemons required.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](pyproject.toml)
[![SQLite: WAL + FTS5](https://img.shields.io/badge/SQLite-FTS5%20%2B%20WAL-orange.svg)](src/sot_graph/db.py)

---

## 💡 The Problem: Why Coding Agents Fail at Memory

Traditional RAG and agent memory systems suffer from **"Phantom Anchors and Dead Paths"**:
1. When files are deleted, renamed, or refactored, the agent's memory continues pointing at old paths.
2. The agent acts on hallucinated code locations, wasting tokens and creating broken code.
3. Every session starts cold without knowing whether a solution was already built in another project.

**`sot-graph` solves this at the root:**
- Every search result is **verified against disk reality** before the agent sees it.
- Filesystem changes trigger **idempotent, level-triggered convergence**.
- Edges between functions, classes, and cross-file dependencies are **resolved bidirectionally**.

---

## 🛡️ The Trust Verdict System

Every knowledge query runs through the **Trust Verification Engine** (`sot_graph.verifier`):

| Verdict | Meaning | Action Taken |
| :--- | :--- | :--- |
| `[STRONG]` | **Path physically exists + high lexical coverage ($\ge 50\%$)** | High confidence: Agent goes straight to the referenced file and line. |
| `[WEAK]` | **Semantic/Title match only, low file content coverage** | Low confidence: Plausible hint; agent must inspect before relying. |
| `[REBUILT]` | **File moved/renamed on disk** | Auto-healing: Found by unique basename, re-anchored in the graph. |
| `[REMOVED]` | **Path deleted permanently from filesystem** | Auto-purging: Node is deleted from DB so it never ranks again. |

---

## 🚀 Architecture & Core Features

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

1. **Native SQLite FTS5 + WAL**: Zero external vector daemons or remote server requirements. Runs in < 15MB RAM.
2. **Two-Way Pending Edge Resolution**: Cross-file imports resolve automatically regardless of the order files are parsed.
3. **Multi-Language AST Extraction**: Built-in support for Python, JavaScript, TypeScript, Go, Rust, Java, C/C++, Ruby, PHP, and Swift.

---

## 📦 Installation & Quick Start

### Standalone CLI
```bash
git clone https://github.com/minhgv/sot-graph.git
cd sot-graph
chmod +x bin/sot

# Index codebase
./bin/sot reconcile

# Search verified knowledge
./bin/sot search "DatabasePool"

# Explore AST callers and callees
./bin/sot explore "DatabasePool" --depth 2

# Check for index drift (Safe for CI)
./bin/sot verify --deep
```

---

## 🤖 Agent Harness Integrations

### 1. Oh My Pi / OMP (`omp`)
Copy `src/sot_graph/adapters/omp_extension.ts` to `~/.omp/agent/extensions/sot_graph.ts`.

### 2. OpenCode / OpenCode V2 (`opencode`)
Reference `src/sot_graph/adapters/opencode_tools.json` in your project's `.opencode.json`.

### 3. Claude Code & Cursor Rules
Add `src/sot_graph/adapters/AGENTS.md` into your root `AGENTS.md` or `.cursorrules`.

---

## 🧪 Testing

Run the comprehensive unit test suite:
```bash
python3 -m unittest discover -s tests
```

---

## 📄 License

MIT License. Copyright (c) 2026 Minh Giap.
