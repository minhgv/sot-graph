# SOT-Graph — Audit Bugs & Kế hoạch Đánh giá Tự động theo Module

> Ngày: 2026-09-03 · Commit base: `7dd9e54` · Baseline: **932/932 test pass** (101s) — mọi finding dưới đây đều là defect mà bộ test hiện tại *chưa phát hiện*, được xác minh trực tiếp trên code.

## 1. Tổng quan

Repo ~30k dòng Python (68 file nguồn, 98 file test) được chia thành **6 scope chức năng**:

| Scope | Module chính | Vai trò |
|---|---|---|
| `core-storage` | db, locking, snapshot, evidence, envelope, config, proc, vector | Lưu trữ SQLite, khóa ghi, snapshot niêm phong |
| `extraction` | extractor, ts_extract, ignore, providers/, importer/scip | Tree-sitter trích xuất đa ngôn ngữ, SCIP import |
| `sync-healing` | reconciler, verifier, watcher | Đồng bộ FS↔DB, self-healing, watch daemon |
| `query-analytics` | pack, repo_map, trace, diff_impact, solution, analytics/ | Truy vấn, impact analysis, báo cáo kiến trúc |
| `surfaces` | cli, mcp_server, mcp_service, adapters/, export/ | CLI, MCP server, adapter ZCode/Opencode, export |
| `assurance` | assurance/ (receipts, ledger, coverage, orchestrator) | Trust chain, receipt, evidence ledger |

Kết quả audit: **~20 P1** (hành vi sai) và **~45 P2** (perf/robustness). Phần 2 liệt kê các P1 nổi bật nhất theo scope; P2 được tóm lược. Mọi finding có dạng `file:line` để đối chiếu.

## 2. Bugs P1 theo scope

### 2.1 core-storage

1. **`db.py:676-689` — LIKE fallback không escape wildcard trong `get_file_journal`.** Query path chứa `_`/`%` (VD `util_.py`) khớp journal row của file *khác* (`utils.py`) qua `LIKE '%/src/pkg/util_.py'`; `LIMIT 1` không có `ORDER BY` khiến row sai thắng cả khi row đúng tồn tại. Hệ quả: file mới kế thừa sha256 của file khác → `reconcile` trả "unchanged", không index (`reconciler.py:521`); verifier so hash với row sai → STALE giả vĩnh viễn (`verifier.py:375`). Đây là bug 3 audit độc lập đều bắt được. Cách sửa: escape `%`/`_` với `ESCAPE '\'` như `search_fts` đã làm (`db.py:1988`).
2. **`snapshot.py:313` — bind_snapshot fail-open khi git hỏng.** `is_dirty()` trả `False` khi `git status` crash/timeout → lưu `dirty=0` cho worktree *không thể kiểm chứng*, mâu thuẫn contract tri-state `dirty_state()` ("None phải coi là NOT clean").
3. **`envelope.py:29-32` — digest manifest fail-open.** `except Exception: return "sha256:unknown"` khiến mọi trạng thái lỗi (DB đóng, schema thiếu, lỗi tạm thời) cùng một digest — snapshot comparison không còn phân biệt được "không tính được" với digest thật.

### 2.2 extraction

4. **`importer/scip.py:206-213` — parse nhầm protobuf Relationships thành documentation.** Field 3 của `SymbolInformation` luôn là `repeated Relationship`, nhưng code "sniff" UTF-8 rồi nhét vào `documentation` → mọi import SCIP binary **mất toàn bộ cạnh implements/is_definition**, trust verdicts mất bằng chứng relationship.
5. **`ts_extract.py:60,862-875` — Go import dạng block bị bỏ qua hoàn toàn.** Regex chỉ bắt `import "x"` một dòng; `import (\n "fmt"\n ...)` (dạng gofmt chuẩn) và blank import `_ "x"` không cho cạnh imports nào → không disambiguate được symbol trùng tên cross-file.
6. **`extractor.py:347-374` — `this.helper()` khớp hàm module-level trùng tên trước khi thử `<Class>.helper`.** Comment `:330-336` tuyên bố guarantee này nhưng chỉ cài cho `receiver_type` có type; khi không suy luận được kiểu, cạnh gọi sai đối tượng.

