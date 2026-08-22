# 06. Final Deep Reasoning Audit & Architectural Verdict (OMP GPT-5.6-Sol)

> **Auditor**: Lead System Architect & Security Auditor (`gpt-5.6-sol` via OMP CLI)  
> **Evaluation Verdict**: **REJECTED (Pre-Implementation Architectural Gate)**  
> **Status**: Specification patched with 4 mandatory P0 engineering contracts.

---

## 1. Summary of the Final Deep Audit

In the final deep reasoning review round, the High-Tier Systems Architect rigorously stress-tested the proposed v2 specifications against heavy multi-agent concurrency (50+ parallel subagents), memory-constrained VPS environments (4GB RAM), and complex monorepos.

The audit uncovered **4 critical design flaws** that would cause data corruption, process crashes (OOM), or false edge deletions if implemented as initially drafted.

```
┌────────────────────────────────────────────────────────────────────────┐
│               CRITICAL DESIGN DEFECTS UNCOVERED BY AUDIT               │
└────────────────────────────────────────────────────────────────────────┘
  1. STALE PUBLICATION RACE:  POSIX-only flock without generation CAS.
  2. DESTRUCTIVE BUILTIN PRUNING: Deleting calls by string name ('get', 'join').
  3. VPS MEMORY EXHAUSTION:   Unbounded 64MB cache × 50 agents = 3.2GB RAM (OOM).
  4. CONTEXTBUNDLE FIDELITY:  Current graph schema lacks FQN and column spans.
```

---

## 2. Detailed Breakdown of the 4 Blocking Defects & Required Patches

> **Verification Status (2026-08-22, code @ `9572abf`)**: Defect 1 ✅ verified (không có lock/CAS); Defect 2 ✅ verified (`ORDER BY id LIMIT 1` tại `db.py:266`, pending schema không có context); Defect 3 ⚠️ **NOT-APPLICABLE cho code shipped** (không có pragma cache_size 64MB — defect nhắm vào draft proposal; patch giữ làm preventive hardening); Defect 4 ✅ verified (schema chỉ có `line_start`).

### Defect 1: Stale Publication Race & POSIX-only FileLock — ✅ VERIFIED
* **Vulnerability**: 
  - SQLite WAL mode permits only one physical writer at a time, but it does **not prevent logical stale writes**.
  - *Scenario*: Agent A scans file $X$ at $t_1$. Agent B edits $X$ and commits at $t_2$. Agent A finishes parsing its old snapshot at $t_3$ and publishes $t_1$ over $t_2$, silently regressing the knowledge graph.
  - `fcntl.flock` is POSIX-only and fails on Windows. Using `open(path, 'w')` truncates the lock inode before acquisition.
* **Mandatory Architecture Patch (2-Phase Publication with Generation CAS)**:
  1. **Single Stable Lock**: Maintain one project-wide lock file at `.sot/write.lock` (using cross-platform backend: `fcntl` on POSIX, `LockFileEx` / `portalocker` on Windows). Never truncate or unlink the lock file during normal execution.
  2. **Phase A (Unpinned Parse)**: Read source bytes $\rightarrow$ Parse AST $\rightarrow$ Record `parsed_content_sha256`, `expected_path_generation`, and `expected_base_generation`.
  3. **Phase B (Atomic CAS Commit)**:
     - Acquire `.sot/write.lock` with a bounded timeout (return `BUSY` on deadline).
     - `BEGIN IMMEDIATE` transaction.
     - Compare current DB `generation` and file hash against expected values.
     - On mismatch: `ROLLBACK` immediately and return `CONFLICT`. **Never use Last-Writer-Wins.**

---

### Defect 2: Destructive Builtin Pruning (`get`, `execute`, `join`) — ✅ VERIFIED (resolve hiện tại dùng `ORDER BY id LIMIT 1` tại `db.py:266`)
* **Vulnerability**:
  - The initial proposal filtered functions named `get`, `execute`, `join` by simple name matching.
  - In real-world codebases, this deletes valid project calls like `requests.get()`, `db.execute()`, `custom_store.get()`, or `workflow.join()`.
  - Furthermore, resolving ambiguous calls via `ORDER BY id LIMIT 1` arbitrarily attaches calls to random same-named functions in other files.
* **Mandatory Architecture Patch (Binding-Aware Resolver)**:
  1. **Never filter by bare string name alone**: The AST parser must record:
     - Caller FQN
     - Call kind: `BARE`, `ATTRIBUTE`, `QUALIFIED`, or `DYNAMIC`
     - Receiver / Qualifier expression (e.g. `requests` in `requests.get`)
     - Import source module
  2. **Resolution Precedence**:
     $$\text{Lexical Binding} \rightarrow \text{Explicit Import} \rightarrow \text{Module FQN} \rightarrow \text{Statically Known Receiver} \rightarrow \text{Candidate Set} \rightarrow \text{Unresolved}$$
  3. **Strict Builtin Rule**: Only **unshadowed Bare Calls** (e.g. `len(x)` where `len` is not assigned locally or imported) may be classified as `BUILTIN` and pruned from `pending_edges`.

