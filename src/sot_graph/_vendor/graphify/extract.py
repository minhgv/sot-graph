"""
src/sot_graph/_vendor/graphify/extract.py — Multi-language AST extractors for sot-graph.
Supports native Python AST extraction + robust structural regex/token extractors for 20+ languages.
Optionally bridges to tree-sitter if tree_sitter and tree_sitter_languages are installed.
"""

import ast
import builtins as _builtins
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Unshadowed bare calls to these names are language builtins, never project
# symbols; callers prune them from pending edges (audit contract: only BARE
# + unshadowed calls may be classified as BUILTIN).
BUILTIN_NAMES = frozenset(dir(_builtins))


def _collect_import_map(tree: ast.AST) -> Dict[str, str]:
    """Map local binding name -> dotted module it was imported from."""
    import_map: Dict[str, str] = {}
    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                top = alias.name.split(".")[0]
                import_map.setdefault(alias.asname or top, alias.name)
        elif isinstance(stmt, ast.ImportFrom):
            module = ("." * stmt.level) + (stmt.module or "")
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                if not stmt.module and stmt.level:
                    # 'from . import name': each binding is itself a submodule
                    # of the current package, not the package root.
                    binding_module = module + alias.name
                else:
                    binding_module = module
                import_map.setdefault(alias.asname or alias.name, binding_module)
    return import_map


def _collect_bound_names(func: ast.AST) -> set:
    """Names bound anywhere inside the function scope (params, assignments,
    for/with/except/comprehension targets, local imports).

    Deliberately an over-approximation: treating a name as shadowed only
    *keeps* a pending edge, never deletes one.
    """
    bound: set = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.asname:
                    bound.add(alias.asname)
                elif alias.name != "*":
                    bound.add(alias.name.split(".")[0])
    return bound


def _dotted_expr(node: ast.AST) -> Optional[str]:
    """Render a Name/Attribute chain ('self.db'), or None for complex exprs."""
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _classify_call(
    call: ast.Call, bound: set, import_map: Dict[str, str]
) -> Optional[Dict[str, Any]]:
    """Classify one call site for the binding-aware resolver.

    Returns None for self-recursion (already filtered by the caller).
    Edge fields: call_kind (BARE|ATTRIBUTE|QUALIFIED|DYNAMIC), receiver,
    import_source, builtin (True only for unshadowed bare builtins).
    """
    func = call.func
    if isinstance(func, ast.Name):
        name = func.id
        import_source = import_map.get(name)
        builtin = (
            not import_source
            and name not in bound
            and name in BUILTIN_NAMES
        )
        return {
            "call_kind": "BARE",
            "receiver": None,
            "import_source": import_source,
            "builtin": builtin,
        }
    if isinstance(func, ast.Attribute):
        receiver = _dotted_expr(func.value)
        import_source = None
        kind = "DYNAMIC"
        if receiver:
            root = receiver.split(".")[0]
            import_source = import_map.get(root)
            kind = "QUALIFIED" if import_source else "ATTRIBUTE"
        return {
            "call_kind": kind,
            "receiver": receiver,
            "import_source": import_source,
            "builtin": False,
        }
    return None


def _format_signature(node: Any, prefix: str, name: str) -> Optional[str]:
    """Render 'def name(args) -> ret' / 'class Name(Base, ...)' contracts."""
    try:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ast.unparse(node.args)  # type: ignore[attr-defined]
            sig = f"{prefix} {name}({args})"
            if node.returns is not None:
                sig += f" -> {ast.unparse(node.returns)}"
            return sig
        if isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]  # type: ignore[arg-type]
            return f"class {name}({', '.join(bases)})" if bases else f"class {name}"
    except Exception:
        return None
    return None


def _span_fields(node: ast.AST) -> Dict[str, Any]:
    """Exact source spans; empty when the runtime AST lacks end positions."""
    return {
        "line_end": getattr(node, "end_lineno", None),
        "col_start": getattr(node, "col_offset", None),
        "col_end": getattr(node, "end_col_offset", None),
    }


