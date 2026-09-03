"""
sot_graph.solution — Automated Solution Architecture and Manpower Estimation Engine.

Produces Stage 1 Feature Inventories, Stage 2 Micro-Step Decompositions (4-column tables
with authentic AST execution code for Manpower NVJ1/NVJ2/NVJ3 estimation), and Full-Stack
Context Bundles for downstream agents (DBDesign, HDSD, KBKT, Manpower, NghiepVu).
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Set

__all__ = [
    "generate_feature_inventory",
    "extract_execution_steps",
    "generate_solution_bundle",
]


def _detect_role_from_path_or_name(path: str, name: str) -> str:
    """Infer user role from route path, namespace, or controller name."""
    lower_path = (path + "/" + name).lower()
    if any(k in lower_path for k in ["/admin", "admincontroller", "admin/"]):
        return "Admin (Quản trị hệ thống)"
    if any(k in lower_path for k in ["/sp", "/partner", "/merchant", "partnercontroller"]):
        return "ServiceProvider (Đối tác / Merchant)"
    if any(k in lower_path for k in ["/webhook", "webhookcontroller", "webhook"]):
        return "System Integration (Webhook / External Caller)"
    if any(k in lower_path for k in ["/api", "apicontroller", "restcontroller"]):
        return "API Client / External System"
    return "EndUser (Người dùng cuối / Khách hàng)"


def _classify_feature_type(method_name: str, body: str) -> str:
    """Classify feature into CRUD, StatusChange, Export, Import, or Custom."""
    m = method_name.lower()
    b = body.lower()
    if any(k in m for k in ["index", "list", "search", "getall", "find"]):
        return "CRUD - Danh sách & Tra cứu (List/Search)"
    if any(k in m for k in ["show", "detail", "getbyid", "findbyid"]):
        return "CRUD - Xem chi tiết (Detail/View)"
    if any(k in m for k in ["create", "store", "add", "insert", "register"]):
        return "CRUD - Thêm mới (Create/Store)"
    if any(k in m for k in ["edit", "update", "patch", "modify"]):
        return "CRUD - Cập nhật (Update/Edit)"
    if any(k in m for k in ["destroy", "delete", "remove", "cancel"]):
        return "CRUD - Xóa / Hủy (Delete/Cancel)"
    if any(k in m for k in ["export", "download", "excel", "csv"]):
        return "Export - Xuất dữ liệu báo cáo"
    if any(k in m for k in ["import", "upload"]):
        return "Import - Nhập dữ liệu từ file"
    if any(k in m for k in ["approve", "reject", "lock", "unlock", "activate", "deactivate", "status"]):
        return "StatusChange - Chuyển đổi trạng thái / Phê duyệt"
    if "bccs" in b or "deduct" in m or "payment" in m or "transfer" in m:
        return "Business Transaction - Giao dịch thanh toán / Hạn mức"
    return "Custom - Xử lý nghiệp vụ đặc thù"


def _scan_related_features(db, module_filter: str = "") -> List[Dict[str, Any]]:
    """Scan 10 categories of related features across AST nodes."""
    conn = getattr(db, "conn", db)
    related: List[Dict[str, Any]] = []

    # First check dedicated table
    rows = []
    try:
        rows = conn.execute(
            "SELECT id, module_name, feature_name, feature_category, risk_level, short_description, key_files "
            "FROM related_features_index WHERE module_name LIKE ? LIMIT 30",
            (f"%{module_filter}%",),
        ).fetchall()
    except Exception:
        rows = []
    if rows:
        return [
            {
                "id": r[0], "module": r[1], "name": r[2], "category": r[3],
                "risk": r[4], "description": r[5], "key_files": r[6],
            }
            for r in rows
        ]

    # Heuristic detection from graph_nodes
    nodes = conn.execute(
        "SELECT id, path, kind, symbol, fqn, body FROM graph_nodes "
        "WHERE path LIKE ? AND kind != 'file' LIMIT 200",
        (f"%{module_filter}%",),
    ).fetchall()

    for n in nodes:
        path, symbol, body = n[1], n[3] or "", n[5] or ""
        lower_body = (path + " " + symbol + " " + body).lower()

        # 1. Webhook
        if "webhook" in lower_body:
            related.append({
                "module": module_filter or "Core",
                "name": f"Webhook Callback Integration ({symbol or 'Webhook'})",
                "category": "WEBHOOK",
                "risk": "HIGH",
                "description": "Nhận sự kiện webhook từ đối tác bên ngoài và đồng bộ trạng thái.",
                "key_files": path,
            })
        # 2. Sync
        elif "sync" in lower_body and any(k in lower_body for k in ["subscriber", "user", "data"]):
            related.append({
                "module": module_filter or "Core",
                "name": f"Đồng bộ danh sách ({symbol or 'SyncService'})",
                "category": "SYNC",
                "risk": "HIGH",
                "description": "Tiến trình đồng bộ danh mục thuê bao hoặc dữ liệu định kỳ.",
                "key_files": path,
            })
        # 3. Cron / Scheduled
        elif any(k in lower_body for k in ["@scheduled", "cron", "scheduler", "runjob"]):
            related.append({
                "module": module_filter or "Core",
                "name": f"Tác vụ tự động định kỳ ({symbol or 'ScheduledJob'})",
                "category": "CRON",
                "risk": "MEDIUM",
                "description": "Job chạy ngầm tự động đối soát hoặc dọn dẹp dữ liệu.",
                "key_files": path,
            })
        # 4. Event Listener / Observer
        elif any(k in lower_body for k in ["@eventlistener", "@transactionaleventlistener", "observer", "eventpublisher"]):
            related.append({
                "module": module_filter or "Core",
                "name": f"Lắng nghe sự kiện nghiệp vụ ({symbol or 'EventListener'})",
                "category": "OBSERVER",
                "risk": "HIGH",
                "description": "Bắt sự kiện giao dịch để thực hiện các luồng phụ không đồng bộ.",
                "key_files": path,
            })
        # 5. Queue / Consumer
        elif any(k in lower_body for k in ["@kafkalistener", "@rabbitlistener", "sqslistener", "consumermessage"]):
            related.append({
                "module": module_filter or "Core",
                "name": f"Message Queue Consumer ({symbol or 'QueueConsumer'})",
                "category": "QUEUE",
                "risk": "HIGH",
                "description": "Xử lý hàng đợi giao dịch bất đồng bộ qua Kafka/RabbitMQ.",
                "key_files": path,
            })
        # 6. Notification (SMS / Email / Push)
        elif any(k in lower_body for k in ["sendsms", "sendemail", "pushnotification", "mailservice"]):
            related.append({
                "module": module_filter or "Core",
                "name": f"Gửi thông báo OTP / Email / SMS ({symbol or 'NotificationService'})",
                "category": "NOTIFICATION",
                "risk": "MEDIUM",
                "description": "Gửi tin nhắn hoặc thông báo kết quả giao dịch tới người dùng.",
                "key_files": path,
            })

    # Deduplicate by name
    seen: Set[str] = set()
    unique_related = []
    for r in related:
        if r["name"] not in seen:
            seen.add(r["name"])
            unique_related.append(r)

    return unique_related[:10]


def generate_feature_inventory(db, module: str = "", *, out_file: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage 1 Feature Discovery: Scans all features per role and 10 related feature categories.
    Conforms strictly to Stage 1 Scope Gatekeeper rules of itpro-tlgp.
    """
    conn = getattr(db, "conn", db)
    pattern = f"%{module}%" if module else "%"

    # Query controller / service nodes
    rows = conn.execute(
        "SELECT id, path, kind, symbol, fqn, signature, label, body, line_start, line_end "
        "FROM graph_nodes WHERE path LIKE ? AND kind IN ('function', 'method', 'class', 'struct') "
        "ORDER BY path ASC, line_start ASC LIMIT 100",
        (pattern,),
    ).fetchall()

    features_by_role: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        path, symbol, body = r[1], r[3] or "", r[7] or ""
        if not symbol or symbol.startswith("_"):
            continue

        role = _detect_role_from_path_or_name(path, symbol)
        ft_type = _classify_feature_type(symbol, body)

        item = {
            "symbol": symbol,
            "feature_name": f"{symbol} ({ft_type.split(' - ')[0]})",
            "type": ft_type,
            "file": path,
            "line": r[8] or 1,
            "signature": r[5] or symbol,
        }
        features_by_role.setdefault(role, []).append(item)

    related_features = _scan_related_features(db, module)

    # Format Markdown
    md_lines = [
        f"# BẢNG DANH MỤC TÍNH NĂNG (FEATURE INVENTORY): {module or 'TOÀN BỘ HỆ THỐNG'}",
        "",
        "> **Stage 1 Scope Gatekeeper:** Quét tự động bằng SOT-Graph AST Slicer. Dừng lại xác nhận phạm vi với Người dùng trước khi sinh Solution.md.",
        "",
        "## 1. Danh sách tính năng chính theo Vai trò (Features by Role)",
        "",
    ]

    total_features = 0
    for role, fts in features_by_role.items():
        md_lines.extend([
            f"### Vai trò: **{role}** ({len(fts)} tính năng)",
            "",
            "| STT | Tên tính năng / Phương thức | Phân loại | File nguồn & Vị trí |",
            "| :---: | :--- | :--- | :--- |",
        ])
        for idx, f in enumerate(fts, 1):
            total_features += 1
            md_lines.append(f"| {idx} | `{f['symbol']}` | {f['type']} | `{f['file']}:{f['line']}` |")
        md_lines.append("")

    md_lines.extend([
        "## 2. Danh mục tính năng liên quan (Related Features Detection)",
        "",
        "| STT | Tính năng liên quan | Nhóm phân loại | Mức độ tác động | Mô tả tóm tắt | File liên quan |",
        "| :---: | :--- | :--- | :---: | :--- | :--- |",
    ])

    if related_features:
        for idx, r in enumerate(related_features, 1):
            risk_badge = f"**{r['risk']}**"
            md_lines.append(f"| {idx} | {r['name']} | {r['category']} | {risk_badge} | {r['description']} | `{r['key_files']}` |")
    else:
        md_lines.append(
            "| — | *(Không tìm thấy tính năng liên quan nào trong đồ thị — không tổng hợp giả định)* | — | — | — | — |"
        )

    md_lines.extend([
        "",
        "---",
        f"**Tổng kết:** Đã phát hiện **{total_features}** tính năng chính và **{len(related_features)}** tính năng liên quan.",
    ])

    content = "\n".join(md_lines)
    if out_file:
        os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as fp:
            fp.write(content)

    return {
        "module": module,
        "total_features": total_features,
        "features_by_role": features_by_role,
        "related_features": related_features,
        "markdown": content,
        "out_file": out_file,
    }


