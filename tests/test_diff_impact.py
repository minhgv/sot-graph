"""
tests.test_diff_impact - Comprehensive Unit & Integration Tests for SOT-Graph Diff Impact & Git History.
"""

import argparse
import asyncio
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sot_graph.diff_impact import (
    ApiImpact,
    ASTCoordinateMapper,
    CallerImpact,
    CommitHistoryEngine,
    CommitHistoryResult,
    CommitSummary,
    DiffHunk,
    DiffImpactEngine,
    DiffImpactResult,
    DirectNodeChange,
    GitDeltaExtractor,
    TestImpact,
    analyze_commit_history,
    analyze_diff_impact,
    format_commit_history_json,
    format_commit_history_markdown,
    format_diff_impact_json,
    format_diff_impact_markdown,
)
from sot_graph.cli import cmd_diff_impact, cmd_log
from sot_graph.mcp_service import McpService


class TestDiffImpactDataModels(unittest.TestCase):
    """Test data class serialization and property behaviors."""

    def test_diff_hunk_serialization(self):
        hunk = DiffHunk(
            file_path="src/auth.py",
            old_start=10,
            old_count=5,
            new_start=10,
            new_count=8,
            heading="def login()",
            lines_added=8,
            lines_deleted=5,
            intervals=[(10, 17)],
        )
        data = hunk.to_dict()
        self.assertEqual(data["file_path"], "src/auth.py")
        self.assertEqual(data["lines_added"], 8)
        self.assertEqual(data["intervals"], [(10, 17)])

    def test_direct_node_change_serialization(self):
        node = DirectNodeChange(
            id="node_123",
            path="src/service.py",
            kind="method",
            symbol="process_payment",
            fqn="service.process_payment",
            label="process_payment()",
            line_start=20,
            line_end=45,
            change_type="modified",
            intersected_lines=[(25, 30)],
        )
        data = node.to_dict()
        self.assertEqual(data["symbol"], "process_payment")
        self.assertEqual(data["change_type"], "modified")
        self.assertEqual(data["intersected_lines"], [(25, 30)])

    def test_caller_impact_serialization(self):
        caller = CallerImpact(
            id="node_456",
            path="src/controller.py",
            kind="class",
            symbol="CheckoutController",
            fqn="controller.CheckoutController",
            label="CheckoutController",
            line_start=10,
            depth=1,
            via_relation="calls",
            callee_id="node_123",
            callee_symbol="process_payment",
        )
        data = caller.to_dict()
        self.assertEqual(data["depth"], 1)
        self.assertEqual(data["via_relation"], "calls")
        self.assertEqual(data["callee_symbol"], "process_payment")

    def test_api_and_test_impact_serialization(self):
        api = ApiImpact(
            id="api_1",
            fe_caller_symbol="payOrder",
            http_method="POST",
            normalized_uri="/api/v1/payments",
            be_controller_symbol="PaymentController.charge",
            fe_file="web/src/api.ts",
            be_file="src/PaymentController.php",
            impact_source="direct_node",
        )
        self.assertEqual(api.to_dict()["http_method"], "POST")

        test = TestImpact(
            id="test_1",
            path="tests/test_payment.py",
            symbol="test_charge_success",
            kind="function",
            impact_reason="calls_modified_node",
            target_symbol="process_payment",
        )
        self.assertEqual(test.to_dict()["impact_reason"], "calls_modified_node")

    def test_diff_impact_result_serialization(self):
        res = DiffImpactResult(
            target="HEAD~1",
            repo_path="/workspace/repo",
            changed_files=["src/main.py"],
            hunks=[],
            direct_nodes=[],
            caller_impacts=[],
            api_impacts=[],
            test_impacts=[],
            summary={"risk_level": "LOW", "risk_score": 10},
        )
        d = res.to_dict()
        self.assertEqual(d["target"], "HEAD~1")
        self.assertEqual(d["summary"]["risk_level"], "LOW")

    def test_commit_history_result_serialization(self):
        summary = CommitSummary(
            commit_hash="a1b2c3d4e5f6",
            short_hash="a1b2c3d",
            author="Developer",
            date="2026-08-24 10:00:00 +0000",
            message="feat: new auth system",
            files_changed=["src/auth.py"],
            insertions=120,
            deletions=10,
            touched_symbols=["AuthService"],
            risk_level="HIGH",
            risk_reasons=["Touches critical security/database/schema paths (1 files)"],
        )
        res = CommitHistoryResult(
            commits=[summary],
            total_commits=1,
            risk_breakdown={"LOW": 0, "MEDIUM": 0, "HIGH": 1},
        )
        d = res.to_dict()
        self.assertEqual(d["total_commits"], 1)
        self.assertEqual(d["risk_breakdown"]["HIGH"], 1)
        self.assertEqual(d["commits"][0]["short_hash"], "a1b2c3d")


