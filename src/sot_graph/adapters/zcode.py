"""
sot_graph.adapters.zcode - ZCode Harness Adapter.
"""

from pathlib import Path
import json
import sys

ZCODE_SKILL_MARKDOWN = """---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, and graph analytics (Louvain clustering, God Node detection, HTML/GraphRAG/Obsidian export, Fact Bundles).
---

# /sot-graph (Single Source of Truth Knowledge Layer for ZCode)

Ground every implementation decision in physical filesystem reality. The graph
(`.sot/sot.db`) is an authoritative projection of the codebase — never a
replacement for verifying against disk.

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
| **Audit Drift** | `sot verify [--deep]` | `sot_verify` |
| **Database Doctor** | `sot doctor` | `sot_doctor` |
| **Clean Stale Data**| `sot clean [--purge-missing]` | `sot_clean` |
| **Vacuum Database** | `sot vacuum` | `sot_vacuum` |
| **Store Note** | `sot insert --title "..." --body "..."` | `sot_insert` |
| **Cluster Graph** | `sot cluster [--scope <path>]` | `sot_cluster` |
| **Architecture Report** | `sot report [-o report.md]` | `sot_report` |
| **Interactive Viz** | `sot viz [-o graph.html]` | `sot_viz` |
| **Export Graph** | `sot export -f <graphrag/obsidian/scip>` | `sot_export` |
| **Fact Bundler** | `sot bundle [-o .sot/bundle/]` | `sot_bundle` |
| **Embed Index** | `sot embed [--limit 5000]` | CLI |
| **File Watcher** | `sot watch [--debounce-ms 200]` | CLI (Daemon) |
| **Harness Setup** | `sot setup [--harness <name>]` | CLI |

## 6 Operational Protocols for Agents

### 1. Filesystem as Single Source of Truth (SSOT)
- The physical filesystem is the absolute ground truth. The SOT knowledge graph (`.sot/sot.db`) is an authoritative projection of reality.
- Never assume a file path exists based on historical context without verification.

### 2. Knowledge Reuse Protocol (Mandatory Before Implementation)
Before writing any new utility, helper function, or class:
1. Run `sot search "<keyword>"` or use the `sot_search` MCP tool.
2. Check Trust Verdicts (`[STRONG]`, `[WEAK]`, `[REBUILT]`).

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
- If you create, move, or delete files, run `sot reconcile` or `sot_reconcile`.
- Run `sot verify --deep` or `sot_verify` to audit phantom anchors and dead paths.
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sot insert --title "..." --body "..." --keywords "..."`.

### 6. Architecture Analysis & Fact Bundle Protocol
When requested to review or synthesize architecture documentation:
1. Run `sot bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/`.
2. Ingest the 5 fact files (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`) along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`.
3. Output the report with 100% grounded facts, valid diagrams, and prioritized recommendations.
"""

ZCODE_COMMAND_SEARCH = """---
description: Search the SOT knowledge graph for verified code and knowledge
---

Run the SOT-Graph verified search and report the ranked results with their
Trust Verdicts:

```bash
sot search "$ARGUMENTS"
```

- Add `-n <count>` to limit results, `--scope <dir>` to narrow the search space.
- Only `[STRONG]` and `[REBUILT]` verdicts may be relied on without inspection;
  `[WEAK]` matches require reading the file first.
- Summarize what already exists before writing any new code.
"""

ZCODE_COMMAND_MAP = """---
description: Generate a token-budgeted PageRank repository map
---

Run the SOT-Graph repository mapper to get top-down architectural orientation:

```bash
sot map $ARGUMENTS
```

- Useful flags: `--tokens <budget>` (default 2048), `--focus <path>` to narrow scope.
"""

ZCODE_COMMAND_EXPLORE = """---
description: Trace cross-file dependencies and blast radius of a symbol
---

Run the SOT-Graph AST explorer for the target symbol:

```bash
sot explore "$ARGUMENTS"
```

- Add `--depth <n>` to widen the graph walk (default 2).
- Review both outward calls and incoming references before changing a
  signature — every incoming caller is part of the blast radius.
"""

ZCODE_COMMAND_USAGES = """---
description: List all call-sites and reference sites for a symbol across files
---

Inspect every usage site of a symbol:

```bash
sot usages "$ARGUMENTS"
```
"""

