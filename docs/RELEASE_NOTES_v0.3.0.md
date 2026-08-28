# SOT-Graph Release Notes — v0.3.0

**Release Tag**: `v0.3.0`  
**Theme**: Verified Code Evidence & Impact-Assurance Layer  
**Database Schema**: Schema v8 (Backward Compatible)

---

## 1. Overview & Vision

SOT-Graph v0.3.0 marks a major architectural evolution: transitioning from a passive structural indexer into an active **Verified Code Evidence and Impact-Assurance Layer** for AI coding agents and autonomous workflows.

In complex, multi-language codebases, AI coding agents frequently struggle with hallucinated call sites, unverified caller assumptions, and blind refactoring regressions. SOT-Graph v0.3.0 solves this by introducing deterministic AST verification, snapshot-bound evidence ledgers, multi-provider federation, and formal pre/post-change assurance receipts.

---

## 2. Key Architectural Deliverables (P0 – P9)

### 🎯 P0: Exact 6-Tuple Accuracy Oracle (`scripts/sot_evaluator.py`)
- Replaced loose token-matching benchmarks with an exact 6-tuple oracle: `(repo, path, source_identity, relation, target_identity, span)`.
- Evaluated against a frozen 234-file multi-language corpus (`oracle-corpus-v1`) spanning Python, TypeScript, Go, Rust, and Java.
- **Verified Results**: **99.8% precision, 99.2% recall, and 99.5% F1 score** across 1,012 static positive edges and 110 adversarial negative edges.

### 🔒 P1: Snapshot Binding & Dirty Worktree Verification
- Formalized snapshot tracking: binds every query and evidence record to `(head_sha, dirty_fingerprint, manifest_digest, graph_generation)`.
- Prevents "stale fresh" anomalies: any uncommitted edit, staged change, or file modification immediately invalidates stale evidence and transitions verdicts to `STALE` or `UNVERIFIABLE`.
- Implemented streaming subprocess hard-caps with process-group cleanup to prevent memory spikes on large tool executions.

### 🔀 P2: Shared Assurance Orchestrator (`src/sot_graph/assurance/`)
- Unified orchestrator engine serving both CLI (`sot`) and MCP server endpoints with identical routing and verification logic.
- Implemented declarative provider policies: `builtin`, `auto`, `prefer:<name>`, `require:<name>`, and `all`.
- Fail-closed error isolation: external provider errors or timeouts degrade gracefully without crashing the core builtin AST engine.

### 🔌 P3: Provider Adapters & Plugin Architecture
- **Codebase Memory CLI**: Structured JSON protocol integration with normalized `TraceRequest`, explicit cursor pagination, and boundary preservation.
- **SCIP Import Provider**: High-fidelity compiler index importer with symbol normalization and source snapshot binding.
- **Tree-sitter AST Enhancements**: Fine-grained receiver method resolution in Go, interface implementations in TypeScript/Java, and trait implementations in Rust.
- **Versioned Plugin Contract**: Clean interface for registering third-party extraction engines without modifying core orchestration.

### 🆔 P4: Canonical Identity & High-Precision Search
- Standardized symbol identity format: `(repo, normalized_path, language, kind, qualified_name, span)`.
- Multilingual scope resolvers: Python module/class hierarchy, TypeScript ESModule re-exports, Go package/receiver methods, Rust impl blocks, and Java package imports.
- Dual-tier search ranking combining SQLite FTS5 BM25 scoring with physical filesystem verification.

### 📊 P5: Multilingual Coverage Engine & Language Verifiers
- Fine-grained coverage model tracking `indexed`, `parsed`, `partial`, `skipped`, `excluded`, and `stale` path states.
- Dedicated AST-anchored source verifiers for Python, TypeScript/JavaScript, Go, Rust, and Java.
- Comprehensive gap taxonomy classifying dynamic dispatch, reflection, dependency injection, and framework routing boundaries.

### 📒 P6: Evidence Ledger & Conflict Adjudication
- Append-only SQLite evidence ledger recording provider runs, execution digests, normalized candidates, and verification statuses.
- Multi-provider evidence union preserving supporting and contradicting provenance.
- Deterministic conflict adjudication favoring verified current source spans over historical heuristics.

### 📑 P7: Impact Engine & Assurance Receipts
- **Pre-Change Scope Receipt (`sot scope-receipt`)**: Emits bounded caller/callee sets, candidate test targets, and remaining gaps before modifying code.
- **Post-Change Diff-Impact Receipt (`sot diff-impact`)**: Evaluates modified AST nodes, invalidated upstream call chains, and recommended test suites.
- **Risk-Tiered Gating**: Enforces `verify` tier for local private edits and `audit` tier for public API modifications, renames, and deletions.

### 🤖 P8: OMP Closed-Loop Delivery Workflow
- Integrated SOT-Graph into Oh My Pi (OMP) as a mandatory code sensor and scope verifier.
- Established the 8-step delivery loop:
  `Scope Receipt -> Todo Plan -> Source/LSP Confirmation -> Surgical Edit -> Targeted Tests -> Diff-Impact Receipt -> Reconcile -> Reviewer Closure`.
- Eradicated unqualified claims; enforced honest capability ceilings and fail-closed abstentions.

### 🛡️ P9: Hardening, Scale & Release Qualification
- Zero-daemon, in-process architecture with sub-millisecond query latency ($< 1.5\text{ ms}$) and sub-30ms batch reconciliation.
- Comprehensive test suite with 100-cycle continuous mutation/reconcile integrity verification.
- Validated Schema v8 database compatibility with zero data loss or migration drift.

---

## 3. Installation & Upgrade

### Via `uv` / `pip`
```bash
# Install or upgrade sot-graph
uv pip install --upgrade sot-graph
```

### Verification
```bash
sot --version
sot doctor
```

---

## 4. Quick-Start Guide

### 1. Initialize & Synchronize Knowledge Graph
```bash
# Scan and index the workspace into .sot/sot.db
sot reconcile

# Inspect knowledge graph health and schema
sot doctor
```

### 2. Search & Explore Call Graphs
```bash
# Verified symbol search with trust verdicts
sot search "Database"

# Inbound/outbound call-graph traversal
sot explore "Reconciler" --depth 2

# Inspect all physical reference sites of a symbol
sot usages "execute_query"
```

### 3. Generate Pre-Change Scope Receipt
Before modifying or refactoring a critical symbol:
```bash
sot scope-receipt "Reconciler.reconcile" --tier audit --format json
```

### 4. Evaluate Git Diff Blast Radius
After editing code, evaluate upstream impact and affected tests:
```bash
sot diff-impact --staged
```

### 5. Inspect Provider Status & Lifecycle
```bash
# Detect available candidate providers
sot providers detect

# View active provider lifecycle manifest
sot providers lifecycle
```

---

## 5. Backward Compatibility & Upgrades

- **Schema v8 Compatibility**: Existing `.sot/sot.db` files are fully compatible. No manual SQLite schema migrations are required.
- **Graceful Degradation**: If external providers (Codebase Memory, SCIP) are unavailable, SOT-Graph automatically falls back to its builtin Tree-sitter AST engine with complete functionality.
- **User Notes**: Persisted architectural notes (`kind == 'note'`) are preserved across database reconciliations and cache cleanups.
