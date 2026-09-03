#!/usr/bin/env python3
"""Consistency gate for harness-adapter documentation.

Adapter docs (the zcode/claude/omp/opencode/antigravity markdown constants,
their slash-command payloads, and adapters/AGENTS.md) hand-maintain a
"Quick CLI & MCP Tool Reference". Audit finding P2 surfaces-20 caught them
drifting from reality: flags and MCP tool names that do not exist
(`--max-hops` on `sot explore`, `sot clean --purge-missing`,
unregistered `sot_rename`...). Hand-maintained tables WILL drift again.

Ground truth is derived from the code that defines reality:
  - CLI commands/flags  <- cli.build_parser()
  - MCP tool names      <- `types.Tool(name="sot_...")` in mcp_server.py

Every backticked `sot <cmd> [--flag ...]` usage and every `sot_*` tool
mention in the doc corpus is validated against that truth.

Modes:
  (default)      check docs; exit 1 with a drift report on mismatch
  --emit-table   print a canonical quick-reference table generated from
                 build_parser() + the MCP registry, so future docs can be
                 pasted instead of hand-written

Usage:
  python scripts/adapter_docs_check.py
  python scripts/adapter_docs_check.py --emit-table
"""
from __future__ import annotations

import argparse
import importlib
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

ADAPTER_MODULES = ["zcode", "claude", "omp", "opencode", "antigravity"]
ADAPTERS_DIR = REPO_ROOT / "src" / "sot_graph" / "adapters"
MCP_SERVER_PY = ADAPTERS_DIR.parent / "mcp_server.py"

# Adapters that register NATIVE harness tools of their own (OMP extension,
# OpenCode plugin). Docs from these adapters may reference their native
# registries in addition to the shared MCP server; the other surfaces
# (zcode/claude/antigravity markdown, AGENTS.md, README) may only
# reference the MCP registry.
NATIVE_TOOL_SOURCES = {
    "omp": ["omp_extension.ts"],
    "opencode": ["opencode_tools.json", "opencode_plugin.ts"],
}
# Doc surfaces outside the adapter modules, validated against MCP only.
# README documents the whole product (incl. the OMP/OpenCode native tool
# surfaces), so it is held to the union of every registry.
STANDALONE_DOC_FILES = {"AGENTS.md": "mcp", "README.md": "all"}

# Words that match the sot_* shape but are not MCP tool claims.
MCP_MENTION_EXEMPT = {"sot_graph"}

# CLI subcommand <-> MCP tool pairs whose names do not correspond 1:1.
# Used by --emit-table only; checking needs no mapping.
CLI_TO_MCP_OVERRIDES: Dict[str, str] = {
    "log": "sot_git_history",
    "verify": "sot_verify_drift",
    "report": "sot_architecture_report",
    "cluster": "sot_communities",
    "diff-impact": "sot_diff_impact",
    "providers": "sot_providers_sync",
}


# ---------------------------------------------------------------------------
# Doc corpus collection
# ---------------------------------------------------------------------------

def _iter_strings(obj: Any, depth: int = 0) -> Iterator[str]:
    """Yield every str inside a nested dict/list/tuple/set structure."""
    if depth > 4:
        return
    if isinstance(obj, str):
        if len(obj) > 40:
            yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_strings(value, depth + 1)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            yield from _iter_strings(item, depth + 1)


def collect_doc_sources() -> List[Tuple[str, str, str]]:
    """Return [(label, doc_text, harness)] for every adapter-authored surface.

    ``harness`` selects the tool ground truth the doc is held to: an
    adapter module name (native registries + MCP) or "mcp" (MCP only).
    """
    sources: List[Tuple[str, str, str]] = []
    for mod_name in ADAPTER_MODULES:
        module = importlib.import_module(f"sot_graph.adapters.{mod_name}")
        for attr, value in sorted(vars(module).items()):
            if attr.startswith("_"):
                continue
            for text in _iter_strings(value):
                if "`sot " in text or re.search(r"\bsot_[a-z_]+\b", text):
                    sources.append(
                        (f"adapters/{mod_name}.py:{attr}", text, mod_name)
                    )
    agents_md = ADAPTERS_DIR / "AGENTS.md"
    if agents_md.exists():
        text = agents_md.read_text(encoding="utf-8")
        if "`sot " in text or re.search(r"\bsot_[a-z_]+\b", text):
            sources.append(("adapters/AGENTS.md", text, "mcp"))
    for name, harness in STANDALONE_DOC_FILES.items():
        path = REPO_ROOT / name
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if "`sot " in text or re.search(r"\bsot_[a-z_]+\b", text):
                sources.append((name, text, harness))
    return sources


# ---------------------------------------------------------------------------
# Ground truth: CLI parser
# ---------------------------------------------------------------------------

def _subparser_choices(parser: Any) -> Dict[str, Any]:
    if not getattr(parser, "_subparsers", None):
        return {}
    for action in parser._subparsers._group_actions:  # noqa: SLF001
        if hasattr(action, "choices") and action.choices:
            return action.choices
    return {}


def _parser_flags(parser: Any) -> set:
    flags = set()
    for action in parser._actions:  # noqa: SLF001
        flags.update(action.option_strings)
    return flags


class CliTruth:
    """Subcommand tree + per-subcommand registered flags from build_parser()."""

    def __init__(self) -> None:
        from sot_graph.cli import build_parser

        self.main = build_parser()
        self.main_flags = _parser_flags(self.main)

    def resolve(self, tokens: List[str]) -> Tuple[List[str], Any]:
        """Walk nested subparsers; return (command_path, leaf_parser)."""
        parts: List[str] = []
        current = self.main
        for raw in tokens:
            token = _strip_syntax(raw)
            choices = _subparser_choices(current)
            if token in choices:
                parts.append(token)
                current = choices[token]
            else:
                break
        return parts, current

    def allowed_flags(self, leaf: Any) -> set:
        return _parser_flags(leaf) | self.main_flags