ZCODE_COMMAND_RENAME = """---
description: Plan or execute safe multi-file symbol refactoring
---

Review or apply a structured rename refactor:

```bash
sot rename "$ARGUMENTS"
```
"""

ZCODE_COMMAND_PACK = """---
description: Package a bounded k-hop ContextBundle (YAML) for the current task
---

Run the SOT-Graph context packer, then read the generated bundle file:

```bash
sot pack "$ARGUMENTS" -o .sot/bundle.yaml
```

- After the command finishes, read `.sot/bundle.yaml` and use it as the working
  context for the task.
- Useful flags: `--depth <n>` (default 2), `--format <yaml|md>`.
"""

ZCODE_COMMAND_BUNDLE = """---
description: Extract 5 high-density architecture fact bundle files for LLM analysis
---

Extract fact bundle files into `.sot/bundle/`:

```bash
sot bundle $ARGUMENTS --out .sot/bundle/
```
"""

ZCODE_COMMANDS = {
    "sot-search.md": ZCODE_COMMAND_SEARCH,
    "sot-map.md": ZCODE_COMMAND_MAP,
    "sot-explore.md": ZCODE_COMMAND_EXPLORE,
    "sot-usages.md": ZCODE_COMMAND_USAGES,
    "sot-rename.md": ZCODE_COMMAND_RENAME,
    "sot-pack.md": ZCODE_COMMAND_PACK,
    "sot-bundle.md": ZCODE_COMMAND_BUNDLE,
}


def _merge_zcode_config(config_path: Path, python_bin: str, root: Path) -> None:
    """
    Merge SOT-Graph into the nested .zcode/config.json MCP format.

    ZCode expects ``{"mcp": {"servers": {...}}}`` (nested, unlike the flat
    ``.mcp.json`` layout). The merge is conservative and idempotent: an
    existing config is parsed and only the ``mcp.servers["sot-graph"]`` entry
    is added/overwritten — every other key (themes, other servers, unrelated
    settings) is preserved untouched. An unreadable/corrupt file is treated as
    empty rather than propagated as an error.
    """
    data = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}

    mcp = data.get("mcp")
    if not isinstance(mcp, dict):
        mcp = {}
        data["mcp"] = mcp

    servers = mcp.get("servers")
    if not isinstance(servers, dict):
        servers = {}
        mcp["servers"] = servers

    servers["sot-graph"] = {
        "command": python_bin,
        "args": ["-m", "sot_graph.cli", "mcp"],
        "env": {"PYTHONPATH": str(root / "src")},
        "cwd": str(root),
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_zcode_skill(base_dir: Path) -> Path:
    """Write the sot-graph skill into a .zcode directory and return its path."""
    skill_dir = base_dir / "skills" / "sot-graph"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(ZCODE_SKILL_MARKDOWN, encoding="utf-8")
    return skill_file


def _write_zcode_commands(base_dir: Path) -> list[Path]:
    """Write the sot-* slash command files into a .zcode directory."""
    cmd_dir = base_dir / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, content in ZCODE_COMMANDS.items():
        cmd_file = cmd_dir / filename
        cmd_file.write_text(content, encoding="utf-8")
        written.append(cmd_file)
    return written


def setup_zcode(root: Path, global_install: bool = True, workspace_install: bool = True) -> list[str]:
    """Configure ZCode harness at workspace and/or global levels."""
    installed = []
    python_bin = sys.executable or "python3"

    # Workspace level (.zcode/)
    if workspace_install:
        zcode_dir = root / ".zcode"

        # 1. config.json (nested MCP server entry, safe merge)
        ws_config = zcode_dir / "config.json"
        _merge_zcode_config(ws_config, python_bin, root)
        installed.append(str(ws_config))

        # 2. Skill
        installed.append(str(_write_zcode_skill(zcode_dir)))

        # 3. Slash commands
        installed.extend(str(p) for p in _write_zcode_commands(zcode_dir))

    # Global level (~/.zcode/)
    if global_install:
        home = Path.home()
        global_zcode = home / ".zcode"

        global_config = global_zcode / "config.json"
        _merge_zcode_config(global_config, python_bin, root)
        installed.append(str(global_config))

        installed.append(str(_write_zcode_skill(global_zcode)))

        installed.extend(str(p) for p in _write_zcode_commands(global_zcode))

    return installed
