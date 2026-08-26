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

from sot_graph.modutil import dotted_module
from sot_graph.parser_outcome import ParserOutcome


def module_form_of_import(raw: str, language: str, dir_module: str) -> Optional[str]:
    """Normalize an import path to the dotted project-module form (P3.3b).

    Go 'go_pkg/storage' -> 'go_pkg.storage'. TS/JS relative '../models/order'
    absolutized against ``dir_module`` — the DECLARING FILE'S DIRECTORY in
    dotted form — mirroring resolve_relative semantics: the first dot is the
    directory itself, each further dot steps one level up. Other languages
    keep slash->dot with a JS/TS extension tail stripped. Returns None when
    nothing usable remains.
    """
    if not raw:
        return None
    if language == "go":
        return raw.replace("/", ".")
    if language in ("typescript", "tsx", "javascript") and raw.startswith("."):
        stripped = raw.lstrip("./")
        if not stripped:
            return None
        dots = len(raw) - len(raw.lstrip("."))
        base_parts = dir_module.split(".") if dir_module else []
        for _ in range(max(dots - 1, 0)):
            if base_parts:
                base_parts.pop()
        joined = stripped.replace("/", ".")
        return ".".join(base_parts + [joined]) if base_parts else joined
    return raw.replace("/", ".").removesuffix(".js").removesuffix(".ts")



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
            # P3.3b: `impl Doc { ... }` scopes its methods to the type —
            # canonical qualified identity Doc.save instead of bare save.
            "impl_item": ("type", "class"),
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
    "c": {
        "module": "tree_sitter_c",
        "loader": "language",
        "defs": {
            "function_definition": ("declarator", "function"),
            "struct_specifier": ("name", "class"),
            "enum_specifier": ("name", "class"),
            "union_specifier": ("name", "class"),
            "type_definition": ("declarator", "class"),
        },
        "calls": [{"type": "call_expression", "field": "function"}],
        "imports": [r'#include\s*[<"]([^>"]+)[>"]'],
    },
    "cpp": {
        "module": "tree_sitter_cpp",
        "loader": "language",
        "defs": {
            "class_specifier": ("name", "class"),
            "struct_specifier": ("name", "class"),
            "enum_specifier": ("name", "class"),
            "union_specifier": ("name", "class"),
            "namespace_definition": ("name", "class"),
            "function_definition": ("declarator", "function"),
        },
        "calls": [{"type": "call_expression", "field": "function"}],
        "imports": [r'#include\s*[<"]([^>"]+)[>"]'],
        "inheritance": {
            "types": {"class_specifier", "struct_specifier"},
            "extends_child_types": ("base_class_clause",),
        },
    },
    "dart": {
        "module": "tree_sitter_dart",
        "loader": "language",
        "defs": {
            "class_definition": ("name", "class"),
            "enum_declaration": ("name", "class"),
            "mixin_declaration": ("name", "class"),
            "extension_declaration": ("name", "class"),
            "function_signature": ("name", "function"),
            "method_signature": ("name", "method"),
            "getter_signature": ("name", "function"),
            "setter_signature": ("name", "function"),
        },
        "calls": [
            {"type": "expression_statement", "field": None},
        ],
        "imports": [r"\bimport\s+['\"]([^'\"]+)['\"]"],
        "inheritance": {
            "types": {"class_definition", "mixin_declaration"},
            "extends_child_types": ("superclass", "interfaces", "mixins"),
        },
    },
    "scala": {
        "module": "tree_sitter_scala",
        "loader": "language",
        "defs": {
            "class_definition": ("name", "class"),
            "trait_definition": ("name", "class"),
            "object_definition": ("name", "class"),
            "function_definition": ("name", "function"),
            "function_declaration": ("name", "function"),
        },
        "calls": [
            {"type": "call_expression", "field": "function"},
            {"type": "generic_function", "field": "function"},
        ],
        "imports": [r"\bimport\s+([\w.]+)"],
        "inheritance": {
            "types": {"class_definition", "trait_definition", "object_definition"},
            "extends_child_types": ("extends_clause",),
        },
    },
    "elixir": {
        "module": "tree_sitter_elixir",
        "loader": "language",
        "defs": {},
        "calls": [{"type": "call", "field": None}],
        "imports": [
            r"\balias\s+([\w.]+)",
            r"\bimport\s+([\w.]+)",
            r"\buse\s+([\w.]+)",
            r"\brequire\s+([\w.]+)",
        ],
    },
    "lua": {
        "module": "tree_sitter_lua",
        "loader": "language",
        "defs": {
            "function_declaration": ("name", "function"),
        },
        "calls": [{"type": "function_call", "field": "name"}],
        "imports": [r'\brequire\s*\(\s*["\']([^"\']+)["\']\s*\)'],
    },
    "zig": {
        "module": "tree_sitter_zig",
        "loader": "language",
        "defs": {
            "function_declaration": ("name", "function"),
            "struct_declaration": (None, "class"),
            "enum_declaration": (None, "class"),
            "union_declaration": (None, "class"),
        },
        "calls": [{"type": "call_expression", "field": "function"}],
        "imports": [r'@import\s*\(\s*["\']([^"\']+)["\']\s*\)'],
    },
    "julia": {
        "module": "tree_sitter_julia",
        "loader": "language",
        "defs": {
            "module_definition": ("name", "class"),
            "struct_definition": ("name", "class"),
            "function_definition": ("name", "function"),
            "macro_definition": ("name", "function"),
        },
        "calls": [{"type": "call_expression", "field": None}],
        "imports": [r"\busing\s+([\w.]+)", r"\bimport\s+([\w.]+)"],
    },
    "sql": {
        "module": "tree_sitter_sql",
        "loader": "language",
        "defs": {
            "create_table": ("name", "class"),
            "create_view": ("name", "class"),
            "create_function": ("name", "function"),
            "create_procedure": ("name", "function"),
        },
        "calls": [],
        "imports": [],
    },
    "graphql": {
        "module": "tree_sitter_graphql",
        "loader": "language",
        "defs": {
            "type_definition": ("name", "class"),
            "interface_type_definition": ("name", "class"),
            "union_type_definition": ("name", "class"),
            "enum_type_definition": ("name", "class"),
            "input_object_type_definition": ("name", "class"),
            "field_definition": ("name", "function"),
        },
        "calls": [],
        "imports": [],
    },
}

