"""
sot_graph.extractor — Dispatcher for source code AST and Symbol extraction.
Maps file extensions to extractors and standardizes node/edge schemas.
"""

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from sot_graph.db import Database
from sot_graph.modutil import dotted_module, normalize_import, resolve_relative

# Suffix to extractor mapping
EXT_DISPATCH = {
    ".py": "extract_python",
    ".js": "extract_js",
    ".jsx": "extract_js",
    ".ts": "extract_js",
    ".tsx": "extract_js",
    ".mjs": "extract_js",
    ".cjs": "extract_js",
    ".go": "extract_go",
    ".rs": "extract_rust",
    ".java": "extract_java",
    ".c": "extract_c",
    ".h": "extract_c",
    ".cpp": "extract_cpp",
    ".cc": "extract_cpp",
    ".cxx": "extract_cpp",
    ".hpp": "extract_cpp",
    ".rb": "extract_ruby",
    ".php": "extract_php",
    ".swift": "extract_swift",
    ".kt": "extract_kotlin",
    ".kts": "extract_kotlin",
    ".dart": "extract_dart",
    ".cs": "extract_c_sharp",
    ".scala": "extract_scala",
    ".sc": "extract_scala",
    ".ex": "extract_elixir",
    ".exs": "extract_elixir",
    ".lua": "extract_lua",
    ".zig": "extract_zig",
    ".jl": "extract_julia",
    ".r": "extract_r",
    ".R": "extract_r",
    ".clj": "extract_clojure",
    ".cljs": "extract_clojure",
    ".cljc": "extract_clojure",
    ".sql": "extract_sql",
    ".graphql": "extract_graphql",
    ".gql": "extract_graphql",
    ".vue": "extract_sfc",
    ".svelte": "extract_sfc",
}
LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".dart": "dart",
    ".cs": "c_sharp",
    ".scala": "scala",
    ".sc": "scala",
    ".ex": "elixir",
    ".exs": "elixir",
    ".lua": "lua",
    ".arb": "json",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sh": "shell",
    ".zig": "zig",
    ".jl": "julia",
    ".r": "r",
    ".R": "r",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".cljc": "clojure",
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".vue": "vue",
    ".svelte": "svelte",
}


def get_language(path: str) -> str:
    ext = Path(path).suffix.lower()
    return LANGUAGE_MAP.get(ext, "text")


def _preview_budget() -> int:
    """Content-preview bytes for file nodes (searchable via FTS).

    Default 4KB covers most source files entirely; SOT_PREVIEW_BYTES raises
    or lowers it (0..1MB) for repos that need deep content search — pair a
    raise with `sot reconcile --force` to refresh existing indexes.
    """
    try:
        raw = int(os.environ.get("SOT_PREVIEW_BYTES", "4096"))
    except ValueError:
        return 4096
    return min(1_048_576, max(0, raw))

def _decompose_keywords(*sources: Optional[str]) -> List[str]:
    """Extract full identifiers, sub-tokens, snake_case parts, camelCase parts,
    and adjacent n-grams so FTS5 matches both full and partial queries."""
    seen: Set[str] = set()
    out: List[str] = []

    def _add(tok: str) -> None:
        cleaned = tok.strip("._-/$: ")
        if len(cleaned) >= 2 and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)

    for src in sources:
        if not src:
            continue
        _add(src)
        parts = [p for p in re.split(r"[\s/\\.:\-]+", src) if p]
        for p in parts:
            _add(p)
            sub_parts = [sp for sp in p.split("_") if sp]
            if len(sub_parts) > 1:
                for sp in sub_parts:
                    _add(sp)
                for i in range(len(sub_parts) - 1):
                    _add(f"{sub_parts[i]}_{sub_parts[i+1]}")
            camel_parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z][a-z0-9]|\b)", p)
            if len(camel_parts) > 1:
                for cp in camel_parts:
                    _add(cp)
    return out


