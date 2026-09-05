# Advisor review — SOT-Graph, 2026-09-05

> Nguồn gốc: report do sub agent **Advisor** tổng hợp theo yêu cầu review toàn diện repo + issues #1-#7.
> Nhãn bằng chứng: `[VERIFIED]` = Advisor tự xác minh qua công cụ của nó; `[REPORTED]` = fact do main agent cung cấp (đã qua QC session SG-204 / chẩn đoán CI agent);
> `[INFERENCE]` = suy luận; `[RECOMMENDATION]` = khuyến nghị.
> Hạn chế đã khai báo: công cụ Read của Advisor lỗi tham số trong cả 2 lượt chạy — các source range không được nó đọc độc lập;
> phần độc lập xác minh được: HEAD `78a4415` + số khai báo function/class (mcp_service 77, diff_impact 54, cli 48, receipts 18).

## Kết luận và phạm vi bằng chứng

**Verdict: INSUFFICIENT_EVIDENCE để chứng nhận toàn bộ HEAD; ưu tiên sửa CI, sau đó đóng các gap coverage/identity trước khi mở rộng tính năng.**

- **[VERIFIED]** Branch `main`, HEAD `78a4415b346c87dd13277a1da92a6c2b8503b6db`, qua `.git/HEAD:1` và `.git/refs/heads/main:1`.
- **[VERIFIED]** Số khai báo function/class: 77 matches `src/sot_graph/mcp_service.py`, 54 `src/sot_graph/diff_impact.py`, 48 `src/sot_graph/cli.py`, 18 `src/sot_graph/assurance/receipts.py`. **Không phải LOC, không phải complexity.**
- **[REPORTED]** Commit history, kết quả test/benchmark, chẩn đoán CI lấy từ main agent / CI-diagnostic agent.
- Báo cáo dùng làm **kế hoạch xử lý + checklist nghiệm thu**, không phải biên bản source review độc lập đã hoàn tất.

## (a) Health assessment

### 1. Kiến trúc và hotspot modules

**Đánh giá: cần kiểm soát coupling; chưa đủ bằng chứng để yêu cầu refactor lớn.**

| Khu vực | Bằng chứng | Nhận định |
|---|---|---|
| MCP service | **[VERIFIED]** 77 declaration matches tại `src/sot_graph/mcp_service.py`; **[REPORTED]** ~1.700 dòng | **[INFERENCE]** Có thể gánh nhiều orchestration/projection responsibilities; số khai báo chưa chứng minh coupling cao. |
| CLI | **[VERIFIED]** 48 matches `src/sot_graph/cli.py` | Giữ CLI là adapter: parse → canonical executor → presentation; không thêm quyết định trust riêng. |
| Diff impact | **[VERIFIED]** 54 matches `src/sot_graph/diff_impact.py` | Tách rõ traversal / evidence collection / claim evaluation trước khi cân nhắc chia module. |
| Receipts | **[VERIFIED]** 18 matches `src/sot_graph/assurance/receipts.py`; **[REPORTED]** schema 1.7 | **[INFERENCE]** Ít functions không loại trừ hotspot: một function lớn có thể chứa nhiều trust-state branches. |

**[RECOMMENDATION]** Chưa làm module split chỉ vì LOC. Đo thêm complexity, fan-in/out, churn, lỗi lịch sử; thiết lập characterization tests trước khi di chuyển code.

### 2. Assurance và claims consistency

**Đánh giá: nền tảng đúng hướng; correctness vẫn phụ thuộc coverage và provenance.**

- **[REPORTED]** SG-105 canonical executor; SG-107 account caps/errors; SG-108 universe/exhaustion; SG-109 generation invalidation.
- **[INFERENCE]** Chuỗi này giảm semantic drift nhưng không tự bảo đảm absence soundness nếu universe loại constructs người dùng hiểu là thuộc phạm vi.
- **[REPORTED]** Linter xác minh provenance bằng `git cat-file -e <sha>^{commit}` tại `src/sot_graph/claims.py:377`.
- **[RECOMMENDATION]** Giữ provenance check fail-closed; sửa môi trường CI thay vì bỏ validation để làm test xanh.
- **[RECOMMENDATION]** Kiểm tra registry nhất quán: claim type, scope, snapshot/generation, provider, resolution, truncation, exhaustion, provenance.

### 3. Extractor và providers

**Đánh giá: coverage và identity là ưu tiên P1.**

