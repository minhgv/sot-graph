"""Optional tree-sitter AST extractors for Go/Rust/Java/Kotlin/Swift/PHP/TypeScript/JavaScript/Python/C#.

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
from typing import Any, Dict, List, Optional, Set, Tuple

CONFIGS: Dict[str, Dict[str, Any]] = {
    "go": {
        "module": "tree_sitter_go",
        "loader": "language",
        "defs": {
            "function_declaration": ("name", "function"),
            "method_declaration": ("name", "method"),
            "type_spec": ("name", "class"),
        },
        "method_receiver": "receiver",
        "calls": [{"type": "call_expression", "field": "function"}],
        "imports": [r'\bimport\s+(?:[\w./]+\s+)?"([^"]+)"'],
    },
    "rust": {
        "module": "tree_sitter_rust",
        "loader": "language",
        "defs": {
            "function_item": ("name", "function"),
            "struct_item": ("name", "class"),
            "enum_item": ("name", "class"),
            "trait_item": ("name", "class"),
        },
        "calls": [{"type": "call_expression", "field": "function"}],
        "imports": [r"\buse\s+([^;]+);"],
    },
    "java": {
        "module": "tree_sitter_java",
        "loader": "language",
        "defs": {
            "class_declaration": ("name", "class"),
            "interface_declaration": ("name", "class"),
            "enum_declaration": ("name", "class"),
            "record_declaration": ("name", "class"),
            "method_declaration": ("name", "method"),
        },
        "calls": [{"type": "method_invocation", "field": "name", "receiver_field": "object"}],
        "imports": [r"\bimport\s+(?:static\s+)?([\w.]+)\s*;"],
        "inheritance": {
            "types": {"class_declaration", "interface_declaration",
                      "enum_declaration", "record_declaration"},
            "extends_fields": ("superclass",),
            "extends_child_types": ("extends_interfaces",),
            "implements_fields": ("interfaces",),
        },
    },
    "kotlin": {
        "module": "tree_sitter_kotlin",
        "loader": "language",
        "defs": {
            "class_declaration": ("name", "class"),
            "object_declaration": ("name", "class"),
            "function_declaration": ("name", "function"),
        },
        "calls": [{"type": "call_expression", "field": None}],
        "imports": [r"\bimport\s+([\w.]+)"],
    },
    "swift": {
        "module": "tree_sitter_swift",
        "loader": "language",
        "defs": {
            "class_declaration": ("name", "class"),
            "struct_declaration": ("name", "class"),
            "protocol_declaration": ("name", "class"),
            "function_declaration": ("name", "function"),
        },
        "calls": [{"type": "call_expression", "field": None}],
        "imports": [r"\bimport\s+([\w.]+)"],
    },
    "php": {
        "module": "tree_sitter_php",
        "loader": "language_php",
        "defs": {
            "class_declaration": ("name", "class"),
            "interface_declaration": ("name", "class"),
            "trait_declaration": ("name", "class"),
            "enum_declaration": ("name", "class"),
            "method_declaration": ("name", "method"),
            "function_definition": ("name", "function"),
        },
        "calls": [
            {"type": "scoped_call_expression", "field": "name", "receiver_field": "scope"},
            {"type": "member_call_expression", "field": "name", "receiver_field": "object"},
            {"type": "function_call_expression", "field": "function"},
        ],
        "imports": [r"\buse\s+(?:function\s+|const\s+)?([A-Za-z0-9_\\]+)"],
        "inheritance": {
            "types": {"class_declaration", "interface_declaration", "enum_declaration"},
            "extends_child_types": ("base_clause",),
            "implements_child_types": ("class_interface_clause",),
        },
    },
    "typescript": {
        "module": "tree_sitter_typescript",
        "loader": "language_typescript",
        "defs": {
            "class_declaration": ("name", "class"),
            "interface_declaration": ("name", "class"),
            "type_alias_declaration": ("name", "class"),
            "enum_declaration": ("name", "class"),
            "function_declaration": ("name", "function"),
            "method_definition": ("name", "method"),
        },
        "calls": [{"type": "call_expression", "field": "function"}],
        "imports": [r"\bfrom\s+['\"]([^'\"]+)['\"]", r"\bimport\s+['\"]([^'\"]+)['\"]"],
        "inheritance": {
            "types": {"class_declaration", "interface_declaration"},
            "extends_child_types": ("extends_clause",),
            "implements_child_types": ("implements_clause",),
        },
    },
    "tsx": {
        "module": "tree_sitter_typescript",
        "loader": "language_tsx",
        "defs": {
            "class_declaration": ("name", "class"),
            "interface_declaration": ("name", "class"),
            "type_alias_declaration": ("name", "class"),
            "enum_declaration": ("name", "class"),
            "function_declaration": ("name", "function"),
            "method_definition": ("name", "method"),
        },
        "calls": [{"type": "call_expression", "field": "function"}],
        "imports": [r"\bfrom\s+['\"]([^'\"]+)['\"]", r"\bimport\s+['\"]([^'\"]+)['\"]"],
        "inheritance": {
            "types": {"class_declaration", "interface_declaration"},
            "extends_child_types": ("extends_clause",),
            "implements_child_types": ("implements_clause",),
        },
    },
    "javascript": {
        "module": "tree_sitter_javascript",
        "loader": "language",
        "defs": {
            "class_declaration": ("name", "class"),
            "function_declaration": ("name", "function"),
            "method_definition": ("name", "method"),
        },
        "calls": [{"type": "call_expression", "field": "function"}],
        "imports": [r"\bfrom\s+['\"]([^'\"]+)['\"]", r"\bimport\s+['\"]([^'\"]+)['\"]"],
        "inheritance": {
            "types": {"class_declaration"},
            "extends_child_types": ("class_heritage",),
        },
    },
    "python": {
        "module": "tree_sitter_python",
        "loader": "language",
        "defs": {
            "class_definition": ("name", "class"),
            "function_definition": ("name", "function"),
            "type_alias_statement": ("name", "class"),
        },
        "calls": [{"type": "call", "field": "function"}],
        "imports": [r"\bimport\s+([\w.]+)", r"\bfrom\s+([\w.]+)\s+import"],
        "inheritance": {
            "types": {"class_definition"},
            "extends_child_types": ("argument_list",),
        },
    },
    "c_sharp": {
        "module": "tree_sitter_c_sharp",
        "loader": "language",
        "defs": {
            "class_declaration": ("name", "class"),
            "interface_declaration": ("name", "class"),
            "struct_declaration": ("name", "class"),
            "record_declaration": ("name", "class"),
            "enum_declaration": ("name", "class"),
            "method_declaration": ("name", "method"),
            "local_function_statement": ("name", "function"),
        },
        "calls": [{"type": "invocation_expression", "field": "expression"}],
        "imports": [r"\busing\s+([\w.]+)\s*;"],
        "inheritance": {
            "types": {"class_declaration", "interface_declaration", "record_declaration", "struct_declaration"},
            "extends_child_types": ("base_list",),
        },
    },
}

_NAME_CHILD_TYPES = (
    "simple_identifier", "identifier", "type_identifier", "name",
    "field_identifier", "property_identifier"
)
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
    if language not in CONFIGS:
        return {"nodes": [], "edges": [], "error": f"Unsupported tree-sitter language: {language}"}

    cfg = CONFIGS[language]
    lang_mod = importlib.import_module(cfg["module"])
    from tree_sitter import Language, Parser

    loader_fn_name = cfg.get("loader", "language")
    loader_fn = getattr(lang_mod, loader_fn_name, None) or getattr(lang_mod, "language")
    language_obj = Language(loader_fn())
    try:
        parser = Parser(language_obj)
    except TypeError:
        parser = Parser()
        if hasattr(parser, "set_language"):
            getattr(parser, "set_language")(language_obj)
        else:
            parser.language = language_obj
    source = path.read_bytes()
    tree = parser.parse(source)

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    calls_cfg_list = cfg.get("calls", [])
    defs_cfg = cfg["defs"]

    def text(node: Any) -> str:
        return source[node.start_byte:node.end_byte].decode("utf-8", "replace")

    def line(node: Any) -> int:
        return node.start_point[0] + 1

    def name_of(node: Any, field: Optional[str]) -> Optional[str]:
        child = node.child_by_field_name(field) if field else None
        if child is None and node.type == "type_alias_statement" and len(node.children) >= 2:
            child = node.children[1]
        if child is None:
            for candidate in node.children:
                if candidate.type in _NAME_CHILD_TYPES:
                    child = candidate
                    break
        if child is None:
            return None
        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", text(child).strip())
        return match.group(0) if match else None

    def collect_bases(node: Any) -> List[str]:
        # Flatten superclass/interfaces/bases clauses into clean type names
        if node.type in ("type_identifier", "identifier", "name", "qualified_name", "namespace_name"):
            raw = text(node).strip()
            # Clean generic arguments and leading/trailing qualifiers
            short = re.sub(r"<[^>]+>", "", raw).rsplit(".", 1)[-1].rsplit("\\", 1)[-1].rsplit("::", 1)[-1]
            return [short] if short and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", short) else []
        if node.type in ("scoped_type_identifier", "scoped_identifier"):
            raw = text(node).strip().rsplit(".", 1)[-1].rsplit("::", 1)[-1]
            return [raw] if raw and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", raw) else []
        if node.type in ("generic_type", "generic_name"):
            for child in node.children:
                if child.type not in ("type_arguments", "type_argument_list"):
                    inner = collect_bases(child)
                    if inner:
                        return inner
            return []
        found: List[str] = []
        for child in node.children:
            found.extend(collect_bases(child))
        return found

    def emit_inheritance(node: Any, node_type: str, source_id: str) -> None:
        inh = cfg.get("inheritance")
        if not inh or node_type not in inh["types"]:
            return
        all_children = list(node.children)
        for c in node.children:
            if c.type in ("class_heritage", "heritage_clause"):
                all_children.extend(c.children)
        extends_nodes = [node.child_by_field_name(f)
                         for f in inh.get("extends_fields", ())]
        extends_nodes += [c for c in all_children
                          if c.type in inh.get("extends_child_types", ())]
        implements_nodes = [node.child_by_field_name(f)
                            for f in inh.get("implements_fields", ())]
        implements_nodes += [c for c in all_children
                            if c.type in inh.get("implements_child_types", ())]
        for relation, clause_nodes in (
            ("extends", extends_nodes),
            ("implements", implements_nodes),
        ):
            for clause in clause_nodes:
                if clause is None:
                    continue
                for base in collect_bases(clause):
                    if base and base != source_id.split(".")[-1]:
                        edges.append({
                            "source": source_id,
                            "target": base,
                            "relation": relation,
                            "source_location": f"L{line(node)}",
                        })

    def walk(node: Any, containers: Tuple[str, ...], current_def: Optional[str]) -> None:
        node_type = node.type

        # Check for named arrow functions / function expressions in variable assignments
        if node_type in ("variable_declarator", "lexical_declaration"):
            # Check if variable declarator contains an arrow function or function expression
            for child in node.children:
                if child.type == "variable_declarator":
                    var_name = name_of(child, "name")
                    val_node = child.child_by_field_name("value")
                    if var_name and val_node and val_node.type in ("arrow_function", "function_expression", "function"):
                        raw_id = f"{containers[-1]}.{var_name}" if containers else var_name
                        if raw_id not in seen_ids:
                            seen_ids.add(raw_id)
                            snippet = text(node).split("\n", 1)[0][:120]
                            nodes.append({
                                "id": raw_id,
                                "label": f"def {raw_id}",
                                "kind": "function",
                                "source_location": f"L{line(child)}",
                                "doc": "",
                                "signature": snippet,
                                "line_end": val_node.end_point[0] + 1,
                                "col_start": child.start_point[1],
                                "col_end": val_node.end_point[1],
                            })
                            edges.append({
                                "source": path.name,
                                "target": raw_id,
                                "relation": "defines",
                                "source_location": f"L{line(child)}",
                            })
                        for sub in val_node.children:
                            walk(sub, containers, raw_id)
                        return

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
                    emit_inheritance(node, node_type, raw_id)

                # Special: PHP traits used inside class body (use LoggerTrait;)
                if language == "php" and kind == "class":
                    for child in node.children:
                        if child.type == "declaration_list":
                            for member in child.children:
                                if member.type == "use_declaration":
                                    for trait_node in member.children:
                                        if trait_node.type in ("name", "qualified_name"):
                                            trait_name = text(trait_node).strip().rsplit("\\", 1)[-1]
                                            if trait_name and trait_name != "use":
                                                edges.append({
                                                    "source": raw_id,
                                                    "target": trait_name,
                                                    "relation": "implements",
                                                    "source_location": f"L{line(member)}",
                                                })

                next_containers = containers + (name,) if kind == "class" else containers
                for child in node.children:
                    walk(child, next_containers, raw_id if kind != "class" else current_def)
                return

        # Check calls against configured call patterns
        for call_spec in calls_cfg_list:
            if node_type == call_spec["type"]:
                callee_node = node.child_by_field_name(call_spec["field"]) if call_spec.get("field") else None
                callee_text = text(callee_node).strip() if callee_node is not None else None
                if not callee_text:
                    match = _CALLEE_RE.match(text(node))
                    callee_text = match.group(1) if match else None
                if callee_text and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:\->]*", callee_text):
                    # Clean PHP $this->, self::, static::, C# client., TS this.
                    callee_clean = callee_text.replace("->", ".").replace("::", ".")
                    parts = callee_clean.split(".")
                    target = parts[-1]
                    receiver: Optional[str] = parts[0] if len(parts) > 1 else None
                    if call_spec.get("receiver_field"):
                        obj = node.child_by_field_name(call_spec["receiver_field"])
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
                break

        for child in node.children:
            walk(child, containers, current_def)

    walk(tree.root_node, (), None)

    decoded = source.decode("utf-8", "replace")
    for i, source_line in enumerate(decoded.splitlines(), 1):
        for pattern in cfg.get("imports", []):
            match = re.search(pattern, source_line)
            if match:
                raw_target = match.group(1).strip()
                # Normalize target name
                clean_target = raw_target.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[-1]
                edges.append({
                    "source": path.name,
                    "target": clean_target,
                    "relation": "imports",
                    "source_location": f"L{i}",
                })

    return {"nodes": nodes, "edges": edges, "error": None}
