# Báo cáo tái đánh giá chuyên sâu SOT-Graph

**Dự án:** https://github.com/minhgv/sot-graph  
**Phiên bản được đánh giá:** commit 10e2953acfdaf329d72b467bd6e6ac746b88b04c  
**Mốc so sánh trước cập nhật:** 870f27f7333724318bab8fd69ce265bf0e63b60e  
**Ngày đánh giá:** 2026-08-23  
**Phạm vi:** độ chính xác khi hỗ trợ viết/sửa code, vai trò “la bàn” cho agent và người dùng, độ tin cậy dữ liệu, trải nghiệm truy vấn, hiệu năng, test và mức sẵn sàng sản xuất.

## 1. Kết luận điều hành

SOT-Graph đã tiến một bước rõ rệt từ một chỉ mục đồ thị thử nghiệm thành một **lớp điều hướng code có bằng chứng**. Bản cập nhật mới cải thiện đáng kể usability: mô hình Trust Evidence năm chiều, usages có trạng thái resolved/unresolved, explore thể hiện đường đi, pack tiết kiệm context lớn, health check tốt hơn, và bộ test tăng lên 239 test.

Tuy nhiên, dự án **chưa nên được coi là semantic source of truth** cho refactor tự động hoặc quyết định thay đổi code có rủi ro cao. Hai lỗi P0 đã tái hiện được:

1. Freshness không so sánh hash hiện tại với hash lúc index, khiến symbol đã lỗi thời vẫn có thể được báo FRESH, thậm chí STRONG với confidence 1.0.
2. Resolver có thể biến import alias thành call nội bộ sai khi tên đích trùng với symbol local, tạo cạnh giả và self-loop giả.

Vì vậy, định vị đúng ở thời điểm hiện tại là:

> **SOT-Graph là “verified navigation layer” mạnh cho agent: rất hữu ích để tìm nơi cần đọc, gom context và giải thích quan hệ; chưa đủ an toàn để một mình quyết định nơi cần sửa hoặc thực hiện refactor diện rộng.**

### Khuyến nghị sử dụng ngay

- Dùng cho search, repo map, explore, pack và triage kiến trúc.
- Dùng usages như tập ứng viên, sau đó xác nhận bằng AST/LSP hoặc đọc source trước khi sửa.
- Không dùng verdict STRONG hiện tại làm điều kiện duy nhất để agent tự động sửa code.
- Không bật auto-heal trong đường đọc/search; repair phải là thao tác tường minh.
- Chặn phát hành ổn định cho đến khi hoàn thành hai lỗi P0 về freshness và alias resolution.

## 2. Điểm số

| Hạng mục | Điểm /10 | Nhận xét |
|---|---:|---|
| Thiết kế mô hình evidence | 8.0 | Năm chiều tách bạch tốt hơn verdict đơn |
| Hiện thực trust/freshness | 5.5 | Ý tưởng tốt nhưng freshness và exact-span đang overclaim |
| Call graph và usages | 6.0 | Hữu ích, song còn false edge, duplicate attribution và nhiều pending |
| Vai trò “la bàn” | 8.0 | Search → explore → pack là workflow có giá trị thực |
| Context pack | 8.0 | Tiết kiệm 79.8–88.7% trong ba ca đo; hard budget chưa đúng |
| Integrity và test | 7.0 | 239 test, coverage 77%, WAL/quick_check tốt; benchmark accuracy còn yếu |
| Mức sẵn sàng sản xuất | 5.0 | Thiếu CI/release discipline, semantics chưa đủ chặt |
| **Tổng thể như advisory compass** | **7.5** | Dùng tốt khi agent biết kiểm chứng |
| **Làm nền duy nhất cho refactor tự động** | **5.0** | Chưa đạt |

## 3. Phương pháp và bằng chứng

Đánh giá được thực hiện bằng bốn lớp:

1. Đọc diff giữa hai commit và rà soát các luồng verifier, extractor, resolver, database, pack, MCP/CLI.
2. Chạy toàn bộ test và coverage trong môi trường sạch.
3. Ép dự án tự index chính nó, kiểm tra graph statistics và truy vấn các symbol quan trọng.
4. Viết các fixture tối thiểu để chủ động tìm phản ví dụ cho freshness, import alias và ownership của call site.

### 3.1 Kết quả test

