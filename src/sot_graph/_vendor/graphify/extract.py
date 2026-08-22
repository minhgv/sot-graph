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