### 2.3 sync-healing

7. **`watcher.py:76-84` — LockBusy làm MẤT vĩnh viễn event đổi file.** Sleep 0.2s rồi `continue` sang path khác, không re-enqueue — mọi event trong lúc CLI migration giữ write lock đều rơi, DB stale cho tới lần sửa tiếp theo.
8. **`watcher.py:101-104` + `reconciler.py:483-537` — churn index file binary/unsupported.** Watcher chỉ check `is_ignored`, không check `_supported()` → `logo.png` được index vào FTS (preview mojibake), rồi lần reconcile full sau đó sweep xóa, rồi index lại khi file chạm lần nữa.
9. **`watcher.py:344-346,606-611` — `sot watch --daemon` không bao giờ khởi động được trên Windows.** `_process_identity` trả `None` trên win32 → `start_daemon` coi là unverifiable, kill con vừa spawn. Nền tảng có code hỗ trợ đầy đủ nhưng deterministically fail.
10. **`verifier.py:395-421` — jit_reconcile gán FRESH không phụ thuộc kết quả reconcile.** Dù commit conflict/failed, verdict vẫn FRESH → [STRONG] có thể khẳng định trên content chưa re-index.

### 2.4 query-analytics

11. **`cli.py:2096` + `diff_impact.py:256-263` — default `HEAD~1` phân tích nhầm commit.** Single target diff `target~1..target` → lệnh mặc định chạy `HEAD~2..HEAD~1`, tức blast radius của commit *lùi 2*, không phải commit mới nhất hay working tree.
12. **`diff_impact.py:378` — dòng content chứa chữ "differ" bị coi là binary.** `"differ" in line` chạy trên mọi dòng diff (kể cả `+`/`-`), một dòng log/doc chứa "differ" tắt toàn bộ hunk còn lại của file đó → under-report blast radius.
13. **`diff_impact.py:1006-1007,1030-1031,1136` — substring matching thổi phồng impact.** API endpoint match `LIKE '%sym%'` (`get` khớp `getUserController`); test discovery `path LIKE '%test%'` khớp `src/latest/`, `contest.py` — mâu thuẫn với `_is_test_path()` chặt hơn ngay trong cùng file.
14. **`solution.py:426-438,240,476` — nội dung bịa trình bày như "SOT-Graph Verified AST Slicer".** Symbol không tìm thấy → trả template 10 bước thanh toán Unipay (msisdn/BCCS/POSTPAID_LIMIT_EXCEEDED) cho *bất kỳ* symbol nào; `_scan_related_features` chèn row "Webhook & Sync" bịa. Đây là đúng failure mode mà tool tồn tại để chống lại. *(Probe đã xác nhận: BUG_PRESENT.)*
15. **`repo_map.py:133` — `_estimate_tokens` dùng hằng số chưa định nghĩa `_CHARS_PER_TOKEN`** → NameError khi gọi (hiện là dead code nhưng là bẫy sống). *(Probe: BUG_PRESENT.)*

### 2.5 surfaces

16. **`cli.py:374,2136-2145` — `sot --db custom.db providers sync` bỏ qua `--db`.** `cmd_providers_sync` hardcode `.sot/sot.db`; evidence ledger ghi vào DB khác với DB mọi lệnh khác đọc — receipt mô tả DB user không query.
17. **`mcp_server.py:205` + `mcp_service.py:696` — MCP `sot_usages` khai báo param `scope` nhưng bỏ qua hoàn toàn.** Client filter theo subdir nhận nguyên repo, không lỗi, không cảnh báo.
18. **`mcp_server.py:299` vs `cli.py:1851` — semantics `depth` CLI≠MCP.** MCP default 1 + cap 4; CLI default 2, không cap; skill文档 ghi "default 2" — cùng câu hỏi qua MCP trả cây nông hơn cam kết.
19. **`cli.py:210-216` — `sot search --hybrid` âm thầm bỏ `--scope`** — `hybrid_search()` không có tham số scope, argparse vẫn nhận cặp cờ. *(Probe: BUG_PRESENT.)*
20. **`adapters/zcode.py:103,158,210` — adapter sinh doc/slash-command trỏ flag và MCP tool không tồn tại.** `sot pack -o`/`--depth`/`--format` không có trong parser (chỉ `--max-hops/--max-nodes/--max-bytes`); bảng quick-ref liệt kê 11 MCP tool không đăng ký (`sot_rename`, `sot_reconcile`…); `sot clean --purge-missing` không tồn tại.

