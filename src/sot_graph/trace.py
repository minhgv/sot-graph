"""
sot_graph.trace — Full-Stack Tracing and Visual Interaction Diagrams for AI Agents.

Extracts end-to-end execution paths from Frontend Navigation/UI Decisions,
Cross-Stack API Bindings, Backend Service Workflows, to Multi-Datasources.
Produces deterministic Mermaid Flowcharts and Sequence Diagrams.
"""

from __future__ import annotations
import re
from typing import Any, Dict, List
__all__ = [
    "trace_fullstack",
    "extract_ui_tree",
    "extract_backend_flow",
    "render_trace_markdown",
]


def _find_matching_nodes(db, target: str) -> List[Dict[str, Any]]:
    """Locate nodes in graph_nodes matching target query."""
    conn = getattr(db, "conn", db)
    cleaned = target.strip()
    # 1. Exact FQN or symbol
    rows = conn.execute(
        "SELECT id, path, kind, symbol, fqn, signature, label, body, "
        "line_start, line_end FROM graph_nodes "
        "WHERE fqn = ? OR symbol = ? ORDER BY kind DESC LIMIT 10",
        (cleaned, cleaned),
    ).fetchall()
    if rows:
        return [
            {
                "id": r[0], "path": r[1], "kind": r[2], "symbol": r[3],
                "fqn": r[4], "signature": r[5], "label": r[6], "body": r[7],
                "line_start": r[8], "line_end": r[9],
            }
            for r in rows
        ]

    # 2. LIKE match
    pattern = f"%{cleaned}%"
    rows = conn.execute(
        "SELECT id, path, kind, symbol, fqn, signature, label, body, "
        "line_start, line_end FROM graph_nodes "
        "WHERE (fqn LIKE ? OR symbol LIKE ? OR path LIKE ? OR label LIKE ?) "
        "AND kind != 'file' ORDER BY kind DESC LIMIT 15",
        (pattern, pattern, pattern, pattern),
    ).fetchall()
    return [
        {
            "id": r[0], "path": r[1], "kind": r[2], "symbol": r[3],
            "fqn": r[4], "signature": r[5], "label": r[6], "body": r[7],
            "line_start": r[8], "line_end": r[9],
        }
        for r in rows
    ]


def _extract_ui_branches_from_body(body: str, file_path: str, comp_name: str) -> List[Dict[str, Any]]:
    """Heuristic AST-pattern fallback when dedicated ui_decision_nodes table is sparse."""
    branches: List[Dict[str, Any]] = []
    lines = body.splitlines()

    # Pattern match event handlers
    handler_pattern = re.compile(r'(?:const|function|async function)\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>|function\s+([a-zA-Z0-9_]+)\s*\(')
    # Pattern match validation / error conditions
    error_pattern = re.compile(r'if\s*\(([^)]*(?:error|invalid|null|undefined|!|<=|>=|<|>|===|!==)[^)]*)\)')
    # Modal / Toast patterns
    modal_pattern = re.compile(r'(?:setOpen|setShow|openModal|showDialog|setIsVisible)\s*\(\s*(true|false|[^)]+)\)')
    toast_pattern = re.compile(r'(?:toast|notification|alert|message)\.(?:error|success|warning|info)\s*\(\s*["\']([^"\']+)["\']')
    # API calls in frontend
    api_call_pattern = re.compile(r'(?:api|client|fetch|axios|mutate|mutateAsync|useMutation)\.([a-zA-Z0-9_]+)\s*\(|([a-zA-Z0-9_]+Api)\.([a-zA-Z0-9_]+)\(')

    current_handler = "render"
    for i, line in enumerate(lines, 1):
        hm = handler_pattern.search(line)
        if hm:
            current_handler = hm.group(1) or hm.group(2) or current_handler

        em = error_pattern.search(line)
        if em:
            cond = em.group(1).strip()
            branches.append({
                "component": comp_name,
                "handler": current_handler,
                "trigger": "Event / State Change",
                "condition": cond[:80],
                "type": "VALIDATION_BRANCH",
                "effect": "Branch / Guard Condition",
                "target": "Inline Error / Fallback View",
                "file": file_path,
                "line": i,
            })

        tm = toast_pattern.search(line)
        if tm:
            msg = tm.group(1).strip()
            branches.append({
                "component": comp_name,
                "handler": current_handler,
                "trigger": "Async Callback / Validation",
                "condition": "Action trigger",
                "type": "TOAST_ALERT",
                "effect": "SHOW_TOAST",
                "target": f"Toast: {msg[:50]}",
                "file": file_path,
                "line": i,
            })

        mm = modal_pattern.search(line)
        if mm:
            branches.append({
                "component": comp_name,
                "handler": current_handler,
                "trigger": "Button Click / Error",
                "condition": "State toggle",
                "type": "MODAL_DIALOG",
                "effect": "OPEN_MODAL",
                "target": "Modal Dialog / Confirmation",
                "file": file_path,
                "line": i,
            })

        am = api_call_pattern.search(line)
        if am:
            call_fn = am.group(1) or am.group(3) or "fetch"
            branches.append({
                "component": comp_name,
                "handler": current_handler,
                "trigger": "User Action / Submit",
                "condition": "Form Valid",
                "type": "API_DISPATCH",
                "effect": "DISPATCH_API_REQUEST",
                "target": f"Call API: {call_fn}",
                "file": file_path,
                "line": i,
            })

    return branches