class TestGitDeltaExtractor(unittest.TestCase):
    """Test unified diff parsing with various git patch shapes."""

    def setUp(self):
        self.extractor = GitDeltaExtractor()

    def test_parse_single_hunk(self):
        diff_text = (
            "diff --git a/src/math.py b/src/math.py\n"
            "index e69de29..d95f3ad 100644\n"
            "--- a/src/math.py\n"
            "+++ b/src/math.py\n"
            "@@ -10,3 +10,5 @@ def add(a, b):\n"
            "-    return a + b\n"
            "+    result = a + b\n"
            "+    # logging\n"
            "+    return result\n"
        )
        intervals, hunks = self.extractor.parse_unified_diff(diff_text)
        self.assertIn("src/math.py", intervals)
        self.assertEqual(intervals["src/math.py"], [(10, 14)])
        self.assertEqual(len(hunks), 1)
        self.assertEqual(hunks[0].file_path, "src/math.py")
        self.assertEqual(hunks[0].old_start, 10)
        self.assertEqual(hunks[0].old_count, 3)
        self.assertEqual(hunks[0].new_start, 10)
        self.assertEqual(hunks[0].new_count, 5)
        self.assertEqual(hunks[0].heading, "def add(a, b):")

    def test_parse_multiple_hunks_and_files(self):
        diff_text = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -5,2 +5,4 @@\n"
            "+ line1\n"
            "+ line2\n"
            "@@ -20,6 +22,1 @@\n"
            "- line old\n"
            "diff --git a/src/bar.py b/src/bar.py\n"
            "--- a/src/bar.py\n"
            "+++ b/src/bar.py\n"
            "@@ -1,4 +1,2 @@\n"
        )
        intervals, hunks = self.extractor.parse_unified_diff(diff_text)
        self.assertIn("src/foo.py", intervals)
        self.assertIn("src/bar.py", intervals)
        self.assertEqual(intervals["src/foo.py"], [(5, 8), (22, 22)])
        self.assertEqual(intervals["src/bar.py"], [(1, 2)])
        self.assertEqual(len(hunks), 3)

    def test_parse_new_file(self):
        diff_text = (
            "diff --git a/src/new_mod.py b/src/new_mod.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/new_mod.py\n"
            "@@ -0,0 +1,15 @@\n"
            "+class NewClass:\n"
            "+    pass\n"
        )
        intervals, hunks = self.extractor.parse_unified_diff(diff_text)
        self.assertIn("src/new_mod.py", intervals)
        self.assertEqual(intervals["src/new_mod.py"], [(1, 15)])
        self.assertEqual(hunks[0].lines_added, 15)
        self.assertEqual(hunks[0].lines_deleted, 0)

    def test_parse_deleted_file(self):
        diff_text = (
            "diff --git a/src/legacy.py b/src/legacy.py\n"
            "deleted file mode 100644\n"
            "--- a/src/legacy.py\n"
            "+++ /dev/null\n"
            "@@ -1,20 +0,0 @@\n"
        )
        intervals, hunks = self.extractor.parse_unified_diff(diff_text)
        self.assertIn("src/legacy.py", intervals)
        self.assertEqual(intervals["src/legacy.py"], [(0, 0)])
        self.assertEqual(hunks[0].lines_added, 0)
        self.assertEqual(hunks[0].lines_deleted, 20)

    def test_parse_binary_file_and_empty(self):
        diff_text = (
            "diff --git a/assets/logo.png b/assets/logo.png\n"
            "Binary files a/assets/logo.png and b/assets/logo.png differ\n"
        )
        intervals, hunks = self.extractor.parse_unified_diff(diff_text)
        self.assertEqual(intervals, {})
        self.assertEqual(hunks, [])

        empty_intervals, empty_hunks = self.extractor.parse_unified_diff("")
        self.assertEqual(empty_intervals, {})
        self.assertEqual(empty_hunks, [])

    def test_extract_diff_with_git_repo(self):
        with tempfile.TemporaryDirectory() as temp_repo:
            # Initialize git repo
            subprocess.run(["git", "init"], cwd=temp_repo, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=temp_repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=temp_repo, check=True)

            f1 = Path(temp_repo) / "test.py"
            f1.write_text("def hello():\n    print('hi')\n")
            subprocess.run(["git", "add", "test.py"], cwd=temp_repo, check=True)
            subprocess.run(["git", "commit", "-m", "initial commit"], cwd=temp_repo, check=True)

            # Modify file
            f1.write_text("def hello():\n    # greeting\n    print('hello world')\n")

            extractor = GitDeltaExtractor(temp_repo)
            # Test working tree diff
            intervals, hunks = extractor.extract_diff(working_tree=True)
            self.assertIn("test.py", intervals)
            self.assertGreater(len(hunks), 0)

            # Test staged diff
            subprocess.run(["git", "add", "test.py"], cwd=temp_repo, check=True)
            staged_intervals, staged_hunks = extractor.extract_diff(staged=True)
            self.assertIn("test.py", staged_intervals)

            # Commit and test target HEAD
            subprocess.run(["git", "commit", "-m", "update hello"], cwd=temp_repo, check=True)
            head_intervals, head_hunks = extractor.extract_diff(target="HEAD")
            self.assertIn("test.py", head_intervals)