| Kiểm tra | Kết quả |
|---|---|
| pytest | 239 passed, 10 warnings, 27.65 giây |
| coverage | 239 passed, tổng 77% |
| database quick_check | ok |
| chạy lại với .sot có sẵn | 2 lần đều pass |
| root test discovery | đã được sửa bằng testpaths = ["tests"] |

Coverage đáng chú ý:

| Module | Coverage |
|---|---:|
| evidence.py | 94% |
| repo_map.py | 91% |
| db.py | 86% |
| pack.py | 84% |
| verifier.py | 78% |
| mcp_service.py | 78% |
| reconciler.py | 65% |
| cli.py | 54% |
| watcher.py | 46% |

Nhận xét: coverage tổng thể đủ tốt cho beta, nhưng những vùng có rủi ro vận hành cao như watcher, CLI orchestration và reconciler vẫn thấp.

### 3.2 Tự index SOT-Graph

| Chỉ số | Kết quả |
|---|---:|
| Files | 118 |
| Thời gian reconcile nội bộ | 2.01 giây |
| Nodes | 1,087 |
| Confirmed edges | 2,608 |
| Pending edges | 2,245 |
| Confirmed calls | 1,235 |
| Pending calls | 2,184 |
| Pending calls ambiguous | 124 |
| Pending calls unresolved | 2,060 |

Tỷ lệ resolve candidate call tăng từ khoảng **28.5% lên 36.1%** so với mốc trước. Đây là cải thiện thật, nhưng khoảng 64% call candidate vẫn chưa được xác nhận; do đó graph hiện là đồ thị có độ phủ tốt cho điều hướng, chưa phải đồ thị semantic đầy đủ.

### 3.3 Hiệu quả context

| Target | Pack tokens | Naive tokens | Tiết kiệm |
|---|---:|---:|---:|
| Database.commit_file_batch | 1,725 | 15,220 | 88.7% |
| build_bundle | 5,009 | 41,944 | 88.1% |
| parse_file_graph | 4,964 | 24,589 | 79.8% |

Đây là điểm mạnh nổi bật nhất của dự án: SOT-Graph giúp agent đọc **đúng vùng code có liên quan** thay vì bơm cả repository vào context.

### 3.4 Hiệu năng

- Query trên fixture 100 file: median 2.647 ms, p95 2.841 ms, kiểm tra correctness pass.
- Reconcile 100 file nhỏ, 1 worker: median 61.1 ms, p95 78.8 ms.
- Reconcile 100 file nhỏ, 4 worker: median 293.5 ms, p95 314.4 ms.

Với workload file nhỏ, process overhead làm 4 worker chậm hơn gần 4.8 lần. Dự án cần ngưỡng tự động hoặc batching thay vì mặc định cho rằng nhiều worker luôn nhanh hơn.

## 4. Những cải thiện đã được xác nhận

### 4.1 Trust Evidence v2 đúng hướng

Mô hình mới tách evidence thành:

- freshness;
- relevance;
- resolution;
- completeness;
- confidence.

Điểm mạnh là agent có thể thấy **vì sao** một kết quả đáng tin hoặc không đáng tin, thay vì chỉ nhận một nhãn STRONG/WEAK. Đây là nền tảng tốt để chuyển từ “tool trả kết quả” sang “tool trình bày mức hiểu biết và giới hạn”.

### 4.2 Luồng đọc đã ít side effect hơn

CLI và MCP search truyền auto_heal = false. Đây là thay đổi quan trọng: truy vấn đọc không nên âm thầm sửa index. Public verify_hit vẫn mặc định auto_heal = true, nên ranh giới này chưa được khóa hoàn toàn.

### 4.3 Usages và explore hữu ích hơn cho agent

- usages hiển thị resolved/unresolved, status và next steps.
- explore có hop, depth, via và tóm tắt 1-hop/2-hop.
- Doctor cho biết schema v4, WAL, quick_check, thống kê pending.

Các cải tiến này biến graph thành một bản đồ có chỉ dẫn thay vì chỉ là danh sách node/edge.

### 4.4 Pack có giá trị thực

Pack kiểm tra hash của target và neighbor, có repo-map và language breakdown, đồng thời cho mức giảm context rất lớn trong benchmark thực tế trên chính repo. Với coding agent, đây là lợi thế khác biệt: không chỉ tìm symbol mà còn đóng gói “vùng bằng chứng” để hành động.

### 4.5 Storage tốt hơn

Bộ test mới bao gồm 100 vòng incremental reconcile và reader/writer bằng thread. Hai lần chạy với index đã tồn tại không tái hiện database malformed trước đây. Dù vậy, chưa có crash simulation thật ở ranh giới process/kill -9/fsync.

