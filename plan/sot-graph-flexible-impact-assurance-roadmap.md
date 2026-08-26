# SOT-Graph — Flexible Impact-Assurance Roadmap

> Roadmap hoàn chỉnh theo quyết định kiến trúc mới: giữ SOT-Graph độc lập với extractor, dùng provider linh hoạt, và tiến tới hệ thống bảo chứng phạm vi ảnh hưởng có bằng chứng.
>
> Ngày lập: 2026-08-26
>
> Baseline SOT-Graph đã kiểm chứng: `cb1bf693d2fbcc703018207bd2e665fb708ab32c`
>
> Codebase Memory contract baseline: `010569fa6ce1bc5d6430f858129243ea1a2e3fd5` / `0.10.8`

## 1. Quyết định kiến trúc

### 1.1 Quyết định được chọn

SOT-Graph sẽ phát triển thành **Verified Code Evidence & Impact-Assurance Layer**:

- SOT-Graph là CLI/MCP duy nhất mà người dùng và OMP cần biết.
- Builtin extractor của SOT luôn tồn tại và đủ để hệ thống hoạt động độc lập.
- Codebase Memory, SCIP, GitNexus hoặc provider khác là nguồn **candidate evidence** tùy chọn.
- Không provider nào được tự tuyên bố kết quả cuối cùng là đúng hoặc đầy đủ.
- SOT chịu trách nhiệm về canonical identity, snapshot, source verification, coverage, provenance, conflict, completeness và receipt.
- OMP chịu trách nhiệm plan, edit, test, compiler/LSP confirmation, reviewer và delivery proof.

### 1.2 Quyết định bị hủy

Không đưa toàn bộ Codebase Memory vào SOT như runtime bắt buộc hoặc fork mặc định.

Lý do:

- Làm SOT phụ thuộc vào vòng đời, binary và schema của một extractor.
- Tăng mạnh kích thước phân phối và độ phức tạp đa nền tảng.
- Biến lỗi provider thành lỗi của toàn SOT.
- Làm khó thay thế bằng SCIP, LSP, GitNexus hoặc provider tốt hơn sau này.
- Không giải quyết bản chất của assurance: một extractor mạnh vẫn không tự chứng minh snapshot, coverage và absence claim.

### 1.3 Ý nghĩa của “bảo chứng phạm vi ảnh hưởng”

SOT không cam kết biết mọi quan hệ runtime trên mọi ngôn ngữ. SOT chỉ phát hành trạng thái mạnh nhất:

```text
ASSURED_WITHIN_SCOPE
```

khi đồng thời chứng minh được:

1. Target được định danh duy nhất.
2. Snapshot khớp worktree hiện tại, gồm cả dirty state.
3. Source anchors của evidence được xác minh.
4. Scope coverage đủ cho loại claim đang đưa ra.
5. Không mất trang, không truncation và không parse gap chưa xử lý.
6. Không có conflict chưa phân xử.
7. Capability của provider phù hợp với relation và language.
8. Known gaps được khai báo và không cắt qua scope cần bảo chứng.

Nếu thiếu một điều kiện, hệ thống phải hạ mức hoặc `ABSTAIN`; không được dùng từ ngữ tương đương “không có tác động”.

## 2. Baseline đã kiểm chứng

### 2.1 Điểm đã đạt

- CLI, wheel, sdist và MCP smoke chạy được.
- 13/13 CI jobs thực thi xanh trên Linux/macOS/Windows và Python 3.10–3.12; release job không chạy vì không phải tag.
- Full suite local với all extras: `595 passed`.
- Line coverage tổng: khoảng 80%.
- Golden contract của Codebase Memory 0.10.8 đã được commit và có capture receipts.
- Adapter đã có argv-only execution, args-file, timeout, process-group kill, output classification, redaction và version gate.
- Builtin graph có reconcile, stale detection, SCIP import, diff-impact, map, pack, architecture analytics và OMP adapter.
- Stress test có 100 vòng mutation/reconcile/integrity.
- Context pack benchmark hiện giảm 81,4–92,2% token estimate trên ba target nội bộ.

### 2.2 Blocker còn tồn tại

