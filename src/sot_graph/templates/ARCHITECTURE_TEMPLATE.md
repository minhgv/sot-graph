# SOT-GRAPH ARCHITECTURE REPORT TEMPLATE (Dual-Target: Human & AI)

> **Mục đích:** Bản mẫu chuẩn hóa 6 phần cho AI Agent / LLM khi nhận yêu cầu: *"Xuất báo cáo kiến trúc"*, *"Tổng quan hệ thống"*, *"Architecture Report"*.
> **Nguyên tắc Ingestion:** LLM CHỈ đọc các file Fact Bundle trong `.sot/bundle/` (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`) và điền dữ liệu theo cấu trúc chuẩn dưới đây.

### Markdown, LaTeX & Mermaid Rendering Rules (BẮT BUỘC TUÂN THỦ)
1. **Mermaid Diagrams:**
   - Mọi nhãn của Node và Subgraph BẮT BUỘC phải đặt trong dấu nháy kép: `NODE["Tên node"]`, `subgraph ID ["Tiêu đề subgraph"]`.
   - TUYỆT ĐỐI KHÔNG dùng ký tự pipe đơn `|` bên trong nhãn node (dùng `/` hoặc `\|` để thay thế).
   - Luôn chừa 1 dòng trống trước và sau khối ````mermaid`.
2. **Ký hiệu Toán học & Unicode (Khuyến nghị dùng Unicode chuẩn):**
   - Ưu tiên sử dụng ký tự Unicode trực tiếp: `Q ≥ 0.650`, `Q = 0.371`, `≈ 400`, `State ∈ { Initial, Loading, Success(data), Failure(error) }`.
   - TUYỆT ĐỐI KHÔNG dùng dấu `$` toán học bên trong ô bảng biểu Markdown (Table cells), tiêu đề hoặc danh sách bullet để tránh lỗi hiển thị raw `$` trên GitHub, VS Code, Obsidian và công cụ xuất DOCX.
3. **Markdown Tables & Text:**
   - Trong bảng markdown, không dùng ký tự `<` hoặc `>` đứng trước số một cách trần trụi; BẮT BUỘC dùng `&lt;`, `&gt;` hoặc Unicode `≤`, `≥`.
   - Không để ký tự pipe `|` không escape làm vỡ cấu trúc cột bảng.

---

# [TÊN DỰ ÁN] — BÁO CÁO KIẾN TRÚC & PHÂN TÍCH HỆ THỐNG TOÀN DIỆN

**Nguồn phân tích:** Single Source of Truth (`sot-graph`)  
**Mục tiêu:** Bóc tách kiến trúc tổng thể, phân rã chi tiết các modules & chức năng con trong phạm vi bundle đã sinh theo User Role, State Machine, Cron SLA và Khuyến nghị tối ưu.  
**Pattern & Modularity:** [Tên Pattern kiến trúc] — Modularity Score (Q = [Score])

---

## 1. TỔNG QUAN HỆ THỐNG & SƠ ĐỒ CONTAINER TỔNG THỂ (C4-CONTAINER HLD)

### 1.1 Bản chất & Định vị Hệ thống
* Tóm tắt mục đích cốt lõi, đối tượng phục vụ, stack công nghệ chính (Backend, Frontend, Mobile, DB, SSO/Auth).

### 1.2 Sơ đồ C4 Container Tổng thể (Mermaid HLD)
```mermaid
graph TD
    subgraph Client_Layer ["Kênh Người Dùng & Giao Tiếp Đa Điểm"]
        WEB["Web Admin / Backoffice"]
        PORTAL["Customer Self-Service Portal"]
        MOBILE["Mobile App / Mini-App"]
        EXT["B2B / Third-Party REST Clients"]
    end

    subgraph Gateway_Auth ["Tầng Cổng Giao Tiếp & Định Danh"]
        API_GW["API Gateway / Headless Router"]
        AUTH_SSO["Authentication / SSO Provider"]
    end

    subgraph Core_Business_Domains ["Cụm Modules Nghiệp Vụ Chính"]
        %% Liệt kê các Cụm Bounded Contexts
        GRP_1["Cụm 1: Nền tảng & Cấu hình Cơ sở"]
        GRP_2["Cụm 2: Dịch vụ & Khách hàng"]
        GRP_3["Cụm 3: Bán hàng, Đơn hàng & Vận hành"]
        GRP_4["Cụm 4: Thuê bao, Hóa đơn & Tài chính"]
        GRP_5["Cụm 5: Kênh Tương tác Số & Báo cáo"]
    end

    subgraph External_Integrations ["Hệ Thống Tích Hợp Ngoại Vi"]
        EXT_1["Hệ thống Ký số / V-Office"]
        EXT_2["Hệ thống Cước / Viễn thông"]
        EXT_3["Cổng Thanh toán / Ngân hàng"]
        EXT_4["Core ERP / Kế toán Tổng"]
    end

    %% Wiring connections
    Client_Layer --> Gateway_Auth
    Gateway_Auth --> Core_Business_Domains
    Core_Business_Domains --> External_Integrations
```

---

## 2. PHÂN RÃ CHI TIẾT MODULES NGHIỆP VỤ & TÍNH NĂNG CON (FEATURE TAXONOMY — THEO PHẠM VI BUNDLE)

> **Cấu trúc bắt buộc:** Nhóm thành các **Cụm Bounded Contexts** logic. Trình bày **tất cả module con trong phạm vi bundle**; module ngoài phạm vi phải ghi rõ là chưa bao phủ.

### CỤM [N]: [TÊN CỤM NGHIỆP VỤ]

#### Module [M]: `[module_name]` ([Tên Tiếng Việt])
* **Thư mục mã nguồn:** `[path/to/module/]`
* **Đối tượng sử dụng (User Roles):** [Ví dụ: Admin, Sales Manager, Tech Staff, Customer]
* **Entities / Models chính:** `model_1`, `model_2`, `model_3`
* **Endpoints / Routes / Handlers:** `GET/POST /api/v1/...`, `Controller/View Class`
* **Chức năng cụ thể (Đánh số chi tiết):**
1. **[Tên Chức năng 1]:** [Mô tả chi tiết cách thức xử lý, quy tắc nghiệp vụ, validation].
2. **[Tên Chức năng 2]:** [Mô tả chi tiết cách thức xử lý, quy tắc nghiệp vụ, validation].
3. **[Tên Chức năng 3]:** [Mô tả chi tiết cách thức xử lý, quy tắc nghiệp vụ, validation].

---

## 3. MA TRẬN PHÂN QUYỀN THEO VAI TRÒ NGƯỜI DÙNG (USER ROLE MATRIX)

| Phân hệ Nghiệp vụ | System Admin | Sales Manager | Sales Staff / AM | Tech Staff | Kế toán / Finance | Khách hàng (Portal/App) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **[Phân hệ 1]** | Toàn quyền | Xem & Duyệt | Thao tác | Không | Không | Xem dữ liệu cá nhân |
| **[Phân hệ 2]** | Toàn quyền | Giám sát | Không | Khảo sát / Lắp đặt | Không | Theo dõi tiến độ |
| **[Phân hệ 3]** | Toàn quyền | Xem doanh số | Không | Không | **Lập & Post Hóa đơn** | Thanh toán |

---

## 4. VÒNG ĐỜI STATE MACHINE & VẬN HÀNH TỰ ĐỘNG (WORKFLOWS & CRON JOBS)

### 4.1 State Machine Đơn hàng / Hợp đồng / Thực thể chính
```mermaid
stateDiagram-v2
    [*] --> Draft: Khởi tạo
    Draft --> In_Review: Trình duyệt
    In_Review --> Approved: Chấp thuận
    Approved --> In_Progress: Triển khai
    In_Progress --> Completed: Nghiệm thu
    Completed --> [*]
    In_Review --> Rejected: Từ chối
    Draft --> Cancelled: Hủy bỏ
```

### 4.2 Cơ chế Chạy ngầm Tự động (Cron Jobs, SLA Escalation & Background Workers)
* **Cron [Tên Cron]:** Chu kỳ quét, điều kiện kích hoạt, tác vụ tự động sinh đơn / cảnh báo SLA.

---

## 5. LUỒNG NGHIỆP VỤ XUYÊN SUỐT TOÀN HỆ THỐNG (END-TO-END SEQUENCE FLOW)

```mermaid
sequenceDiagram
    autonumber
    actor User as Khách Hàng / User
    participant Auth as SSO / Auth Service
    participant Gateway as API Gateway / Portal
    participant Core as Core Service / Order Engine
    participant Partner as External Integration
    participant Finance as Billing / Commission

    User->>Auth: 1. Đăng nhập & Lấy Bearer Token
    User->>Gateway: 2. Gửi yêu cầu nghiệp vụ
    Gateway->>Core: 3. Điều phối & Kiểm tra SLA
    Core->>Partner: 4. Đồng bộ / Trình ký hệ thống ngoài
    Partner-->>Core: 5. Webhook phản hồi kết quả
    Core->>Finance: 6. Kích hoạt hạch toán tài chính & Ghi nhận hoa hồng
```

---

## 6. ĐÁNH GIÁ KIẾN TRÚC & LỘ TRÌNH TỐI ƯU HÓA (ROADMAP P0/P1/P2)

### 6.1 Các Điểm Mạnh Nổi Bật (Architectural Highlights)
1. **[Điểm mạnh 1]:** Đánh giá về tính Modularity, Separation of Concerns.
2. **[Điểm mạnh 2]:** Đánh giá về bảo toàn dữ liệu, tính nhất quán.
3. **[Điểm mạnh 3]:** Đánh giá về cơ chế tự động hóa và tích hợp.

### 6.2 Khuyến Nghị Tối Ưu Hóa Tiếp Theo (Actionable Roadmap)
* **Priority P0 (Bảo đảm Tin cậy & Critical Path):** [Mô tả chi tiết giải pháp kỹ thuật, ví dụ: Transactional Outbox, Lock mechanism].
* **Priority P1 (Hiệu năng & Khả năng Mở rộng):** [Mô tả chi tiết giải pháp kỹ thuật, ví dụ: Redis Caching, Batch query].
* **Priority P2 (Chất lượng Mã nguồn & Giám sát):** [Mô tả chi tiết giải pháp kỹ thuật, ví dụ: Composite Index, Health check].
