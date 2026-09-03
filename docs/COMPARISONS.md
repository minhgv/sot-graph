# Architectural Comparisons: sot-graph vs graphify vs gitnexus

This document provides an objective, multi-dimensional architectural comparison between `sot-graph`, `graphify`, and `gitnexus`, explaining when to choose each tool and how they complement one another in modern AI-assisted software engineering.

---

## ⚖️ 3-Way Architectural Comparison Matrix

| Dimension / Capability | `sot-graph` | `graphify` | `gitnexus` |
| :--- | :--- | :--- | :--- |
| **Core Purpose** | Self-healing **Single Source of Truth** knowledge layer for AI Coding Agents in the active filesystem coding loop. | Deep multi-modal knowledge graph builder (Code, Docs, Papers) with architectural reporting and LLM semantic inference. | Client-side zero-server Code Intelligence & MCP tool running in-browser for AST & Git repository exploration. |
| **Source of Truth** | **Filesystem is the absolute truth**. Hints are only triggers; state is physically verified against disk before delivery. | **Input files + LLM inference**. Takes directory snapshots at extraction time and stores static graph JSON. | **Git Repository + Tree-sitter AST**. Indexes Git trees and in-memory call graph relationships. |
| **Anti-Hallucination Mechanism** | **Trust Verdict Engine** (`[STRONG]`, `[WEAK]`, `[REBUILT]`, `[REMOVED]`): Physical disk checks and token coverage filtering at query time. | Transparent link classification (`EXTRACTED` vs `INFERRED` vs `AMBIGUOUS`) with token cost audit trail. | Static Tree-sitter AST parsing; no runtime token coverage verification or physical disk change audits. |
| **Self-Healing Capabilities** | **Automated & Instantaneous**: Auto-detects moved/renamed files (`[REBUILT]`), purges dead paths (`[REMOVED]`), cleans orphan edges. | **Manual / Batch**: Requires re-running `/graphify --update` or full graph rebuild when the codebase changes. | **Session / Manual**: Requires repository re-indexing when new commits or branches are introduced. |
| **Storage & Query Engine** | **SQLite WAL + FTS5 (BM25)**: ACID transactions, SHA-256 generation dirty tracking, sub-millisecond query latency (< 1.5 ms). | **JSON (`graph.json`) + Markdown Reports**: Flat files; no embedded relational or property graph database. | **In-memory / IndexedDB / WASM Browser Cache**: Data stored in browser RAM or transient Node.js process memory. |
| **Footprint & Resources** | Ultra-lightweight (< 25 MB RAM), **Zero external dependencies**, parallel multiprocessing (~20ms / 100 files). | Incurs LLM API token costs when running `--mode deep`; best for periodic documentation rather than per-turn edits. | Dependent on Node.js/browser runtime and RAM scaling when indexing large monorepos. |
| **Clustering & God Nodes** | In-process **Louvain / Modularity (Q)**, Cohesion scoring, and **God Node Detection (2-hop blast radius)** with zero daemons. | Built-in **Leiden / Louvain community detection**, Cohesion scoring, and Surprising Connection discovery. | Focuses on visual inheritance, import, and call-chain graphs rather than modularity analysis. |
| **Visualization** | Standalone Interactive HTML D3.js v7 (*force-directed physics*) with community filters and node/edge inspector. | Interactive HTML D3.js + Obsidian Canvas / Vault export and GraphML. | Modern client-side interactive graphical web app running directly in the browser. |
| **Export Formats** | **GraphRAG JSON**, **Obsidian Markdown Vault**, **GraphML XML**, and **Markdown Report**. | **GraphRAG JSON**, **Obsidian Markdown Vault**, **GRAPH_REPORT.md**. | Primarily targets internal MCP stdio/SSE server and web UI. |
| **MCP Protocol Integration** | **Read-Only MCP Stdio Server** (`sot_search`, `sot_explore`, `sot_verify_drift`, `sot_architecture_report`, `sot_communities`, `sot_bundle`). | Integrated via CLAUDE.md guidelines or external MCP wrapper servers. | **MCP-Native stdio/SSE server** providing codebase structure lookup tools. |

