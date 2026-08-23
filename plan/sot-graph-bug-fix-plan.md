# Kế hoạch định hướng fix bug và hardening SOT-Graph

**Căn cứ:** tái đánh giá commit 10e2953acfdaf329d72b467bd6e6ac746b88b04c  
**Ngày lập:** 2026-08-24  
**Mục tiêu phát hành đề xuất:** 0.2.0-rc1, sau hardening mới nâng thành 0.2.0 stable  
**Thời lượng ước tính:** 10–14 ngày kỹ sư với một maintainer; 6–8 ngày làm việc với hai maintainer  
**Tài liệu đi kèm:** sot-graph-reassessment-report.md

## 1. Mục tiêu

Đợt hardening này không ưu tiên thêm tính năng mới. Mục tiêu là khóa các invariant để SOT-Graph trở thành một “la bàn có bằng chứng” đáng tin:

1. Không gọi dữ liệu stale là FRESH.
2. Không gọi lexical proximity là EXACT_SPAN.
3. Không biến import alias thành local call.
4. Mỗi physical call site chỉ thuộc một lexical scope.
5. Không gọi index COMPLETE khi chỉ biết rằng không còn pending record.
6. Benchmark phải có khả năng bắt false positive và false negative thực.
7. Pack hoặc tuân thủ token cap, hoặc trả lỗi rõ ràng.
8. Search/verify mặc định là pure read; repair là thao tác riêng.
9. Nội dung trong repository mặc định là untrusted.
10. Tài liệu, version và release metadata phải phản ánh đúng semantics.

## 2. Nguyên tắc triển khai

### 2.1 Không sửa bằng cách hạ confidence tùy ý

Lỗi semantic cần được sửa ở nguồn dữ liệu hoặc trạng thái evidence. Không dùng một hệ số “phạt” để che false edge hoặc stale symbol.

### 2.2 Exact và inferred phải tách biệt

Mỗi edge nên có:

- nguồn evidence;
- resolver/parser version;
- mức resolution;
- lý do resolve;
- vị trí physical call site;
- trạng thái có thể tái kiểm chứng.

### 2.3 Unknown tốt hơn confident-but-wrong

Khi không đủ dữ liệu, trả UNKNOWN, UNRESOLVED hoặc NOT_APPLICABLE. Đối với coding agent, một cảnh báo minh bạch ít nguy hiểm hơn confidence 1.0 sai.

### 2.4 Đường đọc không được tự sửa index

Search, verify, usages và explore phải deterministic theo snapshot đang mở. Reconcile, repair và rehome là command riêng, có audit output.

### 2.5 Mỗi bug phải có fixture tối thiểu

Trước khi sửa, thêm regression test tái hiện bug và xác nhận test fail trên commit hiện tại. Sau đó mới sửa implementation.

## 3. Thứ tự ưu tiên

| ID | Hạng mục | Mức | Rủi ro nếu chưa sửa | Effort |
|---|---|---|---|---:|
| SOT-P0-01 | Hash-based freshness và evidence semantics | P0 | Agent tin symbol stale | 1.5–2 ngày |
| SOT-P0-02 | Import alias/local collision | P0 | False call edge, sai impact analysis | 1.5–2 ngày |
| SOT-P0-03 | Nested-scope call ownership | P0 | Duplicate usages, graph méo | 0.5–1 ngày |
| SOT-P0-04 | Completeness semantics | P0 | Overclaim độ phủ | 0.5–1 ngày |
| SOT-P0-05 | Accuracy benchmark v2 | P0 | Không đo được chất lượng thật | 2–3 ngày |
| SOT-P0-06 | CI, version và docs truth | P0 release gate | Regression lọt vào release | 1–1.5 ngày |
| SOT-P1-01 | Hard token budget | P1 | Vỡ context budget | 1 ngày |
| SOT-P1-02 | Content-hash rehome | P1 | Sai/mất liên kết khi move | 1–1.5 ngày |
| SOT-P1-03 | Trust boundary của repo content | P1 security | Prompt injection | 0.5–1 ngày |
| SOT-P1-04 | Resolver provenance/versioning | P1 | Edge cũ sống sau khi logic đổi | 1 ngày |
| SOT-P1-05 | Adaptive parallel reconcile | P1 | Chậm với workload nhỏ | 0.5 ngày |