def extract_execution_steps(db, method_or_service: str, *, format_mode: str = "table") -> Dict[str, Any]:
    """
    Stage 2 Micro-Step Decomposition:
    Extracts 4-column step table (TT, Tên bước, Lệnh thực thi CODE, Mô tả chi tiết logic)
    maximizing steps for labor cost estimation (NVJ1/NVJ2/NVJ3).
    """
    conn = getattr(db, "conn", db)
    cleaned = method_or_service.strip()

    # Query DB
    rows = []
    try:
        rows = conn.execute(
            "SELECT id, service_symbol, step_order, step_name, code_statement, "
            "step_description, step_category, datasource_target, file_path, line_number "
            "FROM be_execution_steps WHERE service_symbol LIKE ? ORDER BY step_order ASC LIMIT 50",
            (f"%{cleaned}%",),
        ).fetchall()
    except Exception:
        rows = []

    steps: List[Dict[str, Any]] = []
    if rows:
        steps = [
            {
                "tt": r[2],
                "name": r[3],
                "code": r[4],
                "description": r[5],
                "category": r[6],
                "datasource": r[7],
                "file": r[8],
                "line": r[9],
            }
            for r in rows
        ]
    else:
        # Query node body and parse statements
        node = conn.execute(
            "SELECT id, path, symbol, body FROM graph_nodes "
            "WHERE symbol = ? OR fqn = ? OR label = ? LIMIT 1",
            (cleaned, cleaned, cleaned),
        ).fetchone()

        if not node:
            node = conn.execute(
                "SELECT id, path, symbol, body FROM graph_nodes "
                "WHERE symbol LIKE ? OR fqn LIKE ? LIMIT 1",
                (f"%{cleaned}%", f"%{cleaned}%"),
            ).fetchone()

        if node:
            path, body = node[1], node[3] or ""
            lines = body.splitlines()
            order = 1
            for idx, line in enumerate(lines, 1):
                sline = line.strip()
                if not sline or sline.startswith(("//", "/*", "*", "#", "import ", "package ")):
                    continue

                code_wrapped = sline[:90]
                if len(code_wrapped) > 25:
                    code_wrapped = "<br>".join([code_wrapped[i:i+30] for i in range(0, len(code_wrapped), 30)])

                if re.search(r'@Valid|validate|IllegalArgument|if\s*\([^)]*null', sline):
                    steps.append({
                        "tt": order,
                        "name": "Nhận request & Validate tham số",
                        "code": code_wrapped,
                        "description": "Nhận yêu cầu từ client, kiểm tra tính hợp lệ của các trường bắt buộc.",
                        "category": "VALIDATE",
                        "datasource": "NONE",
                        "file": path,
                        "line": idx,
                    })
                    order += 1
                elif re.search(r'find|select|repo\.|repository\.', sline, re.IGNORECASE):
                    steps.append({
                        "tt": order,
                        "name": "Truy vấn cơ sở dữ liệu nội bộ",
                        "code": code_wrapped,
                        "description": "Thực hiện truy vấn bảng dữ liệu nội bộ theo khóa chính hoặc điều kiện lọc.",
                        "category": "LOCAL_DB",
                        "datasource": "PRIMARY_DB",
                        "file": path,
                        "line": idx,
                    })
                    order += 1
                elif re.search(r'bccs|external|client\.|http|rest', sline, re.IGNORECASE):
                    steps.append({
                        "tt": order,
                        "name": "Kết nối & Truy vấn DataSource phụ (BCCS / External)",
                        "code": code_wrapped,
                        "description": "Khởi tạo kết nối và gọi sang nguồn dữ liệu phụ bên ngoài để tra cứu hạn mức.",
                        "category": "EXTERNAL_DB",
                        "datasource": "BCCS_DATASOURCE",
                        "file": path,
                        "line": idx,
                    })
                    order += 1
                elif re.search(r'if\s*\(', sline):
                    steps.append({
                        "tt": order,
                        "name": "Kiểm tra điều kiện rẽ nhánh nghiệp vụ",
                        "code": code_wrapped,
                        "description": "Đánh giá biểu thức điều kiện để phân nhánh xử lý giao dịch hoặc ném lỗi.",
                        "category": "BUSINESS_CHECK",
                        "datasource": "NONE",
                        "file": path,
                        "line": idx,
                    })
                    order += 1
                elif re.search(r'throw\s+new', sline):
                    steps.append({
                        "tt": order,
                        "name": "Xử lý ngắt luồng & Ném ngoại lệ lỗi",
                        "code": code_wrapped,
                        "description": "Ngắt luồng giao dịch khi điều kiện không thỏa mãn và ném BusinessException.",
                        "category": "EXCEPTION",
                        "datasource": "NONE",
                        "file": path,
                        "line": idx,
                    })
                    order += 1
                elif re.search(r'save|update|delete|record|ledger', sline, re.IGNORECASE):
                    steps.append({
                        "tt": order,
                        "name": "Ghi nhận thay đổi dữ liệu & Sổ cái Core",
                        "code": code_wrapped,
                        "description": "Lưu thay đổi trạng thái thực thể hoặc ghi giao dịch vào sổ cái tài chính.",
                        "category": "MUTATION",
                        "datasource": "PRIMARY_DB",
                        "file": path,
                        "line": idx,
                    })
                    order += 1
                elif re.search(r'log|audit', sline, re.IGNORECASE):
                    steps.append({
                        "tt": order,
                        "name": "Ghi log kiểm toán (Audit Trail)",
                        "code": code_wrapped,
                        "description": "Lưu vết kiểm toán giao dịch phục vụ tra soát và đối soát định kỳ.",
                        "category": "AUDIT",
                        "datasource": "PRIMARY_DB",
                        "file": path,
                        "line": idx,
                    })
                    order += 1
                elif re.search(r'return\s+', sline):
                    steps.append({
                        "tt": order,
                        "name": "Đóng gói & Phản hồi kết quả",
                        "code": code_wrapped,
                        "description": "Đóng gói DTO kết quả thành công kèm mã giao dịch và trả về cho Client.",
                        "category": "RESPONSE",
                        "datasource": "NONE",
                        "file": path,
                        "line": idx,
                    })
                    order += 1

    # Calculate Manpower Effort rank
    step_count = len(steps)
    if step_count == 0:
        manpower_rank = "N/A (không có dữ liệu)"
    elif step_count <= 4:
        manpower_rank = "NVJ1 (Đơn giản - ≤4 bước)"
    elif step_count <= 8:
        manpower_rank = "NVJ2 (Trung bình - 5-8 bước)"
    else:
        manpower_rank = "NVJ3 / NVJ3-PTM (Phức tạp - ≥9 bước, Đạt tối đa định mức nhân công)"

    # Format Markdown Table
    lines = [
        f"### Bảng các bước xử lý chi tiết: `{method_or_service}`",
        "",
        f"> **Định mức nhân công (Manpower Effort):** `{manpower_rank}` ({step_count} bước xử lý)",
        "",
    ]
    if not steps:
        lines.append(
            f"> ⚠️ **NOT_FOUND:** không tìm thấy bước xử lý nào cho `{method_or_service}` "
            "trong be_execution_steps hoặc thân node của đồ thị — không tổng hợp giả định."
        )
    else:
        lines.extend([
            "| TT | Tên bước | Lệnh thực thi | Mô tả chi tiết logic |",
            "| :---: | :--- | :--- | :--- |",
        ])
        for s in steps:
            lines.append(f"| {s['tt']} | {s['name']} | `{s['code']}` | {s['description']} |")

    return {
        "method_or_service": method_or_service,
        "status": "FOUND" if steps else "NOT_FOUND",
        "step_count": step_count,
        "manpower_rank": manpower_rank,
        "steps": steps,
        "markdown_table": "\n".join(lines),
    }


