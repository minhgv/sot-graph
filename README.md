# sot-graph (Single Source of Truth Knowledge Graph)

> **Verified, self-healing knowledge layer for AI coding agents and engineering teams.**
> *Filesystem is the Single Source of Truth — The knowledge graph is an authoritative, verified projection of reality. Zero external daemons required.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](pyproject.toml)
[![SQLite: WAL + FTS5](https://img.shields.io/badge/SQLite-FTS5%20%2B%20WAL-orange.svg)](src/sot_graph/db.py)
[![Schema: v8 Multi-Provider](https://img.shields.io/badge/Schema-v8%20Multi--Provider-purple.svg)](src/sot_graph/db.py)
[![Tests: 1014 collected](https://img.shields.io/badge/Tests-1014%20collected-brightgreen.svg)](tests/)
[![Quality Gates: Passing](https://img.shields.io/badge/Quality%20Gates-Passing%20(87%25%20Core%20%7C%2091%25%20Receipts)-success.svg)](scripts/quality_gates.sh)
[![Architecture: Zero-Daemon](https://img.shields.io/badge/Architecture-Zero--Daemon-purple.svg)](#database-architecture--durability)
[![Tree-Sitter: 10 Grammars](https://img.shields.io/badge/Tree--Sitter-10%20Grammars-success.svg)](src/sot_graph/ts_extract.py)

---

## What is sot-graph?

`sot-graph` is an ultra-fast, zero-daemon knowledge graph and symbol intelligence engine designed specifically for **Autonomous AI Coding Agents** (Oh My Pi / OMP, Claude Code, Cursor, OpenCode, Google Antigravity / Gemini CLI, ZCode IDE).

It replaces slow, blind, and hallucination-prone text grepping with an incremental, AST-verified structural graph stored in SQLite (WAL mode + FTS5 full-text indexing + Schema v8 Multi-Provider Provenance Ledger).

### Core Value Pillars

1. **Zero Hallucinated Anchors**: The filesystem is the single source of truth. Every symbol returned is physically verified on disk with confidence scores and Trust Verdicts (`[STRONG]`, `[WEAK]`, `[REBUILT]`).
2. **Multi-Provider Provenance Ledger (Schema v8)**: Transparently records fast AST Heuristics (`AST_HEURISTIC_PARSER`), compiler-backed SCIP indices (`COMPILER_INDEXED_SYMBOLS`), and external provider telemetry (Codebase Memory) in dedicated `provider_runs` and `provider_evidence` tables.
3. **Bounded Impact Trust Chain & Canonical Root Isolation**: Strictly evaluates scope coverage through a fail-closed 6-state decision machine (`ASSURED_WITHIN_SCOPE`, `PARTIAL`, `CONFLICTED`, `STALE`, `UNVERIFIABLE`, `ABSTAINED`). Enforces canonical `os.path.realpath` bounding across DB persistence and ledger queries, preventing cross-repository evidence leakage and symlink retarget exploits in multi-tenant environments.
4. **Token-Bounded Context Packaging (`sot pack`)**: Extracts exact target spans (L0) + 1-hop caller/callee contracts (L1) + 2-hop signature stubs (L2) within strict hard token budgets (`--tokens` / `--max-tokens`), preventing prompt bloat.
5. **Architectural Blast Radius (`sot usages` / `sot explore` / `sot diff-impact`)**: Inbound and outbound dependency traversal identifying transitive callers, breaking API contracts, and unresolved bare-name shadowing risk before refactoring or landing pull requests.
6. **Atomic Two-Phase Mutation Gateway**: All database mutations (`reconcile`, `batch-reconcile`, `insert`, `clean`, `import-scip`, `providers sync`) acquire exclusive write locks (`BEGIN IMMEDIATE` + `.sot/write.lock`) with note preservation across schema migrations.

---

## Polyglot AST Engine (Tree-sitter Grammars)

`sot-graph` includes native concrete syntax tree extractors across 10+ major programming languages:

| Language | Extractor Engine | Key AST Constructs |
| :--- | :--- | :--- |
| **Python** | `ast` + `symtable` (stdlib) | Classes, Functions, Methods, Decorators, Lexical Scope & Shadowing |
| **TypeScript / TSX** | `tree-sitter-typescript>=0.23` | Interfaces, TypeAliases, Classes, Methods, Enums, Exported Consts |
| **JavaScript / JSX** | `tree-sitter-javascript>=0.23` | Classes, Functions, Arrow Functions, Lexical Declarations (`const`/`let`/`var`) |
| **Go** | `tree-sitter-go>=0.23` | Structs, Interfaces, Functions, Methods, Type Definitions |
| **Rust** | `tree-sitter-rust>=0.23` | Structs, Enums, Traits, Impl Blocks, Functions, Modules |
| **Java** | `tree-sitter-java>=0.23` | Classes, Interfaces, Enums, Records, Methods, Fields |
| **C#** | `tree-sitter-c-sharp>=0.23` | Classes, Structs, Interfaces, Enums, Records, Namespaces |
| **PHP** | `tree-sitter-php>=0.23` | Classes, Interfaces, Traits, Enums, Methods, Functions |
| **Kotlin** | `tree-sitter-kotlin>=0.7` | Classes, Interfaces, Objects, Companion Objects, Extension Functions |
| **Swift** | `tree-sitter-swift>=0.7` | Protocols, Structs, Classes, Extensions, Actor Declarations |

*(Other languages such as Ruby, Dart, C/C++ are supported via high-fidelity token state machines).*

---

## 1-Command AI Agent Harness Provisioning (`sot setup`)

`sot-graph` automatically provisions MCP tools, extensions, and SSOT agent rules across all major AI coding harnesses:

```bash
# Provision all supported harnesses at once (Global + Workspace)
sot setup --harness all

# Or provision specific harnesses
sot setup --harness pi          # Pi Harness / Oh My Pi (OMP)
sot setup --harness zcode       # ZCode IDE (MCP + Skill + Slash Commands)
sot setup --harness opencode    # OpenCode
sot setup --harness claude      # Claude Code & Cursor
sot setup --harness antigravity # Google Antigravity / Gemini CLI

# Scope configuration to current workspace only
sot setup --harness all --workspace-only
```

### Supported Harnesses & Deployed Integrations

| Harness | Configuration Files & Artifacts | Integration Highlights |
| :--- | :--- | :--- |
| **Pi Harness / Oh My Pi (OMP)** | `~/.omp/agent/extensions/sot-graph.ts`<br>`.omp/extensions/sot-graph.ts`<br>`.omp/skills/sot-graph/SKILL.md`<br>`.omp/RULES.md`<br>`.omp/rules/sot-graph.md` | Full `xd://sot_*` tool devices, SSOT system prompt rules, and background subagent knowledge reuse |
| **Claude Code & Cursor** | `~/.claude/CLAUDE.md`<br>`.claude/CLAUDE.md` | SSOT Knowledge Reuse Protocol, Blast Radius Pre-Check, and Token-Bounded Context packaging |
| **Google Antigravity** | `~/.gemini/GEMINI.md`<br>`.gemini/GEMINI.md`<br>`.gemini/skills/sot-graph/SKILL.md` | Single-Source-of-Truth directives, pure-read search, and architectural fact bundles |
| **OpenCode** | `~/.config/opencode/opencode.json`<br>`~/.config/opencode/skill/sot-graph/SKILL.md`<br>`~/.config/opencode/plugins/sot-graph/index.ts`<br>`.opencode/opencode.json`<br>`.opencode/skills/sot-graph/SKILL.md` | OpenCode skill integration, local MCP server configuration, and file permissions |
| **ZCode IDE** | `~/.zcode/config.json`<br>`~/.zcode/skills/sot-graph/SKILL.md`<br>`~/.zcode/commands/sot-*.md`<br>`.zcode/config.json`<br>`.zcode/skills/sot-graph/SKILL.md`<br>`.zcode/commands/sot-*.md` | MCP server registration, slash command suite (`/sot-search`, `/sot-map`, `/sot-explore`, `/sot-usages`, `/sot-rename`), and IDE skill |

### Native OMP/OpenCode Adapter Safety

The native TypeScript adapters resolve the installed `sot` command to an
absolute canonical executable from the trusted process `PATH` before invoking
it. They treat environment-variable names case-insensitively (including
Windows-shaped `Path` and `PythonPath` keys), remove every `PATH`/`PythonPath`
variant, filter both the original and canonical forms of each `PATH` entry and
its `sot` target whenever either form is under the canonical workspace root,
and publish only canonical representations of retained external entries. On
Windows, executable candidates follow the configured `PATHEXT` suffix order.
They never inject the workspace `src` directory through `PYTHONPATH`.
Session-start reconciliation remains best-effort when `sot` is unavailable, and
OMP schedules a debounced reconcile after successful `write`, `edit`, `ast_edit`,
or `patch` tool results.

The OMP `sot_diff_impact` adapter rejects revision targets beginning with `-`
before invoking the CLI, preventing option-like targets from being
reinterpreted as command flags.

For the OMP `sot_pack` tool, `depth` is translated to the CLI's `--max-hops`
option and `tokens` is forwarded as `--max-tokens`. The destructive OMP
`sot_clean` reset requires an explicit `confirm: true` argument when `all: true`
(unless `dry_run: true`); only an explicit confirmation adds the CLI `--yes`
flag.
---

## CLI & Agent Tool Usage Reference

### 1. Codebase Indexing & Synchronization
```bash
# Incrementally reconcile modified files into SQLite graph
sot reconcile

# Parallel multi-worker reconciliation for large codebases (100k+ LOC)
sot reconcile --workers 4

# Batch reconcile multiple distinct repositories under a parent directory
sot batch-reconcile /path/to/parent_projects --workers 4

# Import exact compiler-backed SCIP index (e.g. from scip-typescript or scip-python)
sot import-scip index.scip

# Watch filesystem and reconcile automatically on file changes
sot watch --debounce-ms 200

# Audit graph health and Schema v8 table counts
sot doctor

# Emit machine-readable audit receipt
sot doctor --receipt

# CI-safe drift check: compare database projection against the filesystem
sot verify --deep

# Safe reset of disposable graph records (user notes preserved by default)
sot clean --all --yes

# Compact the SQLite database file and re-run ANALYZE
sot vacuum --analyze
```

### 2. Pure-Read Code Search & Trust Verdicts
```bash
# Ranked symbol search with Trust Verdicts ([STRONG], [WEAK], [REBUILT])
sot search "Database.commit_file_batch"

# Search scoped to specific path or module
sot search "Reconciler" --scope "src/sot_graph" -n 10

# Build/refresh the optional vector index, then combine FTS + vector recall
sot embed
sot search "retry backoff policy" --hybrid
```

### 3. Dependency Impact & Blast Radius
```bash
# Bounded graph traversal (inward callers and outward dependencies)
sot explore "Database" --depth 2

# Find all references grouped by caller with bare-name renaming risk
sot usages "commit_file_batch"

# Find implementations and interface extensions in both directions
sot implementations "BaseStore"

# Non-destructive dry-run rename impact analysis
sot rename "explore_node" --to "walk_node"
```

### 4. Context Bundling for Agent Prompts (`sot pack`)
```bash
# Package exact target span (L0) + 1-hop contracts (L1) + 2-hop signature stubs (L2)
sot pack "Database.commit_file_batch" -o .sot/bundle.yaml

# Hard token budget cap (using --tokens or --max-tokens)
sot pack "Database.commit_file_batch" --tokens 1500 --json

# Token-budgeted repository map ranked by personalized PageRank
sot map --tokens 1024 --focus "Database.commit_file_batch"
```

### 5. Multi-Provider Assurance & Bounded Scope Receipts
```bash
# Detect installed provider executables and SCIP artifacts
sot providers detect

# List registered providers, health status, and supported capabilities
sot providers list

# Diagnose provider health with recommended remediation actions
sot providers doctor

# Synchronize index for a specific provider
sot providers sync codebase-memory

# Generate PRE-change bounded impact scope receipt (P7.1)
sot scope-receipt "Pipeline.process" --depth 2 --change-kind local-body --json
```

### 6. Full-Stack Execution Tracing & Solution Workflows
```bash
# Extract full-stack execution trace with Mermaid sequence/flowchart diagrams
sot trace "OrderController.createOrder" --depth 3

# Extract frontend UI decision tree, validation rules, and modal transitions
sot ui-tree "OrderModal.tsx" --json

# Extract backend processing micro-steps, multi-datasources, and exception branches
sot be-flow "OrderProcessingService" --json

# Stage 1: Feature discovery by user role for solution documentation
sot solution inventory "Billing" -o .sot/Feature_Inventory.md

# Stage 2: Micro-step decomposition (4-column table) for labor estimation
sot solution steps "PaymentService.processTransaction" --format table

# Synthesize complete context bundle for downstream documentation agents
sot solution bundle "Billing" -o .sot/bundle/ContextBundle.md
```

### 7. Architecture Fact Bundles & SDLC Documentation
```bash
# Extract 5 high-density fact files into .sot/bundle/ for LLM documentation
sot bundle -o .sot/bundle

# Generate human-readable Markdown architecture report
sot report -o ARCHITECTURE_REPORT.md

# Run Louvain community detection to evaluate modularity (Q) and cohesion
sot cluster

# Persist a durable knowledge/decision note (survives clean --all, queryable via sot_notes)
sot insert --title "ADR: retry policy" --body "..." --keywords "adr,retry"
```

### 8. Interactive Visualizer & Knowledge Graph Export
```bash
# Launch zero-server D3.js interactive force-directed visualizer
sot viz --open

# Export graph for GraphRAG pipelines (JSON)
sot export --format graphrag -o graphrag_dataset.json

# Export Obsidian Markdown Vault with [[wikilinks]]
sot export --format obsidian -o .sot/obsidian_vault
```

### 9. Git Diff Blast Radius & Commit Risk Analysis
```bash
# Analyze blast radius and upstream caller impact for working tree changes
sot diff-impact --working-tree

# Analyze blast radius of staged changes against HEAD~1 with reverse call graph depth 2
sot diff-impact HEAD~1 --depth 2 --staged

# Auto-reconcile knowledge graph and output impact analysis in JSON
sot diff-impact HEAD~1 --auto-reconcile --json

# Inspect recent commit history with automated risk scoring and impacted symbols
sot log -n 10 --author "developer"

# PR-comment-safe rendering for CI bots (collapsed sections, repo-relative paths)
sot diff-impact HEAD~1 --format github
```

> CI-native usage: post/update this report as an idempotent PR comment with the reusable composite action — see [docs/CI_INTEGRATION.md](docs/CI_INTEGRATION.md).

---

## Model Context Protocol (MCP) Server

`sot-graph` exposes 22 structured MCP tools, 2 reusable prompts, and resources over standard I/O for AI coding agents:

```bash
# Start MCP server over stdio
sot mcp
```

### Registered MCP Tools & Exact Schemas

#### Read-Only Inspection & Assurance Tools
| MCP Tool | Description | Required Parameters | Optional Parameters |
| :--- | :--- | :--- | :--- |
| `sot_search` | Read-only verified graph search with resource links (`sot://node/{id}`) | `query` (str) | `limit` (int, default 6), `scope` (str), `threshold` (float 0-1), `assurance` (bool), `provider_policy` ('builtin_only'\|'prefer_external'\|'require_external'), `budget` (int) |
| `sot_explore` | Bounded graph traversal (inbound and outbound) | `node_id` (str) | `depth` (int, default 1), `limit` (int, default 100) |
| `sot_usages` | Find all references grouped by caller + bare-name shadowing risk | `target` (str) | `limit` (int, default 100), `scope` (str), `assurance` (bool), `provider_policy` ('builtin_only'\|'prefer_external'\|'require_external'), `budget` (int) |
| `sot_implementations`| Extends and implements type hierarchy relationships | `target` (str) | — |
| `sot_verify_drift` | Non-destructive filesystem vs database drift check | — | `deep` (bool), `limit` (int) |
| `sot_architecture_report` | Architectural analysis with god nodes and modularity metrics | — | `scope` (str), `min_size` (int), `sigma` (float) |
| `sot_communities` | Louvain / Label Propagation community detection with cohesion scores | — | `scope` (str), `min_size` (int) |
| `sot_pack` | ContextBundle (YAML/JSON) with 1-hop contracts and 2-hop signature stubs | `target` (str) | `max_hops` (int, 1-3), `max_nodes` (int), `max_bytes` (int), `max_tokens` (int) |
| `sot_map` | Token-budgeted repository map ranked by personalized PageRank | — | `focus` (str), `max_tokens` (int, default 1024) |
| `sot_notes` | Persisted architectural knowledge notes query | — | `query` (str), `limit` (int, default 50) |
| `sot_trace` | Execution path trace, UI decision branches, and Mermaid diagrams | `target` (str) | `depth` (int, 1-5, default 2) |
| `sot_ui_tree` | Frontend UI decision tree, validation rules, button triggers, modals | `component` (str) | — |
| `sot_backend_flow` | Backend service micro-steps, multi-datasources, exception branches | `service` (str) | — |
| `sot_solution_steps` | Stage 2 Micro-step decomposition (4-column table) for manpower effort | `method` (str) | — |
| `sot_diff_impact` | Analyze git diff blast radius, inward callers, API contract impacts, and affected tests | — | `target` (str, default 'HEAD~1'), `depth` (int, default 2), `staged` (bool), `working_tree` (bool), `auto_reconcile` (bool), `format` ('markdown'\|'json'\|'github') |
| `sot_git_history` | Inspect git commit history with automated risk scoring and impacted symbol detection | — | `limit` (int, default 10), `author` (str), `since` (str), `with_impact` (bool, default true), `format` ('markdown'\|'json') |
| `sot_scope_receipt` | PRE-change bounded impact scope receipt (P7.1) with snapshot binding and risk assessment | `target` (str) | `kind_of_change` ('local-body'\|'rename'\|'delete'\|'public-api'), `touches_auth` (bool), `dynamic_heavy` (bool), `depth` (int) |
| `sot_diff_impact_receipt` | POST-change diff-impact receipt (P7.2) with post-change snapshot and closure verification | — | `target` (str), `depth` (int, 1-5), `staged` (bool), `working_tree` (bool) |

#### Write-Guarded & Artifact Generator Tools
| MCP Tool | Description | Required Parameters | Optional Parameters |
| :--- | :--- | :--- | :--- |
| `sot_providers_sync` | Explicit provider index sync (write path): records ledger run + evidence with snapshot | — | `provider_name` (str, default 'codebase-memory') |
| `sot_bundle` | Generates 5 high-density architecture fact bundle markdown files | — | `output_dir` (str, default `.sot/bundle`) |
| `sot_solution_inventory` | Stage 1 Feature Discovery by User Role for Solution docs | — | `module` (str), `output_file` (str) |
| `sot_solution_bundle` | Full solution context bundle (UI forms, DataTable schemas, API specs) | — | `module` (str), `output_file` (str) |

---

## Database Architecture & Durability

- **Storage Engine**: SQLite in WAL (Write-Ahead Logging) mode with `NORMAL` synchronous mode and 64MB memory-mapped I/O (`mmap_size = 67108864`).
- **Physical Tables (Schema v8)**:
  - `graph_nodes`: AST symbols, signatures, docstrings, content hashes, roles, and generation timestamps.
  - `graph_edges`: Directed dependency edges (`calls`, `imports`, `extends`, `implements`, `defines`).
  - `provider_runs`: Immutable ledger of extraction runs (`AST_HEURISTIC_PARSER` vs SCIP vs Codebase Memory, versions, argument digests, snapshot hashes, status, canonical project roots).
  - `provider_evidence`: Multi-provider provenance assertions keyed by run, target, capability, confidence score, and JSON payload.
  - `meta`: Key-value store tracking schema version, repository generation, and commit state.
- **Canonical Project Root Isolation**: All run recordings and evidence queries resolve `os.path.realpath(project_root)` before database queries or inserts, guaranteeing strict multi-tenant isolation.
- **Atomic Two-Phase Mutation Gateway**: All database-mutating operations acquire an exclusive file lock (`.sot/write.lock`) and execute inside `BEGIN IMMEDIATE` transactions.
- **Note Preservation**: User notes (`kind == 'note'`) are preserved across schema migrations and `sot clean --all` resets. *(Note: physically deleting the `.sot/sot.db` file from the disk destroys all database data including notes).*

---

## Installation

### From PyPI
```bash
pip install sot-graph            # zero-dependency core
pip install "sot-graph[all]"     # with MCP, analytics, watch, vector, tree-sitter extras
```

### From Source / Git
```bash
git clone https://github.com/minhgv/sot-graph.git
cd sot-graph
pip install -e ".[all,dev]"
```

### Optional Dependency Extras
- `sot-graph[mcp]`: MCP server and JSON-RPC stdio protocol (`mcp>=1.3,<2`).
- `sot-graph[analytics]`: Graph community detection and modularity analysis (`networkx>=3.0`, `scipy>=1.10`).
- `sot-graph[tokens]`: Fast Rust BPE tokenizer for prompt budgeting (`tiktoken>=0.7`).
- `sot-graph[watch]`: Real-time filesystem watcher daemon (`watchfiles>=0.21`).
- `sot-graph[vector]`: Hybrid FTS5 + vector retrieval (`sot search --hybrid`) (`sqlite-vec>=0.1.6`).
- `sot-graph[scip]`: Compiler-backed SCIP index importer (`protobuf>=4.21`).
- `sot-graph[tree-sitter]`: Polyglot Tree-sitter grammars (Go, Rust, Java, Kotlin, Swift, PHP, TS/JS, C/C++, Dart, Lua, Scala, SQL, Zig, ...).
- `sot-graph[all]`: All optional dependencies and polyglot Tree-sitter parsers.

---

## Verification & Test Suite

The test suite includes **1014 collected tests** covering unit functionality, multi-OS file locking, stateful Hypothesis property testing, fault injection (WAL crash simulation, disk-full ENOSPC simulation, mid-batch connection drops), cross-language AST extractions, and multi-provider trust chain boundary enforcement:

```bash
# Run full test suite with pytest (1014 collected; 2 win32-only tests skip on macOS/Linux)
pytest tests/ -v --strict-markers

# Run end-to-end quality gates script (Ruff + Pyright + Bandit + Pip-Audit + Coverage)
./scripts/quality_gates.sh

# Run trust chain hardening and symlink isolation test suite
pytest tests/test_trust_chain_hardening.py -v

# Run fault-injection and process-crash resilience tests
pytest tests/fault/test_fault_injection.py -v

# Run Hypothesis state-machine property invariant tests
pytest tests/property/test_invariants.py -v
```

---

## Open-Source Acknowledgments & Third-Party Licenses

`sot-graph` acknowledges and credits the following open-source projects:

1. **[Graphify](https://github.com/voidshard/graphify)** (MIT License): AST extraction logic foundation and multi-language tokenizers (`src/sot_graph/_vendor/graphify/`).
2. **[Tree-sitter](https://tree-sitter.github.io/tree-sitter/)** (MIT License): Incremental concrete syntax tree parsing system for polyglot AST extractors.
3. **[D3.js](https://d3js.org/)** (ISC / BSD-3-Clause License): Standalone force-directed graph visualizer (`sot viz`).
4. **[SQLite](https://www.sqlite.org/)** (Public Domain): Embedded relational, FTS5 full-text indexing, and Write-Ahead Logging (WAL) engine.

---

## License

MIT License. Copyright (c) 2026 Minh Giap.
