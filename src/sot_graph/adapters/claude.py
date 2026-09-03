"""
sot_graph.adapters.claude - Claude Code & Universal MCP Harness Adapter.
"""

from pathlib import Path
import json
import sys

CLAUDE_SECTION = """
## SOT-Graph Knowledge Reuse Protocol (SSOT)

### 1. Filesystem as Single Source of Truth (SSOT)
- The physical filesystem is the absolute ground truth. The SOT knowledge graph (`.sot/sot.db`) is an authoritative projection of reality.
- Never assume a file path exists based on historical context without verification.

### 2. Knowledge Reuse Protocol (Mandatory Before Implementation)
Before writing any new utility, helper function, or class:
1. Run `sot search "<keyword>"` or use the `sot_search` MCP tool.
2. Check Trust Verdicts:
   - `[STRONG]`: Code physically exists and is verified on disk.
   - `[WEAK]`: Semantic match only; inspect the file.
   - `[REBUILT]`: File was moved; use the updated path.
   - `[REMOVED]`: Node deleted on disk; do NOT reference.
   - `[NOPATH]`: Virtual/inline node; verify origin.

### 3. Dependency Impact & Safe Refactoring Protocol
Before modifying, refactoring, or renaming core functions/classes:
1. Run `sot explore "<symbol>"` or `sot_explore` to inspect Outward Calls and Incoming References.
2. Run `sot usages "<symbol>"` or `sot_usages` to locate all calling sites.
3. For interfaces or abstract classes, run `sot implementations "<symbol>"` or `sot_implementations`.
4. For multi-file symbol renames, run `sot rename "<symbol>" --to "<new_name>"` to review staged changes.
5. Before submitting PRs or finalizing diffs, run `sot diff-impact` or `sot_diff_impact` to analyze blast radius, upstream inward callers, API contract impacts, and affected tests.
6. Inspect commit risk history via `sot log` or `sot_git_history`.
### 4. Context Isolation & Subgraph Packaging Protocol
When delegating code context to subagents or prompt registers:
1. Run `sot pack "<symbol>" --max-hops 2 -o .sot/bundle/context.yaml` to extract a token-efficient k-hop subgraph.
2. Feed the compact YAML ContextBundle instead of full raw files to save 60-70% tokens.

### 5. Self-Healing & Drift Reconciliation
- If you create, move, or delete files, run `sot reconcile` (or `sot batch-reconcile` for monorepos).
- Run `sot verify --deep` or `sot_verify_drift` to audit phantom anchors and dead paths.
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sot insert --title "..." --body "..." --keywords "..."`.

### 6. Architecture Analysis & Fact Bundle Protocol
When requested to review or synthesize architecture documentation:
1. Run `sot bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/`.
2. Ingest the 5 fact files (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`) along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`.
3. Output the report with facts grounded ONLY in the bundle files — anything beyond them must be marked [INFERENCE]. Valid diagrams, prioritized recommendations.

### 7. Markdown, LaTeX & Unicode Rendering Rules (Dual-Target: Human & AI)
1. **Mermaid Diagrams:**
   - Wrap every Node label and Subgraph title in double quotes: `NODE["Label"]`, `subgraph ID ["Title"]`.
   - Never use bare pipe `|` inside node labels (use `/` or `\\|`).
   - Maintain blank lines before and after ````mermaid` blocks.
2. **Mathematical & Unicode Symbols:**
   - Use clean Unicode symbols directly: `Q ≥ 0.650`, `Q = 0.371`, `≈ 400`, `State ∈ { Initial, Loading, Success(data), Failure(error) }`.
   - NEVER use raw `$ ... $` math blocks inside Markdown table cells, headers, or bullet items to prevent raw syntax display on GitHub, VS Code, Obsidian, and Word/DOCX converters.
3. **Markdown Tables & Formatting:**
   - In table cells, escape comparison operators: use `&lt;`, `&gt;` or Unicode `≤`, `≥`.
   - Escape table cell pipes `\\|` to preserve table column alignments.

### CLI & MCP Quick Reference
| Category | CLI Command | MCP Tool |
| :--- | :--- | :--- |
| **Search Codebase** | `sot search "<query>" [-n 5] [--hybrid]` | `sot_search` |
| **Repository Map** | `sot map [--focus <areas>] [--tokens 1024]` | `sot_map` |
| **Trace Call Graph** | `sot explore "<symbol>" [--max-hops 2]` | `sot_explore` |
| **Inspect Usages** | `sot usages "<symbol>"` | `sot_usages` |
| **Implementations** | `sot implementations "<interface>"` | `sot_implementations` |
| **Rename Impact** | `sot rename "<symbol>" --to <new_name>` | `CLI only` |
| **Pack Subgraph** | `sot pack "<symbol>" [--max-hops 2] [-o <file>]`| `sot_pack` |
| **Synchronize DB** | `sot reconcile [--workers 4]` | `CLI only` |
| **Batch Reconcile** | `sot batch-reconcile <dir> [--workers 4]` | CLI |
| **Audit Drift** | `sot verify [--deep]` | `sot_verify_drift` |
| **Database Doctor** | `sot doctor` | `CLI only` |
| **Clean Stale Data**| `sot clean [--all] [--include-notes]` | `CLI only` |
| **Vacuum Database** | `sot vacuum [--analyze]` | `CLI only` |
| **Store Note** | `sot insert --title "..." --body "..."` | `CLI only` |
| **Cluster Graph** | `sot cluster [--scope <path>]` | `CLI only` |
| **Architecture Report** | `sot report [-o report.md]` | `sot_architecture_report` |
| **Interactive Viz** | `sot viz [-o graph.html]` | `CLI only` |
| **Export Graph** | `sot export -f <graphrag/obsidian/scip>` | `CLI only` |
| **Fact Bundler** | `sot bundle [-o .sot/bundle/] [--include-tests]` | `sot_bundle` |
| **Full-Stack Trace** | `sot trace "<target>" [--max-hops 2] [-o <file>]` | `sot_trace` |
| **UI Decision Tree** | `sot ui-tree "<component>"` | `sot_ui_tree` |
| **Backend Flow** | `sot be-flow "<service>"` | `sot_backend_flow` |
| **Feature Inventory** | `sot solution inventory [module] [-o <file>]` | `sot_solution_inventory` |
| **Micro-steps Decompose** | `sot solution steps "<method>" [--format table/json]` | `sot_solution_steps` |
| **Solution Bundle** | `sot solution bundle [module] [-o <file>]` | `sot_solution_bundle` |
| **Diff Impact** | `sot diff-impact [target] [--staged] [--max-hops 2]` | `sot_diff_impact` |
| **Commit History** | `sot log [-n 10] [--author <name>] [--since <date>]` | `sot_git_history` |
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


def _append_agents_rules(agents_md_path: Path) -> None:
    """Append SOT-Graph protocol to AGENTS.md in workspace root."""
    template_file = Path(__file__).parent / "AGENTS.md"
    protocol_text = template_file.read_text(encoding="utf-8") if template_file.exists() else CLAUDE_SECTION
    if not agents_md_path.exists():
        agents_md_path.parent.mkdir(parents=True, exist_ok=True)
        agents_md_path.write_text(f"# Agent Rules & Protocols\n\n{protocol_text}\n", encoding="utf-8")
        return

    content = agents_md_path.read_text(encoding="utf-8")
    if "SOT-Graph Knowledge Reuse Protocol" not in content:
        agents_md_path.write_text(f"{content.rstrip()}\n\n{protocol_text}\n", encoding="utf-8")

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

        # 4. AGENTS.md (Root workspace agent instructions)
        agents_md = root / "AGENTS.md"
        _append_agents_rules(agents_md)
        installed.append(str(agents_md))

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