- **[REPORTED]** `_iter_scope_nodes` bỏ lambda/comprehension bodies tại `src/sot_graph/_vendor/graphify/extract.py:59-65`; holdout impact recall 0.9609.
- **[INFERENCE]** Vấn đề traversal/scope ownership, không chỉ thiếu một loại AST node — đi vào mọi child mù quáng có thể tạo cạnh sai caller.
- **[REPORTED]** Nested defs + module-level `if` được index; `if TYPE_CHECKING:` classes KHÔNG được index.
- **[RECOMMENDATION]** Tách declaration presence khỏi runtime reachability; type-only declaration có thể thuộc universe tìm symbol dù không phải runtime dependency.
- **[REPORTED]** SG-203 canonical join `src/sot_graph/identity_join.py`, nhưng usages vẫn lẫn absolute/relative paths.
- **[INFERENCE]** Chưa kết luận được persisted identities trùng — lỗi có thể ở storage, provider ingress, hoặc presentation. Phân biệt trước khi sửa.
- **[RECOMMENDATION]** AST/SCIP/CBM giữ provenance riêng; disagreement/unresolved không được biến thành exact agreement.

### 4. Benchmark coverage và credibility

**Đánh giá: bước tiến thực chất, nhưng PASS chỉ trong universe đã đo.**

- **[REPORTED]** 11 repo pinned, oracle stdlib-ast độc lập, 5 suites; presence 1.0, false-absence 0, impact 0.9609, test-sel 1.0 (10/11 đo được), abstention 1.0, retrieval Hit@1 0.79.
- **[INFERENCE]** Oracle riêng vẫn có thể chia sẻ điểm mù khái niệm với engine (cùng dựa AST / cùng loại bỏ constructs khó).
- **[REPORTED]** TYPE_CHECKING bị loại khỏi recall universe; jsonschema attribute-only không đo được test-selection.
- **[RECOMMENDATION]** Công bố denominator, exclusions, unmeasurable, per-repo results; không gọi 10/11 là coverage đầy đủ.
- **[RECOMMENDATION]** Corpus đã dùng để thiết kế fix → trở thành regression corpus; bổ sung tập chưa dùng tuning.

### 5. Test và release health

**Đánh giá: RED theo bằng chứng được báo cáo; blocker hiện có fix nhỏ, rõ.**

- **[REPORTED — độ tin cậy CAO từ CI-diagnostic agent]** Checkout depth-1 thiếu historical commit objects được claims cite (chi tiết mục P0-1).
- **[REPORTED]** 2 test lỗi `tests/test_sg110_claims.py:336` và `:374`; Quality Gates P9 chạy lại pytest dưới coverage tại `scripts/quality_gates.sh:29-31`.
- **[REPORTED]** Local 1242 passed/2 skipped không phủ điều kiện shallow checkout.
- **[RECOMMENDATION]** Nghiệm thu trên commit sau sửa với toàn matrix + Quality Gates xanh; fix root cause chưa có nghĩa không còn failure thứ hai.

### 6. Docs so với reality

**Đánh giá: có wording cần làm chính xác hơn; chưa hoàn tất docs/registry audit.**

- **[REPORTED]** `AGENTS.md` nói "locate all calling sites" trong khi builtin AST có misses đã biết → đổi thành "locate indexed calling sites within reported scope".
- **[RECOMMENDATION]** Đối chiếu CLI/MCP và JIT configuration; chưa có bằng chứng implementation mutate trái contract.
- **Giới hạn:** chưa đọc README, chưa liệt kê claim registry/docs.

## (b) Retrospective issues #1-#7