### 2.6 assurance

21. **`receipts.py:509-512,659-662,772-775` — health-check ledger scope theo snapshot digest không bao giờ khớp.** Writer lưu git-head-sha (CBM) hoặc không lưu (SCIP) vào `snapshot_hash`, nhưng check filter theo SOT content digest → `scoped_runs` luôn rỗng, `provider_capability_ok: True` kể cả khi mọi provider run gần nhất fail (fail-open).
22. **`coverage.py:229-237` — tái引入 false-positive staleness mà commit `7dd9e54` vừa sửa ở db.py.** Cùng file, sha256+size khớp nhưng mtime lệch >2s (git checkout/rebase) → STALE; trong khi `db.stale_journal_files` (sha-only) trong cùng receipt báo sạch — hai nguồn staleness tự mâu thuẫn. *(Probe: BUG_PRESENT.)*
23. **`receipts.py:563-567` — `tests_to_run` render literal `"None"`.** Đọc field `test_file` không tồn tại (`TestImpact` có field `path`), `str(None)` = `"None"` sống sót qua filter `-{""}` — hướng dẫn operator chạy test "None". *(Probe: BUG_PRESENT.)*
24. **`ledger.py:156-180` — union adjudication dùng semantics definition cho mọi evidence.** Hardcode `kind: "function"` khi verify; evidence SCIP reference (span là *usage site*) luôn SPAN_MISMATCH → không bao giờ SUPPORTED, cap receipt ở PARTIAL với `unresolved_budget: 0`.

## 3. Điểm cần cải thiện (P2 chọn lọc)

**Hiệu năng hot-path:**
- `db.py:1133-1157` — rehome 1 file rename quét toàn bộ `graph_nodes` + `graph_edges` + `pending_edges` + `provider_evidence` vào Python; gọi per-file từ verifier. Sửa: pre-filter `WHERE src IN (...)`.
- `db.py:1597` + `:1575-1603` — `_resolve_pending_edges_pass` N+1 query per import edge; load toàn bộ pending rows dù `row_filter` chỉ khớp vài dòng.
- `db.py:680-688,731` — các LIKE `'%'` dẫn đầu không index được → `stale_journal_files` O(paths × journal).
- `providers/scip.py:169-182` — parse lại toàn bộ file SCIP (hàng trăm MB) cho **mỗi** call kể cả `probe()`. Sửa: cache theo (realpath, mtime, size).
- Thiếu index: `pending_edges(src)`, `provider_evidence(file_path)` (`db.py:2162,2017`).

**Robustness:**
- `ts_extract.py:600-857`, `analytics/graph.py:443-472` — đệ quy không giới hạn depth; file minified/chain sâu → RecursionError → cả file mất sạch symbol (thành PARSE_ERROR) hoặc crash analytics. Sửa: iterative stack.
- `db.py:774-786` — `mark_evidence_stale` build OR-khổng lồ không chunk >32766 biến SQLite → OperationalError hủy invalidation.
- `proc.py:161` — `start_new_session` POSIX-only; Windows không kill được process tree (mâu thuẫn contract module).
- `locking.py:115-164` — nếu `write.lock` bị xóa ngoài (git clean -x), waiter tạo inode mới → 2 writer đồng thời. Sửa: fstat verify inode sau flock.
- `importer/scip.py:91-93,263-268` — protobuf hỏng → `break` im lặng, import truncated vẫn báo success.
- `vector.py:99-114` — `index_nodes` embed subset 5000 row không ORDER BY, không bao giờ invalidate khi reconcile → graph_vec chứa id đã xóa.
- `export/html.py:119` — "standalone" nhưng kéo d3 từ CDN; máy offline nhận trang trắng.
- `export/exporter.py:283-287` — Obsidian export đè file khi sanitize gây collision tên.