class TestASTCoordinateMapper(unittest.TestCase):
    """Test mapping line intervals to SQLite graph_nodes."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript("""
        CREATE TABLE graph_nodes (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            kind TEXT NOT NULL,
            symbol TEXT,
            fqn TEXT,
            label TEXT,
            line_start INTEGER,
            line_end INTEGER
        );
        """)
        self.conn.executemany(
            "INSERT INTO graph_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("n1", "src/auth/service.py", "class", "AuthService", "auth.service.AuthService", "AuthService", 1, 50),
                ("n2", "src/auth/service.py", "method", "login", "auth.service.AuthService.login", "login()", 10, 25),
                ("n3", "src/auth/service.py", "method", "logout", "auth.service.AuthService.logout", "logout()", 30, 45),
                ("n4", "src/utils/helpers.py", "function", "format_date", "utils.helpers.format_date", "format_date()", 5, 15),
            ],
        )
        self.conn.commit()
        self.mapper = ASTCoordinateMapper(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_map_intervals_to_nodes_exact_hit(self):
        file_intervals = {
            "src/auth/service.py": [(12, 18)],
        }
        nodes = self.mapper.map_intervals_to_nodes(file_intervals)
        # Should hit login (10-25) and AuthService (1-50)
        symbols = [n.symbol for n in nodes]
        self.assertIn("login", symbols)
        self.assertIn("AuthService", symbols)
        self.assertNotIn("logout", symbols)

        login_node = next(n for n in nodes if n.symbol == "login")
        self.assertEqual(login_node.intersected_lines, [(12, 18)])

    def test_map_intervals_to_nodes_no_hit(self):
        file_intervals = {
            "src/utils/helpers.py": [(100, 110)],  # Far past line 15
        }
        nodes = self.mapper.map_intervals_to_nodes(file_intervals)
        self.assertEqual(len(nodes), 0)

    def test_map_intervals_empty_or_unregistered_file(self):
        file_intervals = {
            "src/unknown.py": [(1, 10)],
            "src/auth/service.py": [],
        }
        nodes = self.mapper.map_intervals_to_nodes(file_intervals)
        self.assertEqual(len(nodes), 0)


class TestCommitHistoryEngine(unittest.TestCase):
    """Test git log parsing, symbol cross-referencing, and risk heuristic calculation."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript("""
        CREATE TABLE graph_nodes (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            kind TEXT NOT NULL,
            symbol TEXT
        );
        CREATE TABLE graph_edges (
            id TEXT PRIMARY KEY,
            src TEXT NOT NULL,
            dst TEXT NOT NULL,
            relation TEXT NOT NULL
        );
        """)
        # Seed a high-in-degree node
        self.conn.execute("INSERT INTO graph_nodes VALUES ('n_core', 'src/core.py', 'class', 'CoreEngine')")
        for i in range(6):
            self.conn.execute(f"INSERT INTO graph_nodes VALUES ('caller_{i}', 'src/caller_{i}.py', 'function', 'fn_{i}')")
            self.conn.execute(f"INSERT INTO graph_edges VALUES ('e_{i}', 'caller_{i}', 'n_core', 'calls')")
        self.conn.commit()

        self.engine = CommitHistoryEngine()

    def tearDown(self):
        self.conn.close()

    def test_parse_log_numstat(self):
        raw_log = (
            "hash1\x1fshort1\x1fAlice\x1f2026-08-24\x1frefactor: core engine\n"
            "20\t5\tsrc/core.py\n"
            "100\t10\tsrc/utils.py\n"
            "hash2\x1fshort2\x1fBob\x1f2026-08-23\x1fdocs: update readme\n"
            "2\t1\tREADME.md\n"
        )
        commits = self.engine._parse_log_numstat(raw_log, delimiter="\x1f")
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[0]["hash"], "hash1")
        self.assertEqual(commits[0]["insertions"], 120)
        self.assertEqual(commits[0]["deletions"], 15)
        self.assertEqual(commits[0]["files"], ["src/core.py", "src/utils.py"])
        self.assertEqual(commits[1]["author"], "Bob")
        self.assertEqual(commits[1]["files"], ["README.md"])

    def test_risk_scoring_critical_path_and_high_in_degree(self):
        # Touching security/auth files with high in-degree symbol
        risk, reasons = self.engine._calculate_commit_risk(
            files=["src/auth/security_manager.py", "migrations/001_init.sql"],
            insertions=300,
            deletions=20,
            message="feat: auth migration",
            touched_symbols=["CoreEngine"],
            conn=self.conn,
        )
        self.assertEqual(risk, "HIGH")
        self.assertTrue(any("security/database/schema" in r for r in reasons))
        self.assertTrue(any("incoming callers" in r for r in reasons))

    def test_risk_scoring_low_and_medium(self):
        # Low risk: 1 file, 10 lines
        risk_low, reasons_low = self.engine._calculate_commit_risk(
            files=["src/helper.py"],
            insertions=5,
            deletions=2,
            message="fix typo",
            touched_symbols=[],
        )
        self.assertEqual(risk_low, "LOW")

        # Medium risk: package.json config churn
        risk_med, reasons_med = self.engine._calculate_commit_risk(
            files=["package.json"],
            insertions=10,
            deletions=5,
            message="chore: update deps",
            touched_symbols=[],
        )
        self.assertEqual(risk_med, "MEDIUM")
        self.assertTrue(any("manifest" in r for r in reasons_med))

    def test_analyze_history_with_git_repo(self):
        with tempfile.TemporaryDirectory() as temp_repo:
            subprocess.run(["git", "init"], cwd=temp_repo, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=temp_repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=temp_repo, check=True)

            f = Path(temp_repo) / "auth.py"
            f.write_text("class AuthService:\n    pass\n")
            subprocess.run(["git", "add", "auth.py"], cwd=temp_repo, check=True)
            subprocess.run(["git", "commit", "-m", "feat: initial auth service"], cwd=temp_repo, check=True)

            engine = CommitHistoryEngine(temp_repo)
            result = engine.analyze_history(count=5, db=self.conn)
            self.assertEqual(result.total_commits, 1)
            self.assertEqual(len(result.commits), 1)
            self.assertEqual(result.commits[0].author, "Tester")


class TestDiffImpactEngine(unittest.TestCase):
    """Test reverse call-graph traversal, API bindings, test impact discovery, and summaries."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "sot.db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

        self.conn.executescript("""
        CREATE TABLE graph_nodes (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            kind TEXT NOT NULL,
            symbol TEXT,
            fqn TEXT,
            label TEXT,
            line_start INTEGER,
            line_end INTEGER
        );

        CREATE TABLE graph_edges (
            id TEXT PRIMARY KEY,
            src TEXT NOT NULL,
            dst TEXT NOT NULL,
            relation TEXT NOT NULL,
            weight REAL DEFAULT 1.0
        );

        CREATE TABLE api_cross_bindings (
            id TEXT PRIMARY KEY,
            fe_caller_symbol TEXT,
            http_method TEXT,
            normalized_uri TEXT,
            be_controller_symbol TEXT,
            fe_file TEXT,
            be_file TEXT
        );
        """)

        # 1. Target node (leaf service)
        self.conn.execute("INSERT INTO graph_nodes VALUES ('n_leaf', 'src/payment_service.py', 'method', 'charge_card', 'payment.charge_card', 'charge_card()', 10, 30)")
        
        # 2. 1-hop Caller (Controller)
        self.conn.execute("INSERT INTO graph_nodes VALUES ('n_ctrl', 'src/payment_controller.py', 'method', 'handle_checkout', 'ctrl.handle_checkout', 'handle_checkout()', 15, 40)")
        self.conn.execute("INSERT INTO graph_edges VALUES ('e_1', 'n_ctrl', 'n_leaf', 'calls', 1.0)")

        # 3. 2-hop Caller (Router / App entry)
        self.conn.execute("INSERT INTO graph_nodes VALUES ('n_route', 'src/routes.py', 'function', 'register_routes', 'routes.register_routes', 'register_routes()', 5, 50)")
        self.conn.execute("INSERT INTO graph_edges VALUES ('e_2', 'n_route', 'n_ctrl', 'calls', 1.0)")

        # 4. Impacted Test Function calling target
        self.conn.execute("INSERT INTO graph_nodes VALUES ('n_test', 'tests/test_payment.py', 'function', 'test_charge_card_success', 'tests.test_charge', 'test_charge()', 8, 20)")
        self.conn.execute("INSERT INTO graph_edges VALUES ('e_test', 'n_test', 'n_leaf', 'calls', 1.0)")

        # 5. API Binding
        self.conn.execute(
            "INSERT INTO api_cross_bindings VALUES ('api_1', 'submitPayment', 'POST', '/api/v1/charge', 'handle_checkout', 'web/payment.ts', 'src/payment_controller.py')"
        )
        self.conn.commit()

        self.engine = DiffImpactEngine(self.conn, repo_path=self.temp_dir)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_traverse_reverse_call_graph_depth_1_and_2(self):
        direct_node = DirectNodeChange(
            id="n_leaf",
            path="src/payment_service.py",
            kind="method",
            symbol="charge_card",
            fqn="payment.charge_card",
            label="charge_card()",
            line_start=10,
            line_end=30,
            change_type="modified",
            intersected_lines=[(15, 20)],
        )

        # Depth 1
        callers_d1 = self.engine._traverse_reverse_call_graph([direct_node], max_depth=1)
        caller_symbols_d1 = [c.symbol for c in callers_d1]
        self.assertIn("handle_checkout", caller_symbols_d1)
        self.assertNotIn("register_routes", caller_symbols_d1)

        # Depth 2
        callers_d2 = self.engine._traverse_reverse_call_graph([direct_node], max_depth=2)
        caller_symbols_d2 = [c.symbol for c in callers_d2]
        self.assertIn("handle_checkout", caller_symbols_d2)
        self.assertIn("register_routes", caller_symbols_d2)
        self.assertIn("test_charge_card_success", caller_symbols_d2)

        # Check Depth tags
        route_caller = next(c for c in callers_d2 if c.symbol == "register_routes")
        self.assertEqual(route_caller.depth, 2)
        self.assertEqual(route_caller.callee_symbol, "handle_checkout")

    def test_match_api_endpoints(self):
        direct_node = DirectNodeChange(
            id="n_leaf",
            path="src/payment_service.py",
            kind="method",
            symbol="charge_card",
            fqn="payment.charge_card",
            label="charge_card()",
            line_start=10,
            line_end=30,
            change_type="modified",
            intersected_lines=[(10, 20)],
        )
        caller = CallerImpact(
            id="n_ctrl",
            path="src/payment_controller.py",
            kind="method",
            symbol="handle_checkout",
            fqn="ctrl.handle_checkout",
            label="handle_checkout()",
            line_start=15,
            depth=1,
            via_relation="calls",
            callee_id="n_leaf",
            callee_symbol="charge_card",
        )

        apis = self.engine._match_api_endpoints(
            direct_nodes=[direct_node],
            caller_impacts=[caller],
            changed_files=["src/payment_controller.py"],
        )
        self.assertEqual(len(apis), 1)
        self.assertEqual(apis[0].normalized_uri, "/api/v1/charge")
        self.assertEqual(apis[0].http_method, "POST")

    def test_discover_impacted_tests(self):
        direct_node = DirectNodeChange(
            id="n_leaf",
            path="src/payment_service.py",
            kind="method",
            symbol="charge_card",
            fqn="payment.charge_card",
            label="charge_card()",
            line_start=10,
            line_end=30,
            change_type="modified",
            intersected_lines=[(10, 20)],
        )
        caller_test = CallerImpact(
            id="n_test",
            path="tests/test_payment.py",
            kind="function",
            symbol="test_charge_card_success",
            fqn="tests.test_charge",
            label="test_charge()",
            line_start=8,
            depth=1,
            via_relation="calls",
            callee_id="n_leaf",
            callee_symbol="charge_card",
        )

        tests = self.engine._discover_impacted_tests(
            direct_nodes=[direct_node],
            caller_impacts=[caller_test],
            changed_files=["tests/test_payment.py"],
        )
        self.assertGreaterEqual(len(tests), 1)
        test_paths = [t.path for t in tests]
        self.assertIn("tests/test_payment.py", test_paths)

    def test_compute_summary_risk_levels(self):
        # High risk when total_apis >= 3 or total_callers >= 10
        high_summary = self.engine._compute_summary(
            changed_files=["f1.py", "f2.py", "f3.py"],
            hunks=[MagicMock()],
            direct_nodes=[MagicMock(), MagicMock()],
            caller_impacts=[MagicMock()] * 12,
            api_impacts=[],
            test_impacts=[],
            elapsed_ms=15.0,
        )
        self.assertEqual(high_summary["risk_level"], "HIGH")

        # Low risk
        low_summary = self.engine._compute_summary(
            changed_files=["f1.py"],
            hunks=[MagicMock()],
            direct_nodes=[MagicMock()],
            caller_impacts=[],
            api_impacts=[],
            test_impacts=[],
            elapsed_ms=5.0,
        )
        self.assertEqual(low_summary["risk_level"], "LOW")

    def test_full_pipeline_with_git_repo(self):
        # Create real git commits in temp_dir
        subprocess.run(["git", "init"], cwd=self.temp_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.temp_dir, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=self.temp_dir, check=True)

        py_file = Path(self.temp_dir) / "src" / "payment_service.py"
        os.makedirs(py_file.parent, exist_ok=True)
        py_file.write_text("class PaymentService:\n    def charge_card(self):\n        pass\n")

        subprocess.run(["git", "add", "."], cwd=self.temp_dir, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.temp_dir, check=True)

        # Modify line 15 (inside charge_card 10-30 in db mock)
        py_file.write_text("class PaymentService:\n    # modified comment\n    def charge_card(self):\n        return True\n")

        res = self.engine.analyze_diff_impact(working_tree=True, depth=2)
        self.assertIn("src/payment_service.py", res.changed_files)
        self.assertEqual(res.target, "--working-tree")
        self.assertIsInstance(res.summary, dict)


