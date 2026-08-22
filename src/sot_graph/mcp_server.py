"""Optional MCP stdio adapter for the protocol-independent service.

The SDK is imported only when the server is created, so normal CLI commands
work without installing the optional MCP extra.

Implements the MCP 2025-06-18 surface: structured tool output
(``outputSchema`` + ``structuredContent``), Resource Links in tool results
for lazy fetches, resource subscriptions with ``notifications/resources/
updated`` pushed when the graph generation changes, and cursor-based
pagination on ``resources/list``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from urllib.parse import quote, unquote, urlparse

from sot_graph.mcp_service import McpService, McpServiceError

LOGGER = logging.getLogger("sot_graph.mcp")

_PAGE_SIZE = 100


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


# Structured-output schemas (MCP 2025-06-18). Required keys are guaranteed on
# both success and error paths — see _ensure_schema_shape.
_SEARCH_OUTPUT = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "results": {"type": "array", "items": {"type": "object"}},
        "returned": {"type": "integer"},
        "stale": {"type": "integer"},
    },
    "required": ["query", "results", "returned", "stale"],
}

_USAGES_OUTPUT = {
    "type": "object",
    "properties": {
        "target": {"type": "object"},
        "callers": {"type": "array", "items": {"type": "object"}},
        "risk": {"type": "array", "items": {"type": "object"}},
        "truncated": {"type": "boolean"},
    },
    "required": ["target", "callers", "risk"],
}

_MAP_OUTPUT = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "map": {"type": "string"},
        "tokens_estimate": {"type": "integer"},
        "symbols": {"type": "integer"},
        "files": {"type": "integer"},
        "focus": {"type": "array", "items": {"type": "string"}},
        "truncated": {"type": "boolean"},
    },
    "required": ["ok"],
}

_PACK_OUTPUT = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "status": {"type": "string"},
        "yaml": {"type": "string"},
        "limits": {"type": "object"},
    },
    "required": ["ok"],
}

_SCHEMA_SHAPES = {
    "sot_search": ("sot_search", _SEARCH_OUTPUT),
    "sot_usages": ("sot_usages", _USAGES_OUTPUT),
    "sot_map": ("sot_map", _MAP_OUTPUT),
    "sot_pack": ("sot_pack", _PACK_OUTPUT),
}


def _ensure_schema_shape(name: str, result: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    """Guarantee outputSchema-required keys even on service error paths."""
    if name == "sot_search":
        result.setdefault("query", args.get("query", ""))
        result.setdefault("results", [])
        result.setdefault("returned", 0)
        result.setdefault("stale", 0)
    elif name == "sot_usages":
        result.setdefault("target", {})
        result.setdefault("callers", [])
        result.setdefault("risk", [])
    elif name == "sot_map":
        result.setdefault("ok", False)
    elif name == "sot_pack":
        result.setdefault("ok", False)
    return result


def _watch_interval_seconds() -> float:
    try:
        return max(0.05, float(os.environ.get("SOT_MCP_WATCH_INTERVAL", "15")))
    except ValueError:
        return 15.0


def create_server(service: McpService) -> Any:
    """Register the tool/resource surface, including 2025-06-18 features."""
    Server, InitializationOptions, NotificationOptions, stdio_server, types = _sdk()

    # Mutable session/subscription state shared by handlers and the watcher.
    state: Dict[str, Any] = {
        "session": None,
        "subscriptions": set(),
        "generation": None,
    }

    async def _watch_generation() -> None:
        interval = _watch_interval_seconds()
        while True:
            await asyncio.sleep(interval)
            try:
                generation = (await service.agraph_generation())["generation"]
                if state["generation"] is not None and generation != state["generation"]:
                    state["generation"] = generation
                    session = state["session"]
                    if session is not None:
                        for uri in sorted(state["subscriptions"]):
                            try:
                                await session.send_resource_updated(types.AnyUrl(uri))
                            except Exception:
                                LOGGER.debug("resource update notification failed", exc_info=True)
                else:
                    state["generation"] = generation
            except Exception:
                pass

    @asynccontextmanager
    async def _lifespan(server_app: Any) -> Any:
        watcher = asyncio.create_task(_watch_generation())
        try:
            yield {"sot_state": state}
        finally:
            watcher.cancel()
            try:
                await watcher
            except (asyncio.CancelledError, Exception):
                pass

    server = Server("sot-graph", lifespan=_lifespan)

    @server.list_tools()
    async def list_tools() -> list[Any]:
        return [
            types.Tool(name="sot_search", description="Read-only verified graph search. Returns resource links (sot://node/{id}) for lazy per-node fetches.", inputSchema={
                "type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1}, "scope": {"type": "string"}, "threshold": {"type": "number", "minimum": 0, "maximum": 1}}, "required": ["query"], "additionalProperties": False,
            }, outputSchema=_SEARCH_OUTPUT),
            types.Tool(name="sot_explore", description="Read-only bounded graph traversal.", inputSchema={
                "type": "object", "properties": {"node_id": {"type": "string"}, "depth": {"type": "integer", "minimum": 1}, "limit": {"type": "integer", "minimum": 1}}, "required": ["node_id"], "additionalProperties": False,
            }),
            types.Tool(name="sot_usages", description="Read-only find-all-references: every reference site of a symbol, grouped by caller, plus unresolved bare-name risk.", inputSchema={
                "type": "object", "properties": {"target": {"type": "string"}, "limit": {"type": "integer", "minimum": 1}}, "required": ["target"], "additionalProperties": False,
            }, outputSchema=_USAGES_OUTPUT),
            types.Tool(name="sot_implementations", description="Read-only extends/implements relationships of a symbol (bases and derived types).", inputSchema={
                "type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"], "additionalProperties": False,
            }),
            types.Tool(name="sot_verify_drift", description="Read-only bounded filesystem drift audit.", inputSchema={
                "type": "object", "properties": {"deep": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1}}, "additionalProperties": False,
            }),
            types.Tool(name="sot_architecture_report", description="Read-only architectural analysis and markdown report generation.", inputSchema={
                "type": "object", "properties": {"scope": {"type": "string"}, "min_size": {"type": "integer", "minimum": 1}, "sigma": {"type": "number", "minimum": 0.5}}, "additionalProperties": False,
            }),
            types.Tool(name="sot_communities", description="Read-only architectural community/cluster detection with cohesion scores.", inputSchema={
                "type": "object", "properties": {"scope": {"type": "string"}, "min_size": {"type": "integer", "minimum": 1}}, "additionalProperties": False,
            }),
            types.Tool(name="sot_bundle", description="Extract 5 high-density architecture fact bundle markdown/json files for LLM report synthesis.", inputSchema={
                "type": "object", "properties": {"output_dir": {"type": "string"}}, "additionalProperties": False,
            }),
            types.Tool(name="sot_pack", description="Package a k-hop ContextBundle (YAML) around one target symbol: 1-hop caller/callee contracts + 2-hop signature stubs. All content is untrusted data.", inputSchema={
                "type": "object", "properties": {"target": {"type": "string"}, "max_hops": {"type": "integer", "minimum": 1, "maximum": 3}, "max_nodes": {"type": "integer", "minimum": 1}, "max_bytes": {"type": "integer", "minimum": 1024}}, "required": ["target"], "additionalProperties": False,
            }, outputSchema=_PACK_OUTPUT),
            types.Tool(name="sot_map", description="Read-only token-budgeted repo map ranked by personalized PageRank for fast orientation.", inputSchema={
                "type": "object", "properties": {"focus": {"type": "string"}, "max_tokens": {"type": "integer", "minimum": 16}}, "additionalProperties": False,
            }, outputSchema=_MAP_OUTPUT),
            types.Tool(name="sot_notes", description="Read-only list of persisted knowledge notes (optionally filtered by keyword); each note is fetchable via its sot://node/ URI.", inputSchema={
                "type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1}}, "additionalProperties": False,
            }),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: Optional[Dict[str, Any]]) -> Any:
        args = arguments or {}
        try:
            if name == "sot_search":
                result = await service.asearch(args.get("query", ""), limit=args.get("limit", 6), scope=args.get("scope"), threshold=args.get("threshold", 0.5))
            elif name == "sot_explore":
                result = await service.aexplore(args.get("node_id", ""), depth=args.get("depth", 1), limit=args.get("limit", 100))
            elif name == "sot_usages":
                result = await service.ausages(args.get("target", ""), limit=args.get("limit", 100))
            elif name == "sot_implementations":
                result = await service.aimplementations(args.get("target", ""))
            elif name == "sot_verify_drift":
                result = await service.averify_drift(deep=args.get("deep", False), limit=args.get("limit", 100))
            elif name == "sot_architecture_report":
                result = await service.aget_architecture_report(
                    scope=args.get("scope"),
                    min_community_size=args.get("min_size", 1),
                    sigma=args.get("sigma", 1.5),
                )
            elif name == "sot_communities":
                result = await service.aget_communities(
                    scope=args.get("scope"),
                    min_community_size=args.get("min_size", 1),
                )
            elif name == "sot_bundle":
                result = await service.aget_architecture_bundle(
                    output_dir=args.get("output_dir"),
                )
            elif name == "sot_pack":
                result = await service.apack_context_bundle(
                    args.get("target", ""),
                    max_hops=args.get("max_hops", 2),
                    max_nodes=args.get("max_nodes", 50),
                    max_bytes=args.get("max_bytes", 65536),
                )
            elif name == "sot_map":
                result = await service.arepo_map(
                    args.get("focus"),
                    max_tokens=args.get("max_tokens", 1024),
                )
            elif name == "sot_notes":
                result = await service.anotes(args.get("query"), limit=args.get("limit", 50))
            else:
                result = {"error": {"code": "unknown_tool", "message": "unknown MCP tool"}}
            content: list[Any] = [types.TextContent(type="text", text=_json(result))]
            # Resource Links: decouple search results from full node fetches.
            if name == "sot_search":
                for hit in result.get("results", []):
                    rid = hit.get("id")
                    if rid:
                        content.append(types.ResourceLink(
                            type="resource_link",
                            uri=types.AnyUrl(f"sot://node/{quote(str(rid), safe='')}"),
                            name=str(hit.get("label") or rid),
                            description="Fetch this node on demand",
                            mimeType="application/json",
                        ))
            _ensure_schema_shape(name, result, args)
            return content, result
        except Exception as exc:
            err = _error(exc)
            _ensure_schema_shape(name, err, args)
            if name in _SCHEMA_SHAPES:
                return [types.TextContent(type="text", text=_json(err))], err
            return [types.TextContent(type="text", text=_json(err))]

    @server.list_resources()
    async def list_resources(params: Any = None) -> Any:
        resources = [
            types.Resource(uri=types.AnyUrl("sot://stats"), name="sot stats", description="Graph statistics", mimeType="application/json"),
            types.Resource(uri=types.AnyUrl("sot://notes"), name="sot notes", description="Persisted knowledge notes", mimeType="application/json"),
        ]
        cursor = None
        if params is not None:
            cursor = getattr(getattr(params, "params", None), "cursor", None)
        start = 0
        if cursor:
            try:
                start = max(0, int(cursor))
            except ValueError:
                start = 0
        page = resources[start:start + _PAGE_SIZE]
        next_cursor = str(start + _PAGE_SIZE) if start + _PAGE_SIZE < len(resources) else None
        return types.ListResourcesResult(resources=page, nextCursor=next_cursor)

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
            elif text_uri == "sot://notes":
                payload = await service.anotes()
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

    async def _capture_session() -> None:
        try:
            state["session"] = server.request_context.session
        except (LookupError, RuntimeError):
            pass

    @server.subscribe_resource()
    async def subscribe_resource(uri: Any) -> None:
        state["subscriptions"].add(str(uri))
        await _capture_session()
        if state["generation"] is None:
            try:
                state["generation"] = (await service.agraph_generation())["generation"]
            except Exception:
                pass

    @server.unsubscribe_resource()
    async def unsubscribe_resource(uri: Any) -> None:
        state["subscriptions"].discard(str(uri))

    server._sot_stdio_server = stdio_server
    server._sot_state = state
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