## 5. Lỗi và giới hạn quan trọng

## 5.1 P0 — Freshness có thể báo sai

### Phản ví dụ đã tái hiện

1. Index file chứa hàm alpha.
2. Sửa file thành hàm beta nhưng không reconcile.
3. Verify symbol alpha cũ.

Kết quả vẫn có thể là FRESH vì verifier hash file hiện tại nhưng không đối chiếu với file_journal.sha256.

Ca nghiêm trọng hơn:

1. Sau khi index alpha, đổi file thành comment “alpha was removed” và hàm beta.
2. Verify hit alpha cũ.
3. Hệ thống trả FRESH, EXACT_SPAN, confidence 1.0 và legacy STRONG.

Nguyên nhân là token alpha xuất hiện trong cửa sổ dòng quanh vị trí cũ, dù declaration đã biến mất. Vì vậy, “physically verified” hiện không đồng nghĩa với symbol còn tồn tại.

### Tác động

- Agent có thể sửa nhầm code dựa trên symbol đã stale.
- STRONG trở thành nhãn nguy hiểm vì mức chắc chắn hiển thị cao hơn bằng chứng thật.
- Search relevance bị trộn với existence verification.

## 5.2 P0 — Import alias có thể tạo false edge

Fixture tối thiểu:

    # a_caller.py
    def main():
        from z_target import main as target_main
        return target_main()

    # z_target.py
    def main():
        return 42

Graph hiện có thể gắn call target_main() vào a_caller.main, tạo self-loop sai, thay vì z_target.main. Lỗi đã xuất hiện trên repo thật ở src/sot_graph/cli.py: call qua alias mcp_main bị gắn thành cli.main → cli.main.

Root cause nằm ngay ở extraction: alias được chuẩn hóa về tên main rồi bị local-symbol resolution bắt trước khi cross-file resolver xử lý.

### Tác động

- usages có false positive.
- impact analysis và refactor plan có thể đi sai hướng.
- self-loop giả làm méo ranking và graph traversal.

## 5.3 P0 — Nested function bị double attribution

_handle_func dùng ast.walk trên function node nên đi xuyên vào function lồng nhau; sau đó generic_visit lại xử lý nested function một lần nữa. Một physical call site trong hàm op có thể bị gắn cho cả outer method và op.

Ví dụ thực tế: cùng call site trong MCP service được đếm cho cả McpService.search và nested op. Vì thế usages của TrustVerifier.verify_hit báo 11 site trong khi text search tìm thấy 10 physical call site.

## 5.4 P0 — Completeness đang overclaim

Database.usages đánh dấu COMPLETE khi không tìm thấy pending edge có exact/bare-name match. Điều này chỉ chứng minh “không còn gap mà extractor hiện biết”, không chứng minh extractor đã nhìn thấy mọi call.

Các call động, alias chưa hỗ trợ, receiver không suy ra được hoặc cú pháp ngoài capability có thể biến mất hoàn toàn mà không tạo pending record.

Tên an toàn hơn:

- NO_KNOWN_GAPS; hoặc
- COMPLETE_WITHIN_INDEX_CAPABILITY.

## 5.5 P0 — Accuracy benchmark chưa đo semantic accuracy

Benchmark hiện báo precision/recall/F1 100%, nhưng corpus chỉ có 6 cạnh dương synthetic do chính script tạo. Không có negative case, real-repo ground truth hoặc đối chiếu LSP/SCIP. Nó không bắt được alias self-loop và nested duplicate ở trên.

Tham số --corpus-dir cũng đang sinh/ghi corpus vào thư mục được cấp thay vì đọc một manifest ground truth độc lập.

Kết luận: con số 100% hiện chỉ là **smoke-test regression**, không phải bằng chứng accuracy.

## 5.6 P1 — Hard token budget chưa phải hard

Khi yêu cầu pack rất nhỏ:

| max_tokens | Tokens thực tế | Vượt |
|---:|---:|---:|
| 100 | 377 | +277 |
| 250 | 413 | +163 |
| 500 | 472 | không vượt |
| 1,000 | 996 | không vượt |
| 2,000 | 1,983 | không vượt |

Với budget 100 hoặc 250, framing tối thiểu đã lớn hơn cap nhưng API vẫn trả bundle vượt mức. Tokenizer hiện là fallback; nhận định sai số không quá 5% chưa có benchmark chứng minh.