## 4. P0 — Chi tiết triển khai

## SOT-P0-01 — Hash-based freshness và evidence semantics

### Hiện trạng

src/sot_graph/verifier.py:verify_evidence tính hash file hiện tại nhưng không so với hash lưu trong file_journal. calculate_coverage lại tìm query token trong file hoặc vùng dòng rộng, nên symbol đã bị xóa vẫn có thể được báo FRESH, EXACT_SPAN và confidence 1.0.

### Invariant cần đạt

    FRESH ⇔ current_file_sha256 == indexed_file_sha256

Không có journal hash hoặc không đọc được file thì freshness không được là FRESH.

EXACT_SPAN chỉ đúng khi query/symbol được xác nhận trong span AST của candidate hiện tại, không phải vì token xuất hiện trong comment hoặc vài dòng lân cận.

### File dự kiến sửa

- src/sot_graph/verifier.py
- src/sot_graph/evidence.py
- src/sot_graph/db.py
- src/sot_graph/mcp_service.py
- tests/test_trust_v2_evidence.py
- tests/test_verifier.py
- tests/test_adversarial_edge_cases.py

### Thiết kế đề xuất

#### Bước 1 — Lấy snapshot metadata

Thêm API database trả journal record theo normalized relative path:

    journal = db.get_file_journal(normalized_path)
    indexed_sha = journal.sha256 if journal else None
    current_sha = sha256(current_bytes)

Không lấy journal bằng basename. Path phải được normalize và xác nhận nằm trong project root.

#### Bước 2 — Tính freshness trước relevance

Ma trận:

| Điều kiện | Freshness |
|---|---|
| File không tồn tại | MISSING |
| File không đọc được/quá giới hạn | UNKNOWN |
| Không có journal hash | UNKNOWN |
| current_sha khác indexed_sha | STALE |
| current_sha bằng indexed_sha | FRESH |

Nếu STALE, không được tái sử dụng line_start/line_end cũ để tuyên bố EXACT_SPAN.

#### Bước 3 — Xác nhận span

Khi FRESH:

1. Lấy line_start/line_end của candidate.
2. Parse file bằng parser tương ứng nếu có.
3. Xác nhận declaration identity hoặc symbol token trong chính span.
4. Loại comment/string khỏi lexical evidence khi parser cung cấp token type.

Fallback khi parser không hỗ trợ:

- WITHIN_RECORDED_SPAN hoặc FILE_TOKEN, không dùng EXACT_SPAN;
- confidence bị giới hạn;
- ghi rõ evidence source = lexical_fallback.

#### Bước 4 — Tách các dimension không áp dụng

Thêm NOT_APPLICABLE vào ResolutionStatus và CompletenessStatus nếu API compatibility cho phép.

- Search hit: resolution thường NOT_APPLICABLE.
- Usages result: completeness có ý nghĩa.
- Edge verification: resolution có ý nghĩa.

Không dùng EXACT cho search relevance chỉ vì query trùng tên symbol.

#### Bước 5 — Pure-read default

Đổi TrustVerifier.verify_hit mặc định auto_heal = false. Nếu caller muốn sửa:

    sot repair --path ...
    sot reconcile ...

MCP nên trả suggested_action thay vì tự mutate.

### Regression tests bắt buộc

1. Index alpha, sửa thành beta không reconcile → alpha phải STALE.
2. Index alpha, thay bằng comment chứa alpha + beta → không được EXACT_SPAN/STRONG.
3. File hash giống journal, declaration còn nguyên → FRESH.
4. File mất → MISSING.
5. Journal thiếu → UNKNOWN.
6. File unreadable/oversize → UNKNOWN, không crash.
7. Query token chỉ nằm trong comment → không EXACT_SPAN.
8. verify_hit mặc định không đổi database.

