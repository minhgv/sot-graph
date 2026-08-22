"""Optional tree-sitter AST extractors for Go/Rust/Java/Kotlin/Swift.

Installed via the ``[tree-sitter]`` extra. The zero-dependency core keeps
the vendored regex fallbacks; when a grammar is importable these
extractors return real AST nodes/edges in the exact raw shape graphify
produces, so binding resolution, pending edges, pack and usages work
unchanged downstream.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CONFIGS: Dict[str, Dict[str, Any]] = {
    "go": {
        "module": "tree_sitter_go",
        "defs": {
            "function_declaration": ("name", "function"),
            "method_declaration": ("name", "method"),
            "type_spec": ("name", "class"),
        },
        "method_receiver": "receiver",
        "calls": {"type": "call_expression", "field": "function"},
        "imports": [r'\bimport\s+(?:[\w./]+\s+)?"([^"]+)"'],
    },
    "rust": {
        "module": "tree_sitter_rust",
        "defs": {
            "function_item": ("name", "function"),
            "struct_item": ("name", "class"),
            "enum_item": ("name", "class"),
            "trait_item": ("name", "class"),
        },
        "calls": {"type": "call_expression", "field": "function"},
        "imports": [r"\buse\s+([^;]+);"],
    },
    "java": {
        "module": "tree_sitter_java",
        "defs": {
            "class_declaration": ("name", "class"),
            "interface_declaration": ("name", "class"),
            "enum_declaration": ("name", "class"),
            "record_declaration": ("name", "class"),
            "method_declaration": ("name", "method"),
        },
        "calls": {"type": "method_invocation", "field": "name", "receiver_field": "object"},
        "imports": [r"\bimport\s+(?:static\s+)?([\w.]+)\s*;"],
    },
    "kotlin": {
        "module": "tree_sitter_kotlin",
        "defs": {
            "class_declaration": ("name", "class"),
            "object_declaration": ("name", "class"),
            "function_declaration": ("name", "function"),
        },
        "calls": {"type": "call_expression", "field": None},
        "imports": [r"\bimport\s+([\w.]+)"],
    },
    "swift": {
        "module": "tree_sitter_swift",
        "defs": {
            "class_declaration": ("name", "class"),
            "struct_declaration": ("name", "class"),
            "protocol_declaration": ("name", "class"),
            "function_declaration": ("name", "function"),
        },
        "calls": {"type": "call_expression", "field": None},
        "imports": [r"\bimport\s+([\w.]+)"],
    },
}

_NAME_CHILD_TYPES = ("simple_identifier", "identifier", "type_identifier", "name", "field_identifier")
_CALLEE_RE = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\(")


def available_languages() -> Dict[str, bool]:
    """Which configured languages have importable grammar wheels."""
    out = {}
    for language, cfg in CONFIGS.items():
        try:
            importlib.import_module(cfg["module"])
            out[language] = True
        except ImportError:
            out[language] = False
    return out


def extract_ts(path: Path, language: str) -> Dict[str, Any]:
    """AST extraction into the graphify raw shape ({nodes, edges, error})."""
    cfg = CONFIGS[language]
    lang_mod = importlib.import_module(cfg["module"])
    from tree_sitter import Language, Parser

    language_obj = Language(lang_mod.language())
    parser = Parser()
    try:
        parser.language = language_obj
    except AttributeError:  # older bindings
        parser.set_language(language_obj)

    source = path.read_bytes()
    tree = parser.parse(source)

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen_ids = set()
    calls_cfg = cfg["calls"]
    defs_cfg = cfg["defs"]

    def text(node: Any) -> str:
        return source[node.start_byte:node.end_byte].decode("utf-8", "replace")

    def line(node: Any) -> int:
        return node.start_point[0] + 1

    def name_of(node: Any, field: Optional[str]) -> Optional[str]:
        child = node.child_by_field_name(field) if field else None
        if child is None:
            for candidate in node.children:
                if candidate.type in _NAME_CHILD_TYPES:
                    child = candidate
                    break
        if child is None:
            return None
        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", text(child).strip())
        return match.group(0) if match else None

    def walk(node: Any, containers: Tuple[str, ...], current_def: Optional[str]) -> None:
        node_type = node.type

        if node_type in defs_cfg:
            field, kind = defs_cfg[node_type]
            name = name_of(node, field)
            if name:
                container = containers[-1] if containers else None
                if node_type == "method_declaration" and cfg.get("method_receiver"):
                    recv = node.child_by_field_name(cfg["method_receiver"])
                    if recv is not None:
                        identifiers = re.findall(
                            r"[A-Za-z_][A-Za-z0-9_]*", text(recv).replace("*", " ")
                        )
                        if identifiers:
                            container = identifiers[-1]
                raw_id = f"{container}.{name}" if container else name
                if raw_id not in seen_ids:
                    seen_ids.add(raw_id)
                    snippet = text(node).split("\n", 1)[0][:120]
                    nodes.append({
                        "id": raw_id,
                        "label": f"{'class' if kind == 'class' else 'def'} {raw_id}",
                        "kind": kind,
                        "source_location": f"L{line(node)}",
                        "doc": "",
                        "signature": snippet,
                        "line_end": node.end_point[0] + 1,
                        "col_start": node.start_point[1],
                        "col_end": node.end_point[1],
                    })
                    edges.append({
                        "source": path.name,
                        "target": raw_id,
                        "relation": "defines",
                        "source_location": f"L{line(node)}",
                    })
                next_containers = containers + (name,) if kind == "class" else containers
                for child in node.children:
                    walk(child, next_containers, raw_id if kind != "class" else current_def)
                return

        if node_type == calls_cfg["type"]:
            callee_node = node.child_by_field_name(calls_cfg["field"]) if calls_cfg.get("field") else None
            callee_text = text(callee_node).strip() if callee_node is not None else None
            if not callee_text:
                match = _CALLEE_RE.match(text(node))
                callee_text = match.group(1) if match else None
            if callee_text and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", callee_text):
                parts = callee_text.split(".")
                target = parts[-1]
                receiver: Optional[str] = parts[0] if len(parts) > 1 else None
                if calls_cfg.get("receiver_field"):
                    obj = node.child_by_field_name(calls_cfg["receiver_field"])
                    if obj is not None:
                        receiver = text(obj).strip()[:40] or receiver
                edges.append({
                    "source": current_def or path.name,
                    "target": target,
                    "relation": "calls",
                    "source_location": f"L{line(node)}",
                    "receiver": receiver,
                    "call_kind": "BARE" if receiver is None else "QUALIFIED",
                })

        for child in node.children:
            walk(child, containers, current_def)

    walk(tree.root_node, (), None)

    decoded = source.decode("utf-8", "replace")
    for i, source_line in enumerate(decoded.splitlines(), 1):
        for pattern in cfg["imports"]:
            match = re.search(pattern, source_line)
            if match:
                edges.append({
                    "source": path.name,
                    "target": match.group(1),
                    "relation": "imports",
                    "source_location": f"L{i}",
                })

    return {"nodes": nodes, "edges": edges, "error": None}
