"""
tests.test_solution_trace - Comprehensive Unit Tests for SOT-Graph Trace & Solution Engines.
"""

import asyncio
import os
import shutil
import sqlite3
import tempfile
import unittest

from sot_graph.trace import (
    trace_fullstack,
    extract_ui_tree,
    extract_backend_flow,
)
from sot_graph.solution import (
    generate_feature_inventory,
    extract_execution_steps,
    generate_solution_bundle,
    _resolve_service_symbol,
)
from sot_graph.mcp_service import McpService


class TestSolutionAndTraceEngine(unittest.TestCase):
    """Unit tests for AST execution step extraction, Mermaid rendering, and Solution packaging."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "sot.db")
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row

        # Initialize schema
        self.db.executescript("""
        CREATE TABLE graph_nodes (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            kind TEXT NOT NULL,
            symbol TEXT NOT NULL,
            fqn TEXT NOT NULL,
            signature TEXT,
            label TEXT,
            body TEXT,
            line_start INTEGER,
            line_end INTEGER,
            col_start INTEGER,
            col_end INTEGER
        );

        CREATE TABLE graph_edges (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            kind TEXT NOT NULL,
            weight REAL DEFAULT 1.0
        );

        CREATE TABLE ast_symbols (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            file_path TEXT NOT NULL,
            line_start INTEGER,
            line_end INTEGER,
            col_start INTEGER,
            col_end INTEGER,
            signature TEXT,
            docstring TEXT,
            body TEXT
        );

        CREATE TABLE ast_relations (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            line_number INTEGER,
            metadata TEXT
        );
        """)

        # Insert sample AST fixtures
        self._seed_sample_data()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_sample_data(self):
        # 1. UI Component (React/Vue/HTML)
        ui_body = """
        export const PostpaidSubscriberForm = () => {
            const handleSync = () => {
                if (!phone) {
                    alert('Phone required');
                    return;
                }
                api.post('/api/v1/subscribers/sync', { phone });
            };
            return (
                <div>
                    <input name="phone" required />
                    <button id="btn-sync" onClick={handleSync}>Sync Subscriber</button>
                    <DataTable id="tbl-postpaid" data={subscribers} />
                </div>
            );
        };
        """
        self.db.execute("""
        INSERT INTO graph_nodes (id, path, kind, symbol, fqn, signature, label, body, line_start, line_end)
        VALUES ('ui_comp_1', 'frontend/src/PostpaidSubscriberForm.tsx', 'component', 'PostpaidSubscriberForm',
                'frontend.PostpaidSubscriberForm', 'export const PostpaidSubscriberForm = () =>', 'UI Form', ?, 1, 30)
        """, (ui_body,))

        # 2. Webhook Controller (Backend API Endpoint)
        ctrl_body = """
        @RestController
        @RequestMapping("/api/v1/webhooks/laoid")
        public class LaoIdWebhookController {
            @PostMapping("/subscriber-event")
            public ResponseEntity<ApiResponse> handleSubscriberEvent(@RequestBody SubscriberEventDto dto) {
                if (!signatureValidator.verify(dto)) {
                    throw new UnauthorizedException("Invalid HMAC");
                }
                postpaidSyncService.syncSubscriber(dto);
                return ResponseEntity.ok(ApiResponse.success());
            }
        }
        """
        self.db.execute("""
        INSERT INTO graph_nodes (id, path, kind, symbol, fqn, signature, label, body, line_start, line_end)
        VALUES ('ctrl_node_1', 'unipay-api/src/main/java/LaoIdWebhookController.java', 'controller', 'LaoIdWebhookController',
                'unipay.api.LaoIdWebhookController', 'public class LaoIdWebhookController', 'REST Controller', ?, 1, 40)
        """, (ctrl_body,))

        # 3. MobileBalanceServiceImpl (Business Service)
        svc_body = """
        @Service
        public class MobileBalanceServiceImpl implements MobileBalanceService {
            @Transactional
            public PaymentResult deductBalance(String msisdn, BigDecimal amount) {
                log.info("Starting deductBalance for msisdn: " + msisdn);
                if (msisdn == null || msisdn.isEmpty()) {
                    throw new InvalidParameterException("MSISDN cannot be empty");
                }
                PostpaidSubscriber sub = postpaidSubscriberRepository.findByMsisdn(msisdn);
                if (sub != null) {
                    LimitInfo limit = bccsSubscriberService.querySubscriberLimit(msisdn);
                    if (limit.getCurrentDebt().add(amount).compareTo(limit.getCreditLimit()) > 0) {
                        throw new BusinessException("POSTPAID_LIMIT_EXCEEDED");
                    }
                }
                return coreLedgerService.processDeduction(msisdn, amount);
            }
        }
        """
        self.db.execute("""
        INSERT INTO graph_nodes (id, path, kind, symbol, fqn, signature, label, body, line_start, line_end)
        VALUES ('svc_node_1', 'unipay-service/src/main/java/MobileBalanceServiceImpl.java', 'service', 'MobileBalanceServiceImpl',
                'unipay.service.MobileBalanceServiceImpl', 'public class MobileBalanceServiceImpl', 'Balance Service', ?, 1, 50)
        """, (svc_body,))

        # 4. Edges
        self.db.execute("INSERT INTO graph_edges (id, source, target, kind) VALUES ('e1', 'ctrl_node_1', 'svc_node_1', 'calls')")
        self.db.commit()

    def test_trace_fullstack_returns_complete_payload(self):
        trace_data = trace_fullstack(self.db, "MobileBalanceServiceImpl", depth=2)
        self.assertIn("target", trace_data)
        self.assertEqual(trace_data["target"], "MobileBalanceServiceImpl")
        self.assertGreater(len(trace_data["nodes"]), 0)
        self.assertIn("ui_decisions", trace_data)
        self.assertIn("backend_steps", trace_data)
        self.assertIn("mermaid", trace_data)
        self.assertIn("flowchart", trace_data["mermaid"])
        self.assertIn("sequence", trace_data["mermaid"])
        self.assertIn("graph TD", trace_data["mermaid"]["flowchart"])
        self.assertIn("sequenceDiagram", trace_data["mermaid"]["sequence"])

    def test_extract_ui_tree(self):
        tree = extract_ui_tree(self.db, "PostpaidSubscriberForm")
        self.assertEqual(tree["component"], "PostpaidSubscriberForm")
        self.assertGreater(len(tree["fields"]), 0)
        self.assertGreater(len(tree["actions"]), 0)

    def test_extract_backend_flow(self):
        be_flow = extract_backend_flow(self.db, "MobileBalanceServiceImpl")
        self.assertEqual(be_flow["service"], "MobileBalanceServiceImpl")
        self.assertGreater(len(be_flow["steps"]), 0)
        self.assertIn("datasources", be_flow)

    def test_generate_feature_inventory(self):
        inventory_res = generate_feature_inventory(self.db)
        self.assertIn("markdown", inventory_res)
        markdown_text = inventory_res["markdown"]
        self.assertIn("FEATURE INVENTORY", markdown_text)
        self.assertIn("Stage 1 Scope Gatekeeper", markdown_text)
        self.assertIn("Tính năng liên quan", markdown_text)

    def test_extract_execution_steps_and_4col_table(self):
        res = extract_execution_steps(self.db, "MobileBalanceServiceImpl")
        self.assertIn("steps", res)
        self.assertIn("markdown_table", res)
        self.assertGreater(len(res["steps"]), 0)

        table_md = res["markdown_table"]
        self.assertIn("Bảng các bước xử lý chi tiết", table_md)
        self.assertIn("| TT | Tên bước | Lệnh thực thi | Mô tả chi tiết logic |", table_md)

    def test_generate_solution_bundle(self):
        bundle_res = generate_solution_bundle(self.db)
        self.assertIn("bundle_content", bundle_res)
        bundle_md = bundle_res["bundle_content"]
        self.assertIn("# CONTEXT BUNDLE & TÀI LIỆU GIẢI PHÁP", bundle_md)
        self.assertIn("PHẦN 1: TỔNG QUAN VÀ PHẠM VI TÍNH NĂNG", bundle_md)
        self.assertIn("PHẦN 2: ĐẶC TẢ GIAO DIỆN (FRONTEND UI SPECIFICATION)", bundle_md)
        self.assertIn("PHẦN 3: ĐẶC TẢ XỬ LÝ BACKEND", bundle_md)
        self.assertIn("PHẦN 4: ĐẶC TẢ API & GIAO THỨC TÍCH HỢP", bundle_md)
    def test_mcp_service_async_primitives(self):
        service = McpService(self.db_path, self.temp_dir)
        async def run_checks():
            trace_res = await service.atrace("MobileBalanceServiceImpl")
            self.assertEqual(trace_res["target"], "MobileBalanceServiceImpl")

            ui_res = await service.aui_tree("PostpaidSubscriberForm")
            self.assertEqual(ui_res["component"], "PostpaidSubscriberForm")

            be_res = await service.abackend_flow("MobileBalanceServiceImpl")
            self.assertEqual(be_res["service"], "MobileBalanceServiceImpl")

            inv_res = await service.asolution_inventory()
            self.assertIn("markdown", inv_res)

            steps_res = await service.asolution_steps("MobileBalanceServiceImpl")
            self.assertIn("markdown_table", steps_res)

            bundle_res = await service.asolution_bundle()
            self.assertIn("bundle_content", bundle_res)

        asyncio.run(run_checks())


class TestResolveServiceSymbol(unittest.TestCase):
    """G10: LIKE literal escaping + real GROUP BY for the most-referenced service."""

    def _conn(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE be_execution_steps (service_symbol TEXT)")
        conn.execute(
            "CREATE TABLE graph_nodes (id TEXT, path TEXT, kind TEXT, symbol TEXT)"
        )
        return conn

    def test_underscore_in_module_matches_literal_only(self):
        conn = self._conn()
        conn.executemany(
            "INSERT INTO be_execution_steps VALUES (?)",
            [("coreXbase_service",), ("core_base_service",)],
        )
        conn.commit()
        # Unescaped, '_' would wildcard-match coreXbase_service too and
        # 'coreXbase_service' sorts first — the wrong service.
        self.assertEqual(_resolve_service_symbol(conn, "core_base"), "core_base_service")

    def test_no_module_picks_most_referenced_service(self):
        conn = self._conn()
        rows = [("svc_a",), ("svc_b",), ("svc_b",), ("svc_b",), ("svc_c",)]
        conn.executemany("INSERT INTO be_execution_steps VALUES (?)", rows)
        conn.commit()
        self.assertEqual(_resolve_service_symbol(conn, ""), "svc_b")

    def test_falls_back_to_graph_nodes_literal_like(self):
        conn = self._conn()
        conn.execute(
            "INSERT INTO graph_nodes VALUES ('n1', 'x.py', 'service', 'PaymentService')"
        )
        conn.commit()
        self.assertEqual(_resolve_service_symbol(conn, "Pay%ment"), "")
        self.assertEqual(_resolve_service_symbol(conn, "Pay"), "PaymentService")
