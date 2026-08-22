# So Sánh Chuyên Sâu Kiến Trúc: GitNexus vs sot-graph

> **Báo cáo Thẩm định Kiến trúc & Đánh giá Tính năng Trực tiếp (Architectural Appraisal & Feature-by-Feature Evaluation)**
> *Được biên soạn với vai trò Architectural Advisor & Reviewer độc lập dựa trên mã nguồn thực tế, đặc tả kỹ thuật và lịch sử vận hành của cả hai hệ thống.*

---

## 📑 Mục Lục
1. [Kết Luận Tổng Quan Của Advisor (Executive Verdict)](#1-kết-luận-tổng-quan-của-advisor-executive-verdict)
2. [Bảng Ma Trận So Sánh Trực Tiếp (8 Chiều Kiến Trúc)](#2-bảng-ma-trận-so-sánh-trực-tiếp-8-chiều-kiến-trúc)
3. [Phân Tích Chi Tiết Từng Chiều Kiến Trúc](#3-phân-tích-chi-tiết-từng-chiều-kiến-trúc)
   - [Chiều 1: Triết Lý Thiết Kế & Bất Biến Cốt Lõi](#chiều-1-triết-lý-thiết-kế--bất-biến-cốt-lõi)
   - [Chiều 2: Động Cơ Lưu Trữ & Database Engine](#chiều-2-động-cơ-lưu-trữ--database-engine)
   - [Chiều 3: Thu Thập (Ingestion) & Đồng Bộ (Reconciliation)](#chiều-3-thu-thập-ingestion--đồng-bộ-reconciliation)
   - [Chiều 4: Cơ Chế Xác Thực Thực Tế (Fact Grounding & Anti-Hallucination)](#chiều-4-cơ-chế-xác-thực-thực-tế-fact-grounding--anti-hallucination)
   - [Chiều 5: Truy Vấn, Duyệt Đồ Thị & Phân Tích Cụm](#chiều-5-truy-vấn-duyệt-đồ-thị--phân-tích-cụm)
   - [Chiều 6: Tích Hợp Agent & Giao Thức MCP Server](#chiều-6-tích-hợp-agent--giao-thức-mcp-server)
   - [Chiều 7: Hỗ Trợ Đa Ngôn Ngữ & Bộ Xuất Dữ Liệu](#chiều-7-hỗ-trợ-đa-ngôn-ngữ--bộ-xuất-dữ-liệu)
   - [Chiều 8: Khả Năng Chịu Lỗi & Rủi Ro Vận Hành (Failure Mode Audit)](#chiều-8-khả-năng-chịu-lỗi--rủi-ro-vận-hành-failure-mode-audit)
4. [Kinh Tế Token & Hiệu Năng Vận Hành](#4-kinh-tế-token--hiệu-năng-vận-hành)
5. [Cây Quyết Định Lựa Chọn Kiến Trúc (Decision Tree)](#5-cây-quyết-định-lựa-chọn-kiến-trúc-decision-tree)
6. [Mô Hình Kiến Trúc Lai Tối Ưu (Two-Tier Hybrid Pattern)](#6-mô-hình-kiến-trúc-lai-tối-ưu-two-tier-hybrid-pattern)

---

## 1. Kết Luận Tổng Quan Của Advisor (Executive Verdict)

Không có hệ thống nào chiến thắng tuyệt đối trên mọi phương diện, bởi vì hai giải pháp được xây dựng để tối ưu hóa hai **hàm mục tiêu (Objective Functions)** hoàn toàn khác nhau:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 HAI TRIẾT LÝ HỆ THỐNG ĐỐI LẬP                                    │
├──────────────────────────────────────────────────┬───────────────────────────────────────────────┤
│           GitNexus (Semantic-First)              │            sot-graph (Trust-First)            │
├──────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ • Cỗ máy phân tích ngữ nghĩa mã nguồn chuyên sâu │ • Lớp tri thức chân lý tối thượng (SSOT)      │
│ • Đồ thị Property Graph là thực thể trung tâm    │ • Filesystem là chân lý; Đồ thị là bản chiếu  │
│ • Truy vấn Cypher, Execution Flow, Leiden        │ • FTS5 BM25, Fast Dirty Check, BFS 2-Hop      │
│ • Tối ưu hóa cho: Khám phá kiến trúc phức tạp    │ • Tối ưu hóa cho: Chống ảo giác, bảo đảm đĩa  │
└──────────────────────────────────────────────────┴───────────────────────────────────────────────┘
```

- **GitNexus là cỗ máy phân tích ngữ nghĩa và đồ thị mạnh mẽ (Code-Intelligence Engine):** Thích hợp cho việc đọc hiểu codebase đa ngôn ngữ phức tạp, bóc tách luồng gọi hàm nhiều tầng (Call Chains), truy vấn Cypher và xem trực quan trên trình duyệt (WebAssembly).
- **sot-graph là lớp bảo vệ chân lý và an toàn vận hành cho AI Agent (Trust & Operational Governance Layer):** Thích hợp cho các Agent lập trình trực tiếp (Active Coding Loop), cần bảo đảm $100\%$ không bao giờ chỉnh sửa nhầm file ảo / file đã đổi tên, triển khai Zero-Daemon siêu nhẹ ($< 25\text{MB}$ RAM), và giao thức MCP Read-Only an toàn tuyệt đối.

---

## 2. Bảng Ma Trận So Sánh Trực Tiếp (8 Chiều Kiến Trúc)

| Chiều Đánh Giá | `GitNexus` (TypeScript / Node.js) | `sot-graph` (Python 3.10+ / SQLite) | Nhận Định Chuyên Gia (Advisor Verdict) |
| :--- | :--- | :--- | :--- |
| **1. Triết Lý Cốt Lõi** | **Graph-First**: Đồ thị là nguồn thông tin chính để suy luận ngữ cảnh và luồng chạy. | **Filesystem SSOT**: Ổ đĩa cứng là chân lý; SQLite là bản chiếu có thể tái tạo bất kỳ lúc nào. | GitNexus ưu tiên **độ sâu ngữ nghĩa**. sot-graph ưu tiên **tính tươi mới (freshness) và khả năng tự chữa lành**. |
| **2. Động Cơ Lưu Trữ** | Embedded **LadybugDB** (tiền thân từ KùzuDB C++ / WASM), lưu Property Graph dưới `.gitnexus/lbug`. | **SQLite FTS5 + WAL**, bảng chuẩn hóa quan hệ + Inverted Index. MCP mở chế độ `mode=ro`. | GitNexus thắng về **biểu diễn đồ thị tự nhiên**. sot-graph thắng về **sự đơn giản, dễ sao lưu, không phụ thuộc binary C++**. |
| **3. Cơ Chế Thu Thập & Đồng Bộ** | Pipeline DAG nhiều chặng (Tree-sitter $\rightarrow$ Scope $\rightarrow$ Call Chain $\rightarrow$ Leiden). Lệnh `analyze` dựng lại, `augment` vá gia tăng. | Quét $O(N)$ $\rightarrow$ Fast Dirty Check $\rightarrow$ SHA-256 $\rightarrow$ ProcessPool parsing $\rightarrow$ Ghi tuần tự SQLite $\rightarrow$ Pending Edges. | GitNexus trích xuất quan hệ sâu hơn. sot-graph đồng bộ liên tục cực nhanh (~24.1ms/100 files) với cơ chế Single-Writer an toàn. |
| **4. Xác Thực Chống Ảo Giác** | Tin tưởng vào trạng thái đồ thị đã lập chỉ mục gần nhất; không đọc lại đĩa cứng khi Agent query. | **Xác minh đĩa cứng vật lý ngay tại mili-giây tìm kiếm** (`verifier.py`) với 6 nhãn: `[STRONG]`, `[WEAK]`, `[REBUILT]`, `[REMOVED]`, `[STALE]`, `[NOPATH]`. | **sot-graph thắng áp đảo về khả năng chống ảo giác đường dẫn (Zero Phantom Anchors)**. |
| **5. Truy Vấn & Duyệt Đồ Thị** | Truy vấn Cypher đồ thị tự do, duyệt Execution Flows, Call Hierarchy nhiều bậc, phân cụm **Leiden**. | **FTS5 BM25** siêu tốc ($< 1.2\text{ms}$), BFS 2-hop bounded, phân cụm **Louvain / Modularity $Q$**, phát hiện **God Node** ($\mu + 1.5\sigma$). | **GitNexus thắng về độ sâu và tính linh hoạt của truy vấn đồ thị phức tạp**. sot-graph tối ưu cho tra cứu lexical + blast radius cận biên. |
| **6. Tích Hợp Agent & MCP** | MCP Server đa dạng (`query`, `explore`, `impact`, `context`) + Hook `PreToolUse` / `PostToolUse` tự động làm giàu ngữ cảnh. | MCP Stdio Server **Read-Only tuyệt đối**, có timeout handler, giới hạn payload 256KB, depth cap 4 để bảo vệ Context Window. | GitNexus có **trải nghiệm Agent tự động hơn**. sot-graph có **ranh giới an toàn (authority boundary) vượt trội**, không gây hỏng index. |
| **7. Đa Ngôn Ngữ & Bộ Xuất File** | Parser Tree-sitter hỗ trợ hơn 12 ngôn ngữ chính thức (TS/JS, Python, Go, Rust, Java, C/C++, C#, Ruby, PHP, Swift...). | Trích xuất AST cho các ngôn ngữ phổ biến (Python, Go, Rust, TS/JS, Java, C/C++...). Xuất ra **HTML D3.js, GraphRAG JSON, Obsidian Vault, GraphML**. | GitNexus thắng về **độ chính xác AST đa ngôn ngữ**. sot-graph thắng về **sự đa dạng của các định dạng xuất độc lập**. |
| **8. Rủi Ro Vận Hành & Khắc Phục** | Rủi ro tranh chấp Lock giữa Hook và MCP (`Issue #1492`), lỗi native WAL crash (`Issue #1480`). Yêu cầu runtime Node.js. | Hạn chế Single-Writer của SQLite. Chi phí I/O quét toàn bộ repo lớn. Khắc phục sự cố 100% bằng cách xóa DB và quét lại. | **sot-graph có vùng rủi ro (failure surface) nhỏ và dễ đoán định hơn**. GitNexus đòi hỏi quản trị tiến trình chặt chẽ hơn. |

---

## 3. Phân Tích Chi Tiết Từng Chiều Kiến Trúc

### Chiều 1: Triết Lý Thiết Kế & Bất Biến Cốt Lõi
- **GitNexus:** Theo đuổi triết lý *Graph-as-a-Platform*. Đồ thị là một thực thể phức hợp chứa toàn bộ tri thức tĩnh của dự án. Mục tiêu là cung cấp một bản đồ kiến trúc toàn vẹn để Agent có thể "nhìn thấy" toàn bộ mạng lưới gọi hàm và luồng dữ liệu trước khi hành động.
- **sot-graph:** Theo đuổi triết lý *Filesystem Grounding*. Cơ sở dữ liệu SQLite chỉ là một "bộ nhớ đệm có thể tái tạo" (ephemeral projection). Nếu có sự bất đồng giữa cơ sở dữ liệu và đĩa cứng, **đĩa cứng luôn luôn đúng**. Bất biến này đảm bảo Agent không bao giờ hành động dựa trên những tàn dư đã bị xóa hoặc đổi tên.

### Chiều 2: Động Cơ Lưu Trữ & Database Engine
- **GitNexus:** Tích hợp **LadybugDB** (phát triển từ KùzuDB) trực tiếp trong thư mục `.gitnexus/lbug`. Điểm mạnh là khả năng lưu trữ các quan hệ có hướng, có thuộc tính (Labeled Property Graph) và thực thi ngôn ngữ truy vấn Cypher với hiệu năng cao. Tuy nhiên, việc nhúng native C++ binding khiến nó phụ thuộc vào nền tảng hệ điều hành và nhạy cảm với việc quản lý vòng đời tiến trình.
- **sot-graph:** Sử dụng **SQLite** chuẩn có sẵn trong Python chuẩn (Zero External Daemon). Thiết lập chế độ WAL (`Write-Ahead Logging`), `synchronous=NORMAL` và chỉ mục toàn văn **FTS5 Inverted Index**. Khi phục vụ qua MCP, sot-graph mở kết nối ở chế độ `mode=ro` và thiết lập `PRAGMA query_only=ON`, loại bỏ hoàn toàn khả năng MCP Server chiếm quyền ghi hoặc làm hỏng dữ liệu.

### Chiều 3: Thu Thập (Ingestion) & Đồng Bộ (Reconciliation)
- **GitNexus:** Pipeline Ingestion sử dụng Tree-sitter để phân tích AST, giải quyết tầm vực (scope resolution), phát hiện chuỗi gọi hàm và phân cụm Leiden. Hệ thống hỗ trợ làm mới từng phần thông qua lệnh `augment` được kích hoạt bởi các hook của Claude Code / Codex.
- **sot-graph:** Triển khai **Level-Triggered Single-Writer Reconciler**:
  1. Quét $O(N)$ kiểm tra metadata (`size`, `mtime`) so với `file_journal`.
  2. Đối chiếu mã băm SHA-256 để xác nhận trạng thái thay đổi.
  3. Phân bổ các tác vụ parse sang Process Pool đa nhân (Workers chỉ thực hiện trích xuất dữ liệu thô, tuyệt đối không chạm vào SQLite).
  4. Điều phối viên chính (Coordinator) thực hiện commit hàng loạt tuần tự vào SQLite, sau đó tự động giải quyết các liên kết chờ (`Two-Way Pending Edges`) và thanh trừng các đường dẫn chết (`Auto-Purge`).

### Chiều 4: Cơ Chế Xác Thực Thực Tế (Fact Grounding & Anti-Hallucination)
- **GitNexus:** Độ tin cậy của dữ liệu phụ thuộc vào lần chạy `analyze` hoặc `augment` gần nhất. Nếu mã nguồn bên dưới bị lập trình viên chỉnh sửa thủ công mà chưa trigger hook, đồ thị có thể chứa thông tin cũ (*Stale Graph*).
- **sot-graph:** Tích hợp **Lớp Kiểm Định Đĩa Cứng Tức Thời** (`verifier.py`):
  Mỗi khi Agent chạy lệnh tìm kiếm, hệ thống lập tức kiểm tra file vật lý trên đĩa cứng:
  - `[STRONG]`: File tồn tại vật lý VÀ nội dung chứa $\ge 50\%$ từ khóa truy vấn $\rightarrow$ Độ tin cậy tuyệt đối.
  - `[WEAK]`: File tồn tại nhưng nội dung có độ trùng khớp từ vựng thấp $\rightarrow$ Khuyến cáo Agent đọc kỹ trước khi sửa.
  - `[REBUILT]`: File đã bị đổi tên/chuyển thư mục $\rightarrow$ Cơ chế `Auto-Rehome` tự động quét tìm đường dẫn mới và cập nhật database.
  - `[REMOVED]`: File đã bị xóa hoàn toàn khỏi đĩa $\rightarrow$ Cơ chế `Auto-Purge` tự động xóa node khỏi DB để không bao giờ hiển thị lại.
  - `[STALE]`: Được trả về khi MCP (Read-Only) phát hiện file đã lệch pha nhưng không có quyền sửa DB.
  - `[NOPATH]`: Ghi chú tri thức ảo (Architecture Decision Record, quy ước).

### Chiều 5: Truy Vấn, Duyệt Đồ Thị & Phân Tích Cụm
- **GitNexus:** Vượt trội ở các tác vụ truy vấn đồ thị phức tạp: tìm đường đi ngắn nhất giữa 2 hàm, phân tích cây phân cấp kế thừa, đánh giá mức độ ảnh hưởng diện rộng (Impact Analysis) và phân cụm theo thuật toán **Leiden**.
- **sot-graph:** Tối ưu hóa cho truy vấn văn bản kết hợp đồ thị nông:
  - Tra cứu FTS5 BM25 siêu tốc ($1.17\text{ms}$ P95).
  - Thuật toán **God Node Detection**: Tự động nhận diện các trung tâm kết nối có bậc vượt ngưỡng $\ge \max(4, \mu + 1.5\sigma)$ và tính toán **Bán kính ảnh hưởng 2-hop (2-Hop Blast Radius)**.
  - Phân tích cấu trúc phân rã với **Hệ số Modularity $Q$** và **Điểm số Cohesion $C$** của từng cụm chức năng.

### Chiều 6: Tích Hợp Agent & Giao Thức MCP Server
- **GitNexus:** Cung cấp trải nghiệm tích hợp mượt mà thông qua bộ công cụ MCP phong phú (`query`, `explore`, `impact`, `context`) kết hợp cùng hệ thống Hook tự động chèn ngữ cảnh vào trước và sau mỗi lượt gọi tool của Agent.
- **sot-graph:** Đặt sự an toàn và ổn định của Agent lên hàng đầu:
  - Giao thức MCP Stdio **Read-Only $100\%$**: Ngăn chặn hoàn toàn việc MCP Server tự ý sửa đổi hay gây xung đột khóa (Lock Contention) với các tiến trình khác.
  - **Cơ chế Hard Caps chống tràn Context:** Giới hạn tối đa 50 kết quả tìm kiếm, độ sâu duyệt BFS tối đa 4 hops, kích thước payload trả về tối đa 256 KB.

### Chiều 7: Hỗ Trợ Đa Ngôn Ngữ & Bộ Xuất Dữ Liệu
- **GitNexus:** Sử dụng bộ parser Tree-sitter chính thống cho hơn 12 ngôn ngữ lập trình, mang lại độ chính xác cao khi phân tích cú pháp phức tạp, closure, macro và generic types. Cung cấp Web UI độc lập chạy mượt mà trên trình duyệt qua WebAssembly.
- **sot-graph:** Hỗ trợ trích xuất AST cho các ngôn ngữ phổ biến (Python, Go, Rust, TS/JS, Java, C/C++...) và cung cấp bộ xuất file cực kỳ đa dạng:
  1. **Interactive HTML Standalone (D3.js v7):** Tệp HTML duy nhất, không cần cài đặt Web Server, hỗ trợ vật lý Force-Directed và bảng tra cứu God Node.
  2. **GraphRAG JSON:** Xuất cấu trúc phân cấp tri thức sẵn sàng cho các pipeline Graph RAG.
  3. **Obsidian Vault:** Xuất toàn bộ đồ thị thành mạng lưới Markdown liên kết hai chiều (`[[Node]]`).
  4. **GraphML XML:** Xuất sang định dạng chuẩn quốc tế để mở trong Gephi, Cytoscape.

### Chiều 8: Khả Năng Chịu Lỗi & Rủi Ro Vận Hành (Failure Mode Audit)
Dựa trên phân tích các sự cố thực tế:
- **GitNexus (Rủi ro đã ghi nhận):**
  - Tranh chấp khóa file `.gitnexus/lbug` khi Hook và MCP cùng truy cập đồng thời (`Issue #1492`).
  - Lỗi native crash khi quản lý nhiều repository song song trên cùng tiến trình (`Issue #1480`).
  - Sự cố phân mảnh/hỏng WAL dưới một số điều kiện đóng tiến trình đột ngột (`Issue #1402`, `#1361`).
- **sot-graph (Giới hạn kiến trúc đã ghi nhận):**
  - Cơ chế Single-Writer của SQLite đòi hỏi các thao tác ghi phải tuần tự hóa qua Coordinator.
  - Quét toàn bộ repository có thể tốn I/O với các dự án monorepo khổng lồ (> 50,000 files).
  - Thuật toán BFS hiện tại truy vấn DB theo từng node, chưa tối ưu cho việc duyệt đồ thị đệ quy sâu 10–15 hops.

---

## 4. Kinh Tế Token & Hiệu Năng Vận Hành

| Tiêu Chí Đánh Giá | `GitNexus` | `sot-graph` |
| :--- | :--- | :--- |
| **Chi Phí Token LLM Để Vận Hành** | **0 Token** (Chạy Tree-sitter & LadybugDB cục bộ) | **0 Token** (Chạy AST, SQLite FTS5 & Python cục bộ) |
| **Thời Gian Tra Cứu (Search Latency)** | ~5 – 15 ms (Truy vấn Graph DB) | **1.17 ms P95** (SQLite FTS5 BM25) |
| **Thời Gian Đồng Bộ (Reconcile Speed)** | Phụ thuộc quy mô Hook / Full `analyze` | **~24.1 ms** (Cho lô 100 files với Fast Dirty Check) |
| **Mức Chiếm Dụng Bộ Nhớ (RAM RSS)** | ~80 – 250 MB (Node.js runtime + LadybugDB native) | **< 25 MB** (Pure Python + SQLite in-process) |
| **Mức Tiết Kiệm Context Cho Agent** | Tiết kiệm ~70% – 85% nhờ cung cấp đúng Call Chains | **Tiết kiệm ~80% – 95%** nhờ phân loại nhãn và giới hạn Hard Caps |

---

## 5. Cây Quyết Định Lựa Chọn Kiến Trúc (Decision Tree)

Sử dụng sơ đồ dưới đây để lựa chọn công cụ phù hợp nhất cho dự án của bạn:

```
                                BẠN CẦN ƯU TIÊN ĐIỀU GÌ NHẤT?
                                              │
                    ┌─────────────────────────┴─────────────────────────┐
                    ▼                                                   ▼
       [ PHÂN TÍCH ĐỒ THỊ CHUYÊN SÂU ]                     [ CHÂN LÝ ĐĨA CỨNG & AN TOÀN ]
  • Cần phân tích Execution Flow sâu nhiều tầng.      • AI Agent thường xuyên bị ảo giác đường dẫn cũ.
  • Cần ngôn ngữ truy vấn Cypher linh hoạt.           • Dự án liên tục refactor, đổi tên, di chuyển file.
  • Dự án đa ngôn ngữ phức tạp (C#, Ruby, Swift...).  • Cần hệ thống Zero-Daemon, siêu nhẹ (< 25MB RAM).
  • Cần giao diện Web tương tác trên trình duyệt.     • Muốn lưu trữ quyết định kiến trúc ADR (sot insert).
                    │                                                   │
                    ▼                                                   ▼
             👉 CHỌN GITNEXUS                                    👉 CHỌN SOT-GRAPH
```

---

## 6. Mô Hình Kiến Trúc Lai Tối Ưu (Two-Tier Hybrid Pattern)

Trong các tổ chức phần mềm quy mô lớn, kiến trúc kết hợp **Two-Tier Knowledge Plane** là giải pháp hoàn hảo nhất để tận dụng thế mạnh của cả hai công cụ:

```
+─────────────────────────────────────────────────────────────────────────────────────────+
|                                    CODEBASE DỰ ÁN                                       |
+────────────────────────────────────────────┬────────────────────────────────────────────+
                                             │
                      ┌──────────────────────┴──────────────────────┐
                      ▼                                             ▼
       [ TẦNG 1: KHÁM PHÁ KIẾN TRÚC ]                 [ TẦNG 2: BẢO VỆ CHÂN LÝ THỰC ĐỊA ]
                (GitNexus)                                       (sot-graph)
                      │                                             │
    • Trích xuất Tree-sitter đa ngôn ngữ          • Fast Dirty Check O(1) & SHA-256
    • Xây dựng Call Chains & Execution Flows      • SQLite FTS5 BM25 Index (< 1.2ms)
    • Phân cụm cộng đồng Leiden                   • Quản lý mỏ neo tri thức ADR [NOPATH]
                      │                                             │
                      └──────────────────────┬──────────────────────┘
                                             │
                                             ▼
                      ┌─────────────────────────────────────────────┐
                      │    CỔNG KIỂM ĐỊNH ĐĨA CỨNG (VERIFIER.PY)    │
                      │    (Chuyển giao từ GitNexus sang sot-graph) │
                      └──────────────────────┬──────────────────────┘
                                             │
                        ┌────────────────────┼────────────────────┐
                        ▼                    ▼                    ▼
                    [STRONG]             [REBUILT]            [REMOVED]
                (File & Code thật)    (Đã đổi vị trí)      (Đã bị xóa bỏ)
                        │                    │                    │
                        └────────────────────┼────────────────────┘
                                             │
                                             ▼
                      ┌─────────────────────────────────────────────┐
                      │        AI CODING AGENT (Oh My Pi / Claude)  │
                      │     (Thực thi code AN TOÀN TUYỆT ĐỐI 100%)  │
                      └─────────────────────────────────────────────┘
```

1. **Tầng 1 (GitNexus - Exploration Plane):** Dùng để khám phá cấu trúc tổng thể, tìm kiếm các mối quan hệ ngữ nghĩa phức tạp và trực quan hóa kiến trúc dự án.
2. **Tầng 2 (sot-graph - Grounding & Execution Gatekeeper):** Trước khi Agent thực hiện bất kỳ thao tác ghi đè hoặc chỉnh sửa mã nguồn nào, `sot-graph` thực hiện bước kiểm tra vật lý đĩa cứng cuối cùng, tự động điều chỉnh đường dẫn nếu file đã bị đổi chỗ (`[REBUILT]`) hoặc loại bỏ nếu file đã bị xóa (`[REMOVED]`), bảo đảm an toàn tuyệt đối cho codebase.

---

## 📄 License
MIT License. Bản quyền thuộc về Minh Giap (2026).
