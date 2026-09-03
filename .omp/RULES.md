# SOT-Graph Project Rules for OMP (Oh My Pi)

## 1. Filesystem as Single Source of Truth (SSOT)
- The physical filesystem is the absolute ground truth. The SOT knowledge graph (`.sot/sot.db`) is an authoritative projection of reality (Schema v8 Multi-Provider).
- Never assume a file path exists based on historical context without verification.

## 2. Knowledge Reuse Protocol (Mandatory Before Implementation)
Before writing any new utility, helper function, or class:
1. Run `sot search "<keyword>"` or use the `sot_search` tool (Pure-Read Search; never mutates SQLite).
2. Check Multi-Provider Trust Verdicts:
   - `[STRONG]`: Code physically exists and is verified on disk (`confidence ≥ 0.9`).
   - `[WEAK]`: Semantic match only; inspect the file.
   - `[REBUILT]`: File was moved; use the updated path.
   - `[REMOVED]`: Node deleted on disk; do NOT reference.
   - `[NOPATH]`: Virtual/inline node; verify origin.
3. Check `providers` in response envelope to distinguish `AST_HEURISTIC_PARSER` vs. `COMPILER_SCIP_INDEX`.

## 3. Pre-Edit Scope Receipt Gate (P8)
Before editing core/public symbols (anything outside a leaf function body):
1. Run `sot scope-receipt <symbol> --change-kind <kind> [--auth] [--dynamic] [--json]`.
2. If the receipt status is BLOCKED (e.g. rename gate: caller coverage insufficient), resolve the blocker first — do not edit.
3. Track each `omp_confirmations` item as its own todo node referencing the receipt digest (`receipt <digest12>`).
4. Stop-time rule: do NOT mark the task complete while receipt confirmations remain pending.
5. After the edit: run `sot diff-impact` (post-change receipt binds its own snapshot), run `sot reconcile`, then re-verify. A pre-change receipt (`proof_scope: pre_change_only`) is NEVER post-change proof.

## 4. Dependency Impact & Safe Refactoring Protocol (Honest Usages)
Before modifying, refactoring, or renaming core functions/classes:
1. Run `sot explore "<symbol>"` or `sot usages "<symbol>"` to inspect both Outward Calls and Incoming References.
2. When working with interfaces or abstract classes, run `sot implementations "<interface>"` to identify all concrete implementations.
3. Ensure you understand all upstream callers before changing signatures.
4. Before finalizing changes or submitting PRs, run `sot diff-impact` (or `xd://sot_diff_impact`) to analyze blast radius, upstream inward callers, API contract impacts, and affected tests.
5. Inspect commit risk history via `sot log` (or `xd://sot_git_history`).

## 5. Context Isolation & Hard-Budget Subgraph Packaging Protocol
- When modifying multi-module features, avoid reading dozens of raw source files sequentially.
- Run `sot pack "<symbol>" --tokens 1500 --json` (or `xd://sot_pack`) to generate a token-efficient YAML ContextBundle for subagents.

## 6. Self-Healing & Drift Reconciliation
- If you create, move, or delete files, run:
  `sot reconcile` or `sot_reconcile` tool (or `sot batch-reconcile` for monorepo roots).
- After completing tricky bugs or complex architectural designs, record knowledge:
  `sot insert --title "..." --body "..." --keywords "..."`.

## 7. Architecture Analysis & Fact Bundle Protocol
When requested to review or synthesize comprehensive architecture documentation for a repository:
1. Run `sot bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/`.
2. Ingest the 5 fact files (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`) along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`.
3. Output the 6-section report in Vietnamese with facts grounded ONLY in the generated bundle files (mark anything beyond them as `[INFERENCE]`), valid ASCII/Mermaid diagrams, and prioritized recommendations.

## 8. Two-Tier Context & Code Intelligence Directive (SOT-Graph + Context-Mode)

### Tier 1: SOT-Graph First (Code Intelligence & Navigation)
1. **Zero Raw-Code Discovery**:
   - NEVER run sequential full-file reads or blind `grep`/`glob` across repositories when `.sot/sot.db` or SOT tools exist.
   - Use SOT-Graph (`sot search`, `sot explore`, `sot usages`, `sot implementations`, `sot pack`) to locate symbols, class hierarchies, caller chains, and dependencies in sub-second time.
   - (Note: codebase-memory and graphify are strictly backend extractors; do NOT configure or invoke them as direct agent skills/MCPs to prevent context bloat).
2. **AST Range-Bounded Reading**:
   - Inspect source code strictly using line-anchored range selectors (`file:start-end`) pinpointed by SOT-Graph coordinates or AST signatures.
3. **Reverse Call-Graph Blast Radius**:
   - Prior to modifying or refactoring any method/function/class, run `sot usages` / `sot explore` / `sot diff-impact` to audit all upstream callers and incoming references.
4. **Targeted Test Target Selection**:
   - Run only the specific affected unit tests identified by the dependency graph blast radius (`sot diff-impact`) instead of full-suite testing during iteration.

### Tier 2: Context-Mode Sandboxing (High-Volume Output & Large File Isolation)
1. **Sandboxed Command Execution & Large File Processing**:
   - High-volume terminal outputs (test runners, builds, long logs) and large raw files (>100 lines) MUST use `context-mode` (`ctx_execute`, `ctx_execute_file`, `ctx_search`) or redirect to temporary files.
2. **Receipt-Only Main Context Ingestion**:
   - NEVER dump multi-hundred-line raw terminal output or raw file bytes into the main conversation context.
   - Extract only actionable compressed summaries, failure receipts (failing test name, exact `file:line` anchor, root exception trace), and status codes into context.

## 9. Reviewer & Planner Receipt Duties
- Reviewer: compare the final diff against the PRE and POST receipts — verify every pre-receipt caller was either updated or still compiles, and that the post receipt's `closure_decision` is `closed` (no remaining gaps) before approving.
- Planner: read the scope receipt's `source_anchors` (path + line span) and `known_gaps`/coverage note before assigning work; never plan edits into files the receipt marks UNKNOWN.

## 10. Markdown, LaTeX & Unicode Rendering Rules (Dual-Target: Human & AI)
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
