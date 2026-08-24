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

from sot_graph.tokenizer import estimate_tokens, truncate_to_token_budget

__all__ = ["PackError", "build_bundle", "render_yaml"]

BUNDLE_SCHEMA_VERSION = "2.1.0"
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


def _slice_source_from_bytes(node: Dict[str, Any], raw_bytes: bytes) -> Tuple[Optional[str], List[str]]:
    """Extract the exact source span from pre-read file bytes; None when spans are unknown."""
    warnings: List[str] = []
    if not node.get("line_start"):
        return None, ["span_unavailable: extractor recorded no line span"]
    text_content = raw_bytes.decode("utf-8", errors="replace")
    lines = text_content.splitlines(keepends=True)
    start = max(1, int(node["line_start"]))
    end = int(node["line_end"] or node["line_start"])
    if end < start or end > len(lines) + 1:
        end = min(start + 200, len(lines) + 1)
        warnings.append("span_end_heuristic: recorded end line invalid")
    text = "".join(lines[start - 1:end])
    if not text.strip():
        return None, ["span_empty: recorded span has no content"]
    return text, warnings


def _slice_source(node: Dict[str, Any]) -> Tuple[Optional[str], List[str]]:
    """Read the exact source span from disk; None when spans are unknown."""
    path = node["path"]
    try:
        with open(path, "rb") as handle:
            raw_bytes = handle.read()
    except OSError as exc:
        raise PackError("TARGET_MISSING", f"target file unreadable: {exc}") from exc
    return _slice_source_from_bytes(node, raw_bytes)


def _dedent_block(text: str) -> str:
    import textwrap
    return textwrap.dedent(text).strip("\n")
def _verify_neighbor_freshness(db, neighbor_path: str) -> Tuple[str, Optional[str]]:
    """Check if neighbor file exists and matches indexed hash.

    Returns (verdict, warning_or_none) where verdict is 'FRESH', 'STALE', or 'MISSING'.
    """
    if not os.path.isfile(neighbor_path):
        return "MISSING", f"neighbor_missing: file {neighbor_path} no longer exists on disk"

    journal = db.conn.execute(
        "SELECT sha256 FROM file_journal WHERE path = ?", (neighbor_path,)
    ).fetchone()
    if journal is None:
        return "UNKNOWN", f"neighbor_unindexed: file {neighbor_path} is not in file journal"

    try:
        with open(neighbor_path, "rb") as fh:
            disk_sha = hashlib.sha256(fh.read()).hexdigest()
        if disk_sha != journal[0]:
            return "STALE", f"neighbor_stale: file {neighbor_path} modified on disk since indexing"
        return "FRESH", None
    except OSError as exc:
        return "UNREADABLE", f"neighbor_error: cannot read {neighbor_path}: {exc}"