1. Dirty edit chưa commit có thể vẫn được external snapshot đánh dấu `FRESH` nếu HEAD khớp.
2. Accuracy benchmark hiện không so khớp đúng tuple `(file, caller, relation, callee)`.
3. Exact-oracle độc lập cho baseline cho thấy relaxed direct-call recall:
   - Python: 100%;
   - Java: 100%;
   - Rust: 100% khi canonicalize bare/qualified name;
   - TypeScript: 61,5%;
   - Go: 41,7%.
4. CBM search/trace/impact vẫn phụ thuộc text parser và mất semantic fields.
5. `diff-impact` chưa truyền đầy đủ target/depth/staged/working-tree sang external provider.
6. Envelope `coverage` hiện chủ yếu là `queried=true/false`, chưa phải coverage thật.
7. CLI provider không được truyền active database; production provider runs/evidence chưa được persist đầy đủ.
8. MCP chưa gọi provider federation.
9. Chưa có scope receipt, impact receipt và assurance tiers hoàn chỉnh.
10. Source verifier mạnh mới tập trung vào Python; ngôn ngữ khác chủ yếu heuristic.
11. Agent-facing templates vẫn còn claim “100% verified/reliable/grounded”.
12. CI lint mới chỉ compile; chưa có type, style, security và coverage gates.
13. Subprocess output được cắt sau `communicate()`, chưa phải streaming hard cap.

## 3. Các invariant không được phá vỡ

1. **Provider independence:** SOT chạy được khi không có external provider.
2. **Single interface:** OMP/người dùng chỉ gọi SOT CLI/MCP.
3. **No nested MCP:** không gọi MCP của provider từ MCP của SOT.
4. **No direct foreign DB:** không đọc SQLite/schema nội bộ của provider.
5. **No implicit mutation:** read query không tự cài, tự index hoặc sửa config.
6. **Explicit sync:** index/update provider là lệnh rõ ràng, có receipt và có thể hủy.
7. **Fail closed:** stale, unbound, ambiguous, truncated, uncovered hoặc schema drift không được nâng thành assured evidence.
8. **No global completeness claim:** không dùng “100% callers”, “exact toàn codebase” hoặc tương đương.
9. **Backward compatible:** search/map/explore/usages/diff-impact/pack/report/local SQLite vẫn hoạt động khi tính năng assurance chưa được bật.
10. **Evidence before confidence:** provider confidence không thay thế source/snapshot verification.
11. **One canonical contract:** CLI và MCP dùng chung orchestration, normalization, verification và receipt builder.
12. **Final proof remains external:** compiler, type-check, tests, runtime checks và reviewer vẫn là delivery proof của OMP.

## 4. Kiến trúc mục tiêu

```text
OMP / User
    |
    v
SOT CLI + SOT MCP
    |
    v
Assurance Orchestrator
    |-- Provider Registry & Capability Router
    |     |-- SOT Builtin
    |     |-- SCIP Import Provider
    |     |-- Codebase Memory CLI Provider (optional)
    |     `-- Future Provider Plugins
    |
    |-- Canonical Identity & Relation Normalizer
    |-- Snapshot Binder
    |-- Coverage Engine
    |-- Language-Aware Source Verifier
    |-- Evidence Ledger & Conflict Engine
    |-- Impact Analyzer
    `-- Scope / Impact / Reconcile Receipt Builder
```

### 4.1 Trách nhiệm theo lớp

| Lớp | Trách nhiệm |
|---|---|
| Provider | Tìm candidate symbols, relations, paths, architecture và impact |
| Router | Chọn provider theo capability, language, assurance và health |
| Normalizer | Chuyển identity/relation/span về canonical model |
| Snapshot Binder | Gắn evidence vào HEAD + dirty fingerprint + manifest + generation |
| Coverage Engine | Chứng minh phần nào đã index/parse/verify và phần nào chưa |
| Source Verifier | Kiểm tra path, hash, span, declaration/call site trên filesystem hiện tại |
| Ledger | Lưu run/evidence/provenance/conflict theo snapshot |
| Impact Analyzer | Tính upstream/downstream, changed edges, tests và risk |
| Receipt Builder | Phát hành bằng chứng có scope, gaps, verdict và next actions |
| OMP | Dùng receipt để lập plan, sửa, test, reconcile và review |