### Tiêu chí nghiệm thu

- 0 false FRESH trong toàn bộ stale-file matrix.
- 0 STRONG cho symbol đã bị xóa trong fixture.
- Confidence không vượt ngưỡng exact khi chỉ có lexical fallback.
- API trả explanation chứa indexed_sha/current_sha mismatch ở dạng rút gọn, không lộ nội dung file.
- Tất cả test cũ và test mới pass.

## SOT-P0-02 — Import alias/local collision resolver

### Hiện trạng

Trong Python extractor, import alias target_main được chuẩn hóa về main. Nếu module caller cũng có hàm main, local resolution bắt nhầm và phát confirmed self-loop trước khi cross-file resolver có cơ hội xử lý.

### Invariant cần đạt

Một identifier được bind bởi import chỉ được resolve local khi import source chính là current module và điều đó được chứng minh. Mọi import-bound call còn lại phải:

- resolve tới imported module/symbol; hoặc
- ở trạng thái pending với binding metadata;
- tuyệt đối không fallback sang symbol local trùng bare name.

### File dự kiến sửa

- src/sot_graph/_vendor/graphify/extract.py
- src/sot_graph/extractor.py
- src/sot_graph/reconciler.py
- src/sot_graph/db.py nếu cần schema/provenance
- tests/test_import_resolution.py
- tests/test_python_semantic_resolver.py
- tests/test_adversarial_edge_cases.py

### Mô hình binding đề xuất

Mỗi reference nên mang:

| Trường | Ví dụ |
|---|---|
| call_name | target_main |
| binding_kind | imported_symbol |
| imported_module | z_target |
| imported_symbol | main |
| alias_name | target_main |
| source_scope_id | a_caller.main |
| line/column | physical call site |

### Thuật toán

1. Xây symbol table theo lexical scope.
2. Ưu tiên binding theo Python name-resolution rules.
3. Nếu binding_kind = imported_symbol, bỏ qua local-by-bare-name heuristic.
4. Phát pending edge kèm module + symbol nếu target file chưa có trong batch.
5. Cross-file resolver match module path trước, symbol sau.
6. Chỉ phát inferred edge khi ambiguity = 1.
7. Nếu nhiều target, giữ pending AMBIGUOUS; không chọn theo thứ tự file.

### Regression tests bắt buộc

Fixture chính:

    # a_caller.py
    def main():
        from z_target import main as target_main
        return target_main()

    # z_target.py
    def main():
        return 42

Assertions:

- Không có a_caller.main → a_caller.main.
- Có a_caller.main → z_target.main sau reconcile.
- Physical location trỏ đúng dòng target_main().
- Không còn pending tương ứng nếu module được index.

Thêm cases:

1. import z_target as z; z.main().
2. from z_target import main; local function cũng tên main.
3. Alias bị shadow bởi local assignment sau import.
4. Relative import.
5. Circular import.
6. Hai module có cùng basename.
7. Explicit recursion main() vẫn tạo self-loop hợp lệ và được đánh dấu recursion = true.
8. Regression thực cho src/sot_graph/cli.py call mcp_main.

### Tiêu chí nghiệm thu

- 0 false self-loop trong corpus, trừ explicit recursion.
- Alias fixture resolve đúng 100%.
- Resolver không phụ thuộc lexical file order.
- Edge output có provenance và binding reason.

## SOT-P0-03 — Nested-scope call ownership

### Hiện trạng

src/sot_graph/_vendor/graphify/extract.py:_handle_func dùng ast.walk, đi vào FunctionDef/AsyncFunctionDef/Lambda/ClassDef lồng bên trong. generic_visit sau đó lại xử lý nested scope, gây double attribution.

### Invariant cần đạt

