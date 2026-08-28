"""
sot_graph.importer.scip — SCIP Index Importer & Evidence Ingestion Engine.

Supports SCIP (Sourcegraph Code Intelligence Protocol) indices in both Protobuf
binary (.scip) and JSON (.json) formats, with zero mandatory external dependencies.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union


ROLE_DEFINITION = 0x1
ROLE_IMPORT = 0x2
ROLE_WRITE_ACCESS = 0x4
ROLE_READ_ACCESS = 0x8


# -----------------------------------------------------------------------------
# Zero-Dependency Protobuf Binary Decoder
# -----------------------------------------------------------------------------

def _decode_varint(buffer: bytes, offset: int) -> Tuple[int, int]:
    """Decode a varint from buffer starting at offset; returns (value, new_offset)."""
    value = 0
    shift = 0
    while offset < len(buffer):
        byte = buffer[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, offset
        shift += 7
        if shift > 64:
            raise ValueError("Varint overflow in protobuf decoding")
    raise ValueError("Unexpected EOF while decoding varint")


def _decode_tag(buffer: bytes, offset: int) -> Tuple[int, int, int]:
    """Decode field_number and wire_type; returns (field_number, wire_type, new_offset)."""
    tag, new_offset = _decode_varint(buffer, offset)
    field_number = tag >> 3
    wire_type = tag & 0x07
    return field_number, wire_type, new_offset


def _decode_packed_varints(payload: bytes) -> List[int]:
    """Decode a packed repeated varint field."""
    result: List[int] = []
    offset = 0
    while offset < len(payload):
        val, offset = _decode_varint(payload, offset)
        result.append(val)
    return result


def _decode_raw_message(buffer: bytes, offset: int = 0, length: Optional[int] = None) -> List[Tuple[int, int, Any]]:
    """Decode a message into a list of (field_number, wire_type, raw_value)."""
    end = len(buffer) if length is None else offset + length
    fields: List[Tuple[int, int, Any]] = []
    while offset < end:
        field_number, wire_type, offset = _decode_tag(buffer, offset)
        if wire_type == 0:  # Varint
            val, offset = _decode_varint(buffer, offset)
            fields.append((field_number, wire_type, val))
        elif wire_type == 1:  # 64-bit
            if offset + 8 > end:
                break
            val = struct.unpack("<Q", buffer[offset:offset+8])[0]
            offset += 8
            fields.append((field_number, wire_type, val))
        elif wire_type == 2:  # Length-delimited
            length_val, offset = _decode_varint(buffer, offset)
            if offset + length_val > end:
                break
            payload = buffer[offset:offset+length_val]
            offset += length_val
            fields.append((field_number, wire_type, payload))
        elif wire_type == 5:  # 32-bit
            if offset + 4 > end:
                break
            val = struct.unpack("<I", buffer[offset:offset+4])[0]
            offset += 4
            fields.append((field_number, wire_type, val))
        else:
            # Unsupported wire type or corrupt data
            break
    return fields


def _parse_scip_metadata(payload: bytes) -> Dict[str, Any]:
    """Parse SCIP Metadata message."""
    meta: Dict[str, Any] = {
        "version": 0,
        "tool_info": {"name": "unknown", "version": "unknown", "arguments": []},
        "project_root": "",
        "text_document_encoding": 1,  # 1: UTF-8, 2: UTF-16, 3: UTF-32
    }
    for field_num, wire_type, val in _decode_raw_message(payload):
        if field_num == 1 and wire_type == 0:
            meta["version"] = val
        elif field_num == 2 and wire_type == 2:
            # ToolInfo
            tool: Dict[str, Any] = {"name": "unknown", "version": "unknown", "arguments": []}
            for t_fn, t_wt, t_val in _decode_raw_message(val):
                if t_fn == 1 and t_wt == 2:
                    tool["name"] = t_val.decode("utf-8", errors="replace")
                elif t_fn == 2 and t_wt == 2:
                    tool["version"] = t_val.decode("utf-8", errors="replace")
                elif t_fn == 3 and t_wt == 2:
                    tool["arguments"].append(t_val.decode("utf-8", errors="replace"))
            meta["tool_info"] = tool
        elif field_num == 3 and wire_type == 2:
            meta["project_root"] = val.decode("utf-8", errors="replace")
        elif field_num == 4 and wire_type == 0:
            meta["text_document_encoding"] = val
    return meta


def _parse_scip_occurrence(payload: bytes) -> Dict[str, Any]:
    """Parse SCIP Occurrence message (standard or minimal format)."""
    occ: Dict[str, Any] = {
        "range": [],
        "symbol": "",
        "symbol_roles": 0,
        "override_documentation": [],
        "syntax_kind": 0,
    }
    for field_num, wire_type, val in _decode_raw_message(payload):
        if field_num == 1:
            if wire_type == 2:  # packed varints
                occ["range"] = _decode_packed_varints(val)
            elif wire_type == 0:
                occ["range"].append(val)
        elif field_num == 2 and wire_type == 2:
            occ["symbol"] = val.decode("utf-8", errors="replace")
        elif field_num == 3 and wire_type == 0:
            occ["symbol_roles"] = val
        elif field_num == 4:
            if wire_type == 2:
                occ["override_documentation"].append(val.decode("utf-8", errors="replace"))
            elif wire_type == 0:
                occ["syntax_kind"] = val
        elif field_num == 5 and wire_type == 0:
            occ["syntax_kind"] = val
        elif field_num == 8 and wire_type == 2:
            # Minimal single_line_range message: line=1, start_col=2, end_col=3
            r_fields = {}
            for r_fn, _, r_val in _decode_raw_message(val):
                r_fields[r_fn] = r_val
            if 1 in r_fields and 2 in r_fields and 3 in r_fields:
                occ["range"] = [r_fields[1], r_fields[2], r_fields[3]]
        elif field_num == 9 and wire_type == 2:
            # Minimal multi_line_range message: start_line=1, start_col=2, end_line=3, end_col=4
            r_fields = {}
            for r_fn, _, r_val in _decode_raw_message(val):
                r_fields[r_fn] = r_val
            if 1 in r_fields and 2 in r_fields and 3 in r_fields and 4 in r_fields:
                occ["range"] = [r_fields[1], r_fields[2], r_fields[3], r_fields[4]]
    return occ


def _parse_scip_relationship(payload: bytes) -> Dict[str, Any]:
    """Parse SCIP Relationship message."""
    rel: Dict[str, Any] = {
        "symbol": "",
        "is_reference": False,
        "is_implementation": False,
        "is_type_definition": False,
        "is_definition": False,
    }
    for field_num, wire_type, val in _decode_raw_message(payload):
        if field_num == 1 and wire_type == 2:
            rel["symbol"] = val.decode("utf-8", errors="replace")
        elif field_num == 2 and wire_type == 0:
            rel["is_reference"] = bool(val)
        elif field_num == 3 and wire_type == 0:
            rel["is_implementation"] = bool(val)
        elif field_num == 4 and wire_type == 0:
            rel["is_type_definition"] = bool(val)
        elif field_num == 5 and wire_type == 0:
            rel["is_definition"] = bool(val)
    return rel


def _parse_scip_symbol_info(payload: bytes) -> Dict[str, Any]:
    """Parse SCIP SymbolInformation message."""
    sym_info: Dict[str, Any] = {
        "symbol": "",
        "documentation": [],
        "relationships": [],
        "kind": 0,
        "display_name": "",
    }
    for field_num, wire_type, val in _decode_raw_message(payload):
        if field_num == 1 and wire_type == 2:
            sym_info["symbol"] = val.decode("utf-8", errors="replace")
        elif field_num == 2 and wire_type == 2:
            sym_info["documentation"].append(val.decode("utf-8", errors="replace"))
        elif field_num == 3 and wire_type == 2:
            # Could be documentation string or relationship message
            try:
                # Check if it decodes as UTF-8 text documentation
                text = val.decode("utf-8")
                sym_info["documentation"].append(text)
            except Exception:
                sym_info["relationships"].append(_parse_scip_relationship(val))
        elif field_num == 4:
            if wire_type == 2:
                sym_info["relationships"].append(_parse_scip_relationship(val))
            elif wire_type == 0:
                sym_info["kind"] = val
        elif field_num == 5 and wire_type == 2:
            sym_info["display_name"] = val.decode("utf-8", errors="replace")
    return sym_info


def _parse_scip_document(payload: bytes) -> Dict[str, Any]:
    """Parse SCIP Document message."""
    doc: Dict[str, Any] = {
        "language": "",
        "relative_path": "",
        "occurrences": [],
        "symbols": [],
        "text": "",
        "position_encoding": None,
    }
    for field_num, wire_type, val in _decode_raw_message(payload):
        if field_num == 1 and wire_type == 2:
            # In standard SCIP and minimal format: field 1 is relative_path
            doc["relative_path"] = val.decode("utf-8", errors="replace")
        elif field_num == 2 and wire_type == 2:
            # In standard SCIP / minimal: field 2 is occurrences (repeated)
            doc["occurrences"].append(_parse_scip_occurrence(val))
        elif field_num == 3 and wire_type == 2:
            # In standard SCIP / minimal: field 3 is symbols (repeated)
            doc["symbols"].append(_parse_scip_symbol_info(val))
        elif field_num == 4 and wire_type == 2:
            doc["language"] = val.decode("utf-8", errors="replace")
        elif field_num == 5 and wire_type == 2:
            doc["text"] = val.decode("utf-8", errors="replace")
        elif field_num == 6 and wire_type == 0:
            doc["position_encoding"] = val
    return doc

def parse_scip_protobuf(data: bytes) -> Dict[str, Any]:
    """Parse a SCIP Index protobuf binary payload."""
    index: Dict[str, Any] = {
        "metadata": {
            "version": 0,
            "tool_info": {"name": "unknown", "version": "unknown", "arguments": []},
            "project_root": "",
            "text_document_encoding": 1,
        },
        "documents": [],
    }
    for field_num, wire_type, val in _decode_raw_message(data):
        if field_num == 1 and wire_type == 2:
            index["metadata"] = _parse_scip_metadata(val)
        elif field_num == 2 and wire_type == 2:
            index["documents"].append(_parse_scip_document(val))
    return index


# -----------------------------------------------------------------------------
# SCIP JSON Parser & Normalizer
# -----------------------------------------------------------------------------

def parse_scip_json(data: Union[str, bytes, Dict[str, Any]]) -> Dict[str, Any]:
    """Parse and normalize a SCIP Index in JSON format (supports camelCase & snake_case)."""
    raw: Dict[str, Any]
    if isinstance(data, (str, bytes)):
        raw = json.loads(data)
    elif isinstance(data, dict):
        raw = data
    else:
        raise ValueError(f"Unsupported SCIP JSON data type: {type(data)}")

    meta_raw = raw.get("metadata", {})
    tool_raw = meta_raw.get("tool_info") or meta_raw.get("toolInfo", {})
    metadata = {
        "version": meta_raw.get("version", 0),
        "tool_info": {
            "name": tool_raw.get("name", "unknown"),
            "version": tool_raw.get("version", "unknown"),
            "arguments": tool_raw.get("arguments", []),
        },
        "project_root": meta_raw.get("project_root") or meta_raw.get("projectRoot", ""),
        "text_document_encoding": meta_raw.get("text_document_encoding") or meta_raw.get("textDocumentEncoding", 1),
    }

    documents: List[Dict[str, Any]] = []
    for d in raw.get("documents", []):
        rel_path = d.get("relative_path") or d.get("relativePath", "")
        lang = d.get("language", "")
        occurrences: List[Dict[str, Any]] = []
        for occ in d.get("occurrences", []):
            occurrences.append({
                "range": occ.get("range", []),
                "symbol": occ.get("symbol", ""),
                "symbol_roles": occ.get("symbol_roles") or occ.get("symbolRoles", 0),
                "override_documentation": occ.get("override_documentation") or occ.get("overrideDocumentation", []),
                "syntax_kind": occ.get("syntax_kind") or occ.get("syntaxKind", 0),
            })
        symbols: List[Dict[str, Any]] = []
        for sym in d.get("symbols", []):
            relationships = []
            for rel in sym.get("relationships", []):
                relationships.append({
                    "symbol": rel.get("symbol", ""),
                    "is_reference": rel.get("is_reference") or rel.get("isReference", False),
                    "is_implementation": rel.get("is_implementation") or rel.get("isImplementation", False),
                    "is_type_definition": rel.get("is_type_definition") or rel.get("isTypeDefinition", False),
                    "is_definition": rel.get("is_definition") or rel.get("isDefinition", False),
                })
            symbols.append({
                "symbol": sym.get("symbol", ""),
                "documentation": sym.get("documentation", []),
                "relationships": relationships,
                "kind": sym.get("kind", 0),
                "display_name": sym.get("display_name") or sym.get("displayName", ""),
            })
        doc_entry = {
            "language": lang,
            "relative_path": rel_path,
            "occurrences": occurrences,
            "symbols": symbols,
            "text": d.get("text", ""),
        }
        pos_enc = d.get("position_encoding") or d.get("positionEncoding")
        if pos_enc is not None:
            doc_entry["position_encoding"] = pos_enc
        documents.append(doc_entry)

    return {
        "metadata": metadata,
        "documents": documents,
    }


# -----------------------------------------------------------------------------
# Position Encoding & Symbol Descriptors
# -----------------------------------------------------------------------------

def translate_scip_range(
    range_ints: Sequence[int],
    encoding: Union[int, str] = 1,
    source_text: Optional[str] = None,
) -> Dict[str, Optional[int]]:
    """Translate SCIP range integer sequence to 1-based line and 0-based column.
    
    SCIP 3-tuple: [line, start_col, end_col] (0-based)
    SCIP 4-tuple: [start_line, start_col, end_line, end_col] (0-based)
    """
    if len(range_ints) == 3:
        line, start_col, end_col = range_ints
        line_start = line + 1
        line_end = line + 1
        col_start = start_col
        col_end = end_col
    elif len(range_ints) >= 4:
        start_line, start_col, end_line, end_col = range_ints[:4]
        line_start = start_line + 1
        line_end = end_line + 1
        col_start = start_col
        col_end = end_col
    else:
        return {
            "line_start": None,
            "line_end": None,
            "col_start": None,
            "col_end": None,
        }

    # UTF-16 code units adjustment if source text is available
    is_utf16 = (encoding == 2 or str(encoding).upper().replace("-", "") in ("2", "UTF16"))
    if is_utf16 and source_text is not None:
        try:
            lines = source_text.splitlines()
            if 0 <= line_start - 1 < len(lines) and col_start is not None:
                line_str = lines[line_start - 1]
                utf16_bytes = line_str.encode("utf-16le")
                col_start = len(utf16_bytes[:col_start * 2].decode("utf-16le", errors="ignore"))
            if 0 <= line_end - 1 < len(lines) and col_end is not None:
                end_line_str = lines[line_end - 1]
                utf16_bytes_end = end_line_str.encode("utf-16le")
                col_end = len(utf16_bytes_end[:col_end * 2].decode("utf-16le", errors="ignore"))
        except Exception:
            pass

    return {
        "line_start": line_start,
        "line_end": line_end,
        "col_start": col_start,
        "col_end": col_end,
    }


def _split_scip_spaces(s: str) -> List[str]:
    """Split SCIP symbol by spaces while respecting backtick escapes."""
    parts: List[str] = []
    current: List[str] = []
    in_backtick = False
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == '`':
            if in_backtick and i + 1 < n and s[i+1] == '`':
                current.append('``')
                i += 2
                continue
            in_backtick = not in_backtick
            current.append(c)
            i += 1
        elif c == ' ' and not in_backtick:
            if current:
                parts.append("".join(current))
                current = []
            i += 1
        else:
            current.append(c)
            i += 1
    if current:
        parts.append("".join(current))
    return parts


def _unescape_scip_ident(ident: str) -> str:
    """Unescape backticks from an identifier."""
    if ident.startswith('`') and ident.endswith('`') and len(ident) >= 2:
        inner = ident[1:-1]
        return inner.replace('``', '`')
    return ident


def _parse_descriptors(descriptors_str: str) -> List[str]:
    """Parse SCIP descriptors into individual descriptor chunks."""
    chunks: List[str] = []
    current: List[str] = []
    in_backtick = False
    i = 0
    n = len(descriptors_str)
    while i < n:
        c = descriptors_str[i]
        if c == '`':
            if in_backtick and i + 1 < n and descriptors_str[i+1] == '`':
                current.append('``')
                i += 2
                continue
            in_backtick = not in_backtick
            current.append(c)
            i += 1
        elif in_backtick:
            current.append(c)
            i += 1
        else:
            current.append(c)
            if c in ('/', '#'):
                chunks.append("".join(current))
                current = []
            elif c == '.':
                curr_str = "".join(current)
                if curr_str.endswith("().") or curr_str.endswith(").") or curr_str.endswith("].") or curr_str.endswith("."):
                    chunks.append(curr_str)
                    current = []
            elif c == ':':
                curr_str = "".join(current)
                if curr_str.endswith("():") or curr_str.endswith("):"):
                    chunks.append(curr_str)
                    current = []
            elif c in (']', ')'):
                if i + 1 < n and descriptors_str[i+1] in ('.', ':'):
                    pass
                else:
                    chunks.append("".join(current))
                    current = []
            i += 1
    if current:
        chunks.append("".join(current))
    return chunks


_DESCRIPTOR_SUFFIX_RE = re.compile(r'(\(\)\.|\(\)\:|\#|\.|\/|\(.*?\)|\[.*?\])$')

def parse_scip_symbol(symbol_str: str) -> Dict[str, Any]:
    """Parse a SCIP symbol string into component parts and bare identifier.
    
    Format: <scheme> ' ' <package_manager> ' ' <package_name> ' ' <version> ' ' <descriptors>
    Example: 'scip-python python package 0.1.0 core/service/PaymentProcessor#process_charge().'
    Example: 'sot-graph python /root pkg/core/math_ops.py math_ops.add().'
    Example: 'scip-typescript npm @types/node 18.0.0 fs/readFileSync().'
    Example: 'local 1'
    """
    result: Dict[str, Any] = {
        "raw": symbol_str,
        "scheme": "",
        "manager": "",
        "package_manager": "",
        "package": "",
        "package_name": "",
        "version": "",
        "descriptors": "",
        "name": "",
        "bare_name": "",
        "kind": "symbol",
        "parent": None,
        "fqn": "",
        "is_local": symbol_str.startswith("local "),
    }
    if not symbol_str or result["is_local"]:
        result["name"] = symbol_str
        result["bare_name"] = symbol_str
        return result

    parts = _split_scip_spaces(symbol_str)
    if len(parts) >= 5:
        result["scheme"] = parts[0]
        result["manager"] = _unescape_scip_ident(parts[1])
        result["package_manager"] = result["manager"]
        result["package"] = _unescape_scip_ident(parts[2])
        result["package_name"] = result["package"]
        result["version"] = _unescape_scip_ident(parts[3])
        result["descriptors"] = " ".join(parts[4:])
    elif len(parts) == 4:
        result["scheme"] = parts[0]
        result["manager"] = _unescape_scip_ident(parts[1])
        result["package_manager"] = result["manager"]
        result["package"] = _unescape_scip_ident(parts[2])
        result["package_name"] = result["package"]
        result["version"] = _unescape_scip_ident(parts[3])
        result["descriptors"] = parts[3]
    else:
        result["descriptors"] = symbol_str

    descriptors = result["descriptors"]
    chunks = _parse_descriptors(descriptors)
    if not chunks:
        result["name"] = symbol_str
        result["bare_name"] = symbol_str
        return result

    last_chunk = chunks[-1]

    # Determine kind
    if last_chunk.endswith("().") or last_chunk.endswith("():") or "()" in last_chunk:
        result["kind"] = "method"
    elif last_chunk.endswith("#"):
        result["kind"] = "class"
    elif last_chunk.endswith("/"):
        result["kind"] = "package"
    elif last_chunk.endswith("."):
        result["kind"] = "field"

    # Extract parent from previous chunk if available
    if len(chunks) >= 2:
        prev_chunk = chunks[-2]
        prev_clean = _DESCRIPTOR_SUFFIX_RE.sub('', prev_chunk)
        result["parent"] = _unescape_scip_ident(prev_clean)

    clean_chunks = []
    for c in chunks:
        clean = _DESCRIPTOR_SUFFIX_RE.sub('', c)
        clean_chunks.append(_unescape_scip_ident(clean))

    bare_name = clean_chunks[-1] if clean_chunks else last_chunk
    result["name"] = bare_name
    result["bare_name"] = bare_name
    result["fqn"] = ".".join(clean_chunks)

    return result


# -----------------------------------------------------------------------------
# SCIP Importer Engine
# -----------------------------------------------------------------------------

class ScipImporter:
    """Imports SCIP indices into the SOT-Graph Multi-Provider Evidence Storage."""

    def __init__(self, db: Any, project_root: Optional[str] = None) -> None:
        self.db = db
        self.project_root = project_root or getattr(db, "project_root", None) or os.getcwd()

    def parse_index(self, index_input: Union[str, bytes, Dict[str, Any]]) -> Dict[str, Any]:
        """Parse raw index data from bytes, string path/content, or dict."""
        if isinstance(index_input, dict):
            return parse_scip_json(index_input)
        if isinstance(index_input, bytes):
            # Try JSON parsing if it starts with { or [ and parses cleanly as UTF-8 JSON
            stripped = index_input.strip()
            if stripped.startswith(b"{") or stripped.startswith(b"["):
                try:
                    return parse_scip_json(index_input)
                except Exception:
                    pass
            return parse_scip_protobuf(index_input)
        if isinstance(index_input, str):
            # File path or JSON string
            if os.path.isfile(index_input):
                with open(index_input, "rb") as f:
                    content = f.read()
                return self.parse_index(content)
            elif index_input.strip().startswith("{"):
                return parse_scip_json(index_input)
            else:
                raise FileNotFoundError(f"SCIP index file not found: {index_input}")
        raise ValueError(f"Invalid index input type: {type(index_input)}")

    def import_index(
        self,
        index_input: Union[str, bytes, Dict[str, Any]],
        provider_name: Optional[str] = None,
        provider_version: Optional[str] = None,
        run_id: Optional[str] = None,
        project_root: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Import a SCIP index into database provider_evidence and update graph mappings."""
        started_at = time.monotonic()
        index = self.parse_index(index_input)
        metadata = index.get("metadata", {})
        tool_info = metadata.get("tool_info", {})
        
        prov_name = provider_name or tool_info.get("name") or "scip-importer"
        prov_ver = provider_version or tool_info.get("version") or "1.0.0"
        proj_root = project_root or metadata.get("project_root") or self.project_root
        text_encoding = metadata.get("text_document_encoding", 1)
        encoding_str = "UTF-8" if text_encoding == 1 else ("UTF-16" if text_encoding == 2 else "UTF-32")


        evidence_items: List[Dict[str, Any]] = []
        occurrences_count = 0
        definitions_count = 0
        references_count = 0
        relationships_count = 0
        documents = index.get("documents", [])

        sym_doc_map = {}
        for doc in documents:
            for sym in doc.get("symbols", []):
                s_name = sym.get("symbol")
                if s_name and sym.get("documentation"):
                    sym_doc_map[s_name] = "\n".join(sym.get("documentation", []))

        for doc in documents:
            rel_path = doc.get("relative_path", "")
            if not rel_path:
                continue
            # Normalize path
            norm_path = rel_path.replace("\\", "/")
            doc_text = doc.get("text")
            doc_pos_enc = doc.get("position_encoding")
            doc_encoding = doc_pos_enc if doc_pos_enc is not None else text_encoding

            # Pre-pass: collect all definition spans in this document to attribute enclosing caller symbols
            def_spans: List[Dict[str, Any]] = []
            for occ in doc.get("occurrences", []):
                roles = occ.get("symbol_roles", 0)
                if roles & ROLE_DEFINITION:
                    symbol_raw = occ.get("symbol", "")
                    if symbol_raw:
                        sym_info = parse_scip_symbol(symbol_raw)
                        range_ints = occ.get("range", [])
                        sp = translate_scip_range(range_ints, encoding=doc_encoding, source_text=doc_text)
                        def_spans.append({
                            "symbol_raw": symbol_raw,
                            "bare_name": sym_info["bare_name"],
                            "fqn": sym_info.get("fqn") or sym_info["bare_name"],
                            "line_start": sp["line_start"],
                            "line_end": sp["line_end"],
                            "col_start": sp["col_start"],
                            "col_end": sp["col_end"],
                        })

            # Sort def_spans by line_start
            def_spans.sort(key=lambda x: (x["line_start"] or 0, x["col_start"] or 0))

            # 1. Process Occurrences
            for occ in doc.get("occurrences", []):
                occurrences_count += 1
                symbol_raw = occ.get("symbol", "")
                if not symbol_raw:
                    continue
                roles = occ.get("symbol_roles", 0)
                range_ints = occ.get("range", [])
                spans = translate_scip_range(range_ints, encoding=doc_encoding, source_text=doc_text)
                sym_info = parse_scip_symbol(symbol_raw)
                bare_symbol = sym_info["bare_name"]
                fqn_symbol = sym_info.get("fqn") or bare_symbol

                is_def = bool(roles & ROLE_DEFINITION)
                is_imp = bool(roles & ROLE_IMPORT)

                if is_def:
                    definitions_count += 1
                    relation = "defines"
                    src_sym = fqn_symbol
                    src_bare = bare_symbol
                    dst_sym = None
                    dst_bare = None
                elif is_imp:
                    relation = "imports"
                    src_sym = norm_path
                    src_bare = norm_path
                    dst_sym = fqn_symbol
                    dst_bare = bare_symbol
                else:
                    references_count += 1
                    # P3.2 invariant: a plain occurrence is a REFERENCE,
                    # never a call — no relation upgrade happens here.
                    relation = "references"
                    # Determine enclosing symbol if the reference occurs within a definition span
                    enclosing_sym = norm_path
                    enclosing_bare = norm_path
                    occ_line = spans["line_start"]
                    if occ_line:
                        # Find the closest preceding definition (or exact range enclosing if line_end is set)
                        candidates = [
                            d for d in def_spans
                            if d["line_start"] and d["line_start"] <= occ_line and (d["line_end"] is None or d["line_end"] >= occ_line or d["line_end"] == d["line_start"])
                        ]
                        if candidates:
                            enclosing_sym = candidates[-1]["fqn"]
                            enclosing_bare = candidates[-1]["bare_name"]
                    src_sym = enclosing_sym
                    src_bare = enclosing_bare
                    dst_sym = fqn_symbol
                    dst_bare = bare_symbol

                override_doc = occ.get("override_documentation")
                occ_doc = "\n".join(override_doc) if override_doc else sym_doc_map.get(symbol_raw)
                s_kind = str(occ.get("syntax_kind", 0))

                evidence_items.append({
                    "path": norm_path,
                    "symbol": src_bare,
                    "src_symbol": src_sym,
                    "target_symbol": dst_bare,
                    "dst_symbol": dst_sym,
                    "relation": relation,
                    "line_start": spans["line_start"],
                    "line_end": spans["line_end"],
                    "col_start": spans["col_start"],
                    "col_end": spans["col_end"],
                    "syntax_kind": s_kind,
                    "documentation": occ_doc,
                    "confidence": 1.0,
                    "metadata_json": {
                        "scip_symbol": symbol_raw,
                        "symbol_roles": roles,
                        "syntax_kind": occ.get("syntax_kind", 0),
                        "fqn": sym_info.get("fqn"),
                        "bare_name": bare_symbol,
                    },
                })
            for sym in doc.get("symbols", []):
                sym_raw = sym.get("symbol", "")
                if not sym_raw:
                    continue
                sym_parsed = parse_scip_symbol(sym_raw)
                src_bare = sym_parsed["bare_name"]
                src_fqn = sym_parsed.get("fqn") or src_bare
                sym_kind = str(sym.get("kind", 0))
                sym_doc = "\n".join(sym.get("documentation", [])) if sym.get("documentation") else None

                for rel in sym.get("relationships", []):
                    relationships_count += 1
                    target_raw = rel.get("symbol", "")
                    target_parsed = parse_scip_symbol(target_raw)
                    target_bare = target_parsed["bare_name"]
                    target_fqn = target_parsed.get("fqn") or target_bare

                    if rel.get("is_implementation"):
                        rel_type = "implements"
                    elif rel.get("is_definition"):
                        rel_type = "defines"
                    elif rel.get("is_type_definition"):
                        rel_type = "type_of"
                    else:
                        rel_type = "references"

                    evidence_items.append({
                        "path": norm_path,
                        "symbol": src_bare,
                        "src_symbol": src_fqn,
                        "target_symbol": target_bare,
                        "dst_symbol": target_fqn,
                        "relation": rel_type,
                        "line_start": None,
                        "line_end": None,
                        "col_start": None,
                        "col_end": None,
                        "syntax_kind": sym_kind,
                        "documentation": sym_doc,
                        "confidence": 1.0,
                        "metadata_json": {
                            "scip_src_symbol": sym_raw,
                            "scip_target_symbol": target_raw,
                            "src_fqn": src_fqn,
                            "target_fqn": target_fqn,
                            "relationship": rel,
                        },
                    })

        # P3.2 snapshot binding: tie this run to the reconciler's file
        # journal. journal_bound means every indexed document matched a
        # journal row; manifest_digest pins the (path, sha256) set; stale
        # files (index text or disk state disagreeing with the journal)
        # get their evidence invalidated immediately — never silently kept.
        doc_paths: List[str] = []
        doc_texts: Dict[str, Optional[str]] = {}
        for doc in documents:
            rel = (doc.get("relative_path") or "").replace("\\", "/")
            if rel:
                doc_paths.append(rel)
                doc_texts[rel] = doc.get("text")
        journal_hashes: Dict[str, str] = {}
        stale_files: List[str] = []
        for rel in doc_paths:
            try:
                journal = self.db.get_file_journal(rel)
            except Exception:
                journal = None
            if journal is None:
                continue
            journal_hashes[rel] = journal["sha256"]
            text = doc_texts.get(rel)
            if isinstance(text, str):
                doc_sha = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
                if doc_sha != journal["sha256"] and rel not in stale_files:
                    stale_files.append(rel)
        try:
            for drifted in self.db.stale_journal_files(doc_paths, proj_root):
                if drifted not in stale_files:
                    stale_files.append(drifted)
        except Exception:
            pass
        if journal_hashes:
            manifest = json.dumps(
                sorted(journal_hashes.items()), separators=(",", ":"), sort_keys=True
            )
            manifest_digest = "manifest:" + hashlib.sha256(
                manifest.encode("utf-8")
            ).hexdigest()
        else:
            manifest_digest = None
        journal_bound = bool(journal_hashes)
        # Bind the run to the journal manifest when available; the bare
        # generation fallback only applies when no doc matched the journal.
        snapshot_hash = manifest_digest
        if snapshot_hash is None:
            try:
                row = self.db.conn.execute("SELECT MAX(generation) FROM file_journal").fetchone()
                if row and row[0]:
                    snapshot_hash = f"gen_{row[0]}"
            except Exception:
                snapshot_hash = None

        stale_marked = 0
        run_kwargs: Dict[str, Any] = dict(
            provider_name=prov_name,
            provider_version=prov_ver,
            capability="COMPILER_INDEXED_SYMBOLS",
            snapshot_hash=snapshot_hash,
            project_root=proj_root,
            position_encoding=encoding_str,
            arguments_json=json.dumps(tool_info.get("arguments", [])),
            run_id=run_id,
        )
        with self.db.write_lock():
            rid = self.db.record_provider_outcome(
                run_kwargs, None, evidence_items
            )
            recorded = len(self.db.get_provider_evidence(run_id=rid))
        if stale_files:
            stale_marked = self.db.mark_evidence_stale(
                stale_files,
                reason="scip index stale: indexed content differs from file_journal",
            )
        duration_ms = int((time.monotonic() - started_at) * 1000)
        return {
            "run_id": rid,
            "provider_name": prov_name,
            "provider_version": prov_ver,
            "documents_count": len(documents),
            "occurrences_count": occurrences_count,
            "definitions_count": definitions_count,
            "references_count": references_count,
            "relationships_count": relationships_count,
            "evidence_recorded": recorded,
            "journal_bound": journal_bound,
            "manifest_digest": manifest_digest,
            "stale_files": stale_files,
            "stale_marked": stale_marked,
            "duration_ms": duration_ms,
        }

    def import_file(
        self,
        file_path: str,
        provider_name: Optional[str] = None,
        provider_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Convenience method to import from a file path."""
        return self.import_index(
            file_path,
            provider_name=provider_name,
            provider_version=provider_version,
        )


__all__ = [
    "ScipImporter",
    "parse_scip_protobuf",
    "parse_scip_json",
    "parse_scip_symbol",
    "translate_scip_range",
]