## 5. Provider contract linh hoạt

### 5.1 Capability vocabulary

```text
SYMBOL_SEARCH
DEFINITION
REFERENCE
DIRECT_CALL
CALL_TRACE
IMPORT
INHERITANCE
IMPLEMENTATION
ARCHITECTURE
DIFF_IMPACT
PATH_COVERAGE
SNAPSHOT_METADATA
SOURCE_SPAN
```

Provider chỉ được route vào capability nó khai báo và đã vượt contract test. “Có method” không đồng nghĩa “đủ semantic quality”.

### 5.2 Canonical candidate

Mỗi candidate tối thiểu có:

```text
repo_id
provider_name
provider_version
run_id
snapshot_claim
language
path
kind
qualified_name
symbol_id | unknown
span | unknown
relation
source_identity
target_identity
direction
hop
provider_confidence | unknown
truncated
raw_evidence_digest
```

Không invent path/span/direction. Field thiếu phải là `null`, `unknown` hoặc explicit gap.

### 5.3 Provider policy

| Policy | Hành vi |
|---|---|
| `builtin` | Chỉ dùng SOT builtin |
| `auto` | Chọn provider tốt nhất theo capability, fallback builtin |
| `prefer:<name>` | Ưu tiên provider, fallback trung thực |
| `require:<name>` | Provider lỗi hoặc không đủ capability thì fail closed |
| `all` | Gọi tất cả provider queryable, giữ union và conflict |

`providers_mode=auto` trong config phải có hiệu lực mà người dùng không cần lặp `--provider auto` trên từng lệnh.

## 6. Trust và assurance model

### 6.1 Assertion verdict

```text
SUPPORTED      source span + fresh snapshot + unique identity được xác minh
HEURISTIC      candidate hữu ích nhưng chưa đủ proof
AMBIGUOUS      có nhiều target hoặc identity chưa phân giải
CONFLICT       providers/source đưa ra kết quả bất đồng chưa phân xử
STALE          evidence thuộc source/snapshot cũ
UNVERIFIABLE   thiếu dữ liệu cần thiết để xác minh
```

### 6.2 Receipt assurance

| Tier | Mục đích | Cho phép |
|---|---|---|
| `scout` | Điều hướng nhanh | Candidate discovery; không negative claim |
| `verify` | Sửa đổi có rủi ro vừa | Snapshot + source verification + cited-path coverage |
| `audit` | Rename/delete/public API/core path | Multi-provider union, bounded pagination, scope coverage, conflict report |

Kết quả receipt:

```text
ASSURED_WITHIN_SCOPE
PARTIAL
CONFLICTED
STALE
UNVERIFIABLE
ABSTAINED
```

### 6.3 Negative claim rule

`0 callers` chỉ được diễn giải là “không có caller trong scope đã bảo chứng” khi:

- target identity unique;
- snapshot fresh, gồm dirty fingerprint;
- scope manifest complete;
- provider coverage complete cho scope;
- parser không partial/error trong scope;
- pagination exhausted;
- không truncation;
- relation capability hỗ trợ language;
- không dynamic gap cắt qua scope.

Nếu không, wording bắt buộc là:

> Không tìm thấy caller trong dữ liệu và capability đã báo cáo; completeness chưa được chứng minh.

## 7. Roadmap thực thi

## R0 — Accuracy oracle và truth baseline

### Mục tiêu

Thay test xanh mang tính proxy bằng evaluator có thể phát hiện sai caller/target thật.

### Công việc

- [ ] Chuyển benchmark edge matching sang tuple exact:
  `(repo, path, source identity, relation, target identity, span)`.
- [ ] Báo precision/recall/F1 riêng theo language và relation; không chỉ aggregate.
- [ ] Tách ba tập dữ liệu:
  - positive closed-world;
  - negative/adversarial;
  - dynamic/unsupported.