Mỗi call expression thuộc scope gần nhất chứa nó. Một physical call site chỉ sinh một call edge cho một caller scope, ngoại trừ khi có mô hình edge khác được ghi rõ.

### Thiết kế

Thay ast.walk bằng ScopeLocalVisitor:

- thăm thân function hiện tại;
- thu call/local type trong scope;
- không descend vào nested FunctionDef;
- không descend vào AsyncFunctionDef;
- không descend vào Lambda;
- không descend vào ClassDef;
- nested scope được xử lý bằng visitor chính ở lượt riêng.

Tạo call_site_key ổn định:

    normalized_path : line : column : end_line : end_column

Thêm invariant trong batch:

    unique(call_site_key, edge_kind, caller_scope)

### Regression tests

1. Outer function chứa inner function gọi target → chỉ inner sở hữu call.
2. Lambda gọi target → call thuộc lambda scope nếu lambda được model; nếu không, phải có policy rõ.
3. Method chứa local class/method → không gắn call của local method cho outer method.
4. Async nested function.
5. Case thực McpService.search/op: số physical call site bằng số usages site sau dedupe.

### Tiêu chí nghiệm thu

- Không còn duplicate attribution trong fixture và self-index.
- Số call-site duy nhất có thể audit từ output.
- Không làm giảm resolved calls ngoài các duplicate bị loại.

## SOT-P0-04 — Completeness semantics

### Hiện trạng

Database.usages trả COMPLETE khi không có pending edge exact/bare-name match. Đây chỉ là “không có gap đã biết”.

### Thay đổi API đề xuất

Ưu tiên enum:

- COMPLETE_WITHIN_INDEX_CAPABILITY
- KNOWN_GAPS
- UNKNOWN
- NOT_APPLICABLE

Nếu cần giữ backward compatibility:

- giữ field completeness;
- thêm completeness_scope;
- thêm legacy_mapping;
- phát deprecation warning cho COMPLETE.

Response usages nên có:

    completeness:
      status: COMPLETE_WITHIN_INDEX_CAPABILITY
      eligible_languages: [...]
      parser_tiers: {...}
      known_pending: 0
      unsupported_constructs: [...]
      dynamic_dispatch_modeled: false
      explanation: "No known pending references matched this symbol."

### Regression tests

1. Không pending nhưng có dynamic getattr → không được claim globally complete.
2. Unsupported file language → UNKNOWN hoặc scope bị giới hạn.
3. Có pending exact name → KNOWN_GAPS.
4. Có pending ambiguous receiver → KNOWN_GAPS.
5. Search hit → completeness NOT_APPLICABLE.

### Tiêu chí nghiệm thu

- Không còn chuỗi mô tả “all usages” nếu capability không chứng minh.
- CLI/MCP hiển thị phạm vi completeness.
- Docs giải thích rõ confirmed, pending và invisible-to-extractor.

## SOT-P0-05 — Accuracy benchmark v2

### Mục tiêu

Đo riêng:

- symbol definition accuracy;
- call-edge precision;
- call-edge recall trên eligible syntax;
- import resolution;
- duplicate physical call sites;
- false self-loops;
- exact vs inferred edge;
- unsupported/unknown rate.

### Cấu trúc corpus

Tạo thư mục benchmarks/corpus với manifest versioned:

    corpus/
      manifest.json
      python/
      typescript/
      java/
      expected_edges.jsonl
      expected_non_edges.jsonl

Mỗi ground-truth record có:

- repository/case ID;
- language;
- source path + span;
- caller stable identity;
- callee stable identity;
- edge kind;
- eligible true/false;
- expected resolution tier;
- rationale;
- reviewer.

### Quy mô tối thiểu cho rc1

- 100–300 positive edges;
- ít nhất 100 negative/non-edge cases;
- Python là deep corpus;
- mỗi ngôn ngữ còn lại có smoke corpus;
- ít nhất 3 repo thực nhỏ hoặc snapshot được cấp phép;
- cases bắt buộc: alias collision, nested scope, shadowing, wildcard import, method receiver ambiguity, explicit recursion, duplicate basename.

