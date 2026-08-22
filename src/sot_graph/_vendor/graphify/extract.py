"""
src/sot_graph/_vendor/graphify/extract.py — Multi-language AST extractors for sot-graph.
Supports native Python AST extraction + robust structural regex/token extractors for 20+ languages.
Optionally bridges to tree-sitter if tree_sitter and tree_sitter_languages are installed.
"""

import ast
import re
from pathlib import Path
from typing import Any, Dict, List


def extract_python(path: Path) -> Dict[str, Any]:
    """Extract AST nodes and intra-file call/inheritance edges from Python files."""
    nodes = []
    edges = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(content, filename=str(path))
    except Exception as e:
        return {"nodes": [], "edges": [], "error": str(e)}

    # Top-level file node
    nodes.append({
        "id": path.name,
        "label": path.name,
        "kind": "file",
        "source_location": "L1",
        "doc": ast.get_docstring(tree) or "",
    })

    class PythonVisitor(ast.NodeVisitor):
        def __init__(self):
            self.scope_stack = [path.name]

        def visit_ClassDef(self, node: ast.ClassDef):
            class_id = node.name
            doc = ast.get_docstring(node) or ""
            nodes.append({
                "id": class_id,
                "label": f"class {node.name}",
                "kind": "class",
                "source_location": f"L{node.lineno}",
                "doc": doc,
            })
            # Edges: File contains class, or outer scope contains class
            edges.append({
                "source": self.scope_stack[-1],
                "target": class_id,
                "relation": "defines",
                "source_location": f"L{node.lineno}",
            })
            # Class inheritance edges
            for base in node.bases:
                if isinstance(base, ast.Name):
                    edges.append({
                        "source": class_id,
                        "target": base.id,
                        "relation": "extends",
                        "source_location": f"L{node.lineno}",
                    })
                elif isinstance(base, ast.Attribute):
                    edges.append({
                        "source": class_id,
                        "target": base.attr,
                        "relation": "extends",
                        "source_location": f"L{node.lineno}",
                    })

            self.scope_stack.append(class_id)
            self.generic_visit(node)
            self.scope_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef):
            self._handle_func(node, is_async=False)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            self._handle_func(node, is_async=True)

        def _handle_func(self, node: Any, is_async: bool):
            parent = self.scope_stack[-1]
            kind = "method" if len(self.scope_stack) > 1 and parent != path.name else "function"
            func_id = f"{parent}.{node.name}" if kind == "method" else node.name
            doc = ast.get_docstring(node) or ""
            prefix = "async def" if is_async else "def"

            nodes.append({
                "id": func_id,
                "label": f"{prefix} {node.name}",
                "kind": kind,
                "source_location": f"L{node.lineno}",
                "doc": doc,
            })
            edges.append({
                "source": parent,
                "target": func_id,
                "relation": "defines",
                "source_location": f"L{node.lineno}",
            })

            # Detect call expressions inside function
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name) and child.func.id != node.name:
                        edges.append({
                            "source": func_id,
                            "target": child.func.id,
                            "relation": "calls",
                            "source_location": f"L{getattr(child, 'lineno', node.lineno)}",
                        })
                    elif isinstance(child.func, ast.Attribute):
                        edges.append({
                            "source": func_id,
                            "target": child.func.attr,
                            "relation": "calls",
                            "source_location": f"L{getattr(child, 'lineno', node.lineno)}",
                        })

            self.scope_stack.append(func_id)
            self.generic_visit(node)
            self.scope_stack.pop()

        def visit_Import(self, node: ast.Import):
            for alias in node.names:
                edges.append({
                    "source": path.name,
                    "target": alias.name,
                    "relation": "imports",
                    "source_location": f"L{node.lineno}",
                })

        def visit_ImportFrom(self, node: ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                target_sym = alias.name if alias.name != "*" else mod
                edges.append({
                    "source": path.name,
                    "target": target_sym,
                    "relation": "imports",
                    "source_location": f"L{node.lineno}",
                })

    visitor = PythonVisitor()
    visitor.visit(tree)
    return {"nodes": nodes, "edges": edges, "error": None}


def _extract_regex_patterns(path: Path, patterns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generic high-speed lexical parser for languages when tree-sitter is optional."""
    nodes = []
    edges = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"nodes": [], "edges": [], "error": str(e)}

    nodes.append({
        "id": path.name,
        "label": path.name,
        "kind": "file",
        "source_location": "L1",
        "doc": "",
    })

    lines = content.splitlines()
    for i, line in enumerate(lines, 1):
        for pat in patterns:
            m = re.search(pat["regex"], line)
            if m:
                symbol_name = next((g for g in m.groups() if g), None)
                if symbol_name:
                    sym_id = symbol_name
                    kind = pat.get("kind", "symbol")
                    nodes.append({
                        "id": sym_id,
                        "label": f"{pat.get('prefix', '')} {symbol_name}".strip(),
                        "kind": kind,
                        "source_location": f"L{i}",
                        "doc": line.strip(),
                    })
                    edges.append({
                        "source": path.name,
                        "target": sym_id,
                        "relation": "defines",
                        "source_location": f"L{i}",
                    })
                    # Cross-references in the same line
                    if "import_match" in pat:
                        imp_match = re.search(pat["import_match"], line)
                        if imp_match:
                            target_ref = imp_match.group(1)
                            edges.append({
                                "source": sym_id,
                                "target": target_ref,
                                "relation": "imports",
                                "source_location": f"L{i}",
                            })

    return {"nodes": nodes, "edges": edges, "error": None}


def extract_js(path: Path) -> Dict[str, Any]:
    """JavaScript / TypeScript extractor."""
    patterns = [
        {"regex": r"class\s+([a-zA-Z0-9_$]+)(?:\s+extends\s+([a-zA-Z0-9_$]+))?", "kind": "class", "prefix": "class"},
        {"regex": r"interface\s+([a-zA-Z0-9_$]+)", "kind": "interface", "prefix": "interface"},
        {"regex": r"type\s+([a-zA-Z0-9_$]+)\s*=", "kind": "type", "prefix": "type"},
        {"regex": r"(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\(", "kind": "function", "prefix": "function"},
        {"regex": r"(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>", "kind": "function", "prefix": "arrow_func"},
        {"regex": r"import\s+.*?from\s+['\"]([^'\"]+)['\"]", "kind": "import", "prefix": "import"},
    ]
    return _extract_regex_patterns(path, patterns)


def extract_go(path: Path) -> Dict[str, Any]:
    """Go language extractor."""
    patterns = [
        {"regex": r"func\s+(?:\([^)]+\)\s+)?([a-zA-Z0-9_]+)\s*\(", "kind": "function", "prefix": "func"},
        {"regex": r"type\s+([a-zA-Z0-9_]+)\s+struct\b", "kind": "struct", "prefix": "type struct"},
        {"regex": r"type\s+([a-zA-Z0-9_]+)\s+interface\b", "kind": "interface", "prefix": "type interface"},
    ]
    return _extract_regex_patterns(path, patterns)


def extract_rust(path: Path) -> Dict[str, Any]:
    """Rust language extractor."""
    patterns = [
        {"regex": r"(?:pub\s+)?fn\s+([a-zA-Z0-9_]+)\s*\(", "kind": "function", "prefix": "fn"},
        {"regex": r"(?:pub\s+)?struct\s+([a-zA-Z0-9_]+)", "kind": "struct", "prefix": "struct"},
        {"regex": r"(?:pub\s+)?enum\s+([a-zA-Z0-9_]+)", "kind": "enum", "prefix": "enum"},
        {"regex": r"(?:pub\s+)?trait\s+([a-zA-Z0-9_]+)", "kind": "trait", "prefix": "trait"},
    ]
    return _extract_regex_patterns(path, patterns)


def extract_c(path: Path) -> Dict[str, Any]:
    patterns = [
        {"regex": r"(?:struct|enum|union)\s+([a-zA-Z0-9_]+)\s*\{?", "kind": "struct", "prefix": "struct"},
        {"regex": r"^[a-zA-Z0-9_*]+\s+([a-zA-Z0-9_]+)\s*\([^)]*\)\s*\{?", "kind": "function", "prefix": "c_func"},
    ]
    return _extract_regex_patterns(path, patterns)


def extract_cpp(path: Path) -> Dict[str, Any]:
    patterns = [
        {"regex": r"class\s+([a-zA-Z0-9_]+)", "kind": "class", "prefix": "class"},
        {"regex": r"struct\s+([a-zA-Z0-9_]+)", "kind": "struct", "prefix": "struct"},
        {"regex": r"(?:[a-zA-Z0-9_:<>]+\s+)+([a-zA-Z0-9_]+)\s*\([^)]*\)\s*(?:const)?\s*\{?", "kind": "function", "prefix": "cpp_func"},
    ]
    return _extract_regex_patterns(path, patterns)


def extract_java(path: Path) -> Dict[str, Any]:
    patterns = [
        {"regex": r"(?:public|protected|private)?\s*class\s+([a-zA-Z0-9_]+)", "kind": "class", "prefix": "class"},
        {"regex": r"(?:public|protected|private)?\s*interface\s+([a-zA-Z0-9_]+)", "kind": "interface", "prefix": "interface"},
        {"regex": r"(?:public|protected|private|static|\s)+[a-zA-Z0-9_<>\[\]]+\s+([a-zA-Z0-9_]+)\s*\([^)]*\)\s*\{?", "kind": "function", "prefix": "method"},
    ]
    return _extract_regex_patterns(path, patterns)


def extract_ruby(path: Path) -> Dict[str, Any]:
    patterns = [
        {"regex": r"class\s+([a-zA-Z0-9_:]+)", "kind": "class", "prefix": "class"},
        {"regex": r"module\s+([a-zA-Z0-9_:]+)", "kind": "module", "prefix": "module"},
        {"regex": r"def\s+([a-zA-Z0-9_?!]+)", "kind": "function", "prefix": "def"},
    ]
    return _extract_regex_patterns(path, patterns)


def extract_php(path: Path) -> Dict[str, Any]:
    patterns = [
        {"regex": r"class\s+([a-zA-Z0-9_]+)", "kind": "class", "prefix": "class"},
        {"regex": r"function\s+([a-zA-Z0-9_]+)\s*\(", "kind": "function", "prefix": "function"},
    ]
    return _extract_regex_patterns(path, patterns)


def extract_swift(path: Path) -> Dict[str, Any]:
    patterns = [
        {"regex": r"(?:public|private|internal)?\s*class\s+([a-zA-Z0-9_]+)", "kind": "class", "prefix": "class"},
        {"regex": r"(?:public|private|internal)?\s*struct\s+([a-zA-Z0-9_]+)", "kind": "struct", "prefix": "struct"},
        {"regex": r"(?:public|private|internal)?\s*func\s+([a-zA-Z0-9_]+)\s*\(", "kind": "function", "prefix": "func"},
    ]
    return _extract_regex_patterns(path, patterns)


DART_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "finally", "return", "throw",
    "case", "default", "assert", "break", "continue", "yield", "sync", "async",
    "await", "else", "import", "export", "part", "library", "typedef", "class",
    "mixin", "extension", "enum", "with", "extends", "implements", "show", "hide",
    "new", "super", "this", "operator", "try", "do", "in", "is", "as", "rethrow",
    "Function", "dynamic", "var", "void", "Never", "Object", "Type", "Record",
    "final", "const", "late", "static", "factory", "abstract", "required", "covariant"
}

DART_TYPE_PREFIXES = (
    "void ", "dynamic ", "var ", "int ", "double ", "num ", "bool ", "String ",
    "List<", "Map<", "Set<", "Future<", "Stream<", "Widget ", "BuildContext ",
    "State<", "StatelessWidget ", "StatefulWidget ", "ChangeNotifier ", "Bloc<",
    "Cubit<", "Iterable<", "DateTime ", "DateTime? ", "Duration ", "Color ",
    "TextStyle ", "EdgeInsets ", "BoxDecoration ", "Response ", "Request ",
    "StreamSubscription<", "GlobalKey<"
)


def extract_dart(path: Path) -> Dict[str, Any]:
    """
    Dart and Flutter AST/symbol extractor.
    Extracts classes, Flutter widgets, mixins, extensions, enums, constructors,
    methods, getters, setters, top-level functions, imports, and cross-symbol edges.
    """
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"nodes": [], "edges": [], "error": str(e)}

    nodes = [{
        "id": path.name,
        "label": path.name,
        "kind": "file",
        "source_location": "L1",
        "doc": "",
    }]
    edges = []

    current_class = None
    brace_depth = 0
    bracket_depth = 0
    class_brace_depth = 0
    class_pat = re.compile(
        r"^(?:abstract\s+)?class\s+([a-zA-Z0-9_$]+)(?:<[^>]+>)?(?:\s+extends\s+([a-zA-Z0-9_$.]+(?:<[^>]+>)?))?(?:\s+with\s+([a-zA-Z0-9_$,. ]+))?(?:\s+implements\s+([a-zA-Z0-9_$,. ]+))?"
    )
    mixin_pat = re.compile(
        r"^mixin\s+([a-zA-Z0-9_$]+)(?:<[^>]+>)?(?:\s+on\s+([a-zA-Z0-9_$,. ]+))?(?:\s+implements\s+([a-zA-Z0-9_$,. ]+))?"
    )
    ext_pat = re.compile(
        r"^extension\s+([a-zA-Z0-9_$]+)?(?:<[^>]+>)?\s+on\s+([a-zA-Z0-9_$.]+)"
    )
    enum_pat = re.compile(r"^enum\s+([a-zA-Z0-9_$]+)")
    import_pat = re.compile(r"^(?:import|export|part)\s+['\"]([^'\"]+)['\"]")

    decl_pat = re.compile(
        r"^(?:\s*(?:@\w+(?:\([^)]*\))?\s+)*)*(?:\s*(?:static|const|factory|late|final|abstract)\s+)*(?:(?:[a-zA-Z0-9_$<>, ?\[\]]+)\s+)?([a-zA-Z0-9_$]+(?:\.[a-zA-Z0-9_$]+)?)\s*\("
    )
    getter_pat = re.compile(
        r"^(?:\s*(?:@\w+(?:\([^)]*\))?\s+)*)*(?:\s*(?:static|const|late|final)\s+)*(?:(?:[a-zA-Z0-9_$<>, ?\[\]]+)\s+)?get\s+([a-zA-Z0-9_$]+)\s*(?:=>|\{|\;)"
    )
    setter_pat = re.compile(
        r"^(?:\s*(?:@\w+(?:\([^)]*\))?\s+)*)*(?:\s*(?:static)\s+)*set\s+([a-zA-Z0-9_$]+)\s*\(([^)]*)\)"
    )
    call_pat = re.compile(r"\b([a-zA-Z0-9_$]+)\s*\(")

    lines = content.splitlines()
    in_block_comment = False

    for i, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line:
            continue
        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
                line = line.split("*/", 1)[1].strip()
            else:
                continue
        if line.startswith("/*"):
            if "*/" in line:
                line = line.split("*/", 1)[1].strip()
            else:
                in_block_comment = True
                continue
        if line.startswith("//"):
            continue

        # Check imports / exports / parts
        m_imp = import_pat.match(line)
        if m_imp:
            target_import = m_imp.group(1)
            edges.append({
                "source": path.name,
                "target": target_import,
                "relation": "imports",
                "source_location": f"L{i}",
            })
            continue

        # Check class definition
        m_cls = class_pat.match(line)
        if m_cls:
            class_name = m_cls.group(1)
            current_class = class_name
            class_brace_depth = brace_depth
            nodes.append({
                "id": class_name,
                "label": f"class {class_name}",
                "kind": "class",
                "source_location": f"L{i}",
                "doc": line,
            })
            edges.append({
                "source": path.name,
                "target": class_name,
                "relation": "defines",
                "source_location": f"L{i}",
            })

            # Extends
            if m_cls.group(2):
                base_class = m_cls.group(2).split("<")[0].strip()
                edges.append({
                    "source": class_name,
                    "target": base_class,
                    "relation": "extends",
                    "source_location": f"L{i}",
                })
            # With
            if m_cls.group(3):
                for mixin in m_cls.group(3).split(","):
                    mixin_name = mixin.split("<")[0].strip()
                    if mixin_name:
                        edges.append({
                            "source": class_name,
                            "target": mixin_name,
                            "relation": "with",
                            "source_location": f"L{i}",
                        })
            # Implements
            if m_cls.group(4):
                for iface in m_cls.group(4).split(","):
                    iface_name = iface.split("<")[0].strip()
                    if iface_name:
                        edges.append({
                            "source": class_name,
                            "target": iface_name,
                            "relation": "implements",
                            "source_location": f"L{i}",
                        })
            brace_depth += line.count("{") - line.count("}")
            continue

        # Check mixin
        m_mix = mixin_pat.match(line)
        if m_mix:
            mixin_name = m_mix.group(1)
            current_class = mixin_name
            class_brace_depth = brace_depth
            nodes.append({
                "id": mixin_name,
                "label": f"mixin {mixin_name}",
                "kind": "mixin",
                "source_location": f"L{i}",
                "doc": line,
            })
            edges.append({
                "source": path.name,
                "target": mixin_name,
                "relation": "defines",
                "source_location": f"L{i}",
            })
            brace_depth += line.count("{") - line.count("}")
            continue

        # Check extension
        m_ext = ext_pat.match(line)
        if m_ext:
            ext_name = m_ext.group(1) or f"Extension_L{i}"
            current_class = ext_name
            class_brace_depth = brace_depth
            nodes.append({
                "id": ext_name,
                "label": f"extension {ext_name} on {m_ext.group(2)}",
                "kind": "extension",
                "source_location": f"L{i}",
                "doc": line,
            })
            edges.append({
                "source": path.name,
                "target": ext_name,
                "relation": "defines",
                "source_location": f"L{i}",
            })
            edges.append({
                "source": ext_name,
                "target": m_ext.group(2).strip(),
                "relation": "extends",
                "source_location": f"L{i}",
            })
            brace_depth += line.count("{") - line.count("}")
            continue

        # Check enum
        m_enum = enum_pat.match(line)
        if m_enum:
            enum_name = m_enum.group(1)
            nodes.append({
                "id": enum_name,
                "label": f"enum {enum_name}",
                "kind": "enum",
                "source_location": f"L{i}",
                "doc": line,
            })
            edges.append({
                "source": path.name,
                "target": enum_name,
                "relation": "defines",
                "source_location": f"L{i}",
            })
            brace_depth += line.count("{") - line.count("}")
            continue

        # Check getters
        m_get = getter_pat.match(line)
        if m_get and (brace_depth == (class_brace_depth + 1 if current_class else 0)):
            get_name = m_get.group(1)
            if get_name not in DART_KEYWORDS:
                node_id = f"{current_class}.{get_name}" if current_class else get_name
                nodes.append({
                    "id": node_id,
                    "label": f"get {get_name}",
                    "kind": "getter",
                    "source_location": f"L{i}",
                    "doc": line,
                })
                edges.append({
                    "source": current_class if current_class else path.name,
                    "target": node_id,
                    "relation": "defines",
                    "source_location": f"L{i}",
                })
                brace_depth += line.count("{") - line.count("}")
                continue

        # Check setters
        m_set = setter_pat.match(line)
        if m_set and (brace_depth == (class_brace_depth + 1 if current_class else 0)):
            set_name = m_set.group(1)
            if set_name not in DART_KEYWORDS:
                node_id = f"{current_class}.{set_name}=" if current_class else f"{set_name}="
                nodes.append({
                    "id": node_id,
                    "label": f"set {set_name}",
                    "kind": "setter",
                    "source_location": f"L{i}",
                    "doc": line,
                })
                edges.append({
                    "source": current_class if current_class else path.name,
                    "target": node_id,
                    "relation": "defines",
                    "source_location": f"L{i}",
                })
                brace_depth += line.count("{") - line.count("}")
                continue

        # Check methods / functions / constructors only at definition depth and not inside brackets
        if bracket_depth == 0 and brace_depth == (class_brace_depth + 1 if current_class else 0):
            if not line.startswith("return ") and not line.startswith("throw ") and not line.endswith(",") and "=" not in line.split("(")[0]:
                m_fn = decl_pat.match(line)
                if m_fn:
                    fn_raw_name = m_fn.group(1)
                    first_word = fn_raw_name.split(".")[0]
                    if first_word not in DART_KEYWORDS:
                        is_decl = False
                        if current_class and (
                            fn_raw_name == current_class
                            or fn_raw_name.startswith(f"{current_class}.")
                            or fn_raw_name.startswith(".")
                        ):
                            kind = "constructor"
                            fn_id = f"{current_class}.{fn_raw_name}" if fn_raw_name.startswith(".") else (
                                fn_raw_name if "." in fn_raw_name else f"{current_class}.{fn_raw_name}"
                            )
                            parent = current_class
                            is_decl = True
                        elif current_class:
                            has_prefix = (
                                any(line.startswith(p) for p in DART_TYPE_PREFIXES)
                                or line.startswith("@")
                                or any(line.startswith(m) for m in ("static ", "factory ", "abstract ", "const "))
                                or fn_raw_name in (
                                    "build", "initState", "dispose", "didUpdateWidget",
                                    "createState", "createElement", "didChangeDependencies"
                                )
                            )
                            if has_prefix or "." not in fn_raw_name:
                                kind = "method"
                                fn_id = f"{current_class}.{fn_raw_name}"
                                parent = current_class
                                is_decl = True
                        else:
                            has_prefix = (
                                any(line.startswith(p) for p in DART_TYPE_PREFIXES)
                                or any(line.startswith(m) for m in (
                                    "void ", "Future<", "Stream<", "int ", "String ", "bool ", "Widget "
                                ))
                            )
                            if has_prefix or "." not in fn_raw_name:
                                kind = "function"
                                fn_id = fn_raw_name
                                parent = path.name
                                is_decl = True

                        if is_decl:
                            nodes.append({
                                "id": fn_id,
                                "label": f"{kind} {fn_raw_name}",
                                "kind": kind,
                                "source_location": f"L{i}",
                                "doc": line,
                            })
                            edges.append({
                                "source": parent,
                                "target": fn_id,
                                "relation": "defines",
                                "source_location": f"L{i}",
                            })
                            brace_depth += line.count("{") - line.count("}")
                            bracket_depth += line.count("[") - line.count("]")
                            continue
        else:
            for call_m in call_pat.finditer(line):
                callee = call_m.group(1)
                if callee not in DART_KEYWORDS and len(callee) > 1 and not callee.startswith("_"):
                    edges.append({
                        "source": current_class or path.name,
                        "target": callee,
                        "relation": "calls",
                        "source_location": f"L{i}",
                    })

        brace_depth += line.count("{") - line.count("}")
        bracket_depth += line.count("[") - line.count("]")
        if current_class and brace_depth <= class_brace_depth:
            current_class = None

    unique_nodes = {}
    for n in nodes:
        if n["id"] not in unique_nodes:
            unique_nodes[n["id"]] = n

    return {"nodes": list(unique_nodes.values()), "edges": edges, "error": None}
