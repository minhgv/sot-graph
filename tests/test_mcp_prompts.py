"""R4: MCP prompts (sot_deep_dive / sot_refactor_checklist).

Drives the prompts over the same in-memory client/server transport as
test_mcp_modern.py against a seeded (reconciled) graph, asserting they
are listed and return non-empty messages containing the embedded
bundle/receipt content.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

PROJECT = {
    "src/app/store.py": "def fetch(key):\n    return key\n",
    "src/app/client.py": "from app.store import fetch\n\ndef handler():\n    return fetch('k')\n",
}


class McpPromptTests(unittest.TestCase):
    """Prompt listing + retrieval over an in-memory client/server pair."""

    def setUp(self):
        try:
            import anyio  # noqa: F401
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest("anyio or mcp extra not installed")

        from sot_graph.db import Database
        from sot_graph.reconciler import Reconciler
        self.test_dir = tempfile.mkdtemp()
        for rel, content in PROJECT.items():
            target = Path(self.test_dir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.db_path = os.path.join(self.test_dir, ".sot", "test.db")
        db = Database(self.db_path)
        Reconciler(db, self.test_dir).reconcile(workers=1)
        db.close()

        from sot_graph.mcp_service import McpService
        self.service = McpService(self.db_path, self.test_dir)

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
                    async with ClientSession(server_write_recv, server_read_send) as client:
                        await client.initialize()
                        await case(client)
                finally:
                    tg.cancel_scope.cancel()

        anyio.run(runner)

    def test_prompts_are_listed_with_arguments(self):
        async def case(client):
            result = await client.list_prompts()
            by_name = {p.name: p for p in result.prompts}
            self.assertIn("sot_deep_dive", by_name)
            self.assertIn("sot_refactor_checklist", by_name)
            self.assertEqual(by_name["sot_deep_dive"].arguments[0].name, "target")
            self.assertTrue(by_name["sot_deep_dive"].arguments[0].required)

    def test_deep_dive_embeds_context_bundle(self):
        async def case(client):
            result = await client.get_prompt("sot_deep_dive", {"target": "fetch"})
            self.assertGreaterEqual(len(result.messages), 1)
            text = result.messages[0].content.text
            self.assertIn("fetch", text)
            # The actual k-hop ContextBundle must be embedded, fenced as untrusted.
            self.assertIn("BEGIN CONTEXTBUNDLE", text)
            self.assertIn("END CONTEXTBUNDLE", text)
            self.assertIn("store.py", text)
            self.assertIn("UNTRUSTED", text)

    def test_refactor_checklist_embeds_receipt_and_checklist(self):
        async def case(client):
            result = await client.get_prompt("sot_refactor_checklist", {"target": "fetch"})
            self.assertGreaterEqual(len(result.messages), 1)
            text = result.messages[0].content.text
            self.assertIn("fetch", text)
            self.assertIn("BEGIN SCOPE RECEIPT SUMMARY", text)
            self.assertIn("END SCOPE RECEIPT SUMMARY", text)
            # Checklist derived from the receipt's risk/gap fields.
            self.assertIn("- [ ]", text)
            self.assertIn("Risk rule", text)

    def test_deep_dive_unresolved_target_explains_verdict(self):
        async def case(client):
            result = await client.get_prompt("sot_deep_dive", {"target": "definitely_missing_zz"})
            text = result.messages[0].content.text
            self.assertIn("definitely_missing_zz", text)
            self.assertIn("FAILED", text)

    def test_unknown_prompt_is_an_error(self):
        async def case(client):
            raised = False
            try:
                await client.get_prompt("sot_unknown_prompt", {})
            except Exception:
                raised = True
            self.assertTrue(raised, "unknown prompt must surface as a JSON-RPC error")


if __name__ == "__main__":
    unittest.main()
