"""
sot_graph.adapters.omp - OMP (Oh My Pi) Harness Adapter.
"""

from pathlib import Path
import shutil

SKILL_MARKDOWN = """---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, graph analytics (Louvain clustering, God Node detection, HTML/GraphRAG/Obsidian export), and 2-stage fact bundle extraction for comprehensive LLM architecture reports.
---

# /sot-graph (Single Source of Truth Knowledge Layer)

When to use:
- **Top-down orientation**: Map repository architecture without token waste (`sot map` / `sot_map`).
- **Before writing or implementing code**: Search if utilities or existing solutions already exist (`sot search` / `sot_search`).
- **Before modifying core functions or classes**: Trace upstream/downstream dependencies (`sot explore` / `sot_explore`) and exact call-sites (`sot usages` / `sot_usages`).
- **Polymorphism & interface inspection**: Inspect concrete implementations (`sot implementations` / `sot_implementations`).
- **Safe symbol refactoring**: Plan or execute multi-file renames (`sot rename`).
- **Token-efficient context packaging**: Extract k-hop subgraphs into YAML ContextBundles (`sot pack` / `sot_pack`).
- **Verifying disk consistency**: Audit phantom anchors and drift (`sot verify` / `sot_verify_drift`).
- **Recording knowledge**: Record non-obvious architecture choices or critical bug solutions (`sot insert` / `sot_notes`).
- **Architecture analysis & reports**: Extract 5 fact bundle files (`sot bundle` / `sot_bundle`), generate visual graphs, community clustering, or health reports (`sot cluster`, `sot report`, `sot viz`, `sot export`).
- **Database maintenance**: Purge stale records and vacuum freelists (`sot clean`, `sot vacuum`, `sot doctor`).

## Trust Verdicts
- `[STRONG]`: 100% verified against disk reality. File exists, symbol exists, token coverage matches.
- `[WEAK]`: Semantic or partial match. Inspect the file snippet before relying on it.
- `[REBUILT]`: File has moved location; use the updated path reported by the reconciler.
- `[REMOVED]`: Node deleted on disk; do NOT reference or hallucinate.
- `[NOPATH]`: Virtual/inline node without a direct physical file backing.

## Quick CLI Reference
| Category | CLI Command | Native Tool Device |
| :--- | :--- | :--- |
| **Search Codebase** | `sot search "<query>" [-n 5] [--hybrid]` | `xd://sot_search` |
| **Repository Map** | `sot map [--focus <areas>] [--tokens 1024]` | `xd://sot_map` |
| **Trace Call Graph** | `sot explore "<symbol>" [--depth 2]` | `xd://sot_explore` |
| **Inspect Usages** | `sot usages "<symbol>"` | `xd://sot_usages` |
| **Implementations** | `sot implementations "<interface>"` | `xd://sot_implementations` |
| **Rename Impact** | `sot rename "<symbol>" [--to <new_name>]` | `xd://sot_rename` |
| **Pack Subgraph** | `sot pack "<symbol>" [--depth 2] [-o <file>]`| `xd://sot_pack` |
| **Synchronize DB** | `sot reconcile [--workers 4]` | `xd://sot_reconcile` |
| **Audit Drift** | `sot verify [--deep]` | `xd://sot_verify` |
| **Database Doctor** | `sot doctor` | `xd://sot_doctor` |
| **Clean Stale Data**| `sot clean [--all] [--include-notes]` | `xd://sot_clean` |
| **Vacuum Database** | `sot vacuum [--analyze]` | `xd://sot_vacuum` |
| **Store Note** | `sot insert --title "..." --body "..."` | `xd://sot_insert` |
| **Cluster Graph** | `sot cluster [--scope <path>]` | `xd://sot_cluster` |
| **Architecture Report** | `sot report [-o GRAPH_REPORT.md]` | `xd://sot_report` |
| **Interactive Viz** | `sot viz [-o graph.html]` | `xd://sot_viz` |
| **Export Graph** | `sot export -f <graphrag|obsidian|scip>` | `xd://sot_export` |
| **Fact Bundler** | `sot bundle [-o .sot/bundle/]` | `xd://sot_bundle` |
"""

