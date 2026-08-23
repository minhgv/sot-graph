# SOT-Graph — Goal Roadmap và định hướng triển khai

**Baseline:** commit `870f27f7333724318bab8fd69ce265bf0e63b60e`, phiên bản `0.1.0`  
**Khung kế hoạch:** 12 tuần, 1–2 maintainer, Python-first  
**Định vị mục tiêu:** verified code-navigation layer — “la bàn có bằng chứng”, không tự nhận là semantic source of truth hay hệ thống refactor tự động.

## 1. North Star

Mỗi kết quả mà SOT-Graph trả cho agent hoặc người dùng phải trả lời được năm câu hỏi:

1. **Ở đâu?** File, symbol và span cụ thể.
2. **Còn đúng với filesystem hiện tại không?** Hash/generation và trạng thái freshness.
3. **Vì sao kết quả này liên quan?** Loại match và provenance.
4. **Tin quan hệ này đến mức nào?** Confidence của edge/resolver.
5. **Kết quả có đầy đủ không?** Số resolved, unresolved, phạm vi parser hỗ trợ và giới hạn đã biết.

North Star metric:

> Agent đạt độ chính xác tác vụ không thấp hơn workflow đọc file truyền thống, trong khi giảm ít nhất 60% context token; mọi kết quả không đầy đủ phải tự khai báo là `PARTIAL` hoặc `UNKNOWN`, không tạo cảm giác chắc chắn giả.

## 2. Nguyên tắc sản phẩm

### 2.1. Evidence trước convenience

- Không chuyển trạng thái “không kiểm tra được” thành `STRONG`.
- Không trả “0 usages” nếu còn call candidate chưa resolve có thể liên quan.
- Không gộp freshness, relevance và semantic confidence thành một nhãn duy nhất trong API.
- Một composite score có thể dùng để sắp xếp UI, nhưng các chiều bằng chứng gốc phải luôn được giữ lại.

### 2.2. Precision-first, nhưng phải công khai recall

- Không gắn bừa target cho dynamic call.
- Giữ `unresolved` là lựa chọn đúng.
- Tuy nhiên, mọi query ảnh hưởng phải kèm chỉ báo completeness để người dùng biết graph đang thiếu bao nhiêu.

### 2.3. Python đạt chuẩn trước khi mở rộng ngôn ngữ

- Python là reference implementation cho resolver, benchmark và output contract.
- Chỉ công bố một ngôn ngữ là “semantic” sau khi đạt accuracy gate.
- Tree-sitter structural extraction và regex fallback phải được công bố là cấp hỗ trợ thấp hơn.

### 2.4. Search là read; repair là thao tác riêng

- `search`, `explore`, `usages`, MCP read API không nên âm thầm sửa index.
- Tách rõ `inspect`, `repair`, `reconcile` để hành vi CLI/MCP nhất quán và dễ audit.

### 2.5. Graph định hướng; source và test quyết định

- SOT-Graph phải chỉ rõ khi nào người dùng cần mở source, chạy LSP, compiler/type checker hoặc test.
- Không đưa auto-edit/auto-rename vào stable API trước khi reference recall đạt ngưỡng.

## 3. Goals cấp sản phẩm

| Goal | Kết quả mong muốn | KPI chính | Ưu tiên |
|---|---|---|---|
| G1. Trust Model v2 | Tách freshness, relevance, edge confidence và completeness | 0 trường hợp `STRONG` khi content không được kiểm tra | P0 |
| G2. Index Integrity | Index tái tạo được, không corruption, hành vi đồng thời xác định | 0 lỗi `quick_check` qua 100 vòng test/rebuild/concurrent read-write | P0 |
| G3. Accuracy Benchmark | Có ground truth và đo precision/recall thật | Benchmark công khai, chạy trong CI, có regression gate | P0 |
| G4. Semantic Resolver | Python usages/calls đủ chính xác để phân tích ảnh hưởng có điều kiện | Call-edge precision ≥95%, recall ≥80% trên corpus chuẩn | P1 |
| G5. Agent Context | Context pack luôn fresh, đúng ngân sách và nêu uncertainty | ≥60% token reduction, task accuracy không giảm so với baseline | P1 |
| G6. Compass UX | Người và agent nhìn thấy đường đi, hop và mức đầy đủ | 90% task tìm file đúng có gold file trong top-k map/search | P1 |
| G7. Language Fidelity | Mức hỗ trợ từng ngôn ngữ minh bạch, có gate riêng | Không quảng bá “semantic support” nếu chưa có benchmark | P2 |
| G8. Release Readiness | CI, migration, tài liệu và release discipline ổn định | Clean install/rebuild/test trên ma trận hỗ trợ | P1 |