**Nhất quán CLI↔MCP:**
- `cli.py:1846,671` — `sot embed --limit` khai báo nhưng không truyền vào `index_nodes`.
- `cli.py:1465,1229` — `-o` bị bỏ qua khi `--json` với diff-impact/trace (pack thì honored).
- `mcp_service.py:545-547` — scope filter MCP không escape LIKE (CLI có escape) → `scope: "_"` match tất cả.
- `cli.py:231-242` — P4 ranking factor "qualified-name match" dead vì `fqn` không copy vào row.
- `mcp_service.py:1370-1402` — timeout MCP không hủy được Python-side loop (verify_drift hash 1000 file, `_fits_response` O(n·dumps)); thread daemon chạy tiếp sau khi client nhận timeout.

**Assurance phụ:**
- `receipts.py:475-494` — cap 200 file im lặng khi bind content post-change >200 file mà vẫn ghi `snapshot_bound=True`.
- `receipts.py:517-532` — `closure_decision` dead logic: `claim_profile` mặc định "absence" khiến diff receipt không bao giờ ASSURED.
- `db.py:2428,2641` — ledger "append-only" yếu: `INSERT OR REPLACE` trên id do caller cung cấp có thể đè history.
- `db.py:320` — WAL + `synchronous=NORMAL` không fsync ledger tail theo hợp đồng "durable receipt".

## 4. Harness đánh giá tự động theo module

Đã xây dựng **`scripts/module_eval.py`** — chạy 6 scope song song theo chức năng, mỗi scope 3 lớp:

1. **Gates** (phải pass): `ruff` và `pyright` chạy một lần toàn `src/` rồi quy diag về từng scope theo file; `pytest` chạy đúng tập test file mapped vào scope (test cross-cutting được map vào nhiều scope).
2. **Probes** (trinh sát bug): 8 detector hành vi, tự chứa (tempdir), deterministic, mỗi probe tương ứng 1 P1 đã audit. Probe FAILING = bug còn đó. Sau khi sửa bug, probe chuyển ✅ và bật `--strict-probes` để CI chặn hồi quy.
3. **Report**: `evaluation/module_scope/report.{json,md}` — bảng scope × gate, chi tiết probe kèm ms.

```bash
# toàn bộ 6 scope
uv run python scripts/module_eval.py

# một scope, bỏ pyright cho nhanh
uv run python scripts/module_eval.py --scope core-storage --skip pyright

# chế độ CI sau khi các P1 đã sửa (fail nếu probe còn bắt bug)
uv run python scripts/module_eval.py --strict-probes
```

Kết quả chạy đầu tiên (commit `7dd9e54`, report đầy đủ trong `evaluation/module_scope/report.md`):

| Scope | ruff | pyright | pytest | Probes |
|---|---|---|---|---|
| assurance | ✅ 0 | ✅ 0 | ✅ 186 pass | 🐞 2/2 |
| core-storage | ✅ 0 | ❌ 1 | ✅ 108 pass | 🐞 2/2 |
| extraction | ✅ 0 | ❌ 3 | ✅ 320 pass | 🐞 1/1 |
| query-analytics | ✅ 0 | ❌ 2 | ✅ 113 pass | 🐞 2/2 |
| surfaces | ✅ 0 | ❌ 3 | ✅ 110 pass | 🐞 1/1 |
| sync-healing | ✅ 0 | ❌ 19 | ✅ 56 pass | (chưa có probe) |

Phát hiện đáng chú ý từ chính lần chạy đầu:
- **8/8 probe xác nhận bug P1 còn sống** trong code (kể cả 2 bug fail-open của digest/journal).
- **pytest 6/6 scope xanh** → toàn bộ bug trên đều nằm ngoài lưới test hiện tại.
- **pyright độc lập xác nhận 2 NameError-level bugs** mà audit tĩnh đã nắm: `_CHARS_PER_TOKEN` (repo_map.py:134) và `Set is not defined` (extractor.py:129); thêm `route_path` possibly unbound (architecture.py:683) và 19 lỗi type ở reconciler.py — tổng 28 lỗi type quy về scope. `scripts/quality_gates.sh` không thấy số nợ này vì chỉ chạy pyright trên 8 module "core" (đúng vùng assurance — scope duy nhất sạch).

