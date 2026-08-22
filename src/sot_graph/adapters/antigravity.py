"""
sot_graph.adapters.antigravity - Google Antigravity / Gemini CLI Harness Adapter.
"""

from pathlib import Path
import json
import sys

ANTIGRAVITY_SKILL_MARKDOWN = """---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, and graph analytics.
---

# sot-graph for Google Antigravity / Gemini CLI

Ground agent actions in physical filesystem reality using the SOT knowledge layer:

## 1. Verified Knowledge Search
Search the codebase with Trust Verdicts before implementing new logic:
```bash
sot search "<query>" -n 5
```
Or use the MCP tool `sot_search(query="...")`.

Trust Verdicts:
- `[STRONG]`: High confidence — file and symbols physically verified on disk.
- `[WEAK]`: Semantic match only — inspect before relying on it.
- `[REBUILT]`: File has moved location; use the updated path.

## 2. AST Call Graph & Dependency Exploration
Trace cross-file call graphs and references before modifying functions:
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

GEMINI_SECTION = """
## SOT-Graph Knowledge Reuse Protocol (SSOT)
- **Zero Hallucinated Anchors**: The filesystem is the single source of truth. Always ground symbol existence using `sot search` or `sot_search`.
- **Pre-Implementation Verification**: Before writing new helper utilities, search if a verified implementation exists (`[STRONG]` verdict).
- **Architectural Blast Radius**: Before changing core functions/classes, run `sot explore "<symbol>"` or `sot_explore` to verify all incoming references.
- **Drift Synchronization**: After refactoring, renaming, or deleting files, run `sot reconcile` to purge dead paths.
"""


def _merge_gemini_settings(settings_path: Path, python_bin: str) -> None:
    """Merge SOT-Graph MCP server into settings.json cleanly."""
    data = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
        data["mcpServers"] = {}

    data["mcpServers"]["sot-graph"] = {
        "command": python_bin,
        "args": ["-m", "sot_graph.cli", "mcp"],
    }

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _append_gemini_rules(gemini_md_path: Path) -> None:
    """Append SOT-Graph protocol to GEMINI.md if not already present."""
    if not gemini_md_path.exists():
        gemini_md_path.parent.mkdir(parents=True, exist_ok=True)
        gemini_md_path.write_text(f"# Gemini Agent Rules\n{GEMINI_SECTION}", encoding="utf-8")
        return

    content = gemini_md_path.read_text(encoding="utf-8")
    if "SOT-Graph Knowledge Reuse Protocol" not in content:
        gemini_md_path.write_text(f"{content.rstrip()}\n\n{GEMINI_SECTION}\n", encoding="utf-8")


def setup_antigravity(root: Path, global_install: bool = True, workspace_install: bool = True) -> list[str]:
    """Configure Antigravity / Gemini CLI harness at workspace and/or global levels."""
    installed = []
    python_bin = sys.executable or "python3"

    # Workspace level (.gemini/ and .antigravity/)
    if workspace_install:
        gemini_dir = root / ".gemini"
        skill_dir = gemini_dir / "skills" / "sot-graph"
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Write workspace skill
        (skill_dir / "SKILL.md").write_text(ANTIGRAVITY_SKILL_MARKDOWN, encoding="utf-8")
        installed.append(str(skill_dir / "SKILL.md"))

        # Write workspace settings.json
        ws_settings = gemini_dir / "settings.json"
        _merge_gemini_settings(ws_settings, python_bin)
        installed.append(str(ws_settings))

        # Write workspace GEMINI.md
        ws_gemini_md = gemini_dir / "GEMINI.md"
        _append_gemini_rules(ws_gemini_md)
        installed.append(str(ws_gemini_md))

    # Global level (~/.gemini/)
    if global_install:
        home = Path.home()
        global_gemini = home / ".gemini"
        global_skill_dir1 = global_gemini / "antigravity" / "skills" / "sot-graph"
        global_skill_dir2 = global_gemini / "skills" / "sot-graph"

        global_skill_dir1.mkdir(parents=True, exist_ok=True)
        global_skill_dir2.mkdir(parents=True, exist_ok=True)

        (global_skill_dir1 / "SKILL.md").write_text(ANTIGRAVITY_SKILL_MARKDOWN, encoding="utf-8")
        (global_skill_dir2 / "SKILL.md").write_text(ANTIGRAVITY_SKILL_MARKDOWN, encoding="utf-8")
        installed.append(str(global_skill_dir1 / "SKILL.md"))
        installed.append(str(global_skill_dir2 / "SKILL.md"))

        global_settings = global_gemini / "settings.json"
        _merge_gemini_settings(global_settings, python_bin)
        installed.append(str(global_settings))

        global_gemini_md = global_gemini / "GEMINI.md"
        _append_gemini_rules(global_gemini_md)
        installed.append(str(global_gemini_md))

    return installed