### Ground truth

Ưu tiên theo thứ tự:

1. Compiler/LSP/SCIP occurrence.
2. Human-reviewed manifest.
3. Synthetic generator chỉ dùng cho deterministic edge cases.

Không để cùng một generator vừa tạo source vừa tự định nghĩa toàn bộ expected result mà không có negative/adversarial cases.

### Sửa CLI benchmark

--corpus-dir phải chỉ đọc corpus có manifest. Không ghi đè. Nếu muốn tạo fixture, dùng command riêng:

    python scripts/generate_accuracy_fixtures.py --output ...
    python scripts/benchmark_accuracy.py --corpus-dir ...

### Báo cáo bắt buộc

| Metric | Phải tách theo |
|---|---|
| Precision/recall/F1 | language, edge kind, exact/inferred |
| Unknown rate | language/parser tier |
| False self-loop | recursion/non-recursion |
| Duplicate rate | physical call site |
| Corpus size | positive, negative, eligible |

### Release gate ban đầu

- Precision trên eligible call edges ≥ 95%.
- Recall trên eligible call edges ≥ 80%.
- False non-recursive self-loop = 0.
- Duplicate physical call-site rate = 0.
- Không được in 100% nếu corpus size dưới ngưỡng; report luôn hiển thị N.

## SOT-P0-06 — CI, version và docs truth

### Workflow CI tối thiểu

Tạo .github/workflows/ci.yml:

- Python matrix theo versions hỗ trợ;
- lint/format/type check nếu dự án đã chọn tool;
- pytest;
- coverage gate;
- database integrity test;
- accuracy benchmark smoke;
- package build;
- install wheel vào venv sạch;
- chạy sot --help và doctor smoke.

Nightly hoặc scheduled:

- real corpus accuracy;
- process crash/storage fault tests;
- reconcile performance;
- pack budget suite.

### Version/release

1. Chọn rõ 0.2.0-rc1 hoặc quay commit message về 0.1.x.
2. Đồng bộ pyproject.toml và src/sot_graph/__init__.py.
3. Thêm CHANGELOG.
4. Tag signed hoặc annotated.
5. Build sdist/wheel từ clean checkout.

### Docs cần sửa

- README.md
- AGENTS.md
- WORKFLOW_GUIDELINES.md
- MCP tool descriptions
- release notes

Thay mọi claim “100% reliable”, “physically verified” không điều kiện bằng semantics cụ thể:

- hash snapshot đã khớp hay chưa;
- span được parser hay lexical fallback xác nhận;
- graph complete trong capability nào;
- bước kiểm chứng tiếp theo.

### Gate

- rg không còn claim tuyệt đối ngoài phần mô tả test fixture.
- Tài liệu có trust matrix và safe-agent workflow.
- Version thống nhất ở mọi entry point.
- Pull request không merge nếu pytest/accuracy/package gate fail.

## 5. P1 — Chi tiết triển khai

## SOT-P1-01 — Hard token budget

### Invariant

    rendered_token_count <= max_tokens

Nếu framing tối thiểu lớn hơn max_tokens, trả lỗi BUDGET_TOO_SMALL với minimum_required_tokens; không trả bundle vượt cap.

### Thực hiện

1. Tính minimum viable framing.
2. Reserve header/footer trước khi chọn evidence.
3. Cắt optional sections theo priority.
4. Render lần cuối và tokenize lại.
5. Nếu vượt, loại section tiếp theo; nếu không thể, fail rõ.
6. Cho phép adapter tokenizer chính xác theo model.
7. Không claim fallback sai số ≤5% nếu chưa benchmark.

### Tests

Budget 64, 100, 250, 500, 1,000, 2,000; Unicode; long path; empty result; native/fallback tokenizer.

## SOT-P1-02 — Content-hash rehome

### Invariant

Move/rename không đổi nội dung phải giữ identity theo content/symbol, và cập nhật file nodes, edges, journal trong một transaction.

