"""Minimal SCIP (Sourcegraph Code Intelligence Protocol) export, zero-dep.

Hand-rolled protobuf wire-format writer for the subset of scip.proto we
emit: Index{metadata, documents} with symbol definitions, call/import
reference occurrences and extends/implements relationships. Field numbers
verified against sourcegraph/scip ``scip.proto``. The internal storage
stays SQLite — SCIP is purely an interop bridge for editors/Sourcegraph.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROLE_DEFINITION = 0x1
ROLE_IMPORT = 0x2

_LANGUAGES = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript", ".dart": "dart",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift",
}
_TYPE_KINDS = {"class", "interface", "struct", "type", "enum", "trait"}


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _tag(field: int, wire_type: int) -> bytes:
    return _varint((field << 3) | wire_type)


def _string(field: int, text: str) -> bytes:
    payload = text.encode("utf-8")
    return _tag(field, 2) + _varint(len(payload)) + payload


def _message(field: int, payload: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(payload)) + payload


def _varint_field(field: int, value: int) -> bytes:
    return _tag(field, 0) + _varint(value)


def _tool_version() -> str:
    try:
        import importlib.metadata

        return importlib.metadata.version("sot-graph")
    except Exception:
        return "dev"


def scip_symbol(language: str, project_root: str, rel_path: str,
                module: str, symbol: str, kind: str) -> str:
    """SCIP symbol string: scheme language root path `package`.descriptor."""
    suffix = f"{symbol}#" if kind in _TYPE_KINDS else f"{symbol}()"
    package = f"`{module or 'package'}`."
    return f"sot-graph {language} {project_root} {rel_path} {package}{suffix}"


def _single_line_range(line: int, start: int, end: int) -> bytes:
    # SingleLineRange: line=1, start_character=2, end_character=3 (0-based).
    return (_varint_field(1, line) + _varint_field(2, start)
            + _varint_field(3, max(end, start + 1)))


def _multi_line_range(start_line: int, start_char: int, end_line: int, end_char: int) -> bytes:
    # MultiLineRange: start_line=1, start_character=2, end_line=3, end_character=4.
    return (_varint_field(1, start_line) + _varint_field(2, start_char)
            + _varint_field(3, end_line) + _varint_field(4, end_char))


def build_scip_index(db, project_root: str) -> bytes:
    """Serialize the graph (nodes + non-defines edges) into SCIP bytes."""
    root_uri = f"file://{os.path.abspath(project_root)}"
    documents: Dict[str, Dict[str, Any]] = {}
    sym_strings: Dict[str, str] = {}
    node_doc: Dict[str, str] = {}

    rows = db.conn.execute(
        "SELECT id, path, kind, symbol, fqn, body, line_start, line_end, "
        "col_start, col_end FROM graph_nodes "
        "WHERE kind NOT IN ('file', 'note', 'markdown') AND path != ''"
    ).fetchall()
    for node_id, path, kind, symbol, fqn, body, line_start, line_end, col_start, col_end in rows:
        rel = os.path.relpath(path, project_root) if os.path.isabs(path) else path
        ext = os.path.splitext(rel)[1].lower()
        language = _LANGUAGES.get(ext, "unknown")
        module = (fqn or "").rsplit(".", 1)[0] if fqn and "." in (fqn or "") else os.path.splitext(rel)[0].replace(os.sep, ".")
        sym = scip_symbol(language, root_uri, rel, module, symbol or node_id, kind)
        sym_strings[node_id] = sym
        node_doc[node_id] = rel
        doc = documents.setdefault(rel, {"symbols": {}, "occurrences": [], "order": []})
        if node_id not in doc["symbols"]:
            doc["symbols"][node_id] = {"symbol": sym, "doc": (body or "")[:512], "rels": []}
            doc["order"].append(node_id)

        line0 = max(0, (line_start or 1) - 1)
        end_line0 = max(0, (line_end or line_start or 1) - 1)
        start_char = col_start or 0
        name_len = len((symbol or node_id).rsplit(".", 1)[-1])
        end_char = col_end or (start_char + name_len)
        if end_line0 > line0:
            rng = _message(9, _multi_line_range(line0, start_char, end_line0, end_char))
        else:
            rng = _message(8, _single_line_range(line0, start_char, end_char))
        doc["occurrences"].append(
            rng + _string(2, sym) + _varint_field(3, ROLE_DEFINITION))

    for src, dst, relation, line in db.conn.execute(
        "SELECT src, dst, relation, line FROM graph_edges WHERE relation != 'defines'"
    ):
        if src not in sym_strings or dst not in sym_strings:
            continue
        rel_doc = documents.get(node_doc[src])
        if rel_doc is None:
            continue
        # Relationship inside the caller's SymbolInformation (field 4).
        rel_msg = _string(1, sym_strings[dst])
        if relation in ("extends", "implements"):
            rel_msg += _varint_field(3, 1)  # is_implementation
        else:
            rel_msg += _varint_field(2, 1)  # is_reference
        entry = rel_doc["symbols"].get(src)
        if entry is not None:
            entry["rels"].append(_message(4, rel_msg))
        # Reference occurrence at the edge site.
        line0 = max(0, (line or 1) - 1)
        roles = ROLE_IMPORT if relation == "imports" else 0
        rel_doc["occurrences"].append(
            _message(8, _single_line_range(line0, 0, 1))
            + _string(2, sym_strings[dst]) + _varint_field(3, roles))

    tool_info = _string(1, "sot-graph") + _string(2, _tool_version())
    metadata = (_message(2, tool_info) + _string(3, root_uri)
                + _varint_field(4, 1))  # TextEncoding.UTF8

    index = _message(1, metadata)
    for rel in sorted(documents):
        doc = documents[rel]
        doc_msg = _string(1, rel)
        for occ in doc["occurrences"]:
            doc_msg += _message(2, occ)
        for node_id in doc["order"]:
            entry = doc["symbols"][node_id]
            sym_info = _string(1, entry["symbol"])
            if entry["doc"]:
                sym_info += _string(3, entry["doc"])
            sym_info += b"".join(entry["rels"])
            doc_msg += _message(3, sym_info)
        index += _message(2, doc_msg)
    return index


def export_scip(db, project_root: str, output_path: str) -> int:
    """Write the SCIP index; returns bytes written."""
    payload = build_scip_index(db, project_root)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return len(payload)


__all__ = ["build_scip_index", "export_scip", "scip_symbol"]
