"""
sot_graph.adapters.opencode - OpenCode Harness Adapter.
"""

from pathlib import Path
import json
import shutil
import sys

OPENCODE_SKILL_MARKDOWN = """---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, and graph analytics.
---

# sot-graph for OpenCode

Use SOT-Graph to ground OpenCode agent actions in physical filesystem reality:

## 1. Verified Code Search (Before Writing Code)
Search the knowledge graph with Trust Verdicts:
```bash
sot search "<query>" -n 5
```
Or use the MCP tool `sot_search(query="...")` if SOT MCP server is enabled.

Trust Verdicts:
- `[STRONG]`: High confidence — file and symbols physically verified on disk.
- `[WEAK]`: Semantic match only — inspect before relying on it.
- `[REBUILT]`: File has moved location; use the updated path.

## 2. AST Dependency Exploration (Before Modifying Functions)
Trace cross-file call graphs and references:
```bash
sot explore "<symbol_or_function_name>" --depth 2
```
Or use the MCP tool `sot_explore(target="...")`.

## 3. Drift Audit & Self-Healing
```bash
sot verify --deep        # Check for phantom anchors and dead paths
sot reconcile            # Re-synchronize SQLite DB with disk state
```

## 4. Knowledge Anchoring
Record non-obvious architecture decisions and tricky bug fixes:
```bash
sot insert --title "<topic>" --body "<details>" --keywords "k1,k2"
```
"""


def _merge_opencode_json(config_path: Path, python_bin: str) -> None:
    """Merge SOT-Graph MCP configuration and skill permissions into opencode.json safely."""
    data = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    # 1. Add / update MCP entry
    if "mcp" not in data or not isinstance(data["mcp"], dict):
        data["mcp"] = {}

    data["mcp"]["sot-graph"] = {
        "type": "local",
        "command": [python_bin, "-m", "sot_graph.cli", "mcp"],
        "enabled": True,
    }

    # 2. Add skill permissions
    if "permission" not in data or not isinstance(data["permission"], dict):
        data["permission"] = {}

    # Ensure skill is allowed
    data["permission"]["skill"] = "allow"

    for perm_key in ("read", "glob", "grep", "list", "external_directory"):
        if perm_key not in data["permission"] or not isinstance(data["permission"][perm_key], dict):
            data["permission"][perm_key] = {}
        data["permission"][perm_key]["~/.config/opencode/skill/**"] = "allow"
        data["permission"][perm_key]["~/.config/opencode/skills/**"] = "allow"
        data["permission"][perm_key][".opencode/skills/**"] = "allow"

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def setup_opencode(root: Path, global_install: bool = True, workspace_install: bool = True) -> list[str]:
    """Configure OpenCode harness at workspace and/or global levels."""
    installed = []
    python_bin = sys.executable or "python3"
    plugin_src = Path(__file__).resolve().parent / "opencode_plugin.ts"

    # Workspace level (.opencode/)
    if workspace_install:
        opencode_dir = root / ".opencode"
        skill_dir = opencode_dir / "skills" / "sot-graph"
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Write workspace skill
        (skill_dir / "SKILL.md").write_text(OPENCODE_SKILL_MARKDOWN, encoding="utf-8")
        installed.append(str(skill_dir / "SKILL.md"))

        # Write workspace opencode.json
        ws_config = opencode_dir / "opencode.json"
        _merge_opencode_json(ws_config, python_bin)
        installed.append(str(ws_config))

    # Global level (~/.config/opencode/)
    if global_install:
        home = Path.home()
        global_cfg_dir = home / ".config" / "opencode"
        global_skill_dir = global_cfg_dir / "skill" / "sot-graph"
        global_plugin_dir = global_cfg_dir / "plugins" / "sot-graph"

        global_skill_dir.mkdir(parents=True, exist_ok=True)
        global_plugin_dir.mkdir(parents=True, exist_ok=True)

        # Write global skill
        (global_skill_dir / "SKILL.md").write_text(OPENCODE_SKILL_MARKDOWN, encoding="utf-8")
        installed.append(str(global_skill_dir / "SKILL.md"))

        # Write global plugin
        if plugin_src.exists():
            shutil.copy2(plugin_src, global_plugin_dir / "index.ts")
            installed.append(str(global_plugin_dir / "index.ts"))

        # Update global opencode.json
        global_config = global_cfg_dir / "opencode.json"
        _merge_opencode_json(global_config, python_bin)
        installed.append(str(global_config))

    return installed
