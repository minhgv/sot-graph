"""Phase 3: MCP 2025-06-18 — structured output, resource links, subscriptions, pagination."""
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path


def setUpModule():
    # Make the generation watcher tick fast enough for the push test.
    os.environ["SOT_MCP_WATCH_INTERVAL"] = "0.05"


def tearDownModule():
    os.environ.pop("SOT_MCP_WATCH_INTERVAL", None)


PROJECT = {
    "src/app/store.py": "def fetch(key):\n    return key\n",
    "src/app/client.py": "from app.store import fetch\n\ndef handler():\n    return fetch('k')\n",
}


class McpModernTests(unittest.TestCase):
    """End-to-end over an in-memory client/server pair."""

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
        """Drive server + client in one event loop; captures raw notifications."""
        import anyio
        from mcp import ClientSession
        from sot_graph.mcp_server import create_server

        received: list = []

        async def runner():
            server = create_server(self.service)
            server_read_send, server_read_recv = anyio.create_memory_object_stream(1)
            server_write_send, server_write_recv = anyio.create_memory_object_stream(1)

            async def record(message):
                received.append(str(message))

            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    server.run, server_read_recv, server_write_send,
                    server._sot_initialization_options,
                )
                try:
                    async with ClientSession(
                        server_write_recv, server_read_send, message_handler=record,
                    ) as client:
                        await case(client, received)
                finally:
                    tg.cancel_scope.cancel()

        anyio.run(runner)
        return received

    def test_explore_cancel_check_stops_walk(self):
        # G8: on timeout _async sets the cancel event and injects
        # cancel_check; the explore BFS loop must honor it instead of
        # issuing further query roundtrips after the client already saw
        # its timeout error.
        from sot_graph.mcp_service import McpServiceError

        with self.assertRaises(McpServiceError) as ctx:
            self.service.explore("fetch", cancel_check=lambda: True)
        self.assertEqual(ctx.exception.code, "cancelled")

    def test_tools_advertise_output_schemas(self):
        async def case(client, received):
            await client.initialize()
            tools = await client.list_tools()
            by_name = {t.name: t for t in tools.tools}
            self.assertIn("sot_search", by_name)
            self.assertIn("results", by_name["sot_search"].outputSchema.get("required", []))
            self.assertIn("ok", by_name["sot_map"].outputSchema.get("required", []))
            self.assertIn("ok", by_name["sot_pack"].outputSchema.get("required", []))
        self._run(case)

    def test_search_returns_structured_content_and_resource_links(self):
        async def case(client, received):
            await client.initialize()
            result = await client.call_tool("sot_search", {"query": "fetch"})
            self.assertFalse(result.isError)
            self.assertGreaterEqual(result.structuredContent["returned"], 1)
            links = [c for c in result.content if getattr(c, "type", "") == "resource_link"]
            self.assertGreaterEqual(len(links), 1)
            self.assertTrue(str(links[0].uri).startswith("sot://node/"))
        self._run(case)

    def test_usages_error_path_keeps_schema_shape(self):
        async def case(client, received):
            await client.initialize()
            result = await client.call_tool("sot_usages", {"target": "missing_zz"})
            self.assertIn("error", result.structuredContent)
            # Required keys stay present so outputSchema validation holds.
            self.assertEqual(result.structuredContent["callers"], [])
            self.assertEqual(result.structuredContent["risk"], [])
        self._run(case)

    def test_resources_list_is_paginated(self):
        async def case(client, received):
            await client.initialize()
            page = await client.list_resources()
            uris = {str(r.uri) for r in page.resources}
            self.assertIn("sot://stats", uris)
            self.assertIn("sot://notes", uris)
            self.assertIsNone(page.nextCursor)
        self._run(case)

    def test_subscription_pushes_update_on_generation_change(self):
        async def case(client, received):
            await client.initialize()
            await client.subscribe_resource("sot://stats")
            conn = sqlite3.connect(self.db_path)
            with conn:
                conn.execute("UPDATE file_journal SET generation = generation + 1")
            conn.close()

            import anyio
            with anyio.fail_after(5):
                while not any(
                    "notifications/resources/updated" in text and "sot://stats" in text
                    for text in received
                ):
                    await anyio.sleep(0.02)
            # Reaching here means the push notification arrived.

        received = self._run(case)
        self.assertTrue(
            any("notifications/resources/updated" in t and "sot://stats" in t for t in received),
            "resource update notification not received",
        )


if __name__ == "__main__":
    unittest.main()