| Issue / commits | Chất lượng hướng giải pháp | Rủi ro dư và debt | Nghiệm thu cần bổ sung |
|---|---|---|---|
| #1 SG-105 — `a85653b`, `8ad8149` | Canonical pipeline đúng để giữ CLI/MCP parity. | Projection có thể bỏ warnings; digest ổn định nhưng thiếu trường quan trọng vẫn sai; immutable receipt có thể bind nhầm snapshot. | Parity tests CLI/MCP trên success/stale/error/truncation; mutation tests cho digest inputs. |
| #2 SG-107 — `616dcf2`, `88ebeab` | Accounting mọi cap/error là điều kiện cần cho absence claims. | `_ACCOUNTED_LIMITS` bind số dòng = maintenance debt; chưa chứng minh mọi runtime path report đủ. | Chuyển sang collector IDs/cap registry + boundary tests. |
| #3 SG-108 — `dc7e5a5`, `c39a88c` | Universe/exhaustion là nền sound absence. | False-assured 0 là thực nghiệm giới hạn; unsupported constructs có thể bị loại khỏi mẫu số. | Cap/unresolved/unsupported/provider failure đều chặn global absence; khớp universe oracle với declared scope. |
| #4 SG-109 — `aacaade`, `10138cd` | Generation invalidation + conflict join đúng tầng. | Cần kiểm chứng dirty/untracked, partial provider refresh, rollback, root isolation. | N/N-1/N-2 + failure giữa transaction + khác root + disk dirty. |
| #5 SG-110 — `aeada04`, `40784b5` | Registry/linter biến claims thành artifact kiểm tra được. | Test sống phụ thuộc Git object availability; CI thiếu prerequisite; wording lint ≠ behavior. | Full-history CI; shallow fixture trả diagnostic rõ, không bypass provenance. |
| #6 SG-203 — `6e408ab`, `92a192a` | Canonical cross-provider identity + fix importer thật. | Mixed path representation → cần audit end-to-end; schema 1.7 cần compatibility checks. | Same symbol AST/SCIP/CBM join đúng; same name/different roots không join; conflict hiển thị rõ. |
| #7 SG-204 — `0a2066c`, `78a4415` | Holdout độc lập tìm được misses thực, vượt fixture-only testing. | TYPE_CHECKING exclusion; 10/11 measurable; retrieval 0.79; corpus nguy cơ thành tuning set. | Version universe/exclusions; công bố per-repo denominator; bổ sung holdout chưa dùng tuning. |

**[INFERENCE] Tổng thể:** #1-#7 ưu tiên nền tảng trust đúng thứ tự, nhưng "mọi issue đã đóng" ≠ "mọi public claim đã nghiệm thu". Debt lớn nhất: liên kết extraction coverage → universe → assurance → benchmark denominator.

## (c) Kế hoạch khắc phục P0/P1/P2

Effort: S = nhỏ, boundary rõ; M = nhiều paths/tests hoặc quyết định semantics; L = xuyên tầng/nghiên cứu.

### P0-1 — Khôi phục CI và release evidence — **S**

- **Root cause [REPORTED, CAO]:** `.github/workflows/ci.yml` dùng `actions/checkout@v4` không `fetch-depth: 0` → shallow depth-1; commits được claims cite (`85fd9dd`, `b09548d`, `10138cd`) không có trong object store → `commit-unknown` → exit 1. Fail từ `40784b5` (lần đầu CI lint claims cite commit lịch sử). P9 fail cùng nguồn (`quality_gates.sh:29-31`, output `>/dev/null`).
- **Fix:** thêm `fetch-depth: 0` cho checkout của các job chạy pytest/P9. KHÔNG bỏ `git cat-file` validation tại `claims.py:377`.
- **Verify:** full matrix + Quality Gates xanh trên đúng commit; `test_sg110_claims.py:336,374` pass.

### P1-1 — Call coverage trong lambda/comprehensions — **M**

- **Root cause [REPORTED]:** `_iter_scope_nodes` prune các scope này tại `src/sot_graph/_vendor/graphify/extract.py:59-65`.
- **Fix:** sửa traversal + call-extraction region `:330-370` theo policy ownership rõ; không gán calls của nested scope cho outer caller.
- **Verify/accept:** lambda, list/set/dict comp, generator, nested, shadowing, attribute calls; bắt được misses tenacity/click/pexpect; đo precision song song (không đổi recall bằng cạnh sai); holdout không hồi quy.

### P1-2 — Chốt universe cho TYPE_CHECKING / conditional declarations — **M**

- **Root cause [REPORTED]:** engine và oracle chưa cùng declaration universe; exclusion che phần unsupported khỏi recall.
- **Fix:** extractor + `src/sot_graph/holdout/evaluator.py` — policy phân biệt declaration / type-only reference / runtime impact; map function xử lý `If` trước khi sửa.
- **Accept:** không đồng nhất type-only với runtime; absence chỉ áp dụng đúng declared universe.

### P1-3 — Chuẩn hóa path/identity toàn tuyến — **M**

- **Root cause [REPORTED]:** usages trả path absolute/relative; chưa xác định lỗi ở storage hay presentation.
- **Fix:** từ `src/sot_graph/identity_join.py` truy provider ingress → persisted key → usages projection; canonical key gồm root identity + normalized path; display path khác phải có contract.
- **Accept:** không false join/collision; sửa persisted format phải có migration plan.

### P1-4 — Thay tripwire line-bound bằng contract có cấu trúc — **M**