def parse_file_graph(path: str, root_dir: str) -> Dict[str, Any]:
    """
    Extracts AST/Symbols and edges for a file.
    Returns normalized { nodes, edges, pending, error }.
    """
    p = Path(path)
    ext = p.suffix.lower()
    fn_name = EXT_DISPATCH.get(ext)
    rel_path = os.path.relpath(path, root_dir)
    try:
        content_bytes = p.read_bytes()
        sha = hashlib.sha256(content_bytes).hexdigest()
        file_size = len(content_bytes)
    except Exception as e:
        return {"nodes": [], "edges": [], "pending": [], "sha256": "", "size": 0, "error": str(e)}

    ns = hashlib.sha256(path.encode()).hexdigest()[:12]
    file_node_id = f"file:{ns}"
    lang = get_language(path)
    module = dotted_module(rel_path)

    # 1. Base File Node (both code and non-code files carry a short content
    # preview so full-text search can find strings and comments, not just
    # symbol bodies — e.g. Vietnamese labels inside PHP view controllers.)
    preview = content_bytes[:_preview_budget()].decode("utf-8", errors="replace")
    total_lines = content_bytes.count(b"\n") + (1 if content_bytes and not content_bytes.endswith(b"\n") else (0 if not content_bytes else 1))
    total_lines = max(1, total_lines)
    file_node = {
        "id": file_node_id,
        "kind": "file",
        "symbol": p.name,
        "fqn": module,
        "label": f"File: {rel_path}",
        "body": f"File {rel_path} ({lang}, {file_size} bytes)\nPreview:\n{preview}",
        "keywords": _decompose_keywords(p.name, p.stem, lang, "file", rel_path),
        "line_start": 1,
        "line_end": total_lines,
    }

    if not fn_name:
        # Non-code file (Markdown, configs, scripts): no AST extraction.
        return {
            "nodes": [file_node],
            "edges": [],
            "pending": [],
            "sha256": sha,
            "size": file_size,
            "error": None,
        }

    # 2. Invoke Extractor from vendored graphify
    try:
        try:
            from sot_graph._vendor.graphify import extract as gx
        except ImportError:
            from graphify import extract as gx
        extractor_fn = getattr(gx, fn_name, None)
        if not extractor_fn:
            raise AttributeError(f"No extractor function {fn_name}")
        raw_result = extractor_fn(p)
    except Exception as e:
        # Fall back to base file node on extraction failure
        return {
            "nodes": [file_node],
            "edges": [],
            "pending": [],
            "sha256": sha,
            "size": file_size,
            "error": f"Extraction error: {e}",
        }

    raw_nodes = raw_result.get("nodes", [])
    raw_edges = raw_result.get("edges", [])

    nodes = [file_node]
    edges = []
    pending = []
    symbol_to_node_id = {}

    for rn in raw_nodes:
        raw_id = rn.get("id")
        if not raw_id or raw_id == p.name:
            continue

        node_id = f"sym:{ns}:{raw_id}"
        symbol_to_node_id[raw_id] = node_id

        line_no = None
        loc_end = None
        loc = str(rn.get("source_location", ""))
        m = re.search(r"L(\d+)(?:[-:]L?(\d+))?", loc)
        if m:
            line_no = int(m.group(1))
            if m.group(2):
                loc_end = int(m.group(2))

        line_end = rn.get("line_end") or loc_end
        if line_end is None and line_no is not None:
            line_end = line_no

        label = rn.get("label", raw_id)
        kind = rn.get("kind", "symbol")
        doc = rn.get("doc", "")
        body = f"{label} ({kind}) at {rel_path}:{line_no or 1}\n{doc}".strip()

        nodes.append({
            "id": node_id,
            "kind": kind,
            "symbol": raw_id,
            "fqn": f"{module}.{raw_id}" if module else raw_id,
            "signature": rn.get("signature"),
            "label": f"{label} — {rel_path}:{line_no or 1}",
            "body": body,
            "keywords": _decompose_keywords(raw_id, rn.get("label"), kind, lang, p.name, p.stem),
            "line_start": line_no,
            "line_end": line_end,
            "col_start": rn.get("col_start"),
            "col_end": rn.get("col_end"),
        })
    # Intra-file vs Cross-file edges
    is_package = p.name == "__init__.py"

    def _pending_import_source(raw_imp, fallback=None):
        """Absolutize relative imports ('.hooks' from pkg_a -> 'pkg_a.hooks')
        so the resolver can match the exact package instead of every file
        whose path ends in the same bare module name. The fallback (bound
        name) is applied only by the imports branch, matching v1 semantics.
        """
        value = raw_imp if raw_imp else (fallback or "")
        if re.match(r"^\.(?:\w|$)", value):
            resolved = resolve_relative(value, module, is_package)
            if not resolved:
                return None
            if not value.strip("."):
                # 'from . import name': the bound name is itself the module.
                resolved = f"{resolved}.{fallback}" if fallback else resolved
            return resolved
        return normalize_import(value) or None

    for re_edge in raw_edges:
        src_raw = re_edge.get("source")
        dst_raw = re_edge.get("target")
        rel = re_edge.get("relation", "uses")
        if not src_raw or not dst_raw:
            continue

        src_id = symbol_to_node_id.get(src_raw, file_node_id)
        loc = str(re_edge.get("source_location", ""))
        line_no = int(re.search(r"L(\d+)", loc).group(1)) if re.search(r"L(\d+)", loc) else None
        receiver = re_edge.get("receiver")

        if dst_raw in symbol_to_node_id and not re_edge.get("is_shadowed"):
            # Resolved intra-file edge
            edges.append({
                "src": src_id,
                "dst": symbol_to_node_id[dst_raw],
                "relation": rel,
                "line": line_no,
            })
            continue

        # Method-call qualification: a call on `self`/`cls` (or the enclosing
        # class name) targets the class-scoped symbol 'Class.method', while
        # the raw call target is only the bare attribute name. A receiver-less
        # BARE call inside a method (Java/Kotlin sibling call) qualifies too.
        if rel == "calls" and "." in src_raw:
            parent = src_raw.rsplit(".", 1)[0]
            if receiver in ("self", "cls", parent, None):
                qualified_id = symbol_to_node_id.get(f"{parent}.{dst_raw}")
                if qualified_id:
                    edges.append({
                        "src": src_id,
                        "dst": qualified_id,
                        "relation": rel,
                        "line": line_no,
                    })
                    continue

        # Cross-file pending edge (target symbol lives in another file)
        if rel == "calls":
            call_kind = re_edge.get("call_kind") or "UNKNOWN"
            # Local variable calls and unshadowed bare builtins must not create pending external edges
            if re_edge.get("is_local_var") or (call_kind == "BARE" and re_edge.get("builtin")):
                continue
            pending.append({
                "src": src_id,
                "dst_symbol": dst_raw,
                "relation": rel,
                "line": line_no,
                "language": lang,
                "call_kind": call_kind,
                "receiver": re_edge.get("receiver"),
                "import_source": _pending_import_source(
                    re_edge.get("import_source")
                ),
            })
        elif rel == "imports":
            # Import targets are self-describing module paths: the module is
            # the import source, letting the resolver prune externals.
            pending.append({
                "src": src_id,
                "dst_symbol": dst_raw,
                "relation": rel,
                "line": line_no,
                "language": lang,
                "call_kind": "QUALIFIED" if "." in dst_raw else "BARE",
                "receiver": None,
                "import_source": _pending_import_source(
                    re_edge.get("import_source"), dst_raw
                ),
            })
        else:
            # 'extends' and other relations: legitimate project candidates
            # without call syntax — keep with UNKNOWN context.
            pending.append({
                "src": src_id,
                "dst_symbol": dst_raw,
                "relation": rel,
                "line": line_no,
                "language": lang,
                "call_kind": "UNKNOWN",
                "receiver": None,
                "import_source": _pending_import_source(
                    re_edge.get("import_source")
                ),
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "pending": pending,
        "sha256": sha,
        "size": file_size,
        "error": raw_result.get("error"),
    }