def extract_python(path: Path) -> Dict[str, Any]:
    """Extract AST nodes and intra-file call/inheritance edges from Python files."""
    nodes = []
    edges = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(content, filename=str(path))
    except Exception as e:
        return {"nodes": [], "edges": [], "error": str(e)}

    import_map = _collect_import_map(tree)

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
                "signature": _format_signature(node, "class", node.name),
                **_span_fields(node),
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
                "signature": _format_signature(node, prefix, node.name),
                **_span_fields(node),
            })
            edges.append({
                "source": parent,
                "target": func_id,
                "relation": "defines",
                "source_location": f"L{node.lineno}",
            })

            # Detect call expressions inside function with binding context
            bound = _collect_bound_names(node)
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                callee = None
                if isinstance(child.func, ast.Name):
                    if child.func.id == node.name:
                        continue
                    callee = child.func.id
                elif isinstance(child.func, ast.Attribute):
                    attr_recv = child.func.value
                    # super().x() dispatches to the *parent* class's method;
                    # without inheritance resolution any target we pick would
                    # be a guess (and x == own name degenerates to a self-loop).
                    if (isinstance(attr_recv, ast.Call)
                            and isinstance(attr_recv.func, ast.Name)
                            and attr_recv.func.id == "super"):
                        continue
                    # A chained receiver ('user.sudo().write()' inside
                    # 'write') targets another object; qualifying it to the
                    # enclosing method fabricates a self-loop edge.
                    if (child.func.attr == node.name
                            and not (isinstance(attr_recv, ast.Name)
                                     and attr_recv.id in ("self", "cls"))):
                        continue
                    callee = child.func.attr
                if callee is None:
                    continue
                context = _classify_call(child, bound, import_map) or {}
                edges.append({
                    "source": func_id,
                    "target": callee,
                    "relation": "calls",
                    "source_location": f"L{getattr(child, 'lineno', node.lineno)}",
                    **context,
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
                    "import_source": alias.name,
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
                    "import_source": ("." * node.level) + mod,
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
    """JavaScript / TypeScript extractor supporting ES6, TypeScript types, enums, interfaces, and arrow functions."""
    patterns = [
        {"regex": r"(?:export\s+)?(?:default\s+)?class\s+([a-zA-Z0-9_$]+)(?:\s+extends\s+([a-zA-Z0-9_$]+))?", "kind": "class", "prefix": "class"},
        {"regex": r"(?:export\s+)?interface\s+([a-zA-Z0-9_$]+)", "kind": "interface", "prefix": "interface"},
        {"regex": r"(?:export\s+)?type\s+([a-zA-Z0-9_$]+)\s*=", "kind": "type", "prefix": "type"},
        {"regex": r"(?:export\s+)?enum\s+([a-zA-Z0-9_$]+)", "kind": "enum", "prefix": "enum"},
        {"regex": r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*(?:<[^>]*>)?\s*\(", "kind": "function", "prefix": "function"},
        {"regex": r"(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:<[^>]*>)?\s*(?:\([^)]*\)|[a-zA-Z0-9_$]+)(?:\s*:\s*[^=>]+)?\s*=>", "kind": "function", "prefix": "arrow_func"},
        {"regex": r"import\s+.*?from\s+['\"]([^'\"]+)['\"]", "kind": "import", "prefix": "import"},
    ]
    return _extract_regex_patterns(path, patterns)

def _ts_or_regex(
    path: Path,
    language: str,
    patterns: List[Dict[str, Any]],
    regex_postprocess=None,
) -> Dict[str, Any]:
    """Prefer the optional tree-sitter AST extractor; fall back to regex.

    ``regex_postprocess(path, result)`` augments the regex result only — used
    for relations the generic pattern engine cannot express (e.g. Java
    inheritance clauses).
    """
    try:
        from sot_graph.ts_extract import extract_ts

        return extract_ts(path, language)
    except Exception:
        result = _extract_regex_patterns(path, patterns)
        if regex_postprocess is not None:
            regex_postprocess(path, result)
        return result


def extract_go(path: Path) -> Dict[str, Any]:
    """Go language extractor (tree-sitter when [tree-sitter] extra is present)."""
    patterns = [
        {"regex": r"func\s+(?:\([^)]+\)\s+)?([a-zA-Z0-9_]+)\s*\(", "kind": "function", "prefix": "func"},
        {"regex": r"type\s+([a-zA-Z0-9_]+)\s+struct\b", "kind": "struct", "prefix": "type struct"},
        {"regex": r"type\s+([a-zA-Z0-9_]+)\s+interface\b", "kind": "interface", "prefix": "type interface"},
    ]
    return _ts_or_regex(path, "go", patterns)


def extract_rust(path: Path) -> Dict[str, Any]:
    """Rust language extractor (tree-sitter when [tree-sitter] extra is present)."""
    patterns = [
        {"regex": r"(?:pub\s+)?fn\s+([a-zA-Z0-9_]+)\s*\(", "kind": "function", "prefix": "fn"},
        {"regex": r"(?:pub\s+)?struct\s+([a-zA-Z0-9_]+)", "kind": "struct", "prefix": "struct"},
        {"regex": r"(?:pub\s+)?enum\s+([a-zA-Z0-9_]+)", "kind": "enum", "prefix": "enum"},
        {"regex": r"(?:pub\s+)?trait\s+([a-zA-Z0-9_]+)", "kind": "trait", "prefix": "trait"},
    ]
    return _ts_or_regex(path, "rust", patterns)


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


JAVA_TYPE_HEADER_PAT = re.compile(
    r"\b(?:class|interface|enum|record)\s+([A-Za-z_][A-Za-z0-9_]*)"
    r"(?:<(?:[^<>]*<[^<>]*>)?[^<>]*>)?"      # type parameters, one nesting level
    r"(?:\s*\([^)]*\))?"                     # record component list
    r"(?:\s+extends\s+([A-Za-z_][A-Za-z0-9_.<>,\s]*?))?"
    r"(?:\s+implements\s+([A-Za-z_][A-Za-z0-9_.<>,\s]*?))?"
    r"(?:\s+permits\s+[A-Za-z_][A-Za-z0-9_.<>,\s]*?)?"
    r"\s*\{"
)


def _java_short_type(raw: str) -> str:
    raw = re.split(r"<", raw.strip(), maxsplit=1)[0].strip()
    raw = raw.rsplit(".", 1)[-1].strip()
    # Only whole identifiers survive; stray generics debris does not.
    return raw if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw) else ""


def _java_split_types(clause: str) -> List[str]:
    # Split on commas that sit outside generic angle brackets, so
    # BaseRepo<Map<String, String>> stays a single type.
    parts: List[str] = []
    depth = 0
    current: List[str] = []
    for ch in clause:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def _java_inheritance_edges(path: Path, result: Dict[str, Any]) -> None:
    """Augment the regex fallback with extends/implements header edges."""
    try:
        source_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for match in JAVA_TYPE_HEADER_PAT.finditer(source_text):
        name, extends_clause, implements_clause = match.groups()
        line_no = source_text.count("\n", 0, match.start()) + 1
        for relation, clause in (
            ("extends", extends_clause),
            ("implements", implements_clause),
        ):
            if not clause:
                continue
            for base in _java_split_types(clause):
                base = _java_short_type(base)
                if base:
                    result["edges"].append({
                        "source": name,
                        "target": base,
                        "relation": relation,
                        "source_location": f"L{line_no}",
                    })


def extract_java(path: Path) -> Dict[str, Any]:
    patterns = [
        {"regex": r"(?:public|protected|private)?\s*class\s+([a-zA-Z0-9_]+)", "kind": "class", "prefix": "class"},
        {"regex": r"(?:public|protected|private)?\s*interface\s+([a-zA-Z0-9_]+)", "kind": "interface", "prefix": "interface"},
        {"regex": r"(?:public|protected|private)?\s*enum\s+([a-zA-Z0-9_]+)", "kind": "enum", "prefix": "enum"},
        {"regex": r"(?:public|protected|private)?\s*record\s+([a-zA-Z0-9_]+)", "kind": "record", "prefix": "record"},
        {"regex": r"(?:public|protected|private|static|\s)+[a-zA-Z0-9_<>\[\]]+\s+([a-zA-Z0-9_]+)\s*\([^)]*\)\s*\{?", "kind": "function", "prefix": "method"},
    ]
    return _ts_or_regex(path, "java", patterns, regex_postprocess=_java_inheritance_edges)


def extract_ruby(path: Path) -> Dict[str, Any]:
    patterns = [
        {"regex": r"class\s+([a-zA-Z0-9_:]+)", "kind": "class", "prefix": "class"},
        {"regex": r"module\s+([a-zA-Z0-9_:]+)", "kind": "module", "prefix": "module"},
        {"regex": r"def\s+([a-zA-Z0-9_?!]+)", "kind": "function", "prefix": "def"},
    ]
    return _extract_regex_patterns(path, patterns)


PHP_TYPE_PAT = re.compile(
    r"^(?:(?:abstract|final|readonly)\s+)*(class|interface|trait|enum)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)(.*)$"
)
PHP_EXTENDS_PAT = re.compile(r"\bextends\s+([A-Za-z_][A-Za-z0-9_\\]*)")
PHP_IMPLEMENTS_PAT = re.compile(r"\bimplements\s+([A-Za-z0-9_\\,\s]+)")
PHP_USE_IN_TYPE_PAT = re.compile(
    r"^use\s+([A-Za-z_][A-Za-z0-9_\\]*)((?:\s*,\s*[A-Za-z_][A-Za-z0-9_\\]*)*)\s*;"
)
PHP_USE_IMPORT_PAT = re.compile(
    r"^use\s+(?:function\s+|const\s+)?([A-Za-z_][A-Za-z0-9_\\]*)"
    r"(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?\s*;"
)
PHP_METHOD_PAT = re.compile(
    r"^(?:(?:public|protected|private|static|abstract|final|readonly)\s+)*"
    r"function\s+(&?[A-Za-z_][A-Za-z0-9_]*)\s*\("
)
PHP_THIS_CALL_PAT = re.compile(r"\$this->\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")
PHP_SELF_CALL_PAT = re.compile(r"\b(?:self|static)\s*::\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")
PHP_PARENT_CALL_PAT = re.compile(r"\bparent\s*::\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")
PHP_STATIC_CALL_PAT = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\s*::\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")
PHP_NEW_PAT = re.compile(r"\bnew\s+\\?([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def _php_short_name(fqn: str) -> str:
    """Last segment of a PHP qualified name: 'App\\Contracts\\Bar' -> 'Bar'."""
    return fqn.rsplit("\\", 1)[-1].strip()


def extract_php(path: Path) -> Dict[str, Any]:
    """PHP extractor: classes, interfaces, traits, enums, class-qualified
    methods, inheritance/trait edges, imports, and scoped call sites.

    Line-based state machine in the spirit of the Dart extractor: comments are
    stripped, brace depth tracks the enclosing type/method so symbols get
    stable ids ('PaymentGateway.charge') instead of colliding bare names.
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

    current_type: Optional[str] = None
    current_method: Optional[str] = None
    brace_depth = 0
    type_brace_depth = 0
    method_brace_depth = 0

    lines = content.splitlines()
    i = 0
    in_block_comment = False

    def _inject_tail(line_text: str) -> None:
        """Re-queue the statements after a single-line '{' so compact PHP
        ('class A { function x() {...} }') is still walked statement by
        statement. Braces are blanked: the declaring line already counted
        them for depth tracking."""
        if "{" not in line_text:
            return
        tail = line_text.split("{", 1)[1]
        tail = tail.replace("{", " ").replace("}", " ").strip()
        if tail:
            lines.insert(i, tail)

    while i < len(lines):
        raw_line = lines[i]
        i += 1
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
        if not line or line.startswith("//") or line.startswith("#"):
            continue

        # Type declarations (class/interface/trait/enum), with a bounded
        # lookahead for headers that span multiple lines.
        m_type = PHP_TYPE_PAT.match(line)
        if m_type:
            kind, name, rest = m_type.group(1), m_type.group(2), m_type.group(3)
            header = rest
            lookahead = 0
            while "{" not in header and ";" not in header and lookahead < 5 and i < len(lines):
                nxt = lines[i].strip()
                if nxt.startswith("//") or nxt.startswith("#") or nxt.startswith("*"):
                    break
                header += " " + nxt
                i += 1
                lookahead += 1
            current_type = name
            current_method = None
            type_brace_depth = brace_depth
            nodes.append({
                "id": name,
                "label": f"{kind} {name}",
                "kind": kind,
                "source_location": f"L{i - lookahead}",
                "doc": line,
            })
            edges.append({
                "source": path.name,
                "target": name,
                "relation": "defines",
                "source_location": f"L{i - lookahead}",
            })
            m_ext = PHP_EXTENDS_PAT.search(header)
            if m_ext:
                edges.append({
                    "source": name,
                    "target": _php_short_name(m_ext.group(1)),
                    "relation": "extends",
                    "source_location": f"L{i - lookahead}",
                })
            m_imp = PHP_IMPLEMENTS_PAT.search(header)
            if m_imp:
                for iface in m_imp.group(1).split(","):
                    iface = iface.strip()
                    # Stop at any trailing '{' that leaked into the capture.
                    iface = iface.split("{", 1)[0].strip()
                    if iface:
                        edges.append({
                            "source": name,
                            "target": _php_short_name(iface),
                            "relation": "implements",
                            "source_location": f"L{i - lookahead}",
                        })
            _inject_tail(line)
            # Count braces across the whole consumed header: the '{' may sit
            # on a lookahead line, and missing it desynchronizes scope exit.
            consumed = line + " " + header
            brace_depth += consumed.count("{") - consumed.count("}")
            continue

        m_use = PHP_USE_IN_TYPE_PAT.match(line) if current_type else None
        if m_use:
            names = [m_use.group(1)] + [
                n.strip() for n in (m_use.group(2) or "").split(",") if n.strip()
            ]
            for used in names:
                edges.append({
                    "source": current_type,
                    "target": _php_short_name(used),
                    "relation": "uses",
                    "source_location": f"L{i}",
                })
            continue
        if not current_type:
            m_import = PHP_USE_IMPORT_PAT.match(line)
            if m_import:
                edges.append({
                    "source": path.name,
                    "target": _php_short_name(m_import.group(1)),
                    "relation": "imports",
                    "source_location": f"L{i}",
                })
                continue

        m_method = PHP_METHOD_PAT.match(line)
        if m_method:
            func_name = m_method.group(1).lstrip("&")
            if current_type:
                method_id = f"{current_type}.{func_name}"
                nodes.append({
                    "id": method_id,
                    "label": f"function {func_name}",
                    "kind": "method",
                    "source_location": f"L{i}",
                    "doc": line,
                })
                edges.append({
                    "source": current_type,
                    "target": method_id,
                    "relation": "defines",
                    "source_location": f"L{i}",
                })
            else:
                method_id = func_name
                nodes.append({
                    "id": method_id,
                    "label": f"function {func_name}",
                    "kind": "function",
                    "source_location": f"L{i}",
                    "doc": line,
                })
                edges.append({
                    "source": path.name,
                    "target": method_id,
                    "relation": "defines",
                    "source_location": f"L{i}",
                })
            current_method = method_id
            method_brace_depth = brace_depth
            _inject_tail(line)
            brace_depth += line.count("{") - line.count("}")
            continue

        # Call sites, attributed to the enclosing method (or type).
        if current_method or current_type:
            call_src = current_method or current_type
            for m in PHP_PARENT_CALL_PAT.finditer(line):
                edges.append({
                    "source": call_src,
                    "target": m.group(1),
                    "relation": "calls",
                    "source_location": f"L{i}",
                    # 'super', not 'parent': the dispatcher's qualification
                    # treats the literal 'parent' as same-class scope, which
                    # would fabricate parent::__construct() self-loops.
                    "receiver": "super",
                })
            for m in PHP_THIS_CALL_PAT.finditer(line):
                edges.append({
                    "source": call_src,
                    "target": m.group(1),
                    "relation": "calls",
                    "source_location": f"L{i}",
                    "receiver": "self",
                })
            for m in PHP_SELF_CALL_PAT.finditer(line):
                edges.append({
                    "source": call_src,
                    "target": m.group(1),
                    "relation": "calls",
                    "source_location": f"L{i}",
                    "receiver": "self",
                })
            for m in PHP_STATIC_CALL_PAT.finditer(line):
                edges.append({
                    "source": call_src,
                    "target": f"{m.group(1)}.{m.group(2)}",
                    "relation": "calls",
                    "source_location": f"L{i}",
                    "receiver": m.group(1),
                })
            for m in PHP_NEW_PAT.finditer(line):
                edges.append({
                    "source": call_src,
                    "target": m.group(1),
                    "relation": "calls",
                    "source_location": f"L{i}",
                    "receiver": None,
                })

        had_brace = "{" in line or "}" in line
        brace_depth += line.count("{") - line.count("}")
        if had_brace:
            if current_method and brace_depth <= method_brace_depth:
                current_method = None
            if current_type and brace_depth <= type_brace_depth:
                current_type = None
                current_method = None

    return {"nodes": nodes, "edges": edges, "error": None}


def extract_swift(path: Path) -> Dict[str, Any]:
    patterns = [
        {"regex": r"(?:public|private|internal)?\s*class\s+([a-zA-Z0-9_]+)", "kind": "class", "prefix": "class"},
        {"regex": r"(?:public|private|internal)?\s*struct\s+([a-zA-Z0-9_]+)", "kind": "struct", "prefix": "struct"},
        {"regex": r"(?:public|private|internal)?\s*func\s+([a-zA-Z0-9_]+)\s*\(", "kind": "function", "prefix": "func"},
    ]
    return _ts_or_regex(path, "swift", patterns)


def extract_kotlin(path: Path) -> Dict[str, Any]:
    patterns = [
        {"regex": r"(?:public|private|internal)?\s*class\s+([a-zA-Z0-9_]+)", "kind": "class", "prefix": "class"},
        {"regex": r"\bfun\s+([a-zA-Z0-9_]+)\s*\(", "kind": "function", "prefix": "fun"},
        {"regex": r"\bobject\s+([a-zA-Z0-9_]+)", "kind": "object", "prefix": "object"},
    ]
    return _ts_or_regex(path, "kotlin", patterns)


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
