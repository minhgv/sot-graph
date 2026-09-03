import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sot_graph.db import Database
from sot_graph.mcp_service import McpService, McpServiceError, sanitize_transport_value
from sot_graph.reconciler import ReconcileSummary, Reconciler


class TestMcpService(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, ".sot", "test.db")
        db = Database(self.db_path)
        rec = Reconciler(db, self.test_dir)

        # Create sample source file
        py_file = Path(self.test_dir) / "service.py"
        py_file.write_text(
            "class PaymentService:\n"
            "    def process_order(self, order_id: str):\n"
            "        return True\n"
        )
        rec.reconcile_path(str(py_file))
        db.close()

        self.service = McpService(self.db_path, self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_mcp_service_stats(self):
        stats = self.service.stats()
        self.assertGreaterEqual(stats["paths"], 1)
        self.assertGreaterEqual(stats["nodes"], 1)

    def test_mcp_service_search(self):
        res = self.service.search(query="PaymentService", limit=5)
        self.assertIn("results", res)
        self.assertGreaterEqual(len(res["results"]), 1)
        hit = res["results"][0]
        self.assertEqual(hit["verdict"], "STRONG")
        self.assertIn("PaymentService", hit["label"])

    def test_mcp_service_explore(self):
        res = self.service.explore("PaymentService", depth=2)
        self.assertIn("node", res)
        self.assertEqual(res["node"]["symbol"], "PaymentService")
        self.assertIn("relations", res)

    def test_mcp_service_verify_drift(self):
        drift_report = self.service.verify_drift(deep=True)
        self.assertEqual(len(drift_report["drift"]), 0)
        self.assertFalse(drift_report["truncated"])

    def test_mcp_service_architecture_report(self):
        report = self.service.get_architecture_report()
        self.assertIn("report_markdown", report)
        self.assertIn("metrics", report)
        self.assertIn("communities", report)
        self.assertIn("god_nodes", report)
        self.assertIn("# Architectural Knowledge Graph Report", report["report_markdown"])

    def test_mcp_service_communities(self):
        comm_res = self.service.get_communities()
        self.assertIn("communities", comm_res)
        self.assertIn("community_count", comm_res)
        self.assertGreaterEqual(comm_res["community_count"], 1)

    def test_diff_impact_auto_reconciles_before_read(self):
        commands = [
            ["git", "init"],
            ["git", "config", "user.name", "sot-test"],
            ["git", "config", "user.email", "sot-test@example.invalid"],
            ["git", "add", "service.py"],
            ["git", "commit", "-m", "initial"],
        ]
        for command in commands:
            subprocess.run(
                command,
                cwd=self.test_dir,
                check=True,
                capture_output=True,
                text=True,
            )

        source = Path(self.test_dir) / "service.py"
        source.write_text(
            "class PaymentService:\n"
            "    def process_order(self, order_id: str):\n"
            "        return order_id\n"
        )
        stale = self.service.diff_impact(
            target="HEAD",
            working_tree=True,
            auto_reconcile=False,
            format="json",
        )
        self.assertIn("service.py", stale["stale_files"])

        refreshed = self.service.diff_impact(
            target="HEAD",
            working_tree=True,
            auto_reconcile=True,
            format="json",
        )
        self.assertEqual(refreshed["stale_files"], [])
        self.assertEqual(refreshed["reconcile"]["status"], "success")

    def test_diff_impact_reports_reconcile_failure_and_conflict_status(self):
        cases = (
            (ReconcileSummary(1, 0, 0, 0, 1, 0), "failed"),
            (ReconcileSummary(1, 0, 0, 0, 0, 0, conflicts=1), "conflicts"),
        )
        for summary, expected_status in cases:
            with self.subTest(expected_status=expected_status):
                with patch(
                    "sot_graph.reconciler.Reconciler.reconcile",
                    return_value=summary,
                ):
                    response = self.service.diff_impact(
                        target="HEAD",
                        auto_reconcile=True,
                        format="json",
                    )

                self.assertEqual(response["reconcile"]["status"], expected_status)
                self.assertTrue(response["ok"])
                self.assertEqual(response["status"], "success")
                self.assertEqual(response["reconcile"]["failed"], summary.failed)
                self.assertEqual(
                    response["reconcile"]["conflicts"], summary.conflicts
                )

    def test_diff_impact_reconcile_error_keeps_error_envelope(self):
        with patch(
            "sot_graph.reconciler.Reconciler.reconcile",
            side_effect=RuntimeError("not exposed"),
        ):
            with self.assertRaises(McpServiceError) as raised:
                self.service.diff_impact(
                    target="HEAD",
                    auto_reconcile=True,
                    format="json",
                )

        self.assertEqual(raised.exception.code, "reconcile_failed")


class TestMcpDebtR5(unittest.TestCase):
    """R5 debt closure: verify_drift cancellation + incremental _fits_response."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)
        self.db_path = os.path.join(self.test_dir, ".sot", "test.db")
        db = Database(self.db_path)
        rec = Reconciler(db, self.test_dir)
        self.files = {}
        for i in range(4):
            rel = f"mod_{i}.py"
            path = Path(self.test_dir) / rel
            path.write_text(f"value_{i} = {i}\n")
            self.files[rel] = path
            rec.reconcile_path(str(path))
        db.close()
        self.service = McpService(self.db_path, self.test_dir)
        self.addCleanup(self.service.close)

    def test_verify_drift_cancel_check_stops_per_file_loop(self):
        """cancel_check flips true after k files: the hashing loop must stop."""
        calls = {"n": 0}

        def cancel_after_two():
            calls["n"] += 1
            return calls["n"] > 2

        with self.assertRaises(McpServiceError) as ctx:
            self.service.verify_drift(deep=True, cancel_check=cancel_after_two)
        self.assertEqual(ctx.exception.code, "cancelled")
        self.assertLessEqual(calls["n"], 3, "loop must stop at the cancel point")

    def test_verify_drift_immediate_cancel_does_not_hash_any_file(self):
        calls = {"n": 0}

        def always_cancel():
            calls["n"] += 1
            return True

        with self.assertRaises(McpServiceError) as ctx:
            self.service.verify_drift(deep=True, cancel_check=always_cancel)
        self.assertEqual(ctx.exception.code, "cancelled")
        self.assertEqual(calls["n"], 1)

    def test_verify_drift_without_cancel_still_completes(self):
        report = self.service.verify_drift(deep=True)
        self.assertEqual(report["drift"], [])
        self.assertFalse(report["truncated"])

    # -- incremental _fits_response equivalence ---------------------------

    @staticmethod
    def _legacy_fits(service, value):
        """Byte-for-byte port of the pre-R5 whole-dump trimming algorithm."""
        import copy
        import json as _json

        from sot_graph.assurance.receipts import receipt_digest

        budget = service.limits.response_bytes
        value = sanitize_transport_value(value)
        encoded = _json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) <= budget:
            return value
        if not isinstance(value, dict):
            return McpServiceError("response_too_large", "legacy")
        value = copy.deepcopy(value)
        for text_key in ("markdown", "text", "raw"):
            if isinstance(value.get(text_key), str) and len(value[text_key]) > 8000:
                value[text_key] = value[text_key][:4000] + "\n\n... [truncated to fit response limit]"
                value["truncated"] = True
                if "digest" in value:
                    value["digest"] = receipt_digest({k: v for k, v in value.items() if k != "digest"})
                encoded = _json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                if len(encoded) <= budget:
                    return value
        list_keys = [
            "caller_impacts", "test_impacts", "direct_nodes", "api_impacts",
            "invalidated_evidence", "results", "drift", "relations",
            "nodes", "edges", "changed_files", "commits", "timeline",
            "impacted", "affected_tests", "affected_files", "candidate_tests",
            "callers", "callees", "transitive", "runs", "hunks", "stale_files",
            "quarantined_files", "unsupported_constructs", "parser_error_files"
        ]
        dicts_to_inspect = [value]
        if isinstance(value.get("result"), dict):
            dicts_to_inspect.append(value["result"])
        stored_items = {}
        for d in dicts_to_inspect:
            for k in list_keys:
                if isinstance(d.get(k), list) and d[k]:
                    stored_items[(id(d), k)] = (d, k, list(d[k]))
                    d[k] = []
                    value["truncated"] = True
                    if "digest" in value:
                        value["digest"] = receipt_digest({k2: v2 for k2, v2 in value.items() if k2 != "digest"})
                    enc = _json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    if len(enc) <= budget:
                        break
            if len(_json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= budget:
                break
        for (d_id, k), (d, key, items) in stored_items.items():
            for it in items:
                d[key].append(it)
                if "digest" in value:
                    value["digest"] = receipt_digest({k2: v2 for k2, v2 in value.items() if k2 != "digest"})
                if len(_json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > budget:
                    d[key].pop()
                    if "digest" in value:
                        value["digest"] = receipt_digest({k2: v2 for k2, v2 in value.items() if k2 != "digest"})
                    break
        if "results" in value and isinstance(value.get("results"), list) and "returned" in value:
            value["returned"] = len(value["results"])
        if "digest" in value:
            value["digest"] = receipt_digest({k: v for k, v in value.items() if k != "digest"})
        encoded = _json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) <= budget:
            return value
        return McpServiceError("response_too_large", "legacy")

    @staticmethod
    def _payload_shapes():
        return {
            "search_results": {
                "ok": True,
                "returned": 120,
                "results": [
                    {"id": f"n{i:04d}", "path": f"pkg/mod_{i:04d}.py",
                     "label": f"symbol_{i}", "body": "x" * 40}
                    for i in range(120)
                ],
                "providers": [{"name": "ast", "version": "1"}],
            },
            "receipt_like": {
                "schema_version": "1.2",
                "digest": "d" * 64,
                "changed_files": [f"f{i}.py" for i in range(80)],
                "caller_impacts": [{"caller": f"c{i}", "path": f"p{i}.py"} for i in range(60)],
                "test_impacts": [{"test": f"t{i}"} for i in range(60)],
                "summary": {"total": 200},
            },
            "nested_result_with_markdown": {
                "ok": True,
                "markdown": "md" * 9000,
                "result": {
                    "relations": [
                        {"direction": "outward", "target_id": f"t{i:03d}", "hop": 1}
                        for i in range(150)
                    ],
                    "relations_count": 150,
                },
                "nodes": [{"id": f"n{i}"} for i in range(30)],
            },
            "tiny_strings_lists": {
                "digest": "a" * 64,
                "results": ["" for _ in range(50)],
                "returned": 50,
                "drift": [{"path": ""}],
            },
        }

    def test_fits_response_matches_legacy_reference_on_shapes(self):
        from sot_graph.mcp_service import ServiceLimits

        for budget in (600, 900, 2048, 4096, 16384):
            service = McpService(
                self.db_path, self.test_dir,
                limits=ServiceLimits(response_bytes=budget),
            )
            try:
                for name, payload in self._payload_shapes().items():
                    with self.subTest(budget=budget, shape=name):
                        expected = self._legacy_fits(service, payload)
                        try:
                            actual = service._fits_response(payload)
                        except McpServiceError as exc:
                            actual = exc
                        if isinstance(expected, McpServiceError):
                            self.assertIsInstance(actual, McpServiceError)
                            self.assertEqual(actual.code, expected.code)
                        else:
                            self.assertEqual(actual, expected)
                            encoded = json.dumps(
                                actual, ensure_ascii=False, separators=(",", ":")
                            ).encode("utf-8")
                            self.assertLessEqual(len(encoded), budget)
            finally:
                service.close()

    def test_fits_response_small_payload_untouched(self):
        from sot_graph.mcp_service import ServiceLimits

        service = McpService(
            self.db_path, self.test_dir,
            limits=ServiceLimits(response_bytes=65536),
        )
        try:
            payload = {"ok": True, "results": [{"a": 1}], "returned": 1}
            self.assertEqual(service._fits_response(payload), payload)
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