- [ ] Thêm same-name symbols, alias, shadowing, nested scopes, overload, virtual/interface dispatch, reflection, DI, macros và function pointers.
- [ ] Freeze oracle version và corpus digest.
- [ ] Thêm top-k symbol-search oracle.
- [ ] Đo builtin và từng provider riêng; sau đó đo output sau SOT verification.
- [ ] Xóa hoặc đổi tên các metric hiện tại nếu không đo đúng ý nghĩa.

### Acceptance gate

- Benchmark cũ phải thất bại trên defect Go/TypeScript hiện biết.
- Một edge sai target không được tính true positive.
- Một tên xuất hiện ở đầu cạnh khác không được tính recall.
- Report có confusion set và danh sách false positives/false negatives line-anchored.
- Baseline được commit dưới dạng machine-readable JSON.

## R1 — Sửa trust blocker và chuẩn hóa snapshot

### Mục tiêu

Không evidence nào được đánh dấu fresh khi worktree đã thay đổi sau index/query.

### Công việc

- [ ] Tạo snapshot chung trước mọi assured query:
  - HEAD SHA;
  - dirty flag;
  - dirty fingerprint dựa trên nội dung, không chỉ status string;
  - manifest digest;
  - graph generation;
  - snapshot ID.
- [ ] Gắn snapshot ID vào builtin và external runs.
- [ ] Không dùng `head_sha matches` để suy ra dirty worktree fresh.
- [ ] Kiểm tra coverage/hash cho từng cited path.
- [ ] Invalidate evidence khi edit/rename/delete xảy ra.
- [ ] Phân biệt pre-change và post-change snapshot.
- [ ] Fix subprocess output thành streaming hard cap; kill process group khi vượt cap.

### Test bắt buộc

- Dirty unstaged edit, staged edit, untracked caller, rename, delete.
- HEAD giữ nguyên nhưng file content đổi.
- Provider HEAD khớp nhưng cited path stale.
- Output vô hạn/oversized bị kill và không gây memory spike không giới hạn.
- Snapshot race: file đổi giữa query và verification.

### Acceptance gate

- Zero `SUPPORTED`/`ASSURED_WITHIN_SCOPE` trên stale hoặc unbound evidence.
- Dirty edit reproduction hiện tại phải chuyển từ `FRESH` sang `STALE` hoặc `UNVERIFIABLE`.
- Snapshot race tạo abstention, không tạo receipt mạnh.

## R2 — Shared Assurance Orchestrator

### Mục tiêu

Loại bỏ provider orchestration khỏi private CLI helpers và dùng chung cho CLI/MCP.

### Công việc

- [ ] Tạo package/service độc lập, ví dụ:

```text
src/sot_graph/assurance/
  orchestrator.py
  models.py
  routing.py
  identity.py
  normalization.py
  coverage.py
  verification.py
  conflicts.py
  receipts.py
```

- [ ] CLI chỉ parse args/render output.
- [ ] MCP gọi cùng service, không tái triển khai logic.
- [ ] Implement đúng `builtin/auto/prefer/require/all`.
- [ ] Route theo capability + language + assurance tier.
- [ ] Mọi provider failure trở thành typed outcome, không throw xuyên lớp.
- [ ] Giữ đường builtin tương thích ngược.

### Acceptance gate

- Cùng request/snapshot qua CLI và MCP cho cùng canonical evidence/receipt digest.
- `all` thực sự invoke mọi provider queryable.
- Provider thiếu không làm hỏng builtin trong `auto/prefer`.
- `require` fail closed với exit/error code ổn định.

## R3 — Hoàn thiện provider adapters

### R3.1 Codebase Memory

- [ ] Dùng structured format cho search/trace/impact/architecture khi contract hỗ trợ.
- [ ] `TraceRequest.max_depth -> depth`.
- [ ] Giữ root, source, target, direction, hop, strategy, confidence, cursor, total.
- [ ] Không map `USAGE/REFERENCE` thành `CALLS` nếu provider không chứng minh call.
- [ ] Propagate target/depth/staged/working-tree hoặc khai báo scope conflict.
- [ ] Parse pagination/truncation đầy đủ.
- [ ] Expose architecture qua orchestrator.
- [ ] `check_index_coverage` dùng args-file và explicit project.
- [ ] `sot providers sync codebase-memory` bọc explicit indexing, không bắt người dùng tự gọi CLI CBM.

