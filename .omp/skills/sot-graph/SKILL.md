---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, graph analytics (Louvain clustering, God Node detection, HTML/GraphRAG/Obsidian export), and 2-stage fact bundle extraction for comprehensive LLM architecture reports.
---

# /sot-graph (Single Source of Truth Knowledge Layer)

When to use:
- **Before writing or implementing code**: Search if utilities or existing solutions already exist (`sot search` / `sot_search`).
- **Before modifying core functions or classes**: Trace upstream/downstream dependencies (`sot explore` / `sot_explore`).
- **Verifying disk consistency**: Audit phantom anchors and drift (`sot verify` / `sot_verify`).
- **Recording knowledge**: Record non-obvious architecture choices or critical bug solutions (`sot insert` / `sot_insert`).
- **Architecture analysis & 2-Stage Report Generation**:
  - **Stage 1 (Fact Extraction)**: Run `sot bundle` (or tool `sot_bundle`) to produce 5 dense fact files in `.sot/bundle/`.
  - **Stage 2 (Report Synthesis)**: LLM reads the 5 fact files + `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md` to synthesize the complete Vietnamese architecture report.

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
| **Architecture Report** | `./bin/sot report [-o report.md]` | `sot_report(...)` |
| **Extract Fact Bundle** | `./bin/sot bundle [-o .sot/bundle/]` | `sot_bundle(...)` |
| **Interactive Viz** | `./bin/sot viz [-o graph.html]` | `sot_viz(...)` |
| **Export Graph** | `./bin/sot export --format obsidian` | `sot_export(...)` |

## 2-Stage Architecture Report Synthesis Workflow
When requested to write a complete architecture analysis or review report for any repository:

1. **Stage 1: Fact Extraction (Machine-Level)**
   - Run `sot reconcile` to ensure database matches filesystem reality.
   - Run `sot bundle` to generate 5 high-density fact bundle files in `.sot/bundle/`:
     - `01_module_inventory.md`: Bounded functional modules, core models, entrypoints, and internal files.
     - `02_routing_endpoints.md`: API routes, HTTP methods, controllers, and input/output contracts.
     - `03_workflows_states.md`: State machines, state transitions, and end-to-end execution paths.
     - `04_dependencies_violations.md`: Architectural layer classification, cross-layer dependency matrix, and layer violations.
     - `05_system_metrics.json`: Graph density, modularity score Q, average degree, community count.
2. **Stage 2: LLM Report Synthesis (Human & AI-Level)**
   - Ingest the 5 fact files along with `src/sot_graph/templates/ARCHITECTURE_TEMPLATE.md`.
   - Synthesize the comprehensive Markdown report following the 6 standard sections:
     - **I. Khái Quát Hệ Thống & Topology**: Architecture style, Modularity score Q, stack, overall Mermaid diagram.
     - **II. Danh Mục Phân Hệ & Tính Năng Chi Tiết (Functional Modules)**: Deep breakdown of all functional modules, models, and entrypoints.
     - **III. Luồng Routing & Giao Tiếp Endpoint**: Full API inventory, controller mapping, and route table.
     - **IV. State Machine & Quy Trình Nghiệp Vụ Xuyên Suốt**: Sequence diagrams, lifecycles, and cross-module workflows.
     - **V. Ràng Buộc Kiến Trúc & Ma Trận Tương Tác**: Layer dependencies, database access rules, and violation detection.
     - **VI. Đánh Giá Kiến Trúc & Khuyến Nghị Tối Ưu**: Prioritized P0/P1/P2 recommendations with exact code references and concrete implementation solutions.