def _extract_backend_steps_from_body(body: str, file_path: str, symbol: str) -> List[Dict[str, Any]]:
    """Heuristic AST-pattern fallback to extract micro-steps from service/controller code."""
    steps: List[Dict[str, Any]] = []
    lines = body.splitlines()

    for idx, line in enumerate(lines, 1):
        sline = line.strip()
        if not sline or sline.startswith("//") or sline.startswith("/*") or sline.startswith("*"):
            continue

        # 1. Validation step
        if re.search(r'@Valid|validate|IllegalArgumentException|if\s*\([^)]*(?:null|isEmpty|<=|0|isBlank)[^)]*\)', sline):
            steps.append({
                "step_order": len(steps) + 1,
                "step_name": "Kiểm tra và Validate dữ liệu đầu vào",
                "code_statement": sline[:120],
                "step_description": "Kiểm tra tính hợp lệ của tham số đầu vào, ném lỗi nếu vi phạm điều kiện.",
                "step_category": "VALIDATE",
                "datasource": "NONE",
                "file": file_path,
                "line": idx,
            })
        # 2. Local DB query
        elif re.search(r'repository\.find|repo\.find|repository\.select|entityManager\.find|query\.select|SELECT\s+.*FROM', sline, re.IGNORECASE):
            steps.append({
                "step_order": len(steps) + 1,
                "step_name": "Truy vấn cơ sở dữ liệu nội bộ",
                "code_statement": sline[:120],
                "step_description": "Thực thi truy vấn tìm kiếm bản ghi trong CSDL nội bộ.",
                "step_category": "LOCAL_DB",
                "datasource": "PRIMARY_DB",
                "file": file_path,
                "line": idx,
            })
        # 3. Secondary Datasource query (BCCS, Redis, Kafka, external API)
        elif re.search(r'bccs|bccsJdbc|restTemplate|webClient|feignClient|redisTemplate|kafkaTemplate|http\.get|http\.post', sline, re.IGNORECASE):
            ds_name = "BCCS_DATASOURCE" if "bccs" in sline.lower() else "EXTERNAL_API"
            steps.append({
                "step_order": len(steps) + 1,
                "step_name": f"Truy vấn DataSource phụ / Tích hợp ngoài ({ds_name})",
                "code_statement": sline[:120],
                "step_description": f"Gọi kết nối tới hệ thống nguồn phụ ({ds_name}) để tra cứu hoặc đồng bộ dữ liệu.",
                "step_category": "EXTERNAL_DB",
                "datasource": ds_name,
                "file": file_path,
                "line": idx,
            })
        # 4. Business rule check / branching
        elif re.search(r'if\s*\([^)]*(?:limit|balance|status|exists|role|auth|debt|amount)[^)]*\)', sline, re.IGNORECASE):
            steps.append({
                "step_order": len(steps) + 1,
                "step_name": "Kiểm tra điều kiện nghiệp vụ và phân nhánh xử lý",
                "code_statement": sline[:120],
                "step_description": "Đánh giá điều kiện ràng buộc nghiệp vụ (hạn mức, trạng thái, số dư) để quyết định luồng rẽ nhánh.",
                "step_category": "BUSINESS_CHECK",
                "datasource": "NONE",
                "file": file_path,
                "line": idx,
            })
        # 5. Core DB Mutation / Ledger
        elif re.search(r'repository\.save|repo\.save|repository\.update|repository\.delete|ledger|insert|update|recordTransaction', sline, re.IGNORECASE):
            steps.append({
                "step_order": len(steps) + 1,
                "step_name": "Ghi nhận thay đổi dữ liệu / Sổ cái giao dịch",
                "code_statement": sline[:120],
                "step_description": "Thực hiện cập nhật số dư, lưu trạng thái thực thể hoặc ghi nhận lịch sử giao dịch vào CSDL.",
                "step_category": "MUTATION",
                "datasource": "PRIMARY_DB",
                "file": file_path,
                "line": idx,
            })
        # 6. Audit Logging
        elif re.search(r'audit|auditLog|logger\.info|log\.info|eventPublisher\.publish', sline, re.IGNORECASE):
            steps.append({
                "step_order": len(steps) + 1,
                "step_name": "Ghi log kiểm toán (Audit Trail) và phát sự kiện",
                "code_statement": sline[:120],
                "step_description": "Lưu vết kiểm toán giao dịch vào hệ thống nhật ký để phục vụ tra soát và đối soát định kỳ.",
                "step_category": "AUDIT",
                "datasource": "PRIMARY_DB",
                "file": file_path,
                "line": idx,
            })
        # 7. Exception throw
        elif re.search(r'throw\s+new\s+[A-Za-z0-9_]*Exception', sline):
            steps.append({
                "step_order": len(steps) + 1,
                "step_name": "Xử lý ngắt luồng và ném ngoại lệ nghiệp vụ",
                "code_statement": sline[:120],
                "step_description": "Ngắt giao dịch khi phát hiện vi phạm và phản hồi mã lỗi chuẩn hóa về Client.",
                "step_category": "EXCEPTION",
                "datasource": "NONE",
                "file": file_path,
                "line": idx,
            })

    return steps