class TestFormatters(unittest.TestCase):
    """Test Markdown and JSON report rendering."""

    def test_diff_impact_formatters(self):
        res = DiffImpactResult(
            target="HEAD~1",
            repo_path="/workspace/repo",
            changed_files=["src/auth.py"],
            hunks=[
                DiffHunk(
                    file_path="src/auth.py",
                    old_start=1,
                    old_count=1,
                    new_start=1,
                    new_count=2,
                    heading="def init",
                    lines_added=2,
                    lines_deleted=1,
                    intervals=[(1, 2)],
                )
            ],
            direct_nodes=[
                DirectNodeChange(
                    id="n1",
                    path="src/auth.py",
                    kind="function",
                    symbol="login",
                    fqn="auth.login",
                    label="login()",
                    line_start=1,
                    line_end=10,
                    change_type="modified",
                    intersected_lines=[(1, 2)],
                )
            ],
            caller_impacts=[
                CallerImpact(
                    id="n2",
                    path="src/app.py",
                    kind="function",
                    symbol="start_app",
                    fqn="app.start_app",
                    label="start_app()",
                    line_start=20,
                    depth=1,
                    via_relation="calls",
                    callee_id="n1",
                    callee_symbol="login",
                )
            ],
            api_impacts=[
                ApiImpact(
                    id="api1",
                    fe_caller_symbol="loginUser",
                    http_method="POST",
                    normalized_uri="/api/login",
                    be_controller_symbol="AuthController.login",
                    fe_file="web/auth.ts",
                    be_file="src/auth.py",
                    impact_source="direct_node",
                )
            ],
            test_impacts=[
                TestImpact(
                    id="t1",
                    path="tests/test_auth.py",
                    symbol="test_login",
                    kind="function",
                    impact_reason="calls_modified_node",
                    target_symbol="login",
                )
            ],
            summary={
                "total_changed_files": 1,
                "total_hunks": 1,
                "total_direct_nodes": 1,
                "total_callers": 1,
                "total_apis": 1,
                "total_tests": 1,
                "risk_score": 35,
                "risk_level": "MEDIUM",
                "execution_time_ms": 12.5,
            },
        )

        md = format_diff_impact_markdown(res)
        self.assertIn("# SOT-Graph Diff Impact Analysis Report", md)
        self.assertIn("🟡 **MEDIUM**", md)
        self.assertIn("login", md)
        self.assertIn("start_app", md)
        self.assertIn("/api/login", md)
        self.assertIn("tests/test_auth.py", md)

        js = format_diff_impact_json(res)
        parsed = json.loads(js)
        self.assertEqual(parsed["summary"]["risk_level"], "MEDIUM")
        self.assertEqual(len(parsed["changed_files"]), 1)

    def test_commit_history_formatters(self):
        summary = CommitSummary(
            commit_hash="1122334455667788",
            short_hash="1122334",
            author="Alice",
            date="2026-08-24 12:00:00",
            message="refactor: auth token validation",
            files_changed=["src/token.py"],
            insertions=50,
            deletions=10,
            touched_symbols=["TokenValidator"],
            risk_level="HIGH",
            risk_reasons=["Touches critical security/database/schema paths (1 files)"],
        )
        res = CommitHistoryResult(
            commits=[summary],
            total_commits=1,
            risk_breakdown={"LOW": 0, "MEDIUM": 0, "HIGH": 1},
        )

        md = format_commit_history_markdown(res)
        self.assertIn("# SOT-Graph Commit History & Risk Assessment", md)
        self.assertIn("🔴 **HIGH**", md)
        self.assertIn("1122334", md)
        self.assertIn("Alice", md)

        js = format_commit_history_json(res)
        parsed = json.loads(js)
        self.assertEqual(parsed["total_commits"], 1)
        self.assertEqual(parsed["risk_breakdown"]["HIGH"], 1)