def _strip_syntax(token: str) -> str:
    return token.strip("[]()<>\"'").split("=", 1)[0]


def _claimed_flag(token: str) -> Optional[str]:
    cleaned = _strip_syntax(token)
    if not cleaned.startswith("-") or len(cleaned) < 2:
        return None
    if cleaned.lstrip("-").replace(".", "").isdigit():
        return None  # negative number, not a flag
    return cleaned


def check_cli_claim(
    claim: str, truth: CliTruth
) -> List[str]:
    """Validate one backticked `sot ...` usage string."""
    tokens = claim.strip("`").split()
    if tokens and tokens[0] == "sot":
        tokens = tokens[1:]
    if not tokens:
        return []
    command_path, leaf = truth.resolve(tokens)
    errors: List[str] = []
    if not command_path:
        first = _strip_syntax(tokens[0])
        if first.startswith("-"):
            return []  # `sot --db X` style global usage; nothing claimed here
        return [f"unknown subcommand '{first}'"]
    rest = tokens[len(command_path):]
    allowed = truth.allowed_flags(leaf)
    for token in rest:
        flag = _claimed_flag(token)
        if flag is not None and flag not in allowed:
            errors.append(
                f"'sot {' '.join(command_path)}' has no flag '{flag}' "
                f"(registered: {', '.join(sorted(allowed)) or 'none'})"
            )
    return errors


# ---------------------------------------------------------------------------
# Ground truth: MCP tool registry
# ---------------------------------------------------------------------------

def registered_mcp_tools() -> set:
    text = MCP_SERVER_PY.read_text(encoding="utf-8")
    return set(re.findall(r'types\.Tool\(name="(sot_[a-z_]+)"', text))


def native_tools(harness: str) -> set:
    """Tool names registered natively by an adapter's own harness files."""
    tools: set = set()
    for filename in NATIVE_TOOL_SOURCES.get(harness, []):
        path = ADAPTERS_DIR / filename
        if not path.exists():
            continue
        tools.update(
            re.findall(r'["\']?name["\']?\s*[:=]\s*["\'](sot_[a-z_]+)["\']',
                       path.read_text(encoding="utf-8"))
        )
    return tools


def allowed_tools(harness: str) -> set:
    if harness == "mcp":
        return registered_mcp_tools()
    if harness == "all":  # whole-product docs: every registry counts
        every = registered_mcp_tools()
        for native in NATIVE_TOOL_SOURCES:
            every |= native_tools(native)
        return every
    return registered_mcp_tools() | native_tools(harness)


# ---------------------------------------------------------------------------
# Checking / emitting
# ---------------------------------------------------------------------------

def check() -> List[str]:
    """Return a sorted list of human-readable drift violations."""
    truth = CliTruth()
    violations: List[str] = []
    for label, text, harness in collect_doc_sources():
        tools = allowed_tools(harness)
        for claim in set(re.findall(r"`sot [^`]*`", text)):
            for error in check_cli_claim(claim, truth):
                violations.append(f"{label}: `{claim}` — {error}")
        for mention in set(re.findall(r"\bsot_[a-z_]+\b", text)):
            if mention in MCP_MENTION_EXEMPT:
                continue
            if mention not in tools:
                where = ("mcp_server.py"
                         if harness == "mcp"
                         else f"mcp_server.py or the {harness} native registries")
                violations.append(
                    f"{label}: tool '{mention}' is not registered in {where}"
                )
    return sorted(violations)


def emit_table() -> str:
    """Generate the canonical Quick CLI & MCP Tool Reference table."""
    truth = CliTruth()
    mcp_tools = registered_mcp_tools()
    by_suffix: Dict[str, str] = {}
    for tool in mcp_tools:
        by_suffix[tool[len("sot_"):]] = tool

    def mcp_for(command_path: List[str]) -> str:
        key = "-".join(command_path)
        if key in CLI_TO_MCP_OVERRIDES:
            return CLI_TO_MCP_OVERRIDES[key]
        return by_suffix.get(key.replace("-", "_"), "CLI only")

    rows = ["| CLI Command | Flags | MCP Tool |",
            "| :--- | :--- | :--- |"]
    for name, parser in sorted(_subparser_choices(truth.main).items()):
        flags = sorted(
            f for f in _parser_flags(parser) if f.startswith("--")
        )
        nested = sorted(_subparser_choices(parser))
        command = f"`sot {name}`"
        if nested:
            for sub in nested:
                sub_flags = sorted(
                    f for f in _parser_flags(_subparser_choices(parser)[sub])
                    if f.startswith("--")
                )
                tool = mcp_for([name, sub]) if sub in ("inventory", "steps", "bundle") else "CLI only"
                rows.append(
                    f"| `{name} {sub}` | {', '.join(sub_flags) or '—'} | "
                    f"{tool} |"
                )
            continue
        rows.append(f"| {command} | {', '.join(flags) or '—'} | {mcp_for([name])} |")
    return "\n".join(rows)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--emit-table", action="store_true",
                    help="print the generated quick-reference table and exit")
    args = ap.parse_args(argv)

    if args.emit_table:
        print(emit_table())
        return 0

    violations = check()
    if violations:
        print(f"❌ Adapter docs drifted from CLI/MCP reality "
              f"({len(violations)} violation(s)):")
        for violation in violations:
            print(f"   - {violation}")
        print("\nFix the docs, or regenerate the reference table with "
              "'python scripts/adapter_docs_check.py --emit-table'.")
        return 1
    print("✅ Adapter docs consistent with build_parser() and MCP registry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
