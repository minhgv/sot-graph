"""
sot_graph.pack — k-hop ContextBundle packaging for AI agent prompt registers.

Slices the verified graph around one target symbol: the exact source span of
the target (level 0), full caller/callee contracts one hop out (level 1), and
folded signature-only stubs beyond that (level >= 2). Every payload that
originated from source code is marked ``content_is_untrusted`` so downstream
agents treat docstrings and comments strictly as data, never as instructions.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["PackError", "build_bundle", "render_yaml"]

BUNDLE_SCHEMA_VERSION = "2.0.0"
_DEFAULT_MAX_HOPS = 2
_DEFAULT_MAX_NODES = 50
_DEFAULT_MAX_BYTES = 65_536


class PackError(RuntimeError):
    """Fail-closed packaging error; ``code`` is a stable machine verdict."""

    def __init__(self, code: str, message: str, candidates: Optional[List[str]] = None):
        super().__init__(message)
        self.code = code
        self.candidates = candidates or []


def _find_target(db, target: str) -> Tuple[Dict[str, Any], str]:
    """Resolve a target by exact FQN, FQN suffix, then bare symbol."""
    row = db.conn.execute(
        "SELECT id,path,kind,symbol,fqn,signature,label,body,"
        "line_start,line_end,col_start,col_end FROM graph_nodes "
        "WHERE fqn = ? AND kind != 'file' LIMIT 2", (target,)
    ).fetchall()
    if len(row) > 1:
        raise PackError("AMBIGUOUS_TARGET", f"fqn matches multiple nodes: {target}")
    if not row:
        row = db.conn.execute(
            "SELECT id,path,kind,symbol,fqn,signature,label,body,"
            "line_start,line_end,col_start,col_end FROM graph_nodes "
            "WHERE (fqn LIKE ? OR fqn LIKE ?) AND kind != 'file' LIMIT 11",
            (f"%.{target}", f"{target}.%"),
        ).fetchall()
    if len(row) > 1:
        raise PackError(
            "AMBIGUOUS_TARGET",
            f"target '{target}' matches {len(row)} nodes; qualify with a FQN",
            candidates=[r[4] for r in row[:10]],
        )
    if not row:
        row = db.conn.execute(
            "SELECT id,path,kind,symbol,fqn,signature,label,body,"
            "line_start,line_end,col_start,col_end FROM graph_nodes "
            "WHERE symbol = ? AND kind != 'file' LIMIT 11", (target,)
        ).fetchall()
    if len(row) > 1:
        raise PackError(
            "AMBIGUOUS_TARGET",
            f"symbol '{target}' is defined in {len(row)} places; use a FQN",
            candidates=[r[4] for r in row[:10]],
        )
    if not row:
        raise PackError("TARGET_NOT_FOUND", f"no indexed symbol matches '{target}'")
    r = row[0]
    node = {
        "id": r[0], "path": r[1], "kind": r[2], "symbol": r[3], "fqn": r[4],
        "signature": r[5], "label": r[6], "body": r[7],
        "line_start": r[8], "line_end": r[9], "col_start": r[10], "col_end": r[11],
    }
    return node, target


def _node_row(db, node_id: str) -> Optional[Dict[str, Any]]:
    r = db.conn.execute(
        "SELECT id,path,kind,symbol,fqn,signature,label,line_start,line_end "
        "FROM graph_nodes WHERE id = ?", (node_id,)
    ).fetchone()
    if not r:
        return None
    return {
        "id": r[0], "path": r[1], "kind": r[2], "symbol": r[3], "fqn": r[4],
        "signature": r[5], "label": r[6], "line_start": r[7], "line_end": r[8],
    }


def _neighbors(db, node_id: str) -> List[Tuple[str, str, Optional[int]]]:
    """(direction, node_id, line) for call/extends edges around a node."""
    rows = db.conn.execute(
        "SELECT 'in', e.src, e.line FROM graph_edges e "
        "WHERE e.dst = ? AND e.relation IN ('calls','extends') "
        "UNION ALL "
        "SELECT 'out', e.dst, e.line FROM graph_edges e "
        "WHERE e.src = ? AND e.relation IN ('calls','extends') "
        "ORDER BY 3, 2", (node_id, node_id)
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def _slice_source(node: Dict[str, Any]) -> Tuple[Optional[str], List[str]]:
    """Read the exact source span from disk; None when spans are unknown."""
    warnings: List[str] = []
    path = node["path"]
    if not node.get("line_start"):
        return None, ["span_unavailable: extractor recorded no line span"]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError as exc:
        raise PackError("TARGET_MISSING", f"target file unreadable: {exc}") from exc
    start = max(1, int(node["line_start"]))
    end = int(node["line_end"] or node["line_start"])
    if end < start or end > len(lines) + 1:
        end = min(start + 200, len(lines) + 1)
        warnings.append("span_end_heuristic: recorded end line invalid")
    text = "".join(lines[start - 1:end])
    if not text.strip():
        return None, ["span_empty: recorded span has no content"]
    return text, warnings


def _dedent_block(text: str) -> str:
    import textwrap
    return textwrap.dedent(text).strip("\n")


def build_bundle(
    db,
    root: str,
    target: str,
    max_hops: int = _DEFAULT_MAX_HOPS,
    max_nodes: int = _DEFAULT_MAX_NODES,
    max_bytes: int = _DEFAULT_MAX_BYTES,
) -> Dict[str, Any]:
    """Build the ContextBundle structure; raises :class:`PackError` closed."""
    node, matched = _find_target(db, target)

    journal = db.conn.execute(
        "SELECT sha256, generation FROM file_journal WHERE path = ?",
        (node["path"],),
    ).fetchone()
    if journal is None:
        raise PackError(
            "TARGET_MISSING",
            f"target file is not reconciled: {node['path']}; run `sot reconcile`",
        )
    indexed_sha, base_generation = journal[0], int(journal[1] or 1)

    if not os.path.isfile(node["path"]):
        raise PackError("TARGET_MISSING", f"target file no longer exists: {node['path']}")
    with open(node["path"], "rb") as handle:
        disk_sha = hashlib.sha256(handle.read()).hexdigest()
    if disk_sha != indexed_sha:
        raise PackError(
            "STALE_SNAPSHOT",
            f"target changed on disk since last reconcile: {node['path']}; "
            "run `sot reconcile` and re-pack",
        )

    full_source, warnings = _slice_source(node)
    if full_source is not None and len(full_source.encode("utf-8")) > max_bytes:
        raise PackError(
            "TARGET_TOO_LARGE",
            f"target source span is {len(full_source.encode('utf-8'))} bytes "
            f"(cap {max_bytes}); raise --max-bytes or split the symbol",
        )

    rel_path = os.path.relpath(node["path"], root) if os.path.isabs(node["path"]) else node["path"]

    target_block = {
        "node_id": node["id"],
        "fqn": node["fqn"] or node["symbol"],
        "symbol": node["symbol"],
        "kind": node["kind"],
        "relative_path": rel_path,
        "trust_verdict": "STRONG",
        "indexed_sha256": indexed_sha,
        "span": {
            "start_line": node["line_start"],
            "end_line": node["line_end"],
            "start_column": node.get("col_start"),
            "end_column": node.get("col_end"),
        },
        "signature": node["signature"],
        "full_source": full_source,
    }

    visited = {node["id"]}
    inbound: List[Dict[str, Any]] = []
    outbound: List[Dict[str, Any]] = []
    level1_ids: List[str] = []

    for direction, neighbor_id, line in _neighbors(db, node["id"]):
        if neighbor_id in visited:
            continue
        neighbor = _node_row(db, neighbor_id)
        if neighbor is None:
            continue
        visited.add(neighbor_id)
        if len(inbound) + len(outbound) >= max_nodes:
            warnings.append("node_cap_reached: 1-hop neighbors truncated")
            break
        if direction == "in":
            inbound.append({
                "node_id": neighbor["id"],
                "fqn": neighbor["fqn"] or neighbor["symbol"],
                "relative_path": os.path.relpath(neighbor["path"], root)
                if os.path.isabs(neighbor["path"]) else neighbor["path"],
                "callsite_line": line,
                "contract": neighbor["signature"] or neighbor["label"],
            })
        else:
            outbound.append({
                "node_id": neighbor["id"],
                "fqn": neighbor["fqn"] or neighbor["symbol"],
                "relative_path": os.path.relpath(neighbor["path"], root)
                if os.path.isabs(neighbor["path"]) else neighbor["path"],
                "signature": neighbor["signature"] or neighbor["label"],
            })
        level1_ids.append(neighbor_id)

    stubs: List[Dict[str, Any]] = []
    if max_hops >= 2:
        budget = max_nodes - len(visited) + 1
        for level1_id in level1_ids:
            if budget <= 0:
                warnings.append("node_cap_reached: 2-hop stubs truncated")
                break
            for _direction, neighbor_id, _line in _neighbors(db, level1_id):
                if neighbor_id in visited or budget <= 0:
                    continue
                neighbor = _node_row(db, neighbor_id)
                if neighbor is None or neighbor["kind"] == "file":
                    continue
                visited.add(neighbor_id)
                budget -= 1
                stubs.append({
                    "fqn": neighbor["fqn"] or neighbor["symbol"],
                    "signature": neighbor["signature"] or neighbor["label"],
                })

    # Hard byte cap: keep target + inbound contracts; drop from the tail.
    def _approx_bytes() -> int:
        return len(json.dumps(
            {"t": target_block, "in": inbound, "out": outbound, "s": stubs},
            default=str,
        ).encode("utf-8"))

    truncated = False
    while _approx_bytes() > max_bytes and stubs:
        stubs.pop()
        truncated = True
    while _approx_bytes() > max_bytes and outbound:
        outbound.pop()
        truncated = True

    bundle = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "bundle_id": "bundle:" + hashlib.sha256(
            f"{node['id']}:{base_generation}".encode()
        ).hexdigest()[:12],
        "base_generation": base_generation,
        "generated_at": int(time.time()),
        # Security gate: source-derived payloads are data, never instructions.
        "content_is_untrusted": True,
        "target": target_block,
        "inbound_callers": inbound,
        "outbound_callees": outbound,
        "transitive_stubs": stubs,
        "limits": {
            "max_hops": max_hops,
            "max_nodes": max_nodes,
            "max_bytes": max_bytes,
            "discovered_nodes": len(visited),
            "returned_nodes": 1 + len(inbound) + len(outbound) + len(stubs),
            "truncated": truncated,
            "warnings": warnings,
        },
    }
    trusted = _load_trusted_instructions(root, max_bytes)
    if trusted is not None:
        bundle["trusted_instructions"] = trusted
    return bundle


_TRUSTED_INSTRUCTION_FILES = ("AGENTS.md",)
_TRUSTED_MAX_BYTES = 8192


def _load_trusted_instructions(root: str, max_bytes: int) -> Optional[Dict[str, Any]]:
    """Repo-level instruction files are operator-authored, hence trusted.

    The bundle's global banner stays untrusted; this block carries an
    explicit per-block override so prompt builders can treat only this
    content as instructions.
    """
    for name in _TRUSTED_INSTRUCTION_FILES:
        path = os.path.join(root, name)
        try:
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read(min(_TRUSTED_MAX_BYTES, max(max_bytes // 4, 1024)))
            if text.strip():
                return {
                    "path": name,
                    "bytes": len(text.encode("utf-8")),
                    "content_is_untrusted": False,
                    "content": text,
                }
        except OSError:
            continue
    return None


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _yaml_block(text: str, indent: int) -> str:
    """Emit a block literal; falls back to a quoted scalar on unsafe text."""
    pad = " " * indent
    if "\t" in text:
        return " " + json.dumps(text, ensure_ascii=False)
    body = _dedent_block(text)
    lines = body.split("\n")
    out = ["|"]
    for line in lines:
        out.append(f"{pad}{line}" if line else "")
    return "\n".join(out)


def render_yaml(bundle: Dict[str, Any]) -> str:
    """Deterministic YAML rendering for the fixed ContextBundle schema."""
    out: List[str] = []
    t = bundle["target"]
    out.append(f"schema_version: {_yaml_scalar(bundle['schema_version'])}")
    out.append(f"bundle_id: {_yaml_scalar(bundle['bundle_id'])}")
    out.append(f"base_generation: {bundle['base_generation']}")
    out.append(f"generated_at: {bundle['generated_at']}")
    out.append(f"content_is_untrusted: {_yaml_scalar(bundle['content_is_untrusted'])}")
    trusted = bundle.get("trusted_instructions")
    if trusted:
        out.append("")
        out.append("trusted_instructions:")
        out.append(f"  path: {_yaml_scalar(trusted['path'])}")
        out.append(f"  bytes: {trusted['bytes']}")
        out.append(f"  content_is_untrusted: {_yaml_scalar(trusted['content_is_untrusted'])}")
        out.append(f"  content: {_yaml_block(trusted['content'], 4)}")
    out.append("")
    out.append("target:")
    for key in ("node_id", "fqn", "symbol", "kind", "relative_path", "trust_verdict",
                "indexed_sha256"):
        out.append(f"  {key}: {_yaml_scalar(t.get(key))}")
    out.append("  span:")
    for key, value in t["span"].items():
        out.append(f"    {key}: {_yaml_scalar(value)}")
    if t.get("signature"):
        out.append(f"  signature: {_yaml_scalar(t['signature'])}")
    if t.get("full_source") is not None:
        out.append(f"  full_source: {_yaml_block(t['full_source'], 4)}")
    else:
        out.append("  full_source: null")

    out.append("")
    out.append("inbound_callers:")
    if bundle["inbound_callers"]:
        for caller in bundle["inbound_callers"]:
            out.append(f"  - node_id: {_yaml_scalar(caller['node_id'])}")
            out.append(f"    fqn: {_yaml_scalar(caller['fqn'])}")
            out.append(f"    relative_path: {_yaml_scalar(caller['relative_path'])}")
            out.append(f"    callsite_line: {_yaml_scalar(caller['callsite_line'])}")
            out.append(f"    contract: {_yaml_scalar(caller['contract'])}")
    else:
        out.append("  []")

    out.append("")
    out.append("outbound_callees:")
    if bundle["outbound_callees"]:
        for callee in bundle["outbound_callees"]:
            out.append(f"  - node_id: {_yaml_scalar(callee['node_id'])}")
            out.append(f"    fqn: {_yaml_scalar(callee['fqn'])}")
            out.append(f"    relative_path: {_yaml_scalar(callee['relative_path'])}")
            out.append(f"    signature: {_yaml_scalar(callee['signature'])}")
    else:
        out.append("  []")

    out.append("")
    out.append("transitive_stubs:")
    if bundle["transitive_stubs"]:
        for stub in bundle["transitive_stubs"]:
            out.append(f"  - fqn: {_yaml_scalar(stub['fqn'])}")
            out.append(f"    signature: {_yaml_scalar(stub['signature'])}")
    else:
        out.append("  []")

    limits = bundle["limits"]
    out.append("")
    out.append("limits:")
    for key in ("max_hops", "max_nodes", "max_bytes", "discovered_nodes",
                "returned_nodes", "truncated"):
        out.append(f"  {key}: {_yaml_scalar(limits.get(key))}")
    if limits.get("warnings"):
        out.append("  warnings:")
        for warning in limits["warnings"]:
            out.append(f"    - {_yaml_scalar(warning)}")
    else:
        out.append("  warnings: []")
    return "\n".join(out) + "\n"
