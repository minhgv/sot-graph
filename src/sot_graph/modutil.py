"""
sot_graph.modutil — Shared dotted-module helpers.

Both the extractor (when computing Fully Qualified Names) and the pending-edge
resolver (when classifying imports as project vs external) need to derive
Python dotted module names from project-relative file paths. The rules live
here so the two sides can never drift apart.
"""

from __future__ import annotations

from typing import Iterable, Set

__all__ = [
    "dotted_module",
    "module_candidates",
    "normalize_import",
    "project_module_names",
]

# Common layout prefixes that are not importable package names.
_STRIP_ROOT_DIRS = {"src", "lib", "source"}

_STEM_STRIP_SUFFIXES = (".pyi", ".py")

# Bound on how many trailing path segments fold into a dotted module name.
_MAX_SUFFIX_DEPTH = 8


def dotted_module(rel_path: str) -> str:
    """'src/sot_graph/db.py' -> 'sot_graph.db'; 'pkg/__init__.py' -> 'pkg'.

    A leading ``src``/``lib`` segment is dropped because it is a layout
    convention rather than an importable package. ``__init__`` collapses to
    the package itself. Non-Python paths fall back to the stem-joined form.
    """
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p and p not in (".", "..")]
    if not parts:
        return ""
    if len(parts) > 1 and parts[0] in _STRIP_ROOT_DIRS:
        parts = parts[1:]
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        last = parts[-1] if parts else ""
        for suffix in _STEM_STRIP_SUFFIXES:
            if last.endswith(suffix):
                parts = parts[:-1] + [last[: -len(suffix)]]
                break
    return ".".join(p for p in parts if p)


def module_candidates(rel_path: str) -> Set[str]:
    """Every dotted name a single file may legitimately be imported as.

    For 'src/sot_graph/db.py': {'sot_graph.db', 'db', 'sot_graph'} — the full
    path-derived name, the bare last segment (relative imports), and the
    package prefixes.
    """
    dotted = dotted_module(rel_path)
    if not dotted:
        return set()
    candidates = {dotted, dotted.rsplit(".", 1)[-1]}
    parts = dotted.split(".")
    for i in range(1, len(parts)):
        candidates.add(".".join(parts[:i]))
    return candidates


def normalize_import(import_source: str | None) -> str:
    """Strip relative-import dots: '..pkg.mod' -> 'pkg.mod'."""
    if not import_source:
        return ""
    return import_source.lstrip(".").strip()


def project_module_names(paths: Iterable[str]) -> Set[str]:
    """Every dotted suffix a project file may be imported as.

    ``file_journal`` stores absolute paths, so names are derived from the
    dotted suffixes of each path (stem-stripped, ``__init__`` collapsed).
    For '.../src/sot_graph/db.py' this yields {'db', 'sot_graph.db',
    'src.sot_graph.db', ...}. Suffixes that are not valid Python identifiers
    can never match a real import statement, so they are harmless noise.
    """
    names: Set[str] = set()
    for path in paths:
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        if not parts:
            continue
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            last = parts[-1]
            for suffix in _STEM_STRIP_SUFFIXES:
                if last.endswith(suffix):
                    parts = parts[:-1] + [last[: -len(suffix)]]
                    break
        for k in range(1, min(len(parts), _MAX_SUFFIX_DEPTH) + 1):
            names.add(".".join(parts[-k:]))
    return names


def import_is_project(import_source: str | None, project_names: Set[str]) -> bool:
    """True when a normalized import refers to a module inside the project."""
    imp = normalize_import(import_source)
    if not imp:
        return False
    return imp in project_names
