# SOT-Graph Project Rules for OMP (Oh My Pi)

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

## 5. Architecture Analysis & Report Synthesis Protocol
When requested to review or synthesize comprehensive architecture documentation for a repository:
1. Run `sot bundle` (or tool `sot_bundle`) to generate 5 high-density fact files in `.sot/bundle/`.
2. Ingest the 5 fact files (`01_module_inventory.md`, `02_routing_endpoints.md`, `03_workflows_states.md`, `04_dependencies_violations.md`, `05_system_metrics.json`) along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`.
3. Output the 6-section report in Vietnamese with 100% grounded facts, valid ASCII/Mermaid diagrams, and prioritized P0/P1/P2 recommendations with exact code line references.
