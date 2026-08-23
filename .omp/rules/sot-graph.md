# SOT-Graph Project Rules for OMP (Oh My Pi)

## 1. Filesystem as Single Source of Truth (SSOT)
- The physical filesystem is the absolute ground truth. The SOT knowledge graph (`.sot/sot.db`) is an authoritative projection of reality.
- Never assume a file path exists based on historical context without verification.

## 2. Knowledge Reuse Protocol (Mandatory Before Implementation)
Before writing any new utility, helper function, or class:
1. Run `sot search "<keyword>"` or use the `sot_search` tool (Pure-Read Search; never mutates SQLite).
2. Check Multi-Dimensional Trust Evidence v2:
   - `[STRONG]`: Code physically exists on disk, hash matches journal, AST span verified (`confidence ≥ 0.9`).
   - `[WEAK]`: Semantic/partial match only; inspect the file snippet before reusing.
   - `[REBUILT]`: File was moved; use the updated path reported by atomic hash rehome.
   - `[REMOVED]`: Node deleted on disk; do NOT reference or hallucinate.
   - `[NOPATH]`: Virtual/inline node; verify origin.

## 3. Dependency Impact & Safe Refactoring Protocol (Honest Usages)
Before modifying, refactoring, or renaming core functions/classes:
1. Run `sot explore "<symbol>" --depth 2` or `sot usages "<symbol>"`.
2. Inspect `status` and `unresolved_count`:
   - If `status == "PARTIAL"`: There are `UNRESOLVED` or `AMBIGUOUS` candidate callers in `pending_edges`. NEVER assume 0 callers; inspect candidates before refactoring.
3. When working with interfaces or abstract classes, run `sot implementations "<interface>"` to identify all concrete implementations.

## 4. Context Isolation & Hard-Budget Subgraph Packaging
- When delegating multi-module tasks to subagents (`task`/`worker`), avoid dumping dozens of raw source files.
- Run `sot pack "<symbol>" --tokens 1500 -o context.yaml` to generate a live-verified ContextBundle bounded strictly by token ceiling.

## 5. Self-Healing & Storage Integrity
- If you create, move, or delete files, run:
  `sot reconcile` or `sot_reconcile` tool (or `sot batch-reconcile` for monorepo roots) for atomic content-hash rehoming.
- Check database health with `sot doctor` (runs `PRAGMA quick_check;` and verifies schema consistency).
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sot insert --title "..." --body "..." --keywords "..."`.

## 6. Architecture Analysis & Fact Bundle Protocol
When requested to review or synthesize comprehensive architecture documentation for a repository:
1. Run `sot bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/`.
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
