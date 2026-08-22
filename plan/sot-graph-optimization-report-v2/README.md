# SOT-Graph Optimization & Architectural Evolution — Research Report Suite

> **Research Protocol**: Deli Deep Multi-Iteration Autonomous Research Protocol  
> **Target Repository**: `https://github.com/minhgv/sot-graph`  
> **Advisory Consultation**: OMP Planner / Advisor (`gpt-5.6-sol` / `gemini-3.7-flash`)  
> **Final Audit Verdict**: **REJECTED (Pre-Implementation Gate — Patched with 4 P0 Contracts)**  
> **Report Storage**: `~/mData/hermes_vps/sot-graph-optimization-report/`  
> **Date**: August 22, 2026  
> **Edition**: v2.1 — Verified & Corrected (every claim cross-checked against code @ commit `9572abf`; see Verification Addendum below)

---

## 🏛️ Report Suite Index

| # | Topic / Specialized Module | File Path | Focus & Core Contributions |
| :-: | :--- | :--- | :--- |
| **01** | **Executive Summary & Roadmap** | [`01-executive-summary.md`](01-executive-summary.md) | High-level synthesis, key architectural gaps, and 4-phase strategic evolution roadmap. |
| **02** | **Core Database & Concurrency** | [`02-database-and-concurrency.md`](02-database-and-concurrency.md) | Pending edges bloat analysis (34:1 ratio), SQLite Pragmas, and OS-level FileLock mechanics. |
| **03** | **AST Extraction & Graph Algorithms** | [`03-ast-and-graph-algorithms.md`](03-ast-and-graph-algorithms.md) | Language parser fidelity, LRU AST caching, and deterministic Label Propagation clustering. |
| **04** | **Agent Subgraph Packaging** | [`04-subgraph-packaging-and-tokens.md`](04-subgraph-packaging-and-tokens.md) | $k$-hop Ego-graph slicing, Folded Signature Stubs, and quantified Token Economy (73.4% reduction). |
| **05** | **Agent Ergonomics & Real-Time Sync** | [`05-agent-ergonomics-and-sync.md`](05-agent-ergonomics-and-sync.md) | Multi-harness setup review, inotify real-time watchdog daemon, and Read-Only MCP protocol. |
| **06** | **Final Deep Audit & Verdict (OMP Sol)** | [`06-final-deep-audit-and-verdict.md`](06-final-deep-audit-and-verdict.md) | Phán quyết kiến trúc cuối cùng từ OMP GPT-5.6-Sol: Bóc tách 4 lỗ hổng chí mạng (Stale Publication, False Builtin Pruning, VPS OOM, ContextBundle Schema) và 18 kịch bản kiểm thử nghiệm thu. |

---

## 📊 Summary of Research Findings (10 Verified Insights + Final Verdict)

1. **Pending Edges Bloat**: Language built-ins polluting pending edges (2,206 records for 64 files).
2. **Missing OS FileLock & CAS**: Phải dùng 2-Phase Publication với Generation Check để chống Stale Writer Race.
3. **FTS5 Unicode Normalization**: Cấu hình Unicode61 tokenizer để nhận diện ký tự tiếng Việt và code namespace.
4. **Two-Tier Overlay Graph**: Tách Base Graph (committed) + Overlay Scratchpad (uncommitted rev_id).
5. **Memory Sizing for VPS 4GB**: Giới hạn cache Reader (4MB) và Writer (8MB) để chống OOM khi chạy 50 agents.
6. **Binding-Aware Builtin Resolver**: Không bao giờ lọc built-in theo tên chuỗi trần (`get`, `join`); phải xét phạm vi biến và FQN.
7. **ContextBundle Packaging**: 1-hop full AST + 2-hop folded signature stubs kèm đánh dấu `content_is_untrusted`.
8. **Deterministic Community Detection**: Cố định seed và sort keys cho thuật toán Label Propagation.
9. **AST Extraction LRU Cache**: Tiết kiệm CPU cho các file tĩnh trong phiên tương tác dài. *(Đã điều chỉnh: reconciler vốn đã skip unchanged files qua SHA-256 journal — xem Addendum, mục I.4.)*
10. **Real-time File Watcher Daemon**: Bổ sung `sot watch` (watchfiles nếu có, polling fallback) cho trải nghiệm tức thì.

