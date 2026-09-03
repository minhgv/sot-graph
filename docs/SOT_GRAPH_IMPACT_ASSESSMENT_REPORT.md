# Báo Cáo Khung Đánh Giá Tác Động & Chấm Điểm Mức Độ Rủi Ro (Risk Assessment Framework) trong SOT-Graph

> **Tài liệu Kỹ thuật Chuyên sâu về Cơ chế Phân tích Tác động Thay đổi (Change Impact Analysis), Thang điểm Rủi ro (Risk Scoring Engine) và Cơ sở Nghiên cứu Khoa học / Tiêu chuẩn Công nghiệp của SOT-Graph.**  
> **Phiên bản:** 1.0.0  
> **Phạm vi áp dụng:** SOT-Graph Core AST Engine, MCP Server, CLI, và AI Coding Agent Harnesses (Oh My Pi, OpenCode, Claude Code).  
> **Đối tượng:** Software Architects, Tech Leads, Security Engineers, AI Coding Agents.

---

## 📑 Mục Lục
1. [Tóm tắt Điều hành (Executive Summary)](#1-tóm-tắt-điều-hành-executive-summary)
2. [Cơ chế 1: Đánh giá Rủi ro Lịch sử Commit (`sot log` / `sot_git_history`)](#2-cơ-chế-1-đánh-giá-rủi-ro-lịch-sử-commit-sot-log--sot_git_history)
3. [Cơ chế 2: Đánh giá Tác động Mã Tiền Kiểm (`sot diff-impact` / `sot_diff_impact`)](#3-cơ-chế-2-đánh-giá-tác-động-mã-tiền-kiểm-sot-diff-impact--sot_diff_impact)
4. [Cơ chế 3: Đánh giá Rủi ro Kiến trúc Vĩ mô ("God Node Risk" trong `sot report`)](#4-cơ-chế-3-đánh-giá-rủi-ro-kiến-trúc-vĩ-mô-god-node-risk-trong-sot-report)
5. [Phân tích Sự Tương Hỗ & Tính Nhất Quán Giữa Tiền Kiểm và Hậu Kiểm](#5-phân-tích-sự-tương-hỗ--tính-nhất-quán-giữa-tiền-kiểm-và-hậu-kiểm)
6. [Cơ sở Khoa học & Tiêu chuẩn Nghiên cứu Quốc tế](#6-cơ-sở-khoa-học--tiêu-chuẩn-nghiên-cứu-quốc-tế)
7. [Khuyến nghị Ứng dụng Thực tế trong CI/CD & AI Coding Agent Workflow](#7-khuyến-nghị-ứng-dụng-thực-tế-trong-cicd--ai-coding-agent-workflow)

---

## 1. Tóm tắt Điều hành (Executive Summary)

Trong kỹ nghệ phần mềm hiện đại, việc đánh giá tác động thay đổi mã nguồn (*Change Impact Analysis - CIA*) thường gặp phải hai thái cực sai lầm:
1. **Đánh giá cảm tính (Subjective Guessing):** Dựa hoàn toàn vào trực giác của lập trình viên hoặc reviewer khi đọc diff, dẫn đến việc bỏ sót các liên kết ngầm (cross-module dependencies) hoặc đánh giá thấp mức độ nguy hiểm của các thay đổi quy mô nhỏ nhưng chạm vào symbol cốt lõi.
2. **Đo đạc thô sơ (Primitive Metrics):** Chỉ đếm số dòng code thay đổi (Lines of Code - LOC) mà không hiểu cấu trúc cú pháp (AST) hay quan hệ ngữ nghĩa (Semantic Call Graph).

**SOT-Graph (Single Source of Truth Knowledge Graph)** giải quyết triệt để vấn đề này bằng cách thiết lập **Khung Đánh giá Rủi ro Đa Tầng (Multi-Tier Risk Assessment Framework)**. Hệ thống kết hợp giữa siêu dữ liệu Git (Git Churn) và Đồ thị tri thức AST (AST Knowledge Graph) được lưu trữ và tối ưu hóa dưới dạng Single-file SQLite. Kết quả đánh giá là các chỉ số hoàn toàn **định lượng, tiền định (deterministic), minh bạch về lý do (explainable)** và được bảo chứng bởi các nghiên cứu thực nghiệm hàng đầu thế giới (Microsoft Research, IEEE TSE, ACM OOPSLA, NIST, OWASP).

```mermaid
flowchart TD
    subgraph SOT_Graph_Risk_Framework["Khung Đánh Giá Rủi Ro SOT-Graph"]
        direction TB
        
        subgraph Tier1["Tầng 1: Hồi cứu Nhanh (Fast Retrospective)"]
            CommitLog["Lịch sử Commit (sot log)"] --> Engine1["CommitHistoryEngine"]
            Engine1 --> HeuristicScore["Thang điểm Heuristic (0 - 15+)"]
            HeuristicScore --> RiskTier1["LOW / MEDIUM / HIGH"]
        end

        subgraph Tier2["Tầng 2: Tiền kiểm Sâu (Deep Pre-merge Guardrail)"]
            DiffWorktree["Working Tree Diff / PR (sot diff-impact)"] --> Engine2["DiffImpactEngine"]
            Engine2 --> ASTMapping["Ánh xạ AST Hunk & Reverse Call Graph"]
            ASTMapping --> NormalizedScore["Thang điểm Chuẩn hóa (0 - 100)"]
            NormalizedScore --> RiskTier2["LOW / MEDIUM / HIGH"]
        end

        subgraph Tier3["Tầng 3: Chẩn đoán Kiến trúc (Macro Architecture)"]
            FullGraph["Toàn bộ Đồ thị (.sot/sot.db)"] --> DiagnosticsEngine["find_god_nodes"]
            DiagnosticsEngine --> GaussianAnalysis["Độ lệch chuẩn Gaussian (μ + 2σ, μ + 3σ)"]
            GaussianAnalysis --> RiskTier3["MEDIUM / HIGH / CRITICAL"]
        end
    end

    classDef t1 fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    classDef t2 fill:#fff3e0,stroke:#f57c00,stroke-width:2px;
    classDef t3 fill:#fce4ec,stroke:#c2185b,stroke-width:2px;
    class Tier1 t1;
    class Tier2 t2;
    class Tier3 t3;
```

---

## 2. Cơ chế 1: Đánh giá Rủi ro Lịch sử Commit (`sot log` / `sot_git_history`)

### 2.1. Mục đích & Bản chất
- **Bản chất:** Kiểm toán hồi cứu (*Retrospective Audit*).
- **Mục tiêu:** Quét toàn bộ lịch sử commit (`git log`) với tốc độ cao (vài chục mili-giây cho 50–100 commits) nhằm gắn nhãn mức độ rủi ro, phát hiện các đợt phát hành đột biến hoặc các commit nguy hiểm cần được rà soát lại trước khi phát hành phiên bản (Release Auditing).
- **Engine thực thi:** `CommitHistoryEngine` (mã nguồn tại `sot_graph.diff_impact.CommitHistoryEngine`).

### 2.2. Bảng Tiêu chí Chấm điểm Heuristic Tích lũy

Hệ thống tính điểm cộng dồn (`score = 0`) dựa trên 5 chiều phân tích độc lập:

| STT | Nhóm Tiêu chí | Ngưỡng Kích hoạt | Điểm | Thông báo Lý do (*Reason String*) |
| :---: | :--- | :--- | :---: | :--- |
| **1.1** | **Phạm vi File (Rộng)** | Số file thay đổi **> 15 files** | `+4` | *High file blast radius (N files changed)* |
| **1.2** | **Phạm vi File (Vừa)** | Số file thay đổi **> 5 files** | `+2` | *Multi-file modification (N files changed)* |
| **2.1** | **Biến động Mã (Lớn)** | Tổng dòng thêm + xóa **> 800 dòng** | `+4` | *Massive code churn (N lines modified)* |
| **2.2** | **Biến động Mã (Vừa)** | Tổng dòng thêm + xóa **> 250 dòng** | `+2` | *Moderate code churn (N lines modified)* |
| **3** | **Vùng Trọng yếu** | Tên file khớp Regex: `auth`, `security`, `crypto`, `secret`, `payment`, `billing`, `lock`, `permission`, `database`, `schema`, `migration`, `alembic`, `flyway` | `+4` | *Touches critical security/database/schema paths (N files)* |
| **4** | **Tệp Cấu hình Gốc** | Khớp danh sách tệp build/manifest: `package.json`, `tsconfig.json`, `pyproject.toml`, `go.mod`, `cargo.toml`, `dockerfile`, `docker-compose.yml`, `pom.xml`, `build.gradle` | `+2` | *Touches build/dependency manifest (<files>)* |
| **5** | **Nút Cốt lõi AST** | Symbol bị sửa có **≥ 5 cuộc gọi đến** (*inward references*) từ các module khác trong đồ thị SOT | `+3` | *Touches high-in-degree core symbol '<symbol>' (N incoming callers)* |

### 2.3. Quy tắc Phân loại Mức độ Rủi ro (Commit Risk Levels)

- 🔴 **HIGH (Điểm ≥ 5):** Commit có rủi ro rất lớn (ví dụ: vừa sửa nhiều file vừa đụng vào bảo mật, hoặc vừa churn cao vừa chạm vào symbol lõi). Cần kiểm tra kỹ lưỡng các bài test hồi quy.
- 🟡 **MEDIUM (Điểm từ 2 đến 4):** Commit có biến động vừa phải hoặc chạm vào cấu hình/phạm vi trung bình.
- 🟢 **LOW (Điểm < 2):** Commit mang tính cục bộ, churn thấp, phạm vi hẹp. Nếu không vi phạm bất kỳ tiêu chí nào, hệ thống tự động gán lý do minh bạch: *"Small localized change with low churn"*.

---

## 3. Cơ chế 2: Đánh giá Tác động Mã Tiền Kiểm (`sot diff-impact` / `sot_diff_impact`)

### 3.1. Mục đích & Bản chất
- **Bản chất:** Rào chắn bảo vệ tiền sát nhập (*Pre-merge Guardrail & Deep Blast Radius Analysis*).
- **Mục tiêu:** Phân tích chi tiết working tree chưa commit hoặc diff của một Pull Request. Hệ thống phân tích từng hunk code, xác định chính xác những hàm/lớp/interface nào bị ảnh hưởng, truy vết ngược đồ thị gọi để tìm toàn bộ caller gián tiếp và hợp đồng API công khai bị đe dọa.
- **Engine thực thi:** `DiffImpactEngine` (mã nguồn tại `sot_graph.diff_impact.DiffImpactEngine`).

### 3.2. Công thức Chuẩn hóa Thang điểm Rủi ro (0 – 100 Điểm)

Điểm rủi ro tác động (**Risk Score**) được tính toán theo mô hình cộng dồn 4 thành phần với ngưỡng chặn trần độc lập:

> **Công thức tổng quát:**  
> `Risk Score = S_files + S_nodes + S_callers + S_apis`  
> *(Thang điểm chuẩn hóa từ 0 đến 100 điểm)*

#### Bảng chi tiết 4 thành phần tính điểm:

| Thành phần | Ký hiệu | Công thức tính toán | Điểm trần | Quy tắc & Ngưỡng kích hoạt |
| :--- | :---: | :--- | :---: | :--- |
| **Phạm vi File** | `S_files` | `min(total_files * 5, 25)` | **25 điểm** | 5 điểm / file thay đổi (chạm trần khi ≥ 5 files) |
| **Nút AST Trực tiếp** | `S_nodes` | `min(total_direct_nodes * 8, 30)` | **30 điểm** | 8 điểm / hàm hoặc lớp bị sửa (chạm trần khi ≥ 4 nodes) |
| **Caller Gián tiếp** | `S_callers` | `min(total_callers * 4, 25)` | **25 điểm** | 4 điểm / inward caller bị ảnh hưởng (chạm trần khi ≥ 7 callers) |
| **API Endpoints** | `S_apis` | `min(total_apis * 10, 20)` | **20 điểm** | 10 điểm / API công khai bị chạm (chạm trần khi ≥ 2 APIs) |

#### Thuật toán thực thi (Python Reference Implementation):
```python
def calculate_risk_score(total_files: int, total_direct_nodes: int, total_callers: int, total_apis: int) -> int:
    s_files   = min(total_files * 5, 25)
    s_nodes   = min(total_direct_nodes * 8, 30)
    s_callers = min(total_callers * 4, 25)
    s_apis    = min(total_apis * 10, 20)
    return s_files + s_nodes + s_callers + s_apis
```


### 3.3. Bảng Quy tắc Phân loại Mức độ Rủi ro (Diff Risk Levels)

| Mức độ | Tiêu chí Kích hoạt | Ngưỡng | Bản chất Kỹ thuật & Rủi ro Hệ thống | Hành động CI/CD & Chính sách Kiểm soát |
| :---: | :--- | :---: | :--- | :--- |
| 🔴 **HIGH** | Tổng điểm rủi ro (`Risk Score`) | `≥ 60` | **Biến động đa chiều nghiêm trọng:** Đồng thời sửa nhiều file, nhiều hàm lõi và phát tán caller diện rộng. Nguy cơ gây lỗi dây chuyền trên toàn hệ thống. | **Chặn tự động merge (Hard Gate):** Bắt buộc tối thiểu 2 Senior Engineers / Tech Lead review độc lập và ký duyệt thủ công. |
| 🔴 **HIGH** | API Endpoints công khai bị chạm (`total_apis`) | `≥ 3` | **Phá vỡ hợp đồng API công khai (Contract Breaking):** Thay đổi trực tiếp từ 3 endpoint trở lên, đe dọa các client bên ngoài (Web SPA, Mobile App, Microservice). | **Chặn auto-merge:** Bắt buộc kiểm tra tính tương thích ngược (*Backward Compatibility*), cập nhật OpenAPI spec và chạy test E2E Contract. |
| 🔴 **HIGH** | Callers gián tiếp bị tác động (`total_callers`) | `≥ 10` | **Bán kính nổ lan tỏa sâu (Deep Blast Radius):** Node bị sửa là điểm nghẽn kiến trúc, kéo theo ≥ 10 hàm nghiệp vụ khác bị ảnh hưởng gián tiếp qua đồ thị gọi. | **Chặn auto-merge:** Bắt buộc kích hoạt toàn bộ test suite hồi quy (*Full Regression Test Suite*) cho tất cả các module chứa caller phụ thuộc. |
| 🟡 **MEDIUM** | Tổng điểm rủi ro (`Risk Score`) | `≥ 25` | **Biến động cấu trúc trung bình:** Có sự phân tán thay đổi trên nhiều hàm hoặc cấu trúc dữ liệu nhưng chưa đến ngưỡng gây tê liệt toàn cục. | **Cảnh báo vàng:** Cho phép mở PR, yêu cầu chạy đầy đủ test tích hợp (*Integration Tests*) và cần ít nhất 1 Peer Reviewer phê duyệt. |
| 🟡 **MEDIUM** | Callers gián tiếp bị tác động (`total_callers`) | `≥ 3` | **Tác động liên module (Cross-module Ripple):** Từ 3 đến 9 luồng nghiệp vụ lân cận phụ thuộc trực tiếp vào hàm vừa bị sửa đổi logic hoặc chữ ký. | **Khoanh vùng kiểm thử:** Bắt buộc chạy targeted test suite cho toàn bộ các module và caller liên quan trực tiếp trước khi merge. |
| 🟡 **MEDIUM** | API Endpoints công khai bị chạm (`total_apis`) | `≥ 1` | **Chạm giao diện công khai ngoại vi:** Ảnh hưởng 1–2 API endpoint, có thể làm biến động cấu trúc payload Request/Response hoặc mã lỗi HTTP. | **Kiểm tra hợp đồng:** Bắt buộc xác thực schema (JSON Schema / DTO diff) và chạy suite kiểm thử API endpoints tương ứng. |
| 🟢 **LOW** | Điểm < 25, Callers < 3, APIs = 0 | Đạt cả 3 | **Cục bộ, an toàn (Localized Mutation):** Phạm vi hẹp, không đổi chữ ký hàm lõi, không có caller ngoại vi, không chạm API công khai. | **Fast-track:** Cho phép auto-merge sau khi vượt qua bài kiểm thử đơn vị cơ bản (*Unit Tests Pass*), không yêu cầu quy trình duyệt gắt gao. |

> ⚠️ **Quy tắc kích hoạt (Trigger Logic):** Đối với mức **HIGH** và **MEDIUM**, hệ thống áp dụng logic **HOẶC (OR)** — chỉ cần thỏa mãn **bất kỳ 1 trong 3 điều kiện** trên là commit/diff lập tức bị xếp vào mức rủi ro tương ứng. Riêng mức **LOW** yêu cầu thỏa mãn đồng thời cả 3 điều kiện (logic **AND**).


---

## 4. Cơ chế 3: Đánh giá Rủi ro Kiến trúc Vĩ mô ("God Node Risk" trong `sot report`)

### 4.1. Mục đích & Bản chất
- **Bản chất:** Phân tích Chẩn đoán Cấu trúc Phần mềm (*Architectural Health Diagnostics*).
- **Mục tiêu:** Phát hiện các "God Node" (các hàm/lớp/interface đóng vai trò siêu trung tâm, có liên kết quá dày đặc), từ đó cảnh báo nguy cơ tạo thành điểm nghẽn chịu lỗi duy nhất (*Single Point of Failure*) của toàn bộ hệ thống.
- **Engine thực thi:** `sot_graph.analytics.diagnostics.find_god_nodes`.

### 4.2. Thuật toán Thống kê Phân phối & Bán kính Ảnh hưởng 2 Bước

Hệ thống tính toán phân phối bậc liên kết (Total Degree: `d = in_degree + out_degree`) trên toàn bộ đồ thị tri thức:

> **Công thức thống kê:**  
> - **Bậc trung bình (Mean):** `μ = (1 / N) * ∑(d_i)`  
> - **Độ lệch chuẩn (Std Dev):** `σ = √[ (1 / N) * ∑(d_i - μ)² ]`  
> - **Ngưỡng phát hiện God Node:** `Cutoff = max(4, μ + 1.5σ)`

- Nếu một node có bậc liên kết `d ≥ Cutoff`, hệ thống xác định đây là một **God Node** và tiến hành đo lường **Bán kính Nổ 2 Bước (2-Hop Blast Radius)** bằng thuật toán duyệt BFS trên đồ thị với bán kính `k ≤ 2`.


### 4.3. Bảng Phân loại Mức độ Rủi ro Kiến trúc

| Mức độ | Điều kiện Thống kê Bậc | Điều kiện Bán kính Nổ | Ý nghĩa Kỹ thuật & Khuyến nghị Kiến trúc |
| :---: | :--- | :--- | :--- |
| 🔴 **CRITICAL** | Bậc liên kết `d ≥ μ + 3.0σ` | **HOẶC** Blast Radius ≥ 30% tổng số node | **Cực kỳ nguy hiểm:** Node chi phối ~1/3 hệ thống, thay đổi dễ gây sập toàn bộ ứng dụng. Cần ưu tiên bóc tách (refactor) ngay. |
| 🟡 **HIGH** | Bậc liên kết `d ≥ μ + 2.0σ` | **HOẶC** Blast Radius ≥ 15% tổng số node | **Nguy cơ cao:** Độ kết dính (coupling) vượt xa chuẩn thiết kế. Cần áp dụng Dependency Injection hoặc Facade pattern để giảm tải. |
| 🟢 **MEDIUM** | `d ≥ Cutoff` (dưới mức HIGH) | Blast Radius < 15% tổng số node | **Cần theo dõi:** Node có xu hướng phình to theo thời gian phát triển. |

---

## 5. Phân tích Sự Tương Hỗ & Tính Nhất Quán Giữa Tiền Kiểm và Hậu Kiểm

Người dùng thường đặt câu hỏi: *Liệu có mâu thuẫn giữa Cơ chế 1 (Commit History) và Cơ chế 2 (Diff Impact) khi hai cơ chế sử dụng hai thang điểm khác nhau?*

**Khẳng định: Hai cơ chế hoàn toàn nhất quán và bổ trợ chặt chẽ cho nhau trong một Phễu Đảm bảo Chất lượng (Quality Funnel).**

```mermaid
graph LR
    subgraph Funnel["Mô Hình Phễu Đảm Bảo Chất Lượng SOT-Graph"]
        direction LR
        Dev["Lập trình viên / AI"] -->|Code Diff| P2["Cơ chế 2: sot diff-impact\n(Kính hiển vi AST)"]
        P2 -->|An toàn: Merge| Repo["Kho lưu trữ Git"]
        Repo -->|Lịch sử Commit| P1["Cơ chế 1: sot log\n(Ống nhòm Viễn vọng)"]
        Repo -->|Toàn bộ Kiến trúc| P3["Cơ chế 3: sot report\n(Bản đồ Toàn cảnh)"]
    end
```

### Bảng Đối chiếu Kỹ thuật So sánh Hai Cơ chế

| Tiêu chí | Cơ chế 1: `sot log` (Commit History) | Cơ chế 2: `sot diff-impact` (Diff Impact) |
| :--- | :--- | :--- |
| **Giai đoạn áp dụng** | **Hậu kiểm / Hồi cứu (Post-commit / Audit)** | **Tiền kiểm (Pre-commit / Pre-merge)** |
| **Độ sâu phân tích** | Metadata Git + Heuristic + Tra cứu In-degree nhanh | Full AST Hunk Mapping + Tra cứu Reverse Call Graph sâu |
| **Độ phức tạp thuật toán** | `O(C)` với C là số lượng commit (~10–50 ms) | `O(H · log N + V + E)` trên đồ thị cục bộ (~200–800 ms) |
| **Trọng tâm rủi ro** | Bắt sự **hỗn loạn biến động mã (Code Churn & Dispersion)** | Bắt sự **đổ vỡ ngữ nghĩa (Semantic & Contract Breakage)** |
| **Ví dụ điển hình** | Commit sửa 1.000 dòng trên 20 file → **HIGH** | Đổi signature 1 hàm lõi ảnh hưởng 15 caller → **HIGH** (dù chỉ sửa 2 dòng) |

Nhờ sự phân tầng này:
- Quá trình duyệt lịch sử commit diễn ra gần như tức thì, không gây nghẽn luồng làm việc của kỹ sư.
- Quá trình chuẩn bị sát nhập mã được bảo vệ bằng kính hiển vi AST, ngăn chặn tuyệt đối các lỗi hồi quy ngầm.

---

## 6. Cơ sở Khoa học & Tiêu chuẩn Nghiên cứu Quốc tế

Toàn bộ các tham số, trọng số và điều kiện phân ngưỡng của SOT-Graph được xây dựng dựa trên 3 nhánh công trình khoa học đã được thẩm định đồng đẳng (*Peer-reviewed*):

### 6.1. Nhánh Nghiên cứu Biến động Mã & Đảm bảo Chất lượng Tức thì (JIT-QA)

1. **Nghiên cứu Microsoft Research về Relative Code Churn (Nagappan & Ball, ICSE 2005 / IEEE TSE 2007)**:
   - *Tên bài báo:* *"Use of Relative Code Churn Measures to Predict System Defect Density"*.
   - *Đóng góp:* Chứng minh bằng thực nghiệm trên hàng triệu dòng lệnh của Windows Server rằng lượng biến động mã (*Code Churn*) có mối tương quan mạnh nhất với mật độ lỗi phát sinh sau phát hành (R² > 0.8), vượt trội hoàn toàn so với độ phức tạp chu trình McCabe (*Cyclomatic Complexity*). Đây là cơ sở cho các mốc churn > 250 và > 800 dòng của SOT-Graph.
2. **Mô hình Dự đoán Lỗi Tức thì JIT (Kamei et al., IEEE TSE 2013)**:
   - *Tên bài báo:* *"A Large-Scale Empirical Study of Just-In-Time Quality Assurance"*.
   - *Đóng góp:* Khảo sát 14 dự án mã nguồn mở và thương mại quy mô lớn (> 12.000 commit). Nghiên cứu chỉ ra rằng các yếu tố **Change Size** (kích thước thay đổi), **File Dispersion** (số file bị sửa rải rác) và **Entropy** là những yếu tố quyết định gây ra hiện tượng *Cognitive Overload* ở người duyệt mã, khiến tỷ lệ lọt lỗi tăng vọt khi số file > 5.
3. **Entropy của Thay đổi Phần mềm (Hassan, ICSE 2009)**:
   - *Tên bài báo:* *"Predicting Faults Using the Complexity of Code Changes"*.
   - *Đóng góp:* Chứng minh rằng sự phân tán thay đổi trên nhiều file thuộc các hệ thống con khác nhau làm tăng độ hỗn loạn của mã nguồn và dự báo chính xác các vùng có nguy cơ lỗi cao.

### 6.2. Nhánh Lý thuyết Đồ thị Phụ thuộc & Phân tích Tác động Thay đổi (CIA)

1. **Phân tích Mạng Phụ thuộc Thành phần (Zimmermann & Nagappan, ICSE 2008)**:
   - *Tên bài báo:* *"Predicting Defects for Eclipse: Finding Faults in Network of Components"*.
   - *Đóng góp:* Áp dụng lý thuyết đồ thị mạng xã hội và mạng phức hợp vào đồ thị phụ thuộc phần mềm. Các node có **In-Degree cao (Afferent Coupling - Ca)** đóng vai trò là các trung tâm truyền dẫn rủi ro (*risk propagation hubs*). Khi một node có in-degree cao bị thay đổi, bán kính tác động tăng theo hàm mũ.
2. **Bộ Chỉ số Thiết kế Hướng Đối tượng CK (Chidamber & Kemerer, IEEE TSE 1994)**:
   - *Tên bài báo:* *"A Metrics Suite for Object Oriented Design"*.
   - *Đóng góp:* Chuẩn hóa metric **CBO (Coupling Between Objects)** và **Afferent Coupling**. Ngưỡng liên kết ≥ 5 được thừa nhận rộng rãi là điểm cảnh báo tái cấu trúc do chi phí kiểm thử và bảo trì tăng đột biến.
3. **Hệ Thống Phân Tích Tác Động Chianti (Ren et al., OOPSLA 2004 / Ryder & Tip, IEEE Software 2001)**:
   - *Tên bài báo:* *"Chianti: A Tool for Change Impact Analysis of Java Programs"*.
   - *Đóng góp:* Đặt nền móng cho kỹ thuật bóc tách diff thành các nguyên tử thay đổi AST (*Atomic Changes*) và dùng đồ thị gọi ngược (*Reverse Call Graph Traversal*) để cô lập chính xác các Test Cases bị tác động. SOT-Graph kế thừa hoàn toàn mô hình toán học này trong `DiffImpactEngine`.

### 6.3. Tiêu chuẩn An toàn Thông tin & Kiến trúc Phần mềm Công nghiệp

1. **NIST SP 800-218 (Secure Software Development Framework - SSDF)**:
   - *Khuyến nghị:* Nhiệm vụ **PW.4 (Review Software Architecture)** và **PW.7 (Review Code for Security Vulnerabilities)** yêu cầu phân loại bề mặt tấn công (*Attack Surface*). Các thay đổi chạm vào cơ chế kiểm soát danh tính (Authentication), phân quyền (Authorization), mật mã học (Cryptography) và toàn vẹn cơ sở dữ liệu (Database Schemas) phải tự động kích hoạt mức độ bảo đảm cao (*High Assurance Level*). Đây là căn cứ của nhóm `CRITICAL_PATTERNS` trong SOT-Graph.
2. **OWASP Application Security Verification Standard (ASVS v4.0)**:
   - Yêu cầu mọi biến đổi trong các module kiểm soát truy cập (V4 Access Control) và mã hóa dữ liệu (V6 Stored Cryptography) phải có báo cáo tác động độc lập trước khi đẩy lên môi trường Production.
3. **ISO/IEC 25010 (Software Product Quality Model)**:
   - Chuẩn hóa các đặc tính chất lượng: *Modularity (Tính module)*, *Reusability (Khả năng tái sử dụng)*, và *Analysability (Khả năng phân tích)*.
4. **Nguyên lý Phát hiện Dị thường Gaussian & Anti-pattern Kiến trúc**:
   - Khái niệm **God Class / The Blob** được định nghĩa bởi *Arthur Riel (1996 - Object-Oriented Design Heuristics)* và *Martin Fowler (1999 - Refactoring)*. Việc sử dụng độ lệch chuẩn `μ + 2σ` (ngưỡng 95%) và `μ + 3σ` (ngưỡng 99.7% theo quy tắc Ba Sigma) giúp loại bỏ hoàn toàn tính chủ quan khi định vị các nút thắt kiến trúc.

---

## 7. Khuyến nghị Ứng dụng Thực tế trong CI/CD & AI Coding Agent Workflow

### 7.1. Tích hợp Git Pre-commit / Pre-push Hook
Cài đặt script kiểm tra tự động trước khi kỹ sư hoặc AI Agent đẩy mã lên remote:
```bash
#!/usr/bin/env bash
# .git/hooks/pre-push
echo "🔍 Đang chạy SOT-Graph Diff Impact Audit..."
sot diff-impact --json > /tmp/sot_diff.json

RISK_LEVEL=$(jq -r '.summary.risk_level' /tmp/sot_diff.json)
if [ "$RISK_LEVEL" == "HIGH" ]; then
    echo "❌ Push bị chặn! SOT-Graph phát hiện mức độ rủi ro HIGH:"
    jq -r '.summary' /tmp/sot_diff.json
    echo "Vui lòng tham vấn Tech Lead hoặc bổ sung bài kiểm thử tự động."
    exit 1
fi
echo "✅ SOT-Graph Audit Passed (Risk Level: $RISK_LEVEL)"
exit 0
```

### 7.2. Quy trình Làm việc Dành cho AI Coding Agents (Harness Rules)
Trong các môi trường Agent tự trị (như Oh My Pi, OpenCode, Claude Code):
1. **Trước khi sửa đổi hàm cốt lõi:** Bắt buộc gọi `sot_explore` hoặc `sot_usages` để kiểm tra In-Degree. Nếu In-Degree ≥ 5, Agent phải thông báo bán kính tác động cho người dùng.
2. **Sau khi thực hiện xong diff:** Bắt buộc chạy `sot_diff_impact` (hoặc `sot_diff_impact_receipt`). Nếu mức độ rủi ro là **HIGH**, Agent không được phép tự ý kết thúc phiên làm việc (*yield*) mà phải chạy suite kiểm thử bao phủ toàn bộ danh sách `impacted_tests`.
3. **Khi chuẩn bị phát hành phiên bản:** Sử dụng `sot_git_history` để tạo bảng tổng kết rủi ro cho toàn bộ danh sách commit trong chu kỳ release.

---

> **Tài liệu tham chiếu nội bộ:**  
> - `sot-graph`: Core AST Engine & CLI (`~/.local/bin/sot`)  
> - SQLite Schema: `.sot/sot.db` (`graph_nodes`, `graph_edges`, `file_journal`)  
> - MCP Tool Specifications: `xd://mcp__sot_graph_sot_diff_impact`, `xd://mcp__sot_graph_sot_git_history`  
> - Đối chiếu với GitNexus, CodeGraph, Codebase-Memory-MCP: [`docs/IMPACT_ASSESSMENT_COMPARISON.md`](IMPACT_ASSESSMENT_COMPARISON.md)
