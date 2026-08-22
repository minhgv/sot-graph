"""
sot_graph.adapters - Adapters and Integration Bridges for AI Coding Harnesses.
Supported Harnesses:
- OMP (Oh My Pi)
- OpenCode
- Google Antigravity / Gemini CLI
- Claude Code / Cursor / Universal MCP
- ZCode
"""

from sot_graph.adapters.installer import install_harnesses, list_supported_harnesses

__all__ = ["install_harnesses", "list_supported_harnesses"]