## 5.7 P1 — Rehome chưa dựa trên content hash

Database có rehome_file_atomically, nhưng discovery vẫn dùng find_rehome theo basename. Hai file cùng basename hoặc move kèm rename có thể không được tìm đúng. Test atomic dùng ID theo path, chưa mô phỏng hoàn toàn production ID dạng hash.

## 5.8 P1 — Trust boundary của AGENTS.md chưa an toàn

Pack đang nạp AGENTS.md trong repo như nội dung trusted. Với repo bên ngoài hoặc repo không kiểm soát, đây là điểm prompt-injection. Nội dung trong repository nên mặc định là untrusted; caller/host mới có quyền nâng trust.

## 5.9 P1 — Docs và release metadata chưa đồng bộ

- Commit mô tả roadmap v0.2.0 nhưng pyproject.toml và src/sot_graph/__init__.py vẫn là 0.1.0.
- Chưa có tag/release và chưa có workflow CI.
- AGENTS.md và WORKFLOW_GUIDELINES còn ngôn ngữ như “100% reliable anchor”.
- README vẫn thiên về verdict legacy, không diễn giải giới hạn Evidence v2.

Đây không chỉ là lỗi tài liệu: agent sẽ dùng chính các hướng dẫn này để quyết định mức tin cậy.

## 6. Vai trò “la bàn” cho agent và người dùng

### 6.1 SOT-Graph đang làm tốt điều gì?

Workflow có giá trị nhất là:

    câu hỏi
      → search để tìm điểm vào
      → verify để thấy trạng thái evidence
      → explore để hiểu lân cận và đường đi
      → usages để lập danh sách tác động
      → pack để cung cấp context có giới hạn cho agent
      → đọc source/test trước khi sửa

Nó giúp trả lời nhanh:

- “Nên bắt đầu đọc ở đâu?”
- “Symbol này liên quan tới module nào?”
- “Vùng context nhỏ nhất đủ để hiểu thay đổi là gì?”
- “Cạnh nào xác nhận được, cạnh nào còn pending?”

### 6.2 SOT-Graph chưa nên quyết định điều gì?

- “Đây là toàn bộ call site cần sửa.”
- “Symbol chắc chắn còn fresh chỉ vì verdict là STRONG.”
- “Có thể rename/refactor tự động mà không dùng LSP/AST verification.”
- “Không có pending nghĩa là graph đầy đủ.”

### 6.3 Mô hình sử dụng an toàn

| Loại tác vụ | Có thể dùng SOT-Graph một mình? | Hành động bổ sung |
|---|---|---|
| Tìm entry point, đọc kiến trúc | Có, với caveat | Mở source ở target |
| Gom context cho agent | Có | Kiểm tra budget và trust boundary |
| Lập impact hypothesis | Có | Xác minh usages bằng AST/LSP/rg |
| Sửa một call site đơn giản | Không hoàn toàn | Chạy test và đọc call site |
| Rename/refactor cross-file | Không | Dùng LSP/SCIP/compiler + tests |
| Security/data-flow analysis | Không | Dùng CodeQL/Joern hoặc analyzer chuyên dụng |

## 7. So sánh định vị với công cụ tương tự

So sánh này tập trung vào kiến trúc và vai trò, không coi các công cụ là thay thế 1:1.

| Công cụ/lớp | Nguồn semantic | Điểm mạnh hơn SOT-Graph | Điểm SOT-Graph nổi bật hơn |
|---|---|---|---|
| SCIP/Sourcegraph | Indexer theo ngôn ngữ, symbol occurrence chuẩn hóa | Definition/reference chính xác hơn; hệ sinh thái đa ngôn ngữ | Evidence UX, pending transparency và agent-oriented pack gọn |
| Serena/LSP | Language server hoặc IDE backend | Semantic navigation/refactor chín hơn, hỗ trợ rộng | Local graph snapshot, explicit trust/evidence model, bundle tùy biến |
| Aider repo map | Tree-sitter + graph ranking + token budget | Repo-map battle-tested và tích hợp trực tiếp coding loop | Quan hệ usages/explore chi tiết, evidence và health/integrity rõ hơn |
| Joern CPG | AST + control flow + data flow trong property graph | Truy vấn phân tích chương trình và security sâu hơn | Nhẹ hơn, local-first, dễ dùng như MCP compass |
| CodeQL | Database semantic và query packs | Vulnerability/data-flow analysis, ecosystem và CI maturity | Setup nhẹ, latency tương tác thấp, phù hợp context navigation |
| Text/RAG search | Lexical/vector retrieval | Bao phủ prose và ý nghĩa mơ hồ tốt | Có cấu trúc symbol/edge, provenance và trạng thái unresolved |

