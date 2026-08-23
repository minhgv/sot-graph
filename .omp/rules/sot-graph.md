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
