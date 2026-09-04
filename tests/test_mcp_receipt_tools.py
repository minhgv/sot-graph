"""P0 A3: sot_scope_receipt / sot_diff_impact_receipt MCP tool registration.

End-to-end over an in-memory client/server pair following the
test_mcp_modern.py pattern: registration in list_tools, dispatch through
call_tool, and error-shape stability.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

REPO_PY = "def run():\n    return 42\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


class McpReceiptToolsTests(unittest.TestCase):
    """Registration + dispatch of the two receipt tools."""

    def setUp(self):
        try:
            import anyio  # noqa: F401
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest("anyio or mcp extra not installed")

        from sot_graph.db import Database
        from sot_graph.reconciler import Reconciler

        self.test_dir = tempfile.mkdtemp()
        repo = Path(self.test_dir)
        (repo / "app.py").write_text(REPO_PY, encoding="utf-8")
        _git(repo, "init", "-q")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c1")
        db_path = str(repo / ".sot" / "sot.db")
        db = Database(db_path)
        try:
            Reconciler(db, str(repo)).reconcile(workers=1)
        finally:
            db.close()

        from sot_graph.mcp_service import McpService
        self.service = McpService(db_path, str(repo))

    def tearDown(self):
        self.service.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _run(self, case):
        import anyio
        from mcp import ClientSession
        from sot_graph.mcp_server import create_server

        async def runner():
            server = create_server(self.service)
            server_read_send, server_read_recv = anyio.create_memory_object_stream(1)
            server_write_send, server_write_recv = anyio.create_memory_object_stream(1)
            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    server.run, server_read_recv, server_write_send,
                    server._sot_initialization_options,
                )
                try:
                    async with ClientSession(
                        server_write_recv, server_read_send,
                    ) as client:
                        await client.initialize()
                        await case(client)
                finally:
                    tg.cancel_scope.cancel()

        anyio.run(runner)

    def test_receipt_tools_are_registered_with_schemas(self):
        async def case(client):
            tools = await client.list_tools()
            by_name = {t.name: t for t in tools.tools}
            scope = by_name["sot_scope_receipt"]
            self.assertEqual(scope.inputSchema["required"], ["target"])
            self.assertEqual(
                scope.inputSchema["properties"]["kind_of_change"]["enum"],
                ["local-body", "rename", "delete", "public-api"],
            )
            self.assertFalse(scope.inputSchema["additionalProperties"])
            diff = by_name["sot_diff_impact_receipt"]
            self.assertFalse(diff.inputSchema["additionalProperties"])
            self.assertIn("staged", diff.inputSchema["properties"])
        self._run(case)

    def test_scope_receipt_dispatch_returns_payload(self):
        async def case(client):
            result = await client.call_tool(
                "sot_scope_receipt", {"target": "run"}
            )
            self.assertFalse(result.isError)
            structured = result.structuredContent
            self.assertTrue(structured["digest"])
            self.assertEqual(structured["proof_scope"], "pre_change_only")
            self.assertIn("status", structured["assurance"])
        self._run(case)

    def test_diff_impact_receipt_dispatch_returns_payload(self):
        async def case(client):
            result = await client.call_tool(
                "sot_diff_impact_receipt", {"target": "HEAD~1"}
            )
            self.assertFalse(result.isError)
            structured = result.structuredContent
            self.assertTrue(structured["digest"])
            self.assertIn("closure_decision", structured)
        self._run(case)

    def test_scope_receipt_error_keeps_explicit_code(self):
        async def case(client):
            result = await client.call_tool(
                "sot_scope_receipt", {"target": ""}
            )
            self.assertFalse(result.isError)  # service error maps to payload
            structured = result.structuredContent
            self.assertEqual(
                structured.get("error", {}).get("code"), "invalid_argument"
            )
        self._run(case)

    def test_diff_impact_tools_default_to_head(self):
        """CLI/MCP parity: omitting target must analyze HEAD, not HEAD~1."""
        import unittest.mock

        from sot_graph.mcp_service import McpService

        captured = {}

        def fake_diff_impact(self, **kwargs):
            captured["diff_impact"] = kwargs
            return {"ok": True, "status": "success", "target": kwargs.get("target")}

        def fake_diff_impact_receipt(self, **kwargs):
            captured["receipt"] = kwargs
            return {
                "ok": True,
                "digest": "a" * 64,
                "closure_decision": "open",
                "assurance_facts": {},
                "assurance": {"status": "PARTIAL", "reason_codes": [], "decision": {}},
            }

        async def case(client):
            r1 = await client.call_tool("sot_diff_impact", {})
            self.assertFalse(r1.isError)
            r2 = await client.call_tool("sot_diff_impact_receipt", {})
            self.assertFalse(r2.isError)

        with unittest.mock.patch.object(
            McpService, "diff_impact", fake_diff_impact
        ), unittest.mock.patch.object(
            McpService, "diff_impact_receipt", fake_diff_impact_receipt
        ):
            self._run(case)

        self.assertEqual(captured["diff_impact"]["target"], "HEAD")
        self.assertEqual(captured["receipt"]["target"], "HEAD")

    def test_diff_impact_service_default_signature_is_head(self):
        """McpService defaults match the CLI diff-impact default (HEAD)."""
        import inspect

        from sot_graph.mcp_service import McpService

        self.assertEqual(
            inspect.signature(McpService.diff_impact).parameters["target"].default,
            "HEAD",
        )
        self.assertEqual(
            inspect.signature(McpService.diff_impact_receipt).parameters["target"].default,
            "HEAD",
        )


if __name__ == "__main__":
    unittest.main()
