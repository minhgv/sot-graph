# 02. Core Database & Concurrency Optimization

> **Document Status**: Harmonized & Authoritative (Aligned with Final Audit P0 Contracts)  
> **Topic**: SQLite Storage Architecture, Binding-Aware Builtin Pruning & Cross-Platform Concurrency  
> **Audited By**: OMP Systems Architect (`gpt-5.6-sol`)

---

## 1. The Pending Edges Bloat & Binding-Aware Resolution

### Empirical Discovery (verified 2026-08-22)
Profiling `sot-graph/.sot/sot.db` revealed that the `pending_edges` table held **2,206 records across 39 distinct paths** (66 rows in `file_journal`). Cùng phân bố quan sát trên `relation`: ngoài `calls`, các edge `imports` của module ngoài (`os`, `ast`, `sqlite3`...) cũng nằm mãi trong pending.

```sql
SELECT dst_symbol, COUNT(*) as c 
FROM pending_edges 
GROUP BY dst_symbol 
ORDER BY c DESC 
LIMIT 10;
```

**Top Offending Symbols:**
1. `len`: 92 references
2. `Path`: 79 references
3. `append`: 74 references
4. `str`: 64 references
5. `join`: 51 references
6. `get`: 46 references
7. `execute`: 43 references
8. `write_text`: 41 references

### The Critical Flaw of String-Based Filtering
A naive blacklist that filters out `get`, `execute`, or `join` by simple name matching creates severe **False Negatives**:
- Project calls like `requests.get()`, `custom_store.get()`, `db.execute()`, or `pipeline.join()` would be silently dropped.
- Resolving bare string names via `ORDER BY id LIMIT 1` creates **False Positives** by arbitrarily attaching calls to unrelated functions in other files.

### Hardened Architecture: Binding-Aware AST Resolver

> ⚠️ **Nhất thể hóa (theo File 06 - Final Deep Audit)**: Không bao giờ phân loại Built-in chỉ dựa trên tên chuỗi trần. Parser bắt buộc phải lưu ngữ cảnh cú pháp đầy đủ.

```text
pending_edges Schema (Hardened v2):
  callsite_id      TEXT PRIMARY KEY       -- Stable SHA256 of (path, caller_node_id, line, col)
  path             TEXT NOT NULL          -- Source file path owning the call
  src_node_id      TEXT NOT NULL          -- Caller node ID
  language         TEXT NOT NULL          -- Source language ('python', 'typescript', etc.)
  callee_name      TEXT NOT NULL          -- Literal callee name ('get', 'execute')
  call_kind        TEXT NOT NULL          -- 'BARE' | 'ATTRIBUTE' | 'QUALIFIED' | 'DYNAMIC'
  receiver         TEXT                   -- Object / module receiver (e.g. 'requests' or 'self.db')
  import_source    TEXT                   -- Statically known import module
  relation         TEXT NOT NULL          -- 'calls' | 'uses' | 'imports'
  line             INTEGER NOT NULL
  column           INTEGER NOT NULL
  resolution_state TEXT NOT NULL          -- 'EXACT' | 'AMBIGUOUS' | 'UNRESOLVED' | 'BUILTIN'
```

#### Strict Resolution Precedence:
$$\text{Lexical Scope Binding} \longrightarrow \text{Explicit Import Module} \longrightarrow \text{Module FQN Match} \longrightarrow \text{Statically Known Receiver} \longrightarrow \text{Ambiguous Candidate Set} \longrightarrow \text{Unresolved}$$

1. **Bare Call Rule**: Only calls of kind `BARE` (e.g. `len(items)`) that are **unshadowed** by local variables, parameters, or imports are marked as `BUILTIN` and pruned from `pending_edges`.
2. **Attribute Call Rule**: Method calls of kind `ATTRIBUTE` (e.g. `obj.get()`) are retained as project dependencies and resolved against known receiver types or marked `AMBIGUOUS`.

---

## 2. Cross-Platform Concurrency & Stale Publication Prevention

### The Problem of Stale Writers
SQLite WAL mode serializes physical disk writes, but it **cannot prevent logical stale writes** when multiple agents run in parallel:

