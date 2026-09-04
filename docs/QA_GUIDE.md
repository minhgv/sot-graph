# 📚 SOT-Graph: Complete Q&A & Real-World Implementation Guide (Q&A Guide)

> **Self-Healing, Anti-Hallucination & Operational Knowledge Architecture for AI Coding Agents.**  
> *Filesystem as the Single Source of Truth (SSOT) — Zero External Daemons — Sub-Millisecond Latency.*

---

## 🌐 Ways to View This Document:
- 📖 **Directly on GitHub (Markdown UI)**: Viewing this document (using the expandable accordions below).
- ⚡ **Interactive Standalone HTML (Live Search & Filter)**: [Open on HTMLPreview (GitHub)](https://htmlpreview.github.io/?https://github.com/minhgv/sot-graph/blob/main/sot_qa_guide.html)
- 💻 **Local Offline Browser**: `open sot_qa_guide.html` (macOS) or `xdg-open sot_qa_guide.html` (Linux).

---

## 📑 Quick Navigation

1. [Topic 1: Core Architecture & Anti-Hallucination](#-1-core-architecture--anti-hallucination)
2. [Topic 2: Self-Healing & Data Integrity](#-2-self-healing--data-integrity)
3. [Topic 3: AI Agent Integration & MCP Protocol](#-3-ai-agent-integration--mcp-protocol)
4. [Topic 4: Graph Analytics & Visualizations](#-4-graph-analytics--visualizations)
5. [Topic 5: Operations, Maintenance & Performance](#-5-operations-maintenance--performance)
6. [Topic 6: Edge Cases & Incident Handling](#-6-edge-cases--incident-handling)

---

## 🛡️ 1. Core Architecture & Anti-Hallucination

<details open>
<summary><h3>Q1: Why is sot-graph called a "Single Source of Truth"? What is the difference between a Filesystem-first architecture and traditional Vector/Graph RAG?</h3></summary>

Traditional RAG and Agent Memory systems (relying on Vector DBs, Neo4j, Redis) store knowledge as a **detached snapshot**. When a developer modifies code, renames a file, or deletes a directory, the database remains oblivious until a manual re-indexing occurs. This produces **Phantom Anchors (Dead Paths)** — where AI Agents retrieve stale paths and generate patches for non-existent files.

> [!IMPORTANT]
> **The Golden Rule of sot-graph:**  
> *"Filesystem is the Single Source of Truth — The knowledge graph is a verified, bounded evidence index: anchors are span-verified on disk; verdicts are advisory and scope-bounded."*

Every signal from file watchers, git hooks, or CLI commands is treated merely as a hint (*"please inspect this path"*). The system **never blindly trusts cached records**; it physically verifies file existence and content on disk before delivering results to the Agent.

| Characteristic | Traditional Vector / Graph RAG | sot-graph (SSOT Architecture) |
| :--- | :--- | :--- |
| **Source of Truth** | Vector Embeddings / Graph Nodes in external DB | **Physical Files on Filesystem** |
| **Deleted File Handling** | Stale vectors remain (causing path hallucinations) | **Instant Auto-Purge at query time** |
| **Infrastructure Overhead** | External servers required (Neo4j, Qdrant, Chroma, Java/Node) | **Zero Daemon**: Embedded SQLite WAL (< 25MB RAM) |
| **Query Latency** | 50ms - 500ms (Network / RPC round-trips) | **< 1.5ms (P95)** via SQLite FTS5 BM25 |

</details>

---

<details>
<summary><h3>Q2: If I modify a single line in a file, does the system detect it, and how does reconciliation work?</h3></summary>

**YES — detected by the next reconciliation pass.**

The `sot_graph.reconciler` coordinator employs a two-tier defense mechanism to capture even the smallest file modification:

1. **Tier 1 - Fast Dirty Check via Filesystem Metadata (O(1)):**
   When modifying a line of code, the operating system instantly updates `st_mtime` (millisecond resolution) and typically alters `st_size` (byte length). The Reconciler compares the `(size, mtime_ms)` pair against the `file_journal` table. If different, the file is marked dirty in microseconds.

2. **Tier 2 - Integrity Guard via SHA-256 Hashing:**
   If a single character is modified such that file size remains identical and timestamp collisions occur, `_hash(path)` re-computes the SHA-256 digest. Due to the cryptographic avalanche effect, the digest diverges completely from the stored database state, ensuring no mutation is missed.

```python
# src/sot_graph/reconciler.py:270-281
prior = journal_cache.get(path)
if prior and prior.get("size") == size and prior.get("mtime_ms") == mtime_ms:
    current_sha = self._hash(path)
    if prior.get("sha256") == current_sha:
        continue  # Skip cleanly: file has genuinely not changed
jobs.append(ParseJob(path, self.root_dir, size, mtime_ms))
```

Once flagged as dirty, the Reconciler executes an **Atomic Full-File Replacement** in SQLite: clearing old nodes and edges belonging to that path and inserting freshly extracted AST nodes within a single ACID transaction.

</details>

---

<details>
<summary><h3>Q3: How does the Trust Verdict System work? What are the exact meanings of [STRONG], [WEAK], [REBUILT], [REMOVED], [NOPATH]?</h3></summary>

When an Agent runs `sot search "<query>"`, all candidate hits from FTS5 pass through `TrustVerifier.verify_hit` for physical on-disk validation:

```
[Agent Query] ──> [SQLite FTS5 (BM25)] ──> [Candidate Node]
                                    │
        ┌───────────────────────────┴───────────────────────────┐
        ▼                                                       ▼
[File exists on disk?]                                  [File MISSING on disk?]
├── Yes: Read first 256KB of file                                   │
│   ├── Query keywords matched >= 50% ──> [STRONG]                  ▼
│   └── Query keywords matched < 50%  ──> [WEAK]        [find_rehome: Scan disk by basename]
│                                                       ├── Exactly 1 candidate found:
│                                                       │   ├── db.update_node_path(...)
│                                                       │   └── Returns [REBUILT]
│                                                       └── No match (permanently deleted):
│                                                           ├── db.delete_path(...)
│                                                           └── Returns [REMOVED]
```

| Verdict Label | Trigger Condition | Recommended Agent Action |
| :--- | :--- | :--- |
| `[STRONG]` | File physically exists AND contains **≥ 50%** of search query keywords. | **Absolute Trust**: Navigate directly to the reported file and line number. |
| `[WEAK]` | File exists but keyword coverage is **< 50%** (e.g. title/symbol match only). | **Caution**: Skim file context before applying logic. |
| `[REBUILT]` | File was renamed or moved; path has been automatically updated in SQLite. | **Auto-Healed**: Use the updated, relocated path immediately. |
| `[REMOVED]` | File was permanently deleted from disk. | **Auto-Purged**: Node deleted from DB; ignore this search result. |
| `[NOPATH]` | Virtual knowledge note (Architecture Decision Record, conventions, tips). | **Knowledge Anchor**: Treat as an authoritative engineering guideline. |

</details>

---

<details>
<summary><h3>Q4: How does Two-Way Pending Edge Resolution solve circular imports and out-of-order indexing?</h3></summary>

In real-world projects, File A calls `AuthService.validate()` in File B, but File A might be scanned by the Reconciler before File B. At that point, the symbol `AuthService.validate` does not yet exist in the database.

**sot-graph Resolution Mechanism:**
1. **Step 1:** The unresolved dependency is staged in `pending_edges (path, src, dst_symbol, relation, line)`.
2. **Step 2:** When File B is subsequently scanned and registers `AuthService.validate`, `resolve_all_pending_edges()` executes a single atomic SQL statement:

```sql
-- src/sot_graph/db.py:263-273
-- Atomically promote pending edges to full graph_edges
INSERT OR REPLACE INTO graph_edges(path, src, dst, relation, line)
SELECT p.path, p.src, (
    SELECT n.id FROM graph_nodes n 
    WHERE n.symbol = p.dst_symbol 
    ORDER BY n.id LIMIT 1
), p.relation, p.line
FROM pending_edges p 
WHERE EXISTS (SELECT 1 FROM graph_nodes n WHERE n.symbol = p.dst_symbol);

-- Clean up resolved pending edges
DELETE FROM pending_edges 
WHERE EXISTS (SELECT 1 FROM graph_nodes n WHERE n.symbol = pending_edges.dst_symbol);
```

As a result, indexing order is completely decoupled, ensuring **deterministic graph convergence** regardless of file traversal sequence.

</details>

---

## 🩹 2. Self-Healing & Data Integrity

<details>
<summary><h3>Q5: When a file is permanently deleted via rm, how does the database handle it so the Agent doesn't read dead code?</h3></summary>

There are two distinct paths for `sot-graph` to detect and purge deleted files:

1. **Active Reconciliation (`sot reconcile`):**  
   The Reconciler walks the disk tree and compares the current physical path set against `_known_abs_paths()` in the database. Any path present in the DB but absent from disk is pruned immediately via `db.delete_path(path)`.

2. **Passive Self-Healing at Query Time (`sot search`):**  
   If an Agent executes a search before `sot reconcile` is called, `TrustVerifier.verify_hit` encounters `os.path.exists(path) == False`. It attempts a rehome scan; upon finding no candidate, it **deletes the stale record immediately during the search call** and returns `[REMOVED]`:

```python
# src/sot_graph/verifier.py:139-141
db.delete_path(requested)
return "REMOVED", 0.0, requested
```

> [!TIP]
> **Outcome:** Agents never suffer from Phantom Anchors because stale nodes are eliminated on first contact.

</details>

---

<details>
<summary><h3>Q6: When a file is moved (e.g., mv src/utils.py src/helpers/utils.py), how does Auto-Rehome work?</h3></summary>

When a file is moved or its parent directory renamed, its prior path becomes invalid. The `TrustVerifier.find_rehome` routine handles this gracefully:

1. Extracts `basename = "utils.py"` from the missing path.
2. Performs a fast search across the project tree (skipping `node_modules`, `.git`, `venv`).
3. If **EXACTLY 1 candidate file** named `utils.py` is found at `src/helpers/utils.py`:
   - Invokes `db.update_node_path(node_id, old_path, new_path)`.
   - Updates the path and label attributes in `graph_nodes`.
   - Returns the verdict `[REBUILT]` alongside the new path.
4. If **≥ 2 candidate files** match the basename (ambiguous match): The system refuses to guess, safely purges the stale path, and awaits the next `sot reconcile` run.

</details>

---

<details>
<summary><h3>Q7: Why does the database never accumulate stale or dead functions when a developer deletes functions from a file?</h3></summary>

Many graph databases accumulate dead records because they rely on `UPSERT` operations (updating existing rows and inserting new ones without removing functions deleted from the source file).

`sot-graph` enforces **Atomic Full-File Replacement** inside `Database.commit_file_batch`:

```python
# src/sot_graph/db.py:216-218
# Purge all previous nodes, edges, and pending edges belonging to this file
self.conn.execute("DELETE FROM graph_nodes WHERE path = ?", (path,))
self.conn.execute("DELETE FROM graph_edges WHERE path = ?", (path,))
self.conn.execute("DELETE FROM pending_edges WHERE path = ?", (path,))
```

It then inserts the newly extracted classes, functions, and call edges from the current file snapshot. If you delete 3 functions from `service.py`, those 3 symbols vanish from the database within the exact same ACID transaction.

</details>

---

## 🤖 3. AI Agent Integration & MCP Protocol

<details>
<summary><h3>Q8: How do I integrate sot-graph into Oh My Pi (OMP), Claude Code, Cursor, and OpenCode?</h3></summary>

`sot-graph` provides 3 official adapters in `src/sot_graph/adapters/`:

1. **Oh My Pi / OMP Integration (`~/.omp`):**  
   Copy the TypeScript extension to the OMP extensions directory:
   ```bash
   cp src/sot_graph/adapters/omp_extension.ts ~/.omp/agent/extensions/sot_graph.ts
   ```
   Exposes 4 native agent tools: `sot_search`, `sot_explore`, `sot_reconcile`, `sot_insert`.

2. **Claude Code / Cursor / Codex Integration:**  
   Add the contents of `src/sot_graph/adapters/AGENTS.md` to `AGENTS.md` or `.cursorrules` in your repository root to guide agents toward pre-code knowledge retrieval.

3. **OpenCode Integration:**  
   Configure tools in `.opencode.json` pointing to `src/sot_graph/adapters/opencode_tools.json`.

</details>

---

<details>
<summary><h3>Q9: What tools does the MCP (Model Context Protocol) Server provide to LLMs? Why is the MCP server strictly Read-Only?</h3></summary>

Running `./bin/sot mcp` launches a standard MCP Stdio Server exposing 5 tools and 2 resources to LLMs:

- `sot_search`: Search on-disk verified codebase symbols and knowledge notes.
- `sot_explore`: Multi-hop relationship traversal and call graph inspection.
- `sot_verify_drift`: Non-mutating drift audit between graph state and filesystem.
- `sot_architecture_report`: Generates a Markdown architectural report with God Node diagnostics.
- `sot_communities`: Lists functional modules and cohesion metrics.
- **MCP Resources:** `sot://stats` (global repository metrics) and `sot://node/{id}` (entity details).

> [!WARNING]
> **Why is MCP strictly Read-Only?**  
> To guarantee *Determinism* and eliminate SQLite database lock contention when dozens of concurrent AI subagents query the database simultaneously. All mutations are restricted to the standalone Reconciler process.

</details>

---

<details>
<summary><h3>Q10: What is the standard AI Agent workflow (Knowledge Reuse Protocol) when starting a coding task?</h3></summary>

To optimize token consumption and prevent redundant code implementation, agents follow a 4-step protocol:

1. **Step 1 - Retrieve Existing Logic:**  
   `sot search "<feature or utility to implement>"`
2. **Step 2 - Evaluate Trust Verdict:**  
   If `[STRONG]`: Open the reported file:line and reuse the logic. If `[WEAK]`: Skim the file first.
3. **Step 3 - Analyze Blast Radius:**  
   `sot explore "<function_or_class_name>"` to inspect all incoming and outgoing dependencies.
4. **Step 4 - Persist Knowledge Decisions:**  
   After completing complex bug fixes or architectural changes:  
   `sot insert --title "Solution Title" --body "Fix details..." --keywords "tag1,tag2"`

</details>

---

## 📊 4. Graph Analytics & Visualizations

<details>
<summary><h3>Q11: What is a "God Node"? How does the algorithm detect God Nodes and calculate the 2-hop Blast Radius?</h3></summary>

**God Node (Central Hub / High-Degree Symbol):** A class, function, or module possessing an unusually high degree of connectivity, concentrating system-wide dependencies. If a God Node breaks or its API changes, regressions cascade across distant modules.

**Detection Algorithm (`src/sot_graph/analytics/diagnostics.py`):**
1. Computes the global degree mean **μ** and standard deviation **σ**:
   > **Cutoff** = μ + (threshold_sigma × σ)
2. Any node with **Degree ≥ Cutoff** (default `threshold_sigma = 1.5`) is classified as a **God Node**.
3. **2-hop Blast Radius:** A bounded 2-step BFS traversal calculates the count of directly and indirectly impacted entities:
   - **Blast Radius ≥ 25**: `[CRITICAL]` risk.
   - **Blast Radius ≥ 15**: `[HIGH]` risk.
   - **Blast Radius ≥ 8**: `[MEDIUM]` risk.

```bash
# Detect God Nodes and export full architecture report
./bin/sot report --sigma 1.5 --min-size 2 -o ARCHITECTURE_REPORT.md
```

</details>

---

<details>
<summary><h3>Q12: What do Community Detection (Louvain), Modularity (Q), and the Cohesion Score mean?</h3></summary>

The `Label Propagation / Louvain` algorithm in `sot_graph.analytics` groups tightly coupled files and functions into **Functional Communities**:

- **Modularity Score (Q ∈ [-0.5, 1.0]):** Measures the quality of architectural decomposition. **Q > 0.3** indicates strong modular boundaries and clean interfaces.
- **Cohesion Score (C ∈ [0.0, 1.0]):** Ratio of internal cluster connections to total connections:
  > **Cohesion (C)** = `E_internal / (E_internal + E_external)`

  If **C < 0.4**, the cluster is overly dependent on external packages (*Tightly Coupled*) and represents a candidate for refactoring.

```bash
# Inspect detected architectural communities
./bin/sot cluster --min-size 3
```

</details>

---

<details>
<summary><h3>Q13: How do I export the knowledge graph to Interactive HTML D3.js, GraphRAG JSON, Obsidian Vault, and GraphML?</h3></summary>

`sot-graph` includes standalone multi-format exporters in `src/sot_graph/export/`:

```bash
# 1. Interactive D3.js HTML visualization opened directly in browser
./bin/sot viz -o graph.html --open

# 2. Hierarchical dataset export for GraphRAG pipelines
./bin/sot export -f graphrag -o graphrag_dataset.json

# 3. Obsidian Vault export (with bidirectional [[Node]] Wikilinks)
./bin/sot export -f obsidian -o my_obsidian_vault/

# 4. Standard GraphML XML export for Gephi, Cytoscape, NetworkX
./bin/sot export -f graphml -o graph.graphml
```

</details>

---

## ⚙️ 5. Operations, Maintenance & Performance

<details>
<summary><h3>Q14: When should I run sot clean and sot vacuum? What is the difference between --dry-run and live execution?</h3></summary>

Over prolonged active development, the SQLite database may accumulate freelist disk pages or orphaned relationship edges:

- **`sot clean`:** Prunes deleted file records, orphaned edges, and obsolete pending edges.
  - `--dry-run`: Previews the count of removable records in JSON format **without altering the database**.
  - `--all --yes`: Completely wipes all graph nodes and edges to prepare for a clean re-index.
- **`sot vacuum`:** Checkpoints the SQLite WAL (Write-Ahead Log) and runs `VACUUM` to defragment B-Tree pages and reclaim disk space.

```bash
# Preview cleanable stale records
./bin/sot clean --dry-run --json

# Execute safe pruning
./bin/sot clean --json

# Defragment database and reclaim disk space
./bin/sot vacuum --analyze
```

</details>

---

<details>
<summary><h3>Q15: How do I run Drift Verification in CI/CD pipelines without modifying the database or failing builds?</h3></summary>

The `sot verify` command is specifically engineered for CI/CD pipelines and pre-commit checks:

- Operates in **Strictly Read-Only Mode**: Never mutates SQLite files or acquires write locks.
- `sot verify`: Rapidly cross-checks metadata (`size`, `mtime`) between database and filesystem.
- `sot verify --deep`: Re-computes SHA-256 hashes for all physical files to catch hidden code mutations.
- **Exit Code Convention:** Returns `0` if the knowledge graph is fully in sync with disk; returns `1` if drift is detected (with a JSON payload of anomalous paths).

```yaml
# GitHub Actions / CI workflow step
- name: Verify Knowledge Graph Drift
  run: ./bin/sot verify --deep --json
```

</details>

---

<details>
<summary><h3>Q16: What is the real-world performance of sot-graph (reconciliation throughput, FTS5 latency, RAM footprint)?</h3></summary>

Measured performance benchmarks (tested on Apple M1 Max):
- **Reconcile Throughput:** Full AST parsing and ingestion of **100 files in ~24.1ms** (> 4,000 files/second for incremental dirty checks).
- **FTS5 BM25 Query Latency:** **~1.17ms** (P95) across complex lexical queries.
- **Memory Footprint (RAM RSS):** Consistently **< 25MB** under continuous operation.

**Key Architectural Performance Factors:**
1. **Adaptive Worker Threshold:** Small file batches (< 16 files) execute sequentially in the main process to eliminate multiprocessing fork overhead; worker pools activate only for large file volumes.
2. **Zero External Daemon Footprint:** Embedded SQLite configured with `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` maximizes I/O efficiency without memory bloat.

</details>

---

## 🚨 6. Edge Cases & Incident Handling

<details>
<summary><h3>Q17: If two files have the same name (e.g. models/user.py and controllers/user.py) and are moved, how does the system avoid false rehoming?</h3></summary>

This represents a **Basename Collision** during file relocation.

```python
# src/sot_graph/verifier.py:73-78
if basename in files:
    cands.append(os.path.abspath(os.path.join(root, basename)))
    if len(cands) > 1:
        return None  # Collision detected: reject ambiguous guessing
return cands[0] if len(cands) == 1 else None
```

The `find_rehome` routine enforces an **Ambiguity Guard**: If 2 or more files named `user.py` exist across the project tree, the function immediately returns `None`. It **refuses to guess**. The stale path is safely pruned and awaits the next `sot reconcile` cycle for deterministic AST-based re-indexing.

</details>

---

<details>
<summary><h3>Q18: If a source file has a syntax error, will the Reconciler crash?</h3></summary>

**IT WILL NEVER CRASH.**

All parsers in `src/sot_graph/extractor.py` and `_vendor/graphify/extract.py` are wrapped in defensive `try-except` handlers:
- If a Python file contains a `SyntaxError` or a TypeScript file is missing brackets, the parser captures the error in the `error` attribute while **preserving the parent file node**.
- The Reconciler continues processing remaining files uninterrupted and summarizes failed files in `ReconcileSummary.failed`.

</details>

---

<details>
<summary><h3>Q19: How do I store Architecture Decision Records (ADRs) or tricky bug-fixing notes in the knowledge graph?</h3></summary>

Developers or AI Agents can persist Virtual Knowledge Notes using `sot insert`:

```bash
./bin/sot insert \
  --title "Database Transaction Safety Guidelines" \
  --body "All multi-table mutations must be wrapped inside 'with self.conn:' to guarantee ACID compliance and prevent lock leaks." \
  --path "src/sot_graph/db.py" \
  --keywords "sqlite,transaction,acid,concurrency"
```

These records receive the `[NOPATH]` label (or bind to a specific path if `--path` is supplied) and are indexed into FTS5 BM25. When an agent queries *"How do I safely write database transactions?"*, this architectural anchor is returned at the top of the search results.

</details>

---

## 📄 License
MIT License. Copyright (c) 2026 Minh Giap.