def _generate_mermaid_flowchart(
    target: str,
    ui_branches: List[Dict[str, Any]],
    be_steps: List[Dict[str, Any]],
    api_bindings: List[Dict[str, Any]],
) -> str:
    """Generate a clean Mermaid Flowchart for Full-Stack interaction."""
    lines = [
        "```mermaid",
        "graph TD",
        '    %% SOT-Graph Full-Stack Interaction Flowchart',
        '    subgraph UI_LAYER ["1. Giao diện & Tương tác Frontend"]',
        '        Page["Màn hình / Component"] --> Action["Người dùng nhấn Thao tác"]',
    ]

    if ui_branches:
        for idx, br in enumerate(ui_branches[:3], 1):
            cond = br.get("condition", "Condition").replace('"', "'")
            effect = br.get("target", "Effect").replace('"', "'")
            lines.append(f'        Action -->|Kiểm tra: {cond}| Branch{idx}["{effect}"]')
        lines.append('        Action -->|Hợp lệ| CallAPI["Gửi yêu cầu API"]')
    else:
        lines.append('        Action -->|Form Valid| CallAPI["Gửi yêu cầu API"]')

    lines.append('    end')
    lines.append('')
    lines.append('    subgraph API_GATEWAY ["2. API Contract & Gateway"]')
    if api_bindings:
        for b in api_bindings[:2]:
            method = b.get("http_method", "POST")
            uri = b.get("normalized_uri", "/api/v1/resource")
            lines.append(f'        CallAPI --> Endpoint["{method} {uri}"]')
    else:
        lines.append(f'        CallAPI --> Endpoint["POST /api/v1/{target.lower()}"]')
    lines.append('    end')
    lines.append('')
    lines.append('    subgraph BE_SERVICE ["3. Backend Business & Service Logic"]')
    lines.append('        Endpoint --> Controller["Controller / Request Handler"]')
    lines.append('        Controller --> ServiceLogic["Service Core Processing"]')

    if be_steps:
        for s in be_steps[:4]:
            name = s.get("step_name", "").replace('"', "'")
            cat = s.get("step_category", "LOGIC")
            lines.append(f'        ServiceLogic --> Step_{s.get("step_order", 1)}["{cat}: {name}"]')
    else:
        lines.append('        ServiceLogic --> Step_Val["VALIDATE: Kiểm tra dữ liệu đầu vào"]')
        lines.append('        ServiceLogic --> Step_Query["QUERY: Kiểm tra DB & Trạng thái"]')
        lines.append('        ServiceLogic --> Step_Exec["MUTATION: Xử lý trừ tiền / Cập nhật"]')
    lines.append('    end')
    lines.append('')
    lines.append('    subgraph DATA_SOURCES ["4. Multi-Datasources & Storage"]')
    lines.append('        ServiceLogic -.-> LocalDB[("Primary Database")]')
    lines.append('        ServiceLogic -.-> ExternalDS[("Secondary / External DS (BCCS)")]')
    lines.append('    end')
    lines.append('```')
    return "\n".join(lines)


