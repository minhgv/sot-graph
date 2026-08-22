# Ứng Dụng sot-graph Trong Vòng Đời Phát Triển Phần Mềm Trợ Lực AI (AI SDLC)

> **Cẩm nang chuyên sâu về việc tích hợp `sot-graph` làm Lớp Tri Thức Nguồn Chân Lý Duy Nhất (Single Source of Truth Knowledge Layer) cho AI Coding Agents.**
> *Loại bỏ Phantom Anchors, chống ảo giác đường dẫn, ngăn chặn tái tạo mã thừa (Cold Start Redundancy) và kiểm soát bán kính ảnh hưởng (Blast Radius).*

---

## 📑 Mục Lục
1. [Bối Cảnh & Vấn Đề Cốt Lõi Trong AI SDLC](#-1-bối-cảnh--vấn-đề-cốt-lõi-trong-ai-sdlc)
2. [Chi Tiết 6 Giai Đoạn AI SDLC Cùng sot-graph](#-2-chi-tiết-6-giai-đoạn-ai-sdlc-cùng-sot-graph)
   - [Phase 1: Khám Phá & Lập Kế Hoạch (Discovery & Architecture Scoping)](#phase-1-khám-phá--lập-kế-hoạch-discovery--architecture-scoping)
   - [Phase 2: Sinh Mã & Triển Khai Trong Active Coding Loop (Generation & Development)](#phase-2-sinh-mã--triển-khai-trong-active-coding-loop-generation--development)
   - [Phase 3: Tái Cấu Trúc & Giảm Thiểu Vùng Ảnh Hưởng (Refactoring & Blast Radius Mitigation)](#phase-3-tái-cấu-trúc--giảm-thiểu-vùng-ảnh-hưởng-refactoring--blast-radius-mitigation)
   - [Phase 4: Đánh Giá & CI/CD Verification Gate (Code Review & Drift Auditing)](#phase-4-đánh-giá--cicd-verification-gate-code-review--drift-auditing)
   - [Phase 5: Lưu Trữ & Kế Thừa Tri Thức Kiến Trúc (Knowledge Retention & ADR)](#phase-5-lưu-trữ--kế-thừa-tri-thức-kiến-trúc-knowledge-retention--adr)
   - [Phase 6: Bảo Trì, Vệ Sinh & Tối Ưu Hệ Thống (Maintenance & Graph Hygiene)](#phase-6-bảo-trì-vệ-sinh--tối-ưu-hệ-thống-maintenance--graph-hygiene)
3. [Bảng So Sánh: AI SDLC Truyền Thống vs AI SDLC Với sot-graph](#-3-bảng-so-sánh-ai-sdlc-truyền-thống-vs-ai-sdlc-với-sot-graph)
4. [Tích Hợp Tự Động Vào CI/CD & Git Hooks](#-4-tích-hợp-tự-động-vào-cicd--git-hooks)
5. [Cấu Hình Mẫu Cho AI Coding Agents (AGENTS.md)](#-5-cấu-hình-mẫu-cho-ai-coding-agents-agentsmd)

---

## 🎯 1. Bối Cảnh & Vấn Đề Cốt Lõi Trong AI SDLC

Trong kỷ nguyên các **AI Coding Agent** (như Oh My Pi, Claude Code, Cursor, Windsurf, Devin) trực tiếp tham gia viết code hàng ngày, quy trình phát triển phần mềm truyền thống (SDLC) đã chuyển dịch thành **AI-Assisted SDLC**.

Tuy nhiên, các hệ thống AI Coding hiện nay đang gặp phải **3 "Căn Bệnh Trầm Kha"**:

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                        3 NGHẼN CẢNH LỚN NHẤT CỦA AI CODING AGENT                        │
├──────────────────────────────┬─────────────────────────────┬────────────────────────────┤
│   1. COLD START REDUNDANCY   │     2. PHANTOM ANCHORS      │   3. REFACTOR BLIND SPOT   │
│                              │                             │                            │
│  Mỗi phiên làm việc bắt đầu  │  Agent nhớ file/hàm đã bị   │  Sửa đổi 1 hàm trung tâm   │
│  từ số 0. Agent tự viết lại  │  xóa hoặc đổi tên từ trước. │  làm gãy 15 module ở xa    │
│  hàm tiện ích đã có sẵn, làm │  Sinh patch trỏ vào đường   │  mà Agent hoàn toàn không  │
│  phình to codebase gấp 3 lần.│  dẫn chết (Dead Paths).     │  hề hay biết.              │
└──────────────────────────────┴─────────────────────────────┴────────────────────────────┘
```

`sot-graph` sinh ra nhằm cung cấp một **Lớp Tri Thức Xác Thực Vật Lý Trên Ổ Đĩa (Physically Verified Knowledge Layer)**. Bằng cách kết hợp **Filesystem làm Nguồn Chân Lý Duy Nhất (SSOT)**, **SQLite FTS5 + WAL**, và **Thuật Toán Đồ Thị Trực Tiếp**, `sot-graph` đồng hành xuyên suốt 6 giai đoạn phát triển phần mềm.

---

## 🚀 2. Chi Tiết 6 Giai Đoạn AI SDLC Cùng sot-graph

```
                  ┌────────────────────────────────────────────────────────┐
                  │              VÒNG ĐỜI AI SDLC VỚI SOT-GRAPH             │
                  └────────────────────────────────────────────────────────┘
                                              │
    ┌─────────────────────────────────────────┼─────────────────────────────────────────┐
    │                                         │                                         │
    ▼                                         ▼                                         ▼
[ 1. KHÁM PHÁ & LẬP KẾ HOẠCH ]     [ 2. SINH MÃ & PHÁT TRIỂN ]        [ 3. TÁI CẤU TRÚC & REFACTOR ]
• Kiểm tra tri thức tái sử dụng    • Tra cứu symbol xác minh đĩa     • Phân tích 2-hop Blast Radius
• Tránh viết lại hàm có sẵn        • Auto-Heal khi file đổi vị trí   • Đánh giá God Nodes & Cohesion
• Lập bản đồ cộng đồng Louvain     • Pending Edge giải quyết import  • Đo Modularity Q ngăn gãy API
    │                                         │                                         │
    ├─────────────────────────────────────────┼─────────────────────────────────────────┤
    │                                         │                                         │
    ▼                                         ▼                                         ▼
[ 4. CODE REVIEW & CI/CD ]         [ 5. LƯU TRỮ TRI THỨC (ADR) ]      [ 6. BẢO TRÌ & HYGIENE ]
• Phát hiện Architectural Drift   • Ghi chú giải pháp hiểm hóc      • Dọn dẹp rác với `sot clean`
• Auto-Purge đường dẫn đã xóa     • Không mất context giữa session  • Thu gọn DB với `sot vacuum`
• Gatekeeper kiểm tra lệch pha    • Tra cứu FTS5 BM25 tức thì       • Giữ hiệu năng Sub-Millisecond
```

---

### Phase 1: Khám Phá & Lập Kế Hoạch (Discovery & Architecture Scoping)

#### Thách thức thực tế
- Khi nhận một user prompt (ví dụ: *"Hãy viết chức năng xác thực token JWT kèm phân quyền role"*), Agent thường bắt đầu code ngay mà không biết rằng trong thư mục `src/auth/` hoặc `utils/` đã có sẵn các helper mã hóa HMAC, parse claims, hoặc validate expiration.
- Agent dùng lệnh `grep`/`find` thô sơ làm tràn ngập context window với hàng nghìn dòng code không liên quan, dẫn tới cạn token và giảm sút khả năng suy luận logic.

#### Cách `sot-graph` giải quyết
1. **Tra Cứu Nhanh & Phân Loại Mức Độ Tin Cậy (`sot search` / MCP `sot_search`):**
   Agent chỉ cần 1 câu lệnh để truy vấn toàn bộ codebase qua SQLite FTS5 (BM25 score):
   ```bash
   ./bin/sot search "jwt token validation role"
   ```
   Hệ thống phản hồi tức thì (< 1.2ms) kèm nhãn **Trust Verdict**:
   - `[STRONG]`: File tồn tại vật lý và chứa ≥ 50% từ khóa (Agent có thể dùng ngay).
   - `[WEAK]`: Khớp ngữ nghĩa tiêu đề (cần đọc lướt trước khi dùng).
2. **Khảo Sát Ranh Giới Module Qua Cộng Đồng Louvain (`sot cluster` / `sot report`):**
   Agent hiểu được kiến trúc tổng quan mà không cần đọc từng file:
   ```bash
   ./bin/sot cluster --min-size 3
   ```
   Kết quả trả về danh sách các cụm chức năng (Auth, Billing, Notifications...) cùng hệ số Modularity $Q$, giúp Agent đặt file mới đúng vị trí kiến trúc.

---

### Phase 2: Sinh Mã & Triển Khai Trong Active Coding Loop (Generation & Development)

#### Thách thức thực tế
- **Phantom Anchors**: Lập trình viên vừa đổi tên file `src/services/user_service.py` thành `src/core/services/user.py`. Agent nhớ đường dẫn cũ trong context, tạo ra đoạn import `from src.services.user_service import UserService` $\rightarrow$ runtime crash.
- **Import chéo và thứ tự index**: File A import Class từ File B chưa được lưu vào đồ thị, gây đứt gãy đồ thị quan hệ.

#### Cách `sot-graph` giải quyết
1. **Cơ Chế Tự Động Định Vị Lại (Auto-Rehome `[REBUILT]`):**
   Khi Agent tra cứu `UserService`, nếu đường dẫn cũ không còn, `verifier.py` tự động quét basename trên đĩa, phát hiện vị trí mới tại `src/core/services/user.py`, cập nhật lại SQLite và trả về kết quả `[REBUILT]`. Agent lập tức viết đúng đường dẫn mới!
2. **Đồng Bộ Hai Chiều Cho Pending Edges (`db.resolve_pending_edges`):**
   Mọi liên kết gọi hàm/import chưa rõ đích đến được lưu tạm tại `pending_edges`. Ngay khi file đích được parse, câu lệnh SQL nguyên tử tự động thăng hạng chúng thành `graph_edges` hoàn chỉnh.
3. **Đồng Bộ Siêu Nhanh Trong Micro-Giây (Fast Dirty Check):**
   Trong vòng lặp sinh mã, Agent chỉ mất **~24.1ms** để gọi `sot reconcile`. Reconciler so sánh cặp `(size, mtime_ms)` $O(1)$, chỉ parse lại đúng 1 file vừa thay đổi.

---

### Phase 3: Tái Cấu Trúc & Giảm Thiểu Vùng Ảnh Hưởng (Refactoring & Blast Radius Mitigation)

#### Thách thức thực tế
- Khi Agent được yêu cầu *"Thay đổi chữ ký hàm `process_payment(amount)` thành `process_payment(amount, currency, idempotency_key)`"*, Agent thường chỉ sửa đúng định nghĩa hàm và 1-2 vị trí gọi gần nhất.
- Hàng chục lời gọi gián tiếp ở các module khác bị bỏ sót, gây lỗi âm thầm khi lên môi trường staging.

#### Cách `sot-graph` giải quyết
1. **Phân Tích 2-hop Blast Radius (`sot explore` / MCP `sot_explore`):**
   Trước khi sửa hàm, Agent chạy lệnh:
   ```bash
   ./bin/sot explore "PaymentService.process_payment" --depth 2
   ```
   Hệ thống thực hiện duyệt BFS đúng 2 bước, liệt kê toàn bộ:
   - Các hàm gọi trực tiếp (Incoming Edges - Hop 1).
   - Các service cấp cao phụ thuộc gián tiếp (Upstream Callers - Hop 2).
2. **Cảnh Báo Nút Siêu Kết Nối (God Node Diagnostics):**
   Nếu hàm/class vượt quá ngưỡng $\text{Cutoff} = \mu + 1.5\sigma$, hệ thống gắn cờ cảnh báo:
   ```
   ⚠️ WARNING: 'PaymentService' is a GOD NODE with Blast Radius = 28 [CRITICAL]
   Modifying this symbol will impact 5 architectural communities.
   ```
   Agent sẽ tự động bổ sung test case và cập nhật toàn bộ các caller liên quan.
3. **Đánh Giá Điểm Cohesion Cụm ($C < 0.4$):**
   Hệ thống chỉ ra các module bị phụ thuộc chéo quá mức (Tightly Coupled) để Agent đề xuất tách interface phù hợp.

---

### Phase 4: Đánh Giá & CI/CD Verification Gate (Code Review & Drift Auditing)

#### Thách thức thực tế
- Khi nhiều Agent và lập trình viên cùng merge code vào nhánh `main`, các file cũ bị xóa nhưng tài liệu kiến trúc không được cập nhật. Codebase rơi vào trạng thái "lệch pha" (**Architectural Drift**).

#### Cách `sot-graph` giải quyết
1. **Kiểm Toán Trôi Dạt Sâu (`sot verify --deep` / MCP `sot_verify_drift`):**
   Trong pipeline CI/CD hoặc Pull Request check, chạy lệnh:
   ```bash
   ./bin/sot verify --deep
   ```
   Hệ thống đối chiếu hash SHA-256 của từng file vật lý với journal. Nếu phát hiện sai lệch:
   - Tự động thanh trừng (**Auto-Purge**) các đường dẫn đã bị xóa vĩnh viễn (`[REMOVED]`).
   - Xuất báo cáo tỷ lệ sai lệch (**Drift Percentage**).
2. **CI/CD Quality Gate:**
   Nếu tỷ lệ drift vượt ngưỡng cho phép, pipeline CI sẽ tự động chạy `sot reconcile` để đưa đồ thị về trạng thái nhất quán 100% trước khi deploy.

---

### Phase 5: Lưu Trữ & Kế Thừa Tri Thức Kiến Trúc (Knowledge Retention & ADR)

#### Thách thức thực tế
- **Context Reset**: Mỗi khi mở một session mới, AI Agent bị "mất trí nhớ". Một bài học đắt giá về cách xử lý deadlock trong PostgreSQL vừa được Agent giải quyết hôm qua, hôm nay một Agent khác lại mắc đúng sai lầm đó.

#### Cách `sot-graph` giải quyết
1. **Mỏ Neo Kiến Thức Ảo (`sot insert` & `[NOPATH]`):**
   Sau khi hoàn thành một bug-fix phức tạp hoặc đưa ra quyết định kiến trúc quan trọng (Architecture Decision Record - ADR), Agent chủ động lưu lại vào SQLite:
   ```bash
   ./bin/sot insert \
     --title "Postgres Deadlock Prevention in Order Processing" \
     --body "Always acquire row locks in deterministic ID ascending order (SELECT FOR UPDATE ORDER BY id ASC)." \
     --keywords "postgres,deadlock,locking,order_service"
   ```
2. **Kế Thừa Vĩnh Viễn Không Cần Đọc Lại File:**
   Trong các phiên làm việc tiếp theo, khi một Agent khác gõ:
   ```bash
   ./bin/sot search "deadlock order locking"
   ```
   Node `[NOPATH]` sẽ xuất hiện ngay đầu danh sách kết quả, đóng vai trò là kim chỉ nam hướng dẫn Agent tuân thủ chuẩn kiến trúc của dự án.

---

### Phase 6: Bảo Trì, Vệ Sinh & Tối Ưu Hệ Thống (Maintenance & Graph Hygiene)

#### Thách thức thực tế
- Sau hàng tháng phát triển với hàng nghìn lần thêm/sửa/xóa file, database có thể tích tụ các orphan nodes, phân mảnh B-Tree hoặc làm chậm tốc độ tra cứu FTS5.

#### Cách `sot-graph` giải quyết
1. **Lệnh Dọn Dẹp An Toàn (`sot clean`):**
   - Hỗ trợ chế độ `--dry-run` để kiểm tra trước các node rác sẽ bị xóa mà không gây rủi ro:
     ```bash
     ./bin/sot clean --dry-run
     ```
   - Thực thi dọn sạch hoàn toàn các dead paths và orphan edges:
     ```bash
     ./bin/sot clean --all --yes
     ```
2. **Thu Gọn & Tối Ưu B-Tree (`sot vacuum`):**
   - Tái cấu trúc cơ sở dữ liệu SQLite FTS5, tối ưu hóa các trang disk page để duy trì độ trễ truy vấn dưới **1.2ms**:
     ```bash
     ./bin/sot vacuum
     ```
3. **Cơ Chế Khóa SQLite WAL An Toàn:**
   - Trong quá trình bảo trì, các Agent khác vẫn có thể thực hiện lệnh `search` và `explore` song song nhờ chế độ `WAL` (Write-Ahead Logging) và kết nối `mode=ro` (Read-Only) không bị block.

---

## 📊 3. Bảng So Sánh: AI SDLC Truyền Thống vs AI SDLC Với sot-graph

| Tiêu Chí Đánh Giá | AI SDLC Truyền Thống (Không có sot-graph) | AI SDLC Với sot-graph |
| :--- | :--- | :--- |
| **Độ Chính Xác Vị Trí File** | **Kém (Dễ Ảo Giác)**: Agent thường đoán mò đường dẫn cũ hoặc sinh code trỏ vào file đã bị xóa. | **Tuyệt Đối (100% Verified)**: Mọi node đều qua cổng `TrustVerifier` đối chiếu trực tiếp trên đĩa. |
| **Khả Năng Tái Sử Dụng Mã** | **Thấp**: Thường xuyên viết lại helper/utility đã có sẵn (Cold Start Redundancy). | **Cao**: `sot search` với FTS5 BM25 giúp Agent tìm thấy hàm có sẵn chỉ trong 1ms. |
| **Kiểm Soát Khi Refactor** | **Mù Quáng (Blind Edits)**: Chỉ sửa cục bộ 1 file, không biết các caller gián tiếp bị gãy. | **Toàn Diện**: Phân tích **2-hop Blast Radius** và phát hiện **God Nodes** trước khi sửa. |
| **Độ Trễ Tra Cứu Ngữ Cảnh** | **Chậm (10s - 30s)**: Phải đọc toàn bộ file hoặc gọi Vector DB / Embeddings qua mạng. | **Cực Nhanh (~1.17ms)**: Tra cứu trực tiếp trên SQLite FTS5 nội bộ máy. |
| **Tài Nguyên Hệ Thống** | **Nặng nề**: Cần Docker, Vector DB Server, background daemons chạy ngầm tốn 1-2GB RAM. | **Siêu Nhẹ (Zero-Daemon)**: Khởi động tức thì qua CLI/MCP, tốn `< 25MB RAM`, không daemon. |
| **Tự Chữa Lành (Self-Healing)** | **Không có**: Khi đổi tên thư mục (`mv`), toàn bộ memory/vector index của Agent bị hỏng. | **Tự Động**: `Auto-Rehome` tự định vị lại file bị di chuyển; `Auto-Purge` tự xóa dead paths. |

---

## ⚙️ 4. Tích Hợp Tự Động Vào CI/CD & Git Hooks

### 1. Git Pre-Commit Hook (`.git/hooks/pre-commit`)
Tự động đồng bộ đồ thị tri thức và ngăn chặn commit code khi đồ thị bị trôi dạt:

```bash
#!/bin/bash
# .git/hooks/pre-commit
echo "[sot-graph] Reconciling knowledge graph before commit..."
./bin/sot reconcile --batch-size 64

# Kiểm tra tính toàn vẹn
./bin/sot verify
if [ $? -ne 0 ]; then
  echo "[sot-graph] ❌ Verification failed. Please resolve discrepancies."
  exit 1
fi
echo "[sot-graph]  Knowledge graph is fully in sync with filesystem."
```

### 2. GitHub Actions Workflow (`.github/workflows/sot_verification.yml`)
Kiểm toán kiến trúc và cập nhật báo cáo đồ thị tự động khi có Pull Request:

```yaml
name: SOT-Graph Architecture Audit

on:
  push:
    branches: [ main, master ]
  pull_request:
    branches: [ main, master ]

jobs:
  verify-graph:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Run Test Suite
        run: |
          PYTHONPATH="src" python3 -m unittest discover -s tests -p "test_*.py" -v

      - name: Deep Verify Knowledge Graph
        run: |
          ./bin/sot reconcile
          ./bin/sot verify --deep

      - name: Generate Architecture Report
        run: |
          ./bin/sot report --sigma 1.5 --min-size 2 -o ARCHITECTURE_REPORT.md

      - name: Upload Architecture Artifact
        uses: actions/upload-artifact@v4
        with:
          name: architecture-report
          path: ARCHITECTURE_REPORT.md
```

---

## 🤖 5. Cấu Hình Mẫu Cho AI Coding Agents (AGENTS.md)

Thêm đoạn quy ước sau vào file `AGENTS.md` hoặc `.cursorrules` ở thư mục gốc dự án của bạn để mọi AI Coding Agent (Oh My Pi, Claude Code, Cursor, Windsurf) tự động tuân thủ quy trình:

```markdown
## SOT-Graph Knowledge Reuse & Architecture Protocol

Trước khi thực hiện bất kỳ thay đổi mã nguồn, tính năng mới hoặc tái cấu trúc (Refactoring):

1. **Kiểm tra tri thức tái sử dụng (Tránh Cold Start Redundancy):**
   Chạy lệnh: `sot search "<chức_năng_hoặc_từ_khóa>"`
   - `[STRONG]`: Độ tin cậy tuyệt đối - Sử dụng lại hàm/class tại file:dòng được chỉ định.
   - `[WEAK]`: Khớp ngữ nghĩa - Đọc lướt nội dung file trước khi quyết định viết mới.
   - `[REBUILT]`: File đã được tự động định vị lại sau khi đổi tên - Dùng đường dẫn mới nhất.

2. **Phân tích vùng ảnh hưởng trước khi sửa hàm cốt lõi (Blast Radius Check):**
   Chạy lệnh: `sot explore "<tên_hàm_hoặc_class>" --depth 2`
   - Đọc kỹ danh sách caller trực tiếp (Hop 1) và gián tiếp (Hop 2) để cập nhật đồng bộ.
   - Nếu biểu tượng được gắn nhãn `GOD NODE`, chú ý kiểm tra lại toàn bộ các test case liên quan.

3. **Đồng bộ hóa sau khi hoàn thành code:**
   Chạy lệnh: `sot reconcile` để cập nhật trạng thái đồ thị tri thức mới nhất.

4. **Lưu trữ quyết định kiến trúc quan trọng (Knowledge Retention):**
   Sau khi giải quyết xong một lỗi hiểm hóc hoặc quy ước kiến trúc mới, lưu lại:
   `sot insert --title "<Tiêu Đề>" --body "<Mô tả chi tiết giải pháp>" --keywords "k1,k2"`
```

---

## 📄 License
MIT License. Bản quyền thuộc về Minh Giap (2026).
