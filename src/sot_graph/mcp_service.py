"""Read-only, protocol-independent service for the sot-graph MCP surface.

The service deliberately does not import the MCP SDK.  It owns short-lived
read-only SQLite connections and returns plain JSON-compatible values so it is
usable from other protocols and straightforward to test.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, cast
from urllib.parse import quote
from sot_graph.db import Database
from sot_graph.verifier import TrustVerifier, tokenize


class McpServiceError(Exception):
    """Stable public error with a machine-readable code."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def as_dict(self) -> Dict[str, str]:
        return {"code": self.code, "message": self.message}

def resolve_and_validate_output_path(
    project_root: str,
    user_path: Optional[str],
    default_relative: Optional[str] = None,
) -> str:
    """Confine output paths to project_root to prevent path traversal vulnerabilities."""
    target = user_path or default_relative
    if not target:
        raise McpServiceError("invalid_path", "No output path specified")
    resolved_root = os.path.realpath(os.path.abspath(project_root))
    if not os.path.isabs(target):
        resolved_target = os.path.realpath(os.path.abspath(os.path.join(resolved_root, target)))
    else:
        resolved_target = os.path.realpath(os.path.abspath(target))
    try:
        common = os.path.commonpath([resolved_root, resolved_target])
    except ValueError as exc:
        raise McpServiceError("path_traversal", f"Output path outside project root: {target}") from exc
    if common != resolved_root:
        raise McpServiceError("path_traversal", f"Output path outside project root: {target}")
    return resolved_target


@dataclass(frozen=True)
class ServiceLimits:
    search: int = 50
    explore_depth: int = 4
    explore_nodes: int = 500
    drift: int = 1_000
    response_bytes: int = 256 * 1024
    body_bytes: int = 8 * 1024


class _ConnView:
    """Minimal Database-compatible view over a read-only connection.

    Database query methods only touch ``self.conn``, so the unbound methods
    can serve MCP reads without opening a writer connection.
    """

    __slots__ = ("conn",)

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn


class McpService:
    """Bounded read-only graph operations rooted at one project directory."""

    def __init__(
        self,
        db_path: str,
        project_root: str,
        *,
        limits: Optional[ServiceLimits] = None,
        timeout_ms: int = 2_000,
    ) -> None:
        self.db_path = os.path.abspath(os.fspath(db_path))
        self.project_root = os.path.realpath(os.path.abspath(os.fspath(project_root)))
        self.limits = limits or ServiceLimits()
        self.timeout_ms = max(1, int(timeout_ms))
        if not os.path.isdir(self.project_root):
            raise McpServiceError("invalid_root", "project root must be an existing directory")
        if not os.path.isfile(self.db_path):
            raise McpServiceError("database_unavailable", "SQLite database does not exist")
        self._closed = False

    def close(self) -> None:
        """Mark the service closed; per-operation connections are already closed."""
        self._closed = True

    def _connection(self) -> sqlite3.Connection:
        if self._closed:
            raise McpServiceError("closed", "MCP service is closed")
        # URI mode=ro guarantees that this surface cannot create schema, WAL,
        # journal, or other files even when the caller supplies a new database.
        uri = "file:" + quote(self.db_path, safe="/") + "?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=self.timeout_ms / 1000.0)
            conn.row_factory = sqlite3.Row
            deadline = time.monotonic() + self.timeout_ms / 1000.0
            conn.set_progress_handler(lambda: 1 if time.monotonic() >= deadline else 0, 1_000)
            return conn
        except (sqlite3.Error, OSError) as exc:
            raise McpServiceError("database_unavailable", "unable to open read-only graph database") from exc

    def _run(self, operation: Any) -> Any:
        conn = self._connection()
        try:
            return operation(conn)
        except McpServiceError:
            raise
        except sqlite3.OperationalError as exc:
            if "interrupt" in str(exc).lower() or "locked" in str(exc).lower():
                raise McpServiceError("timeout", "graph operation timed out") from exc
            raise McpServiceError("query_failed", "graph query failed") from exc
        except sqlite3.Error as exc:
            raise McpServiceError("query_failed", "graph query failed") from exc
        finally:
            conn.close()

    def _bounded(self, value: Any, maximum: int, default: int = 1) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise McpServiceError("invalid_argument", "numeric argument is invalid") from exc
        if number < 1:
            raise McpServiceError("invalid_argument", "numeric argument must be positive")
        return min(number, maximum)

    def _relative_path(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        try:
            real = os.path.realpath(os.path.abspath(value if os.path.isabs(value) else os.path.join(self.project_root, value)))
            if os.path.commonpath([self.project_root, real]) != self.project_root:
                return None
            return os.path.relpath(real, self.project_root).replace(os.sep, "/")
        except (OSError, ValueError):
            return None

    def _body(self, value: Any) -> str:
        text = str(value or "")
        raw = text.encode("utf-8")
        if len(raw) <= self.limits.body_bytes:
            return text
        return raw[: self.limits.body_bytes].decode("utf-8", errors="ignore")

    def _fits_response(self, value: Any) -> Any:
        # Keep the API JSON-ready while enforcing a hard response ceiling.  A
        # deterministic truncation is preferable to returning an oversized body.
        import json
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) <= self.limits.response_bytes:
            return value
        if isinstance(value, dict):
            for key in ("results", "drift", "relations"):
                if not isinstance(value.get(key), list):
                    continue
                value = dict(value)
                items = list(value[key])
                value[key] = []
                value["truncated"] = True
                for item in items:
                    trial = dict(value)
                    trial[key] = value[key] + [item]
                    if len(json.dumps(trial, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > self.limits.response_bytes:
                        break
                    value[key].append(item)
                if key == "results":
                    value["returned"] = len(value[key])
                return value

        raise McpServiceError("response_too_large", "response exceeds configured size limit")
    def search(self, query: str, *, limit: int = 6, scope: Optional[str] = None, threshold: float = 0.5) -> Dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise McpServiceError("invalid_argument", "query must not be empty")
        if len(query) > 1000:
            raise McpServiceError("invalid_argument", "query exceeds 1000 characters")
        if scope is not None and (not isinstance(scope, str) or len(scope) > 4096):
            raise McpServiceError("invalid_argument", "scope exceeds 4096 characters")
        limit = self._bounded(limit, self.limits.search)
        try:
            threshold = float(threshold)
        except (TypeError, ValueError) as exc:
            raise McpServiceError("invalid_argument", "threshold must be between 0 and 1") from exc
        if not 0 <= threshold <= 1:
            raise McpServiceError("invalid_argument", "threshold must be between 0 and 1")
        raw_tokens = [t.strip("\"'") for t in query.split() if t.strip("\"'")]
        tokens: Set[str] = set()
        tokens_l: List[str] = []
        for raw in raw_tokens:
            cleaned = re.sub(r'[\*\^\"(){}:]', '', raw)
            if not cleaned:
                continue
            if len(cleaned) >= 2:
                tokens.add(f'"{cleaned}"*')
            for part in re.split(r'[_\.\-:\$@\s]+', cleaned):
                if len(part) >= 2:
                    tokens.add(f'"{part}"*')
                    tokens_l.append(part.lower())
                part_strip = part.strip('_')
                if len(part_strip) >= 2:
                    tokens.add(f'"{part_strip}"*')
                    tokens_l.append(part_strip.lower())
        if not tokens:
            return {"query": query, "results": [], "returned": 0, "stale": 0}
        expr = " OR ".join(sorted(tokens))

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            sql = """SELECT k.id,k.path,k.kind,k.symbol,k.label,k.body,k.keywords,k.line_start,
                      bm25(graph_fts) AS rank_score
                      FROM graph_fts f JOIN graph_nodes k ON f.rowid=k.rowid
                      WHERE graph_fts MATCH ?"""
            params: List[Any] = [expr]
            if scope:
                sql += " AND (k.path LIKE ? OR k.body LIKE ?)"
                params.extend([f"%{scope}%", f"%{scope}%"])
            sql += " ORDER BY rank_score ASC LIMIT ?"
            params.append(limit * 3)
            rows = conn.execute(sql, params).fetchall()
            def _bucket(row: Any):
                # bm25 is negative-better; keep the raw value for ordering.
                try:
                    score = float(row["rank_score"])
                except (TypeError, ValueError):
                    score = 0.0
                text = f"{row['symbol'] or ''} {row['label'] or ''}".lower()
                if row["kind"] != "file" and any(t in text for t in tokens_l):
                    return (0, score)
                return (1, score)

            buckets = [_bucket(row) for row in rows]
            out: List[Dict[str, Any]] = []
            for row, bucket in zip(rows, buckets):
                candidate = dict(row)
                res = TrustVerifier.verify_hit(
                    cast(Database, _ConnView(conn)), candidate, tokenize(query), self.project_root,
                    threshold=threshold, auto_heal=False,
                )
                verdict, coverage, real = res
                evidence = res.evidence
                rel = self._relative_path(real or candidate.get("path"))
                if candidate.get("path") and rel is None:
                    verdict = "STALE"
                out.append({
                    "_bucket": bucket,
                    "id": candidate["id"], "verdict": verdict,
                    "coverage": coverage, "path": rel,
                    "kind": candidate["kind"], "symbol": candidate.get("symbol"),
                    "label": candidate["label"], "line": candidate.get("line_start"),
                    "body": self._body(candidate.get("body")),
                    "rank_score": round(float(candidate.get("rank_score") or 0), 6),
                    "evidence": evidence.to_dict(),
                })
            rank = {"STRONG": 0, "REBUILT": 0, "WEAK": 1, "NOPATH": 2, "STALE": 3}
            out.sort(key=lambda item: (
                rank.get(item["verdict"], 9), -(item["coverage"] or 0),
                item["_bucket"], item["id"]))
            for item in out:
                item.pop("_bucket", None)
            stale = sum(item["verdict"] == "STALE" for item in out)
            return self._fits_response({"query": query, "results": out[:limit], "returned": min(len(out), limit), "stale": stale})
        return self._run(op)
    def explore(self, node_id: str, *, depth: int = 1, limit: int = 100) -> Dict[str, Any]:
        if not isinstance(node_id, str) or not node_id.strip():
            raise McpServiceError("invalid_argument", "node_id must not be empty")
        if len(node_id) > 512:
            raise McpServiceError("invalid_argument", "node_id exceeds 512 characters")
        depth = self._bounded(depth, self.limits.explore_depth)
        limit = self._bounded(limit, self.limits.explore_nodes)
        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            row = conn.execute("SELECT id,path,kind,symbol,label,body,keywords,line_start FROM graph_nodes WHERE id = ?", (node_id,)).fetchone()
            if row is None:
                row = conn.execute("SELECT id,path,kind,symbol,label,body,keywords,line_start FROM graph_nodes WHERE symbol = ? OR label LIKE ? ORDER BY id LIMIT 1", (node_id, f"%{node_id}%")).fetchone()
            if row is None:
                raise McpServiceError("not_found", "node was not found")
            node = self._node_dict(row)
            relations: List[Dict[str, Any]] = []
            visited = {row["id"]}
            # queue: (node_id, current_depth, via_id, via_label, via_path)
            queue: List[Tuple[str, int, Optional[str], Optional[str], Optional[str]]] = [(row["id"], 0, None, None, None)]
            sql = (
                "SELECT 'outward' AS dir, e.relation, n.id, n.label, n.path, n.line_start, n.kind "
                "FROM graph_edges e JOIN graph_nodes n ON e.dst=n.id WHERE e.src=? AND e.relation != 'defines' "
                "UNION ALL "
                "SELECT 'inward' AS dir, e.relation, n.id, n.label, n.path, n.line_start, n.kind "
                "FROM graph_edges e JOIN graph_nodes n ON e.src=n.id WHERE e.dst=? AND e.relation != 'defines' "
                "ORDER BY dir DESC, n.id"
            )
            while queue and len(relations) < limit:
                current, current_depth, via_id, via_label, via_path = queue.pop(0)
                if current_depth >= depth:
                    continue
                for direction, rel, target, label, path, line, kind in conn.execute(sql, (current, current)).fetchall():
                    if target == row["id"]:
                        continue
                    if len(relations) >= limit:
                        break
                    hop_num = current_depth + 1
                    item = {
                        "direction": direction,
                        "relation": rel if direction == "outward" else f"used_by ({rel})",
                        "target_id": target,
                        "label": label,
                        "path": self._relative_path(path),
                        "line": line,
                        "kind": kind,
                        "depth": hop_num,
                        "hop": hop_num,
                        "via_id": via_id if hop_num > 1 else None,
                        "via_label": via_label if hop_num > 1 else None,
                        "via_path": self._relative_path(via_path) if (hop_num > 1 and via_path) else None,
                    }
                    relations.append(item)
                    if target not in visited and hop_num < depth:
                        visited.add(target)
                        queue.append((target, hop_num, target, label, path))
            hop1_count = sum(1 for r in relations if r.get("hop") == 1)
            hop2_count = sum(1 for r in relations if r.get("hop", 0) > 1)
            return self._fits_response({
                "node": node,
                "relations": relations,
                "hop_summary": {"1_hop_direct": hop1_count, "transitive_hops": hop2_count},
                "truncated": len(relations) >= limit,
            })
        return self._run(op)

    def _resolve_target_row(self, conn: sqlite3.Connection, target: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT id,path,kind,symbol,label,body,keywords,line_start FROM graph_nodes WHERE id = ?",
            (target,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id,path,kind,symbol,label,body,keywords,line_start FROM graph_nodes WHERE symbol = ? LIMIT 1",
                (target,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id,path,kind,symbol,label,body,keywords,line_start FROM graph_nodes "
                "WHERE kind != 'file' AND (label LIKE ? OR fqn LIKE ?) ORDER BY kind LIMIT 1",
                (f"%{target}%", f"%{target}%")).fetchone()
        if row is None:
            raise McpServiceError("not_found", "symbol was not found")
        return row

    def usages(self, target: str, *, limit: int = 100) -> Dict[str, Any]:
        """Reference sites of a symbol grouped by caller (find-all-references)."""
        if not isinstance(target, str) or not target.strip():
            raise McpServiceError("invalid_argument", "target must not be empty")
        if len(target) > 512:
            raise McpServiceError("invalid_argument", "target exceeds 512 characters")
        limit = self._bounded(limit, self.limits.explore_nodes)

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            row = self._resolve_target_row(conn, target)
            view = cast(Database, _ConnView(conn))
            data = Database.usages(view, row["id"], row["symbol"])
            callers = [{
                "caller_id": caller["caller_id"],
                "label": caller["label"],
                "kind": caller["kind"],
                "path": self._relative_path(caller["path"]),
                "sites": caller["sites"],
            } for caller in data["callers"][:limit]]
            risk = [{
                "label": item["label"], "path": self._relative_path(item["path"]),
                "dst_symbol": item["dst_symbol"], "relation": item["relation"],
                "line": item["line"], "state": item["state"],
            } for item in data["risk"][:limit]]
            return self._fits_response({
                "target": self._node_dict(row),
                "status": data.get("status", "COMPLETE"),
                "completeness": data.get("completeness", "COMPLETE"),
                "resolved_count": data.get("resolved_count", sum(len(c["sites"]) for c in callers)),
                "unresolved_count": data.get("unresolved_count", len(risk)),
                "callers": callers,
                "risk": risk,
                "next_steps": data.get("next_steps", []),
                "truncated": len(data["callers"]) > limit or len(data["risk"]) > limit,
            })
        return self._run(op)

    def implementations(self, target: str) -> Dict[str, Any]:
        """extends/implements edges of a symbol, both directions."""
        if not isinstance(target, str) or not target.strip():
            raise McpServiceError("invalid_argument", "target must not be empty")
        if len(target) > 512:
            raise McpServiceError("invalid_argument", "target exceeds 512 characters")

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            row = self._resolve_target_row(conn, target)
            view = cast(Database, _ConnView(conn))
            data = Database.inheritance_edges(view, row["id"], row["symbol"])

            def _rel(entry: Mapping[str, Any]) -> Dict[str, Any]:
                return {"label": entry["label"], "path": self._relative_path(entry["path"]),
                        "kind": entry["kind"], "relation": entry["relation"], "line": entry["line"]}

            def _pen(entry: Mapping[str, Any]) -> Dict[str, Any]:
                return {"label": entry["label"], "path": self._relative_path(entry["path"]),
                        "dst_symbol": entry["dst_symbol"], "state": entry["state"]}

            return self._fits_response({
                "target": self._node_dict(row),
                "bases": [_rel(e) for e in data["bases"]],
                "derived": [_rel(e) for e in data["derived"]],
                "pending_bases": [_pen(e) for e in data["pending_bases"]],
                "pending_derived": [_pen(e) for e in data["pending_derived"]],
            })
        return self._run(op)

    def repo_map(self, focus: Optional[str] = None, *, max_tokens: int = 1024) -> Dict[str, Any]:
        """Token-budgeted repo map ranked by personalized PageRank."""
        from sot_graph.repo_map import build_repo_map

        if focus is not None and not isinstance(focus, str):
            raise McpServiceError("invalid_argument", "focus must be a string")
        if focus is not None and len(focus) > 2048:
            raise McpServiceError("invalid_argument", "focus exceeds 2048 characters")
        max_tokens = self._bounded(max_tokens, 8192)

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            focus_list = [f for f in (focus or "").split(",") if f.strip()]
            result = build_repo_map(conn, focus=focus_list, max_tokens=max_tokens,
                                    root=self.project_root)
            return self._fits_response({
                "ok": True,
                "map": result["rendered"],
                "tokens_estimate": result["tokens_estimate"],
                "symbols": result["symbols"],
                "files": len(result["files"]),
                "focus": result["focus"],
                "truncated": result["truncated"],
            })
        return self._run(op)

    def notes(self, query: Optional[str] = None, *, limit: int = 50) -> Dict[str, Any]:
        """List persisted knowledge notes (optionally filtered by keyword)."""
        if query is not None and not isinstance(query, str):
            raise McpServiceError("invalid_argument", "query must be a string")
        if query is not None and len(query) > 512:
            raise McpServiceError("invalid_argument", "query exceeds 512 characters")
        limit = self._bounded(limit, self.limits.search)

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            sql = ("SELECT id, label, keywords, updated_at FROM graph_nodes "
                   "WHERE kind = 'note'")
            params: List[Any] = []
            if query:
                sql += " AND (label LIKE ? OR keywords LIKE ? OR body LIKE ?)"
                like = f"%{query}%"
                params.extend([like, like, like])
            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            out = [{
                "id": row["id"],
                "uri": f"sot://node/{row['id']}",
                "title": row["label"],
                "keywords": (row["keywords"] or "").split(),
                "updated_at": row["updated_at"],
            } for row in conn.execute(sql, params).fetchall()]
            return self._fits_response({"notes": out, "returned": len(out)})
        return self._run(op)

    def graph_generation(self) -> Dict[str, Any]:
        """Current publication generation — the staleness signal for MCP push."""
        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            row = conn.execute(
                "SELECT COALESCE(MAX(generation), 0), COUNT(*) FROM file_journal"
            ).fetchone()
            return {"generation": row[0], "paths": row[1]}
        return self._run(op)

    def _node_dict(self, row: Mapping[str, Any]) -> Dict[str, Any]:
        return {"id": row["id"], "path": self._relative_path(row["path"]), "kind": row["kind"], "symbol": row["symbol"], "label": row["label"], "body": self._body(row["body"]), "keywords": row["keywords"], "line": row["line_start"]}

    def node(self, node_id: str) -> Dict[str, Any]:
        if not isinstance(node_id, str) or not node_id.strip():
            raise McpServiceError("invalid_argument", "node_id must not be empty")
        if len(node_id) > 512:
            raise McpServiceError("invalid_argument", "node_id exceeds 512 characters")
        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            row = conn.execute("SELECT id,path,kind,symbol,label,body,keywords,line_start FROM graph_nodes WHERE id=?", (node_id,)).fetchone()
            if row is None:
                raise McpServiceError("not_found", "node was not found")
            return self._fits_response(self._node_dict(row))
        return self._run(op)

    def verify_drift(self, *, deep: bool = False, limit: int = 100) -> Dict[str, Any]:
        limit = self._bounded(limit, self.limits.drift)
        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            rows = conn.execute("SELECT path,sha256,size,mtime_ms FROM file_journal ORDER BY path LIMIT ?", (limit + 1,)).fetchall()
            drift: List[Dict[str, Any]] = []
            for row in rows:
                rel = self._relative_path(row["path"])
                if rel is None:
                    drift.append({"path": None, "why": "outside_root"})
                    continue
                path = os.path.join(self.project_root, rel)
                if not os.path.isfile(path):
                    drift.append({"path": rel, "why": "missing"})
                    continue
                st = os.stat(path)
                if deep:
                    try:
                        with open(path, "rb") as handle:
                            current = hashlib.sha256(handle.read()).hexdigest()
                    except OSError:
                        drift.append({"path": rel, "why": "unreadable"})
                    else:
                        if current != row["sha256"]:
                            drift.append({"path": rel, "why": "hash_mismatch"})
                elif st.st_size != row["size"] or int(st.st_mtime * 1000) != row["mtime_ms"]:
                    drift.append({"path": rel, "why": "mtime_size_mismatch"})
                if len(drift) >= limit:
                    break
            return self._fits_response({"deep": bool(deep), "drift": drift, "truncated": len(rows) > limit})
        return self._run(op)

    def stats(self) -> Dict[str, Any]:
        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            counts = {"paths": "file_journal", "nodes": "graph_nodes", "edges": "graph_edges", "pending": "pending_edges"}
            return {key: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for key, table in counts.items()}
        return self._run(op)

    def get_architecture_report(
        self,
        *,
        scope: Optional[str] = None,
        min_community_size: int = 1,
        sigma: float = 1.5,
        format: str = "markdown",
    ) -> Dict[str, Any]:
        from sot_graph.analytics.graph import AnalyticsGraph
        from sot_graph.analytics.diagnostics import analyze_graph
        from sot_graph.analytics.report import generate_markdown_report

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            graph = AnalyticsGraph.from_connection(conn, scope=scope)
            analysis = analyze_graph(
                graph,
                min_community_size=min_community_size,
                threshold_sigma=sigma,
            )
            report_md = generate_markdown_report(
                analysis,
                project_name=os.path.basename(self.project_root),
            )
            comms_summary = [
                {
                    "id": cid,
                    "label": c.label,
                    "cohesion_score": c.cohesion_score,
                    "node_count": len(c.nodes),
                    "sample_nodes": c.nodes[:5],
                }
                for cid, c in sorted(
                    analysis.community_result.community_info.items(),
                    key=lambda x: len(x[1].nodes),
                    reverse=True,
                )
            ]
            gods_summary = [
                {
                    "node_id": g.node_id,
                    "label": g.label,
                    "path": g.path,
                    "kind": g.kind,
                    "total_degree": g.total_degree,
                    "blast_radius": g.blast_radius,
                    "risk_level": g.risk_level,
                }
                for g in analysis.god_nodes
            ]
            surprises = [
                {
                    "source_id": s.source_id,
                    "target_id": s.target_id,
                    "relation": s.relation,
                    "source_community": s.source_community,
                    "target_community": s.target_community,
                    "explanation": s.explanation,
                }
                for s in analysis.surprising_connections
            ]
            return self._fits_response({
                "report_markdown": report_md,
                "metrics": {
                    "node_count": analysis.metrics.node_count,
                    "edge_count": analysis.metrics.edge_count,
                    "community_count": analysis.metrics.community_count,
                    "density": analysis.metrics.density,
                    "modularity": analysis.metrics.modularity,
                },
                "communities": comms_summary,
                "god_nodes": gods_summary,
                "surprising_connections": surprises,
            })
        return self._run(op)

    def get_communities(
        self,
        *,
        scope: Optional[str] = None,
        min_community_size: int = 1,
    ) -> Dict[str, Any]:
        from sot_graph.analytics.graph import AnalyticsGraph

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            graph = AnalyticsGraph.from_connection(conn, scope=scope)
            res = graph.detect_communities(min_community_size=min_community_size)
            comm_list = []
            for cid, cinfo in res.community_info.items():
                comm_list.append({
                    "community_id": cid,
                    "label": cinfo.label,
                    "cohesion_score": cinfo.cohesion_score,
                    "node_count": len(cinfo.nodes),
                    "nodes": cinfo.nodes,
                })
            return self._fits_response({
                "modularity": res.modularity,
                "community_count": len(comm_list),
                "communities": comm_list,
            })
        return self._run(op)
    def get_architecture_bundle(
        self,
        *,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract the 5 fact bundle markdown/json files for LLM architecture reports."""
        from sot_graph.analytics.bundle import ArchitectureBundler
        from sot_graph.analytics.graph import AnalyticsGraph

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            graph = AnalyticsGraph.from_connection(conn)
            bundler = ArchitectureBundler(root_dir=self.project_root, graph=graph)
            out_dir = resolve_and_validate_output_path(
                self.project_root,
                output_dir,
                os.path.join(".sot", "bundle"),
            )
            bundle = bundler.extract_bundle(out_dir)
            return self._fits_response({
                "ok": True,
                "status": "success",
                "output_dir": os.path.abspath(out_dir),
                "files": {fname: len(content) for fname, content in bundle.items()},
                "metrics": {
                    "total_nodes": len(bundler.graph.nodes),
                    "total_edges": len(bundler.graph.edges),
                    "modularity": bundler.analysis.metrics.modularity,
                },
            })
        return self._run(op)

    def pack_context_bundle(
        self,
        target: str,
        *,
        max_hops: int = 2,
        max_nodes: int = 50,
        max_bytes: int = 65_536,
    ) -> Dict[str, Any]:
        """Build a k-hop ContextBundle (read-only) for agent prompt registers."""
        from sot_graph.pack import PackError, build_bundle, render_yaml

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            try:
                bundle = build_bundle(
                    _ConnView(conn), self.project_root, target,
                    max_hops=max_hops, max_nodes=max_nodes, max_bytes=max_bytes,
                )
            except PackError as exc:
                return {
                    "ok": False,
                    "status": "error",
                    "code": exc.code,
                    "error": str(exc),
                    "candidates": exc.candidates,
                }
            return self._fits_response({
                "ok": True,
                "status": "success",
                "yaml": render_yaml(bundle),
                "limits": bundle["limits"],
            })
        return self._run(op)

    def trace(
        self,
        target: str,
        *,
        depth: int = 2,
    ) -> Dict[str, Any]:
        """Extract Full-Stack execution path, UI decisions, API bindings, and Mermaid diagrams."""
        from sot_graph.trace import trace_fullstack

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            view = _ConnView(conn)
            res = trace_fullstack(cast(Database, view), target, depth=depth)
            return self._fits_response({
                "ok": True,
                "status": "success",
                "target": target,
                "depth": depth,
                **res,
            })
        return self._run(op)

    def ui_tree(
        self,
        component: str,
    ) -> Dict[str, Any]:
        """Extract local Frontend UI decision tree, validation rules, and modals."""
        from sot_graph.trace import extract_ui_tree

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            view = _ConnView(conn)
            res = extract_ui_tree(cast(Database, view), component)
            return self._fits_response({
                "ok": True,
                "status": "success",
                "component": component,
                **res,
            })
        return self._run(op)

    def backend_flow(
        self,
        service: str,
    ) -> Dict[str, Any]:
        """Extract Backend processing steps, multi-datasources, and exception branches."""
        from sot_graph.trace import extract_backend_flow

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            view = _ConnView(conn)
            res = extract_backend_flow(cast(Database, view), service)
            return self._fits_response({
                "ok": True,
                "status": "success",
                "service": service,
                **res,
            })
        return self._run(op)

    def solution_inventory(
        self,
        module: str = "",
        *,
        output_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate Stage 1 Feature Inventory by Role & Related Features for TLGP."""
        from sot_graph.solution import generate_feature_inventory

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            view = _ConnView(conn)
            out_file = None
            if output_file:
                out_file = resolve_and_validate_output_path(self.project_root, output_file)
            res = generate_feature_inventory(cast(Database, view), module, out_file=out_file)
            return self._fits_response({
                "ok": True,
                "status": "success",
                "module": module or "all",
                **res,
            })
        return self._run(op)

    def solution_steps(
        self,
        method: str,
    ) -> Dict[str, Any]:
        """Extract Stage 2 Micro-step decomposition (4-column table) for manpower estimation."""
        from sot_graph.solution import extract_execution_steps

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            view = _ConnView(conn)
            res = extract_execution_steps(cast(Database, view), method)
            return self._fits_response({
                "ok": True,
                "status": "success",
                "method": method,
                **res,
            })
        return self._run(op)

    def solution_bundle(
        self,
        module: str = "",
        *,
        output_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate Stage 2 Full Solution Context Bundle for Solution.md and downstream agents."""
        from sot_graph.solution import generate_solution_bundle

        def op(conn: sqlite3.Connection) -> Dict[str, Any]:
            view = _ConnView(conn)
            out_file = resolve_and_validate_output_path(
                self.project_root,
                output_file,
                os.path.join(".sot", "bundle", "ContextBundle.md"),
            )
            res = generate_solution_bundle(cast(Database, view), module, out_file=out_file)
            return self._fits_response({
                "ok": True,
                "status": "success",
                "module": module or "all",
                **res,
            })
        return self._run(op)

    async def _async(self, method: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.wait_for(asyncio.to_thread(method, *args, **kwargs), self.timeout_ms / 1000.0)
        except asyncio.TimeoutError as exc:
            raise McpServiceError("timeout", "graph operation timed out") from exc

    async def asearch(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.search, *args, **kwargs)

    async def aexplore(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.explore, *args, **kwargs)

    async def ausages(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.usages, *args, **kwargs)

    async def aimplementations(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.implementations, *args, **kwargs)

    async def arepo_map(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.repo_map, *args, **kwargs)

    async def anotes(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.notes, *args, **kwargs)

    async def agraph_generation(self) -> Dict[str, Any]:
        return await self._async(self.graph_generation)

    async def averify_drift(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.verify_drift, *args, **kwargs)

    async def anode(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.node, *args, **kwargs)

    async def astats(self) -> Dict[str, Any]:
        return await self._async(self.stats)

    async def aget_architecture_report(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.get_architecture_report, *args, **kwargs)

    async def apack_context_bundle(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.pack_context_bundle, *args, **kwargs)

    async def aget_communities(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.get_communities, *args, **kwargs)
    async def aget_architecture_bundle(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.get_architecture_bundle, *args, **kwargs)

    async def atrace(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.trace, *args, **kwargs)

    async def aui_tree(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.ui_tree, *args, **kwargs)

    async def abackend_flow(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.backend_flow, *args, **kwargs)

    async def asolution_inventory(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.solution_inventory, *args, **kwargs)

    async def asolution_steps(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.solution_steps, *args, **kwargs)

    async def asolution_bundle(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await self._async(self.solution_bundle, *args, **kwargs)


__all__ = ["McpService", "McpServiceError", "ServiceLimits"]