## 5. Lộ trình đề xuất (theo thứ tự rủi ro × công sức)

| Giai đoạn | Việc | Scope | Cách nghiệm thu |
|---|---|---|---|
| G1 | Sửa 4 P1 "nói dối niềm tin": solution fabricated template, tests_to_run None, coverage mtime staleness, ledger health-check fail-open | assurance + query-analytics | 4 probe chuyển ✅, `--strict-probes` xanh |
| G2 | Sửa wiring surfaces: `--db` providers sync, MCP scope/usages, depth semantics, hybrid+scope, adapter docs sinh từ parser thật | surfaces | thêm probe wiring; test CLI↔MCP parity |
| G3 | Sửa extraction đúng nghĩa: SCIP relationships, Go import block, `this.x()` resolution, SCIP kind map, nested gitignore | extraction | test fixtures Go/SCIP mới |
| G4 | Sửa sync: watcher re-enqueue LockBusy, `_supported()` gate, Windows daemon identity, jit FRESH theo outcome | sync-healing | test watcher chaos + Windows CI matrix |
| G5 | Perf db: escape LIKE journal, pre-filter rehome, batch resolve pending edges, chunk mark_evidence_stale, thêm 2 index | core-storage | benchmark trước/sau trên repo thật |
| G6 | Robustness dài hạn: iterative walk thay đệ quy, inode-verify lock, vector invalidate theo reconcile, SCIP cache | nhiều scope | fuzz/property test sâu |

Sau G1 nên bổng probe mới từ các P2 còn lại vào `PROBES` registry của harness để mỗi lần sửa đều gia tăng lưới chặn hồi quy.

## 6. Kết quả sau đợt sửa (2026-09-03) — TOÀN XANH

**Trạng thái cuối:** `pytest 932/932 pass` · `ruff clean toàn cây` · `pyright 0 errors toàn cây` (đã exclude `_vendor/` — code vendored bên thứ ba) · `module_eval --strict-probes` = **ALL PASS, 0 bug, exit 0** trên cả 6 scope.

### Đã sửa trong G1–G5
- **G1 (assurance):** solution.py bỏ template bịa 10 bước + trạng thái NOT_FOUND trung thực; receipts tests_to_run đọc `path` thay `test_file`; coverage staleness theo sha+size (bỏ mtime); ledger cross-check ngừng bỏ qua failed runs.
- **G2 (surfaces):** `sot providers sync --db`; MCP usages/search tôn trọng `scope` (kèm escape LIKE `ESCAPE '\'`); `sot_explore` depth mặc định 2; hybrid_search hỗ trợ scope; adapter docs đồng bộ tên MCP thật.
- **G3 (extraction):** SCIP field 3 = Relationship (luôn parse) + field 17 kind enum; Go `import (...)` block state-machine giữ số dòng thật; receiver `this/self/cls` resolve; SCIP_KIND_MAP tái sinh 87 entry từ scip.proto chuẩn; nested .gitignore/​.sotignore + negation precedence.
- **G4 (sync-healing):** watcher re-enqueue LockBusy (pending set + retry 0.2s); reconciler `_supported()` gate trả "excluded"; Windows daemon identity qua CIM (Get-CimInstance) thay fail cứng; verifier jit-FRESH theo reconcile outcome thật.
- **G5 (core-storage + query-analytics):** journal LIKE escape 3 site; manifest digest fail-closed (TypeError/OperationalError); mark_evidence_stale chunk 200/statement (<999 params); index `idx_pending_src`, `idx_p_evidence_file_path`; snapshot dirty phân biệt non-git (0) vs repo không verify được (1, fail-closed); diff-impact bỏ match `"differ"` trong hunk + API exact-match + test discovery escape; pack.py tính `trusted_instructions` vào byte-cap; extractor import-provenance chuẩn hoá theo `dotted_module` (src-layout).

