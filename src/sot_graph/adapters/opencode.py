"""
sot_graph.adapters.opencode - OpenCode Harness Adapter.
"""

from pathlib import Path
import json
import shutil
import sys

OPENCODE_SKILL_MARKDOWN = """---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, and graph analytics (Louvain clustering, God Node detection, HTML/GraphRAG/Obsidian export, Fact Bundles).
---

# /sot-graph (Single Source of Truth Knowledge Layer for OpenCode)

Ground OpenCode agent actions in physical filesystem reality using the SOT knowledge layer.

## When to Use SOT-Graph
- **Top-down orientation**: Map repository architecture without token waste (`sot map` / `sot_map`).
- **Before writing or implementing code**: Search if utilities or existing solutions already exist (`sot search` / `sot_search`).
- **Before modifying core functions or classes**: Trace upstream/downstream dependencies (`sot explore` / `sot_explore`, `sot usages` / `sot_usages`).
- **Polymorphism & interface inspection**: Inspect concrete implementations (`sot implementations` / `sot_implementations`).
- **Safe symbol refactoring**: Plan or execute multi-file renames (`sot rename` / `sot_rename`).
- **Token-efficient context packaging**: Extract k-hop subgraphs into YAML ContextBundles (`sot pack` / `sot_pack`).
- **Verifying disk consistency**: Audit phantom anchors and drift (`sot verify` / `sot_verify`).
- **Recording knowledge**: Record non-obvious architecture choices or critical bug solutions (`sot insert` / `sot_insert`).
- **Architecture analysis & reports**: Extract 5 fact bundle files (`sot bundle` / `sot_bundle`), generate visual graphs, community clustering, or health reports (`sot cluster`, `sot report`, `sot viz`, `sot export`).
- **Database maintenance**: Purge stale records and vacuum freelists (`sot clean`, `sot vacuum`, `sot doctor`).

## Trust Verdicts
| Verdict | Meaning | Action |
| :--- | :--- | :--- |
| `[STRONG]` | File exists on disk, symbol exists in AST, token coverage verified. | **Proceed directly.** 100% reliable anchor. |
| `[WEAK]` | Semantic or partial match; low lexical coverage. | **Inspect snippet range** before relying on symbol. |
| `[REBUILT]` | File moved or renamed; auto-rehomed by reconciler. | **Use updated path** reported in result. |
| `[REMOVED]` | Node deleted on disk; scheduled for purge. | **Do NOT use.** Symbol no longer exists. |
| `[NOPATH]` | Virtual or inline node without a physical file backing. | **Context-only.** Verify origin. |

## Quick CLI & MCP Tool Reference
| Category | CLI Command | MCP Tool |
| :--- | :--- | :--- |
| **Search Codebase** | `sot search "<query>" [-n 5] [--hybrid]` | `sot_search` |
| **Repository Map** | `sot map [--focus <areas>] [--tokens 1024]` | `sot_map` |
| **Trace Call Graph** | `sot explore "<symbol>" [--depth 2]` | `sot_explore` |
| **Inspect Usages** | `sot usages "<symbol>"` | `sot_usages` |
| **Implementations** | `sot implementations "<interface>"` | `sot_implementations` |
| **Rename Impact** | `sot rename "<symbol>" --to <new_name>` | `sot_rename` |
| **Pack Subgraph** | `sot pack "<symbol>" [--depth 2] [-o <file>]`| `sot_pack` |
| **Synchronize DB** | `sot reconcile [--workers 4]` | `sot_reconcile` |
| **Batch Reconcile** | `sot batch-reconcile <dir> [--workers 4]` | CLI |
| **Audit Drift** | `sot verify [--deep]` | `sot_verify` |
| **Database Doctor** | `sot doctor` | `sot_doctor` |
| **Clean Stale Data**| `sot clean [--purge-missing] [--include-notes]` | `sot_clean` |
| **Vacuum Database** | `sot vacuum [--analyze]` | `sot_vacuum` |
| **Store Note** | `sot insert --title "..." --body "..."` | `sot_insert` |
| **Cluster Graph** | `sot cluster [--scope <path>]` | `sot_cluster` |
| **Architecture Report** | `sot report [-o report.md]` | `sot_report` |
| **Interactive Viz** | `sot viz [-o graph.html]` | `sot_viz` |
| **Export Graph** | `sot export -f <graphrag/obsidian/scip>` | `sot_export` |
| **Fact Bundler** | `sot bundle [-o .sot/bundle/] [--include-tests]` | `sot_bundle` |
| **Full-Stack Trace** | `sot trace "<target>" [--depth 2] [-o <file>]` | `sot_trace` |
| **UI Decision Tree** | `sot ui-tree "<component>"` | `sot_ui_tree` |
| **Backend Flow** | `sot be-flow "<service>"` | `sot_backend_flow` |
| **Feature Inventory** | `sot solution inventory [module] [-o <file>]` | `sot_solution_inventory` |
| **Micro-steps Decompose** | `sot solution steps "<method>" [--format table/json]` | `sot_solution_steps` |
| **Solution Bundle** | `sot solution bundle [module] [-o <file>]` | `sot_solution_bundle` |
| **Embed Index** | `sot embed [--limit 5000]` | CLI |
| **File Watcher** | `sot watch [--debounce-ms 200]` | CLI (Daemon) |
| **Harness Setup** | `sot setup [--harness <name>]` | CLI |

## 7 Operational Protocols for Agents

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

### 4. Context Isolation & Subgraph Packaging Protocol
When delegating code context to subagents or prompt registers:
1. Run `sot pack "<symbol>" --depth 2 -o .sot/bundle/context.yaml` to extract a token-efficient k-hop subgraph.
2. Feed the compact YAML ContextBundle instead of full raw files to save 60-70% tokens.

### 5. Self-Healing & Drift Reconciliation
- If you create, move, or delete files, run `sot reconcile` or `sot_reconcile` (or `sot batch-reconcile` for monorepos).
- Run `sot verify --deep` or `sot_verify` to audit phantom anchors and dead paths.
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sot insert --title "..." --body "..." --keywords "..."`.

### 6. Architecture Analysis & Fact Bundle Protocol
When requested to review or synthesize architecture documentation:
1. Run `sot bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/`.
2. Ingest the 5 fact files (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`) along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`.
3. Output the report with 100% grounded facts, valid diagrams, and prioritized recommendations.

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