```text
Time t1: Agent A scans file X (at SHA1).
Time t2: Agent B edits file X (to SHA2). Agent B parses and commits to DB.
Time t3: Agent A finishes its long parsing pass on SHA1 and commits.
Result : Stale data from SHA1 overwrites Agent B's newer SHA2 without triggering an SQLite error!
```

### Hardened 2-Phase Publication Protocol with Generation CAS

> ⚠️ **Nhất thể hóa (theo File 06 - Final Deep Audit)**: Triển khai stable project lock `.sot/write.lock` kết hợp Compare-And-Swap (CAS) generation check.
>
> **Ghi chú hiện trạng (verified)**: (1) Cột `generation` đã TỒN TẠI trong `file_journal` (`db.py:21`) và tự tăng khi upsert (`db.py:244`) — CAS chỉ cần so sánh expected-vs-current per-path, **không cần global counter** (tránh thêm write contention). (2) Reconciler đã tách sẵn Phase A (parse ngoài lock, ProcessPoolExecutor) / Phase B (commit) — chỉ cần bọc Phase B trong lock + CAS check. (3) Lock cross-platform implement bằng stdlib (`fcntl` POSIX / `msvcrt` Windows), mở với `O_CREAT|O_RDWR` **không bao giờ truncate/unlink** — không cần thêm dependency `portalocker`.

```
┌────────────────────────────────────────────────────────────────────────┐
│                   2-PHASE PUBLICATION PROTOCOL (CAS)                   │
└────────────────────────────────────────────────────────────────────────┘

  [ PHASE A: Outside Lock (CPU Parallel Extraction) ]
  1. Scan and read immutable source file bytes.
  2. Parse AST nodes, edges, and callsite identifiers.
  3. Produce an immutable `ParseSnapshot`:
     • path, parsed_content_sha256
     • expected_path_generation
     • expected_global_graph_generation
     • extracted_nodes, extracted_edges, pending_calls

  [ PHASE B: Publication Gate (Single-Writer SQLite Commit) ]
  4. Acquire stable `.sot/write.lock` with bounded timeout (e.g. 5,000ms).
     (Return explicit `BUSY` on timeout; never wait indefinitely).
  5. Re-check file existence and physical hash on disk.
  6. Execute `BEGIN IMMEDIATE` transaction.
  7. CAS Validation: Compare DB `generation` against `expected_path_generation`.
     • Mismatch ➔ `ROLLBACK` immediately, emit `CONFLICT`, re-queue for retry.
  8. Atomic Replacement: Delete old path records, insert new nodes/edges.
  9. Increment global `graph_generation` and commit.
  10. Release `.sot/write.lock` in a `finally` block.
```

---

## 3. VPS Memory Safety & Connection Profiles

> ⚠️ **Nhất thể hóa (theo File 06 - Final Deep Audit)**: Không bật `cache_size` lớn toàn cục. Sử dụng Bounded Connection Profiles.
>
> **Ghi chú hiện trạng (verified)**: code shipped KHÔNG hề set `cache_size = -64000` — defect 3.2GB chỉ áp dụng cho bản draft proposal. Profiles dưới đây là **preventive hardening** (đặt giới hạn tường minh thay vì dựa vào SQLite default ~2MB), không phải hotfix.

```python
# Writer Connection Profile (Single Writer Process)
def configure_writer(conn: sqlite3.Connection):
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA mmap_size = 67108864;")       # 64MB mmap for writer
    conn.execute("PRAGMA cache_size = -8000;")         # 8MB page cache
    conn.execute("PRAGMA foreign_keys = ON;")

# Reader Connection Profile (Concurrent Agent Queries / MCP)
def configure_reader(conn: sqlite3.Connection):
    conn.execute("PRAGMA query_only = ON;")
    conn.execute("PRAGMA cache_size = -4000;")         # 4MB page cache per reader
    conn.execute("PRAGMA mmap_size = 33554432;")       # 32MB mmap for reader
    conn.execute("PRAGMA temp_store = FILE;")          # Guard VPS RAM against CTE blowouts
```

### Covered Indexes for Zero-Heap Traversals:
```sql
CREATE INDEX IF NOT EXISTS idx_edges_forward_covered 
ON graph_edges (src, relation, dst, line);

CREATE INDEX IF NOT EXISTS idx_edges_reverse_covered 
ON graph_edges (dst, relation, src, line);
```