---

### Defect 3: VPS Memory Exhaustion under Multi-Agent Concurrency — ⚠️ NOT-APPLICABLE cho code shipped (patch giữ làm preventive)
* **Vulnerability**:
  - Setting `PRAGMA cache_size = -64000` (64 MiB) and `PRAGMA temp_store = MEMORY` on all database connections allocates:
    $$\text{50 concurrent agents} \times 64\text{ MiB page cache} = 3.2\text{ GiB RAM}$$
  - On a 4GB RAM VPS (like Hetzner CX23), this causes the Linux **OOM Killer** to terminate agent processes and corrupt in-flight state.
* **Mandatory Architecture Patch (Connection Profiles)**:
  - **Writer Profile (Single Writer)**:
    - `PRAGMA journal_mode = WAL;`
    - `PRAGMA synchronous = NORMAL;`
    - `PRAGMA busy_timeout = 5000;`
    - Small bounded cache: `cache_size = -8000` (8 MiB).
  - **Reader Profile (Concurrent Agents / MCP)**:
    - `PRAGMA query_only = ON;`
    - `PRAGMA cache_size = -4000` (4 MiB per reader).
    - `PRAGMA temp_store = FILE` (or capped memory).

---

### Defect 4: ContextBundle Schema & Fidelity Deficits — ✅ VERIFIED
* **Vulnerability**:
  - Current `graph_nodes` schema only tracks `symbol`, `label`, `body`, and `line_start`.
  - It cannot truthfully provide full AST spans (`start_col`, `end_col`, `end_line`), type contracts, parameter types, or exception contracts.
* **Mandatory Architecture Patch (Schema & Security Protocol)**:
  1. **Schema Extension**: Bổ sung các cột `fully_qualified_name`, `end_line`, `start_col`, `end_col`, `signature_contract` vào `graph_nodes`.
  2. **Untrusted Data Enforcement**: Toàn bộ mã nguồn và docstring trong `ContextBundle.yaml` phải được gắn cờ `content_is_untrusted: true`. Cấm chèn mã nguồn thô vào system instruction của LLM để ngăn chặn tấn công Prompt Injection qua mã nguồn.

---

## 3. Mandatory 18-Scenario Acceptance Test Suite

Before any code is considered production-ready for v2, it must pass all 18 acceptance scenarios:

| # | Acceptance Scenario | Expected Strict Outcome |
| :-: | :--- | :--- |
| **1** | 50 processes reconcile the same unchanged file | Exactly 1 idempotent publication; 0 DB corruption; bounded completion time. |
| **2** | 50 processes publish different versions of 1 file | Only generation-valid publication succeeds; stale publishers return `CONFLICT`. |
| **3** | Process A scans deletion while Process B recreates file | Process A cannot delete Process B's newly published path. |
| **4** | Two disjoint overlays promote concurrently | Both succeed or one retries safely; zero lost rows. |
| **5** | Two overlays modify the exact same path | One succeeds; the second receives deterministic `CONFLICT`. |
| **6** | Process receives `SIGKILL` mid-transaction | SQLite rolls back cleanly; lock is re-acquirable; zero partial state. |
| **7** | Crash after base commit but before overlay cleanup | Retry recognizes `applied_overlays`; zero duplicate merge. |
| **8** | Lock holder exceeds timeout threshold | Waiting processes return explicit `BUSY`; zero infinite hangs. |
| **9** | Database VACUUM / Migration races Reconcile | Fixed lock order enforced; zero deadlock. |
| **10** | Custom user methods named `get`, `execute`, `join` | Preserved with exact custom destinations; never pruned. |
| **11** | True unshadowed `len()` or language built-in | Classified as `BUILTIN`; zero pending project edges created. |
| **12** | Shadowed built-in (e.g. `len = custom_len`) | Correctly resolves to shadowing project / local binding. |
| **13** | Duplicate project symbol names across files | Import-qualified calls resolve exactly; unqualified ambiguity marked `AMBIGUOUS`. |
| **14** | ContextBundle target modified during packaging | Packaging detects generation drift and returns `STALE_SNAPSHOT`. |
| **15** | Target symbol body exceeds hard byte cap | Fails closed with `TARGET_TOO_LARGE` or explicit partial with `complete: false`. |
| **16** | Bundle traversal encounters path outside project root | Path excluded immediately; security warning emitted. |
| **17** | Source comments contain prompt injection payload | Treated strictly as untrusted data fields; never interpreted as instructions. |
| **18** | Full 50-process concurrent stress test | `PRAGMA quick_check` = `ok`; RSS stays $\le 256\text{MB}$; WAL $\le 16\text{MB}$. |
