"""
sot_graph.ignore — Zero-dependency GitIgnore and Ignore Rule Engine.
Supports standard .gitignore, .sotignore syntax, default project exclusions,
and automatic heuristic detection for virtual environments and artifact directories.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Set

DEFAULT_IGNORED_DIRS: Set[str] = {
    ".git",
    ".sot",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "ENV",
    "dist",
    "build",
    "target",
    ".cache",
    ".idea",
    ".vscode",
    "coverage",
    "htmlcov",
    ".coverage",
    ".next",
    ".turbo",
    ".dart_tool",
    "Pods",
    ".gradle",
    "DerivedData",
    "graphify-out",
    "sot_obsidian_vault",
}

DEFAULT_IGNORED_PATTERNS: List[str] = [
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".DS_Store",
    "Thumbs.db",
    "*.log",
    "*.tmp",
    "*.swp",
    "*~",
]


def is_virtualenv_dir(dir_path: str, dir_name: Optional[str] = None) -> bool:
    """
    Detect Python virtual environments by signature files or naming conventions.
    Catches custom names like 'headroom_env', 'my-env', 'test_venv', etc.
    """
    name = dir_name if dir_name is not None else os.path.basename(dir_path)
    lower_name = name.lower()

    # Naming heuristics
    if lower_name.endswith(("_env", "-env")) or lower_name in ("env", "venv", ".venv"):
        return True
    if "venv" in lower_name or "virtualenv" in lower_name:
        return True

    # Signature file heuristics
    try:
        if os.path.isfile(os.path.join(dir_path, "pyvenv.cfg")):
            return True
        if os.path.isfile(os.path.join(dir_path, "bin", "activate")):
            return True
        if os.path.isfile(os.path.join(dir_path, "Scripts", "activate.bat")):
            return True
    except OSError:
        pass

    return False


class IgnoreRule:
    """Represents a single parsed gitignore rule."""
    __slots__ = ("raw", "pattern", "is_negated", "is_dir_only", "regex", "base_dir")

    def __init__(self, raw: str, pattern: str, is_negated: bool, is_dir_only: bool,
                 regex: re.Pattern, base_dir: str):
        self.raw = raw
        self.pattern = pattern
        self.is_negated = is_negated
        self.is_dir_only = is_dir_only
        self.regex = regex
        self.base_dir = base_dir

    def match(self, rel_path: str, is_dir: bool) -> bool:
        if self.is_dir_only and not is_dir:
            return False
        # Normalize relative path to use forward slashes
        norm_path = rel_path.replace("\\", "/")
        if self.base_dir:
            if not norm_path.startswith(self.base_dir):
                return False
            # Strip base_dir prefix
            norm_path = norm_path[len(self.base_dir):].lstrip("/")
        return bool(self.regex.match(norm_path))


def pattern_to_regex(pattern: str) -> re.Pattern:
    """Convert a gitignore glob pattern to a compiled regex Pattern."""
    clean_pat = pattern.rstrip("/").lstrip("/")
    is_anchored = pattern.startswith("/") or ("/" in clean_pat)
    res = []
    
    # If not anchored, match pattern anywhere in the path
    if not is_anchored:
        res.append("(?:^|.*/)")
    else:
        res.append("^")
    i = 0
    n = len(clean_pat)
    while i < n:
        c = clean_pat[i]
        if c == "*":
            if i + 1 < n and clean_pat[i + 1] == "*":
                # Double asterisk '**'
                i += 2
                if i < n and clean_pat[i] == "/":
                    i += 1
                    res.append("(?:.*/)?")
                else:
                    res.append(".*")
            else:
                res.append("[^/]*")
                i += 1
        elif c == "?":
            res.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and clean_pat[j] in "!^":
                j += 1
            if j < n and clean_pat[j] == "]":
                j += 1
            while j < n and clean_pat[j] != "]":
                j += 1
            if j >= n:
                res.append("\\[")
                i += 1
            else:
                stuff = clean_pat[i + 1:j].replace("\\", "\\\\")
                i = j + 1
                if stuff.startswith(("!", "^")):
                    stuff = "^" + stuff[1:]
                res.append(f"[{stuff}]")
        elif c in ".()^$+|{}":
            res.append(f"\\{c}")
            i += 1
        else:
            res.append(c)
            i += 1

    res.append(r"(?:/.*)?$")
    return re.compile("".join(res))


class GitIgnoreMatcher:
    """
    Manages and matches gitignore and sotignore rules across project paths.
    """

    def __init__(self, root_dir: str, extra_ignored_dirs: Optional[Set[str]] = None):
        self.root_dir = os.path.abspath(root_dir)
        self.ignored_dirs = set(DEFAULT_IGNORED_DIRS)
        if extra_ignored_dirs:
            self.ignored_dirs.update(extra_ignored_dirs)
        self.rules: List[IgnoreRule] = []
        self._init_default_rules()
        self._load_root_ignore_files()

    def _init_default_rules(self) -> None:
        for pat in DEFAULT_IGNORED_PATTERNS:
            self.add_pattern(pat, base_dir="")

    def _load_root_ignore_files(self) -> None:
        for fname in (".gitignore", ".sotignore"):
            fpath = os.path.join(self.root_dir, fname)
            if os.path.isfile(fpath):
                self.load_file(fpath, base_dir="")

    def add_pattern(self, pattern: str, base_dir: str = "") -> None:
        raw = pattern.strip()
        if not raw or raw.startswith("#"):
            return

        is_negated = False
        if raw.startswith("!"):
            is_negated = True
            raw = raw[1:].strip()

        is_dir_only = False
        if raw.endswith("/"):
            is_dir_only = True
            raw = raw[:-1]

        if not raw:
            return

        regex = pattern_to_regex(raw)
        norm_base = base_dir.replace("\\", "/").strip("/")
        self.rules.append(IgnoreRule(
            raw=pattern,
            pattern=raw,
            is_negated=is_negated,
            is_dir_only=is_dir_only,
            regex=regex,
            base_dir=norm_base,
        ))

    def load_file(self, file_path: str, base_dir: str = "") -> None:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    self.add_pattern(line, base_dir=base_dir)
        except OSError:
            pass

    def is_ignored(self, abs_or_rel_path: str, is_dir: bool = False) -> bool:
        """
        Check if a path is ignored according to default dirs, heuristics, or gitignore rules.
        """
        if os.path.isabs(abs_or_rel_path):
            try:
                rel_path = os.path.relpath(abs_or_rel_path, self.root_dir)
            except ValueError:
                return True
        else:
            rel_path = abs_or_rel_path

        norm_rel = rel_path.replace("\\", "/").strip("/")
        if not norm_rel or norm_rel == ".":
            return False

        parts = norm_rel.split("/")
        
        # 1. Fast check against hardcoded ignored directory names in any path segment
        for i, segment in enumerate(parts):
            seg_is_dir = is_dir if i == len(parts) - 1 else True
            if seg_is_dir:
                if segment in self.ignored_dirs:
                    return True
                # Heuristic: graphify patterns or temp artifacts
                if segment.startswith(".graphify") or segment.endswith("_vault"):
                    return True

        # 2. Virtual environment heuristic for directory path
        if is_dir and is_virtualenv_dir(os.path.join(self.root_dir, norm_rel), parts[-1]):
            return True

        for rule in reversed(self.rules):
            if rule.match(norm_rel, is_dir):
                return not rule.is_negated
            if rule.is_dir_only and len(parts) > 1:
                # Check parent directories
                for k in range(1, len(parts)):
                    parent_dir = "/".join(parts[:k])
                    if rule.match(parent_dir, is_dir=True):
                        return not rule.is_negated

        return False
