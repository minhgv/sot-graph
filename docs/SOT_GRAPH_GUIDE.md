# Cẩm Nang Toàn Diện SOT-Graph: MCP Tools & CLI

> **Single Source of Truth (SOT) Verified Knowledge Graph cho AI Coding Agents và Phần Mềm Doanh Nghiệp**  
> *Tài liệu hướng dẫn chuyên sâu về kiến trúc, cơ chế hoạt động, chi tiết toàn bộ 21+ MCP Tools và hệ thống câu lệnh CLI của SOT-Graph.*

---

## MỤC LỤC
1. [Tổng Quan về SOT-Graph](#1-tổng-quan-về-sot-graph)
2. [Mô Hình Bằng Chứng & Hệ Nhãn Niềm Tin (Trust Model)](#2-mô-hình-bằng-chứng--hệ-nhãn-niềm-tin-trust-model)
3. [Chi Tiết 21+ MCP Tools (Dành Cho AI Coding Agents)](#3-chi-tiết-21-mcp-tools-dành-cho-ai-coding-agents)
   - [Nhóm 1: Định vị & Tìm Kiếm Tri Thức](#nhóm-1-định-vị--tìm-kiếm-tri-thức)
   - [Nhóm 2: Khảo Sát AST & Mối Quan Hệ Mã Nguồn](#nhóm-2-khảo-sát-ast--mối-quan-hệ-mã-nguồn)
   - [Nhóm 3: Phân Tích Kiến Trúc, Cụm Module & Fact Bundler](#nhóm-3-phân-tích-kiến-trúc-cụm-module--fact-bundler)
   - [Nhóm 4: Reverse Engineering & Động Cơ Solution (ITPRO / Manpower)](#nhóm-4-reverse-engineering--động-cơ-solution-itpro--manpower)
   - [Nhóm 5: Git Diff Impact, Assurance Receipts & Lịch Sử Commit](#nhóm-5-git-diff-impact-assurance-receipts--lịch-sử-commit)
   - [Nhóm 6: Đồng Bộ External Provider](#nhóm-6-đồng-bộ-external-provider)
   - [Tài Nguyên MCP (Resources, Templates & Subscriptions)](#tài-nguyên-mcp-resources-templates--subscriptions)
4. [Chi Tiết Hệ Thống Câu Lệnh CLI](#4-chi-tiết-hệ-thống-câu-lệnh-cli)
   - [Nhóm Lệnh Vòng Đời & Đồng Bộ CSDL](#nhóm-lệnh-vòng-đời--đồng-bộ-csdl)
   - [Nhóm Lệnh Truy Vấn, Tìm Kiếm & Bản Đồ Mã Nguồn](#nhóm-lệnh-truy-vấn-tìm-kiếm--bản-đồ-mã-nguồn)
   - [Nhóm Lệnh Báo Cáo Kiến Trúc & Trực Quan Hóa Đồ Thị](#nhóm-lệnh-báo-cáo-kiến-trúc--trực-quan-hóa-đồ-thị)
   - [Nhóm Lệnh Động Cơ Solution & Trace Full-Stack](#nhóm-lệnh-động-cơ-solution--trace-full-stack)
   - [Nhóm Lệnh Phân Tích Tác Động Thay Đổi (Diff Impact & Git)](#nhóm-lệnh-phân-tích-tác-động-thay-đổi-diff-impact--git)
   - [Nhóm Lệnh Multi-Provider & Trình Nhập SCIP](#nhóm-lệnh-multi-provider--trình-nhập-scip)
   - [Nhóm Lệnh Bảo Trì CSDL & Thiết Lập Harness](#nhóm-lệnh-bảo-trì-csdl--thiết-lập-harness)
5. [Bảng Đối Chiếu So Sánh: MCP Tools vs. CLI Commands](#5-bảng-đối-chiếu-so-sánh-mcp-tools-vs-cli-commands)
6. [4 Kịch Bản Vận Hành Thực Chiến (Real-World Workflows)](#6-4-kịch-bản-vận-hành-thực-chiến-real-world-workflows)

---

## 1. Tổng Quan về SOT-Graph

### 1.1. Vấn đề cốt lõi mà SOT-Graph giải quyết
Trong quá trình hỗ trợ lập trình của AI Agents (Claude Code, OpenCode, Antigravity, Pi/OMP, Cursor), hai vấn đề lớn nhất thường trực xảy ra:
1. **Lãng phí Token & Suy giảm Ngữ cảnh (Context Exhaustion):** Đọc tuần tự hàng chục file mã nguồn lớn (`>100 dòng`) chỉ để tìm vị trí một hàm hoặc hiểu mối quan hệ giữa Controller và Model.
2. **Ảo tưởng Mã nguồn (Hallucination):** Agent tự suy diễn ra các hàm, route, tham số hoặc cấu trúc bảng không có thật trên đĩa, hoặc sử dụng các symbol đã bị xóa/đổi tên trước đó.

### 1.2. Triết lý Thiết kế của SOT-Graph
* **Zero-Daemon SQLite Storage:** Toàn bộ đồ thị tri thức mã nguồn được lưu trữ tại file SQLite cục bộ `.sot/sot.db` (chạy chế độ WAL, tối ưu hóa multi-process locking), không yêu cầu background daemon cồng kềnh, không phụ thuộc vào hạ tầng bên ngoài.
* **AST Graph-First (Trích xuất Cây Cú pháp Trừu tượng):** Phân tích tĩnh đa ngôn ngữ (PHP, TypeScript/JavaScript, Python, Dart/Flutter, Java, C#, Go, Rust, v.v.) thành các Node (File, Class, Method, Function, Route, Entity) và Edges (Calls, Implements, Extends, Imports, Uses).
* **Zero-Token Ingestion Protocol:** Tra cứu cấu trúc dự án trong `0.1s` thông qua đồ thị thay vì ném hàng ngàn dòng code vào context window.
* **Self-Healing & JIT Micro-Reconciliation:** Tự động phát hiện thay đổi trên đĩa và cập nhật đồ thị tức thời theo từng file bị sửa đổi trước khi thực thi truy vấn.
* **Giao thức Bảo đảm P7 (Assurance Receipts):** Cung cấp biên lai phạm vi trước khi sửa (`scope_receipt`) và biên lai tác động sau khi sửa (`diff_impact_receipt`) để đảm bảo không phá vỡ hợp đồng API hay gây lỗi hồi quy.

---

## 2. Mô Hình Bằng Chứng & Hệ Nhãn Niềm Tin (Trust Model)

Mọi symbol/kết quả do SOT-Graph trả về đều được đối soát vật lý với đĩa cứng tại thời điểm truy vấn và gán một **Trust Verdict**:

| Nhãn Niềm Tin | Ý nghĩa Chi Tiết | Hành Động Khuyến Nghị Của Agent |
| :--- | :--- | :--- |
| `[STRONG]` | **Xác thực vật lý trên đĩa (span-verified):** File tồn tại, symbol tồn tại chính xác tại vị trí khai báo, nội dung hash trùng khớp. | Độ tin cậy cao cho điều hướng/tái sử dụng; vẫn nên đọc snippet — không phải bảo đảm về ngữ nghĩa hay tính đầy đủ. |
| `[WEAK]` | **Khớp ngữ nghĩa / Khớp một phần:** Tìm thấy tên hàm nhưng độ bao phủ token (coverage) chưa đạt ngưỡng hoặc chỉ khớp trong comment/chuỗi. | Phải đọc lại phạm vi dòng (`range selector: file:start-end`) trước khi gọi. |
| `[REBUILT]` | **Tệp đã được di chuyển:** File đã bị đổi tên hoặc chuyển thư mục nhưng bộ reconciler đã tìm thấy và tự động ánh xạ lại đường dẫn mới. | Cập nhật lại đường dẫn import sang path mới được báo cáo. |
| `[REMOVED]` | **Tệp/Symbol đã bị xóa trên đĩa:** Node từng tồn tại trong CSDL nhưng hiện tại không còn trên đĩa. | **TUYỆT ĐỐI KHÔNG** tham chiếu hoặc sinh code gọi symbol này. |
| `[NOPATH]` | **Node ảo / Inline node:** Symbol không gắn liền trực tiếp với một file vật lý độc lập (hằng số hệ thống, dynamic hook). | Kiểm tra lại ngữ cảnh runtime. |

### Cơ chế Multi-Provider Evidence
SOT-Graph tích hợp cơ chế bằng chứng đa nguồn:
1. **Builtin Extractor:** Phân tích AST qua Tree-sitter & biểu thức chính quy tối ưu hóa cao.
2. **SCIP Evidence:** Nạp dữ liệu từ compiler thực thụ (`scip-typescript`, `scip-python`, `scip-java`, `rust-analyzer`).
3. **Codebase-Memory / External Providers:** Tích hợp với các engine semantic bên ngoài.

---

## 3. Chi Tiết 21+ MCP Tools (Dành Cho AI Coding Agents)

Giao diện Model Context Protocol (MCP) của SOT-Graph tuân thủ chuẩn **MCP 2025-06-18**, hỗ trợ `outputSchema` có cấu trúc và `ResourceLink` (`sot://node/{id}`) cho phép lazy-fetching dữ liệu chi tiết của từng Node mà không làm tràn context.

---

### Nhóm 1: Định vị & Tìm Kiếm Tri Thức

#### 1. `sot-graph_sot_search`
* **Mô tả:** Tìm kiếm đồ thị tri thức có xác thực niềm tin (`[STRONG]`, `[WEAK]`, v.v.). Trả về danh sách nodes kèm điểm xếp hạng, metadata và các liên kết `sot://node/{id}` để lazy-fetch khi cần.
* **Tham số (Parameters):**
  * `query` *(string, bắt buộc)*: Chuỗi tìm kiếm (tên hàm, tên class, route, biến, hoặc từ khóa nghiệp vụ).
  * `limit` *(integer, tùy chọn, mặc định: 6)*: Số lượng kết quả tối đa trả về.
  * `scope` *(string, tùy chọn)*: Giới hạn tìm kiếm trong thư mục hoặc file cụ thể (VD: `Modules/Api`).
  * `threshold` *(number, 0-1, mặc định: 0.5)*: Ngưỡng coverage tối thiểu để đạt nhãn `[STRONG]`.
  * `assurance` *(boolean, mặc định: true)*: Bật/tắt kiểm tra đối soát bằng chứng vật lý.
  * `provider_policy` *(string: `builtin_only` \| `prefer_external` \| `require_external`)*: Chính sách nguồn dữ liệu.
  * `budget` *(integer, tùy chọn)*: Giới hạn số lượng token/nút xử lý.
* **Kịch bản sử dụng:** Sử dụng trước khi viết bất kỳ helper function mới nào để kiểm tra xem trong dự án đã có sẵn hàm tương tự chưa.

#### 2. `sot-graph_sot_map`
* **Mô tả:** Trả về bản đồ cấu trúc repository được cô đọng theo ngân sách token, xếp hạng mức độ quan trọng của các symbols bằng thuật toán **Personalized PageRank (PPR)**.
* **Tham số (Parameters):**
  * `focus` *(string, tùy chọn)*: Danh sách symbols quan trọng (ngăn cách bởi dấu phẩy) để định hướng PageRank tập trung vào phân vùng đó (VD: `UserController,AuthService`).
  * `max_tokens` *(integer, tối thiểu 16, mặc định: 1024)*: Ngân sách token tối đa cho bản đồ đầu ra.
* **Kịch bản sử dụng:** Khi Agent vừa bắt đầu một phiên làm việc mới và cần nắm bức tranh tổng thể của dự án mà không tốn token đọc hàng loạt thư mục.

#### 3. `sot-graph_sot_notes`
* **Mô tả:** Tra cứu danh sách các ghi chú tri thức (Notes) đã được con người hoặc AI ghi lại từ trước (các quyết định kiến trúc, lỗi kỳ quặc và cách fix, mẹo cấu hình hệ thống).
* **Tham số (Parameters):**
  * `query` *(string, tùy chọn)*: Từ khóa lọc nội dung ghi chú.
  * `limit` *(integer, mặc định: 50)*: Số lượng ghi chú tối đa.
* **Kịch bản sử dụng:** Tra cứu khi gặp các lỗi lạ liên quan đến môi trường hoặc kiến trúc để xem trước đây đồng đội đã ghi chép giải pháp chưa.

---

### Nhóm 2: Khảo Sát AST & Mối Quan Hệ Mã Nguồn

#### 4. `sot-graph_sot_explore`
* **Mô tả:** Duyệt đồ thị quan hệ có giới hạn bậc (bounded traversal). Cho biết một Node được gọi bởi ai (inward callers) và gọi tới ai (outward callees), liên kết import/export nào đang kết nối.
* **Tham số (Parameters):**
  * `node_id` *(string, bắt buộc)*: ID của Node hoặc FQN của symbol cần duyệt.
  * `depth` *(integer, tối thiểu 1, mặc định: 1)*: Độ sâu duyệt đồ thị (hops).
  * `limit` *(integer, mặc định: 100)*: Số lượng cạnh tối đa trả về.
* **Kịch bản sử dụng:** Khảo sát các lớp xung quanh một hàm trước khi sửa code để nắm rõ bối cảnh phụ thuộc.

#### 5. `sot-graph_sot_usages`
* **Mô tả:** Tìm kiếm toàn bộ vị trí tham chiếu (Find All References) của một symbol trên toàn bộ mã nguồn, nhóm theo từng hàm gọi (caller), đồng thời phát hiện các nguy cơ bare-name (tên biến/hàm bị trùng lặp mơ hồ).
* **Tham số (Parameters):**
  * `target` *(string, bắt buộc)*: Tên class, phương thức hoặc symbol cần tra cứu.
  * `limit` *(integer, mặc định: 100)*: Số lượng reference tối đa.
  * `scope` *(string, tùy chọn)*: Giới hạn trong thư mục con.
  * `assurance` *(boolean, mặc định: true)*: Đối soát trên đĩa.
* **Kịch bản sử dụng:** Bắt buộc chạy trước khi thay đổi tham số hoặc kiểu trả về của một hàm để đảm bảo không bỏ sót bất kỳ nơi nào đang gọi hàm đó.

#### 6. `sot-graph_sot_implementations`
* **Mô tả:** Tra cứu quan hệ kế thừa và hiện thực hóa (extends/implements) của một interface, abstract class hoặc class cơ sở, tìm ra toàn bộ các lớp con cụ thể.
* **Tham số (Parameters):**
  * `target` *(string, bắt buộc)*: Tên interface hoặc class cơ sở cần tra cứu.
* **Kịch bản sử dụng:** Khi làm việc với mô hình Factory, Strategy hoặc Polymorphism, giúp Agent lập tức nhìn thấy toàn bộ các Concrete Implementations trong codebase.

#### 7. `sot-graph_sot_pack`
* **Mô tả:** Đóng gói một k-hop ContextBundle dưới dạng định dạng YAML chuẩn hóa quanh một symbol mục tiêu. Bao gồm: 1-hop caller/callee contracts (hợp đồng đầy đủ) và 2-hop signature stubs (chữ ký hàm mở rộng).
* **Tham số (Parameters):**
  * `target` *(string, bắt buộc)*: Symbol hoặc FQN mục tiêu.
  * `max_hops` *(integer, 1-3, mặc định: 2)*: Số bước nhảy quan hệ.
  * `max_nodes` *(integer, mặc định: 50)*: Số node tối đa đóng gói.
  * `max_bytes` *(integer, mặc định: 65536 = 64KB)*: Giới hạn dung lượng byte.
* **Kịch bản sử dụng:** Cung cấp context chính xác, siêu gọn cho subagent khi giao việc lập trình chức năng liên quan đến symbol đó.

---

### Nhóm 3: Phân Tích Kiến Trúc, Cụm Module & Fact Bundler

#### 8. `sot-graph_sot_architecture_report`
* **Mô tả:** Đọc và phân tích toàn diện kiến trúc dự án: phát hiện mô hình phân tầng (MVC, Clean Architecture), các God Nodes (các lớp/hàm quá ôm đồm nhiều liên kết), chu trình phụ thuộc vòng (circular dependencies) và vi phạm ranh giới tầng kiến trúc.
* **Tham số (Parameters):**
  * `scope` *(string, tùy chọn)*: Giới hạn đường dẫn phân tích.
  * `min_size` *(integer, mặc định: 1)*: Kích thước cụm tối thiểu.
  * `sigma` *(number, mặc định: 1.5)*: Ngưỡng độ lệch chuẩn để gắn nhãn God Node.
* **Kịch bản sử dụng:** Lập báo cáo đánh giá hiện trạng mã nguồn định kỳ hoặc thẩm định kiến trúc trước đợt tái cấu trúc lớn.

#### 9. `sot-graph_sot_communities`
* **Mô tả:** Sử dụng thuật toán phân cụm **Louvain / Modularity Optimization** để phát hiện các phân vùng kiến trúc tự nhiên (communities) và tính điểm gắn kết (cohesion score) của từng phân vùng.
* **Tham số (Parameters):**
  * `scope` *(string, tùy chọn)*: Đường dẫn giới hạn phân tích.
  * `min_size` *(integer, mặc định: 1)*: Số lượng node tối thiểu trong một cụm.
* **Kịch bản sử dụng:** Phát hiện các ranh giới module bị phân mảnh hoặc các cụm mã nguồn có tính kết dính lỏng lẻo.

#### 10. `sot-graph_sot_bundle`
* **Mô tả:** Trích xuất tự động **5 file Fact Bundle** mật độ thông tin cao vào thư mục `.sot/bundle/` để LLM tổng hợp báo cáo kiến trúc mà không phải quét lại source code:
  1. `01_MODULE_INVENTORY.md`: Danh mục toàn bộ module, namespace, file.
  2. `02_ROUTING_ENDPOINTS.md`: Toàn bộ REST/Web endpoints, HTTP methods, Middleware, Controller action.
  3. `03_WORKFLOWS_AND_STATES.md`: Các State Machine, Enum, luồng xử lý trạng thái.
  4. `04_DEPENDENCIES_AND_VIOLATIONS.md`: Vi phạm tầng kiến trúc, circular dependencies.
  5. `05_SYSTEM_METRICS.json`: Chỉ số tổng hợp toàn bộ đồ thị (Nodes, Edges, Density, Modularity).
* **Tham số (Parameters):**
  * `output_dir` *(string, tùy chọn)*: Thư mục lưu kết quả (mặc định: `.sot/bundle/`).
* **Kịch bản sử dụng:** Tạo đầu vào làm việc cho các subagent viết tài liệu hoặc lập báo cáo kiến trúc cấp cao.

---

### Nhóm 4: Reverse Engineering & Động Cơ Solution (ITPRO / Manpower)

#### 11. `sot-graph_sot_trace`
* **Mô tả:** Trích xuất toàn diện đường đi thực thi Full-Stack: từ sự kiện click/nút bấm trên giao diện người dùng (Frontend UI Tree), qua API binding, Controller, Service nghiệp vụ đến tầng truy cập dữ liệu và Database. Tự động sinh sơ đồ **Mermaid Flowchart** và **Sequence Diagram**.
* **Tham số (Parameters):**
  * `target` *(string, bắt buộc)*: Mã ticket (VD: `CRMCM-107`), tên chức năng, route endpoint hoặc tên Service/Controller.
  * `depth` *(integer, 1-5, mặc định: 2)*: Độ sâu trace qua các tầng.
* **Kịch bản sử dụng:** Dùng để vẽ sơ đồ tuần tự và luồng dữ liệu cho Tài liệu Giải pháp (TLGP) và Tài liệu Nghiệp vụ (NV).

#### 12. `sot-graph_sot_ui_tree`
* **Mô tả:** Đọc và phân tích cây quyết định giao diện người dùng (Frontend UI Tree): trích xuất các trường dữ liệu đầu vào (Input fields), quy tắc validate, các nút bấm (Button Triggers) và sự kiện chuyển đổi Modal/Màn hình (hỗ trợ Flutter, React, Vue, Blade).
* **Tham số (Parameters):**
  * `component` *(string, bắt buộc)*: Tên component hoặc đường dẫn file UI.
* **Kịch bản sử dụng:** Dùng khi viết Hướng Dẫn Sử Dụng (HDSD) và Kịch Bản Kiểm Thử (KBKT), giúp mô tả các trường trên giao diện bám sát nguồn được truy vết (grounded); vẫn cần đối soát lại với giao diện thực tế.

#### 13. `sot-graph_sot_backend_flow`
* **Mô tả:** Bóc tách các vi bước xử lý backend (micro-steps), các nguồn dữ liệu đa dạng (Multi-Datasources, Oracle/MySQL/Redis), các nhánh rẽ điều kiện và các khối bắt ngoại lệ (Exception handling).
* **Tham số (Parameters):**
  * `service` *(string, bắt buộc)*: Tên Service class hoặc endpoint controller.
* **Kịch bản sử dụng:** Đào sâu chi tiết kỹ thuật các bước xử lý backend phục vụ viết tài liệu giải pháp và tính điểm nhân công.

#### 14. `sot-graph_sot_solution_inventory`
* **Mô tả:** **Giai đoạn 1 (Stage 1) Discovery:** Quét toàn bộ hệ thống để phát hiện danh sách tính năng theo từng vai trò người dùng (Admin, Merchant, EndUser, v.v.) và phân loại vào 10 danh mục tính năng liên quan (CRUD, StatusChange, Export, Import, Payment, v.v.).
* **Tham số (Parameters):**
  * `module` *(string, tùy chọn)*: Tên module hoặc phân hệ cần quét.
  * `output_file` *(string, tùy chọn)*: Đường dẫn lưu file markdown kết quả.
* **Kịch bản sử dụng:** Bắt buộc chạy ở bước đầu tiên của quy trình lập Tài liệu Giải pháp (kỹ năng `itpro-tlgp`).

#### 15. `sot-graph_sot_solution_steps`
* **Mô tả:** **Giai đoạn 2 (Stage 2) Micro-step Decomposition:** Tự động bóc tách một phương thức xử lý thành bảng chuẩn 4 cột: `Bước | Thao tác | Đối tượng tác động | Chi tiết kỹ thuật & Đoạn mã AST thực tế` phục vụ tính toán nhân công Manpower (NVJ1/NVJ2/NVJ3).
* **Tham số (Parameters):**
  * `method` *(string, bắt buộc)*: Tên phương thức hoặc FQN cần bóc tách.
* **Kịch bản sử dụng:** Dùng để điền file Excel ước lượng nhân công outsource hoặc làm rõ các bước kỹ thuật trong tài liệu giải pháp.

#### 16. `sot-graph_sot_solution_bundle`
* **Mô tả:** Tổng hợp toàn bộ bối cảnh giải pháp vào một file `ContextBundle.md` hoàn chỉnh: bao gồm định nghĩa bảng CSDL replayed từ migration, form UI, API contract và sơ đồ luồng dữ liệu để các subagent hạ tầng (DBDesign, HDSD, KBKT, Manpower) sử dụng mà không cần đọc lại source code.
* **Tham số (Parameters):**
  * `module` *(string, tùy chọn)*: Tên module.
  * `output_file` *(string, tùy chọn)*: Đường dẫn file đầu ra.
* **Kịch bản sử dụng:** Cung cấp SSOT artifact cho toàn bộ chuỗi subagent tài liệu tự động.

---

### Nhóm 5: Git Diff Impact, Assurance Receipts & Lịch Sử Commit

#### 17. `sot-graph_sot_diff_impact`
* **Mô tả:** Tính toán bán kính ảnh hưởng (Blast Radius) từ git diff: ánh xạ các dòng thay đổi trong git hunk trực tiếp vào các node AST, tính toán toàn bộ inward callers bị ảnh hưởng gián tiếp, các API endpoints bị tác động và các test suite cần chạy lại.
* **Tham số (Parameters):**
  * `target` *(string, mặc định: `HEAD~1`)*: Git revision đích (`HEAD~1`, commit SHA, hoặc `main...HEAD`).
  * `depth` *(integer, 1-5, mặc định: 2)*: Độ sâu duyệt ngược đồ thị gọi.
  * `staged` *(boolean, mặc định: false)*: Phân tích các thay đổi đã stage (`git diff --cached`).
  * `working_tree` *(boolean, mặc định: false)*: Phân tích thay đổi chưa stage trong working tree.
  * `auto_reconcile` *(boolean, mặc định: false)*: Tự động sync lại đồ thị trước khi phân tích.
  * `format` *(string: `markdown` \| `json`, mặc định: `markdown`)*: Định dạng kết quả.
* **Kịch bản sử dụng:** Chạy trước khi tạo Pull Request hoặc sau khi hoàn thành sửa code để xác minh toàn bộ phạm vi ảnh hưởng.

#### 18. `sot-graph_sot_scope_receipt`
* **Mô tả:** **Giao thức P7.1 PRE-change Scope Receipt:** Tạo biên lai phạm vi trước khi chỉnh sửa một symbol. Ghi nhận snapshot commit hiện tại, độ sâu tác động dự kiến, mức độ rủi ro (liên quan đến Auth hay Dynamic dispatch), danh sách các test candidate tương ứng.
* **Tham số (Parameters):**
  * `target` *(string, bắt buộc)*: Symbol dự kiến sửa đổi.
  * `kind_of_change` *(string: `local-body` \| `rename` \| `delete` \| `public-api`)*: Loại thay đổi.
  * `touches_auth` *(boolean, mặc định: false)*: Có đụng chạm logic xác thực/phân quyền không.
  * `dynamic_heavy` *(boolean, mặc định: false)*: Có sử dụng reflection hay dynamic call không.
  * `depth` *(integer, mặc định: 2)*: Bán kính duyệt tác động.
* **Kịch bản sử dụng:** Bắt buộc tạo trước khi thực hiện các sửa đổi cốt lõi trên God Nodes hoặc Public API.

#### 19. `sot-graph_sot_diff_impact_receipt`
* **Mô tả:** **Giao thức P7.2 POST-change Diff Impact Receipt:** Tạo biên lai hoàn tất sau khi sửa đổi mã nguồn. Đóng gói kết quả phân tích git diff, bằng chứng đối soát sau thay đổi, các điểm còn hở (gaps) và quyết định đóng (closure decision) rõ ràng.
* **Tham số (Parameters):**
  * `target` *(string, mặc định: `HEAD~1`)*: Git revision so sánh.
  * `depth` *(integer, mặc định: 2)*: Bán kính duyệt gọi ngược.
  * `staged` *(boolean)*: So sánh staged changes.
  * `working_tree` *(boolean)*: So sánh unstaged working tree.
* **Kịch bản sử dụng:** Bắt buộc tạo sau khi sửa code để nộp bằng chứng kiểm toán cho Tier-1 Reviewer và Advisor trước khi merge.

#### 20. `sot-graph_sot_git_history`
* **Mô tả:** Quét lịch sử git commit kèm chấm điểm rủi ro tự động (Low, Medium, High, Critical) dựa trên số dòng thay đổi, tần suất sửa đổi các God Node và đối soát các symbol bị sửa với đồ thị tri thức.
* **Tham số (Parameters):**
  * `limit` *(integer, 1-100, mặc định: 10)*: Số lượng commit cần kiểm tra.
  * `author` *(string, tùy chọn)*: Lọc commit theo tác giả.
  * `since` *(string, tùy chọn)*: Lọc commit từ mốc thời gian (VD: `2026-01-01` hoặc `2.weeks`).
  * `with_impact` *(boolean, mặc định: true)*: Bật đối soát symbol với đồ thị SOT.
  * `format` *(string: `markdown` \| `json`)*: Định dạng kết quả.
* **Kịch bản sử dụng:** Kiểm toán chất lượng mã nguồn định kỳ hoặc rà soát nhanh các commit nóng trước khi deploy lên UAT/Production.

#### 21. `sot-graph_sot_verify_drift`
* **Mô tả:** Kiểm tra độ lệch (drift) giữa đồ thị trong SQLite và thực tế file trên đĩa cứng: phát hiện các file bị xóa nhưng vẫn còn trong CSDL, các file mới chưa được lập chỉ mục, hoặc hash SHA-256 bị sai lệch. An toàn khi chạy trong CI/CD.
* **Tham số (Parameters):**
  * `deep` *(boolean, mặc định: false)*: Bật băm toàn bộ nội dung file (SHA-256) thay vì chỉ kiểm tra mtime/size.
  * `limit` *(integer, mặc định: 100)*: Số file phát hiện tối đa.
* **Kịch bản sử dụng:** Chạy kiểm tra nhanh trong pre-commit hook hoặc CI pipeline.

---

### Nhóm 6: Đồng Bộ External Provider

#### 22. `sot-graph_sot_providers_sync`
* **Mô tả:** Kích hoạt đồng bộ hóa tường minh (write path) chỉ mục từ một evidence provider bên ngoài (VD: `codebase-memory`), được bảo vệ an toàn bởi project write lock và lưu lại ledger run receipt kèm snapshot.
* **Tham số (Parameters):**
  * `provider_name` *(string, mặc định: `codebase-memory`)*: Tên provider cần đồng bộ.
* **Kịch bản sử dụng:** Khi dự án có sử dụng song song engine SCIP hoặc codebase-memory và cần cập nhật chỉ mục đồng nhất vào SOT-Graph.

---

### Tài Nguyên MCP (Resources, Templates & Subscriptions)
SOT-Graph MCP Server cung cấp các MCP Resources trực tiếp:
* `sot://stats`: Trả về toàn bộ chỉ số thống kê của đồ thị (tổng số node, edge, files, dung lượng DB).
* `sot://notes`: Trả về toàn bộ ghi chú tri thức đã lưu trữ.
* `sot://node/{node_id}`: Resource Template cho phép đọc nội dung đầy đủ (source code snippet, signature, caller/callee list) của một node bất kỳ theo ID.
* **Resource Subscriptions:** Hỗ trợ client lắng nghe sự kiện thay đổi của đồ thị (`notifications/resources/updated`) khi có tiến trình khác chạy `reconcile`.

---

## 4. Chi Tiết Hệ Thống Câu Lệnh CLI

Lệnh CLI thực thi qua binary `sot`. Hỗ trợ toàn diện cờ toàn cục:
* `--root <PATH>`: Thiết lập thư mục gốc dự án (mặc định: thư mục hiện tại).
* `--db <PATH>`: Thiết lập đường dẫn SQLite DB tùy chỉnh (mặc định: `.sot/sot.db`).
* `-V, --version`: Hiển thị phiên bản SOT-Graph.

---

### Nhóm Lệnh Vòng Đời & Đồng Bộ CSDL

#### `sot reconcile`
Đồng bộ hóa đồ thị tri thức với hệ thống tệp đĩa cứng một cách lũy kế (idempotent). Tự động bỏ qua các file không đổi nhờ bảng nhật ký thay đổi (journal).
```bash
# Đồng bộ toàn bộ dự án
sot reconcile

# Đồng bộ một thư mục hoặc tệp cụ thể
sot reconcile Modules/Api/Services/ContractService.php

# Ép quét lại toàn bộ (bỏ qua journal hash)
sot reconcile --force

# Chỉ định số tiến trình worker song song (tối đa 8)
sot reconcile --workers 4 --batch-size 128

# Xuất biên lai xác thực (Assurance Receipt) dưới dạng JSON
sot reconcile --receipt --json
```

#### `sot batch-reconcile`
Đồng bộ hóa hàng loạt nhiều repositories cùng lúc trong một thư mục cha.
```bash
sot batch-reconcile ~/code/GitHub/ --workers 4
```

#### `sot watch`
Chạy watcher theo dõi thay đổi tệp tin theo thời gian thực và tự động reconcile ngay lập tức.
```bash
# Chạy tương tác trực tiếp
sot watch --debounce-ms 200

# Khởi động chạy nền dưới dạng Daemon
sot watch -d

# Kiểm tra trạng thái watcher daemon
sot watch --status

# Dừng daemon đang chạy
sot watch --stop

# Cài đặt thành background service hệ thống (macOS LaunchAgent hoặc Linux systemd)
sot watch --service install
```

#### `sot verify`
Kiểm tra độ lệch (drift) giữa CSDL đồ thị và đĩa cứng mà không thực hiện ghi đè. Rất thích hợp cho CI/CD pipeline.
```bash
sot verify
sot verify --deep   # Kiểm tra băm SHA-256 sâu toàn bộ file
```

#### `sot doctor`
Kiểm tra sức khỏe CSDL SQLite, tính toàn vẹn của chỉ mục FTS5, độ gắn kết đồ thị và thông số hiệu năng.
```bash
sot doctor
sot doctor --receipt --json   # Xuất báo cáo kiểm toán hệ thống
```

---

### Nhóm Lệnh Truy Vấn, Tìm Kiếm & Bản Đồ Mã Nguồn

#### `sot search`
Tìm kiếm symbol có xếp hạng và gắn nhãn niềm tin (`[STRONG]`, `[WEAK]`, v.v.).
```bash
# Tìm kiếm cơ bản
sot search "ContractService"

# Tìm kiếm giới hạn số lượng và phạm vi thư mục
sot search "calculateFee" -n 5 --scope "Modules/Api"

# Tìm kiếm Hybrid (kết hợp BM25 văn bản và Vector Similarity)
sot search "thanh toán hóa đơn" --hybrid

# Xuất dạng JSON để các script khác xử lý
sot search "User" --json
```

#### `sot embed`
Xây dựng chỉ mục vector embeddings (yêu cầu cài đặt extra `pip install 'sot-graph[vector]'`).
```bash
sot embed --limit 5000
```

#### `sot map`
Sinh bản đồ mã nguồn thu gọn theo ngân sách token dựa trên Personalized PageRank.
```bash
# Bản đồ mặc định 1024 tokens
sot map

# Bản đồ 2048 tokens tập trung vào module Hợp đồng và Đối tác
sot map --tokens 2048 --focus "ContractController,PartnerService"
```

#### `sot explore`
Duyệt đồ thị các mối quan hệ AST (calls, called_by, imports) của một symbol.
```bash
sot explore "App\\Services\\PaymentService" --depth 2
sot explore "approveContract" --all --json
```

#### `sot usages`
Tìm kiếm toàn bộ vị trí gọi/sử dụng một symbol trong toàn bộ codebase.
```bash
sot usages "changeStatus"
sot usages "UserModel" --json
```

#### `sot implementations`
Xem toàn bộ cây kế thừa hoặc các lớp hiện thực hóa interface.
```bash
sot implementations "PaymentGatewayInterface"
```

#### `sot rename`
Lập kế hoạch phân tích tác động (Impact Plan) trước khi đổi tên một symbol trên toàn bộ dự án (chế độ report-only, không sửa file bừa bãi).
```bash
sot rename "oldFunctionName" --to "newFunctionName"
```

#### `sot pack`
Đóng gói một ContextBundle YAML k-hop tối ưu token quanh một symbol để làm prompt context cho Agent.
```bash
sot pack "OrderService" --max-hops 2 --tokens 1500 -o order_context.yaml
```

#### `sot insert`
Lưu trữ một ghi chú kiến trúc, quyết định kỹ thuật hoặc giải pháp sửa lỗi quan trọng vào CSDL SOT để các agent/developer khác tái sử dụng.
```bash
sot insert --title "Lưu ý kết nối Oracle DB" \
           --body "Không sử dụng raw query thiếu schema prefix. Phải dùng DB::connection('oracle')->..." \
           --keywords "oracle,db,connection,bug"
```

---

### Nhóm Lệnh Báo Cáo Kiến Trúc & Trực Quan Hóa Đồ Thị

#### `sot report`
Sinh báo cáo phân tích kiến trúc hoàn chỉnh dưới dạng Markdown (bao gồm sơ đồ C4 Mermaid, các God Node, vi phạm tầng kiến trúc).
```bash
sot report -o Docs/ARCHITECTURE_REPORT.md
sot report --sigma 2.0 --scope "Modules/Web"
```

#### `sot cluster`
Phân cụm đồ thị bằng thuật toán Louvain và hiển thị các ranh giới kiến trúc tự nhiên.
```bash
sot cluster --min-size 3
sot cluster --json
```

#### `sot viz`
Sinh file HTML độc lập chứa trình trực quan hóa đồ thị tương tác (sử dụng Vis.js / Force-directed layout), cho phép zoom, pan, click xem node.
```bash
# Sinh file graph.html và tự động mở trình duyệt
sot viz -o graph.html --open
```

#### `sot export`
Xuất đồ thị tri thức sang các định dạng chuẩn khác để phục vụ nghiên cứu hoặc công cụ ngoài.
```bash
sot export -f obsidian -o ~/Documents/ObsidianVault/CodeGraph/  # Xuất thành vault Markdown cho Obsidian
sot export -f graphrag -o graphrag_dump.json                  # Xuất cho GraphRAG của Microsoft
sot export -f graphml  -o graph.graphml                       # Xuất định dạng Gephi / GraphML
sot export -f scip     -o index.scip                          # Xuất chỉ mục SCIP
```

#### `sot bundle`
Trích xuất bộ 5 file Fact Bundle mật độ cao phục vụ tổng hợp tài liệu tự động.
```bash
sot bundle -o .sot/bundle/
```

---

### Nhóm Lệnh Động Cơ Solution & Trace Full-Stack

#### `sot trace`
Truy vết luồng thực thi Full-Stack từ Frontend UI -> Route -> Controller -> Service -> Database, tự động render sơ đồ Mermaid.
```bash
sot trace "CRMCM-107" --depth 3 -o Docs/CRMCM-107_Trace.md
sot trace "ContractController::approve" --json
```

#### `sot ui-tree`
Bóc tách cây quyết định UI, validation, modal và button trigger của màn hình giao diện.
```bash
sot ui-tree "lib/screens/contract/contract_detail_screen.dart"
```

#### `sot be-flow`
Bóc tách các vi bước xử lý nghiệp vụ của Service/Controller phía backend.
```bash
sot be-flow "ContractService"
```

#### `sot solution`
Động cơ tự động hóa phục vụ viết Tài liệu Giải pháp (TLGP) và ước lượng nhân lực Manpower:
```bash
# Giai đoạn 1: Khám phá danh mục tính năng theo vai trò người dùng (Feature Discovery)
sot solution inventory "Contract" -o Feature_Inventory.md

# Giai đoạn 2: Bóc tách vi bước xử lý thành bảng 4 cột phục vụ tính Manpower (NVJ1/2/3)
sot solution steps "ContractService::createContract" --format table

# Tổng hợp toàn bộ context bundle phục vụ các subagent viết Solution.md
sot solution bundle "Contract" -o .sot/bundle/ContextBundle.md
```

---

### Nhóm Lệnh Phân Tích Tác Động Thay Đổi (Diff Impact & Git)

#### `sot diff-impact`
Phân tích bán kính ảnh hưởng từ thay đổi mã nguồn git, chỉ ra các hàm gọi ngược (inward callers) bị ảnh hưởng và danh sách test suites cần chạy.
```bash
# Phân tích commit gần nhất so với HEAD~1
sot diff-impact

# Phân tích các thay đổi đang staged trong Git
sot diff-impact --staged

# Phân tích các thay đổi chưa staged trong working tree
sot diff-impact --working-tree

# Tự động đồng bộ đồ thị trước khi phân tích và xuất file Markdown
sot diff-impact HEAD~1 --depth 3 --auto-reconcile -o Diff_Impact_Report.md
```

#### `sot scope-receipt`
Tạo biên lai phạm vi trước khi chỉnh sửa mã nguồn (P7.1 PRE-change Scope Receipt).
```bash
sot scope-receipt "ContractService::approveContract" --change-kind "public-api" --auth --json
```

#### `sot log` (alias: `sot commits`)
Quét lịch sử git commit kèm chấm điểm rủi ro tự động và đối soát các symbol bị sửa với đồ thị SOT.
```bash
sot log -n 15
sot log --since "2.weeks" --author "giapminh" -o Commit_Risk_Report.md
```

---

### Nhóm Lệnh Multi-Provider & Trình Nhập SCIP

#### `sot providers`
Quản lý, phát hiện và kiểm tra sức khỏe các nhà cung cấp bằng chứng bên ngoài:
```bash
sot providers detect      # Kiểm tra các công cụ SCIP / external provider trên máy
sot providers list        # Liệt kê các provider đã cấu hình và năng lực
sot providers doctor      # Đánh giá sức khỏe và gợi ý hành động cải thiện
sot providers resolve --capability impact   # Tìm provider tốt nhất cho tính năng impact
sot providers sync codebase-memory          # Kích hoạt đồng bộ hóa dữ liệu từ provider
```

#### `sot import-scip`
Nạp trực tiếp chỉ mục SCIP từ compiler vào CSDL SOT-Graph.
```bash
sot import-scip index.scip --provider scip-typescript
```

---

### Nhóm Lệnh Bảo Trì CSDL & Thiết Lập Harness

#### `sot clean`
Dọn dẹp các bản ghi rác, bản ghi mồ côi hoặc reset toàn bộ dữ liệu đồ thị một cách an toàn.
```bash
# Xem trước các node/edge rác sẽ bị xóa (dry-run)
sot clean --dry-run

# Dọn dẹp bản ghi tệp không còn tồn tại
sot clean

# Reset toàn bộ dữ liệu đồ thị (giữ lại ghi chú notes)
sot clean --all --yes
```

#### `sot vacuum`
Thu gọn kích thước tệp CSDL SQLite, giải phóng dung lượng trống trên đĩa và tối ưu hóa index (`PRAGMA optimize`).
```bash
sot vacuum --analyze
sot vacuum --dry-run
```

#### `sot setup`
Tự động cấu hình các AI Coding Harness (Pi/OMP, OpenCode, Antigravity, Claude, ZCode) để kết nối trực tiếp với SOT-Graph, đồng thời cài đặt git post-merge hooks để tự động reconcile.
```bash
sot setup --harness all
sot setup --hooks    # Cài đặt hook git tự động sync đồ thị sau mỗi lần git pull/merge
```

#### `sot mcp`
Khởi chạy MCP stdio server để kết nối với Claude Desktop, Cursor, OpenCode hoặc Antigravity qua giao thức MCP.
```bash
sot mcp
```

---

## 5. Bảng Đối Chiếu So Sánh: MCP Tools vs. CLI Commands

| Nhu Cầu Nghiệp Vụ | Gọi Qua MCP Tool (AI Agent Tự Động) | Chạy Qua CLI (Terminal / Script / Makefile) |
| :--- | :--- | :--- |
| **Tìm kiếm hàm / class có xác thực** | `sot_search(query="...")` | `sot search "..."` |
| **Lấy bản đồ repo theo token** | `sot_map(tokens=1024)` | `sot map --tokens 1024` |
| **Xem ai gọi hàm này (References)** | `sot_usages(target="...")` | `sot usages "..."` |
| **Xem cây kế thừa interface/class** | `sot_implementations(target="...")` | `sot implementations "..."` |
| **Đóng gói ContextBundle YAML** | `sot_pack(target="...")` | `sot pack "..." -o context.yaml` |
| **Truy vết luồng Full-Stack & Mermaid**| `sot_trace(target="...")` | `sot trace "..." -o trace.md` |
| **Bóc tách cây giao diện Frontend UI** | `sot_ui_tree(component="...")` | `sot ui-tree "..."` |
| **Bóc tách vi bước xử lý Backend** | `sot_backend_flow(service="...")` | `sot be-flow "..."` |
| **Khám phá danh mục tính năng (Stage 1)**| `sot_solution_inventory(module="...")` | `sot solution inventory "..."` |
| **Bóc tách vi bước tính Manpower (Stage 2)**| `sot_solution_steps(method="...")` | `sot solution steps "..."` |
| **Trích xuất 5 Fact Bundle files** | `sot_bundle(output_dir="...")` | `sot bundle -o ...` |
| **Phân tích Bán kính tác động Git Diff**| `sot_diff_impact(target="HEAD~1")` | `sot diff-impact HEAD~1` |
| **Biên lai P7.1 trước khi sửa code** | `sot_scope_receipt(target="...")` | `sot scope-receipt "..."` |
| **Biên lai P7.2 sau khi sửa code** | `sot_diff_impact_receipt()` | *(API/MCP Protocol chuyên dụng)* |
| **Đánh giá rủi ro commit Git** | `sot_git_history(limit=10)` | `sot log -n 10` |
| **Kiểm tra lệch CSDL và đĩa (Drift)** | `sot_verify_drift(deep=False)` | `sot verify [--deep]` |
| **Đồng bộ CSDL đồ thị từ mã nguồn** | *(Tự động chạy JIT trong MCP read)* | `sot reconcile [--force]` |
| **Watcher chạy nền thời gian thực** | *(Lắng nghe qua Resource Subscriptions)* | `sot watch -d` |
| **Bảo trì, Vacuum, Clean CSDL** | *(Read-only, không mở qua MCP)* | `sot clean`, `sot vacuum`, `sot doctor` |
| **Xem đồ thị tương tác HTML** | *(Không phù hợp giao tiếp Agent)* | `sot viz --open` |

---

## 6. 4 Kịch Bản Vận Hành Thực Chiến (Real-World Workflows)

### Kịch Bản 1: Tiếp nhận Dự án mới (Onboarding không tốn Token)
1. **Lập chỉ mục ban đầu:**  
   Chạy `sot reconcile --workers 4` trên terminal để nạp toàn bộ cấu trúc AST vào `.sot/sot.db`.
2. **Khảo sát bản đồ tổng thể:**  
   AI Agent gọi `sot_map(tokens=1024)` để nắm các điểm nút trung tâm của dự án.
3. **Trực quan hóa cấu trúc:**  
   Developer chạy `sot viz --open` để xem sơ đồ phân cụm tương tác trên trình duyệt.
4. **Đánh giá sức khỏe kiến trúc:**  
   Chạy `sot report -o Docs/ARCHITECTURE_REPORT.md` để xem danh sách God Nodes và các chu trình phụ thuộc vòng.

### Kịch Bản 2: Sửa đổi / Refactor Mã Nguồn An Toàn (Chuẩn 4 Bước)
1. **Bước 1 - Định vị & Khảo sát:**  
   Agent gọi `sot_search("approveContract")` -> Nhận kết quả với nhãn `[STRONG]` kèm đường dẫn chính xác.
2. **Bước 2 - Lập Biên lai Phạm vi (P7.1 Scope Receipt):**  
   Agent gọi `sot_scope_receipt(target="ContractService::approveContract", kind_of_change="public-api")` để xác định danh sách các inward callers và candidate test suites.
3. **Bước 3 - Tiến hành Chỉnh sửa Mã nguồn:**  
   Áp dụng các thay đổi cục bộ có giới hạn dòng (`file:start-end`).
4. **Bước 4 - Xác minh Tác động & Lập Biên lai Đóng (P7.2 Diff Impact Receipt):**  
   Agent gọi `sot_diff_impact_receipt(working_tree=True)` để kiểm tra git diff, đảm bảo không có tác động ngoài ý muốn và chạy đúng các unit tests đã được chỉ định. Chạy `sot reconcile` để cập nhật lại đồ thị.

### Kịch Bản 3: Viết Bộ Tài Liệu Giải Pháp (TLGP) & Tính Toán Manpower
1. **Giai đoạn 1 (Discovery):**  
   Gọi `sot_solution_inventory(module="Contract")` để phát hiện toàn bộ tính năng theo các vai trò (Admin, User, Merchant) và phân loại vào 10 nhóm nghiệp vụ.
2. **Giai đoạn 2 (Bóc tách Vi bước Manpower):**  
   Với mỗi tính năng backend phức tạp, gọi `sot_solution_steps(method="ContractService::processPayment")` để nhận bảng 4 cột có code thực tế, tự động phân loại độ phức tạp (NVJ1, NVJ2, NVJ3).
3. **Giai đoạn 3 (Đóng gói Bundle):**  
   Gọi `sot_solution_bundle(module="Contract")` sinh `ContextBundle.md`. Toàn bộ các subagent viết tài liệu downstream (`itpro-dbdesign`, `itpro-hdsd`, `itpro-kbkt`, `itpro-manpower`) chỉ tiêu thụ từ bundle này, tuyệt đối không đọc lại source code.

### Kịch Bản 4: Thiết Lập Git Hooks Tự Động Đồng Bộ
1. **Cài đặt Git Hook:**  
   Chạy `sot setup --hooks`. Hệ thống sẽ tạo hook `post-merge` và `post-checkout` trong `.git/hooks/`.
2. **Vận hành:**  
   Mỗi khi lập trình viên `git pull` hoặc đổi branch, SOT-Graph sẽ tự động chạy `sot reconcile` đồng bộ lại các file vừa thay đổi trong chưa đầy 1 giây mà không cần can thiệp thủ công.

---
*Tài liệu được tổng hợp và biên soạn theo kiến trúc SOT-Graph v0.3.0.*
