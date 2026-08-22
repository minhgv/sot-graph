"""
sot_graph.adapters.omp - OMP (Oh My Pi) Harness Adapter.
"""

from pathlib import Path
import json
import shutil

SKILL_MARKDOWN = """---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, and graph analytics (Louvain clustering, God Node detection, HTML/GraphRAG/Obsidian export).
---

# /sot-graph (Single Source of Truth Knowledge Layer)

When to use:
- **Before writing or implementing code**: Search if utilities or existing solutions already exist (`sot search` / `sot_search`).
- **Before modifying core functions or classes**: Trace upstream/downstream dependencies (`sot explore` / `sot_explore`).
- **Verifying disk consistency**: Audit phantom anchors and drift (`sot verify` / `sot_verify`).
- **Recording knowledge**: Record non-obvious architecture choices or critical bug solutions (`sot insert` / `sot_insert`).
- **Architecture analysis**: Generate visual graphs or community reports (`sot cluster`, `sot report`, `sot viz`, `sot export`).

## Trust Verdicts
- `[STRONG]`: 100% verified against disk reality. File exists, symbol exists, content matches.
- `[WEAK]`: Semantic or partial match. Inspect the file before relying on it.
- `[REBUILT]`: File has moved location; use the updated path reported by the reconciler.

## Quick CLI Reference
| Task | CLI Command | Native Tool Equivalent |
| :--- | :--- | :--- |
| **Search Codebase** | `./bin/sot search "<query>" [-n 5]` | `sot_search(query="...")` |
| **Trace Call Graph** | `./bin/sot explore "<symbol>" [--depth 2]` | `sot_explore(target="...")` |
| **Synchronize DB** | `./bin/sot reconcile [--workers 4]` | `sot_reconcile()` |
| **Audit Drift** | `./bin/sot verify [--deep]` | `sot_verify()` |
| **Database Doctor** | `./bin/sot doctor` | `sot_doctor()` |
| **Store Note** | `./bin/sot insert --title "..." --body "..."` | `sot_insert(...)` |
| **Cluster Communities** | `./bin/sot cluster` | `sot_cluster()` |
| **Export Graph** | `./bin/sot export --format obsidian` | `sot_export(...)` |
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

## 3. Dependency Impact Tracing
Before modifying or refactoring core functions/classes:
1. Run `sot explore "<symbol>"` or use `sot_explore` to inspect both Outward Calls and Incoming References.
2. Ensure you understand all upstream callers before changing signatures.

## 4. Self-Healing & Drift
- If you create, move, or delete files, run:
  `sot reconcile` or `sot_reconcile` tool.
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sot insert --title "..." --body "..." --keywords "..."`.
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
        ext_dir.mkdir(parents=True, exist_ok=True)
        skill_dir.mkdir(parents=True, exist_ok=True)

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

    # Global level (~/.omp/)
    if global_install:
        home = Path.home()
        global_omp = home / ".omp"
        global_ext_dir = global_omp / "agent" / "extensions"
        global_skill_dir = global_omp / "skills" / "sot-graph"
        global_ext_dir.mkdir(parents=True, exist_ok=True)
        global_skill_dir.mkdir(parents=True, exist_ok=True)

        if adapter_src.exists():
            shutil.copy2(adapter_src, global_ext_dir / "sot-graph.ts")
            installed.append(str(global_ext_dir / "sot-graph.ts"))

        (global_skill_dir / "SKILL.md").write_text(SKILL_MARKDOWN, encoding="utf-8")
        installed.append(str(global_skill_dir / "SKILL.md"))

    return installed