### Thiết kế

1. Khi old path missing, lấy indexed sha256.
2. Tìm candidate mới bằng content hash trong changed-file set trước.
3. Nếu một candidate → rehome.
4. Nếu nhiều candidate → AMBIGUOUS, không tự chọn.
5. Nếu hash khác → reconcile như edit/delete+add.
6. Test bằng production-style IDs, không chỉ path IDs.

### Tests

- move cùng basename;
- move kèm rename;
- hai file cùng content;
- move trong lúc có reader;
- crash trước/sau commit;
- rollback giữ DB consistent.

## SOT-P1-03 — Trust boundary của repository content

### Policy

- Source code, comments, README, AGENTS.md trong repo: untrusted mặc định.
- Host instructions ngoài repo: có thể trusted.
- Caller phải truyền trust policy tường minh nếu muốn promote repo file.
- Pack đánh dấu origin, path và trust state cho từng section.

### Tests

AGENTS.md chứa instruction cố điều khiển agent → content vẫn có content_is_untrusted = true; chỉ explicit host policy mới thay đổi.

## SOT-P1-04 — Resolver provenance và invalidation

Thêm:

- extractor_version;
- resolver_version;
- schema_version;
- resolution_reason;
- source_evidence;
- inferred_at.

Khi resolver semantics đổi:

- confirmed inferred edges cũ phải được re-resolve hoặc invalidated;
- exact imported SCIP/LSP edges có lifecycle riêng;
- doctor báo số edge stale-by-resolver-version.

## SOT-P1-05 — Adaptive parallel reconcile

Với file nhỏ, 4 worker hiện chậm hơn 1 worker. Đề xuất:

- single process dưới ngưỡng số file/tổng byte;
- worker pool chỉ khi workload đủ lớn;
- batch nhiều file nhỏ trong một task;
- benchmark cold/warm process riêng;
- doctor/verbose output nêu strategy đã chọn.

## 6. Trình tự sprint

## Sprint 1 — Trust correctness, 2–3 ngày

Phạm vi:

- SOT-P0-01;
- regression stale/comment/exact-span;
- pure-read default;
- terminology draft cho completeness.

Exit criteria:

- stale symbol không thể STRONG;
- hash matrix pass;
- test suite xanh.

## Sprint 2 — Resolver correctness, 3–5 ngày

Phạm vi:

- SOT-P0-02;
- SOT-P0-03;
- provenance tối thiểu;
- rebuild/re-index migration.

Exit criteria:

- alias fixture đúng;
- 0 false self-loop ngoài recursion;
- 0 duplicate physical call site;
- self-index không còn cli.main false loop.

## Sprint 3 — Measurement và epistemics, 2–3 ngày

Phạm vi:

- SOT-P0-04;
- SOT-P0-05;
- real/adversarial corpus;
- accuracy report theo tier.

Exit criteria:

- benchmark có positive + negative;
- corpus size hiện rõ;
- threshold CI hoạt động;
- COMPLETE được thay bằng scoped semantics.

## Sprint 4 — Product hardening/release, 2–3 ngày

Phạm vi:

- SOT-P0-06;
- SOT-P1-01;
- SOT-P1-02;
- SOT-P1-03;
- adaptive workers nếu còn capacity.

Exit criteria:

- hard budget;
- trust policy;
- CI/package/version/docs đồng bộ;
- rc1 phát hành từ clean checkout.

## 7. Test plan tổng

### Unit

- hash comparison;
- span verifier;
- import binding;
- nested scope visitor;
- completeness state machine;
- token budget allocator;
- content-hash candidate selection.

### Integration

- reconcile → verify → edit without reconcile;
- reconcile multi-file alias → usages;
- move file → rehome → query;
- MCP search/verify không mutation;
- pack trên untrusted AGENTS.md;
- schema/resolver-version migration.

### Storage/fault

