# Applying sot-graph Across the AI-Assisted Software Development Life Cycle (AI SDLC)

> **Comprehensive Guide to Integrating `sot-graph` as the Authoritative Single Source of Truth Knowledge Layer for AI Coding Agents.**  
> *Eliminate Phantom Anchors, prevent path hallucinations, eradicate Cold Start Redundancy, and constrain Blast Radius during active coding loops.*

---

## 📑 Table of Contents
1. [Context & Core Challenges in AI SDLC](#-1-context--core-challenges-in-ai-sdlc)
2. [Detailed 6 Phases of AI SDLC with sot-graph](#-2-detailed-6-phases-of-ai-sdlc-with-sot-graph)
   - [Phase 1: Discovery & Architecture Scoping](#phase-1-discovery--architecture-scoping)
   - [Phase 2: Generation & Active Development Loop](#phase-2-generation--active-development-loop)
   - [Phase 3: Refactoring & Blast Radius Mitigation](#phase-3-refactoring--blast-radius-mitigation)
   - [Phase 4: Code Review & CI/CD Verification Gate](#phase-4-code-review--cicd-verification-gate)
   - [Phase 5: Knowledge Retention & Architecture Decision Records (ADR)](#phase-5-knowledge-retention--architecture-decision-records-adr)
   - [Phase 6: Maintenance, Graph Hygiene & Database Optimization](#phase-6-maintenance-graph-hygiene--database-optimization)
3. [Comparison Matrix: Traditional AI SDLC vs AI SDLC with sot-graph](#-3-comparison-matrix-traditional-ai-sdlc-vs-ai-sdlc-with-sot-graph)
4. [Automated CI/CD & Git Hooks Integration](#-4-automated-cicd--git-hooks-integration)
5. [Sample Agent Configuration (AGENTS.md)](#-5-sample-agent-configuration-agentsmd)
6. [Token Economy & Cost Efficiency Analysis](#-6-token-economy--cost-efficiency-analysis)
---

## 🎯 1. Context & Core Challenges in AI SDLC

In the era of autonomous **AI Coding Agents** (such as Oh My Pi, Claude Code, Cursor, Windsurf, Devin) authoring code daily, traditional software development workflows have evolved into **AI-Assisted SDLC**.

However, contemporary AI coding agents suffer from **3 Critical Failure Modes**:

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
3 MAJOR BOTTLENECKS OF CONTEMPORARY AI CODING AGENTS
├──────────────────────────────┬─────────────────────────────┬────────────────────────────┤
│   1. COLD START REDUNDANCY   │     2. PHANTOM ANCHORS      │   3. REFACTOR BLIND SPOT   │
│                              │                             │                            │
│  Every session starts from   │  The agent remembers files  │  Modifying a core utility  │
│  scratch. The agent rebuilds │  or functions that have     │  silently breaks 15 distant│
│  existing utilities, causing │  been deleted or renamed,   │  modules that the agent is │
│  codebase bloat (3x sprawl). │  generating dead patches.   │  completely unaware of.    │
└──────────────────────────────┴─────────────────────────────┴────────────────────────────┘
```

`sot-graph` was engineered to provide a **Physically Verified Knowledge Layer**. By anchoring the **Filesystem as the Single Source of Truth (SSOT)**, backed by **SQLite FTS5 + WAL** and **in-process deterministic graph algorithms**, `sot-graph` seamlessly guides agents across all 6 phases of software engineering.

---

## 🚀 2. Detailed 6 Phases of AI SDLC with sot-graph

```
                  ┌────────────────────────────────────────────────────────┐
                  │              AI SDLC WITH SOT-GRAPH KNOWLEDGE LAYER    │
                  └────────────────────────────────────────────────────────┘
                                              │
    ┌─────────────────────────────────────────┼─────────────────────────────────────────┐
    │                                         │                                         │
    ▼                                         ▼                                         ▼
[ 1. DISCOVERY & SCOPING ]            [ 2. GENERATION & DEV ]             [ 3. REFACTORING & IMPACT ]
• Check existing reusable logic       • Disk-verified symbol lookup       • 2-hop Blast Radius analysis
• Prevent helper duplication          • Auto-Heal on path relocations     • God Node & Cohesion diagnostics
• Louvain community boundaries        • 2-way atomic pending edges        • Modularity Q protects contracts
    │                                         │                                         │
    ├─────────────────────────────────────────┼─────────────────────────────────────────┤
    │                                         │                                         │
    ▼                                         ▼                                         ▼
[ 4. CODE REVIEW & CI/CD ]            [ 5. KNOWLEDGE RETENTION ]          [ 6. OPS & GRAPH HYGIENE ]
• Detect Architectural Drift          • Persist complex ADR decisions     • Prune stale records with `clean`
• Auto-Purge deleted paths            • Zero context loss across chats    • Defrag database with `vacuum`
• Quality gate prevents divergence    • Instant FTS5 BM25 retrieval       • Sub-millisecond read latency
```

---

### Phase 1: Discovery & Architecture Scoping

#### The Real-World Challenge
- When given a user prompt (e.g., *"Implement JWT token validation with role-based access control"*), agents often jump straight to writing code from scratch, unaware that `src/auth/` or `utils/` already contains HMAC signing, claims parsing, or expiration validation helpers.
- Primitive `grep`/`find` scans flood the LLM context window with thousands of irrelevant lines, burning tokens and degrading reasoning depth.

#### How `sot-graph` Solves It
1. **Rapid Verified Search (`sot search` / MCP `sot_search`):**
   The agent queries the entire codebase via SQLite FTS5 (BM25 ranking) in a single command:
   ```bash
   ./bin/sot search "jwt token validation role"
   ```
   The engine responds immediately (< 1.2ms) with authoritative **Trust Verdicts**:
   - `[STRONG]`: File physically exists on disk and contains ≥ 50% query keyword coverage (Agent can immediately use/import).
   - `[WEAK]`: Semantic or header match (Agent should inspect before implementing).
2. **Architecture Scoping via Louvain Communities (`sot cluster` / `sot report`):**
   The agent discovers the modular structure without reading raw files:
   ```bash
   ./bin/sot cluster --min-size 3
   ```
   The response enumerates functional clusters (Auth, Billing, Notifications...) along with the global Modularity score Q, ensuring new files are placed in their proper architectural domain.

---

### Phase 2: Generation & Active Development Loop

#### The Real-World Challenge
- **Phantom Anchors**: A developer renames `src/services/user_service.py` to `src/core/services/user.py`. The agent remembers the old path from previous turns and generates `from src.services.user_service import UserService` → immediate runtime failure.
- **Cross-Import & Out-of-Order Indexing**: File A imports a class from File B before File B has been indexed, breaking relationship graphs.

#### How `sot-graph` Solves It
1. **Auto-Rehome Mechanism (`[REBUILT]`):**
   When the agent looks up `UserService`, if the old path is missing, `verifier.py` scans disk basenames, detects the relocated file at `src/core/services/user.py`, updates SQLite, and returns `[REBUILT]`. The agent writes the correct import on the first pass!
2. **Two-Way Pending Edge Resolution (`db.resolve_pending_edges`):**
   Unresolved imports/calls are staged in `pending_edges`. The moment the target file is parsed, a single atomic SQL transaction promotes them into fully resolved `graph_edges`.
3. **Microsecond Reconciliation (Fast Dirty Check):**
   During active coding, calling `sot reconcile` takes only **~24.1ms**. The reconciler performs an O(1) comparison of `(size, mtime_ms)`, re-parsing only the single file that actually changed.

---

### Phase 3: Refactoring & Blast Radius Mitigation

#### The Real-World Challenge
- When asked to *"Refactor `process_payment(amount)` to `process_payment(amount, currency, idempotency_key)`"*, the agent typically updates the signature and 1 or 2 nearby call sites.
- Dozens of indirect callers across other packages are overlooked, creating silent regressions in staging.

#### How `sot-graph` Solves It
1. **2-hop Blast Radius Analysis (`sot explore` / MCP `sot_explore`):**
   Before touching the function, the agent runs:
   ```bash
   ./bin/sot explore "PaymentService.process_payment" --depth 2
   ```
   The engine performs a bounded 2-step BFS traversal, listing:
   - Direct callers (Incoming Edges - Hop 1).
   - Higher-level upstream services depending indirectly (Upstream Callers - Hop 2).
2. **God Node Diagnostics:**
   If a symbol's degree exceeds `Cutoff = μ + 1.5σ`, the system flags a warning:
   ```
   ⚠️ WARNING: 'PaymentService' is a GOD NODE with Blast Radius = 28 [CRITICAL]
   Modifying this symbol will impact 5 architectural communities.
   ```
   The agent proactively updates all upstream callers and expands unit test coverage.
3. **Cluster Cohesion Scoring (C < 0.4):**
   Identifies tightly coupled modules so the agent can suggest clean interface decoupling.

---

### Phase 4: Code Review & CI/CD Verification Gate

#### The Real-World Challenge
- When multiple developers and agents merge PRs into `main`, files get deleted but architectural knowledge remains stale, resulting in **Architectural Drift**.

#### How `sot-graph` Solves It
1. **Deep Drift Auditing (`sot verify --deep` / MCP `sot_verify_drift`):**
   In CI/CD pipelines or pre-commit checks, execute:
   ```bash
   ./bin/sot verify --deep
   ```
   The system verifies every physical file's SHA-256 hash against the journal:
   - Automatically purges permanently deleted paths (`[REMOVED]`).
   - Reports exact drift percentages and anomalous files.
2. **CI/CD Quality Gate:**
   If drift exceeds allowable thresholds, CI can automatically invoke `sot reconcile` to ensure 100% database-to-disk consistency before deployment.

---

### Phase 5: Knowledge Retention & Architecture Decision Records (ADR)

#### The Real-World Challenge
- **Context Reset**: Every new chat session wipes agent memory. A hard-fought lesson regarding PostgreSQL deadlock handling resolved yesterday is repeated as a bug by another agent today.

#### How `sot-graph` Solves It
1. **Virtual Knowledge Anchors (`sot insert` & `[NOPATH]`):**
   Upon solving a complex bug or agreeing on an architectural standard, the agent persists an ADR directly into SQLite:
   ```bash
   ./bin/sot insert \
     --title "Postgres Deadlock Prevention in Order Processing" \
     --body "Always acquire row locks in deterministic ID ascending order (SELECT FOR UPDATE ORDER BY id ASC)." \
     --keywords "postgres,deadlock,locking,order_service"
   ```
2. **Cross-Session Persistence Without Re-reading Code:**
   In future sessions, when any agent searches:
   ```bash
   ./bin/sot search "deadlock order locking"
   ```
   The `[NOPATH]` virtual anchor appears at the top of the search results, instantly enforcing architectural compliance.

---

### Phase 6: Maintenance, Graph Hygiene & Database Optimization

#### The Real-World Challenge
- Over months of active development with thousands of file mutations, graph databases can accumulate orphaned nodes, fragmented B-Trees, and degraded FTS index speed.

#### How `sot-graph` Solves It
1. **Safe Database Pruning (`sot clean`):**
   - Supports `--dry-run` to preview deleted records safely without modifying disk:
     ```bash
     ./bin/sot clean --dry-run
     ```
   - Prunes all dead paths and orphaned edges:
     ```bash
     ./bin/sot clean --all --yes
     ```
2. **B-Tree Optimization & WAL Checkpointing (`sot vacuum`):**
   - Restructures SQLite FTS5 storage and defragments pages to guarantee sub-**1.2ms** query latency:
     ```bash
     ./bin/sot vacuum
     ```
3. **Non-Blocking WAL Concurrency:**
   - During maintenance, agents can still execute concurrent `search` and `explore` commands via `WAL` mode and `mode=ro` (Read-Only) connections without lock contention.

---

## 📊 3. Comparison Matrix: Traditional AI SDLC vs AI SDLC with sot-graph

| Evaluation Criterion | Traditional AI SDLC (Without sot-graph) | AI SDLC with sot-graph |
| :--- | :--- | :--- |
| **Path Grounding Accuracy** | **Poor (Prone to Hallucinations)**: Agents guess stale paths or write code against deleted files. | **Absolute (100% Verified)**: Every node is physically verified on disk by `TrustVerifier`. |
| **Code Reuse Capability** | **Low**: Frequently reinvents existing utilities (Cold Start Redundancy). | **High**: `sot search` with FTS5 BM25 locates existing utilities in < 1.2ms. |
| **Refactoring Control** | **Blind Edits**: Modifies only local files, unaware of broken indirect callers. | **Comprehensive**: Analyzes **2-hop Blast Radius** and flags **God Nodes** prior to edits. |
| **Context Retrieval Latency** | **Slow (10s - 30s)**: Requires reading entire files or querying remote Vector DBs. | **Ultra-Fast (~1.17ms P95)**: Queries local in-process SQLite FTS5 directly. |
| **Infrastructure Overhead** | **Heavy**: Demands Docker, Vector DBs, background daemons consuming 1-2GB RAM. | **Zero-Daemon (< 25MB RAM)**: Embedded in-process Python/SQLite CLI & MCP server. |
| **Self-Healing Capabilities** | **None**: Directory moves (`mv`) completely break vector/agent memory indices. | **Automated**: `Auto-Rehome` tracks moved files; `Auto-Purge` cleans dead paths. |

---

## ⚙️ 4. Automated CI/CD & Git Hooks Integration

### 1. Git Pre-Commit Hook (`.git/hooks/pre-commit`)
Automatically reconciles the knowledge graph and prevents commits when drift is detected:

```bash
#!/bin/bash
# .git/hooks/pre-commit
echo "[sot-graph] Reconciling knowledge graph before commit..."
./bin/sot reconcile --batch-size 64

# Integrity verification
./bin/sot verify
if [ $? -ne 0 ]; then
  echo "[sot-graph] ❌ Verification failed. Please resolve discrepancies."
  exit 1
fi
echo "[sot-graph]  Knowledge graph is fully in sync with filesystem."
```

### 2. GitHub Actions Workflow (`.github/workflows/sot_verification.yml`)
Audits architecture and updates structural reports automatically on every Pull Request:

```yaml
name: SOT-Graph Architecture Audit

on:
  push:
    branches: [ main, master ]
  pull_request:
    branches: [ main, master ]

jobs:
  verify-graph:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Run Test Suite
        run: |
          PYTHONPATH="src" python3 -m unittest discover -s tests -p "test_*.py" -v

      - name: Deep Verify Knowledge Graph
        run: |
          ./bin/sot reconcile
          ./bin/sot verify --deep

      - name: Generate Architecture Report
        run: |
          ./bin/sot report --sigma 1.5 --min-size 2 -o ARCHITECTURE_REPORT.md

      - name: Upload Architecture Artifact
        uses: actions/upload-artifact@v4
        with:
          name: architecture-report
          path: ARCHITECTURE_REPORT.md
```

---

## 🤖 5. Sample Agent Configuration (AGENTS.md)

Add the following protocol to `AGENTS.md` or `.cursorrules` in your project root so that all AI Coding Agents (Oh My Pi, Claude Code, Cursor, Windsurf) adhere to the knowledge reuse workflow:

```markdown
## SOT-Graph Knowledge Reuse & Architecture Protocol

Before implementing any code changes, new features, or refactoring:

1. **Check for existing reusable logic (Prevent Cold Start Redundancy):**
   Run: `sot search "<feature_or_keyword>"`
   - `[STRONG]`: High confidence - reuse the class/function at the reported file:line.
   - `[WEAK]`: Semantic match - inspect the file before implementing from scratch.
   - `[REBUILT]`: File was automatically relocated after renaming - use the updated path.

2. **Analyze blast radius before modifying core symbols (Blast Radius Check):**
   Run: `sot explore "<function_or_class_name>" --depth 2`
   - Review direct callers (Hop 1) and indirect callers (Hop 2) to update all call sites.
   - If the symbol is marked as `GOD NODE`, verify and update all associated unit test cases.

3. **Reconcile after completing changes:**
   Run: `sot reconcile` to synchronize the knowledge graph with disk.

4. **Persist important architectural decisions (Knowledge Retention):**
   After resolving a non-trivial bug or establishing a project pattern, persist it:
   `sot insert --title "<Title>" --body "<Detailed solution explanation>" --keywords "k1,k2"`
```

---

## 💰 6. Token Economy & Cost Efficiency Analysis

A fundamental operational question: **"When integrating sot-graph into a codebase, what is the token overhead?"**

> **Core Finding:** `sot-graph` itself consumes **0 LLM Tokens** ($0.00 USD) for indexing, storage, and retrieval, while enabling AI Agents to **SAVE between 65% and 90% of token ingestion into the Context Window** across the software lifecycle.

---

### 1. Intrinsic Operational Cost: 0 LLM Tokens ($0.00 USD)

Unlike cloud RAG or vector database solutions (which consume continuous API credits for LLM summarization and embedding vectors):

1. **AST Parsing & Extraction:** 100% local CPU processing via Tree-sitter / Regex → **0 Tokens**.
2. **Indexing & SHA-256 Hashing:** All hash tables and SQLite FTS5 inverted indices run in-process → **0 Tokens**.
3. **Graph Algorithms & Clustering:** Louvain community detection, Modularity Q, God Node cutoff (μ + 1.5σ), and BFS 2-hop traversals execute in RAM → **0 Tokens**.
4. **Zero Embedding Cost:** No dependency on or billing from external embedding APIs (e.g., `text-embedding-3-small` or `ada-002`).

---

### 2. Quantifying Context Window Token Ingestion

When agents interact with `sot-graph` via CLI or MCP Stdio protocol, payloads injected into the Context Window are extremely compact:

| CLI Command / MCP Tool | Returned Data Payload | Context Tokens Ingested |
| :--- | :--- | :---: |
| **`sot search`** / `sot_search` | 3–5 candidate nodes with `[STRONG]` labels, exact file paths, and line numbers. | **~150 – 350 tokens** |
| **`sot explore`** / `sot_explore` | 2-hop relationship tree (direct callers, upstream dependencies, call sites). | **~300 – 700 tokens** |
| **`sot cluster`** / `sot_communities` | List of functional clusters and Modularity score Q. | **~200 – 450 tokens** |
| **`sot verify`** / `sot_verify_drift` | SHA-256 drift report and list of anomalous files. | **~80 – 200 tokens** |
| **`sot insert`** | Virtual knowledge anchor confirmation (ADR / Bug note). | **~50 – 100 tokens** |

---

### 3. Head-to-Head Comparison: Net Token Savings

Consider a typical real-world development task: **"Add Role-Based Access Control (RBAC) validation logic to an existing API in a 300-file repository"**.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│             TOKEN CONSUMPTION COMPARISON DURING A SINGLE AGENT SESSION                 │
├─────────────────────────────────────────────┬──────────────────────────────────────────┤
│    WITHOUT SOT-GRAPH (TRADITIONAL)          │           WITH SOT-GRAPH                 │
├─────────────────────────────────────────────┼──────────────────────────────────────────┤
│ 1. Agent runs grep/find, gets 40 matches    │ 1. Agent runs `sot search`               │
│    -> Ingests 4,000 tokens of raw output.   │    -> Ingests 250 tokens of FTS5 hits.   │
│                                             │                                          │
│ 2. Reads 15 files to understand context     │ 2. Agent locates exact `auth.py` via     │
│    (each file 400 lines ~ 2,500 tokens)     │    [STRONG] verdict; reads only 60 lines │
│    -> Consumes 37,500 tokens in context.    │    -> Consumes 400 tokens.               │
│                                             │                                          │
│ 3. Edits function, silently breaks 4 callers│ 3. Runs `sot explore AuthService`, sees  │
│    due to unknown dependencies.             │    all 4 dependent modules immediately   │
│    -> Tests fail, 3 debug loops required    │    -> Synchronously updates all callers  │
│    -> Consumes 45,000 tokens reading logs.  │    -> Consumes 600 tokens.               │
│                                             │                                          │
│ 4. Path hallucination (Phantom Anchor)      │ 4. Auto-Rehome & Auto-Purge eliminate    │
│    on a recently renamed file               │    100% of dead paths                    │
│    -> Consumes 20,000 tokens retrying.      │    -> Consumes 0 retry tokens.           │
├─────────────────────────────────────────────┼──────────────────────────────────────────┤
│ TOTAL CONSUMPTION: ~106,500 TOKENS          │ TOTAL CONSUMPTION: ~1,250 TOKENS         │
│ (Estimated API Cost: ~USD 0.35 - 1.50/session)│ (Estimated API Cost: ~USD 0.003 - 0.015) │
└─────────────────────────────────────────────┴──────────────────────────────────────────┘
                      👉 NET TOKEN SAVINGS: ~98.8%!
```

---

### 4. Key Economic Benefits in Production

1. **Context Window Hygiene & LLM Reasoning Preservation:**
   Flooding the Context Window with tens of thousands of irrelevant code tokens causes *Context Window Degradation*, impairing LLM logical reasoning and increasing syntax errors. `sot-graph` feeds only physically grounded, relevant lines, enabling coding sessions to run productively all day without memory saturation.

2. **Debug Loop Elimination:**
   Whenever an agent generates a patch targeting a hallucinated path (Phantom Anchor) or breaks an indirect dependency, the developer or agent spends 3 to 5 extra prompt turns troubleshooting. Eliminating errors at the discovery stage saves millions of prompt tokens across an engineering organization.

---

## 📄 License
MIT License. Copyright (c) 2026 Minh Giap.