---

## 🔬 Verification Addendum (2026-08-22, code @ `9572abf`)

Toàn bộ claims đã được đối chiếu trực tiếp với source code và database thật (`.sot/sot.db`). Kết quả:

### Xác nhận chính xác
| Claim | Bằng chứng |
| :--- | :--- |
| Pending edges bloat 2,206 records | Query trực tiếp `.sot/sot.db`: đúng **2,206** rows, top offenders khớp từng số (`len`:92, `Path`:79, `append`:74, `str`:64, `join`:51, `get`:46, `execute`:43, `write_text`:41) |
| Pending edges thiếu ngữ cảnh cú pháp | `src/sot_graph/db.py:36-41` — schema chỉ có `(path, src, dst_symbol, relation, line)` |
| Resolve tùy ý bằng `ORDER BY id LIMIT 1` | `src/sot_graph/db.py:266` — đúng nguyên văn, gán edge vào node cùng tên đầu tiên (False Positive) |
| `graph_nodes` thiếu FQN/spans/signature | `src/sot_graph/db.py:23-27` — chỉ có `line_start` |
| Không có file lock / CAS khi commit | `reconciler.py` parse ở process pool rồi commit tại `reconciler.py:338` mà không re-verify hash trên đĩa trong transaction |
| FTS5 dùng default tokenizer | `db.py:42-44` — không unicode61, không tokenchars, không index FQN |
| MCP read-only + cap 256KB + timeout 2000ms | `mcp_service.py:43,56` — đã có sẵn, mô tả trong doc 05 chính xác |
| Chưa có `sot watch` / `sot pack` | Không tồn tại trong `cli.py` |

### Không khớp thực tế — đã đính chính
1. **Deterministic Community Detection (doc 03 §1): ĐÃ CÀI ĐẶT SẴN**. `analytics/graph.py:300-338` đã có `seed=42`, `random.Random(seed)`, `rng.shuffle`, tie-breaking `sorted(best_labels)[0]`; Louvain cũng `seed=42` (line 291). Item này thu hẹp còn **regression test lock**.
2. **Defect 3 — VPS OOM 3.2GB (doc 06): KHÔNG ÁP DỤNG cho code shipped**. Code hiện tại không set `cache_size=-64000` (mặc định SQLite ~2MB/connection). Defect này nhắm vào bản draft proposal v1. Connection Profiles giữ lại như **hardening/ preventive**, không phải critical fix.
3. **Số liệu "64 files"**: thực tế 2,206 records trên **39 distinct paths** (file_journal có 66 rows).
4. **AST LRU Cache (doc 03 §3): giá trị thấp hơn claim**. Reconciler đã skip unchanged files bằng SHA-256 journal (`reconciler.py:272-281`) trước khi parse. LRU chỉ lợi cho parse lặp trong cùng process (session MCP dài).
5. **Token ROI bảng trong doc 04**: chưa có methodology — hạ cấp thành **hypothesis**, cần benchmark riêng qua `benchmarks/`.
6. **Binding-Aware Resolver chỉ full-fidelity cho Python**. Vendor extractor: Python full AST; JS/Go/Rust/Java... đều regex (`_vendor/graphify/extract.py:148,202-308`). Tiered fidelity bắt buộc: Python exact binding analysis; ngôn ngữ khác heuristic保守 (không prune).

### Roadmap hiệu chỉnh
- **Phase 1** giữ nguyên (Resolver + write.lock/CAS + Profiles) — ưu tiên cao nhất.
- **Phase 2 thu hẹp**: bỏ mục determinism (đã xong), **thăng hạng schema v2 (FQN/spans/signature) + FTS5 unicode61 lên P0** vì là điều kiện tiên quyết của `sot pack` (Phase 3).
- **Phase 3** giữ nguyên thiết kế ContextBundle.
- **Phase 4**: `watchfiles` là **optional dependency group `[watch]`** (giữ tinh thần zero-dependency), kèm stdlib polling fallback.
