"""
sot_graph.adapters.claude - Claude Code & Universal MCP Harness Adapter.
"""

from pathlib import Path
import json
import sys

CLAUDE_SECTION = """
## SOT-Graph Knowledge Reuse Protocol (SSOT)
- **Zero Hallucinated Anchors**: The filesystem is the single source of truth. Always ground symbol existence using `sot search` or MCP `sot_search`.
- **Pre-Implementation Verification**: Before writing new helper utilities, search if a verified implementation exists (`[STRONG]` verdict).
- **Architectural Blast Radius**: Before changing core functions/classes, run `sot explore "<symbol>"` or MCP `sot_explore` to verify all incoming references.
- **Drift Synchronization**: After refactoring, renaming, or deleting files, run `sot reconcile` to purge dead paths.
"""


def _merge_mcp_json(mcp_path: Path, python_bin: str) -> None:
    """Merge SOT-Graph into standard mcp.json format."""
    data = {}
    if mcp_path.exists():
        try:
            data = json.loads(mcp_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
        data["mcpServers"] = {}

    data["mcpServers"]["sot-graph"] = {
        "command": python_bin,
        "args": ["-m", "sot_graph.cli", "mcp"],
    }

    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _append_claude_rules(claude_md_path: Path) -> None:
    """Append SOT-Graph protocol to CLAUDE.md if not already present."""
    if not claude_md_path.exists():
        claude_md_path.parent.mkdir(parents=True, exist_ok=True)
        claude_md_path.write_text(f"# CLAUDE Agent Rules\n{CLAUDE_SECTION}", encoding="utf-8")
        return

    content = claude_md_path.read_text(encoding="utf-8")
    if "SOT-Graph Knowledge Reuse Protocol" not in content:
        claude_md_path.write_text(f"{content.rstrip()}\n\n{CLAUDE_SECTION}\n", encoding="utf-8")


def setup_claude(root: Path, global_install: bool = True, workspace_install: bool = True) -> list[str]:
    """Configure Claude Code and Cursor harness at workspace and/or global levels."""
    installed = []
    python_bin = sys.executable or "python3"

    # Workspace level
    if workspace_install:
        # 1. .mcp.json (Standard Claude / Zed / Windsurf)
        ws_mcp = root / ".mcp.json"
        _merge_mcp_json(ws_mcp, python_bin)
        installed.append(str(ws_mcp))

        # 2. .cursor/mcp.json (Cursor IDE)
        cursor_mcp = root / ".cursor" / "mcp.json"
        _merge_mcp_json(cursor_mcp, python_bin)
        installed.append(str(cursor_mcp))

        # 3. .claude/CLAUDE.md
        claude_md = root / ".claude" / "CLAUDE.md"
        _append_claude_rules(claude_md)
        installed.append(str(claude_md))

    # Global level
    if global_install:
        home = Path.home()
        global_mcp = home / ".claude" / "mcp.json"
        _merge_mcp_json(global_mcp, python_bin)
        installed.append(str(global_mcp))

        global_claude_md = home / ".claude" / "CLAUDE.md"
        _append_claude_rules(global_claude_md)
        installed.append(str(global_claude_md))

    return installed