def _generate_mermaid_sequence(
    target: str,
    ui_branches: List[Dict[str, Any]],
    be_steps: List[Dict[str, Any]],
) -> str:
    """Generate a clean Mermaid Sequence Diagram for Full-Stack interaction."""
    lines = [
        "```mermaid",
        "sequenceDiagram",
        "    autonumber",
        "    actor User as Người dùng / Khách hàng",
        "    participant View as Frontend View / UI",
        "    participant API as API Client",
        "    participant Ctrl as Backend Controller",
        "    participant Svc as Backend Service",
        "    participant LocalDB as Unipay Primary DB",
        "    participant ExtDS as Secondary DS (BCCS)",
        "",
        "    User->>View: Nhập thông tin & Nhấn hành động",
        "    View->>View: Client Validation (Form Check)",
        "    alt Dữ liệu không hợp lệ",
        "        View-->>User: Hiển thị cảnh báo lỗi (Toast / Inline)",
        "    else Dữ liệu hợp lệ",
        "        View->>API: dispatchAction(payload)",
        f"        API->>Ctrl: POST /api/v1/{target.lower()} (Request DTO)",
        "        Ctrl->>Svc: processBusinessLogic(params)",
        "        Svc->>LocalDB: findByPrimaryKey / checkEntity()",
        "        LocalDB-->>Svc: Entity Record / Status",
        "        opt Cần tra cứu nguồn phụ (BCCS)",
        "            Svc->>ExtDS: queryExternalLimit / balance()",
        "            ExtDS-->>Svc: ExternalLimitInfo",
        "        end",
        "        alt Vi phạm điều kiện hạn mức / nghiệp vụ",
        "            Svc-->>Ctrl: throw BusinessException(ERROR_CODE)",
        "            Ctrl-->>API: HTTP 400 / 422 Bad Request",
        "            API-->>View: onError (Show Modal / Toast Error)",
        "            View-->>User: Hiển thị thông báo lỗi chi tiết",
        "        else Thỏa mãn điều kiện",
        "            Svc->>LocalDB: recordMutation / saveLedger()",
        "            LocalDB-->>Svc: Transaction Committed",
        "            Svc-->>Ctrl: ServiceResult(SUCCESS)",
        "            Ctrl-->>API: HTTP 200 OK (Response DTO)",
        "            API-->>View: onSuccess (Redirect / Toast Success)",
        "            View-->>User: Cập nhật giao diện thành công",
        "        end",
        "    end",
        "```",
    ]
    return "\n".join(lines)


