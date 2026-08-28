# SOT-Graph — Đánh giá lại mức độ hoàn thiện so với roadmap

**Ngày đánh giá:** 2026-08-28  
**Repository:** [minhgv/sot-graph](https://github.com/minhgv/sot-graph)  
**HEAD được đánh giá:** [`a5d50c008aa6e47bcba803b6f2be4d4f8a83a302`](https://github.com/minhgv/sot-graph/commit/a5d50c008aa6e47bcba803b6f2be4d4f8a83a302)  
**Mục tiêu cuối:** hệ thống bảo chứng phạm vi ảnh hưởng ở mức `ASSURED_WITHIN_SCOPE`  
**Ràng buộc kiến trúc:** provider-neutral; builtin hoạt động độc lập; provider bên ngoài là tùy chọn và không tự động được coi là nguồn sự thật.

## 1. Kết luận điều hành

Repo đã tiến bộ rõ rệt về test, benchmark, cấu trúc assurance và khả năng tìm kiếm. Tuy nhiên, trạng thái hiện tại **chưa đủ an toàn để dùng receipt làm cổng quyết định thay đổi mã nguồn**.

Đánh giá thực tế:

| Năng lực | Mức đánh giá | Kết luận |
|---|---:|---|
| Navigation và tìm kiếm mã nguồn | **8/10** | Beta tốt, có giá trị sử dụng thực tế |
| Static graph trên tập benchmark hiện có | **Khá cao** | Cần thêm holdout repo thật và kiểm chứng dynamic behavior |
| Impact assurance | **4/10** | Có prototype và primitives nhưng các invariant cốt lõi chưa đóng |
| Hoàn thành roadmap `R0–R9` | **Khoảng 40–45%** | Nhiều phase có code nhưng chưa đạt exit gate |
| Production readiness cho assurance gate | **3/10** | CI đỏ và có counterexample tạo false assurance |

Phán quyết:

> **GO** cho discovery, navigation, candidate scope và advisory analysis.  
> **NO-GO** cho `ASSURED_WITHIN_SCOPE`, rename/delete gate, exhaustive caller claim hoặc quyết định “không còn tác động nào khác”.

Vấn đề lớn nhất không còn là thiếu class hay thiếu test đơn vị. Vấn đề là hệ thống có thể phát hành trạng thái bảo chứng mạnh hơn bằng chứng thực sự mà nó đang nắm giữ.

## 2. Bằng chứng kiểm chứng

### 2.1 Test và coverage tại local

- `817 passed`, `1 skipped` trong môi trường hiện có.
- Tổng line coverage: **81%**.
- Coverage một số vùng quan trọng:
  - Assurance receipts: **93%**.
  - Assurance orchestrator: **87%**.
  - Codebase Memory adapter: **91%**.
  - CLI: **61%**.
  - MCP server: **55%**.
  - Watcher: **53%**.

Kết quả benchmark static edge theo oracle tuple hiện tại:

| Chỉ số | Kết quả |
|---|---:|
| Precision | **99,8%** |
| Recall | **99,2%** |
| F1 | **99,5%** |

Kết quả search benchmark hiện tại:

| Chỉ số | Kết quả |
|---|---:|
| Hit@1 | **60%** |
| Hit@5 | **75%** |
| Hit@10 | **100%** |

Các con số này chứng minh nền tảng tìm kiếm và static extraction đã mạnh hơn trước, nhưng chưa đủ để suy ra completeness trên codebase thực tế hoặc độ chính xác của blast radius.

### 2.2 Giới hạn của môi trường local

Local test được chạy trên môi trường dependency đã tồn tại và dùng `PYTHONPATH`. Clean `uv sync --all-extras` trên VM dừng khi build `tree-sitter-graphql` vì môi trường không có `clang`.

Đây là giới hạn của VM, chưa đủ để kết luận packaging của repo bị lỗi. Kết luận release phải dựa thêm trên CI chính thức.

### 2.3 Trạng thái GitHub Actions

[GitHub Actions run 33150572364](https://github.com/minhgv/sot-graph/actions/runs/33150572364) tại HEAD được đánh giá:

- **5 jobs thành công**.
- **11 jobs thất bại**.
- **1 job skipped**.
- 3 package-smoke jobs thành công.
- Oracle benchmark thành công.
- Lint/compile smoke thành công.
- 9 test matrix jobs thất bại.
- Quality gate thất bại.
- Real-Codebase-Memory E2E thất bại.

Quality gate có lỗi có thể tái hiện trực tiếp:

```text
npx -y ruff --version
→ npm error
```

`ruff` là Python tool nhưng workflow gọi qua `npx`. Gate này cần dùng dependency đã pin và chạy qua môi trường Python, ví dụ `uv run ruff`.

Raw log chi tiết của một số job cần đăng nhập GitHub nên chưa đủ bằng chứng để kết luận nguyên nhân cụ thể của 9 test jobs và real-CBM E2E. Báo cáo này không suy đoán nguyên nhân khi chưa có log.

## 3. Các lỗi có thể tạo false assurance

### 3.1 `scope_receipt` có thể trả `ASSURED` dù coverage bằng 0

Logic receipt hiện chủ yếu hạ cấp khi gặp stale evidence. Nó chưa bắt buộc đầy đủ các điều kiện:

- target identity phải duy nhất;
- snapshot phải bind với nội dung hiện tại;
- bounded scope phải có coverage đạt ngưỡng;
- parser không được lỗi;
- unresolved references phải nằm trong ngân sách cho phép;
- không có conflict chưa xử lý;
- kết quả không bị truncation hoặc pagination thiếu;
- provider phải có capability phù hợp;
- external evidence phải được verify độc lập.

Counterexample đã tái hiện: receipt có `coverage = 0`, có parser failure nhưng vẫn phát hành `ASSURED`.

Implementation liên quan: [assurance/receipts.py](https://github.com/minhgv/sot-graph/blob/a5d50c008aa6e47bcba803b6f2be4d4f8a83a302/src/sot_graph/assurance/receipts.py#L253-L354).

Đây là blocker P0 vì receipt hiện có thể biến “không thấy bằng chứng xấu” thành “đã chứng minh đủ”.

### 3.2 Target ambiguity bị che bởi `LIMIT 1`

Lookup symbol hiện có đường đi chọn một node đầu tiên thay vì trả trạng thái ambiguity. Với hai symbol cùng tên ở `a.py` và `b.py`, hệ thống có thể chọn `a.py` rồi tiếp tục phát hành receipt mạnh.

Yêu cầu đúng phải là một trong ba trạng thái:

```text
UNIQUE | AMBIGUOUS | NOT_FOUND
```

Không được chọn ngầm một target khi identity chưa duy nhất.

### 3.3 Dirty fingerprint chưa bind với nội dung file

Dirty snapshot hiện dựa chủ yếu vào danh sách trạng thái Git. Nếu một file vẫn ở trạng thái modified nhưng nội dung thay đổi từ phiên bản dirty `v1` sang `v2`, Git status có thể không đổi.

Counterexample đã tái hiện:

```text
dirty_fingerprint(v1) == dirty_fingerprint(v2)
snapshot_digest(v1)   == snapshot_digest(v2)
```

Như vậy evidence tạo trên `v1` có thể bị tái sử dụng cho `v2`.

Implementation liên quan: [snapshot.py](https://github.com/minhgv/sot-graph/blob/a5d50c008aa6e47bcba803b6f2be4d4f8a83a302/src/sot_graph/snapshot.py#L69-L91).

Snapshot phải bind tối thiểu với content hash của mọi file nằm trong bounded scope hoặc mọi cited path.

### 3.4 Evidence ledger mặc định nâng evidence lên `SUPPORTED`

`union_evidence()` có thể gán trạng thái `SUPPORTED` khi evidence chưa có đủ:

- snapshot binding;
- file path;
- source span;
- verification result;
- current-snapshot check.

Counterexample đã tái hiện: external evidence không bind snapshot, path rỗng, nhưng kết quả union vẫn là `SUPPORTED`.

Ngoài ra, provider run, project binding và evidence đang có các đường ghi transaction rời nhau. Nếu một bước thất bại, ledger có thể lưu trạng thái không nguyên tử.

Implementation liên quan: [assurance/ledger.py](https://github.com/minhgv/sot-graph/blob/a5d50c008aa6e47bcba803b6f2be4d4f8a83a302/src/sot_graph/assurance/ledger.py#L48-L134).

Nguyên tắc cần áp dụng:

> Evidence chỉ được nâng lên `SUPPORTED` sau khi snapshot, identity, path/span và verification đều vượt gate tương ứng. Thiếu một điều kiện phải fail-closed.

### 3.5 MCP không thực thi đúng `require_external`

Policy `require_external` có thể vẫn trả kết quả builtin khi provider ngoài không khả dụng. Điều này làm response nói một policy nhưng thực thi policy khác.

Hành vi tái hiện về bản chất:

```json
{
  "provider_policy": "require_external",
  "results": [
    {"provider": "builtin"}
  ]
}
```

Với `require_external`, hành vi đúng là fail-closed hoặc trả `ABSTAINED/UNVERIFIABLE`, không fallback im lặng.

Implementation liên quan: [mcp_service.py](https://github.com/minhgv/sot-graph/blob/a5d50c008aa6e47bcba803b6f2be4d4f8a83a302/src/sot_graph/mcp_service.py#L373-L397).

### 3.6 Receipt chưa nằm trên production path duy nhất

Hiện có sự phân mảnh:

- `diff_impact_receipt` chủ yếu được gọi trong test.
- CLI còn xây response theo đường ad hoc.
- MCP sử dụng đường query thông thường.
- MCP chưa expose scope receipt thống nhất.

Do đó test receipt xanh chưa chứng minh người dùng CLI/MCP thật đang nhận cùng một state machine assurance.

### 3.7 Provider-neutral mới ở mức scaffolding

Kiến trúc mong muốn là provider-neutral, nhưng production wiring vẫn còn nhiều chỗ đặc thù:

- hardcode `CodebaseMemoryProvider`;
- chế độ `all` có đường chỉ dùng provider đầu tiên;
- plugin registry thiên về detection hơn orchestration;
- SCIP chủ yếu là importer, chưa phải provider ngang hàng trong shared assurance pipeline.

Điều này chưa phá use case hiện tại, nhưng chưa đạt mục tiêu flexible federation.

## 4. Đánh giá độ chính xác tìm kiếm và graph

### 4.1 Những gì đã có bằng chứng tốt

- Exact static-edge oracle đã được sửa theo tuple thay vì chỉ dò tên symbol.
- Precision và recall rất cao trên synthetic benchmark hiện có.
- Search đạt `Hit@10 = 100%` trên tập probe hiện tại.
- Builtin graph có nền tảng tốt cho candidate discovery và navigation.

### 4.2 Những gì chưa được chứng minh

- Benchmark chủ yếu dùng corpus do dự án tự tạo.
- Mới tập trung vào năm ngôn ngữ chính.
- Ground truth Java/Rust cho quan hệ `implements` còn bằng 0, nên không đo được chất lượng quan hệ đó.
- Dynamic corpus hiện có khoảng 4 case resolve đúng, 21 case abstain và 1 case misresolve; độ phủ dynamic dispatch còn thấp.
- Search benchmark chỉ có khoảng 20 probe.
- Với nhóm truy vấn ambiguous, `Hit@5` chỉ khoảng **44,4%**.
- Chưa có exact diff-impact oracle đủ mạnh.
- Provider-union chưa có benchmark precision/recall độc lập.
- Real-CBM E2E đang đỏ trên CI.

Vì vậy không nên chuyển kết quả static benchmark thành claim “graph đầy đủ” hoặc “blast radius được bảo chứng”.

## 5. Tiến độ so với roadmap `R0–R9`

| Phase | Mục tiêu | Trạng thái thực tế | Đánh giá |
|---|---|---|---|
| `R0` | Correctness oracle và baseline trung thực | Exact edge oracle đã tốt hơn; còn thiếu holdout và quality gate xanh | **Phần lớn hoàn thành** |
| `R1` | Snapshot và trust blocker | Có snapshot model nhưng dirty content binding chưa đúng | **Một phần** |
| `R2` | Shared Assurance Orchestrator | Có orchestrator/receipt primitives nhưng CLI và MCP chưa dùng chung hoàn toàn | **Chưa đạt exit gate** |
| `R3` | Provider capability contract | Có registry và adapter contract ban đầu; production còn hardcode | **Một phần** |
| `R4` | Canonical identity và search accuracy | Search/edge accuracy tốt hơn rõ rệt; ambiguity còn nguy hiểm | **Tiến triển đáng kể, chưa đóng** |
| `R5` | Coverage và multilingual verification | Có primitives nhưng chưa chứng minh completeness trong bounded scope | **Một phần** |
| `R6` | Evidence ledger và conflict engine | Schema/API đã có; trust defaults và transaction còn không an toàn | **Prototype chưa an toàn** |
| `R7` | Scope/diff/reconcile receipts | Có receipt code và test; chưa thành production decision path | **Prototype** |
| `R8` | OMP workflow integration | Có adapter/template nhưng chưa có unified assurance gate | **Một phần** |
| `R9` | Hardening và release qualification | CI đang đỏ; real-provider E2E chưa đạt | **Không đạt** |

Tổng thể, code volume có thể tạo cảm giác roadmap đã đi xa hơn thực tế. Nếu tính theo exit gate thay vì số file/class, mức hoàn thành hợp lý là **40–45%**.

## 6. Những việc cần sửa theo ưu tiên

### P0 — Khôi phục release gate trung thực

1. Sửa quality workflow:
   - đưa `ruff` vào dev dependencies;
   - pin version;
   - chạy bằng `uv run ruff` hoặc command Python tương đương;
   - không dùng `npx` cho Python package.
2. Lấy raw log và sửa nguyên nhân của 9 test matrix jobs.
3. Làm real-CBM E2E thực sự:
   - cài/pin binary hoặc source commit;
   - index fixture repo;
   - chạy structured query;
   - assert semantic output, snapshot và provenance;
   - không chỉ kiểm tra binary khởi động.
4. Chỉ coi release qualified khi toàn bộ 17-job workflow xanh.

### P0 — Xây một assurance state machine duy nhất

Chuẩn hóa trạng thái:

```text
ASSURED_WITHIN_SCOPE
PARTIAL
CONFLICTED
STALE
UNVERIFIABLE
ABSTAINED
```

Một pure decision function phải nhận toàn bộ fact:

- target identity;
- snapshot/content binding;
- scope coverage;
- parser status;
- unresolved budget;
- provider capabilities;
- evidence verification;
- conflict state;
- pagination/truncation;
- dynamic gap declarations.

CLI, MCP và test phải gọi cùng hàm này. Không surface nào được tự xây logic assurance riêng.

### P0 — Sửa snapshot và ledger

1. Hash nội dung file trong cited paths hoặc bounded scope.
2. Evidence chỉ hợp lệ cho current snapshot.
3. Bỏ mọi default có thể tự nâng lên `SUPPORTED`.
4. Ghi provider run, binding và evidence trong một transaction nguyên tử.
5. Thêm `invalidated_at` hoặc lifecycle tương đương.
6. Verify đúng edge `(caller, relation, callee)`, không chỉ verify source anchor.
7. Có migration và invariant tests cho stale/dirty/renamed/deleted files.

### P1 — Đưa receipt vào production path

1. CLI và MCP cùng gọi shared orchestrator.
2. Expose tối thiểu:
   - scope receipt;
   - diff-impact receipt;
   - reconcile/post-change receipt;
   - audit receipt.
3. `require_external` phải fail-closed nếu external provider không chạy hoặc không đạt capability.
4. Chế độ `all` phải gọi tất cả provider đủ capability, không chỉ provider đầu tiên.
5. Receipt phải chứa reason codes và evidence references có thể audit.
6. Thêm E2E test từ command/MCP request tới persisted ledger và final status.

### P1 — Sửa identity và coverage

1. Symbol resolution phải trả `UNIQUE | AMBIGUOUS | NOT_FOUND`.
2. Loại bỏ `LIMIT 1` khỏi mọi đường cần quyết định identity.
3. Canonicalize path, repo root và language-aware qualified name.
4. Coverage phải dựa trên manifest/filesystem content, không chỉ Git status journal.
5. Negative claim chỉ được phép trong bounded scope có manifest rõ ràng.
6. Công khai excluded files, parser failures, unsupported languages và unresolved references trong receipt.

### P2 — Mở rộng benchmark accuracy

1. Thêm holdout từ repo thật, không chỉ corpus tự tạo.
2. Tăng search query set và tách rõ exact, semantic, ambiguous, path-qualified.
3. Đặt gate riêng cho `Hit@1`, `Hit@5` và MRR.
4. Xây exact diff-impact oracle theo changed symbols và expected impacted edges/files/tests.
5. Đo precision/recall của từng provider và kết quả union.
6. Thêm dynamic/reflection/DI/macro/function-pointer gap corpus.
7. Đo abstention quality: hệ thống phải biết khi nào không đủ bằng chứng.

### P2 — Sửa documentation và roadmap hygiene

1. Xóa claim tuyệt đối còn sót trong root `AGENTS.md`, docs và generated templates.
2. Phân biệt rõ:
   - `IMPLEMENTED`;
   - `LOCALLY_VERIFIED`;
   - `CI_ACCEPTANCE_VERIFIED`;
   - `PRODUCTION_QUALIFIED`.
3. Không tick phase chỉ vì đã có code hoặc unit test.
4. Mỗi phase phải có measurable exit gate và receipt CI tương ứng.

## 7. Trình tự triển khai khuyến nghị

Đường đi ngắn nhất tới hệ thống bảo chứng phạm vi ảnh hưởng:

```text
Một assurance state machine duy nhất
→ snapshot bind theo content
→ target identity duy nhất
→ manifest coverage trong bounded scope
→ ledger chỉ chứa evidence đã verify cho current snapshot
→ CLI/MCP dùng cùng production receipt path
→ provider federation đúng capability và policy
→ real-provider E2E + holdout benchmark
→ CI release gate xanh hoàn toàn
```

Không nên ưu tiên thêm provider mới trước khi năm invariant đầu tiên được đóng. Provider mới chỉ làm tăng lượng candidate; nó không tự làm tăng assurance nếu snapshot, identity, coverage và verification còn hở.

## 8. Definition of Done cho mục tiêu cuối

Chỉ phát hành `ASSURED_WITHIN_SCOPE` khi đồng thời thỏa mãn:

- target được resolve duy nhất;
- snapshot bind với nội dung hiện tại của toàn bộ bounded scope;
- manifest và exclusions được công khai;
- mọi parser failure và unsupported construct được tính vào coverage;
- evidence thuộc current snapshot và có provenance;
- source spans và edge semantics được verify;
- không còn conflict chưa xử lý;
- không bị truncation hoặc pagination thiếu;
- provider policy được thực thi đúng;
- dynamic gaps được khai báo;
- receipt có thể audit và tái lập;
- CLI và MCP trả cùng quyết định cho cùng input;
- full CI, real-provider E2E và accuracy gates đều xanh.

Nếu thiếu bất kỳ điều kiện bắt buộc nào, trạng thái phải hạ xuống `PARTIAL`, `UNVERIFIABLE`, `CONFLICTED`, `STALE` hoặc `ABSTAINED` với reason code cụ thể.

## 9. Kết luận cuối

SOT-Graph hiện đã là một công cụ navigation và search đáng dùng, với static benchmark tốt và nền tảng assurance có tiềm năng. Nhưng nó **chưa phải hệ thống bảo chứng phạm vi ảnh hưởng**, vì các đường snapshot, identity, coverage, evidence union và production receipt vẫn có thể tạo kết luận mạnh hơn dữ liệu.

Ưu tiên đúng không phải mở rộng thêm tính năng bề mặt. Cần đóng chuỗi trust từ source content đến decision receipt, rồi mới nâng trạng thái sản phẩm từ advisory beta thành `ASSURED_WITHIN_SCOPE`.
