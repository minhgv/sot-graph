# 📚 SOT-Graph: Toàn Tập Hỏi Đáp & Kịch Bản Sử Dụng Thực Tế (Q&A Guide)

> **Kiến Trúc Tri Thức Tự Chữa Lành, Chống Ảo Giác & Vận Hành Cho AI Coding Agents.**  
> *Filesystem là Nguồn Chân Lý Duy Nhất (Single Source of Truth) — Không Daemon — Độ Trễ Sub-Millisecond.*

---

## 🌐 Các Cách Xem Tài Liệu Này:
- 📖 **Đọc trực tiếp trên GitHub (Markdown UI)**: Đang xem tài liệu này (sử dụng các khối mở rộng bên dưới).
- ⚡ **Xem bản HTML tương tác (Live Search & Filter)**: [Mở trên HTMLPreview (GitHub)](https://htmlpreview.github.io/?https://github.com/minhgv/sot-graph/blob/main/sot_qa_guide.html)
- 💻 **Xem Offline trên máy cá nhân**: `open sot_qa_guide.html` (macOS) hoặc `xdg-open sot_qa_guide.html` (Linux).

---

## 📑 Mục Lục Nhanh

1. [Chủ Đề 1: Cơ Chế Cốt Lõi & Chống Ảo Giác (Core Architecture)](#-1-cơ-chế-cốt-lõi--chống-ảo-giác-core-architecture)
2. [Chủ Đề 2: Tự Chữa Lành & Toàn Vẹn Dữ Liệu (Self-Healing)](#-2-tự-chữa-lành--toàn-vẹn-dữ-liệu-self-healing)
3. [Chủ Đề 3: Tích Hợp AI Agent & Giao Thức MCP (AI Agent Integration)](#-3-tích-hợp-ai-agent--giao-thức-mcp-ai-agent-integration)
4. [Chủ Đề 4: Phân Tích Đồ Thị & Trực Quan Hóa (Graph Analytics)](#-4-phân-tích-đồ-thị--trực-quan-hóa-graph-analytics)
5. [Chủ Đề 5: Vận Hành, Bảo Trì & Hiệu Năng (Ops & Maintenance)](#-5-vận-hành-bảo-trì--hiệu-năng-ops--maintenance)
6. [Chủ Đề 6: Xử Lý Sự Cố & Tình Huống Thực Tế (Edge Cases)](#-6-xử-lý-sự-cố--tình-huống-thực-tế-edge-cases)

---

## 🛡️ 1. Cơ Chế Cốt Lõi & Chống Ảo Giác (Core Architecture)

<details open>
<summary><h3>Q1: Tại sao sot-graph gọi là "Single Source of Truth"? Sự khác biệt giữa Filesystem làm gốc và Vector/Graph RAG truyền thống là gì?</h3></summary>

Các hệ thống RAG và Agent Memory truyền thống (dùng Vector DB, Neo4j, Redis) lưu trữ tri thức như một **bản sao rời rạc (detached snapshot)**. Khi lập trình viên sửa code, đổi tên file hoặc xóa thư mục, database không hề biết sự thay đổi này cho đến khi được re-index thủ công, dẫn đến hiện tượng **Phantom Anchors (Đường dẫn ma)** — AI Agent đọc tri thức cũ và sinh mã cho file không còn tồn tại.

> [!IMPORTANT]
> **Nguyên tắc vàng của sot-graph:**  
> *"Filesystem is the Single Source of Truth — The knowledge graph is an authoritative, verified projection of reality."*

Mọi tín hiệu từ file watcher, git hook hay lệnh CLI chỉ được coi là lời gợi ý (*"hãy kiểm tra đường dẫn này"*). Hệ thống **không bao giờ tin tưởng mù quáng** vào bộ nhớ đệm mà luôn đối soát vật lý trên đĩa cứng trước khi trả kết quả cho Agent.

| Đặc tính | Vector / Graph RAG Truyền Thống | sot-graph (Kiến trúc SSOT) |
| :--- | :--- | :--- |
| **Nguồn chân lý** | Vector Embeddings / Graph Nodes trong DB rời | **Tệp vật lý trên Filesystem** |
| **Xử lý khi xóa file** | Vẫn trả về vector cũ (gây ảo giác đường dẫn) | **Tự động thanh trừng ngay khi tìm kiếm (Auto-Purge)** |
| **Hạ tầng yêu cầu** | Cần Server nền (Neo4j, Qdrant, Chroma, Java/Node) | **Zero Daemon**: Nhúng trực tiếp SQLite WAL &lt; 25MB RAM |
| **Độ trễ truy vấn** | 50ms - 500ms (qua mạng / RPC) | **&lt; 1.5ms (P95)** qua SQLite FTS5 BM25 |

</details>

---

<details>
<summary><h3>Q2: Nếu tôi sửa đúng 1 dòng trong file, hệ thống có phát hiện được không và cơ chế đồng bộ diễn ra như thế nào?</h3></summary>

**CÓ, CHẮC CHẮN BIẾT 100% VÀ BIẾT NGAY LẬP TỨC.**

Bộ điều phối `sot_graph.reconciler` sử dụng cơ chế bảo vệ 2 tầng để phát hiện mọi thay đổi dù là nhỏ nhất:

1. **Tầng 1 - Fast Dirty Check qua Filesystem Metadata ($O(1)$):**
   Khi sửa 1 dòng code, hệ điều hành lập tức cập nhật `st_mtime` (mili-giây) và thường làm đổi `st_size` (kích thước byte). Reconciler so sánh cặp `(size, mtime_ms)` với bản ghi trong bảng `file_journal`. Nếu khác, file được đánh dấu là bẩn (dirty) ngay trong micro-giây.

2. **Tầng 2 - Bảo Vệ Toàn Vẹn Bằng SHA-256 Hash:**
   Trong trường hợp bạn sửa 1 ký tự mà kích thước tệp giữ nguyên và metadata `mtime` bị trùng, hàm `_hash(path)` sẽ tính toán lại mã băm SHA-256 nội dung. Do hiệu ứng tuyết lở (*avalanche effect*), mã SHA-256 sẽ khác hoàn toàn giá trị lưu trong database, đảm bảo không một thay đổi nào bị bỏ sót.

```python
# src/sot_graph/reconciler.py:270-281
prior = journal_cache.get(path)
if prior and prior.get("size") == size and prior.get("mtime_ms") == mtime_ms:
    current_sha = self._hash(path)
    if prior.get("sha256") == current_sha:
        continue  # Bỏ qua vì file thực sự không thay đổi
jobs.append(ParseJob(path, self.root_dir, size, mtime_ms))
```

Sau khi xác định file bị bẩn, Reconciler thực hiện **Thay thế nguyên tử (Atomic Batch Replacement)** trong SQLite: xóa toàn bộ node, edge cũ của riêng file đó và nạp lại AST mới trong một transaction duy nhất.

</details>

---

<details>
<summary><h3>Q3: Trust Verdict System hoạt động ra sao? Ý nghĩa cụ thể của các nhãn [STRONG], [WEAK], [REBUILT], [REMOVED], [NOPATH]?</h3></summary>

Khi Agent thực hiện `sot search "<query>"`, mọi kết quả trả về từ FTS5 đều phải đi qua `TrustVerifier.verify_hit` để kiểm tra tính xác thực trên đĩa cứng:

```
[Agent Query] ──> [SQLite FTS5 (BM25)] ──> [Candidate Node]
                                    │
        ┌───────────────────────────┴───────────────────────────┐
        ▼                                                       ▼
[File tồn tại trên đĩa?]                               [File KHÔNG tồn tại?]
├── Có: Đọc 256KB đầu tệp                                           │
│   ├── Token query khớp >= 50% ──> [STRONG]                        ▼
│   └── Token query khớp < 50%  ──> [WEAK]                [find_rehome: Quét đĩa tìm basename]
│                                                          ├── Tìm thấy duy nhất 1 file mới:
│                                                          │   ├── db.update_node_path(...)
│                                                          │   └── Trả về [REBUILT]
│                                                          └── Không tìm thấy (đã xóa vĩnh viễn):
│                                                              ├── db.delete_path(...)
│                                                              └── Trả về [REMOVED]
```

| Nhãn Verdict | Điều Kiện Kích Hoạt | Hành Động Khuyến Nghị Cho AI Agent |
| :--- | :--- | :--- |
| `[STRONG]` | File tồn tại vật lý VÀ nội dung chứa $\ge 50\%$ từ khóa tìm kiếm. | **Tin cậy tuyệt đối**: Điều hướng thẳng tới file và số dòng code. |
| `[WEAK]` | File có tồn tại nhưng độ phủ từ khóa $&lt; 50\%$ (khớp ngữ nghĩa tiêu đề). | **Cẩn trọng**: Đọc lướt nội dung trước khi áp dụng logic. |
| `[REBUILT]` | File bị đổi tên hoặc chuyển thư mục; đã được tự động định vị lại. | **Đã tự chữa lành**: Sử dụng đường dẫn mới nhất được báo cáo. |
| `[REMOVED]` | File đã bị xóa vĩnh viễn khỏi ổ cứng. | **Đã thanh trừng**: Node bị xóa khỏi DB, bỏ qua kết quả này. |
| `[NOPATH]` | Ghi chú tri thức ảo (Architecture Decision Record, quy ước, mẹo). | **Mỏ neo kiến thức**: Coi như tài liệu hướng dẫn chuẩn. |

</details>

---

<details>
<summary><h3>Q4: Pending Edge Resolution 2 chiều giải quyết bài toán import chéo (Circular / Out-of-order indexing) như thế nào?</h3></summary>

Trong một dự án thực tế, File A gọi hàm `AuthService.validate()` ở File B, nhưng File A có thể được Reconciler quét trước File B. Lúc này node `AuthService.validate` chưa tồn tại trong database.

**Cơ chế giải quyết của sot-graph:**
1. **Bước 1:** Quan hệ chưa giải quyết được lưu tạm vào bảng `pending_edges (path, src, dst_symbol, relation, line)`.
2. **Bước 2:** Khi File B được quét và định nghĩa symbol `AuthService.validate`, hàm `resolve_all_pending_edges()` chạy một câu lệnh SQL duy nhất:

```sql
-- src/sot_graph/db.py:263-273
-- Tự động thăng hạng pending edge thành graph_edges hoàn chỉnh
INSERT OR REPLACE INTO graph_edges(path, src, dst, relation, line)
SELECT p.path, p.src, (
    SELECT n.id FROM graph_nodes n 
    WHERE n.symbol = p.dst_symbol 
    ORDER BY n.id LIMIT 1
), p.relation, p.line
FROM pending_edges p 
WHERE EXISTS (SELECT 1 FROM graph_nodes n WHERE n.symbol = p.dst_symbol);

-- Dọn dẹp sạch bảng pending_edges
DELETE FROM pending_edges 
WHERE EXISTS (SELECT 1 FROM graph_nodes n WHERE n.symbol = pending_edges.dst_symbol);
```

Nhờ vậy, thứ tự duyệt file hoàn toàn độc lập, đồ thị luôn đạt trạng thái hội tụ (*deterministic convergence*).

</details>

---

## 🩹 2. Tự Chữa Lành & Toàn Vẹn Dữ Liệu (Self-Healing)

<details>
<summary><h3>Q5: Khi một file bị xóa vĩnh viễn bằng lệnh rm, database tự động xử lý như thế nào để Agent không đọc nhầm mã nguồn đã chết?</h3></summary>

Có 2 con đường để `sot-graph` phát hiện và thanh trừng file đã bị xóa:

1. **Đồng Bộ Chủ Động (`sot reconcile`):**  
   Reconciler quét toàn bộ ổ đĩa, so sánh tập hợp đường dẫn hiện có trên đĩa với tập `_known_abs_paths()` trong DB. Bất kỳ file nào có trong DB nhưng mất trên đĩa sẽ lập tức bị xóa qua `db.delete_path(path)`.

2. **Tự Chữa Lành Bị Động Tại Thời Điểm Truy Vấn (`sot search`):**  
   Nếu bạn chưa kịp chạy `sot reconcile` mà Agent đã tìm kiếm từ khóa trúng vào file vừa xóa, `TrustVerifier.verify_hit` kiểm tra `os.path.exists(path) == False`. Nó quét tìm rehome nhưng không thấy, sau đó **tự động xóa bản ghi ngay trong lượt tìm kiếm đó** và trả về nhãn `[REMOVED]`:

```python
# src/sot_graph/verifier.py:139-141
db.delete_path(requested)
return "REMOVED", 0.0, requested
```

> [!TIP]
> **Kết quả:** Agent không bao giờ bị ảo giác vì node rác bị tiêu diệt ngay tại thời điểm chạm vào.

</details>

---

<details>
<summary><h3>Q6: Khi một file bị di chuyển thư mục (mv src/utils.py src/helpers/utils.py), cơ chế Auto-Rehome diễn ra ra sao?</h3></summary>

Khi một file bị di chuyển hoặc đổi tên thư mục cha, đường dẫn cũ trở thành không hợp lệ. Hàm `TrustVerifier.find_rehome` xử lý như sau:

1. Tách `basename = "utils.py"` từ đường dẫn cũ.
2. Duyệt nhanh cây thư mục dự án (bỏ qua các thư mục `node_modules`, `.git`, `venv`).
3. Nếu tìm thấy **DUY NHẤT 1 file** có tên `utils.py` tại vị trí mới `src/helpers/utils.py`:
   - Hệ thống gọi `db.update_node_path(node_id, old_path, new_path)`.
   - Cập nhật lại đường dẫn trong `graph_nodes` và nhãn `label`.
   - Trả về nhãn `[REBUILT]` kèm đường dẫn mới nhất.
4. Nếu tìm thấy $\ge 2$ file trùng tên (mơ hồ - *ambiguous match*): Hệ thống từ chối đoán bừa để đảm bảo an toàn tuyệt đối, xóa đường dẫn cũ và đợi lượt `reconcile` tiếp theo.

</details>

---

<details>
<summary><h3>Q7: Tại sao database không bao giờ bị "dơ" hay chứa hàm rác khi lập trình viên xóa bớt hàm trong code?</h3></summary>

Nhiều hệ thống đồ thị bị lỗi "tích tụ rác" vì chúng dùng câu lệnh `UPSERT` (chỉ cập nhật hoặc thêm mới, không xóa hàm cũ nếu trong file đã xóa định nghĩa hàm đó).

`sot-graph` sử dụng mô hình **Toàn Quyền Theo Tệp (Atomic Full-File Replacement)** trong `Database.commit_file_batch`:

```python
# src/sot_graph/db.py:216-218
# Xóa sạch toàn bộ node, quan hệ và pending edge cũ thuộc về tệp này
self.conn.execute("DELETE FROM graph_nodes WHERE path = ?", (path,))
self.conn.execute("DELETE FROM graph_edges WHERE path = ?", (path,))
self.conn.execute("DELETE FROM pending_edges WHERE path = ?", (path,))
```

Sau đó mới chèn lại chính xác các hàm, class và lời gọi hàm vừa trích xuất được từ phiên bản hiện tại của tệp. Do đó, nếu bạn xóa 3 hàm trong `service.py`, 3 hàm đó lập tức biến mất khỏi database trong cùng 1 transaction ACID.

</details>

---

## 🤖 3. Tích Hợp AI Agent & Giao Thức MCP (AI Agent Integration)

<details>
<summary><h3>Q8: Làm thế nào để tích hợp sot-graph vào Oh My Pi (OMP), Claude Code, Cursor, OpenCode?</h3></summary>

`sot-graph` cung cấp sẵn 3 adapter chính thức trong thư mục `src/sot_graph/adapters/`:

1. **Tích hợp Oh My Pi / OMP (`~/.omp`):**  
   Copy file TypeScript extension vào thư mục extensions:
   ```bash
   cp src/sot_graph/adapters/omp_extension.ts ~/.omp/agent/extensions/sot_graph.ts
   ```
   Cung cấp cho Agent 4 tool tự động: `sot_search`, `sot_explore`, `sot_reconcile`, `sot_insert`.

2. **Tích hợp Claude Code / Cursor / Codex:**  
   Thêm nội dung của `src/sot_graph/adapters/AGENTS.md` vào tệp `AGENTS.md` hoặc `.cursorrules` của repository để định hướng Agent tuân thủ quy trình tra cứu tri thức trước khi viết code mới.

3. **Tích hợp OpenCode:**  
   Khai báo công cụ trong file cấu hình `.opencode.json` trỏ tới `src/sot_graph/adapters/opencode_tools.json`.

</details>

---

<details>
<summary><h3>Q9: MCP (Model Context Protocol) Server cung cấp những công cụ gì cho LLM? Tại sao MCP lại là Read-Only?</h3></summary>

Lệnh `./bin/sot mcp` khởi chạy một MCP Stdio Server tiêu chuẩn cung cấp 5 công cụ và 2 tài nguyên cho LLM:

- `sot_search`: Tìm kiếm tri thức đã được xác minh đĩa cứng.
- `sot_explore`: Duyệt đồ thị quan hệ phụ thuộc và lời gọi hàm đa tầng.
- `sot_verify_drift`: Kiểm toán độ lệch giữa đồ thị và filesystem mà không sửa đổi DB.
- `sot_architecture_report`: Sinh báo cáo kiến trúc Markdown tóm tắt kèm phát hiện God Nodes.
- `sot_communities`: Liệt kê các cụm chức năng và điểm số Cohesion.
- **Tài nguyên MCP:** `sot://stats` (thống kê tổng thể) và `sot://node/{id}` (chi tiết thực thể).

> [!WARNING]
> **Tại sao MCP lại Read-Only?**  
> Để đảm bảo tính *Deterministic* và không gây tranh chấp khóa SQLite (Database Lock contention) khi có hàng chục Subagent AI cùng truy vấn đồng thời. Mọi thao tác ghi chỉ diễn ra qua tiến trình Reconciler độc lập.

</details>

---

<details>
<summary><h3>Q10: Quy trình làm việc chuẩn của AI Agent (Knowledge Reuse Protocol) khi bắt đầu một task lập trình là gì?</h3></summary>

Để tối ưu token và tránh viết lại mã nguồn đã có trong dự án, Agent cần tuân thủ quy trình 4 bước:

1. **Bước 1 - Tra Cứu Tri Thức Đã Có:**  
   `sot search "<tính năng hoặc hàm cần tìm>"`
2. **Bước 2 - Đánh Giá Độ Tin Cậy (Trust Verdict):**  
   Nếu là `[STRONG]`: Đọc thẳng vào file và tái sử dụng. Nếu là `[WEAK]`: Mở file kiểm tra nhanh.
3. **Bước 3 - Khảo Sát Tác Động (Impact Analysis):**  
   `sot explore "<tên_hàm_hoặc_class_sắp_sửa>"` để xem những module nào đang phụ thuộc vào nó.
4. **Bước 4 - Lưu Lại Quyết Định (Knowledge Persistence):**  
   Sau khi hoàn thành giải pháp phức tạp:  
   `sot insert --title "Giải pháp X" --body "Chi tiết cách fix..." --keywords "tag1,tag2"`

</details>

---

## 📊 4. Phân Tích Đồ Thị & Trực Quan Hóa (Graph Analytics)

<details>
<summary><h3>Q11: "God Node" là gì? Thuật toán phát hiện God Node và tính toán 2-hop Blast Radius (bán kính ảnh hưởng) như thế nào?</h3></summary>

**God Node (Nút Siêu Kết Nối / Hub Trung Tâm):** Là các class, module hoặc hàm có bậc kết nối (degree) vượt trội, tập trung quá nhiều phụ thuộc của hệ thống. Nếu một God Node bị lỗi hoặc thay đổi API, nó có thể làm gãy hàng loạt module khác.

**Thuật toán phát hiện (`src/sot_graph/analytics/diagnostics.py`):**
1. Tính giá trị trung bình $\mu$ và độ lệch chuẩn $\sigma$ của bậc kết nối toàn bộ đồ thị:
   $$\text{Cutoff} = \mu + \text{threshold\_sigma} \times \sigma$$
2. Bất kỳ nút nào có $\text{Degree} \ge \text{Cutoff}$ (mặc định $\text{sigma} = 1.5$) được phân loại là **God Node**.
3. **2-hop Blast Radius:** Thuật toán duyệt BFS đúng 2 bước từ God Node để đếm số lượng thực thể chịu ảnh hưởng trực tiếp và gián tiếp:
   - $\text{Blast} \ge 25$: Nguy cơ `[CRITICAL]`.
   - $\text{Blast} \ge 15$: Nguy cơ `[HIGH]`.
   - $\text{Blast} \ge 8$: Nguy cơ `[MEDIUM]`.

```bash
# Lệnh phát hiện God Nodes và xuất báo cáo
./bin/sot report --sigma 1.5 --min-size 2 -o ARCHITECTURE_REPORT.md
```

</details>

---

<details>
<summary><h3>Q12: Thuật toán phát hiện cộng đồng (Community Detection) và hệ số Modularity (Q) / Cohesion Score có ý nghĩa gì?</h3></summary>

Thuật toán `Label Propagation / Louvain` trong `sot_graph.analytics` tự động gom các file và hàm có tần suất gọi nhau dày đặc thành các **Cộng Đồng Chức Năng (Functional Communities)**:

- **Hệ số Modularity ($Q \in [-0.5, 1.0]$):** Đo lường chất lượng phân rã kiến trúc. $Q > 0.3$ thể hiện cấu trúc mã nguồn có tính module hóa cao, ranh giới rõ ràng.
- **Điểm Số Cohesion ($C \in [0.0, 1.0]$):** Tỷ lệ liên kết nội bộ trong cụm so với tổng liên kết:
  $$C = \frac{E_{\text{internal}}}{E_{\text{internal}} + E_{\text{external}}}$$
  Nếu $C < 0.4$, cụm đó đang bị phụ thuộc quá nhiều vào bên ngoài (*Tightly Coupled*) và cần được xem xét tái cấu trúc (Refactoring).

```bash
# Lệnh kiểm tra các cụm cộng đồng
./bin/sot cluster --min-size 3
```

</details>

---

<details>
<summary><h3>Q13: Làm thế nào để xuất đồ thị sang Interactive HTML D3.js, GraphRAG JSON, Obsidian Vault và GraphML?</h3></summary>

`sot-graph` tích hợp sẵn bộ xuất đa định dạng độc lập trong `src/sot_graph/export/`:

```bash
# 1. Trực quan hóa HTML D3.js tương tác và mở trên trình duyệt
./bin/sot viz -o graph.html --open

# 2. Xuất dữ liệu phân cấp cho các hệ thống GraphRAG
./bin/sot export -f graphrag -o graphrag_dataset.json

# 3. Xuất toàn bộ đồ thị thành Obsidian Vault (kèm Markdown Wikilinks [[Node]])
./bin/sot export -f obsidian -o my_obsidian_vault/

# 4. Xuất GraphML chuẩn XML cho Gephi, Cytoscape, NetworkX
./bin/sot export -f graphml -o graph.graphml
```

</details>

---

## ⚙️ 5. Vận Hành, Bảo Trì & Hiệu Năng (Ops & Maintenance)

<details>
<summary><h3>Q14: Khi nào cần chạy sot clean và sot vacuum? Điểm khác biệt giữa --dry-run và thực thi thật là gì?</h3></summary>

Trong quá trình phát triển dài hạn, database có thể tích tụ không gian trống (freelist pages) hoặc các quan hệ mồ côi:

- **`sot clean`:** Quét và xóa các đường dẫn không còn trên đĩa, các cạnh đồ thị mồ côi (orphaned edges), và pending edges không còn mục tiêu.
  - `--dry-run`: Chỉ tính toán và báo cáo số lượng bản ghi sẽ bị xóa dưới dạng JSON, **tuyệt đối không chạm vào DB**.
  - `--all --yes`: Xóa toàn bộ dữ liệu đồ thị để chuẩn bị index mới từ đầu.
- **`sot vacuum`:** Thực hiện Checkpoint SQLite WAL (Write-Ahead Log) và chạy `VACUUM` để giải phóng dung lượng ổ cứng, chống phân mảnh trang dữ liệu.

```bash
# Kiểm tra trước số lượng rác
./bin/sot clean --dry-run --json

# Dọn dẹp an toàn
./bin/sot clean --json

# Thu gọn và giải phóng dung lượng đĩa
./bin/sot vacuum --analyze
```

</details>

---

<details>
<summary><h3>Q15: Làm thế nào để chạy kiểm tra độ lệch (Drift Verification) trong pipeline CI/CD mà không gây lỗi hoặc sửa DB?</h3></summary>

Lệnh `sot verify` được thiết kế chuyên biệt cho các quy trình CI/CD và pre-commit hooks:

- Hoạt động ở chế độ **Read-Only tuyệt đối**: Không sửa đổi tệp SQLite, không tạo lock ghi.
- `sot verify`: Đối soát nhanh metadata (size, mtime) giữa database và filesystem.
- `sot verify --deep`: Đọc toàn bộ nội dung tệp và băm lại SHA-256 để phát hiện mọi độ lệch ẩn.
- **Mã trả về (Exit Code):** Trả về `0` nếu đồ thị hoàn toàn khớp với đĩa; trả về `1` nếu có độ lệch (drift) kèm danh sách tệp bị lệch.

```yaml
# Bước kiểm tra trong GitHub Actions / CI workflow
- name: Verify Knowledge Graph Drift
  run: ./bin/sot verify --deep --json
```

</details>

---

<details>
<summary><h3>Q16: Hiệu năng thực tế của sot-graph: Xử lý bao nhiêu file một giây? Tại sao đạt tốc độ dưới 25ms với RAM dưới 25MB?</h3></summary>

Kết quả đo đạc thực tế từ bộ Benchmark chính thức (trên chip Apple M1 Max):
- **Tốc độ Reconcile:** Xử lý và nạp đầy đủ AST cho **100 files trong ~24.1ms** (&gt; 4,000 files/giây đối với dirty-check).
- **Độ trễ truy vấn FTS5 BM25:** **~1.17ms** (P95) cho các câu truy vấn phức tạp.

**Lý do đạt được hiệu năng ấn tượng:**
1. **Adaptive Worker Threshold:** Các lô nhỏ (&lt; 16 tệp) chạy tuần tự trong tiến trình chính để loại bỏ 100% chi phí fork đa tiến trình (multiprocessing overhead); chỉ mở worker pool khi có khối lượng tệp lớn.
2. **Zero External Memory Footprint:** Sử dụng SQLite nhúng cấu hình `PRAGMA journal_mode=WAL` và `PRAGMA synchronous=NORMAL`, bộ nhớ RAM duy trì ổn định dưới 25MB.

</details>

---

## 🚨 6. Xử Lý Sự Cố & Tình Huống Thực Tế (Edge Cases)

<details>
<summary><h3>Q17: Nếu có 2 file trùng tên (VD: models/user.py và controllers/user.py) bị di chuyển, hệ thống xử lý thế nào để tránh gán nhầm?</h3></summary>

Đây là tình huống **Trùng tên cơ sở (Basename Collision)** khi di chuyển file.

```python
# src/sot_graph/verifier.py:73-78
if basename in files:
    cands.append(os.path.abspath(os.path.join(root, basename)))
    if len(cands) > 1:
        return None  # Trùng lặp - từ chối đoán bừa (Ambiguity Guard)
return cands[0] if len(cands) == 1 else None
```

Hàm `find_rehome` có cơ chế **Ambiguity Guard**: Nếu trong cây thư mục xuất hiện từ 2 file `user.py` trở lên, hệ thống lập tức trả về `None`. Nó **tuyệt đối không gán bừa**. Node cũ sẽ được thanh trừng an toàn và đợi lượt `sot reconcile` tiếp theo để nhận diện chính xác theo cấu trúc AST.

</details>

---

<details>
<summary><h3>Q18: Nếu dự án có file mã nguồn bị lỗi cú pháp (Syntax Error), Reconciler có bị crash không?</h3></summary>

**KHÔNG BAO GIỜ CRASH.**

Tất cả parser trong `src/sot_graph/extractor.py` và `_vendor/graphify/extract.py` đều được bọc trong các khối `try-except` phòng vệ:
- Nếu file Python bị `SyntaxError` hoặc file TypeScript thiếu dấu ngoặc, parser sẽ ghi nhận lỗi vào trường `error` nhưng vẫn **bảo lưu node tệp gốc (file node)**.
- Tiến trình Reconciler tiếp tục xử lý các file khác bình thường và trả về tổng kết số file `failed` trong `ReconcileSummary`.

</details>

---

<details>
<summary><h3>Q19: Làm thế nào để lưu trữ các quyết định kiến trúc (ADR) hoặc kinh nghiệm sửa bug phức tạp vào đồ thị tri thức?</h3></summary>

Bạn hoặc AI Agent có thể chèn các ghi chú tri thức (Virtual Knowledge Notes) bằng lệnh `sot insert`:

```bash
./bin/sot insert \
  --title "Quy tắc Transaction trong Database" \
  --body "Mọi thay đổi trên nhiều bảng liên quan bắt buộc phải bọc trong 'with self.conn:' để đảm bảo ACID và chống leak lock." \
  --path "src/sot_graph/db.py" \
  --keywords "sqlite,transaction,acid,concurrency"
```

Các ghi chú này nhận nhãn `[NOPATH]` (hoặc liên kết với tệp nếu có `--path`) và được lập chỉ mục FTS5 BM25. Khi Agent hỏi *"Làm sao để viết transaction an toàn?"*, hệ thống sẽ trả về ngay mỏ neo kiến thức này.

</details>

---

## 📄 License
MIT License. Copyright (c) 2026 Minh Giap.