- **Root cause [REPORTED]:** `_ACCOUNTED_LIMITS` (`tests/test_sg107_stress.py:1-40`) phụ thuộc số dòng source.
- **Fix:** collector/cap IDs ổn định + registry mapping nguồn giới hạn → receipt diagnostic tại `assurance/receipts.py`.
- **Accept:** thêm dòng vô hại không vỡ; cap mới chưa account phải fail; cap−1/cap/cap+1, exception/timeout/truncation hiện đúng trên CLI/MCP.

### P1-5 — Làm rõ GT gaps + tính độc lập benchmark — **M**

- **Fix:** `holdout/evaluator.py` công bố measured/unmeasurable/excluded + denominators; jsonschema không thành pass mặc định.
- **Dependency:** universe policy P1-2; oracle attribute-reference mở rộng có thể nâng lên L.

### P1-6 — Retrieval bare-name/qualified-name matching — **M**

- **Root cause [REPORTED]:** BM25/prefix tokens; mismatch `Class.method` vs query bare name; Hit@1 0.79.
- **Fix:** bổ sung identifier components hoặc exact bare-name signal có kiểm soát tại tầng ranker (không sửa ở CLI adapter).
- **Accept:** cải thiện trên held-out queries chưa tuning; không boost mù làm sai ambiguous-name ranking.

### P1-7 — Đồng bộ public claims và diagnostics — **S/M**

- **Fix:** chỉnh `AGENTS.md` ("all calling sites" → "indexed calling sites within reported scope"), đối chiếu README + claim registry; tại `claims.py:377` phân biệt "thiếu object do shallow" với "provenance không hợp lệ".

### P2-1 — Hotspot decomposition theo boundaries — **L**

- Chỉ sau characterization tests; tách adapters/executor/collection/trust-evaluation; giữ public contract + receipt serialization ổn định. Không chia module đồng thời với sửa trust semantics.

### P2-2 — Mở rộng evaluation + release hygiene — **M/L**

- Bổ sung untouched holdout, adversarial identity/truncation fixtures, coverage matrix claim × provider × language; governance/supply-chain ở issue riêng.

## (d) Định hướng issues #8-#10

**Thứ tự khuyến nghị:** P0 CI → chốt identity/universe contracts → **#9 SG-202** → **#8 SG-201** → **#10 SG-205**. #8 có thể làm song song phần filter parsing thuần túy.

| Issue | Outcome và scope đề xuất | Phụ thuộc | Nghiệm thu |
|---|---|---|---|
| #9 SG-202 pack completeness | `src/sot_graph/pack.py`: biểu diễn selection policy, token budget, truncation, coverage gaps, snapshot binding; không tuyên bố graph đầy đủ chỉ vì bundle vừa budget. | Scope/identity contracts; SG-107 accounting. | Budget nhỏ/biên/lớn; seed không mất im lặng; omitted categories có lý do; không suy ra zero callers từ bundle bị cắt. |
| #8 SG-201 repo-map filters | `src/sot_graph/repo_map.py`: filters semantics xác định cho root-relative paths; CLI/MCP dùng chung interpretation. | Canonical path + scope contract. | Cross-root isolation; excludes/includes; deterministic ordering; filter scope được trả lại; không coi "không thấy trong map" là absence. |
| #10 SG-205 receipt explorer | Read-only viewer serialized receipt: claim, scope, generation/snapshot, providers, caps/errors, conflicts, provenance; map receipt-read API trước khi tạo module mới. | Schema compatibility, canonical receipts. | Không recompute rồi trình bày như receipt cũ; không tự reconcile; old/unknown versions có trạng thái rõ. |

**Non-goals:** #9 không mở thành context optimizer tổng quát; #8 không thêm filter dimensions không nhu cầu; #10 không thành quyền tự approve.
**Xem lại thứ tự nếu:** pack đã giữ đầy đủ accounting mà filters gây cross-root leak → #8 lên trước; receipt cũ sai trust semantics → phần compatibility #10 thành P1 correctness.

## Bàn giao

1. **P0:** patch `fetch-depth: 0`, lấy evidence CI xanh trên đúng revision — S.
2. **P1:** traversal fix có ownership tests; chốt declaration universe; xác định tầng gây mixed paths trước khi sửa.
3. **P1:** bỏ line-bound tripwire; công khai benchmark denominators + unmeasurable.
4. **P1:** đồng bộ docs/public claims, rồi tuning retrieval trên tập chưa dùng.

**Kết luận cuối:** root cause CI đủ rõ để hành động ngay; các gap coverage/identity đủ quan trọng để ưu tiên trước feature expansion. Report là đánh giá dựa trên bằng chứng được cung cấp + đếm khai báo độc lập, không phải chứng nhận chất lượng source tại HEAD.