- multi-process readers/writer;
- kill process giữa staging và commit;
- reopen + PRAGMA quick_check;
- 100–1,000 incremental cycles;
- disk-full/read-only simulation nếu CI hỗ trợ.

### Accuracy

- synthetic adversarial;
- small real repos;
- LSP/SCIP comparison;
- negative edges;
- dedupe/self-loop checks.

### Performance

- 10/100/1,000/10,000 files;
- file size buckets;
- 1/2/4 workers;
- cold/warm cache;
- query p50/p95/p99;
- pack token/time.

## 8. Commands kiểm chứng đề xuất

Chạy nhanh trước commit:

    pytest -q
    pytest -q tests/test_trust_v2_evidence.py tests/test_import_resolution.py

Chạy gate:

    pytest --cov=src/sot_graph --cov-report=term-missing
    python scripts/benchmark_accuracy.py --corpus-dir benchmarks/corpus
    python scripts/benchmark_context.py
    python benchmarks/bench_query.py

Package smoke:

    python -m build
    python -m venv /tmp/sot-graph-wheel-test
    /tmp/sot-graph-wheel-test/bin/pip install dist/*.whl
    /tmp/sot-graph-wheel-test/bin/sot --help

Database:

    sot doctor
    sqlite3 .sot/sot.db "PRAGMA quick_check;"

## 9. Definition of Done cho 0.2.0 stable

- [ ] 239 test hiện tại vẫn pass.
- [ ] Có regression test cho mọi P0 trong tài liệu này.
- [ ] Freshness dựa trên journal hash.
- [ ] Stale symbol không thể nhận STRONG/confidence 1.0.
- [ ] EXACT_SPAN không dựa trên comment/window proximity.
- [ ] Alias import không fallback vào local bare-name.
- [ ] Không có false non-recursive self-loop trong corpus.
- [ ] Mỗi physical call site chỉ có một owner scope.
- [ ] Completeness luôn có scope/capability.
- [ ] Accuracy corpus có ít nhất 100 positive và 100 negative cases.
- [ ] Precision eligible calls ≥95%, recall ≥80%.
- [ ] Pack không vượt hard token cap; budget quá nhỏ trả lỗi rõ.
- [ ] Search/verify mặc định không mutate.
- [ ] Rehome dựa trên content hash và transaction thật.
- [ ] Repo content mặc định untrusted.
- [ ] CI chạy test, coverage, accuracy smoke và package smoke.
- [ ] pyproject, __init__, tag và changelog cùng version.
- [ ] Docs không còn claim “100% reliable”.
- [ ] Clean checkout có thể build/install/run doctor.

## 10. Những việc chưa nên làm trước khi đóng P0

- Mở rộng thêm nhiều language adapter.
- Tự động rename/refactor cross-file.
- Thêm graph visualization lớn.
- Tối ưu ranking bằng heuristic mới.
- Bật auto-heal mặc định.
- Quảng bá SOT-Graph như semantic source of truth.

Các hạng mục này làm tăng bề mặt hệ thống nhưng không giải quyết rủi ro cốt lõi. Sau khi P0 đóng, ưu tiên chiến lược nên là **nhận SCIP/LSP làm evidence source cấp EXACT** và để SOT-Graph tập trung vào orchestration, provenance, context packing và agent guidance.

## 11. Issue template dùng để triển khai

Mỗi issue nên có cấu trúc:

    Title:
    Risk:
    Current counterexample:
    Expected invariant:
    Files likely affected:
    Failing regression test:
    Proposed implementation:
    Compatibility/migration:
    Observability:
    Acceptance criteria:
    Benchmark impact:
    Documentation changes:

Quy tắc merge:

1. Regression test phải fail trước fix.
2. PR mô tả invariant, không chỉ mô tả code change.
3. Nếu thay semantics, cập nhật MCP schema/docs cùng PR.
4. Nếu thay resolver, xác định cách invalidation/reindex.
5. Không merge nếu chỉ giảm confidence nhưng false edge vẫn tồn tại.