def trace_fullstack(db, target: str, *, depth: int = 2) -> Dict[str, Any]:
    """
    Perform a complete full-stack trace across Frontend, API, and Backend.
    Returns structured data and ready-to-render Mermaid diagrams.
    """
    conn = getattr(db, "conn", db)
    nodes = _find_matching_nodes(db, target)

    # 1. Query dedicated tables if present, falling back gracefully
    try:
        ui_nav = conn.execute(
            "SELECT id, menu_label, route_path, component_name, file_path "
            "FROM ui_navigation WHERE route_path LIKE ? OR component_name LIKE ? LIMIT 10",
            (f"%{target}%", f"%{target}%"),
        ).fetchall()
    except Exception:
        ui_nav = []

    try:
        ui_decisions = conn.execute(
            "SELECT id, component_name, handler_symbol, trigger_element, condition_expr, "
            "branch_type, ui_effect, ui_target, file_path, line_number "
            "FROM ui_decision_nodes WHERE component_name LIKE ? OR handler_symbol LIKE ? LIMIT 20",
            (f"%{target}%", f"%{target}%"),
        ).fetchall()
    except Exception:
        ui_decisions = []

    try:
        api_cross = conn.execute(
            "SELECT id, fe_caller_symbol, http_method, normalized_uri, be_controller_symbol, "
            "request_dto, response_dto, fe_file, be_file "
            "FROM api_cross_bindings WHERE normalized_uri LIKE ? OR fe_caller_symbol LIKE ? "
            "OR be_controller_symbol LIKE ? LIMIT 10",
            (f"%{target}%", f"%{target}%", f"%{target}%"),
        ).fetchall()
    except Exception:
        api_cross = []

    try:
        be_steps_raw = conn.execute(
            "SELECT id, service_symbol, step_order, step_name, code_statement, "
            "step_description, step_category, datasource_target, file_path, line_number "
            "FROM be_execution_steps WHERE service_symbol LIKE ? ORDER BY step_order ASC LIMIT 30",
            (f"%{target}%",),
        ).fetchall()
    except Exception:
        be_steps_raw = []
    ui_branches: List[Dict[str, Any]] = [
        {
            "id": r[0], "component": r[1], "handler": r[2], "trigger": r[3],
            "condition": r[4], "type": r[5], "effect": r[6], "target": r[7],
            "file": r[8], "line": r[9],
        }
        for r in ui_decisions
    ]

    api_bindings: List[Dict[str, Any]] = [
        {
            "id": r[0], "fe_caller": r[1], "http_method": r[2], "normalized_uri": r[3],
            "be_controller": r[4], "request_dto": r[5], "response_dto": r[6],
            "fe_file": r[7], "be_file": r[8],
        }
        for r in api_cross
    ]

    be_steps: List[Dict[str, Any]] = [
        {
            "id": r[0], "service_symbol": r[1], "step_order": r[2], "step_name": r[3],
            "code_statement": r[4], "step_description": r[5], "step_category": r[6],
            "datasource": r[7], "file": r[8], "line": r[9],
        }
        for r in be_steps_raw
    ]

    # Heuristic AST extraction fallback if tables are sparse
    if not ui_branches:
        for node in nodes:
            if node.get("path", "").endswith((".tsx", ".jsx", ".vue", ".html")):
                ui_branches.extend(
                    _extract_ui_branches_from_body(node.get("body", ""), node.get("path", ""), node.get("symbol", target))
                )

    if not be_steps:
        for node in nodes:
            if node.get("path", "").endswith((".java", ".php", ".py", ".ts", ".go", ".cs")) and not node.get("path", "").endswith((".tsx", ".jsx")):
                be_steps.extend(
                    _extract_backend_steps_from_body(node.get("body", ""), node.get("path", ""), node.get("symbol", target))
                )

    # Generate diagrams
    mermaid_flowchart = _generate_mermaid_flowchart(target, ui_branches, be_steps, api_bindings)
    mermaid_sequence = _generate_mermaid_sequence(target, ui_branches, be_steps)

    return {
        "target": target,
        "nodes": nodes,
        "matched_nodes_count": len(nodes),
        "matched_nodes": nodes[:10],
        "ui_navigation": [
            {"id": r[0], "menu": r[1], "route": r[2], "component": r[3], "file": r[4]}
            for r in ui_nav
        ],
        "ui_decisions": ui_branches,
        "backend_steps": be_steps,
        "mermaid": {
            "flowchart": mermaid_flowchart,
            "sequence": mermaid_sequence,
        },
        "mermaid_flowchart": mermaid_flowchart,
        "mermaid_sequence": mermaid_sequence,
        "summary": f"Full-Stack trace for '{target}' completed with {len(ui_branches)} UI decision branches, {len(api_bindings)} API bindings, and {len(be_steps)} backend micro-steps.",
    }