## 4. Roadmap 12 tuần

### Phase 0 — Ổn định và đo lường (Tuần 1–2, release `0.1.1`)

**Mục tiêu:** có baseline đáng tin trước khi thay resolver.

Deliverables:

- Sửa cấu hình pytest để `scripts/test_real_repos.py` không bị collect như test thông thường.
- Xóa đường dẫn máy cá nhân khỏi test; chuyển repo fixture thành cấu hình hoặc temporary repo.
- Dựng CI tối thiểu cho Python 3.10–3.13 trên Linux; thêm macOS/Windows sau khi Linux ổn định.
- Test bốn trạng thái: không có `.sot`, index sạch, index stale và index tồn tại từ lần chạy trước.
- Tạo stress test: rebuild, incremental reconcile, nhiều reader/một writer, process interruption.
- Chạy `PRAGMA quick_check` sau các test integrity và lưu artifact chẩn đoán khi fail.
- Thêm `sot doctor` hoặc `sot stats --health` để báo schema, generation, journal, pending edge và DB health.
- Chốt corpus benchmark Python đầu tiên: chính sot-graph cộng 3–5 repo mã nguồn mở có test và LSP index ổn định.

Exit criteria:

- `pytest` chạy từ project root thành công trên checkout sạch.
- Full suite chạy lặp lại 10 lần với index sạch/cũ mà không có SQLite corruption.
- CI có accuracy/performance baseline, dù chưa đặt gate cao.
- Mọi benchmark có mô tả dataset, hardware, cold/warm cache và đơn vị đo.

### Phase 1 — Trust Model v2 và lifecycle rõ ràng (Tuần 3–4, release `0.2.0`)

**Mục tiêu:** nhãn tin cậy phản ánh đúng loại bằng chứng.

Đề xuất contract:

```text
freshness:    FRESH | STALE | MISSING | UNKNOWN
relevance:    EXACT_SYMBOL | EXACT_SPAN | FILE_TOKEN | NAME_ONLY | UNKNOWN
resolution:   EXACT | INFERRED | AMBIGUOUS | UNRESOLVED
completeness: COMPLETE | PARTIAL | UNKNOWN
confidence:   0.0 .. 1.0
provenance:   parser/resolver/version/rule
```

Deliverables:

- Thay `[STRONG]/[WEAK]` nội bộ bằng evidence object nhiều chiều; giữ compatibility renderer trong một release nếu cần.
- Coverage phải tính trên symbol/span khi span tồn tại; file-level match chỉ được ghi là `FILE_TOKEN`.
- File quá lớn, binary hoặc đọc thất bại trả `UNKNOWN`, không trả freshness/relevance mạnh.
- Mọi `usages`, `implementations`, `impact` trả cả `resolved_count`, `unresolved_candidate_count` và completeness.
- Tách read API khỏi repair API; MCP và CLI dùng cùng semantics.
- Rehome cả file atomically: journal, toàn bộ nodes, edges và file record trong một transaction.
- Dò move/rename bằng content hash trước; basename chỉ là fallback candidate.
- Version hóa DB schema và rebuild tự động khi resolver/parser version không tương thích.

Exit criteria:

- Không có testcase nào mà content không được đọc nhưng kết quả mang relevance mạnh.
- `0 usages` luôn đi kèm `COMPLETE`, hoặc được trình bày thành “0 confirmed, N unresolved”.
- Move và rename file giữ được toàn bộ symbol/edge hoặc chủ động đánh dấu cần reconcile; không để trạng thái nửa cũ nửa mới.

### Phase 2 — Semantic Resolver Python (Tuần 5–8, release `0.3.0`)

**Mục tiêu:** nâng độ đầy đủ của call/reference graph mà không hy sinh precision.

Thứ tự resolver đề xuất:

1. Symbol cùng lexical scope.
2. Fully qualified name và module-local declaration.
3. Import, alias và re-export.
4. `Class.method`, static/class method.
5. Receiver từ annotation, assignment và constructor flow đơn giản.
6. Inheritance/MRO và implementation candidates.
7. Framework plugin có opt-in cho pattern phổ biến.
8. Không đủ bằng chứng: giữ unresolved với reason code.

Schema edge nên bổ sung:

- `source_file_hash`, `target_file_hash`.
- `resolver_stage`, `resolver_version`.
- `confidence`, `ambiguity_count`.
- `evidence_span` và `reason_code`.

Deliverables:

- Resolver import/alias xuyên file.
- Resolver class/static method và receiver có type hint.
- Call graph qua inheritance với nhiều candidate thay vì chọn ngẫu nhiên.
- Reason taxonomy: `EXTERNAL`, `DYNAMIC_RECEIVER`, `MISSING_IMPORT`, `MULTIPLE_TARGETS`, `UNSUPPORTED_SYNTAX`.
- So sánh output với Pyright/Jedi hoặc SCIP/LSP index trên corpus chuẩn.
- Bộ golden fixtures cho từng pattern; mutation test để phát hiện resolver “ăn may”.

Exit criteria:

- Precision confirmed call edges ≥95% trên corpus.
- Recall eligible project-local calls ≥80%; external/dynamic calls được loại khỏi mẫu số theo quy tắc công khai.
- Case `TrustVerifier.verify_hit` tìm thấy các caller trực tiếp trong CLI, MCP và tests.
- Không tăng false-positive rate để đổi lấy recall.

### Phase 3 — Compass UX và context an toàn (Tuần 9–10, release `0.4.0`)

**Mục tiêu:** biến graph thành đường dẫn hành động dễ hiểu.

Deliverables:

- `explore` hiển thị hop, path và direction; depth 2 không được trình bày như edge trực tiếp.
- Deduplicate node, collapse hub, mặc định giới hạn số nhánh; cung cấp `--all` khi cần.
- `usages` chia rõ `confirmed`, `possible`, `unresolved`.
- Repo map hiển thị coverage/fidelity của các file/ngôn ngữ được đưa vào.
- Context pack live-verify cả target và neighbor trước khi xuất.
- Enforce ngân sách trên output cuối cùng; token estimator có adapter theo model, fallback mới dùng byte/4.
- Cấu trúc pack thành bốn tầng: target code, confirmed dependencies, possible dependencies, project instructions.
- Toàn bộ nội dung lấy từ repo mặc định là untrusted; chỉ policy/instruction ngoài repo mới có thể được đánh dấu trusted.
- Thêm “next best action”: mở source, reconcile, hỏi LSP, chạy test hoặc inspect unresolved.

Exit criteria:

- Không có node depth 2 bị hiển thị như direct dependency.
- Pack không vượt ngân sách quá 5% với tokenizer được hỗ trợ.
- 100% fragment trong pack có file hash/generation và evidence level.
- Agent benchmark đạt accuracy không thấp hơn full-file baseline, giảm ≥60% token median.

### Phase 4 — Beta cứng và language fidelity (Tuần 11–12, release `0.5.0`)

**Mục tiêu:** phát hành beta mà người dùng hiểu rõ giới hạn.

Định nghĩa tier ngôn ngữ:

| Tier | Khả năng |
|---|---|
| L0 Text | Chỉ FTS/text, không tuyên bố symbol semantics |
| L1 Structural | Symbols/imports từ parser hoặc Tree-sitter |
| L2 Linked | Definitions và một phần references đã resolve |
| L3 Semantic | Precision/recall đạt gate công bố |

Deliverables:

- Công bố fidelity matrix theo phiên bản parser và ngôn ngữ.
- Python đạt L3; chọn tối đa một trong TypeScript/Go làm ngôn ngữ L3 tiếp theo dựa trên nhu cầu thực tế.
- Các ngôn ngữ fallback chỉ công bố L0/L1.
- Tài liệu migration, troubleshooting, trust semantics và workflow an toàn.
- Release notes, changelog, signed tag và benchmark snapshot.
- Dogfood trên ít nhất 10 repo về kích thước và phong cách khác nhau.

Exit criteria:

- Clean install, index, query, rebuild và uninstall thành công trên ma trận hỗ trợ.
- Không có P0; P1 còn lại đều có workaround và được ghi trong known limitations.
- Benchmark có thể tái tạo bằng một command trong CI hoặc container chuẩn.

## 5. Roadmap sau 12 tuần

### `0.6` — Multi-language semantic support

- TypeScript/JavaScript: module resolution, class/interface, method receiver.
- Hoặc Go: package/import, method set, interface implementation.
- Chỉ chọn một hướng trước; không mở đồng thời nhiều resolver.

### `0.7` — Change impact có điều kiện

- Impact paths kèm confidence và unresolved boundary.
- So sánh graph trước/sau diff.
- Risk score dựa trên evidence, không chỉ centrality.

### `1.0` — Stable navigation contract

Chỉ gắn `1.0` khi:

- Evidence API ổn định và có migration policy.
- Python semantic benchmark đạt gate trong ít nhất ba release liên tiếp.
- Không có integrity regression nghiêm trọng trong ba release.
- Agent benchmark đo task success, không chỉ token/time.
- Tài liệu nêu rõ những việc tool không bảo đảm.

Auto-rename hoặc autonomous edit không phải điều kiện của `1.0`; đó là sản phẩm khác và chỉ nên làm sau khi reference accuracy đủ cao.

## 6. Backlog có thể chuyển thẳng thành GitHub Issues

### P0 — Làm ngay

1. **P0-01: Fix root pytest collection**  
   AC: `pytest -q` từ root không collect benchmark script; CI pass trên checkout sạch.

2. **P0-02: Reproduce and eliminate existing-index corruption**  
   AC: test matrix sạch/stale/tái sử dụng index chạy 100 vòng; `quick_check=ok` sau mỗi vòng; có regression test từ case tái tạo.

3. **P0-03: Trust evidence schema v2**  
   AC: freshness, relevance, resolution, completeness độc lập trong Python API, CLI JSON và MCP.

4. **P0-04: Accuracy benchmark harness**  
   AC: ground truth versioned; xuất precision/recall/F1 theo edge kind và language; CI so với baseline.

5. **P0-05: Honest zero-result semantics**  
   AC: không trả “no usages” nếu còn unresolved candidates; output hướng dẫn bước kiểm chứng tiếp theo.

### P1 — Giá trị cốt lõi

6. **P1-01: Python import and alias resolver**
7. **P1-02: Class/static/receiver method resolver**
8. **P1-03: Atomic file move/rename by content hash**
9. **P1-04: Explore path/hop renderer**
10. **P1-05: Live-verified, hard-budget context pack**
11. **P1-06: `sot doctor` health and completeness report**
12. **P1-07: DB schema/parser/resolver version migration**

### P2 — Sau khi accuracy ổn định

13. **P2-01: Language fidelity matrix**
14. **P2-02: TypeScript hoặc Go semantic resolver**
15. **P2-03: Before/after change-impact graph**
16. **P2-04: Human visualization filters theo confidence/hop/community**
17. **P2-05: IDE integration hoặc richer MCP workflow**