_NAME_CHILD_TYPES = (
    "simple_identifier", "identifier", "type_identifier", "name",
    "namespace_identifier", "field_identifier", "property_identifier",
    "destructor_name", "dot_index_expression", "method_index_expression"
)
_CALLEE_RE = re.compile(r"\s*([A-Za-z_~][A-Za-z0-9_.]*)\s*\(")

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
    """AST extraction into the graphify raw shape ({nodes, edges, error}).

    Results carry truthful parser provenance: ``parser_outcome`` (a
    :class:`sot_graph.parser_outcome.ParserOutcome` value) plus an optional
    ``fallback_reason`` explaining why a lower-fidelity path was taken.
    """
    if language not in CONFIGS:
        return {
            "nodes": [],
            "edges": [],
            "error": f"Unsupported tree-sitter language: {language}",
            "parser_outcome": ParserOutcome.PARSER_UNAVAILABLE.value,
            "fallback_reason": f"no tree-sitter grammar configured for language: {language}",
        }

    path = Path(path)  # callers/tests may pass a plain str path
    cfg = CONFIGS[language]
    try:
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
    except ImportError as exc:
        return {
            "nodes": [],
            "edges": [],
            "error": f"tree-sitter grammar not installed for {language}: {exc}",
            "parser_outcome": ParserOutcome.PARSER_UNAVAILABLE.value,
            "fallback_reason": f"missing module: {cfg['module']}",
        }
    except Exception as exc:
        return {
            "nodes": [],
            "edges": [],
            "error": f"tree-sitter parse failed for {language}: {exc}",
            "parser_outcome": ParserOutcome.PARSE_ERROR.value,
            "fallback_reason": str(exc),
        }

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    calls_cfg_list = cfg.get("calls", [])
    defs_cfg = cfg["defs"]
    # P3.3b: AST-anchored receiver typing. Maps a simple variable name to
    # the type it was constructed as (TS `const v = new C()`, Go receiver
    # params `func (r *T)`, Go value params `func f(r *T)`, Go
    # `r := &T{}`). File-scoped and last-declaration-wins: deliberately
    # conservative — it only ever QUALIFIES an existing receiver call
    # target, never invents a callee.
    var_types: Dict[str, str] = {}

    def _bind_typed_params(node: Any) -> None:
        """Bind Go/Rust parameter variables to their declared types.

        Go: `d *Doc` / receiver `(w *Worker1)`. Rust: `d: &Doc`,
        `d: Doc`, `d: &mut Doc` (crate:: paths keep their tail type).
        """
        patterns = (
            r"([A-Za-z_]\w*)\s+\*?\s*([A-Za-z_]\w*)"  # Go form
            if language == "go"
            else r"([A-Za-z_]\w*)\s*:\s*&?(?:mut\s+)?(?:crate::)?([A-Z]\w*)"  # Rust form
        )
        for child in node.children:
            if child.type in ("parameter_list", "parameter_declaration", "parameters"):
                for m in re.finditer(patterns, text(child)):
                    var, type_name = m.group(1), m.group(2)
                    if var != type_name and type_name[0].isupper():
                        var_types[var] = type_name

    def _bind_ts_declarator(node: Any) -> None:
        """Bind TS `const v = new C()` variable names to class C."""
        name_node = node.child_by_field_name("name")
        value_node = node.child_by_field_name("value")
        if name_node is None or value_node is None or value_node.type != "new_expression":
            return
        ctor = value_node.child_by_field_name("constructor")
        if ctor is not None and ctor.type in _NAME_CHILD_TYPES + ("identifier",):
            ctor_name = text(ctor).strip()
            var_name = text(name_node).strip()
            if ctor_name and var_name and re.fullmatch(r"[A-Za-z_$][\w$]*", var_name):
                var_types[var_name] = ctor_name

    def text(node: Any) -> str:
        return source[node.start_byte:node.end_byte].decode("utf-8", "replace")

    def line(node: Any) -> int:
        return node.start_point[0] + 1

    def _unwrap_declarator(d_node: Any) -> Optional[str]:
        if d_node is None:
            return None
        if d_node.type in _NAME_CHILD_TYPES:
            raw_n = text(d_node).strip()
            if ":" in raw_n or "." in raw_n:
                raw_n = raw_n.replace(":", ".").split(".")[-1]
            match = re.match(r"[~]?[A-Za-z_][A-Za-z0-9_]*", raw_n)
            return match.group(0) if match else None
        if d_node.type == "qualified_identifier":
            name_child = d_node.child_by_field_name("name")
            res = _unwrap_declarator(name_child)
            if res:
                return res
            raw_q = text(d_node).strip().split("::")[-1]
            match = re.match(r"[~]?[A-Za-z_][A-Za-z0-9_]*", raw_q)
            return match.group(0) if match else None
        if d_node.type == "function_declarator":
            inner = d_node.child_by_field_name("declarator") or (d_node.children[0] if d_node.children else None)
            return _unwrap_declarator(inner)
        if d_node.type in ("pointer_declarator", "reference_declarator", "parenthesized_declarator"):
            inner = d_node.child_by_field_name("declarator") or (d_node.children[-1] if d_node.children else None)
            return _unwrap_declarator(inner)
        if d_node.type == "template_function":
            inner = d_node.child_by_field_name("name") or (d_node.children[0] if d_node.children else None)
            return _unwrap_declarator(inner)
        if d_node.type in ("class_specifier", "struct_specifier", "function_definition"):
            name_field = d_node.child_by_field_name("name") or d_node.child_by_field_name("declarator")
            return _unwrap_declarator(name_field)
        for cand in d_node.children:
            res = _unwrap_declarator(cand)
            if res:
                return res
        return None

    def name_of(node: Any, field: Optional[str]) -> Optional[str]:
        child = node.child_by_field_name(field) if field else None
        if child is None and node.type == "type_alias_statement" and len(node.children) >= 2:
            child = node.children[1]
        if child is not None:
            unwrapped = _unwrap_declarator(child)
            if unwrapped:
                return unwrapped
        for candidate in node.children:
            unwrapped = _unwrap_declarator(candidate)
            if unwrapped:
                return unwrapped
        return None
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

        # P3.3b receiver typing + constructor edges (AST-anchored).
        if node_type in ("variable_declarator", "lexical_declaration", "variable_declaration"):
            for _d in (
                [c for c in node.children if c.type == "variable_declarator"]
                if node_type != "variable_declarator" else [node]
            ):
                _bind_ts_declarator(_d)
        elif language == "go" and node_type == "short_var_declaration":
            for _m in re.finditer(
                r"([A-Za-z_]\w*)\s*:=\s*&?\s*([A-Z]\w*)\s*\{", text(node)
            ):
                var_types[_m.group(1)] = _m.group(2)
        elif language == "rust" and node_type == "let_declaration":
            for _m in re.finditer(
                r"let\s+(?:mut\s+)?([a-z_]\w*)\s*(?::\s*[^=]+)?=\s*([A-Z]\w*)\s*(?:\{|;)",
                text(node),
            ):
                var_types[_m.group(1)] = _m.group(2)
        elif node_type == "new_expression" and language in ("typescript", "tsx", "javascript"):
            ctor = node.child_by_field_name("constructor")
            if ctor is not None:
                ctor_text = text(ctor).strip()
                if re.fullmatch(r"[A-Za-z_$][\w$]*", ctor_text):
                    edges.append({
                        "source": current_def or path.name,
                        "target": ctor_text,
                        "relation": "calls",
                        "source_location": f"L{line(node)}",
                        "receiver": None,
                        "call_kind": "CONSTRUCTOR",
                    })
        # Check for named arrow functions / function expressions in variable assignments
        if node_type in ("variable_declarator", "lexical_declaration", "variable_declaration"):
            declarators = (
                [child for child in node.children if child.type == "variable_declarator"]
                if node_type in ("lexical_declaration", "variable_declaration")
                else [node]
            )
            for child in declarators:
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
                elif val_node:
                    walk(val_node, containers, current_def)
            return
        if language == "elixir" and node_type == "call":
            # In Elixir, defmodule, def, defp, defmacro, defprotocol are call nodes
            first_child = node.child_by_field_name("name") or (node.children[0] if node.children else None)
            f_text = text(first_child).strip() if first_child else ""
            if f_text == "defmodule":
                args_node = node.child_by_field_name("arguments") or (node.children[1] if len(node.children) > 1 else None)
                mod_name = text(args_node).strip().split(".")[-1] if args_node else None
                if mod_name:
                    if mod_name not in seen_ids:
                        seen_ids.add(mod_name)
                        nodes.append({
                            "id": mod_name,
                            "label": f"class {mod_name}",
                            "kind": "class",
                            "source_location": f"L{line(node)}",
                            "doc": "",
                            "signature": f"defmodule {mod_name}",
                            "line_end": node.end_point[0] + 1,
                            "col_start": node.start_point[1],
                            "col_end": node.end_point[1],
                        })
                        edges.append({
                            "source": path.name,
                            "target": mod_name,
                            "relation": "defines",
                            "source_location": f"L{line(node)}",
                        })
                    for child in node.children:
                        walk(child, containers + (mod_name,), current_def)
                    return
            elif f_text in ("def", "defp", "defmacro", "defprotocol", "defimpl"):
                args_node = node.child_by_field_name("arguments") or (node.children[1] if len(node.children) > 1 else None)
                fn_name = None
                if args_node:
                    m = re.match(r"([A-Za-z_][A-Za-z0-9_?!]*)", text(args_node).strip())
                    if m:
                        fn_name = m.group(1)
                if fn_name:
                    container = containers[-1] if containers else None
                    raw_id = f"{container}.{fn_name}" if container else fn_name
                    if raw_id not in seen_ids:
                        seen_ids.add(raw_id)
                        nodes.append({
                            "id": raw_id,
                            "label": f"def {raw_id}",
                            "kind": "function",
                            "source_location": f"L{line(node)}",
                            "doc": "",
                            "signature": text(node).split("\n", 1)[0][:120],
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
                    # Walk only inside do_block body to avoid caller matching its own signature
                    do_block = node.child_by_field_name("do_block") or next((c for c in node.children if c.type == "do_block"), None)
                    if do_block:
                        walk(do_block, containers, raw_id)
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
                if language == "go" and node_type in ("function_declaration", "method_declaration"):
                    _bind_typed_params(node)
                elif language == "rust" and node_type == "function_item":
                    _bind_typed_params(node)
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
                if language == "dart" and kind == "class":
                    # In Dart grammar, class_body contains method_signature followed by function_body as sibling
                    for child in node.children:
                        if child.type == "class_body":
                            active_method = current_def
                            for member in child.children:
                                if member.type in ("method_signature", "function_signature", "getter_signature", "setter_signature"):
                                    m_name = name_of(member, "name")
                                    if m_name:
                                        active_method = f"{name}.{m_name}"
                                        walk(member, next_containers, current_def)
                                elif member.type == "function_body":
                                    walk(member, next_containers, active_method)
                                else:
                                    walk(member, next_containers, current_def)
                            return
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
                        "receiver_type": var_types.get(receiver) if receiver else None,
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
                target_clean = raw_target.split("/")[-1].split(".")[0] if ("/" in raw_target or "." in raw_target) else raw_target
                edges.append({
                    "source": path.name,
                    "target": target_clean or raw_target,
                    "relation": "imports",
                    "source_location": f"L{i}",
                    "import_source": raw_target,
                })
                break
    # Attach import provenance to call edges so the DB-side resolver can
    # disambiguate same-named symbols by the calling file's imports
    # (mirrors the Python extractor's ``import_source`` behavior).
    import_map: Dict[str, str] = {}
    alias_map: Dict[str, str] = {}
    for edge_item in edges:
        if edge_item.get("relation") == "imports" and edge_item.get("import_source"):
            raw_import = edge_item["import_source"]
            import_map.setdefault(edge_item["target"], raw_import)
            # PHP ``use Foo\Bar\Baz`` / Dart ``package:app/src/bloc.dart``:
            # bind calls by the imported symbol or file basename too.
            tail = re.split(r"[\\/:]", raw_import)[-1]
            base = tail.split(".")[0] if "." in tail else tail
            if tail:
                import_map.setdefault(tail, raw_import)
            if base:
                import_map.setdefault(base, raw_import)
    # P3.3b: TS alias imports ``import { x as y }`` bind y -> x so calls via
    # the alias resolve to the original exported name.
    if language in ("typescript", "tsx", "javascript"):
        for bindings in re.findall(r"import\s*\{([^}]*)\}", decoded):
            for item in bindings.split(","):
                m = re.match(r"\s*([A-Za-z_$][\w$]*)\s+as\s+([A-Za-z_$][\w$]*)\s*$", item)
                if m:
                    alias_map[m.group(2)] = m.group(1)

    def _module_for_import(raw: str) -> Optional[str]:
        """Shared normalizer; the caller with the true repo-relative module
        re-normalizes via import_raw (dir base is best-effort here)."""
        return module_form_of_import(raw, language, dotted_module(str(path.parent)))



    for edge_item in edges:
        if edge_item.get("relation") != "calls":
            continue
        bound: Optional[str] = None
        receiver = edge_item.get("receiver")
        if receiver and receiver.split(".")[0] in import_map:
            bound = import_map[receiver.split(".")[0]]
        elif edge_item["target"] in import_map:
            bound = import_map[edge_item["target"]]
        module_form = _module_for_import(bound) if bound else None
        if module_form:
            edge_item["import_raw"] = bound
            edge_item["import_source"] = module_form
        if edge_item["target"] in alias_map:
            edge_item["alias_of"] = edge_item["target"]
            edge_item["target"] = alias_map[edge_item["target"]]
    if not nodes and not edges:
        return {
            "nodes": [],
            "edges": [],
            "error": None,
            "parser_outcome": ParserOutcome.VALID_EMPTY.value,
            "fallback_reason": None,
        }
    return {
        "nodes": nodes,
        "edges": edges,
        "error": None,
        "parser_outcome": ParserOutcome.COMPLETE.value,
        "fallback_reason": None,
    }