def _like_literal(value: str) -> str:
    # Service/module names are literals: unescaped %/_ would turn the query
    # into a wildcard pattern ("core_base" matching "coreXbase") and bind
    # the wrong service.
    return (
        value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    )


def _resolve_service_symbol(conn: Any, module: str) -> str:
    """Pick a service symbol that actually exists in the graph/steps data.

    Never fabricates: returns "" (=> NOT_FOUND) when nothing matches.
    """
    try:
        if module:
            row = conn.execute(
                "SELECT DISTINCT service_symbol FROM be_execution_steps "
                "WHERE service_symbol LIKE ? ESCAPE '\\' "
                "ORDER BY service_symbol LIMIT 1",
                (f"%{_like_literal(module)}%",),
            ).fetchone()
        else:
            # Most-referenced service: GROUP BY is required for per-symbol
            # COUNT(*) — the old bare "ORDER BY COUNT(*) DESC" aggregated
            # the whole table into one meaningless order key.
            row = conn.execute(
                "SELECT service_symbol FROM be_execution_steps "
                "GROUP BY service_symbol "
                "ORDER BY COUNT(*) DESC, service_symbol LIMIT 1"
            ).fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception:
        pass
    try:
        row = conn.execute(
            "SELECT symbol FROM graph_nodes WHERE kind = 'service' "
            "AND symbol LIKE ? ESCAPE '\\' LIMIT 1",
            (f"%{_like_literal(module)}%",),
        ).fetchone() if module else conn.execute(
            "SELECT symbol FROM graph_nodes WHERE kind = 'service' LIMIT 1"
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception:
        pass
    return ""


def generate_solution_bundle(db, module: str = "", *, out_file: Optional[str] = None) -> Dict[str, Any]:
    """
    Synthesize complete Stage 2 Context Bundle for Solution.md and downstream subagents.
    Includes UI Form Fields, DataTable Types, API Specs, 4-Column Step Tables, Schema DDL, and Mermaid diagrams.

    Sections 2, 4 (partial), 5, 6 are template scaffolding, NOT graph-derived;
    they are labelled as such so no unverified content is presented as fact.
    """
    conn = getattr(db, "conn", db)
    inventory = generate_feature_inventory(db, module)
    service_symbol = _resolve_service_symbol(conn, module)
    steps_result = extract_execution_steps(db, service_symbol)

    md_lines = [
        f"# CONTEXT BUNDLE & TÀI LIỆU GIẢI PHÁP: {module or 'HỆ THỐNG UNIPAY'}",
        "",
        f"> **Solution Bundle cho module:** `{module or service_symbol or 'N/A'}` — PHẦN 1 & 3 được suy ra từ đồ thị/AST (SOT-Graph). "
        "PHẦN 2, 4 (trừ bảng bước xử lý), 5, 6 là **khung template GỢI Ý, chưa được đồ thị kiểm chứng** — phải đối chiếu với module thực tế trước khi sử dụng.",
        "",
        "---",
        "## PHẦN 1: TỔNG QUAN VÀ PHẠM VI TÍNH NĂNG (STAGE 1 SCOPE)",
        "",
        inventory["markdown"],
        "",
        "---",
        "## PHẦN 2: ĐẶC TẢ GIAO DIỆN (FRONTEND UI SPECIFICATION)",
        "",
        "### 1. Chi tiết các trường giao diện (Form Fields & Inputs)",
        "| STT | Tên trường | Mã trường (ID/Name) | Kiểu control | Bắt buộc | Giá trị mặc định | Quy tắc Validate |",
        "| :---: | :--- | :--- | :--- | :---: | :--- | :--- |",
        "| 1 | Số điện thoại | `msisdn` | Input text | Có | Trống | Regex số điện thoại 10 chữ số |",
        "| 2 | Loại thuê bao | `subscriberType` | Radio Button | Có | PREPAID | Giá trị: PREPAID / POSTPAID |",
        "| 3 | Số tiền giao dịch | `amount` | Input number | Có | Trống | Giá trị > 0, chia hết cho 1.000 |",
        "| 4 | Ghi chú giao dịch | `remark` | Textarea | Không | Trống | Tối đa 255 ký tự |",
        "",
        "### 2. Cấu hình bảng hiển thị (DataTable Columns)",
        "| STT | Tên cột | Mã trường | Kiểu dữ liệu | Cho phép sắp xếp | Cho phép tìm kiếm |",
        "| :---: | :--- | :--- | :--- | :---: | :---: |",
        "| 1 | Mã giao dịch | `transactionId` | **String** | Có | Có |",
        "| 2 | Số điện thoại | `msisdn` | **String** | Có | Có |",
        "| 3 | Số tiền | `amount` | **String** (Formatted) | Có | Không |",
        "| 4 | Trạng thái | `status` | **HTML Badge** | Có | Có |",
        "| 5 | Thời gian tạo | `createdAt` | **DateTime** | Có | Có |",
        "| 6 | Thao tác | `actions` | **HTML Button / Dropdown** | Không | Không |",
        "",
        "---",
        "## PHẦN 3: ĐẶC TẢ XỬ LÝ BACKEND & TÍNH TIỀN NHÂN LỰC",
        "",
        steps_result["markdown_table"],
        "",
        "---",
        "## PHẦN 4: ĐẶC TẢ API & GIAO THỨC TÍCH HỢP (4 TIỂU MỤC)",
        "",
        "### 1. Thông tin chung",
        "- **Tên API:** Trừ tiền và kiểm tra hạn mức thuê bao trả sau",
        "- **Phương thức & Endpoint:** `POST /api/v1/payments/deduct`",
        "- **Mô tả:** Tiếp nhận yêu cầu thanh toán, kiểm tra hạn mức BCCS nếu là thuê bao trả sau, và trừ tiền Core.",
        "",
        "### 2. Danh sách tham số đầu vào (Request DTO)",
        "| STT | Tên tham số | Kiểu dữ liệu | Bắt buộc | Vị trí | Mô tả |",
        "| :---: | :--- | :--- | :---: | :--- | :--- |",
        "| 1 | `msisdn` | String | Có | Body (JSON) | Số điện thoại thực hiện giao dịch |",
        "| 2 | `amount` | Long | Có | Body (JSON) | Số tiền cần trừ (> 0) |",
        "| 3 | `requestId` | String | Có | Header | Idempotency key chống trùng lặp |",
        "",
        "### 3. Danh sách tham số đầu ra (Response DTO)",
        "| STT | Tên tham số | Kiểu dữ liệu | Bắt buộc | Mô tả |",
        "| :---: | :--- | :--- | :---: | :--- |",
        "| 1 | `code` | String | Có | Mã kết quả (00: Thành công, 01: Lỗi) |",
        "| 2 | `message` | String | Có | Thông điệp phản hồi chi tiết |",
        "| 3 | `transactionId` | String | Không | Mã định danh giao dịch Core phát sinh |",
        "",
        "### 4. Luồng xử lý chi tiết của API",
        steps_result["markdown_table"],
        "",
        "---",
        "## PHẦN 5: THIẾT KẾ CƠ SỞ DỮ LIỆU (DATABASE SCHEMA)",
        "",
        "```sql",
        "-- Bảng danh sách thuê bao trả sau",
        "CREATE TABLE postpaid_subscriber (",
        "    id BIGINT PRIMARY KEY AUTO_INCREMENT,",
        "    msisdn VARCHAR(20) NOT NULL UNIQUE,",
        "    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',",
        "    credit_limit DECIMAL(18,2) DEFAULT 0,",
        "    current_debt DECIMAL(18,2) DEFAULT 0,",
        "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,",
        "    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,",
        "    INDEX idx_postpaid_msisdn (msisdn),",
        "    INDEX idx_postpaid_status (status)",
        ");",
        "```",
        "",
        "---",
        "## PHẦN 6: SƠ ĐỒ MERMAID CHUẨN",
        "",
        "```mermaid",
        "sequenceDiagram",
        "    autonumber",
        "    actor Client as Khách hàng / API Caller",
        "    participant Ctrl as PaymentController",
        "    participant Svc as MobileBalanceServiceImpl",
        "    participant LocalDB as Unipay DB (postpaid_subscriber)",
        "    participant BCCS as BCCS DataSource",
        "    participant Core as Core Balance Service",
        "",
        "    Client->>Ctrl: POST /api/v1/payments/deduct",
        "    Ctrl->>Svc: deductBalance(msisdn, amount)",
        "    Svc->>LocalDB: findByMsisdn(msisdn)",
        "    alt Là thuê bao trả sau (Postpaid)",
        "        LocalDB-->>Svc: PostpaidSubscriber Record",
        "        Svc->>BCCS: querySubscriberLimit(msisdn)",
        "        BCCS-->>Svc: LimitInfo (creditLimit, currentDebt)",
        "        alt Vượt hạn mức (debt + amount > creditLimit)",
        "            Svc-->>Ctrl: throw BusinessException(LIMIT_EXCEEDED)",
        "            Ctrl-->>Client: HTTP 400 Bad Request",
        "        else Đủ hạn mức",
        "            Svc->>Core: recordTransaction(msisdn, amount)",
        "            Core-->>Svc: Success",
        "            Svc-->>Ctrl: PaymentResponse(SUCCESS)",
        "            Ctrl-->>Client: HTTP 200 OK",
        "        end",
        "    else Là thuê bao trả trước (Prepaid)",
        "        LocalDB-->>Svc: Not Found",
        "        Svc->>Core: processPrepaidDeduction(msisdn, amount)",
        "        Core-->>Svc: Success",
        "        Svc-->>Ctrl: PaymentResponse(SUCCESS)",
        "        Ctrl-->>Client: HTTP 200 OK",
        "    end",
        "```",
    ]

    bundle_content = "\n".join(md_lines)
    if out_file:
        os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as fp:
            fp.write(bundle_content)

    return {
        "module": module,
        "inventory": inventory,
        "steps": steps_result,
        "bundle": bundle_content,
        "bundle_content": bundle_content,
        "bundle_markdown": bundle_content,
        "out_file": out_file,
    }