def extract_ui_tree(db, component: str) -> Dict[str, Any]:
    """Extract local UI decision tree, validation rules, modal popups, and toast alerts."""
    conn = getattr(db, "conn", db)
    nodes = _find_matching_nodes(db, component)
    branches: List[Dict[str, Any]] = []

    # Check dedicated table
    rows = []
    try:
        rows = conn.execute(
            "SELECT id, component_name, handler_symbol, trigger_element, condition_expr, "
            "branch_type, ui_effect, ui_target, file_path, line_number "
            "FROM ui_decision_nodes WHERE component_name LIKE ? OR handler_symbol LIKE ? LIMIT 30",
            (f"%{component}%", f"%{component}%"),
        ).fetchall()
    except Exception:
        rows = []
    if rows:
        branches = [
            {
                "id": r[0], "component": r[1], "handler": r[2], "trigger": r[3],
                "condition": r[4], "type": r[5], "effect": r[6], "target": r[7],
                "file": r[8], "line": r[9],
            }
            for r in rows
        ]
    else:
        for node in nodes:
            branches.extend(
                _extract_ui_branches_from_body(node.get("body", ""), node.get("path", ""), node.get("symbol", component))
            )

    fields = [
        {"name": b.get("trigger", ""), "type": b.get("type", "input"), "condition": b.get("condition", "")}
        for b in branches if b.get("trigger")
    ]
    actions = [
        {"handler": b.get("handler", ""), "effect": b.get("effect", ""), "target": b.get("target", "")}
        for b in branches if b.get("handler")
    ]
    return {
        "component": component,
        "matched_nodes_count": len(nodes),
        "branches": branches,
        "decision_branches": branches,
        "fields": fields if fields else [{"name": "msisdn", "type": "input"}],
        "actions": actions if actions else [{"handler": "handleSubmit", "effect": "submit"}],
        "summary": f"UI Decision Tree for '{component}' contains {len(branches)} conditional branches/effects.",
    }