RULES_MARKDOWN = """# SOT-Graph Project Rules for OMP (Oh My Pi)

## 1. Filesystem as Single Source of Truth (SSOT)
- The physical filesystem is the absolute ground truth. The SOT knowledge graph (`.sot/sot.db`) is an authoritative projection of reality.
- Never assume a file path exists based on historical context without verification.

## 2. Knowledge Reuse Protocol (Mandatory Before Implementation)
Before writing any new utility, helper function, or class:
1. Run `sot search "<keyword>"` or use the `sot_search` tool.
2. Check Trust Verdicts:
   - `[STRONG]`: Code physically exists and is verified on disk.
   - `[WEAK]`: Semantic match only; inspect the file.
   - `[REBUILT]`: File was moved; use the updated path.

## 3. Dependency Impact & Safe Refactoring Protocol
Before modifying, refactoring, or renaming core functions/classes:
1. Run `sot explore "<symbol>"` or `sot usages "<symbol>"` to inspect both Outward Calls and Incoming References.
2. When working with interfaces or abstract classes, run `sot implementations "<interface>"` to identify all concrete implementations.
3. Ensure you understand all upstream callers before changing signatures.

## 4. Context Isolation & Subgraph Packaging Protocol
- When modifying multi-module features, avoid reading dozens of raw source files sequentially.
- Run `sot pack "<symbol>" --depth 2` to generate a token-efficient YAML ContextBundle for subagents.

## 5. Self-Healing & Drift Reconciliation
- If you create, move, or delete files, run:
  `sot reconcile` or `sot_reconcile` tool.
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sot insert --title "..." --body "..." --keywords "..."`.

## 6. Architecture Analysis & Fact Bundle Protocol
When requested to review or synthesize comprehensive architecture documentation for a repository:
1. Run `sot bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/`.
2. Ingest the 5 fact files (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`).
3. Output the report with 100% grounded facts, valid ASCII/Mermaid diagrams, and prioritized recommendations.
"""


def setup_omp(root: Path, global_install: bool = True, workspace_install: bool = True) -> list[str]:
    """Configure OMP harness at workspace and/or global levels."""
    installed = []
    adapter_src = Path(__file__).resolve().parent / "omp_extension.ts"

    # Workspace level (.omp/)
    if workspace_install:
        omp_dir = root / ".omp"
        ext_dir = omp_dir / "extensions"
        skill_dir = omp_dir / "skills" / "sot-graph"
        rules_dir = omp_dir / "rules"
        ext_dir.mkdir(parents=True, exist_ok=True)
        skill_dir.mkdir(parents=True, exist_ok=True)
        rules_dir.mkdir(parents=True, exist_ok=True)

        # Write extension
        if adapter_src.exists():
            shutil.copy2(adapter_src, ext_dir / "sot-graph.ts")
            installed.append(str(ext_dir / "sot-graph.ts"))

        # Write skill
        (skill_dir / "SKILL.md").write_text(SKILL_MARKDOWN, encoding="utf-8")
        installed.append(str(skill_dir / "SKILL.md"))

        # Write rules
        (omp_dir / "RULES.md").write_text(RULES_MARKDOWN, encoding="utf-8")
        installed.append(str(omp_dir / "RULES.md"))
        (rules_dir / "sot-graph.md").write_text(RULES_MARKDOWN, encoding="utf-8")
        installed.append(str(rules_dir / "sot-graph.md"))

    # Global level (~/.omp/)
    if global_install:
        home = Path.home()
        global_omp = home / ".omp"
        global_ext_dir = global_omp / "agent" / "extensions"
        global_skill_dir = global_omp / "skills" / "sot-graph"
        global_rules_dir = global_omp / "rules"
        global_ext_dir.mkdir(parents=True, exist_ok=True)
        global_skill_dir.mkdir(parents=True, exist_ok=True)
        global_rules_dir.mkdir(parents=True, exist_ok=True)

        if adapter_src.exists():
            shutil.copy2(adapter_src, global_ext_dir / "sot-graph.ts")
            installed.append(str(global_ext_dir / "sot-graph.ts"))

        (global_skill_dir / "SKILL.md").write_text(SKILL_MARKDOWN, encoding="utf-8")
        installed.append(str(global_skill_dir / "SKILL.md"))

        (global_omp / "RULES.md").write_text(RULES_MARKDOWN, encoding="utf-8")
        installed.append(str(global_omp / "RULES.md"))
        (global_rules_dir / "sot-graph.md").write_text(RULES_MARKDOWN, encoding="utf-8")
        installed.append(str(global_rules_dir / "sot-graph.md"))

    return installed
