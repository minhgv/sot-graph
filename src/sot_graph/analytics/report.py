from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from sot_graph.analytics.diagnostics import AnalysisResult


def generate_markdown_report(
    analysis: AnalysisResult,
    project_name: str = "Project",
    scope: Optional[str] = None,
) -> str:
    """Generate a comprehensive, structured Markdown architectural analysis report."""
    m = analysis.metrics
    cr = analysis.community_result
    now = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    lines = [
        f"# Architectural Knowledge Graph Report: {project_name}",
        "",
        f"> Generated on **{now}** by `sot-graph`"
        + (f" (Scope: `{scope}`)" if scope else ""),
        "",
        "## 1. Executive Summary & Graph Topology",
        "",
        "| Metric | Value | Description |",
        "| :--- | :--- | :--- |",
        f"| **Total Nodes** | `{m.node_count}` | Total entities in knowledge graph |",
        f"| **Total Edges** | `{m.edge_count}` | Resolved dependency & call relationships |",
        f"| **Indexed Files** | `{m.file_count}` | Source code & documentation files |",
        f"| **Symbols** | `{m.symbol_count}` | Functions, classes, structs, methods |",
        f"| **Communities** | `{m.community_count}` | Detected architectural functional clusters |",
        f"| **Graph Density** | `{m.density:.6f}` | Interconnectedness ratio ($E / E_{{max}}$) |",
        f"| **Average Degree** | `{m.avg_degree:.2f}` | Mean relationships per node |",
        f"| **Modularity (Q)** | `{m.modularity:.4f}` | Community separation quality score |",
        f"| **Isolated Nodes** | `{m.isolated_nodes}` | Nodes with zero active relationships |",
        "",
        "---",
        "",
        "## 2. Architectural Communities & Module Breakdown",
        "",
        "Communities represent coherent functional domains discovered via topological graph clustering:",
        "",
        "| ID | Community / Domain | Nodes | Cohesion | Internal Edges | External Edges | Sample Symbols / Paths |",
        "| :-: | :--- | :-: | :-: | :-: | :-: | :--- |",
    ]

    for cid, info in sorted(
        cr.community_info.items(), key=lambda x: len(x[1].nodes), reverse=True
    ):
        sample_nodes = ", ".join(
            [f"`{n.split(':')[-1]}`" for n in info.nodes[:3]]
        )
        if len(info.nodes) > 3:
            sample_nodes += f" *(+{len(info.nodes) - 3} more)*"

        cohesion_pct = f"{int(info.cohesion_score * 100)}%"
        lines.append(
            f"| `{cid}` | **{info.label}** | `{len(info.nodes)}` | `{cohesion_pct}` | `{info.internal_edges}` | `{info.external_edges}` | {sample_nodes} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 3. Critical God Nodes & Architectural Bottlenecks",
            "",
            "God Nodes are hyper-connected hubs with high in/out degree. Changes to these nodes carry high blast radius risks:",
            "",
            "| Node / Symbol | Kind | Location | Degree (In/Out) | Blast Radius | Risk Level | Score |",
            "| :--- | :--- | :--- | :-: | :-: | :-: | :-: |",
        ]
    )

    if analysis.god_nodes:
        for g in analysis.god_nodes:
            loc = (
                f"`{g.path}:{g.line_start}`"
                if g.path and g.line_start
                else (f"`{g.path}`" if g.path else "N/A")
            )
            risk_badge = (
                f"🔴 **{g.risk_level}**"
                if g.risk_level == "CRITICAL"
                else (
                    f"🟡 **{g.risk_level}**"
                    if g.risk_level == "HIGH"
                    else f"🟢 **{g.risk_level}**"
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
            "## 4. Cross-Cutting & Boundary Coupling",
            "",
            "Dependencies spanning across separate architectural communities:",
            "",
            "| Source | Source Cluster | Target | Target Cluster | Relation | Coupling Weight |",
            "| :--- | :--- | :--- | :--- | :--- | :-: |",
        ]
    )

    if analysis.surprising_connections:
        for s in analysis.surprising_connections[:15]:
            src_lbl = f"`{s.src_label}`"
            dst_lbl = f"`{s.dst_label}`"
            c_src = f"Community `{s.src_community}`"
            c_dst = f"Community `{s.dst_community}`"
            lines.append(
                f"| {src_lbl} | {c_src} | {dst_lbl} | {c_dst} | `{s.relation}` | `{int(s.weight)}` |"
            )
    else:
        lines.append(
            "| *(None)* | - | *(None)* | - | - | - |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 5. Actionable Recommendations & Focus Areas",
            "",
        ]
    )

    for i, rec in enumerate(analysis.suggested_focus_areas, 1):
        lines.append(f"{i}. {rec}")

    lines.append("")
    return "\n".join(lines)


def save_markdown_report(report_content: str, output_path: str) -> None:
    """Write markdown report to disk."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(report_content, encoding="utf-8")
