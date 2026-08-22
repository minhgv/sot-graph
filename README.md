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

# 7. Generate architectural markdown report (God nodes, surprising connections, communities)
./bin/sot report -o GRAPH_REPORT.md

# 8. Inspect detected modular communities and cohesion scores
./bin/sot cluster

# 9. Launch standalone interactive HTML graph visualizer
./bin/sot viz -o graph.html --open

# 10. Export graph to GraphRAG JSON, Obsidian Vault, or GraphML
./bin/sot export --format graphrag -o graphrag.json
./bin/sot export --format obsidian -o obsidian_vault/
./bin/sot export --format graphml -o graph.graphml
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

### 4. Model Context Protocol (MCP) Stdio Server
`sot-graph` exposes 5 read-only tools and resources over stdio for Claude Desktop, Cursor, and IDEs:
- `sot_search`: Trust-verified search with disk validation.
- `sot_explore`: Bounded AST exploration and cross-file relations.
- `sot_verify_drift`: Read-only drift audit between graph and disk.
- `sot_architecture_report`: Complete architectural analysis with God Node detection.
- `sot_communities`: Cluster detection with modularity and cohesion metrics.

```bash
./bin/sot mcp
```

### Maintenance and parallel reconciliation

Reconciliation uses deterministic, bounded worker windows and one SQLite writer. Tune
throughput explicitly when needed; `--workers 1` is the sequential baseline:

```bash
./bin/sot reconcile --workers 4 --batch-size 64
./bin/sot reconcile --workers 1
```

`clean` is conservative by default: it removes missing tracked paths and orphaned
edges/pending references while preserving live graph rows and notes. Inspect before
writing, or reset generated rows with explicit confirmation:

```bash
./bin/sot clean --dry-run --json
./bin/sot clean --all --yes --json
./bin/sot clean --all --include-notes --yes --json
```

`vacuum` reports database/WAL sizes, pages, free-list space, checkpoint status, and
elapsed time. `--dry-run` only reports metrics; the mutating operation checkpoints
the WAL and runs SQLite `VACUUM` without deleting `-wal` or `-shm` files. Keep
adequate free disk space and avoid running it while another writer holds the DB:

```bash
./bin/sot vacuum --dry-run --json
./bin/sot vacuum --optimize --json
```

### MCP stdio server

Install the optional SDK; the base CLI does not import MCP dependencies:

```bash
python3 -m pip install '.[mcp]'
./bin/sot --root /path/to/repo --db /path/to/repo/.sot/sot.db mcp
```

The server is read-only, does not create a missing database, and exposes the
bounded `sot_search`, `sot_explore`, and `sot_verify_drift` tools plus
`sot://stats` and `sot://node/{node_id}` resources. It uses stdio: stdout is
reserved for JSON-RPC protocol traffic and diagnostics go to stderr. Configure
`--request-timeout` with a positive finite number and use `--log-level` for
diagnostics.

### Benchmarks

Benchmark fixtures are deterministic across Python, TypeScript, Go, Rust, and
Markdown. Each run performs a warmup, reports `perf_counter_ns` median/p95/min
samples, records an environment fingerprint, and gates correctness against the
single-worker result. Performance numbers are machine-dependent; correctness is
the portable acceptance criterion:

```bash
python3 -m benchmarks.bench_reconcile \
  --files 5000 --workers 1,2,4,8 --repeat 5 --json results.json
python3 -m benchmarks.bench_query --files 5000 --repeat 5 --json query-results.json
```


---

## ⚖️ So Sánh Kiến Trúc: `sot-graph` vs `graphify` vs `gitnexus` (Architectural Comparison)

