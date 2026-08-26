# SOT-Graph Project Rules for OMP (Oh My Pi)

## 1. Filesystem as Single Source of Truth (SSOT)
- The physical filesystem is the absolute ground truth. The SOT knowledge graph (`.sot/sot.db`) is an authoritative projection of reality (Schema v8).
- Never assume a file path exists based on historical context without verification.

## 2. Knowledge Reuse & Multi-Provider Evidence Protocol (Mandatory Before Implementation)
Before writing any new utility, helper function, or class:
1. Run `sot search "<keyword>"` or use the `sot_search` tool (Pure-Read Search; never mutates SQLite).
2. Check Multi-Provider Trust Evidence:
   - `[STRONG]`: Code physically exists on disk, hash matches journal, AST / SCIP span verified (`confidence ≥ 0.9`).
   - `[WEAK]`: Semantic/partial match only; inspect the file snippet before reusing.
   - `[REBUILT]`: File was moved; use the updated path reported by atomic hash rehome.
   - `[REMOVED]`: Node deleted on disk; do NOT reference or hallucinate.
   - `[NOPATH]`: Virtual/inline node; verify origin.
3. Check `providers` in response envelope to distinguish `AST_HEURISTIC_PARSER` vs. `COMPILER_SCIP_INDEX`.

## 3. Dependency Impact & Safe Refactoring Protocol (Honest Usages)
Before modifying, refactoring, or renaming core functions/classes:
1. Run `sot explore "<symbol>" --depth 2` or `sot usages "<symbol>"`.
2. Inspect `status` and `unresolved_count`:
   - If `status == "PARTIAL"`: There are `UNRESOLVED` or `AMBIGUOUS` candidate callers in `pending_edges`. NEVER assume 0 callers; inspect candidates before refactoring.
3. When working with interfaces or abstract classes, run `sot implementations "<interface>"` to identify all concrete implementations.
4. When compiler-level 100% precision is required for cross-package type resolution, run `sot import-scip <path_to_index.scip>`.

## 4. Context Isolation & Hard-Budget Subgraph Packaging
- When delegating multi-module tasks to subagents (`task`/`worker`), avoid dumping dozens of raw source files.
- Run `sot pack "<symbol>" --tokens 1500 --json` (or `xd://sot_pack`) to generate a live-verified ContextBundle strictly bounded by token ceiling ($\le 5\%$ error margin).

## 5. Self-Healing, Note Preservation & Storage Integrity
- If you create, move, or delete files, run:
  `sot reconcile` or `sot_reconcile` tool (or `sot batch-reconcile` for monorepo roots) for atomic content-hash rehoming.
- Check database health with `sot doctor` (runs `PRAGMA quick_check;`, verifies foreign keys, schema v5 and page allocations).
- `sot clean --all` safely purges disposable index data while preserving user notes (`kind == 'note'`).
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sot insert --title "..." --body "..." --keywords "..."`.

## 6. Architecture Analysis & Fact Bundle Protocol
When requested to review or synthesize comprehensive architecture documentation for a repository:
1. Run `sot bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/` (MCP output paths are strictly confined to project root).
2. Ingest the 5 fact files (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`) along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`.
3. Output the 6-section report in Vietnamese with 100% grounded facts, valid ASCII/Mermaid diagrams, and prioritized recommendations.

## 7. Markdown, LaTeX & Unicode Rendering Rules (Dual-Target: Human & AI)
1. **Mermaid Diagrams:**
   - Wrap every Node label and Subgraph title in double quotes: `NODE["Label"]`, `subgraph ID ["Title"]`.
   - Never use bare pipe `|` inside node labels (use `/` or `\|`).
   - Maintain blank lines before and after ````mermaid` blocks.
2. **Mathematical & Unicode Symbols:**
   - Use clean Unicode symbols directly: `Q ≥ 0.650`, `Q = 0.371`, `≈ 400`, `State ∈ { Initial, Loading, Success(data), Failure(error) }`.
   - NEVER use raw `$ ... $` math blocks inside Markdown table cells, headers, or bullet items to prevent raw syntax display on GitHub, VS Code, Obsidian, and Word/DOCX converters.
3. **Markdown Tables & Formatting:**
   - In table cells, escape comparison operators: use `&lt;`, `&gt;` or Unicode `≤`, `≥`.
   - Escape table cell pipes `\|` to preserve table column alignments.

## 8. Graph-First Code Investigation Protocol (Zero-Discovery Invariant)
When investigating, reverse-engineering, or auditing a Symbol, Class, God Node, or Module:
1. **Graph Query First (Mandatory):** ALWAYS query SOT-Graph (`sot explore "<symbol>"`, `sot usages "<symbol>"`, or read `.sot/bundle/` fact files) FIRST to extract method inventories, callers, and blast radius in 0.1s.
2. **Zero Blind Glob / Grep:** NEVER spawn Scouts or run exploratory `glob`/`grep` commands across the codebase when `sot.db` or Fact Bundles already exist.
3. **Pinpointed Range Reading:** If code implementation details (side effects, inline comments, body logic) must be audited, Scouts MUST ONLY use exact line ranges (`file:start-end`) based on coordinates provided by SOT-Graph.
