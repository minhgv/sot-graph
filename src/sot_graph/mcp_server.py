"""Optional MCP stdio adapter for the protocol-independent service.

The SDK is imported only when the server is created, so normal CLI commands
work without installing the optional MCP extra.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

from sot_graph.mcp_service import McpService, McpServiceError

LOGGER = logging.getLogger("sot_graph.mcp")


class MissingMcpExtra(RuntimeError):
    """Raised when optional MCP support has not been installed."""


def _sdk() -> Any:
    try:
        from mcp.server.lowlevel import NotificationOptions, Server
        from mcp.server.models import InitializationOptions
        from mcp.server.stdio import stdio_server
        import mcp.types as types
        return Server, InitializationOptions, NotificationOptions, stdio_server, types
    except ImportError as exc:
        raise MissingMcpExtra(
            "MCP support is optional; install it with `pip install 'sot-graph[mcp]'`"
        ) from exc


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _error(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, McpServiceError):
        return {"error": exc.as_dict()}
    LOGGER.exception("MCP request failed")
    return {"error": {"code": "internal", "message": "internal MCP service error"}}


def create_server(service: McpService) -> Any:
    """Register exactly three tools and the stats/node resources."""
    Server, InitializationOptions, NotificationOptions, stdio_server, types = _sdk()
    server = Server("sot-graph")

    @server.list_tools()
    async def list_tools() -> list[Any]:
        return [
            types.Tool(name="sot_search", description="Read-only verified graph search.", inputSchema={
                "type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1}, "scope": {"type": "string"}, "threshold": {"type": "number", "minimum": 0, "maximum": 1}}, "required": ["query"], "additionalProperties": False,
            }),
            types.Tool(name="sot_explore", description="Read-only bounded graph traversal.", inputSchema={
                "type": "object", "properties": {"node_id": {"type": "string"}, "depth": {"type": "integer", "minimum": 1}, "limit": {"type": "integer", "minimum": 1}}, "required": ["node_id"], "additionalProperties": False,
            }),
            types.Tool(name="sot_verify_drift", description="Read-only bounded filesystem drift audit.", inputSchema={
                "type": "object", "properties": {"deep": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1}}, "additionalProperties": False,
            }),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: Optional[Dict[str, Any]]) -> list[Any]:
        args = arguments or {}
        try:
            if name == "sot_search":
                result = await service.asearch(args.get("query", ""), limit=args.get("limit", 6), scope=args.get("scope"), threshold=args.get("threshold", 0.5))
            elif name == "sot_explore":
                result = await service.aexplore(args.get("node_id", ""), depth=args.get("depth", 1), limit=args.get("limit", 100))
            elif name == "sot_verify_drift":
                result = await service.averify_drift(deep=args.get("deep", False), limit=args.get("limit", 100))
            else:
                result = {"error": {"code": "unknown_tool", "message": "unknown MCP tool"}}
            return [types.TextContent(type="text", text=_json(result))]
        except Exception as exc:
            return [types.TextContent(type="text", text=_json(_error(exc)))]

    @server.list_resources()
    async def list_resources() -> list[Any]:
        return [types.Resource(uri="sot://stats", name="sot stats", description="Graph statistics", mimeType="application/json")]

    @server.list_resource_templates()
    async def list_resource_templates() -> list[Any]:
        return [types.ResourceTemplate(uriTemplate="sot://node/{node_id}", name="sot node", description="Graph node", mimeType="application/json")]

    @server.read_resource()
    async def read_resource(uri: Any) -> list[Any]:
        text_uri = str(uri)
        try:
            parsed = urlparse(text_uri)
            if text_uri == "sot://stats":
                payload = await service.astats()
            elif parsed.scheme == "sot" and parsed.netloc == "node" and parsed.path.startswith("/"):
                node_id = unquote(parsed.path[1:])
                if not node_id or "/" in node_id:
                    raise McpServiceError("invalid_argument", "node resource id is invalid")
                payload = await service.anode(node_id)
            else:
                raise McpServiceError("not_found", "resource was not found")
            return [types.TextResourceContents(uri=text_uri, mimeType="application/json", text=_json(payload))]
        except Exception as exc:
            return [types.TextResourceContents(uri=text_uri, mimeType="application/json", text=_json(_error(exc)))]

    server._sot_stdio_server = stdio_server
    server._sot_initialization_options = InitializationOptions(
        server_name="sot-graph", server_version="0.1.0",
        capabilities=server.get_capabilities(notification_options=NotificationOptions(), experimental_capabilities={}),
    )
    return server


async def run_stdio(service: McpService) -> None:
    """Run MCP over stdio; diagnostics are sent to stderr by logging only."""
    _, _, _, stdio_server, _ = _sdk()
    server = create_server(service)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server._sot_initialization_options)
    finally:
        service.close()


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="sot mcp", description="Run the sot-graph MCP stdio server")
    parser.add_argument("--root", default=".")
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)
    try:
        from sot_graph.cli import default_db_path
        root = os.path.abspath(args.root)
        service = McpService(args.db or default_db_path(root), root)
        try:
            asyncio.run(run_stdio(service))
            return 0
        finally:
            service.close()
    except MissingMcpExtra as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except McpServiceError as exc:
        print(f"MCP startup failed [{exc.code}]: {exc.message}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["MissingMcpExtra", "create_server", "run_stdio", "main"]