## 7. Cách tổ chức thực hiện

### Nếu có một maintainer

- Làm tuần tự Phase 0 → Phase 1 → benchmark → resolver.
- Không làm UX lớn trước khi evidence contract ổn định.
- Mỗi tuần dành khoảng 60% cho core/accuracy, 25% test/benchmark, 15% docs/release.

### Nếu có hai maintainer

- **Track A — Integrity & Trust:** DB, lifecycle, evidence contract, pack verification.
- **Track B — Accuracy & Benchmark:** ground truth, resolver, language fixtures.
- Cùng hội tụ ở Phase 3 để thiết kế CLI/MCP output dựa trên schema đã ổn định.

### Nhịp làm việc đề xuất

- Mỗi PR chỉ thay một lớp: extraction, resolution, verification hoặc presentation.
- PR thay resolver phải kèm golden fixtures và thay đổi accuracy report.
- Hàng tuần lưu benchmark snapshot; không tối ưu performance nếu chưa chỉ ra bottleneck bằng profiling.
- Mỗi release có dogfood report trên chính sot-graph và ít nhất hai repo ngoài.

## 8. Definition of Done cho mọi thay đổi graph

Một issue chỉ được đóng khi:

- Có unit test cho happy path, ambiguity, missing/stale file và unsupported syntax.
- Có integration test sau rebuild sạch và reconcile incremental.
- Không làm giảm accuracy metric ngoài tolerance đã thống nhất.
- Không làm tăng p95 latency quá 20% nếu không có lý do được ghi lại.
- DB `quick_check` thành công sau test concurrent/lifecycle liên quan.
- JSON/MCP contract và CLI renderer phản ánh cùng semantics.
- Known limitation được cập nhật nếu còn trường hợp không xử lý.
- Có migration/rebuild behavior rõ nếu thay schema hoặc resolver version.

## 9. Những việc chủ động chưa làm

Trong 12 tuần đầu, không ưu tiên:

- Thêm hàng loạt ngôn ngữ mới.
- Auto-edit hoặc auto-rename production.
- Embedding/vector search như mặc định bắt buộc.
- Cloud collaboration, hosted graph hoặc account system.
- Visualization cầu kỳ nhưng không hiển thị confidence/completeness.
- Benchmark chỉ nhấn mạnh token và tốc độ mà không đo task accuracy.

Các hạng mục này tạo độ rộng sản phẩm nhưng không sửa rủi ro cốt lõi: người dùng có thể tin một graph chưa đầy đủ.

## 10. Quy trình sử dụng khuyến nghị trong thời gian roadmap đang được thực hiện

```text
sot map/search
    → sot explore/usages
    → kiểm tra resolved + unresolved
    → mở source thật
    → đối chiếu rg/LSP/SCIP khi refactor quan trọng
    → chạy compiler/type checker/test
```

SOT-Graph nên được truyền thông nhất quán là:

> “Giúp bạn biết nên nhìn ở đâu tiếp theo, cho biết bằng chứng nào còn tươi và phần nào chưa chắc chắn.”

Không nên truyền thông là:

> “Graph đã biết đầy đủ mọi nơi cần sửa.”

## 11. Dashboard release đề xuất

Mỗi release nên công bố cùng một bảng:

| Nhóm | Chỉ số |
|---|---|
| Integrity | Rebuild success, `quick_check`, concurrency/lifecycle failures |
| Freshness | Fresh/stale/unknown classification accuracy |
| Search | Symbol precision, gold-file top-k hit rate |
| Graph | Edge precision/recall/F1, unresolved ratio theo reason |
| Context | Task success, token reduction, budget overshoot |
| Performance | Cold/warm query p50/p95, incremental/full reconcile time |
| Compatibility | Python/platform/parser matrix |

Dashboard này là cơ chế giữ dự án đi đúng hướng: độ chính xác và tính trung thực phải tăng trước số lượng tính năng.