def build_bundle(
    db,
    root: str,
    target: str,
    max_hops: int = _DEFAULT_MAX_HOPS,
    max_nodes: int = _DEFAULT_MAX_NODES,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    max_tokens: Optional[int] = None,
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

    try:
        with open(node["path"], "rb") as handle:
            raw_bytes = handle.read()
    except OSError as exc:
        raise PackError("TARGET_MISSING", f"target file no longer exists or unreadable: {node['path']}") from exc

    disk_sha = hashlib.sha256(raw_bytes).hexdigest()
    if disk_sha != indexed_sha:
        raise PackError(
            "STALE_SNAPSHOT",
            f"target changed on disk since last reconcile: {node['path']}; "
            "run `sot reconcile` and re-pack",
        )

    full_source, warnings = _slice_source_from_bytes(node, raw_bytes)
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

        n_verdict, n_warn = _verify_neighbor_freshness(db, neighbor["path"])
        if n_warn:
            warnings.append(n_warn)

        n_rel_path = os.path.relpath(neighbor["path"], root) if os.path.isabs(neighbor["path"]) else neighbor["path"]

        if direction == "in":
            inbound.append({
                "node_id": neighbor["id"],
                "fqn": neighbor["fqn"] or neighbor["symbol"],
                "relative_path": n_rel_path,
                "trust_verdict": n_verdict,
                "callsite_line": line,
                "contract": neighbor["signature"] or neighbor["label"],
            })
        else:
            outbound.append({
                "node_id": neighbor["id"],
                "fqn": neighbor["fqn"] or neighbor["symbol"],
                "relative_path": n_rel_path,
                "trust_verdict": n_verdict,
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
        draft = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "bundle_id": "bundle:preview",
            "base_generation": base_generation,
            "generated_at": int(time.time()),
            "content_is_untrusted": True,
            "target": target_block,
            "inbound_callers": inbound,
            "outbound_callees": outbound,
            "transitive_stubs": stubs,
            "limits": {
                "max_hops": max_hops,
                "max_nodes": max_nodes,
                "max_bytes": max_bytes,
                "max_tokens": max_tokens,
                "tokens_estimate": 0,
                "discovered_nodes": len(visited),
                "returned_nodes": 1 + len(inbound) + len(outbound) + len(stubs),
                "truncated": False,
                "warnings": warnings,
            },
        }
        return len(render_yaml(draft).encode("utf-8"))
    truncated = False
    while _approx_bytes() > max_bytes and stubs:
        stubs.pop()
        truncated = True
    while _approx_bytes() > max_bytes and outbound:
        outbound.pop()
        truncated = True
    # Build draft bundle
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
            "max_tokens": max_tokens,
            "tokens_estimate": 0,
            "discovered_nodes": len(visited),
            "returned_nodes": 1 + len(inbound) + len(outbound) + len(stubs),
            "truncated": truncated,
            "warnings": warnings,
        },
    }
    trusted = _load_trusted_instructions(root, max_bytes)
    if trusted is not None:
        bundle["trusted_instructions"] = trusted

    # Hard token budget enforcement if max_tokens is provided
    if max_tokens is not None:
        if max_tokens < 32:
            raise PackError("BUDGET_TOO_SMALL", f"max_tokens ({max_tokens}) is too small to fit target block metadata (minimum 32 tokens required)")
        rendered = render_yaml(bundle)
        tok_count = estimate_tokens(rendered)
        while tok_count > max_tokens and stubs:
            stubs.pop()
            bundle["transitive_stubs"] = stubs
            bundle["limits"]["returned_nodes"] = 1 + len(inbound) + len(outbound) + len(stubs)
            truncated = True
            bundle["limits"]["truncated"] = True
            rendered = render_yaml(bundle)
            tok_count = estimate_tokens(rendered)

        while tok_count > max_tokens and outbound:
            outbound.pop()
            bundle["outbound_callees"] = outbound
            bundle["limits"]["returned_nodes"] = 1 + len(inbound) + len(outbound) + len(stubs)
            truncated = True
            bundle["limits"]["truncated"] = True
            rendered = render_yaml(bundle)
            tok_count = estimate_tokens(rendered)

        while tok_count > max_tokens and inbound:
            inbound.pop()
            bundle["inbound_callers"] = inbound
            bundle["limits"]["returned_nodes"] = 1 + len(inbound) + len(outbound) + len(stubs)
            truncated = True
            bundle["limits"]["truncated"] = True
            rendered = render_yaml(bundle)
            tok_count = estimate_tokens(rendered)

        if tok_count > max_tokens and target_block.get("full_source"):
            # Target span truncation
            overhead_tokens = estimate_tokens(render_yaml({**bundle, "target": {**target_block, "full_source": ""}}))
            avail_source_tokens = max(16, max_tokens - overhead_tokens)
            trunc_src, is_trunc, _ = truncate_to_token_budget(target_block["full_source"], avail_source_tokens)
            if is_trunc:
                target_block["full_source"] = trunc_src
                truncated = True
                bundle["limits"]["truncated"] = True
                warnings.append("token_cap_reached: target full_source truncated")
                rendered = render_yaml(bundle)
                tok_count = estimate_tokens(rendered)

        if tok_count > max_tokens and bundle.get("trusted_instructions"):
            inst_block = bundle["trusted_instructions"]
            inst_text = inst_block.get("content", "")
            if inst_text:
                avail_inst_tokens = max(16, max_tokens // 4)
                trunc_inst, is_trunc_inst, _ = truncate_to_token_budget(inst_text, avail_inst_tokens)
                if is_trunc_inst:
                    inst_block["content"] = trunc_inst
                    truncated = True
                    bundle["limits"]["truncated"] = True
                    warnings.append("token_cap_reached: trusted instructions truncated")
                    rendered = render_yaml(bundle)
                    tok_count = estimate_tokens(rendered)

        # Strict budget enforcement: if still exceeding max_tokens, drop remaining components or truncate cleanly
        if tok_count > max_tokens and bundle.get("trusted_instructions"):
            del bundle["trusted_instructions"]
            truncated = True
            bundle["limits"]["truncated"] = True
            warnings.append("token_cap_reached: trusted instructions omitted")
            rendered = render_yaml(bundle)
            tok_count = estimate_tokens(rendered)

        if tok_count > max_tokens and target_block.get("full_source"):
            # Truncate source further down if needed
            while tok_count > max_tokens and target_block.get("full_source"):
                curr_src = target_block["full_source"]
                if len(curr_src) <= 50:
                    target_block["full_source"] = ""
                else:
                    new_len = len(curr_src) // 2
                    trunc_candidate = curr_src[:new_len] + "\n# ... truncated ..."
                    if len(trunc_candidate) >= len(curr_src):
                        trunc_candidate = curr_src[:new_len]
                    target_block["full_source"] = trunc_candidate
                truncated = True
                bundle["limits"]["truncated"] = True
                rendered = render_yaml(bundle)
                tok_count = estimate_tokens(rendered)
        # Stable token estimation & final validation
        tok_est = estimate_tokens(render_yaml(bundle))
        bundle["limits"]["tokens_estimate"] = tok_est
        rendered = render_yaml(bundle)
        tok_count = estimate_tokens(rendered)
        if tok_count != tok_est:
            bundle["limits"]["tokens_estimate"] = tok_count
            rendered = render_yaml(bundle)
            tok_count = estimate_tokens(rendered)

        if tok_count > max_tokens:
            raise PackError("BUDGET_TOO_SMALL", f"rendered bundle ({tok_count} tokens) exceeds budget ({max_tokens} tokens)")
    else:
        tok_est = estimate_tokens(render_yaml(bundle))
        bundle["limits"]["tokens_estimate"] = tok_est
        rendered = render_yaml(bundle)
        tok_count = estimate_tokens(rendered)
        if tok_count != tok_est:
            bundle["limits"]["tokens_estimate"] = tok_count
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
            if "trust_verdict" in caller:
                out.append(f"    trust_verdict: {_yaml_scalar(caller['trust_verdict'])}")
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
            if "trust_verdict" in callee:
                out.append(f"    trust_verdict: {_yaml_scalar(callee['trust_verdict'])}")
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
    for key in ("max_hops", "max_nodes", "max_bytes", "max_tokens", "tokens_estimate",
                "discovered_nodes", "returned_nodes", "truncated"):
        if key in limits:
            out.append(f"  {key}: {_yaml_scalar(limits.get(key))}")
    if limits.get("warnings"):
        out.append("  warnings:")
        for warning in limits["warnings"]:
            out.append(f"    - {_yaml_scalar(warning)}")
    else:
        out.append("  warnings: []")
    return "\n".join(out) + "\n"