---

## 📌 Tool Selection Guide

```
                                  [ What is your primary objective? ]
                                                   │
         ┌─────────────────────────────────────────┼─────────────────────────────────────────┐
         ▼                                         ▼                                         ▼
[ AI Coding Agent Loop ]                [ Multi-Modal Study ]                     [ Visual Web Exploration ]
 • Sub-millisecond search                • Source code + PDF/Docs                  • In-browser zero-install
 • Zero dead paths / phantom anchors     • LLM-inferred semantics                  • Client-side Git tree exploration
 • Single-writer SQLite WAL              • Token-audited reports                   • Interactive call-chain UI
         │                                         │                                         │
         ▼                                         ▼                                         ▼
   ▶ sot-graph                               ▶ graphify                                ▶ gitnexus
```

### 1. When to Choose `sot-graph`
- You are building or using **AI Coding Agents (Oh My Pi / OMP, Claude Code, Cursor, Windsurf, OpenCode, Gemini CLI / Antigravity)** that require an **ultra-fast, self-healing knowledge layer that eliminates dead paths and phantom anchors**.
- You need a **Zero-Daemon, Zero-External-Dependencies** tool running on standard Python 3.10+ and embedded SQLite with sub-millisecond query latency (< 1.5 ms).
- You want end-to-end capabilities from trust-verified search and architectural diagnostics (God Nodes, Louvain Communities, 2-stage Fact Bundles) to GraphRAG, Obsidian, and HTML visualizer exports in a single CLI.

### 2. When to Choose `graphify`
- You need to analyze a **heterogeneous multi-modal document corpus** (combining source code, Markdown/PDF docs, research papers, and diagrams).
- You want to leverage **LLM semantic reasoning** to discover implicit relationships (`INFERRED` edges) with explicit token cost audit trails.
- You want to generate rich Obsidian vaults for human architectural study and documentation.

### 3. When to Choose `gitnexus`
- You want to **rapidly explore code architecture directly in a web browser** (Zero-Server Web App) by dropping a ZIP file or pasting a GitHub repository URL.
- You need an interactive client-side web UI for developers to inspect call chains and Git revision graphs without configuring a backend runtime.

---

## 🤝 Two-Tier Hybrid Architecture Pattern

In advanced software engineering teams, `sot-graph` and `graphify` / `gitnexus` can be paired synergistically:

1. **Tier 1 (Inner Loop - Fast Agent Execution)**:
   - `sot-graph` runs on every file change, providing verified symbols, call graphs, and preventing agent hallucinations in real-time.
2. **Tier 2 (Outer Loop - High-Level Architecture & Onboarding)**:
   - `sot bundle` feeds structured 5-fact bundles to LLM agents for standardized architecture reports (`ARCHITECTURE_REPORT.md`).
   - `gitnexus` or `sot viz` provides visual diagrams for developer onboarding and design reviews.

---

## 🔗 Related Documentation
- 📖 [GitNexus vs sot-graph Deep Dive (`docs/GITNEXUS_VS_SOT_GRAPH.md`)](GITNEXUS_VS_SOT_GRAPH.md)
- 🚀 [AI-Assisted SDLC Guide (`docs/AI_SDLC_GUIDE.md`)](AI_SDLC_GUIDE.md)
- ❓ [Comprehensive Q&A Guide (`docs/QA_GUIDE.md`)](QA_GUIDE.md)
- 📊 [Benchmarks & Performance Guide (`docs/BENCHMARKS.md`)](BENCHMARKS.md)
- 🏛️ [Project Architecture Report (`docs/ARCHITECTURE_REPORT.md`)](ARCHITECTURE_REPORT.md)
- 🛡️ [Change Impact Analysis & Risk Benchmark: SOT-Graph vs GitNexus vs CodeGraph vs Codebase-Memory (`docs/IMPACT_ASSESSMENT_COMPARISON.md`)](IMPACT_ASSESSMENT_COMPARISON.md)
