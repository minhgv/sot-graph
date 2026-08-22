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
from sot_graph.modutil import dotted_module, normalize_import

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
    ".dart": "extract_dart",
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
    ".dart": "dart",
    ".arb": "json",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sh": "shell",
    ".sql": "sql",
}


def get_language(path: str) -> str:
    ext = Path(path).suffix.lower()
    return LANGUAGE_MAP.get(ext, "text")


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

    # 1. Base File Node
    file_node = {
        "id": file_node_id,
        "kind": "file",
        "symbol": p.name,
        "fqn": module,
        "label": f"File: {rel_path}",
        "body": f"File {rel_path} ({lang}, {file_size} bytes)",
        "keywords": [p.name, lang, "file"],
        "line_start": 1,
    }

    if not fn_name:
        # Non-code or non-AST file (Markdown, configs, scripts)
        preview = content_bytes[:400].decode("utf-8", errors="replace")
        file_node["body"] = f"File {rel_path} ({lang})\nPreview:\n{preview}"
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
        loc = str(rn.get("source_location", ""))
        m = re.search(r"L(\d+)", loc)
        if m:
            line_no = int(m.group(1))

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
            "keywords": [raw_id, kind, lang, p.name],
            "line_start": line_no,
            "line_end": rn.get("line_end"),
            "col_start": rn.get("col_start"),
            "col_end": rn.get("col_end"),
        })

    # Intra-file vs Cross-file edges
    for re_edge in raw_edges:
        src_raw = re_edge.get("source")
        dst_raw = re_edge.get("target")
        rel = re_edge.get("relation", "uses")
        if not src_raw or not dst_raw:
            continue

        src_id = symbol_to_node_id.get(src_raw, file_node_id)
        loc = str(re_edge.get("source_location", ""))
        line_no = int(re.search(r"L(\d+)", loc).group(1)) if re.search(r"L(\d+)", loc) else None

        if dst_raw in symbol_to_node_id:
            # Resolved intra-file edge
            edges.append({
                "src": src_id,
                "dst": symbol_to_node_id[dst_raw],
                "relation": rel,
                "line": line_no,
            })
            continue

        # Cross-file pending edge (target symbol lives in another file)
        if rel == "calls":
            call_kind = re_edge.get("call_kind") or "UNKNOWN"
            # Audit contract: only unshadowed BARE builtins may be pruned.
            # Attribute/qualified calls (requests.get, db.execute) always
            # survive with their receiver context for the resolver.
            if call_kind == "BARE" and re_edge.get("builtin"):
                continue
            pending.append({
                "src": src_id,
                "dst_symbol": dst_raw,
                "relation": rel,
                "line": line_no,
                "language": lang,
                "call_kind": call_kind,
                "receiver": re_edge.get("receiver"),
                "import_source": normalize_import(re_edge.get("import_source")) or None,
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
                "import_source": normalize_import(
                    re_edge.get("import_source") or dst_raw
                ) or None,
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
                "import_source": normalize_import(re_edge.get("import_source")) or None,
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "pending": pending,
        "sha256": sha,
        "size": file_size,
        "error": raw_result.get("error"),
    }
