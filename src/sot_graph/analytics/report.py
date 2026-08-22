"""
src/sot_graph/analytics/report.py
Professional, comprehensive Architectural Report generator for sot-graph v3.0.
Dual-Target format: Rich visual diagrams & human-readable breakdown + AI machine-readable JSON-LD.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from sot_graph.analytics.architecture import ArchitecturalLayer
from sot_graph.analytics.diagnostics import AnalysisResult


def generate_jsonld_schema(
    analysis: AnalysisResult,
    project_name: str = "Project",
) -> Dict[str, Any]:
    """Generate structured JSON-LD architectural metadata for AI Agents and LLMs."""
    m = analysis.metrics
    prof = analysis.architecture_profile

    modules_data: List[Dict[str, Any]] = []
    if prof and prof.functional_modules:
        for mod in prof.functional_modules:
            modules_data.append(
                {
                    "@type": "SoftwareModule",
                    "name": mod.name,
                    "category": mod.category,
                    "responsibility": mod.responsibility,
                    "fileCount": mod.file_count,
                    "nodeCount": mod.node_count,
                    "coreEntities": mod.core_entities,
                    "entrypoints": mod.entrypoints,
                    "dependencies": mod.dependencies,
                }
            )

    routes_data: List[Dict[str, Any]] = []
    if prof and prof.routing_architecture:
        ra = prof.routing_architecture
        all_routes = ra.http_routes + ra.ui_routes + ra.event_routes
        for r in all_routes[:30]:
            routes_data.append(
                {
                    "@type": "WebAPIEndpoint" if r.route_type == "HTTP_API" else "NavigationRoute",
                    "routeType": r.route_type,
                    "path": r.path_or_pattern,
                    "handler": r.handler,
                    "fileAnchor": r.file_anchor,
                    "method": r.method,
                    "authGuard": r.auth_guard,
                    "targetLayer": r.target_layer,
                }
            )

    god_nodes_data: List[Dict[str, Any]] = []
    if analysis.god_nodes:
        for g in analysis.god_nodes[:10]:
            god_nodes_data.append(
                {
                    "@type": "CentralComponent",
                    "symbol": g.label,
                    "kind": g.kind,
                    "location": f"{g.path}:{g.line_start}" if g.path else "N/A",
                    "degree": g.total_degree,
                    "blastRadiusNodes": g.blast_radius,
                    "riskLevel": g.risk_level,
                    "centralityScore": round(g.score, 2),
                }
            )

    violations_data: List[Dict[str, Any]] = []
    if prof and prof.violations:
        for v in prof.violations[:10]:
            violations_data.append(
                {
                    "@type": "ArchitecturalViolation",
                    "severity": v.severity,
                    "type": v.violation_type,
                    "source": v.source_node,
                    "target": v.target_node,
                    "description": v.description,
                    "recommendation": v.recommendation,
                }
            )

    return {
        "@context": "https://schema.org/",
        "@type": "SoftwareApplicationArchitecture",
        "name": project_name,
        "engine": "sot-graph v3.0 Architectural Intelligence",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "primaryPattern": prof.pattern_name if prof else "Modular Architecture",
        "primaryLanguage": prof.primary_language if prof else "General",
        "frameworks": prof.framework_hints if prof else [],
        "metrics": {
            "nodeCount": m.node_count,
            "edgeCount": m.edge_count,
            "fileCount": m.file_count,
            "symbolCount": m.symbol_count,
            "modularityScore": round(m.modularity, 4),
            "density": round(m.density, 6),
            "communityCount": m.community_count,
        },
        "functionalModules": modules_data,
        "routingArchitecture": {
            "totalRoutes": prof.routing_architecture.total_routes if prof and prof.routing_architecture else 0,
            "routes": routes_data,
        },
        "criticalHubs": god_nodes_data,
        "violations": violations_data,
    }


def generate_markdown_report(
    analysis: AnalysisResult,
    project_name: str = "Project",
    scope: Optional[str] = None,
) -> str:
    """Generate a comprehensive, structured Markdown architectural analysis report."""
    m = analysis.metrics
    prof = analysis.architecture_profile
    now = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    pattern_name = prof.pattern_name if prof else "Modular Layered Architecture"
    primary_lang = prof.primary_language if prof else "General"
    frameworks_str = (
        ", ".join(prof.framework_hints)
        if prof and prof.framework_hints
        else "Standard Ecosystem"
    )
    modularity_verdict = (
        prof.modularity_verdict
        if prof
        else f"Modularity Q = {m.modularity:.4f}"
    )

    lines = [
        f"# Architectural Knowledge Graph Report: {project_name}",
        "",
        f"> **Generated on:** `{now}` by `sot-graph`"
        + (f" | **Scope:** `{scope}`" if scope else "")
        + " | **Engine:** `v3.0 Architectural Intelligence (Dual-Target: Human & AI)`",
        "",
        "---",
        "",
        "## 1. Executive Summary & Architecture Topology",
        "",
        "| Architecture Dimension | Profile Assessment | Key Evidence / Metric |",
        "| :--- | :--- | :--- |",
        f"| **Primary Architectural Pattern** | **{pattern_name}** | Discovered via AST signatures & layer directory conventions |",
        f"| **Language & Framework Stack** | `{primary_lang}` | Frameworks: *{frameworks_str}* |",
        f"| **Architectural Modularity** | {modularity_verdict} | Louvain Community Quality Score ($Q$) |",
        f"| **Total System Entities** | `{m.node_count}` Nodes (`{m.file_count}` files, `{m.symbol_count}` symbols) | Complete indexed codebase graph surface |",
        f"| **Dependency & Call Edges** | `{m.edge_count}` Relationships | Density: `{m.density:.6f}` (Avg degree: `{m.avg_degree:.2f}`) |",
        f"| **Functional Business Domains** | `{len(prof.domains) if prof else m.community_count}` High-Level Domains | Aggregated from `{m.community_count}` topological clusters |",
        f"| **Functional Modules (Features)** | `{len(prof.functional_modules) if prof and prof.functional_modules else 0}` Structured Modules | Feature taxonomy with responsibilities & core models |",
        f"| **Routing & Entrypoints** | `{prof.routing_architecture.total_routes if prof and prof.routing_architecture else 0}` Endpoints | HTTP APIs, UI Pages & Event Dispatches |",
        f"| **Architectural Integrity** | `{len(prof.violations) if prof else 0}` Warnings / Anti-patterns | Layer bypasses & inverted dependencies |",
        "",
        "---",
        "",
        "## 2. High-Level Design (HLD) & System Context Diagram",
        "",
        "The C4-Container style system context below illustrates client channels, central gateway dispatching, core business domains, supporting platforms, and storage tiers:",
        "",
    ]

    # Add Mermaid HLD Diagram
    if prof and prof.mermaid_hld_diagram:
        lines.append(prof.mermaid_hld_diagram)
    else:
        lines.append("*HLD System Context diagram unavailable.*")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 3. High-Level Architectural Layer Boundary Diagram",
            "",
            "The diagram below reflects the multi-tier separation of concerns and allowed unidirectional dependency flow:",
            "",
        ]
    )

    # Add Mermaid Layer Boundary Diagram
    if prof and prof.mermaid_layer_diagram:
        lines.append(prof.mermaid_layer_diagram)
    else:
        lines.append("*Layer diagram unavailable.*")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 4. Comprehensive Routing & Dispatch Architecture",
            "",
            "System ingress routing, HTTP API endpoints, UI page navigations, and event dispatches mapped across the codebase:",
            "",
        ]
    )

    # Add Mermaid Routing Tree
    if prof and prof.mermaid_routing_tree:
        lines.append("### 4.1 Routing & Dispatch Topology Tree")
        lines.append("")
        lines.append(prof.mermaid_routing_tree)
        lines.append("")

    lines.extend(
        [
            "### 4.2 Endpoint Inventory & Access Control Matrix",
            "",
            "| Route Type | Method | Path / Pattern | Handler & Source File Anchor | Auth Guard | Target Layer |",
            "| :-: | :-: | :--- | :--- | :--- | :--- |",
        ]
    )

    if prof and prof.routing_architecture:
        ra = prof.routing_architecture
        all_routes = ra.http_routes + ra.ui_routes + ra.event_routes
        if all_routes:
            for r in all_routes[:20]:
                type_badge = (
                    "🌐 `HTTP_API`"
                    if r.route_type == "HTTP_API"
                    else (
                        "📱 `UI_PAGE`"
                        if r.route_type == "UI_PAGE"
                        else "⚡ `EVENT`"
                    )
                )
                handler_anchor = f"`{r.handler}`<br/>*({r.file_anchor})*"
                lines.append(
                    f"| {type_badge} | `{r.method}` | `{r.path_or_pattern}` | {handler_anchor} | `{r.auth_guard}` | `{r.target_layer}` |"
                )
            if len(all_routes) > 20:
                lines.append(
                    f"| - | - | *... and {len(all_routes) - 20} more route endpoints* | - | - | - |"
                )
        else:
            lines.append("| - | - | *(No explicit HTTP/UI routes discovered)* | - | - | - |")
    else:
        lines.append("| - | - | *(Routing information unavailable)* | - | - | - |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 5. Functional Module Breakdown & Feature Taxonomy",
            "",
            "Comprehensive decomposition of codebase into bounded functional modules, outlining responsibilities, core domain models, entrypoints, and dependencies:",
            "",
            "| Functional Module | Category | Primary Responsibility | Core Entities / Models | Entrypoints / Handlers | Key Dependencies | Files / Nodes |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :-: |",
        ]
    )

    if prof and prof.functional_modules:
        for mod in prof.functional_modules[:15]:
            entities_str = ", ".join([f"`{e}`" for e in mod.core_entities[:3]]) if mod.core_entities else "*(Internal)*"
            entries_str = ", ".join([f"`{h}`" for h in mod.entrypoints[:2]]) if mod.entrypoints else "*(Service)*"
            deps_str = ", ".join([f"`{d}`" for d in mod.dependencies[:2]]) if mod.dependencies else "*(Independent)*"
            lines.append(
                f"| **{mod.name}** | `{mod.category}` | {mod.responsibility} | {entities_str} | {entries_str} | {deps_str} | `{mod.file_count} f / {mod.node_count} n` |"
            )
        if len(prof.functional_modules) > 15:
            lines.append(
                f"| *... and {len(prof.functional_modules) - 15} more smaller modules* | - | - | - | - | - | - |"
            )
    else:
        lines.append("| *(None)* | - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 6. Core Lifecycle Execution & Data Flow Diagram",
            "",
            "The sequence flow below illustrates the standard end-to-end execution lifecycle from user interaction to data persistence:",
            "",
        ]
    )

    # Add Mermaid Execution Sequence Diagram
    if prof and prof.mermaid_execution_flow:
        lines.append(prof.mermaid_execution_flow)
    else:
        lines.append("*Execution sequence diagram unavailable.*")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 7. Multi-Layer Component Breakdown & Inventory",
            "",
            "Distribution of codebase components across the 5 canonical architectural layers:",
            "",
            "| Architectural Layer | Nodes | Files | Key Responsibilities | Sample Symbols & File Anchors |",
            "| :--- | :-: | :-: | :--- | :--- |",
        ]
    )

    if prof and prof.layer_breakdown:
        layer_roles = {
            ArchitecturalLayer.PRESENTATION: "Screens, Widgets, Views, UI State Rendering, User Interaction Handling",
            ArchitecturalLayer.BUSINESS_LOGIC: "BLoCs, Cubits, ViewModels, Application Services, State Machine Transitions",
            ArchitecturalLayer.DOMAIN: "Domain Entities, UseCases, Business Invariants, Core Interfaces/Contracts",
            ArchitecturalLayer.DATA: "Repositories, DataSources, REST/GraphQL Clients, Local Storage, DTO Models",
            ArchitecturalLayer.CORE: "App Router, DI Container, Theme, Constants, Security, Shared Utilities",
            ArchitecturalLayer.UNKNOWN: "Uncategorized root scripts or standalone config files",
        }

        for layer in [
            ArchitecturalLayer.PRESENTATION,
            ArchitecturalLayer.BUSINESS_LOGIC,
            ArchitecturalLayer.DOMAIN,
            ArchitecturalLayer.DATA,
            ArchitecturalLayer.CORE,
        ]:
            b = prof.layer_breakdown.get(layer)
            if b:
                sample_syms = ", ".join([f"`{s}`" for s in b.top_symbols[:3]]) if b.top_symbols else "*(None)*"
                role = layer_roles.get(layer, "-")
                lines.append(
                    f"| **{layer.value}** | `{b.node_count}` | `{b.file_count}` | {role} | {sample_syms} |"
                )
    else:
        lines.append("| *(None)* | - | - | - | - |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 8. High-Level Business Domains & Subsystems",
            "",
            "Components aggregated into distinct functional domains based on module boundaries and topological cohesion:",
            "",
            "| Domain Subsystem | Category | Nodes | Files | Cohesion | Key Domain Dependencies | Sample Core Entities / Symbols |",
            "| :--- | :--- | :-: | :-: | :-: | :--- | :--- |",
        ]
    )

    if prof and prof.domains:
        for d in prof.domains[:12]:
            cohesion_pct = f"{int(d.cohesion_score * 100)}%"
            deps_str = ", ".join([f"`{dep}`" for dep in d.dependencies[:2]]) if d.dependencies else "*(Independent)*"
            syms_str = ", ".join([f"`{s}`" for s in d.sample_symbols[:3]]) if d.sample_symbols else "*(None)*"
            lines.append(
                f"| **{d.name}** | `{d.category}` | `{d.node_count}` | `{d.file_count}` | `{cohesion_pct}` | {deps_str} | {syms_str} |"
            )
        if len(prof.domains) > 12:
            lines.append(
                f"| *... and {len(prof.domains) - 12} more smaller domain modules* | - | - | - | - | - | - |"
            )
    else:
        lines.append("| *(None)* | - | - | - | - | - | - |")

    # Add Domain Interaction Diagram
    if prof and prof.mermaid_domain_flow and len(prof.domains) > 1:
        lines.extend(
            [
                "",
                "### 8.1 Domain Interaction Matrix",
                "",
                prof.mermaid_domain_flow,
            ]
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 9. Architectural Violations & Structural Warnings",
            "",
            "Detection of architectural smells, layer bypassing, and inverted dependency anti-patterns:",
            "",
            "| Severity | Violation Type | Source Component | Target Component | Description & Remediation |",
            "| :-: | :--- | :--- | :--- | :--- |",
        ]
    )

    if prof and prof.violations:
        for v in prof.violations[:10]:
            sev_badge = (
                "🔴 **CRITICAL**"
                if v.severity == "CRITICAL"
                else (
                    "🟠 **HIGH**"
                    if v.severity == "HIGH"
                    else "🟡 **MEDIUM**"
                )
            )
            src_desc = f"`{v.source_node}`<br/>*({v.source_path})*" if v.source_path else f"`{v.source_node}`"
            tgt_desc = f"`{v.target_node}`<br/>*({v.target_path})*" if v.target_path else f"`{v.target_node}`"
            lines.append(
                f"| {sev_badge} | `{v.violation_type}` | {src_desc} | {tgt_desc} | {v.description}<br/>👉 **Fix:** {v.recommendation} |"
            )
        if len(prof.violations) > 10:
            lines.append(
                f"| - | *... and {len(prof.violations) - 10} additional warnings* | - | - | - |"
            )
    else:
        lines.append(
            "| 🟢 **CLEAN** | `ZERO_VIOLATIONS` | *(All Layers)* | *(All Layers)* | No layer bypasses or inverted dependencies detected. Architecture conforms to unidirectional constraints. |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 10. Critical God Nodes & Blast Radius Assessment",
            "",
            "Hyper-connected hub components that represent potential architectural bottlenecks and blast radius risks:",
            "",
            "| Node / Symbol | Layer / Kind | Location | Degree (In / Out) | 2-Hop Blast Radius | Risk Rating | Centrality Score |",
            "| :--- | :--- | :--- | :-: | :-: | :-: | :-: |",
        ]
    )

    if analysis.god_nodes:
        for g in analysis.god_nodes[:10]:
            loc = (
                f"`{g.path}:{g.line_start}`"
                if g.path and g.line_start
                else (f"`{g.path}`" if g.path else "N/A")
            )
            risk_badge = (
                f"🔴 **{g.risk_level}**"
                if g.risk_level == "CRITICAL"
                else (
                    f"🟠 **{g.risk_level}**"
                    if g.risk_level == "HIGH"
                    else f"🟡 **{g.risk_level}**"
                )
            )
            lines.append(
                f"| `{g.label}` | `{g.kind}` | {loc} | `{g.total_degree}` (`{g.in_degree}` / `{g.out_degree}`) | `{g.blast_radius} nodes` | {risk_badge} | `{g.score:.2f}σ` |"
            )
    else:
        lines.append(
            "| *(None)* | - | - | - | - | 🟢 **BALANCED** | - |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 11. Prioritized Architectural Refactoring Roadmap",
            "",
            "Actionable refactoring recommendations prioritized by structural risk, blast radius, and maintainability:",
            "",
            "### 🔴 Priority P0 — Critical Architectural Invariants & Blast Radius",
        ]
    )

    if prof and prof.recommendations_p0:
        for rec in prof.recommendations_p0:
            lines.append(f"- {rec}")
    else:
        lines.append("- *(No immediate P0 critical blockers)*")

    lines.extend(
        [
            "",
            "### 🟠 Priority P1 — Architectural Hygiene & Layer Separation",
        ]
    )

    if prof and prof.recommendations_p1:
        for rec in prof.recommendations_p1:
            lines.append(f"- {rec}")
    else:
        lines.append("- *(No immediate P1 layer separation warnings)*")

    lines.extend(
        [
            "",
            "### 🟡 Priority P2 — Modularity, Decoupling & Package Isolation",
        ]
    )

    if prof and prof.recommendations_p2:
        for rec in prof.recommendations_p2:
            lines.append(f"- {rec}")
    else:
        lines.append("- *(Architecture is well-modularized)*")

    # Section 12: Machine-Readable JSON-LD
    schema_data = generate_jsonld_schema(analysis, project_name)
    schema_json = json.dumps(schema_data, indent=2, ensure_ascii=False)

    lines.extend(
        [
            "",
            "---",
            "",
            "## 12. Machine-Readable Architecture Schema (JSON-LD)",
            "",
            "Structured architectural metadata for AI coding agents, context injection, and automated CI/CD gating:",
            "",
            "```json",
            schema_json,
            "```",
            "",
        ]
    )

    return "\n".join(lines)


def save_markdown_report(report_content: str, output_path: str) -> None:
    """Write markdown report to disk."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(report_content, encoding="utf-8")