class TestStandaloneFunctions(unittest.TestCase):
    """Test analyze_diff_impact and analyze_commit_history wrappers."""

    def test_analyze_diff_impact_wrapper(self):
        conn = sqlite3.connect(":memory:")
        res = analyze_diff_impact(db=conn, repo_path=".", target="HEAD", depth=1)
        self.assertIsInstance(res, DiffImpactResult)
        conn.close()

    def test_analyze_commit_history_wrapper(self):
        conn = sqlite3.connect(":memory:")
        res = analyze_commit_history(repo_path=".", count=2, db=conn)
        self.assertIsInstance(res, CommitHistoryResult)
        conn.close()


class TestCLIExecution(unittest.TestCase):
    """Test CLI commands cmd_diff_impact and cmd_log."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.conn = sqlite3.connect(":memory:")
        self.db_mock = MagicMock()
        self.db_mock.conn = self.conn

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("sot_graph.diff_impact.analyze_diff_impact")
    def test_cmd_diff_impact_markdown_and_json(self, mock_analyze):
        mock_analyze.return_value = DiffImpactResult(
            target="HEAD~1",
            repo_path=self.temp_dir,
            changed_files=[],
            hunks=[],
            direct_nodes=[],
            caller_impacts=[],
            api_impacts=[],
            test_impacts=[],
            summary={"risk_level": "LOW", "risk_score": 0},
        )

        # Markdown stdout
        args_md = argparse.Namespace(
            target="HEAD~1",
            depth=2,
            staged=False,
            working_tree=False,
            auto_reconcile=False,
            json=False,
            output=None,
        )
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = cmd_diff_impact(args_md, self.db_mock, self.temp_dir)
            self.assertEqual(code, 0)
            self.assertIn("Blast Radius", mock_out.getvalue())

        # JSON stdout
        args_json = argparse.Namespace(
            target="HEAD~1",
            depth=2,
            staged=False,
            working_tree=False,
            auto_reconcile=False,
            json=True,
            output=None,
        )
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = cmd_diff_impact(args_json, self.db_mock, self.temp_dir)
            self.assertEqual(code, 0)
            parsed = json.loads(mock_out.getvalue())
            self.assertEqual(parsed["summary"]["risk_level"], "LOW")

        # Output to file
        out_file = os.path.join(self.temp_dir, "report.md")
        args_file = argparse.Namespace(
            target="HEAD~1",
            depth=2,
            staged=False,
            working_tree=False,
            auto_reconcile=False,
            json=False,
            output=out_file,
        )
        code = cmd_diff_impact(args_file, self.db_mock, self.temp_dir)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(out_file))

    @patch("sot_graph.diff_impact.analyze_commit_history")
    def test_cmd_log_markdown_and_json(self, mock_analyze):
        mock_analyze.return_value = CommitHistoryResult(
            commits=[],
            total_commits=0,
            risk_breakdown={"LOW": 0, "MEDIUM": 0, "HIGH": 0},
        )

        # Markdown stdout
        args_md = argparse.Namespace(
            limit=5,
            author=None,
            since=None,
            no_impact=False,
            json=False,
            output=None,
        )
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = cmd_log(args_md, self.db_mock, self.temp_dir)
            self.assertEqual(code, 0)
            self.assertIn("Commit History & Risk Assessment", mock_out.getvalue())

        # JSON stdout
        args_json = argparse.Namespace(
            limit=5,
            author="Alice",
            since="1 week ago",
            no_impact=True,
            json=True,
            output=None,
        )
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = cmd_log(args_json, self.db_mock, self.temp_dir)
            self.assertEqual(code, 0)
            parsed = json.loads(mock_out.getvalue())
            self.assertEqual(parsed["total_commits"], 0)

        # Output to file
        out_file = os.path.join(self.temp_dir, "log_report.md")
        args_file = argparse.Namespace(
            limit=5,
            author=None,
            since=None,
            no_impact=False,
            json=False,
            output=out_file,
        )
        code = cmd_log(args_file, self.db_mock, self.temp_dir)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(out_file))


class TestMcpServiceDiffImpact(unittest.TestCase):
    """Test McpService integration for diff_impact and git_history."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "sot.db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript("""
        CREATE TABLE graph_nodes (id TEXT PRIMARY KEY, path TEXT, kind TEXT, symbol TEXT, fqn TEXT, label TEXT, line_start INT, line_end INT);
        CREATE TABLE graph_edges (id TEXT PRIMARY KEY, src TEXT, dst TEXT, relation TEXT, weight REAL);
        """)
        self.conn.commit()
        self.conn.close()

        self.service = McpService(self.db_path, project_root=self.temp_dir)

    def tearDown(self):
        self.service.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_mcp_diff_impact_sync_and_async(self):
        # Sync call
        res = self.service.diff_impact(target="HEAD", depth=2, format="json")
        self.assertIn("target", res)
        self.assertIn("summary", res)
        self.assertIn("providers", res)

        # Markdown format
        res_md = self.service.diff_impact(target="HEAD", depth=1, format="markdown")
        self.assertIn("markdown", res_md)
        self.assertIn("# SOT-Graph Diff Impact Analysis Report", res_md["markdown"])

        # Async call
        async def run_async():
            return await self.service.adiff_impact(target="HEAD", depth=1, format="json")

        async_res = asyncio.run(run_async())
        self.assertIn("summary", async_res)

    def test_mcp_git_history_sync_and_async(self):
        # Sync call
        res = self.service.git_history(limit=5, format="json")
        self.assertIn("total_commits", res)
        self.assertIn("risk_breakdown", res)

        # Markdown format
        res_md = self.service.git_history(limit=5, format="markdown")
        self.assertIn("markdown", res_md)
        self.assertIn("# SOT-Graph Commit History & Risk Assessment", res_md["markdown"])

        # Async call
        async def run_async():
            return await self.service.agit_history(limit=3, format="json")

        async_res = asyncio.run(run_async())
        self.assertIn("total_commits", async_res)


if __name__ == "__main__":
    unittest.main()