### R3.2 SCIP

- [ ] Chuẩn hóa SCIP definitions/references thành cùng identity model.
- [ ] Bind index metadata vào source snapshot.
- [ ] Phân biệt definition/reference/call; không suy call từ reference đơn thuần.
- [ ] Invalidate artifact khi commit/manifest không khớp.

### R3.3 Builtin

- [ ] Gắn capability theo từng language/relation thay vì quảng bá chung.
- [ ] Sửa Go và TypeScript recall theo exact oracle.
- [ ] Giữ regex fallback ở heuristic ceiling.
- [ ] Nâng canonical qualified identity cho Rust/Go/TS methods.

### R3.4 Provider plugin contract

- [ ] Entry-point/plugin API versioned.
- [ ] Provider adapter có contract tests bắt buộc.
- [ ] Provider mới không cần sửa orchestrator core.
- [ ] Không tự động cài plugin trong read query.

### Acceptance gate

- Không production evidence parser nào phụ thuộc whitespace report nếu provider có structured model.
- Provider contract golden tests chạy từ clean clone.
- Schema drift, unknown version và partial payload đều abstain.
- Provider output giữ đủ identity/direction để exact oracle đánh giá.

## R4 — Canonical identity và search accuracy

### Mục tiêu

Tìm đúng symbol/node trước khi tính caller hoặc impact.

### Công việc

- [ ] Canonical identity gồm repo, normalized path, language, kind, qualified name, span và provider symbol ID khi có.
- [ ] Không deduplicate bằng short name.
- [ ] Alias/import/re-export resolution theo language.
- [ ] Scope-aware Python resolver tiếp tục là chuẩn tham chiếu.
- [ ] Bổ sung TS/JS module resolution, Go package/receiver, Rust module/impl, Java package/type.
- [ ] Rank kết quả theo exact identity, scope, path proximity, provider evidence và freshness.
- [ ] Query parser chống FTS injection và wildcard/path ambiguity.
- [ ] Top-k result luôn kèm reason/provenance.

### Minimum quality gate

- Gold target xuất hiện trong top-k: ≥90% trên mỗi Tier-A language corpus.
- Confirmed direct-call precision: ≥95%.
- Project-local direct-call recall: ≥80% trên mỗi Tier-A language, không chỉ aggregate.
- False verified edge rate: 0 trên frozen adversarial corpus.
- Provider union không làm giảm verified precision so với provider tốt nhất.

Threshold này là release floor, không phải tuyên bố global accuracy.

## R5 — Coverage, multilingual verification và completeness

### Mục tiêu

Chuyển “query đã chạy” thành bằng chứng về phần codebase thực sự được bao phủ.

### Công việc

- [ ] Coverage model theo path/range/language/relation.
- [ ] Phân biệt indexed, parsed, partial, skipped, excluded, stale, unknown.
- [ ] Propagate parser error ranges và ignored/generated/vendor paths.
- [ ] Source-span verifier dùng parser/provider thật cho Python, TS/JS, Go, Rust, Java và C/C++.
- [ ] Verify declaration span và call-site span riêng.
- [ ] Content hash + line/column encoding validation.
- [ ] Gap taxonomy:
  - dynamic dispatch;
  - reflection;
  - dependency injection;
  - framework routing;
  - macros/preprocessor;
  - function pointers;
  - generated code;
  - cross-repo/runtime dependency.
- [ ] Completeness engine xét coverage + capability + pagination + gaps, không chỉ số lượng kết quả.

### Acceptance gate

- Coverage API lỗi luôn downgrade completeness.
- Zero result không tạo negative claim khi coverage thiếu.
- Verifier non-Python không dùng Python-style regex để phát hành exact verdict.
- Mỗi receipt chỉ claim assurance cho language/relation đã đạt quality gate.

## R6 — Evidence ledger, union và conflict adjudication

### Mục tiêu

Mọi kết luận đều truy được về provider run, source anchor và snapshot.