### Nhận xét định vị

SOT-Graph không nên cố thắng CodeQL/Joern ở static analysis sâu hoặc thắng LSP/SCIP ở semantic resolution thuần túy. Khoảng trống tốt nhất là:

> **Lớp orchestration nhẹ, local-first, evidence-aware nằm giữa text search và semantic indexer, chuyên biến graph thành context có thể hành động cho coding agent.**

Chiến lược mạnh là cho phép SCIP/LSP trở thành nguồn cạnh cấp EXACT, còn extractor nội bộ tiếp tục cung cấp fallback nhanh và đa ngôn ngữ. Khi đó SOT-Graph trở thành lớp hợp nhất evidence thay vì phải tự tái tạo mọi compiler frontend.

Nguồn tham chiếu kiến trúc:

- [SCIP Code Intelligence Protocol](https://github.com/scip-code/scip)
- [Serena – semantic retrieval/editing over MCP](https://github.com/oraios/serena)
- [Aider repository map](https://aider.chat/docs/repomap.html)
- [Joern Code Property Graph](https://docs.joern.io/code-property-graph/)
- [GitHub CodeQL concepts](https://docs.github.com/en/code-security/concepts/code-scanning/codeql)

## 8. Điểm mạnh

1. **Product thesis tốt:** graph không chỉ để hiển thị mà phục vụ quyết định context cho agent.
2. **Evidence model có tiềm năng khác biệt:** tách freshness, relevance, resolution và completeness là đúng hướng.
3. **Transparency tốt hơn đa số wrapper search:** confirmed/pending và next steps được phơi bày.
4. **Context compression hiệu quả:** giảm 79.8–88.7% trên ba target thực.
5. **Local-first và MCP-friendly:** phù hợp coding agent, ít phụ thuộc dịch vụ ngoài.
6. **Test suite tăng nhanh:** 239 test, coverage 77%, có storage/incremental/concurrency cases.
7. **Doctor và integrity checks hữu ích:** WAL, schema, quick_check và thống kê graph dễ chẩn đoán.
8. **Kiến trúc mở:** có chỗ để nhận adapter, SCIP export, tree-sitter và source evidence khác.

## 9. Điểm yếu

1. **Semantics đang hứa nhiều hơn bằng chứng:** FRESH/EXACT_SPAN/COMPLETE có thể sai.
2. **Resolver chưa đủ an toàn:** alias collision và nested-scope attribution tạo false positive xác nhận.
3. **Accuracy benchmark không đại diện:** 100% trên 6 synthetic edge gây cảm giác chắc chắn giả.
4. **Hard budget không hard:** bundle có thể vượt cap lớn ở budget nhỏ.
5. **Trust boundary chưa chặt:** repo instructions được nâng thành trusted.
6. **Rehome/auto-heal chưa đạt invariant:** lookup theo basename và public read path còn mutation mặc định.
7. **Parallelism chưa thích nghi workload:** nhiều worker chậm hơn rõ với file nhỏ.
8. **Release engineering còn non trẻ:** thiếu CI/tag/version alignment và tài liệu vẫn dùng claim tuyệt đối.
9. **Độ phủ resolver còn thấp:** phần lớn pending call chưa được giải quyết.
10. **Bus factor cao:** repo mới và tập trung vào một maintainer chính.

## 10. Quyết định đề xuất

### Có nên tiếp tục đầu tư?

**Có.** Giá trị cốt lõi đã được chứng minh ở navigation, context compression và agent UX.

### Có nên phát hành stable ngay?

**Chưa.** Nên phát hành dạng 0.2.0-rc hoặc beta cho đến khi đóng các gate:

- hash-based freshness;
- alias-resolution regression;
- nested-call ownership;
- completeness wording;
- benchmark accuracy v2;
- CI và tài liệu trust semantics.

### North-star

“Mỗi kết quả không chỉ chỉ đường, mà còn nói rõ nó dựa trên bằng chứng nào, còn thiếu gì và agent phải xác minh bước nào trước khi sửa.”

Kế hoạch thực thi chi tiết nằm trong tài liệu **sot-graph-bug-fix-plan.md**.