### Bug runtime phát hiện thêm khi xử pyright (không nằm trong audit ban đầu)
- `extractor.py`: import cục bộ `dotted_module` bên trong hàm che import module-level → `UnboundLocalError` làm **mọi reconcile .py đều failed** (đã sửa).
- `verifier.py:181`: `len(name_hits)` trên biến **int** → TypeError tiềm ẩn khi nhánh ±2 tolerance chạy (đã sửa thành `name_hits <= 1`).
- `db.py` migration: chuỗi SQL đứt dòng (SyntaxError, chặn import cả package) — tách thành 2 execute.
- `envelope.wrap_envelope`: digest fail-closed khiến CLI crash trên DB thiếu schema — transport layer giờ ghi marker `unavailable:<Error>` + `fallbacks_applied` thay vì nuốt hoặc crash.

### Test thay đổi theo contract mới (4 test)
- `test_p5_coverage_verification.py`: gap code `parser-failed` → `stale-content`.
- `test_watcher_daemon.py` (2 test): Windows identity contract mới — CIM được thử, degrade về None.
- `test_snapshot_binding.py` (fixture v5): bổ sung bảng `file_journal` cho đúng schema v5 thật (digest fail-closed làm lộ chỗ hụt của fixture).

### Việc còn treo (G6 — không chặn)
Iterative walk thay đệ quy sâu, inode-verify lock, vector invalidate theo reconcile, SCIP cache, benchmark trước/sau cho các index G5.

## 7. G6 — Robustness dài hạn (2026-09-03) — HOÀN TẤT

**Trạng thái:** `pytest 939/939` (+7 test hồi quy mới) · `ruff` + `pyright` 0 lỗi toàn cây · `module_eval --strict-probes` ALL PASS, 0 bug, exit 0.

| Mục | Sửa | Test hồi quy |
|---|---|---|
| locking.py | Sau flock: verify fd inode == path inode và nlink ≥ 1; inode mồ côi (lock bị xóa/thay giữa open–flock, vd `git clean -x`) bị từ chối, release rồi contend lại trên path sống | 2 test fault-injection (scenario 4b replaced, 4c unlinked) |
| analytics/graph.py | `detect_cycles` đệ quy → iterative 3-colour DFS (GRAY/BLACK + stack LIFO push đảo); chuỗi phụ thuộc 50k node không còn RecursionError | smoke 50k chain + 2-cycle đúng + cancel vẫn raise |
| vector.py | `index_nodes` thêm `ORDER BY id` (subset >5000 hết xoay vòng giữa các lần chạy); sửa leak early-return (graph rỗng giờ dọn sạch graph_vec); thêm `prune_orphans()` gọi cuối `Reconciler.reconcile()` — embedding hết "thấy ma" node đã xóa | 3 test (deterministic subset, reconcile prune, empty rebuild) |
| providers/scip.py | Cache parse 1-entry theo (realpath, mtime_ns, size); probe + query trên cùng index chỉ parse 1 lần (index SCIP hàng trăm MB); đổi file → cache miss; trả bản copy chống poison | 1 test đếm parse-call |
| ts_extract.py | `walk()` đệ quy ~250 dòng → `visit()` trả pending-list + driver stack LIFO push đảo (bảo toàn thứ tự duyệt pre-order gốc, mọi nhánh return sớm giữ nguyên); bundle minified lồng 3000 tầng parse bình thường thay vì RecursionError mất cả file | 1 test deep-nest 3000 |
| db.py (nợ G5) | `_resolve_pending_edges_pass` nhận `filter_symbols`/`filter_path` push xuống SQL (`dst_symbol IN` chunk 250 OR `path =`) — per-file commit hết materialize cả bảng pending; `rehome_file_atomically` bỏ 3 scan toàn bảng (graph_nodes ids, graph_edges, pending_edges) → pre-filter SQL prefix-LIKE (path forms × `file:`/`sym:` namespace + hashed namespace tokens) + IN-probe chunked cho membership test | 60 test rehome/pending/identity/storage xanh |

**Bài học rehome:** pre-filter theo prefix-path KHÔNG đủ — `remap_id` còn đổi hashed namespace ids (`file:<sha12>`/`sym:<sha12>`) không chứa text path; phải thêm prefix của namespace tokens vào điều kiện SQL nếu không cross-file edges tới file đổi tên bị sót (test `test_rehome_updates_hashed_ids_and_all_edge_endpoints` bắt đúng case này).
