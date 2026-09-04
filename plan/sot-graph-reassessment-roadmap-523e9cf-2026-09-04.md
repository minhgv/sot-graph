# Tái đánh giá toàn diện SOT Graph và roadmap trở thành “bản đồ lập trình” đáng tin cậy

**Repository:** [minhgv/sot-graph](https://github.com/minhgv/sot-graph)  
**HEAD được đánh giá:** [523e9cf7bf943a865a123cdc49af1446d73c027b](https://github.com/minhgv/sot-graph/commit/523e9cf7bf943a865a123cdc49af1446d73c027b)  
**So sánh với baseline trước:** [2666c5832649644897d9e03b89e431c35f70b80d](https://github.com/minhgv/sot-graph/commit/2666c5832649644897d9e03b89e431c35f70b80d)  
**Thời điểm chốt:** 2026-09-04 UTC / ICT  
**Phạm vi:** source, graph/index, assurance, CLI/MCP, provider, benchmark, CI/release, repo map, context pack, trải nghiệm AI và người vận hành

---

## 1. Kết luận điều hành

### Verdict mới

> **SOT Graph đã chuyển từ prototype khó phát hành thành một beta cài đặt và vận hành được, nhưng chưa trở thành cổng bảo chứng an toàn.**

Khuyến nghị sử dụng hiện tại:

- **GO_BETA_DISTRIBUTION:** package 0.3.1 đã có trên PyPI; release pipeline, matrix đa hệ điều hành và branch protection hoạt động.
- **GO_ADVISORY:** tìm symbol, kiểm tra anchor, khám phá caller/callee, tạo repo map ban đầu, đóng gói context và gợi ý blast radius.
- **CONDITIONAL_GO_HUMAN_GATED:** refactor cục bộ khi người vận hành đọc source, compiler/LSP, test và diff thật.
- **NO_GO_AUTONOMOUS_ASSURANCE:** chưa dùng SOT Graph một mình để kết luận “không có caller”, rename/delete tự động, chọn test tối thiểu, chặn/cho merge hoặc tuyên bố production-qualified.
- **NO_GO_PR_IMPACT_GATE:** GitHub diff-impact workflow hiện phân tích sai revision khi chạy trên pull request.

Điểm tổng hợp tăng từ **5,8/10 lên 6,4/10**. Phần tăng chủ yếu đến từ release/CI, portability, hiệu năng và regression benchmark. Điểm assurance gần như chưa tăng vì các bất biến quyết định an toàn vẫn hở trên đường MCP, diff bot, scope coverage và evaluator gate.

### Ba kết luận quan trọng nhất

1. **Tiến bộ là thật, không chỉ là tài liệu.** v0.3.1 được publish bằng OIDC, tag release xanh, main có 23 required checks, toàn bộ 15 tổ hợp OS/Python xanh, local test và quality gate xanh.
2. **Tuyên bố “R1–R5 complete” chưa đúng về mặt outcome.** R1 gần hoàn tất; R2 tốt; R3 là bước đầu; R4 có blocker phân tích sai PR; R5 chỉ làm rõ cap 200 file nhưng transport truncation và cap khác vẫn có thể giữ verdict cao.
3. **Khoảng cách lớn nhất không còn là thiếu feature, mà là thiếu một claim pipeline duy nhất.** Mọi bề mặt phải cùng trả lời: claim gì, trên snapshot nào, universe nào đã duyệt, phần nào bị cắt, phần nào chưa biết và quyết định nào được phép.

---

## 2. Quy ước bằng chứng

Repo yêu cầu kiến trúc phải được tổng hợp từ năm fact bundle. Báo cáo này tuân thủ bằng cách tách nguồn:

| Nhãn | Ý nghĩa |
|---|---|
| **BUNDLE** | Fact trực tiếp từ năm file do sot bundle sinh tại HEAD mới |
| **OUTSIDE-BUNDLE / INFERENCE — CODE** | Ngoài bundle theo protocol của repo, nhưng được xác minh bằng đọc source tại commit cố định |
| **OUTSIDE-BUNDLE / INFERENCE — RUN** | Ngoài bundle, được xác minh bằng thực nghiệm local tái lập |
| **OUTSIDE-BUNDLE / INFERENCE — REMOTE** | Ngoài bundle, được xác minh bằng GitHub/PyPI API công khai |
| **INFERENCE** | Đánh giá, tác động hoặc khuyến nghị suy ra từ các fact trên |

Các nguồn bundle đã đọc đầy đủ:

1. .sot/bundle/01_module_inventory.md
2. .sot/bundle/02_routing_endpoints.md
3. .sot/bundle/03_workflows_states.md
4. .sot/bundle/04_dependencies_violations.md
5. .sot/bundle/05_system_metrics.json
6. Template đi kèm: src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md

Không có source file nào của repo được thay đổi để đưa ra kết luận này.

---

## 3. Delta kể từ đánh giá trước

Từ 2666c583 đến 523e9cf có **10 commit, 50 file thay đổi, +6.956/-290 dòng**.

| Nhóm thay đổi | Kết quả thực | Trạng thái |
|---|---|---|
| Release v0.3.1, PyPI trusted publishing | Tag run publish thành công; wheel và sdist tồn tại trên PyPI | **Đã đóng phần chính** |
| CI portability | Linux/macOS/Windows × Python 3.10–3.14 đều xanh | **Đã đóng phần chính** |
| Branch protection | 23 required contexts cho non-admin | **Đã đóng phần chính** |
| CI watchdog | Kiểm tra main mỗi 6 giờ, mở/đóng issue khi đỏ/xanh | **Có giá trị, chưa thay gate** |
| Hiệu năng | BFS theo batch, watcher janitor theo batch, rehome cache, vector incremental, retention ledger | **Tiến bộ rõ** |
| Search benchmark | 48 probe, bốn lớp query, Hit@k/MRR, có threshold | **Đã có regression gate synthetic** |
| Diff-impact oracle | Sáu scenario, P/R/F1, bắt được và sửa bug delete-file | **Đã có regression gate synthetic** |
| GitHub diff bot | Có renderer/action/workflow | **Blocker: target semantics sai** |
| MCP prompts | Có deep-dive và refactor checklist | **Hữu ích nhưng phụ thuộc receipt chưa sound** |
| Provider cross-check | Có CLI agreements/builtin-only/external-only | **Prototype; identity join chưa canonical** |
| Honest receipt cap | Cap 200 changed files có total/truncated/warning | **Đóng một phần R5** |

---

## 4. Snapshot hiện trạng

### Repository và package

| Hạng mục | Kết quả |
|---|---:|
| Tổng commit | 135 |
| Tracked files | 287 |
| Python source | 69 file, 33.567 dòng |
| Python tests | 106 file, 25.130 dòng |
| Maintainer | 1 người, hai git identity |
| Package classifier | Beta |
| Main HEAD | 523e9cf |
| Release mới nhất | v0.3.1, tag tại 2cc3f50 |
| PyPI | sot-graph 0.3.1, Python ≥ 3.10 |
| GitHub | 1 star, 0 fork, 0 open issue tại thời điểm chốt |

### Local verification

| Kiểm tra | Kết quả |
|---|---|
| uv sync --all-extras --dev | Pass |
| pytest tests/ -q --strict-markers | **1011 passed, 3 skipped**, 1014 collected |
| Skip | Bun-dependent adapter test + 2 win32-only tests |
| quality_gates.sh | Pass |
| Coverage gate | Core 86%, receipts 91% |
| Ruff / Pyright | Pass / 0 errors |
| Bandit / pip-audit | Pass / không thấy CVE đã biết |
| module_eval --strict-probes | 6 scope pass, 0 bug, 0 probe error |
| sot verify --deep | Zero drift |
| sot doctor | DB healthy, schema 8 |

### Self-index sau reconcile

**BUNDLE**

| Metric | Giá trị |
|---|---:|
| Files | 273 |
| Nodes | 3.921 |
| Symbols | 3.648 |
| Edges | 9.854 |
| Communities | 117 |
| Modularity Q | 0,7882 |
| Functional modules | 38 |
| Routes được nhận dạng | 11 |

**OUTSIDE-BUNDLE / INFERENCE — RUN**

Doctor ghi nhận thêm:

- 5.932 pending edges;
- 257 ambiguous;
- 5.675 unresolved;
- 0 orphaned nodes;
- file và node trên disk không drift.

Điều này cho thấy freshness tốt không đồng nghĩa relation coverage hoàn chỉnh.

### CI và release công khai

**OUTSIDE-BUNDLE / INFERENCE — REMOTE**

- [Main CI run 33826064445](https://github.com/minhgv/sot-graph/actions/runs/33826064445) tại đúng 523e9cf thành công.
- Cả 15 test jobs Linux/macOS/Windows × Python 3.10–3.14 thành công.
- Accuracy, quality, module eval, real CBM 0.10.8 và package smoke ba OS đều thành công.
- [Branch main](https://api.github.com/repos/minhgv/sot-graph/branches/main) được bảo vệ bằng 23 required status contexts cho non-admin.
- [Tag release run 33823998246](https://github.com/minhgv/sot-graph/actions/runs/33823998246) thành công, gồm GitHub Release và PyPI publish.
- [GitHub Release v0.3.1](https://github.com/minhgv/sot-graph/releases/tag/v0.3.1) có wheel, sdist và một asset thừa default.gitignore dung lượng 1 byte.
- [PyPI sot-graph 0.3.1](https://pypi.org/project/sot-graph/) có wheel 509.149 byte và sdist 682.750 byte, không bị yank.

---

## 5. Scorecard mới

Điểm đo mức sẵn sàng làm “bản đồ dẫn đường có bảo chứng”, không đo số lượng command.

| Năng lực | Trước | Mới | Nhận định |
|---|---:|---:|---|
| Index, freshness, self-healing | 8,0 | **8,5** | Nền tảng local-first, zero drift, portability tốt |
| Symbol navigation | 7,8 | **8,0** | Anchor verification mạnh; relevance và ambiguity vẫn lẫn |
| Static call graph | 7,4 | **7,8** | Oracle tốt hơn, thêm negative cases; dynamic/alias/scope còn FN/FP |
| Search quality | 5,0 | **6,2** | Có 48-probe gate; vẫn synthetic và dogfood relevance chưa tốt |
| Context pack cho AI | 5,4 | **5,2** | Hard budget đúng; completeness và ambiguity contract chưa đúng |
| Diff-impact engine advisory | 6,2 | **6,8** | Delete bug đã sửa, oracle mới; errors/caps vẫn chưa join decision |
| PR-native impact integration | — | **3,0** | Workflow chạy được nhưng đang phân tích sai diff |
| Thiết kế trust chain | 7,2 | **7,5** | State machine, receipt, snapshot, ledger đúng hướng |
| Assurance soundness thực tế | 4,2 | **4,0** | Phản ví dụ false-assured qua MCP còn nguyên |
| Provider-neutral/federation | 5,5 | **5,8** | Builtin độc lập; cross-check mới nhưng MCP vẫn builtin-only |
| Repo/architecture map | 3,5 | **3,3** | Self-dogfood vẫn nhiễu fixture/vendor/template |
| Evaluation science | 5,6 | **6,6** | Search/diff gate tốt hơn; exact oracle không gate metric |
| Release/operations | 4,5 | **8,3** | Cải thiện lớn nhất: tag, PyPI, matrix, protection, watchdog |
| Maintainability/governance | 4,8 | **5,0** | Test dày nhưng core file lớn, bus factor 1, thiếu governance |

---

## 6. Những gì đã làm tốt

### 6.1 Release và vận hành đã trở nên tái lập

**OUTSIDE-BUNDLE / INFERENCE — CODE/REMOTE**

- Version được single-source từ sot_graph.__version__ trên main.
- Release phụ thuộc đầy đủ lint, matrix test, accuracy, quality, module eval, real-provider E2E và package smoke.
- PyPI dùng trusted publishing/OIDC và attestation.
- Branch protection thực sự tồn tại, không chỉ là comment trong workflow.
- Package smoke kiểm tra cả wheel, sdist, CLI và MCP initialization trên ba OS.

Đây là thay đổi cấp sản phẩm, không phải cosmetic.

### 6.2 Nền tảng trust vẫn là điểm khác biệt tốt

**OUTSIDE-BUNDLE / INFERENCE — CODE**

- [State machine canonical](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/assurance/state.py) có sáu trạng thái và severity join fail-closed.
- [Snapshot](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/snapshot.py) gắn HEAD, dirty state và content digest.
- [Identity](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/assurance/identity.py) giàu hơn bare symbol.
- Ledger có provenance, append-only, transaction, invalidation và retention.
- Builtin có thể chạy không cần external daemon; provider ngoài là optional.

Hướng kiến trúc đúng là “evidence/claim system”, không phải chỉ “graph search có confidence”.

### 6.3 Regression evidence tốt hơn

**OUTSIDE-BUNDLE / INFERENCE — RUN**

Exact static corpus:

| Metric | Giá trị |
|---|---:|
| Static positive | 1.012 |
| Static negative | 124 |
| TP / FN / FP / TN | 1007 / 5 / 2 / 123 |
| Precision / Recall / F1 | 99,8% / 99,5% / 99,7% |
| Search cũ, 20 probe | Hit@1 60%, Hit@5 75%, Hit@10 100% |

Search-quality mới:

| Lớp | Hit@1 | Hit@5 | Hit@10 | MRR |
|---|---:|---:|---:|---:|
| Exact | 100% | 100% | 100% | 1,000 |
| Semantic | 75% | 100% | 100% | 0,875 |
| Ambiguous | 100% | 100% | 100% | 1,000 |
| Path-qualified | 100% | 100% | 100% | 1,000 |
| Overall | 93,8% | 100% | 100% | 0,969 |

Diff-impact mới đạt macro symbol/test/files F1 = 1,00 trên sáu scenario planted. Quan trọng hơn, benchmark đã bắt một bug thật: delete-file trước đó map vào interval rỗng.

### 6.4 Hiệu năng được xử lý ở đúng hotspot

**OUTSIDE-BUNDLE / INFERENCE — CODE**

- Reverse traversal và explore được batch theo level.
- Watcher chỉ chạy resolver/janitor một lần mỗi batch.
- Rehome cache basename walk.
- Vector index incremental, prune orphan, không rotate im lặng.
- Provider ledger có retention.
- MCP response trimming giảm từ O(n²) serialization về accounting incremental.

Baseline ghi nhận 10.000 file: reconcile p50 khoảng 6,4 giây; mixed verified query p50 khoảng 97,5 ms trên máy benchmark. Đây là tín hiệu khả quan, nhưng chưa phải CI performance gate.

---

## 7. P0 blockers — phải đóng trước khi gọi là assurance gate

### P0-1. PR diff bot phân tích sai revision

**OUTSIDE-BUNDLE / INFERENCE — CODE/RUN**

[Workflow](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/.github/workflows/diff-impact.yml) đặt base bằng pull_request.base.sha rồi truyền nguyên SHA cho action.

[GitDeltaExtractor](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/diff_impact.py) định nghĩa một revision đơn thành:

    git diff revision~1 revision

Vì vậy bot đọc commit đã tạo base, không đọc base...HEAD của PR.

Phản ví dụ trên chính repo:

| Target | Số file engine thấy |
|---|---:|
| 2666c583 | 2 |
| 2666c583...HEAD | 50 |

Hai vấn đề đi kèm:

- [Composite action](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/.github/actions/diff-impact/action.yml) cài sot-graph mới nhất từ PyPI, nên dogfood main thường kiểm thử bản release cũ thay vì code của PR.
- Fallback git URL dùng github.repository của consumer, tức có thể trỏ tới repo dùng action chứ không phải sot-graph.
- GitHub renderer chỉ hiển thị risk score/caller/test, không hiển thị receipt status, scope coverage, unknowns, truncation hay closure decision.
- Khi không tìm thấy caller, renderer viết “low ripple effect”; command vẫn exit 0 ngay cả khi receipt PARTIAL.

**Tác động:** Một PR có thể nhận comment trông đáng tin nhưng dựa trên diff khác.

**Fix tối thiểu:**

1. Workflow truyền base_sha...head_sha hoặc merge-base...HEAD.
2. Action có input head rõ ràng; lưu request identity trong report.
3. Dogfood local source bằng pip install . hoặc wheel build từ checkout; external consumers pin owner/repo/path@immutable-tag.
4. Renderer bắt buộc hiện assurance status, reason codes, coverage, truncation và snapshot.
5. Thêm chế độ advisory exit 0 và gate exit khác 0; không trộn hai semantics.

**Exit gate:** Integration test tạo PR history nhiều commit và chứng minh changed-file set đúng với git diff merge-base...HEAD; golden comment chứa receipt digest và không nói “low ripple” khi completeness chưa proven.

### P0-2. MCP transport cắt evidence nhưng giữ ASSURED_WITHIN_SCOPE

**OUTSIDE-BUNDLE / INFERENCE — CODE/RUN**

[McpService._fits_response](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/mcp_service.py) đặt top-level truncated khi giảm list để vừa byte budget, nhưng không đưa fact mới về canonical decision.

Phản ví dụ tại HEAD:

~~~json
{
  "input_callers": 400,
  "returned_callers": 13,
  "transport_truncated": true,
  "assurance_facts.truncated": false,
  "assurance.status": "ASSURED_WITHIN_SCOPE",
  "closure_decision": "closed",
  "response_bytes": 1989
}
~~~

R5 đã làm trimmer nhanh hơn, nhưng giữ nguyên semantics cũ. Digest mới chỉ chứng minh payload đã cắt, không chứng minh kết luận ban đầu còn sound.

**Fix:**

- Transport không được tự sửa evidence-bearing receipt.
- Nếu cần cắt, lưu receipt đầy đủ thành content-addressed artifact; response trả receipt_root, page cursor và counts.
- Nếu vẫn trả projection bị cắt, recompute decision với truncated=true, tối đa PARTIAL.
- Mọi adapter chỉ được dùng canonical decision sau projection, không dùng status cũ.

**Exit gate:** Property invariant trên mọi surface:

    returned_count < enumerated_count  => status != ASSURED_WITHIN_SCOPE

### P0-3. CLI, MCP thường và MCP receipt chưa cùng một request pipeline

**OUTSIDE-BUNDLE / INFERENCE — CODE/RUN**

- CLI parser mặc định target là HEAD.
- McpService.diff_impact và McpService.diff_impact_receipt mặc định HEAD~1.
- Với semantics revision đơn, CLI đọc commit mới nhất; MCP mặc định đọc commit trước đó.

Tại HEAD audit:

| Surface mặc định | File được phân tích |
|---|---|
| CLI | .github/workflows/ci-watchdog.yml |
| MCP | docs/RELEASE.md, pyproject.toml, uv.lock |

Ngoài ra MCP diff_impact thường gọi DiffImpactEngine trực tiếp; receipt tool đi qua diff_impact_receipt. Hai đường có metadata và assurance contract khác nhau.

**Fix:** Tạo một ImpactRequest typed contract và một executor:

    parse request → resolve diff identity → collect evidence → decide → immutable receipt → render

CLI, MCP, Python API, action và UI chỉ là projection của cùng receipt.

**Exit gate:** Metamorphic test chứng minh cùng request cho cùng changed files, snapshot, evidence root, reason codes và status trên HEAD, range, staged, working tree, rename, delete và empty diff.

### P0-4. Scope proof, coverage và hard-cap accounting chưa sound

**OUTSIDE-BUNDLE / INFERENCE — CODE/RUN**

[Receipt collection](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/assurance/receipts.py) còn:

- direct edges LIMIT 500 không có enumerated/returned/truncated;
- lỗi DB ở _edges_of bị đổi thành list rỗng;
- diff evidence LIMIT 50 mỗi path;
- evidence query nuốt exception;
- reverse call traversal break khi DB error nhưng không tạo collection_error;
- changed-file cap 200 đã explicit, nhưng các cap trên chưa explicit;
- diff receipt vẫn hard-code open_conflicts=0.

[Scope manifest](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/assurance/coverage.py) hash tên included file và exclusion pattern, chưa hash content của toàn search universe. Snapshot scope digest chủ yếu bind các file đã được tìm thấy, không chứng minh đã duyệt hết candidate universe.

Coverage có hai lỗi đối nghịch:

- PARTIAL_AST được tính như covered hoàn toàn;
- EXCLUDED vẫn nằm trong mẫu số.

Phản ví dụ:

| Input | covered_fraction |
|---|---:|
| Chỉ một file PARTIAL_AST | 1,0 |
| Một indexed + một excluded | 0,5 |

Ngưỡng 0,9 cũng không đủ để bảo chứng absence: 10% chưa duyệt vẫn có thể chứa caller duy nhất.

Self scope-receipt của scope_receipt sau reconcile chỉ đạt PARTIAL, coverage 75,8%, transitive bị cắt và dynamic gap được phát hiện. Việc fail-closed này là tốt; nhưng nó cũng cho thấy repo chưa tự đạt mức assurance mà tài liệu tuyên bố.

**Fix:**

- Xây ScopeUniverse trước query: eligible files, exclusions, file digests, language/relation capability, parser outcomes, cross-repo boundaries.
- Tách enumeration coverage, semantic capability và evidence freshness.
- Absence/exhaustive claim đòi universe exhaustion 100% trong declared scope, không dùng average 90%.
- PARTIAL_AST có ceiling PARTIAL cho relation/exhaustive claims.
- EXCLUDED đứng ngoài denominator nhưng hiện rõ trong boundary và risk.
- Mọi collection trả enumerated, returned, cap, cursor_exhausted, error.
- DB/tool error luôn map collection_error → UNVERIFIABLE.

**Exit gate:** Stress/fault tests với 201 file, 501 edge, 51 evidence/path, 5.001 ledger row, DB fault và provider pagination không bao giờ false-assure.

### P0-5. Job “Accuracy Oracle” chưa gate accuracy của exact oracle

**OUTSIDE-BUNDLE / INFERENCE — CODE**

[CI workflow](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/.github/workflows/ci.yml) chạy evaluator rồi chỉ assert committed corpus digest bằng fresh corpus digest. [sot_evaluator.py](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/scripts/sot_evaluator.py) luôn exit 0 sau full run, bất kể metric.

Do đó extractor có thể regress từ F1 99,7% xuống thấp hơn mà job vẫn xanh, miễn corpus không đổi. Search-quality và diff-impact scripts có threshold thật; exact evaluator chưa có.

Baseline JSON còn chứa absolute temp paths, nên artifact khác byte giữa macOS và Linux dù metric giống nhau.

**Fix:**

- Thêm --gate với floor theo language × relation × positive/negative.
- So committed và fresh metrics/confusion bằng normalized relative paths.
- Fail khi metric giảm quá budget hoặc xuất hiện regression class mới.
- Giữ selfcheck để bảo vệ evaluator, nhưng không coi selfcheck là model quality gate.

**Exit gate:** Mutation test cố tình xóa resolver/đổi target và chứng minh CI đỏ vì metric, không chỉ vì test unit.

### P0-6. Evidence invalidation và conflict chưa được bind đúng generation

**OUTSIDE-BUNDLE / INFERENCE — CODE**

Diff receipt tìm provider evidence theo path nhưng:

- không lọc invalidated_at;
- không ràng buộc project/snapshot generation ở query đó;
- chỉ lấy 50 row/path;
- chỉ liệt kê “invalidated” chứ không thực hiện state transition;
- đặt open_conflicts bằng 0.

Historical evidence có thể làm closure mở mãi; evidence thứ 51 có thể biến mất; conflict thật có thể bị bỏ qua.

**Fix:** Evidence identity phải gồm project root, provider, capability, source snapshot, target snapshot và canonical subject/relation. Invalidation phải là append-only transition có reason; receipt join đúng generation và union conflicts.

**Exit gate:** Replay nhiều generation chứng minh N không bị N-2 làm nhiễu và mọi conflict/truncation đều hạ decision.

### P0-7. Claim trong docs và agent prompts vẫn vượt bằng chứng

**OUTSIDE-BUNDLE / INFERENCE — CODE**

Ví dụ còn tồn tại:

- README: “authoritative, verified projection”, “Zero Hallucinated Anchors”.
- RELEASE_DECISION v0.3.0: GO PRODUCTION_QUALIFIED / ASSURED_WITHIN_SCOPE, autonomous refactoring.
- Capability matrix: Tier-A có ceiling ASSURED_WITHIN_SCOPE dù exact corpus vẫn có FP/FN.
- Workflow guideline: STRONG là “100% reliable anchor; proceed directly”.
- AGENTS.md: “100% exact cross-file references”, lặp nhiều block, ghi v0.3.0 và chỗ khác ghi schema v5 dù runtime là v0.3.1/schema 8.
- Release note ghi 1012 pass/2 skip; local reproducible run là 1011/3 vì còn một Bun-dependent skip.
- README quality badge ghi core 87%; local gate hiện báo 86%.

CI vẫn ignore toàn bộ Markdown/docs. Test “no absolute claims” chỉ kiểm tra một số OMP artifacts, không scan docs/AGENTS.

**Fix:** Claim registry machine-readable, docs sinh từ artifact; claim linter chạy cả docs/agent prompts; mọi claim gắn capability, language, provider, corpus, commit, metric và ceiling.

**Exit gate:** Không có trust claim public nào không truy được về artifact cùng commit; docs-only PR thay trust claim vẫn chạy claim validation.

---

## 8. P1 gaps — để trở thành bản đồ hữu ích thật sự

### P1-1. Repo map và architecture bundle đang lập bản đồ “mọi thứ”, chưa lập bản đồ “điều quan trọng”

**BUNDLE**

Bundle tại HEAD:

- gọi tests, fixtures, docs, plans, CI workflows và adapter config là Core Business modules;
- tạo Calculator.py, Java, Go, Rust, Controllers và Models modules từ evaluation fixtures;
- routing nhận covered_fraction, _disk_state và decide là event/message routes;
- báo ZERO_VIOLATIONS nhưng cùng file liệt kê nhiều critical god nodes;
- modularity Q cao nhưng community count 117 trên repo nhỏ, chưa diễn giải thành mental model;
- template mặc định chứa web portal, SSO, billing, finance và telco integrations không xuất phát từ bundle.

**OUTSIDE-BUNDLE / INFERENCE — RUN**

Repo map 1.200 token xếp evaluation fixture add lên đầu, có minified D3 functions, vendor internals và test helpers. Ngay cả khi focus scope_receipt, fixture add và minified D3 vẫn xuất hiện.

**Fix:**

- Phân loại source/test/fixture/vendor/generated/docs/tooling trước ranking.
- Default product map chỉ dùng production source; có flag để thêm test/docs.
- Rank kết hợp entrypoint, public API, ownership, churn, fan-in/fan-out và domain cluster; không chỉ PageRank.
- Bundle phải có confidence và UNKNOWN, không dùng ZERO_VIOLATIONS khi rule detector chưa quan sát được layer policy.
- Template phải schema-driven; bỏ mọi domain giả định.

**Exit gate:** Human study và agent task test cho thấy top map chứa landmark thật; fixture/vendor contamination dưới 2%; không có template claim không có evidence.

### P1-2. Context pack tôn trọng budget nhưng contract về “đủ” chưa đúng

**OUTSIDE-BUNDLE / INFERENCE — RUN**

Với scope_receipt và budget 1.200 token:

- discovered_nodes: 51;
- returned_nodes: 1;
- inbound/outbound/transitive: 0;
- full_source bị cắt;
- trusted instructions bị cắt;
- target được auto-resolve từ ambiguity;
- limits.truncated=true;
- nhưng completeness vẫn COMPLETE_WITHIN_INDEX_CAPABILITY.

AGENTS.md lặp nội dung và tiêu tốn 8.200 byte trusted instructions, đẩy code context ra khỏi budget.

**Fix:**

- Completeness phải phản ánh bundle projection: PARTIAL_TRUNCATED.
- Không auto-resolve ambiguous target cho change/refactor context.
- Chia budget riêng: instructions, target body, contracts, tests, unknowns.
- Trả omitted counts và cursor/artifact refs.
- Deduplicate/version agent instructions; chỉ inject rule liên quan task.
- Đo task sufficiency, không chỉ token reduction.

**Exit gate:** 95% benchmark tasks nhận đủ target + direct contracts + tối thiểu một relevant test trong budget; ambiguity không bao giờ bị chọn im lặng.

### P1-3. STRONG đang mô tả anchor, nhưng giao diện khiến người dùng hiểu là câu trả lời đúng

**OUTSIDE-BUNDLE / INFERENCE — RUN/CODE**

Search “assurance receipt” trả ReceiptStatus trước scope_receipt, nhưng mọi hit đều mang STRONG và coverage 100%. “100%” ở đây là physical span verification của từng hit, không phải relevance hay repo coverage. Envelope đồng thời ghi COMPLETE_WITHIN_INDEX_CAPABILITY dù doctor có 5.932 pending relations.

**Fix:** Trả bốn trục riêng:

| Trục | Ví dụ |
|---|---|
| Anchor freshness | fresh / stale / missing |
| Identity | unique / ambiguous / unresolved |
| Query relevance | exact / semantic / weak |
| Scope completeness | exhaustive / bounded / partial / unknown |

Legacy STRONG chỉ là compatibility field và không được dùng cho autonomous decision.

### P1-4. Provider federation chưa thống nhất identity space và chưa tới MCP read path

**OUTSIDE-BUNDLE / INFERENCE — CODE/RUN**

Điểm tốt: builtin độc lập; external mặc định off; require_external fail-closed trên MCP.

Gap:

- MCP search/usages thực tế builtin-only; prefer_external chỉ trả note.
- Provider cross-check hiện so graph_edges src/dst node IDs với provider_evidence src_symbol/dst_symbol. Unit test seed hai bên bằng cùng chuỗi giả, nhưng real builtin IDs có dạng sym:hash:name trong khi provider thường ghi qualified/bare symbol.
- SCIP search evidence chủ yếu definition/reference, không phải cặp call-edge tương thích.
- Self cross-check có 9.854 builtin pairs, 0 external pair; chưa chứng minh reconciliation thực tế.

**Fix:** Canonical EvidenceIdentity dùng repo/path/language/kind/FQN/span; normalize cả hai provider về identity trước join. Expose cross-check qua MCP và receipt, nhưng giữ external optional.

**Exit gate:** Real CBM/SCIP overlap corpus có precision/recall/conflict adjudication và zero join-by-accidental-string.

### P1-5. Real-repo evaluation chưa là quality evidence

**OUTSIDE-BUNDLE / INFERENCE — CODE**

scripts/test_real_repos.py là smoke harness trông chờ 12 sibling repo có sẵn; không clone/pin commit, không có labeled ground truth và không chạy trong CI. Real CBM E2E chứng minh adapter/wire/ledger hoạt động, không chứng minh impact accuracy trên code thật.

**Fix:** Tạo versioned holdout manifest với immutable commit, annotated tasks/edges/diffs, language/license metadata và evaluator độc lập. Tách:

- extractor accuracy;
- retrieval relevance;
- impact recall;
- test-selection recall;
- abstention calibration;
- task success và token/time saving.

### P1-6. Người vận hành chưa có cockpit để phản biện receipt

Hiện JSON giàu dữ liệu nhưng người dùng cần một view trả lời:

1. SOT đang khẳng định điều gì?
2. Scope nào đã được duyệt?
3. Những file/provider/construct nào nằm ngoài?
4. Evidence nào dẫn tới conclusion?
5. Vì sao bị hạ từ ASSURED xuống PARTIAL?
6. Cần làm gì để nâng trạng thái?
7. Receipt trước và sau khác nhau thế nào?

Nên có terminal TUI hoặc static HTML đầu tiên; web service không bắt buộc.

### P1-7. Hotspot maintainability và governance

**BUNDLE**

God nodes gồm Database degree 356, Reconciler 236 và McpService 118.

**OUTSIDE-BUNDLE / INFERENCE — CODE**

- db.py 3.122 dòng;
- cli.py 2.365 dòng;
- diff_impact.py 1.584 dòng;
- mcp_service.py 1.571 dòng.

Repo còn thiếu CONTRIBUTING, SECURITY, CODEOWNERS, Dependabot/Renovate và changelog chuẩn; bus factor là 1. GitHub Actions dùng version tags và setup-uv “latest”, chưa pin immutable SHA.

Đây chưa phải blocker beta, nhưng là blocker để người khác tin và cùng duy trì.

---

## 9. Mô hình sản phẩm đích

### 9.1 SOT Graph không nên là “graph biết mọi thứ”

North star phù hợp hơn:

> **Một hệ thống tạo claim có evidence, biết giới hạn của claim và cung cấp cùng một bản đồ cho AI lẫn con người.**

Ba lane phải tách rõ:

| Lane | Mục tiêu | Ceiling |
|---|---|---|
| Scout | Tìm nhanh, định hướng, recall cao | Candidate/advisory |
| Verify | Xác minh anchor, identity, relation cục bộ | Verified presence/relationship |
| Assure | Chứng minh bounded absence/exhaustive impact | ASSURED_WITHIN_SCOPE khi universe exhausted |

### 9.2 Kiến trúc tham chiếu

~~~mermaid
flowchart TD
    A["Ý định / thay đổi"] --> B["Canonical ClaimRequest"]
    B --> C["Scope compiler + snapshot"]
    C --> D["Evidence collectors"]
    D --> E["Canonical claim engine"]
    E --> F["Immutable full receipt"]
    F --> G["CLI / MCP / PR / Human view"]
~~~

Nguyên tắc:

- Request identity được resolve một lần.
- Scope universe được compile trước collection.
- Collector không tự quyết định trust.
- Decision engine không biết transport.
- Full receipt bất biến và content-addressed.
- CLI/MCP/PR/UI không recompute; chỉ render cùng receipt.
- Mất dữ liệu khi projection luôn hạ ceiling hoặc dẫn tới page/artifact, không giữ verdict cũ.

### 9.3 Contract chung

~~~json
{
  "request": {
    "claim_type": "impact",
    "subject": {"kind": "git_range", "base": "...", "head": "..."},
    "policy": "verify"
  },
  "snapshot": {
    "repo_id": "...",
    "head": "...",
    "dirty_digest": "...",
    "scope_root": "sha256:..."
  },
  "scope": {
    "eligible": 273,
    "enumerated": 273,
    "excluded": [],
    "unknown": [],
    "cursor_exhausted": true
  },
  "evidence": {
    "root": "sha256:...",
    "counts": {},
    "providers": [],
    "conflicts": []
  },
  "decision": {
    "status": "PARTIAL",
    "reason_codes": ["dynamic_dispatch_unresolved"],
    "allowed_actions": ["inspect", "run_tests"],
    "forbidden_actions": ["auto_merge"]
  },
  "projection": {
    "returned": 100,
    "total": 100,
    "truncated": false,
    "next_cursor": null
  }
}
~~~

### 9.4 Claim profiles

| Claim | Điều kiện tối thiểu |
|---|---|
| Presence | Anchor fresh, identity đủ rõ, span source-verified |
| Relationship | Presence hai đầu + relation verifier/capability phù hợp |
| Impact candidate | Bounded traversal, explicit gaps, không gọi là exhaustive |
| Absence | Scope universe 100% exhausted, no cap/error, capability đủ cho relation |
| Exhaustive impact | Absence conditions + all relevant boundaries/providers reconciled |

---

## 10. Roadmap theo phụ thuộc

### Phase 0 — Truth reset và fix false signal, ngày 0–7

**Mục tiêu:** Không để AI/người dùng nhận tín hiệu “an toàn” từ sai diff hoặc response thiếu evidence.

Deliverables:

1. Sửa PR action thành merge-base...head.
2. Dogfood source của PR, không cài PyPI latest.
3. GitHub comment hiện receipt status/reason/scope/truncation.
4. Fix invariant MCP truncation.
5. Đồng bộ default diff CLI/MCP.
6. Thêm exact evaluator metric gate.
7. Hạ claim production trong README, RELEASE_DECISION, capability matrix, workflow guide và AGENTS.

Exit gates:

- PR integration golden test đúng range.
- Không surface nào giữ ASSURED khi projection truncated.
- Intentional F1 regression làm CI đỏ.
- Main/docs trust claims đều trace được về artifact.

### Phase 1 — Một canonical claim pipeline, tuần 2–4

**Mục tiêu:** Xóa đường đi song song.

Deliverables:

- ClaimRequest/ImpactRequest schema versioned.
- Một executor cho CLI, MCP, Python API, PR action.
- Immutable ReceiptStore local content-addressed.
- Projection contract có total/returned/cursor/root.
- CollectionError typed; không swallow DB/tool errors.
- Golden parity tests trên mọi diff mode.

Exit gates:

- CLI/MCP/action cùng digest cho cùng request.
- Surface code không gọi collector/engine riêng.
- Fault injection luôn dẫn tới UNVERIFIABLE hoặc ABSTAINED.

### Phase 2 — ScopeUniverse và semantics bảo chứng, tuần 4–8

**Mục tiêu:** Chứng minh “đã tìm ở đâu” trước khi nói “không có”.

Deliverables:

- Eligible/excluded/unknown file manifest với content Merkle root.
- Coverage ba trục: enumeration, parser capability, relation capability.
- PARTIAL_AST ceiling; excluded semantics đúng.
- Exhausted pagination cho edge/provider/ledger.
- Generation-scoped evidence invalidation/conflict join.
- Policy theo risk: local body, public API, rename/delete, auth/tenant.

Exit gates:

- False-assured rate = 0 trên adversarial scope suite.
- 201/501/5001 stress cases có accounting đầy đủ.
- Rename/delete chỉ mở gate khi absence proof đủ.

### Phase 3 — Evaluation thật và provider-neutral federation, tuần 6–10

**Mục tiêu:** Biết hệ thống đúng đến đâu ngoài corpus do mình trồng.

Deliverables:

- 10–20 repo holdout pin commit, giấy phép rõ, ground truth review đôi.
- Diff-impact/test-selection benchmark trên PR thật.
- Search task set từ issue/bugfix thật.
- Canonical provider identity normalization.
- CBM/SCIP cross-check bằng overlap thật; MCP exposure.
- Calibration cho abstention và unknown.

Exit gates đề xuất:

- Presence precision ≥ 99,5% trên holdout.
- Impact recall ≥ 95% cho supported static scope.
- Test-selection recall ≥ 98% trước khi cho phép skip test.
- False absence = 0 trong suite.
- Provider conflict không bị overwrite.

### Phase 4 — Bản đồ và context product-grade, tuần 8–13

**Mục tiêu:** Bản đồ giúp hoàn thành task, không chỉ chứa nhiều node.

Deliverables:

- Production-source default filters.
- Landmark/domain/entrypoint/change-flow maps.
- Schema-driven architecture report không có domain giả định.
- Context budget allocator và task-sufficiency benchmark.
- Ambiguity UX: candidate selection, no silent auto-pick.
- Human receipt explorer static HTML/TUI.

Exit gates:

- Fixture/vendor contamination top map < 2%.
- Landmark precision@20 ≥ 90% qua reviewer.
- Agent task success tăng có ý nghĩa so với rg/baseline.
- Context pack đủ target/contracts/test cho ≥ 95% supported tasks.

### Phase 5 — Pilot, hardening và GA, tháng 4–6

Deliverables:

- Required PR workflow, admin bypass policy rõ.
- Immediate workflow_run watchdog hoặc external monitor; không chờ 6 giờ.
- Pinned Actions SHA, SBOM, signed provenance, reproducible build check.
- SECURITY, CONTRIBUTING, CODEOWNERS, dependency automation.
- Telemetry opt-in chỉ chứa metric, không source.
- 3–5 pilot repo, incident review và rollback playbook.

GA gate:

- 30 ngày không có false-assured Sev-1/Sev-2 trong pilot.
- 100 lifecycle integrity runs liên tiếp pass.
- p95 query/reconcile trong budget trên repo đại diện.
- Mọi supported claim có measured ceiling và public limitation.

---

## 11. Backlog có thể tạo GitHub issues ngay

| ID | Priority | Issue | Acceptance criteria |
|---|---:|---|---|
| SG-101 | P0 | Fix PR base/head range | Multi-commit PR test; set file bằng git diff merge-base...head |
| SG-102 | P0 | Dogfood current checkout in action | CI report ghi tool commit = analyzed commit |
| SG-103 | P0 | Put assurance in GitHub renderer | Status, reasons, scope, snapshot, truncation, digest hiện ở top |
| SG-104 | P0 | Transport truncation invariant | Any omitted evidence ⇒ PARTIAL hoặc artifact pagination |
| SG-105 | P0 | Unify diff defaults and executor | CLI/MCP/Python/action parity golden |
| SG-106 | P0 | Gate exact evaluator metrics | Regression mutation fails CI |
| SG-107 | P0 | Account every collector cap/error | total/returned/exhausted/error on 200/500/50/5000 boundaries |
| SG-108 | P0 | Redesign absence coverage | 100% eligible universe; PARTIAL_AST cannot assure absence |
| SG-109 | P0 | Generation-scoped invalidation/conflict | Replay N/N-1/N-2 tests |
| SG-110 | P0 | Claim registry and docs linter | Public claims generated/validated at same commit |
| SG-201 | P1 | Production-source repo-map filters | No fixture/vendor/minified symbols by default |
| SG-202 | P1 | Honest pack completeness | Returned/discovered/omitted + no ambiguous auto-pick |
| SG-203 | P1 | Canonical cross-provider identity | Join by EvidenceIdentity, not raw string |
| SG-204 | P1 | Real-repo holdout benchmark | Pinned repos, labeled oracle, CI/nightly report |
| SG-205 | P1 | Human receipt explorer | Explain claim/scope/evidence/unknown/remediation |
| SG-301 | P2 | Split core hotspots | DB repositories, CLI commands, services, renderers separated |
| SG-302 | P2 | OSS governance/security | SECURITY, CONTRIBUTING, CODEOWNERS, dependency bot |
| SG-303 | P2 | Supply-chain hardening | Pin Actions SHA, SBOM, provenance/reproducibility |

Thứ tự bắt buộc: **101–110 trước 201–205**. Thêm provider, UI hoặc language trước khi đóng P0 sẽ tăng diện tích false confidence.

---

## 12. KPI và release gates

### Safety

- False ASSURED after truncation: 0.
- False absence/exhaustive claim: 0 trong adversarial + holdout.
- Unaccounted cap/error: 0.
- Cross-repo evidence leakage: 0.
- CLI/MCP/action receipt mismatch: 0.

### Accuracy

- Metrics theo language × relation × construct, không chỉ aggregate F1.
- Precision/recall cho presence, relation, impact, test selection.
- Ambiguous query MRR/Hit@k.
- Abstention precision: khi abstain có đúng là thiếu evidence không.
- Calibration: confidence bucket so với observed correctness.

### AI utility

- Task success rate.
- Wrong-file edit rate.
- Time-to-first-correct-anchor.
- Token dùng tới first successful test.
- Tỷ lệ agent kiểm tra reason/unknown trước khi edit.

### Human utility

- Thời gian hiểu blast radius.
- Tỷ lệ reviewer đồng ý với landmark map.
- Tỷ lệ receipt có remediation rõ.
- Số lần operator override và lý do.

### Operations

- Main green rate và mean time to detect/recover.
- p50/p95 reconcile/search/impact theo repo size.
- Determinism qua OS/Python.
- Reproducible artifact digest.
- Provider timeout/crash/orphan rate.

---

## 13. Chính sách sử dụng nên công bố ngay

| Workflow | Trạng thái |
|---|---|
| Cài package và dùng local index | Supported beta |
| Tìm symbol/file và mở anchor | Supported advisory |
| Caller/callee exploration | Advisory; không exhaustive |
| Repo map | Experimental orientation |
| Context pack | Beta; bắt buộc đọc limits/warnings |
| Diff-impact local với explicit range | Beta advisory |
| GitHub PR bot hiện tại | Không dùng cho quyết định cho tới SG-101–103 |
| “0 callers/no impact” | Unsupported production claim |
| Rename/delete tự động | Human-gated experimental |
| Minimal test selection để bỏ test khác | Unsupported safety gate |
| Auto-merge dựa trên SOT receipt | No-go |

---

## 14. Khuyến nghị quyết định

### Nên làm ngay

1. Phát hành 0.3.2 chỉ cho truth/surface fixes: PR range, MCP truncation, default parity, exact metric gate, docs.
2. Đổi slogan từ “authoritative projection” thành “verified, bounded evidence index”.
3. Đóng R1–R5 bằng exit criteria đo được, không bằng commit message.
4. Giữ builtin độc lập và external optional; không biến CBM/SCIP thành dependency bắt buộc.
5. Chỉ mở thêm language/UI sau khi một canonical receipt pipeline đi qua mọi surface.

### Chưa nên làm

- Không gọi v0.3.1 là production-qualified.
- Không marketing “zero hallucination”, “100% reliable” hoặc “complete” ở cấp repo.
- Không dùng PR bot hiện tại làm required safety gate.
- Không tối ưu thêm response trimmer trước khi sửa semantics truncation.
- Không dùng aggregate F1 synthetic để bảo chứng rename/delete.

### North star 12 tháng

Một task bắt đầu bằng intent và kết thúc bằng receipt có thể kiểm toán:

1. AI/human chọn subject và claim.
2. SOT compile universe và snapshot.
3. Builtin + optional providers thu evidence.
4. Claim engine quyết định với unknowns/caps/conflicts.
5. Agent sửa code trong boundary.
6. Test/compiler/reconcile tạo post-change evidence.
7. Human xem cùng receipt qua UI; AI đọc cùng JSON.
8. Gate chỉ mở khi policy của loại thay đổi được thỏa.

Khi đó SOT Graph mới thực sự là “bản đồ”: không chỉ chỉ đường, mà còn cho biết đường nào chưa khảo sát, biển báo nào đáng tin và điều kiện nào phải thỏa trước khi đi tiếp.

---

## Phụ lục A — Kết quả tái lập chính

~~~text
HEAD
523e9cf7bf943a865a123cdc49af1446d73c027b

Reconcile
49 indexed/updated, 224 unchanged, 0 purged, 0 failed

Self-index
273 files, 3921 nodes, 9854 edges
5932 pending: 257 ambiguous, 5675 unresolved

Tests
1011 passed, 3 skipped, 1014 collected

Quality
core 86%, receipts 91%
ruff pass, pyright 0, bandit pass, pip-audit clean

Search benchmark
48 probes; overall Hit@1 93.8%, Hit@5 100%, MRR 96.9%; gates pass

Diff benchmark
6 scenarios; macro symbol/test/files F1 1.00; gates pass

Exact evaluator
TP 1007, FN 5, FP 2, TN 123
P 99.8%, R 99.5%, F1 99.7%

MCP truncation counterexample
400 caller input → 13 returned
transport truncated=true
assurance_facts.truncated=false
status=ASSURED_WITHIN_SCOPE
closure=closed

PR target counterexample
single baseline SHA → 2 files
baseline...HEAD → 50 files
~~~

## Phụ lục B — Nguồn chính

- [Repository](https://github.com/minhgv/sot-graph)
- [HEAD 523e9cf](https://github.com/minhgv/sot-graph/commit/523e9cf7bf943a865a123cdc49af1446d73c027b)
- [Diff từ baseline cũ tới HEAD](https://github.com/minhgv/sot-graph/compare/2666c5832649644897d9e03b89e431c35f70b80d...523e9cf7bf943a865a123cdc49af1446d73c027b)
- [CI workflow](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/.github/workflows/ci.yml)
- [PR diff workflow](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/.github/workflows/diff-impact.yml)
- [Composite diff action](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/.github/actions/diff-impact/action.yml)
- [CI watchdog](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/.github/workflows/ci-watchdog.yml)
- [Assurance state](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/assurance/state.py)
- [Receipts](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/assurance/receipts.py)
- [Coverage and scope manifest](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/assurance/coverage.py)
- [MCP service](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/mcp_service.py)
- [Diff impact engine](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/diff_impact.py)
- [Repo map](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/repo_map.py)
- [Architecture bundler](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/analytics/bundle.py)
- [Provider cross-check](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/src/sot_graph/providers/cross_check.py)
- [Search benchmark](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/scripts/bench_search_quality.py)
- [Diff-impact benchmark](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/scripts/bench_diff_impact.py)
- [Exact evaluator](https://github.com/minhgv/sot-graph/blob/523e9cf7bf943a865a123cdc49af1446d73c027b/scripts/sot_evaluator.py)
- [Main CI run](https://github.com/minhgv/sot-graph/actions/runs/33826064445)
- [Release CI run](https://github.com/minhgv/sot-graph/actions/runs/33823998246)
- [Release v0.3.1](https://github.com/minhgv/sot-graph/releases/tag/v0.3.1)
- [PyPI project](https://pypi.org/project/sot-graph/)

