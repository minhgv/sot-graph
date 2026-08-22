"""
sot_graph.adapters.installer - Unified Multi-Harness Installer.
Configures OMP, OpenCode, Antigravity, and Claude harnesses seamlessly.
"""

from pathlib import Path
from typing import Dict, List, Sequence

from sot_graph.adapters.omp import setup_omp
from sot_graph.adapters.opencode import setup_opencode
from sot_graph.adapters.antigravity import setup_antigravity
from sot_graph.adapters.claude import setup_claude

SUPPORTED_HARNESSES = {
    "omp": ("Oh My Pi (OMP) Native Extension, Skill & Rules", setup_omp),
    "opencode": ("OpenCode Skill, Plugin & MCP Server", setup_opencode),
    "antigravity": ("Google Antigravity / Gemini CLI MCP & Skill", setup_antigravity),
    "claude": ("Claude Code & Cursor Universal MCP", setup_claude),
}


def list_supported_harnesses() -> Dict[str, str]:
    """Return dictionary of supported harness keys and human-readable names."""
    return {k: v[0] for k, v in SUPPORTED_HARNESSES.items()}


def install_harnesses(
    harnesses: Sequence[str],
    root: Path | None = None,
    global_install: bool = True,
    workspace_install: bool = True,
) -> Dict[str, List[str]]:
    """
    Install and configure adapters for selected harnesses.
    
    Args:
        harnesses: List of harness identifiers ('omp', 'opencode', 'antigravity', 'claude', 'all').
        root: Target workspace root directory (defaults to current working directory).
        global_install: Whether to write user-level global configurations.
        workspace_install: Whether to write workspace-level configurations.
        
    Returns:
        Dictionary mapping harness name to list of installed/updated file paths.
    """
    target_root = (root or Path.cwd()).resolve()
    results: Dict[str, List[str]] = {}

    selected = set(harnesses)
    if "all" in selected:
        selected = set(SUPPORTED_HARNESSES.keys())

    for name in selected:
        if name not in SUPPORTED_HARNESSES:
            continue
        _, setup_fn = SUPPORTED_HARNESSES[name]
        installed_files = setup_fn(
            root=target_root,
            global_install=global_install,
            workspace_install=workspace_install,
        )
        results[name] = installed_files

    return results
