from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sot_graph.analytics.architecture import (
    ArchitecturalLayer,
    classify_node_layer,
    detect_pattern_and_framework,
)
from sot_graph.analytics.diagnostics import (
    analyze_graph,
    calculate_graph_metrics,
)
from sot_graph.analytics.graph import AnalyticsGraph
from sot_graph.analytics.report import generate_markdown_report
from sot_graph.cli import build_parser, cmd_cluster, cmd_report
from sot_graph.db import Database
from sot_graph.reconciler import Reconciler


class AnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.mkdtemp(prefix="sot-analytics-")
        self.root_path = Path(self._temp_dir)
        self.db_path = self.root_path / ".sot" / "sot.db"
        self.db = Database(str(self.db_path))

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _populate_mock_project(self) -> None:
        """Create a mock multi-layer codebase with presentation, bloc, domain, data, and core layers."""
        # 1. Core Layer
        core_dir = self.root_path / "lib" / "core"
        core_dir.mkdir(parents=True, exist_ok=True)
        (core_dir / "app_router.dart").write_text(
            "class AppRouter { static void navigate(String path) {} }\n"
        )
        (core_dir / "api_client.dart").write_text(
            "class ApiClient { Future<Map> get(String url) async => {}; }\n"
        )

        # 2. Auth Feature (Clean Architecture)
        auth_pres = self.root_path / "lib" / "features" / "auth" / "presentation"
        auth_pres.mkdir(parents=True, exist_ok=True)
        (auth_pres / "login_screen.dart").write_text(
            "import 'package:app/features/auth/bloc/auth_bloc.dart';\n"
            "class LoginScreen extends StatelessWidget {\n"
            "  void onLoginPressed() { AuthBloc.login(); }\n"
            "}\n"
        )

        auth_bloc = self.root_path / "lib" / "features" / "auth" / "bloc"
        auth_bloc.mkdir(parents=True, exist_ok=True)
        (auth_bloc / "auth_bloc.dart").write_text(
            "import 'package:app/features/auth/domain/auth_usecase.dart';\n"
            "class AuthBloc {\n"
            "  static void login() { AuthUseCase.execute(); }\n"
            "}\n"
        )

        auth_domain = self.root_path / "lib" / "features" / "auth" / "domain"
        auth_domain.mkdir(parents=True, exist_ok=True)
        (auth_domain / "auth_usecase.dart").write_text(
            "import 'package:app/features/auth/data/auth_repository.dart';\n"
            "class AuthUseCase {\n"
            "  static void execute() { AuthRepository.authenticate(); }\n"
            "}\n"
        )

        auth_data = self.root_path / "lib" / "features" / "auth" / "data"
        auth_data.mkdir(parents=True, exist_ok=True)
        (auth_data / "auth_repository.dart").write_text(
            "import 'package:app/core/api_client.dart';\n"
            "class AuthRepository {\n"
            "  static void authenticate() { ApiClient().get('/auth'); }\n"
            "}\n"
        )

        # 3. Layer Bypass Anti-pattern: UI calling Data directly
        billing_pres = self.root_path / "lib" / "features" / "billing" / "presentation"
        billing_pres.mkdir(parents=True, exist_ok=True)
        (billing_pres / "quick_pay_widget.dart").write_text(
            "import 'package:app/core/api_client.dart';\n"
            "class QuickPayWidget extends StatelessWidget {\n"
            "  void pay() { ApiClient().get('/pay'); }\n"
            "}\n"
        )

        reconciler = Reconciler(
            self.db,
            str(self.root_path),
        )
        reconciler.reconcile()

    def test_layer_classification(self) -> None:
        """Test layer classification across various node paths and types."""
        l1 = classify_node_layer("n1", {"path": "lib/features/auth/presentation/login_page.dart"})
        self.assertEqual(l1, ArchitecturalLayer.PRESENTATION)

        l2 = classify_node_layer("n2", {"path": "lib/features/auth/bloc/auth_bloc.dart"})
        self.assertEqual(l2, ArchitecturalLayer.BUSINESS_LOGIC)

        l3 = classify_node_layer("n3", {"path": "lib/features/auth/domain/login_usecase.dart"})
        self.assertEqual(l3, ArchitecturalLayer.DOMAIN)

        l4 = classify_node_layer("n4", {"path": "lib/features/auth/data/auth_repository.dart"})
        self.assertEqual(l4, ArchitecturalLayer.DATA)

        l5 = classify_node_layer("n5", {"path": "lib/core/config/app_config.dart"})
        self.assertEqual(l5, ArchitecturalLayer.CORE)

    def test_pattern_and_framework_detection(self) -> None:
        """Test automatic architecture pattern detection."""
        self._populate_mock_project()
        g = AnalyticsGraph.from_database(self.db)
        pattern, lang, frameworks = detect_pattern_and_framework(g)

        self.assertIn("Flutter", pattern)
        self.assertIn("Dart", lang)
        self.assertTrue(len(frameworks) > 0)

    def test_analytics_graph_construction_and_metrics(self) -> None:
        self._populate_mock_project()
        graph = AnalyticsGraph.from_database(self.db)
        self.assertGreater(len(graph.nodes), 0)
        self.assertGreater(len(graph.edges), 0)

        comm_res = graph.detect_communities(min_community_size=1)
        self.assertGreater(len(comm_res.communities), 0)
        self.assertGreater(len(comm_res.community_info), 0)

        metrics = calculate_graph_metrics(graph, comm_res)
        self.assertEqual(metrics.node_count, len(graph.nodes))
        self.assertEqual(metrics.edge_count, len(graph.edges))
        self.assertGreaterEqual(metrics.density, 0.0)

    def test_community_labels_are_repo_relative(self) -> None:
        self._populate_mock_project()
        graph = AnalyticsGraph.from_database(self.db)
        comm_res = graph.detect_communities(min_community_size=2)
        labels = [info.label for info in comm_res.community_info.values()]
        self.assertTrue(labels, "expected at least one community")
        for label in labels:
            self.assertNotIn(str(self.root_path), label,
                             f"label must be repo-relative: {label}")
            self.assertNotIn("/private/", label, label)
            self.assertNotIn("/var/folders/", label, label)

    def test_architectural_profile_and_mermaid_diagrams(self) -> None:
        self._populate_mock_project()
        graph = AnalyticsGraph.from_database(self.db)
        analysis = analyze_graph(graph)

        self.assertIsNotNone(analysis.architecture_profile)
        prof = analysis.architecture_profile
        self.assertIsNotNone(prof)

        # Check Layer Breakdown
        self.assertIn(ArchitecturalLayer.PRESENTATION, prof.layer_breakdown)
        self.assertIn(ArchitecturalLayer.BUSINESS_LOGIC, prof.layer_breakdown)
        self.assertIn(ArchitecturalLayer.DATA, prof.layer_breakdown)

        # Check Mermaid Diagrams
        self.assertIn("```mermaid", prof.mermaid_layer_diagram)
        self.assertIn("graph TD", prof.mermaid_layer_diagram)
        self.assertIn("```mermaid", prof.mermaid_hld_diagram)
        self.assertIn("```mermaid", prof.mermaid_routing_tree)
        self.assertIn("```mermaid", prof.mermaid_execution_flow)
        self.assertIn("sequenceDiagram", prof.mermaid_execution_flow)

        # Check Functional Modules & Routing
        self.assertIsNotNone(prof.functional_modules)
        self.assertIsNotNone(prof.routing_architecture)
        self.assertGreaterEqual(len(prof.functional_modules), 1)

        # Check Domains Aggregated
        domain_names = [d.name for d in prof.domains]
        self.assertTrue(any("Auth" in name for name in domain_names))

        # Check Report Generation
        report = generate_markdown_report(analysis, project_name="MockCRM")
        self.assertIn("# Architectural Knowledge Graph Report: MockCRM", report)
        self.assertIn("## 1. Executive Summary & Architecture Topology", report)
        self.assertIn("## 2. High-Level Design (HLD) & System Context Diagram", report)
        self.assertIn("## 3. High-Level Architectural Layer Boundary Diagram", report)
        self.assertIn("## 4. Comprehensive Routing & Dispatch Architecture", report)
        self.assertIn("## 5. Functional Module Breakdown & Feature Taxonomy", report)
        self.assertIn("## 6. Core Lifecycle Execution & Data Flow Diagram", report)
        self.assertIn("## 7. Multi-Layer Component Breakdown & Inventory", report)
        self.assertIn("## 8. High-Level Business Domains & Subsystems", report)
        self.assertIn("## 9. Architectural Violations & Structural Warnings", report)
        self.assertIn("## 10. Critical God Nodes & Blast Radius Assessment", report)
        self.assertIn("## 11. Prioritized Architectural Refactoring Roadmap", report)
        self.assertIn("## 12. Machine-Readable Architecture Schema (JSON-LD)", report)
        self.assertIn('"@context": "https://schema.org/"', report)
        self.assertIn('"@type": "SoftwareApplicationArchitecture"', report)
    def test_cli_report_and_cluster_commands(self) -> None:
        self._populate_mock_project()
        parser = build_parser()

        # Test CLI report command
        out_report = self.root_path / "architecture_report.md"
        args_report = parser.parse_args(
            ["--root", str(self.root_path), "report", "-o", str(out_report)]
        )
        cmd_report(args_report, self.db, str(self.root_path))
        self.assertTrue(out_report.exists())
        content = out_report.read_text(encoding="utf-8")
        self.assertIn("Architectural Knowledge Graph Report", content)
        self.assertIn("```mermaid", content)

        # Test CLI cluster command
        buf = io.StringIO()
        with redirect_stdout(buf):
            args_cluster = parser.parse_args(
                ["--root", str(self.root_path), "cluster", "--min-size", "1"]
            )
            cmd_cluster(args_cluster, self.db)
        output = buf.getvalue()
        self.assertIn("Architectural Communities", output)

    def test_sql_degree_aggregation_and_graph_degrees(self) -> None:
        """Test direct SQL degree computation on AnalyticsGraph and DB."""
        self._populate_mock_project()
        deg_sql = AnalyticsGraph.compute_degrees_sql(self.db)
        self.assertIsInstance(deg_sql, dict)
        self.assertGreater(len(deg_sql), 0)
        
        graph = AnalyticsGraph.from_database(self.db)
        self.assertGreater(len(graph.nodes), 0)
        # Verify node degree matches
        for node_id in list(graph.nodes.keys())[:5]:
            self.assertGreaterEqual(graph.degree(node_id), 0)

    def test_cooperative_cancellation_analytics_graph(self) -> None:
        """Verify OperationCancelledError is raised across graph routines when cancel_check triggers."""
        from sot_graph.analytics.graph import OperationCancelledError
        self._populate_mock_project()
        graph = AnalyticsGraph.from_database(self.db)

        # Cancel Louvain / community detection
        with self.assertRaises(OperationCancelledError):
            graph.detect_communities(cancel_check=lambda: True)

        # Cancel connected components
        with self.assertRaises(OperationCancelledError):
            graph.connected_components(cancel_check=lambda: True)
        # Cancel label propagation
        with self.assertRaises(OperationCancelledError):
            graph._label_propagation_community(cancel_check=lambda: True)
        with self.assertRaises(OperationCancelledError):
            analyze_graph(graph, cancel_check=lambda: True)

    def test_cooperative_cancellation_mcp_service(self) -> None:
        """Verify McpService raises McpServiceError('cancelled') when cancel_check triggers."""
        from sot_graph.mcp_service import McpService, McpServiceError
        self._populate_mock_project()
        service = McpService(str(self.db_path), str(self.root_path))
        with self.assertRaises(McpServiceError) as ctx:
            service.get_communities(cancel_check=lambda: True)
        self.assertEqual(ctx.exception.code, "cancelled")

        with self.assertRaises(McpServiceError) as ctx:
            service.get_architecture_report(cancel_check=lambda: True)
        self.assertEqual(ctx.exception.code, "cancelled")
        with self.assertRaises(McpServiceError) as ctx:
            service.get_architecture_bundle(cancel_check=lambda: True)
        self.assertEqual(ctx.exception.code, "cancelled")

    def test_pagerank_cancellation(self) -> None:
        """Verify pagerank raises OperationCancelledError on cancel_check."""
        from sot_graph.repo_map import pagerank
        from sot_graph.analytics.graph import OperationCancelledError
        nodes = ["a", "b", "c"]
        out_edges = {"a": ["b"], "b": ["c"], "c": ["a"]}
        with self.assertRaises(OperationCancelledError):
            pagerank(nodes, out_edges, cancel_check=lambda: True)

    def test_precomputed_degrees_cache_handling(self) -> None:
        """Verify precomputed degree cache seeds from existing adjacency and updates correctly on add_node and add_edge."""
        graph = AnalyticsGraph()
        # Pre-populate some nodes and edges before initializing degree cache
        graph.add_node("A")
        graph.add_node("B")
        graph.add_edge("A", "B")

        # Enable precomputed degree cache
        graph._precomputed_degrees = {
            "A": {"in": 0, "out": 1, "total": 1},
            "B": {"in": 1, "out": 0, "total": 1},
        }

        # 1. Add edge between pre-existing nodes
        graph.add_edge("B", "A")
        self.assertEqual(graph.in_degree("A"), 1)
        self.assertEqual(graph.out_degree("A"), 1)
        self.assertEqual(graph.degree("A"), 2)
        self.assertEqual(graph.in_degree("B"), 1)
        self.assertEqual(graph.out_degree("B"), 1)
        self.assertEqual(graph.degree("B"), 2)

        # 2. Add a new node not in precomputed_degrees
        graph.add_node("C")
        self.assertIn("C", graph._precomputed_degrees)
        self.assertEqual(graph.in_degree("C"), 0)
        self.assertEqual(graph.out_degree("C"), 0)
        self.assertEqual(graph.degree("C"), 0)

        # 3. Add edge involving newly created and existing nodes
        graph.add_edge("A", "C")
        self.assertEqual(graph.out_degree("A"), 2)
        self.assertEqual(graph.in_degree("C"), 1)
        self.assertEqual(graph.degree("A"), 3)
        self.assertEqual(graph.degree("C"), 1)

        # 4. Add edge where src / dst were not in precomputed degrees (e.g. node D with existing unindexed edges)
        # Manually attach edge without cache then add edge via add_edge
        graph.nodes["D"] = {"id": "D"}
        graph._adj_out["D"].append(("A", "relates"))
        graph._adj_in["A"].append(("D", "relates"))
        # D is not in _precomputed_degrees yet, but has out-degree 1
        graph.add_edge("D", "C")
        self.assertEqual(graph.out_degree("D"), 2)
        self.assertEqual(graph.in_degree("D"), 0)
        self.assertEqual(graph.degree("D"), 2)

if __name__ == "__main__":
    unittest.main()