| Tiêu chí / Capability | `sot-graph` (Dự án này) | `graphify` | `gitnexus` |
| :--- | :--- | :--- | :--- |
| **Mục tiêu cốt lõi (Core Purpose)** | Lớp tri thức **Single Source of Truth** tự chữa lành cho AI Coding Agents trong vòng lặp lập trình thực tế (*Active filesystem loop*). | Xây dựng đồ thị tri thức đa phương tiện sâu (Code, Docs, Papers) kèm báo cáo kiến trúc và phân tích suy luận ngữ nghĩa qua LLM. | Công cụ Code Intelligence & MCP client-side chạy trong trình duyệt / zero-server, lập bản đồ AST & Git repository. |
| **Nguồn Chân Lý (Source of Truth)** | **Filesystem là chân lý tuyệt đối**. Mọi hint chỉ là gợi ý, dữ liệu luôn được xác minh đối chiếu trực tiếp từ đĩa trước khi trả về. | **Tệp đầu vào + Suy luận LLM**. Lấy snapshot cây thư mục tại thời điểm quét và lưu đồ thị JSON tĩnh. | **Git Repository + Tree-sitter AST**. Lập chỉ mục cây Git và các quan hệ cuộc gọi (*call graph*) trong bộ nhớ. |
| **Cơ chế Chống Ảo Giác (Anti-Hallucination)** | **Trust Verdict Engine** (`[STRONG]`, `[WEAK]`, `[REBUILT]`, `[REMOVED]`): Kiểm tra vật lý file tồn tại và độ phủ token trên đĩa trước khi trả kết quả. | Phân loại liên kết minh bạch (`EXTRACTED` vs `INFERRED` vs `AMBIGUOUS`) kèm audit trail và cảnh báo token cost. | Dựa vào phân tích cú pháp tĩnh Tree-sitter; không có cơ chế đối soát độ phủ token hay kiểm tra thay đổi vật lý runtime. |
| **Cơ chế Tự Chữa Lành (Self-Healing)** | **Tự động & Tức thì**: Tự nhận diện file bị di chuyển/đổi tên (`[REBUILT]`), tự động xóa các đường dẫn chết (`[REMOVED]`) và dọn dẹp quan hệ mồ côi. | **Không tự động**: Cần chạy lại `/graphify --update` hoặc tái tạo toàn bộ đồ thị tri thức khi codebase thay đổi. | **Theo phiên / Manual**: Đòi hỏi re-indexing lại kho mã nguồn khi có commit hoặc nhánh mới. |
| **Engine Lưu trữ & Truy vấn (Storage & State)** | **SQLite WAL + FTS5 (BM25)**: Hỗ trợ giao dịch ACID, dirty tracking theo SHA-256 generation, độ trễ truy vấn sub-millisecond ($< 1.5\text{ms}$). | **JSON (`graph.json`) + Markdown Reports**: Không dùng DB quan hệ nhúng; lưu đồ thị dưới dạng tệp phẳng. | **In-memory / IndexedDB / WASM Browser Cache**: Dữ liệu lưu trong RAM trình duyệt hoặc tiến trình Node.js tạm thời. |
| **Hiệu năng & Tài nguyên (Footprint)** | Cực kỳ nhẹ ($< 25\text{MB}$ RAM), **Zero external dependencies**, xử lý song song đa tiến trình (~$20\text{ms}$ / 100 files). | Tốn token LLM khi chạy chế độ `--mode deep`; thích hợp chạy định kỳ / tài liệu hóa thay vì chạy theo từng lệnh code. | Phụ thuộc runtime trình duyệt/Node.js và bộ nhớ RAM khi xử lý các kho mã nguồn lớn (*monorepo*). |
| **Phân tích Cụm & God Nodes** | Tích hợp sẵn thuật toán **Louvain / Modularity ($Q$)**, Cohesion score, và **God Node Detection (2-hop blast radius)** không cần daemon ngoài. | Tích hợp thuật toán **Leiden / Louvain community detection**, chấm điểm Cohesion, và phát hiện các kết nối bất thường (*Surprising connections*). | Tập trung vào biểu diễn quan hệ kế thừa, import và call-chain trực quan; không tập trung vào phân tích cụm kiến trúc. |
| **Trực quan hóa (Visualization)** | Trực quan hóa tương tác Standalone HTML D3.js v7 (*force-directed graph*) kèm bộ lọc cộng đồng và chi tiết nút/cạnh. | Trực quan hóa tương tác HTML D3.js + Hỗ trợ xuất Obsidian Canvas / Vault và GraphML. | Giao diện đồ họa Web UI hiện đại chạy trực tiếp trên trình duyệt (*client-side interactive map*). |
| **Định dạng Xuất (Exports)** | **GraphRAG JSON**, **Obsidian Markdown Vault**, **GraphML XML**, và **Markdown Report**. | **GraphRAG JSON**, **Obsidian Markdown Vault**, **GRAPH_REPORT.md**. | Chủ yếu phục vụ MCP server và Web UI nội bộ. |
| **Giao thức MCP (Model Context Protocol)** | **5 MCP Tools stdio** (`sot_search`, `sot_explore`, `sot_verify_drift`, `sot_architecture_report`, `sot_communities`). | Tích hợp qua cấu hình CLAUDE.md hoặc MCP server mở rộng. | **MCP-Native stdio/SSE server** với các công cụ tra cứu cấu trúc mã nguồn. |

---

### 📌 Khi Nào Nên Sử Dụng Công Cụ Nào? (Selection Guide)

1. **Chọn `sot-graph` khi:**
   - Bạn đang xây dựng hoặc sử dụng **AI Coding Agents (OMP, Claude Code, Cursor, Agy)** cần một lớp tri thức **cực nhanh, tự chữa lành, và không bao giờ bị lỗi đường dẫn chết (dead paths / phantom anchors)**.
   - Cần một công cụ **Zero-Daemon, Zero-External-Dependencies** chạy bằng Python tiêu chuẩn + SQLite với độ trễ truy vấn sub-millisecond ($< 1.5\text{ms}$).
   - Bạn muốn có đầy đủ từ tìm kiếm trust-verified, phân tích kiến trúc (God Nodes, Communities), đến xuất GraphRAG / Obsidian / HTML visualizer trong cùng một CLI duy nhất.

2. **Chọn `graphify` khi:**
   - Bạn cần phân tích **toàn diện một kho tài liệu hỗn hợp** (bao gồm cả mã nguồn, tài liệu Markdown/PDF, bài báo nghiên cứu, hình ảnh/video).
   - Bạn muốn tận dụng **sức mạnh suy luận ngữ nghĩa của LLM** để trích xuất các liên kết tiềm ẩn (`INFERRED` edges) và tạo báo cáo kiểm toán chi phí token chi tiết.
   - Bạn muốn tạo Obsidian Vault tri thức sâu để con người đọc và nghiên cứu tài liệu hệ thống.

3. **Chọn `gitnexus` khi:**
   - Bạn muốn **khảo sát nhanh kiến trúc mã nguồn ngay trên trình duyệt web** (Zero-Server Web App) chỉ bằng cách kéo thả file ZIP hoặc paste URL GitHub.
   - Bạn cần một giao diện đồ họa web client-side trực quan để lập trình viên tự duyệt call-chains và cây quan hệ Git mà không cần cài đặt môi trường backend.

---

## 🧪 Testing

The test suite exercises idempotency, content coverage scoring, auto-purging of dead paths, two-way edge resolution, and multi-language parsers:

```bash
python3 -m unittest discover -s tests
```

---

## 📄 License

MIT License. Copyright (c) 2026 Minh Giap.