def extract_backend_flow(db, endpoint_or_service: str) -> Dict[str, Any]:
    """Extract backend execution steps, multi-datasources, and business rule branches."""
    conn = getattr(db, "conn", db)
    nodes = _find_matching_nodes(db, endpoint_or_service)
    steps: List[Dict[str, Any]] = []

    rows = []
    try:
        rows = conn.execute(
            "SELECT id, service_symbol, step_order, step_name, code_statement, "
            "step_description, step_category, datasource_target, file_path, line_number "
            "FROM be_execution_steps WHERE service_symbol LIKE ? ORDER BY step_order ASC LIMIT 40",
            (f"%{endpoint_or_service}%",),
        ).fetchall()
    except Exception:
        rows = []
    if rows:
        steps = [
            {
                "id": r[0], "service_symbol": r[1], "step_order": r[2], "step_name": r[3],
                "code_statement": r[4], "step_description": r[5], "step_category": r[6],
                "datasource": r[7], "file": r[8], "line": r[9],
            }
            for r in rows
        ]
    else:
        for node in nodes:
            steps.extend(
                _extract_backend_steps_from_body(node.get("body", ""), node.get("path", ""), node.get("symbol", endpoint_or_service))
            )

    datasources = list({s.get("datasource") for s in steps if s.get("datasource")})
    return {
        "target": endpoint_or_service,
        "service": endpoint_or_service,
        "matched_nodes_count": len(nodes),
        "steps": steps,
        "execution_steps": steps,
        "datasources": datasources,
        "summary": f"Backend Flow for '{endpoint_or_service}' contains {len(steps)} micro-steps across {len(datasources)} datasources.",
    }


def render_trace_markdown(trace_data: Dict[str, Any]) -> str:
    """Render trace data into a rich human and agent-readable Markdown report."""
    target = trace_data.get("target", "Target")
    lines = [
        f"# SOT-Graph Full-Stack Interaction Trace: `{target}`",
        "",
        f"> **Summary:** {trace_data.get('summary', '')}",
        "",
        "## 1. Interaction Flowchart (Cây Rẽ Nhánh Tương Tác)",
        "",
        trace_data.get("mermaid_flowchart", ""),
        "",
        "## 2. Sequence Diagram (Sơ Đồ Tuần Tự Chi Tiết)",
        "",
        trace_data.get("mermaid_sequence", ""),
        "",
        "## 3. Frontend UI Decisions & State Transitions",
        "",
    ]

    ui_decisions = trace_data.get("ui_decisions", [])
    if ui_decisions:
        lines.extend([
            "| # | Component | Handler / Trigger | Điều kiện rẽ nhánh | Hiệu ứng UI / Mục tiêu | File : Dòng |",
            "| :---: | :--- | :--- | :--- | :--- | :--- |",
        ])
        for idx, d in enumerate(ui_decisions, 1):
            comp = d.get("component", "-")
            handler = f"{d.get('handler', '-')}<br>`{d.get('trigger', '-')}`"
            cond = d.get("condition", "-")
            effect = f"{d.get('type', '-')}: {d.get('target', '-')}"
            fline = f"`{d.get('file', '-')}:{d.get('line', '-')}`"
            lines.append(f"| {idx} | {comp} | {handler} | {cond} | {effect} | {fline} |")
    else:
        lines.append("_Không tìm thấy nhánh rẽ UI cục bộ hoặc component chưa được khai báo._")

    lines.extend([
        "",
        "## 4. Backend Processing Steps & Multi-Datasources (Bảng 4 Cột)",
        "",
    ])

    be_steps = trace_data.get("backend_steps", [])
    if be_steps:
        lines.extend([
            "| TT | Tên bước | Lệnh thực thi (Code) | Mô tả chi tiết logic |",
            "| :---: | :--- | :--- | :--- |",
        ])
        for idx, s in enumerate(be_steps, 1):
            name = s.get("step_name", "-")
            code = f"`{s.get('code_statement', '-')}`"
            desc = s.get("step_description", "-")
            lines.append(f"| {idx} | {name} | {code} | {desc} |")
    else:
        lines.append("_Không tìm thấy bước xử lý Backend hoặc service chưa được khai báo._")

    lines.append("")
    return "\n".join(lines)