### Công việc

- [ ] Truyền active database vào provider qua orchestrator.
- [ ] Persist provider run, binding và normalized evidence trên production CLI/MCP path.
- [ ] Lưu provider/version/capability/command digest/duration/status/snapshot.
- [ ] Commit run + evidence atomically sau parse/verification.
- [ ] Evidence union theo canonical identity + relation + target + snapshot.
- [ ] Giữ từng support/contradict provenance.
- [ ] Không trộn historic stale run vào active result.
- [ ] Conflict adjudication ưu tiên current source/compiler evidence; nếu chưa đủ thì giữ `CONFLICT`.
- [ ] Purge một run không xóa evidence độc lập của run khác.
- [ ] Ledger failure không corrupt builtin graph.

### Acceptance gate

- Một query CLI và một query MCP thật tạo ledger rows có snapshot.
- Có thể tái tạo receipt từ ledger mà không cần tin log console.
- Không có winner-takes-all merge âm thầm.
- Conflict chưa phân xử chặn assurance ở tier `audit`.

## R7 — Impact engine và assurance receipts

### Mục tiêu

Biến graph navigation thành workflow bảo chứng trước và sau thay đổi.

### R7.1 Scope receipt trước thay đổi

Receipt bắt buộc có:

- request identity và resolved target;
- snapshot ID/digest;
- source anchors;
- direct callers/callees;
- imports, implementations, inheritance;
- transitive impact theo bounded depth;
- affected files/modules;
- candidate tests;
- providers/runs/versions;
- coverage và exclusions;
- conflicts, truncation và known gaps;
- assurance status;
- OMP confirmations còn phải thực hiện.

### R7.2 Diff-impact receipt sau thay đổi

- diff identity: base/head/index/worktree scope;
- changed files/symbols;
- added/removed/changed edges;
- upstream/downstream affected nodes;
- invalidated pre-change evidence;
- tests cần chạy và test receipts đã nhận;
- reconcile result và post-change snapshot;
- remaining conflicts/gaps;
- closure decision.

### R7.3 Assurance rules theo rủi ro

| Thay đổi | Minimum tier |
|---|---|
| Local body, private helper | `verify` |
| Public signature/API/schema | `audit` |
| Rename/delete/move | `audit` |
| Auth/security/tenant/data isolation | `audit` + security reviewer |
| Dynamic/reflection-heavy code | Không cho absence assurance nếu chưa có runtime evidence |

### Acceptance gate

- Pre-change receipt không được dùng cho post-change snapshot.
- Public rename bị block nếu caller coverage chưa đủ.
- `0 callers` chỉ xuất hiện với bounded assured scope.
- Receipt JSON có schema version và deterministic digest.

## R8 — OMP integration và delivery contract

### Mục tiêu

SOT trở thành scope/evidence sensor bắt buộc trong OMP nhưng không thay thế test/reviewer.

### Workflow chuẩn

```text
scope receipt
  -> todo plan
  -> source/LSP confirmation
  -> edit
  -> targeted tests
  -> diff-impact receipt
  -> reconcile
  -> post-change receipt
  -> independent reviewer receipt
  -> close
```

### Công việc

- [ ] MCP inputs hỗ trợ `assurance`, `provider_policy`, `scope`, `budget`.
- [ ] OMP rule bắt buộc receipt trước sửa core/public symbol.
- [ ] Todo nodes tham chiếu receipt items và unresolved gaps.
- [ ] Reviewer đối chiếu diff với pre/post receipts.
- [ ] Stop-time rule không cho đóng nếu receipt yêu cầu test/confirmation còn pending.
- [ ] Xóa toàn bộ wording “100% verified/reliable/grounded” khỏi generated templates.
- [ ] Planner được quyền đọc source anchors và known gaps; không cấm kiểm chứng source.

### Acceptance gate

- OMP config chỉ cần SOT MCP; external providers là implementation detail tùy chọn.
- E2E fixture hoàn thành đủ workflow và receipts.
- Provider vắng mặt vẫn hoàn thành workflow ở capability builtin, nhưng assurance được hạ trung thực.
- Không receipt nào thay thế targeted test hoặc reviewer proof.

