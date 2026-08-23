"""Token-budgeted repo map ranked by personalized PageRank.

Aider proved that a PageRank-ranked, token-budgeted symbol map gives coding
agents cheap orientation (https://aider.chat/docs/repomap.html). This module
applies the same recipe to the sot-graph database: rank code symbols by
graph centrality, personalize on the caller's focus set when given, then
binary-search the symbol count until the rendered tree fits the budget.
"""
from __future__ import annotations
import os
from typing import Any, Dict, List, Optional

from sot_graph.tokenizer import estimate_tokens

DAMPING = 0.85
ITERATIONS = 24
_RANKED_RELATIONS = ("calls", "extends", "implements", "uses")


def _display_path(path: str, root: Optional[str]) -> str:
    """Absolute journal paths are normalized so the budget is spent on code."""
    if root and os.path.isabs(path):
        try:
            return os.path.relpath(path, root)
        except ValueError:
            return path
    return path


def _load_symbols(conn, root: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, symbol, kind, path, line_start, signature FROM graph_nodes "
        "WHERE kind != 'file' AND kind != 'note' AND path != '' "
        "AND kind != 'markdown'"
    ).fetchall()
    if not rows:
        return {}
    if root is None:
        abs_paths = [r[3] for r in rows if os.path.isabs(r[3])]
        if abs_paths:
            try:
                root = os.path.commonpath(abs_paths)
            except ValueError:
                root = None
    return {
        row[0]: {"id": row[0], "symbol": row[1], "kind": row[2],
                 "path": _display_path(row[3], root),
                 "line": row[4], "signature": row[5]}
        for row in rows
    }


def _load_edges(conn, symbol_ids) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for src, dst, relation in conn.execute(
        f"SELECT src, dst, relation FROM graph_edges "
        f"WHERE relation IN ({','.join('?' * len(_RANKED_RELATIONS))})",
        _RANKED_RELATIONS,
    ):
        if src in symbol_ids and dst in symbol_ids and src != dst:
            out.setdefault(src, []).append(dst)
    return out


def pagerank(
    nodes: List[str],
    out_edges: Dict[str, List[str]],
    personalization: Optional[Dict[str, float]] = None,
    damping: float = DAMPING,
    iterations: int = ITERATIONS,
) -> Dict[str, float]:
    """Power iteration with uniform restart mass (dangling nodes included)."""
    n = len(nodes)
    if n == 0:
        return {}
    base = personalization or {u: 1.0 / n for u in nodes}
    total = sum(base.values()) or 1.0
    base = {u: base.get(u, 0.0) / total for u in nodes}
    rank = dict(base)
    out_count = {u: len(out_edges.get(u, [])) for u in nodes}
    for _ in range(iterations):
        nxt = {u: (1.0 - damping) * base.get(u, 0.0) for u in nodes}
        dangling = damping * sum(rank[u] for u in nodes if out_count[u] == 0) / n
        for u in nodes:
            nxt[u] += dangling
        for u in nodes:
            if out_count[u]:
                share = damping * rank[u] / out_count[u]
                for v in out_edges[u]:
                    nxt[v] += share
        rank = nxt
    return rank


def _resolve_focus(conn, focus: List[str], symbol_ids) -> List[str]:
    resolved: List[str] = []
    for name in focus:
        name = name.strip()
        if not name:
            continue
        row = conn.execute(
            "SELECT id FROM graph_nodes WHERE symbol = ? LIMIT 1", (name,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id FROM graph_nodes WHERE kind != 'file' AND (label LIKE ? OR fqn LIKE ?) "
                "ORDER BY kind LIMIT 1", (f"%{name}%", f"%{name}%")
            ).fetchone()
        if row and row[0] in symbol_ids:
            resolved.append(row[0])
    return resolved


def _render(symbols: List[Dict[str, Any]]) -> str:
    by_path: Dict[str, List[Dict[str, Any]]] = {}
    for sym in symbols:
        by_path.setdefault(sym["path"], []).append(sym)
    lines: List[str] = []
    for path in sorted(by_path):
        lines.append(f"{path}:")
        for sym in sorted(by_path[path], key=lambda s: (s["line"] or 0, s["symbol"])):
            stub = sym["signature"] or sym["symbol"]
            lines.append(f"  {stub}")
    return "\n".join(lines)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def build_repo_map(
    conn,
    *,
    focus: Optional[List[str]] = None,
    max_tokens: int = 1024,
    max_symbols: int = 400,
    root: Optional[str] = None,
) -> Dict[str, Any]:
    """Rank symbols by personalized PageRank and fit them to a token budget."""
    max_tokens = max(16, min(int(max_tokens), 32_768))
    symbols = _load_symbols(conn, root)
    if not symbols:
        return {"files": [], "rendered": "", "tokens_estimate": 0,
                "symbols": 0, "focus": [], "truncated": False}

    ids = list(symbols)
    out_edges = _load_edges(conn, symbols)
    personalization = None
    focus_ids: List[str] = []
    if focus:
        focus_ids = _resolve_focus(conn, [f for f in focus], symbols)
        if focus_ids:
            personalization = {fid: 1.0 for fid in focus_ids}
    ranks = pagerank(ids, out_edges, personalization)
    ordered = sorted(ids, key=lambda u: (-ranks[u], symbols[u]["path"], symbols[u]["symbol"]))
    # Focus symbols are guaranteed to appear in the map (front of the
    # budgeted prefix) even when pure centrality would rank them lower.
    if focus_ids:
        focus_set = set(focus_ids)
        ordered = [u for u in focus_ids if u in focus_set] + \
                  [u for u in ordered if u not in focus_set]
    ordered = ordered[:max_symbols]

    # Binary search the largest prefix whose rendered tree fits the budget.
    lo, hi, best = 1, len(ordered), 1
    while lo <= hi:
        mid = (lo + hi) // 2
        text = _render([symbols[u] for u in ordered[:mid]])
        if estimate_tokens(text) <= max_tokens:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    chosen = ordered[:best]
    rendered = _render([symbols[u] for u in chosen])
    files: List[Dict[str, Any]] = []
    by_path: Dict[str, List[Dict[str, Any]]] = {}
    lang_counts: Dict[str, int] = {}

    for u in chosen:
        sym_path = symbols[u]["path"]
        ext = os.path.splitext(sym_path)[1].lstrip(".") or "other"
        lang_counts[ext] = lang_counts.get(ext, 0) + 1

        by_path.setdefault(sym_path, []).append(
            {"symbol": symbols[u]["symbol"], "kind": symbols[u]["kind"],
             "line": symbols[u]["line"], "signature": symbols[u]["signature"],
             "rank": round(ranks[u], 8)})
    for path in sorted(by_path):
        files.append({"path": path,
                      "symbols": sorted(by_path[path], key=lambda s: (s["line"] or 0, s["symbol"]))})

    total_syms = len(chosen)
    lang_breakdown = {
        lang: round((count / total_syms) * 100.0, 1)
        for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1])
    } if total_syms > 0 else {}

    return {
        "files": files,
        "rendered": rendered,
        "tokens_estimate": estimate_tokens(rendered),
        "symbols": len(chosen),
        "focus": focus_ids,
        "ranking_method": "personalized_pagerank" if focus_ids else "pagerank",
        "language_breakdown": lang_breakdown,
        "truncated": len(chosen) < len(ordered) or best < len(ordered),
    }