## R9 — Hardening, scale và release qualification

### Công việc

- [ ] Ruff hoặc tương đương.
- [ ] Type checker cho public/core modules.
- [ ] Coverage threshold tổng và riêng cho orchestrator/receipt/snapshot.
- [ ] Dependency and secret scan.
- [ ] Real-provider E2E job tối thiểu trên Linux cho provider được support chính thức.
- [ ] Cross-platform wheel/sdist/MCP/OMP smoke.
- [ ] Chaos tests: timeout, crash, partial write, corrupt DB, schema drift, huge output.
- [ ] Monorepo benchmarks: latency p50/p95, memory, index time, fallback time.
- [ ] Response hard budgets và deterministic truncation.
- [ ] Migration/rollback tests cho ledger schema.
- [ ] Release notes phải ghi capability matrix và known gaps.

### Final release gates

- Full CI xanh trên Python 3.10–3.12 × Linux/macOS/Windows.
- 100 clean lifecycle integrity runs.
- Context reduction ≥60% và task-answer accuracy không thấp hơn baseline protocol.
- Top-k target recall ≥90% trên từng Tier-A language.
- Confirmed direct-call precision ≥95% và recall ≥80% trên từng Tier-A language.
- False verified edge rate = 0 trên frozen adversarial corpus.
- Stale/unbound evidence reaching `SUPPORTED` = 0.
- Negative claim without complete bounded coverage = 0.
- Receipt schema compatibility tests xanh.
- Không agent-facing absolute completeness claim.

## 8. Provider lifecycle và upstream updates

### 8.1 Supported-provider manifest

Repo lưu manifest, ví dụ:

```text
provider
tested_versions
wire_contract_version
golden_digest
capabilities_verified
languages_verified
known_gaps
last_verified_at
```

### 8.2 Update process

1. Bot hoặc maintainer phát hiện upstream release.
2. Tạo PR cập nhật manifest, không auto-merge.
3. Capture golden outputs từ binary thật.
4. Chạy schema differential với version đang support.
5. Chạy exact accuracy oracle và performance regression.
6. Chạy security/license/artifact checksum verification.
7. Reviewer xác nhận capability changes và trust ceilings.
8. Chỉ thêm version vào tested set khi tất cả exit gate xanh.
9. Nếu regression: giữ pin cũ, ghi compatibility status `UNTESTED/INCOMPATIBLE`.

### 8.3 Update policy

- External provider có thể được người dùng nâng độc lập.
- SOT chỉ cấp assurance mạnh cho version đã contract-test.
- Version chưa test có thể dùng ở `scout`, nhưng verdict tối đa `UNVERIFIABLE` nếu wire/snapshot không được chứng minh.
- Không cần fork upstream để cập nhật adapter.
- Chỉ cân nhắc embedded/fork khi benchmark chứng minh subprocess/contract boundary không thể đạt latency hoặc semantic requirement, và phải có ADR riêng.

## 9. CI và test pyramid

### Unit

- Identity normalization.
- Relation mapping.
- Snapshot comparison.
- Coverage completeness.
- Trust ceilings.
- Conflict merge.
- Receipt digest/schema.

### Contract

- Golden provider captures.
- Schema drift.
- Version compatibility.
- Pagination/cursor.
- Path with spaces/Unicode/platform separators.
- Position encoding.

### Integration

- Fake executable failure matrix.
- Real provider binary fixture.
- Dirty/rename/delete lifecycle.
- SQLite atomicity/crash injection.
- CLI/MCP parity.

### Accuracy

- Exact tuple oracle.
- Negative/adversarial oracle.
- Metamorphic transforms.
- Differential comparison giữa builtin/SCIP/CBM/providers.
- Per-language and per-relation scorecards.

### End-to-end

- Builtin-only OMP flow.
- Optional provider available.
- Provider missing/unhealthy/stale.
- Multi-provider conflict.
- Public rename with full coverage.
- Dynamic case requiring abstention.
- Post-change reconcile and reviewer closure.

## 10. Thứ tự ưu tiên triển khai

Không chạy song song các phase có dependency semantic:

```text
R0 Accuracy oracle
  -> R1 Snapshot/trust blocker
    -> R2 Shared orchestrator
      -> R3 Provider adapters
        -> R4 Identity/search accuracy
          -> R5 Coverage/verification
            -> R6 Ledger/conflicts
              -> R7 Impact receipts
                -> R8 OMP workflow
                  -> R9 Release qualification
```

Có thể chạy song song trong cùng phase:

- Các language corpus độc lập.
- Provider golden capture độc lập.
- Documentation cleanup sau khi vocabulary đã freeze.
- Performance benchmark sau khi correctness test đã xanh.

## 11. Definition of Done cuối cùng

Hệ thống chỉ được gọi là **Impact-Assurance System** khi:

- [ ] SOT hoạt động đầy đủ ở builtin-only mode.
- [ ] Provider có thể thêm/thay/xóa mà không đổi public CLI/MCP contract.
- [ ] CLI và MCP dùng cùng assurance engine.
- [ ] Search target identity đạt quality floor theo từng Tier-A language.
- [ ] Caller/impact evaluator dùng exact tuple oracle.
- [ ] Dirty/stale/unbound không bao giờ được coi fresh/assured.
- [ ] Coverage là coverage thật theo scope, không phải query status.
- [ ] Source verification là language-aware cho capability được quảng bá.
- [ ] Production queries ghi provider runs và evidence theo snapshot.
- [ ] Conflict và gaps được giữ, không bị merge mất.
- [ ] Scope receipt và post-change impact receipt có deterministic digest.
- [ ] Negative claims chỉ xuất hiện trong bounded assured scope.
- [ ] OMP thực thi receipt -> plan -> edit -> test -> reconcile -> review.
- [ ] Provider vắng mặt/failure có fallback hoặc abstention trung thực.
- [ ] Tất cả accuracy, lifecycle, packaging và security gates xanh.
- [ ] Không còn claim tuyệt đối gây overtrust.

## 12. Stop conditions

Agent phải dừng phase và báo blocker nếu:

- Oracle không phân biệt được đúng/sai target.
- Không xác định được common snapshot hoặc diff identity.
- Provider không cung cấp đủ direction/source/target cho relation đang map.
- Coverage không chứng minh được scope của negative claim.
- Structured output và captured binary mâu thuẫn.
- Một fix chỉ làm metric xanh bằng cách hạ hoặc sửa oracle.
- Provider update làm giảm verified precision/recall dưới release floor.
- Một thay đổi đòi hỏi fork/vendor nhưng chưa có benchmark và ADR chứng minh.
- Receipt có thể đạt assured dù truncation/conflict/gap tồn tại.

`UNKNOWN` phải được giữ là `UNKNOWN`; assurance đến từ khả năng từ chối kết luận khi chưa đủ bằng chứng.

## 13. Milestone bàn giao

| Milestone | Deliverable |
|---|---|
| M1 | Exact accuracy oracle + fixed dirty snapshot |
| M2 | Shared CLI/MCP assurance orchestrator |
| M3 | Structured CBM + normalized SCIP/builtin providers |
| M4 | Canonical search đạt per-language quality floor |
| M5 | Real coverage + multilingual verification |
| M6 | Snapshot-scoped evidence ledger + conflict engine |
| M7 | Scope/diff/reconcile receipts |
| M8 | OMP E2E assurance workflow |
| M9 | Qualified impact-assurance release |

## 14. Kết luận định hướng

Con đường phù hợp nhất không phải làm SOT-Graph thành extractor lớn nhất. Giá trị bền vững của SOT là:

```text
provider candidates
  + current-source verification
  + snapshot and coverage proof
  + conflict-aware evidence union
  + pre/post-change receipts
  = bounded impact assurance
```

Codebase Memory là provider discovery mạnh và nên được hoàn thiện trước trong adapter hiện có, nhưng không trở thành dependency bắt buộc. Điều này giữ SOT nhẹ, local-first, dễ cập nhật và có thể tận dụng provider tốt nhất theo từng ngôn ngữ—đồng thời assurance semantics vẫn do một mình SOT kiểm soát.

