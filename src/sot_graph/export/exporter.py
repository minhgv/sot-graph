from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from sot_graph.analytics.diagnostics import AnalysisResult, analyze_graph
from sot_graph.analytics.graph import AnalyticsGraph


def export_graphrag_json(
    graph: AnalyticsGraph,
    analysis: Optional[AnalysisResult] = None,
    output_path: Optional[str] = "graphrag.json",
) -> Dict[str, Any]:
    """
    Export knowledge graph into GraphRAG-ready JSON schema.
    Includes entities, relationships, communities, and document references.
    """
    if analysis is None:
        analysis = analyze_graph(graph)

    node_to_comm = analysis.community_result.node_to_community
    god_map = {g.node_id: g for g in analysis.god_nodes}

    entities: List[Dict[str, Any]] = []
    for node_id, data in graph.nodes.items():
        comm_id = node_to_comm.get(node_id, 0)
        god = god_map.get(node_id)
        entities.append({
            "id": node_id,
            "title": data.get("label", node_id),
            "type": data.get("kind", "symbol").upper(),
            "description": data.get("body", ""),
            "path": data.get("path", ""),
            "line_start": data.get("line_start"),
            "community_id": comm_id,
            "degree": graph.degree(node_id),
            "in_degree": graph.in_degree(node_id),
            "out_degree": graph.out_degree(node_id),
            "is_hub": bool(god),
            "risk_level": god.risk_level if god else "NORMAL",
        })

    relationships: List[Dict[str, Any]] = []
    for e in graph.edges:
        relationships.append({
            "source": e["src"],
            "target": e["dst"],
            "relation": e.get("relation", "relates"),
            "line": e.get("line"),
            "path": e.get("path", ""),
        })

    communities: List[Dict[str, Any]] = []
    for cid, c in sorted(
        analysis.community_result.community_info.items(),
        key=lambda x: len(x[1].nodes),
        reverse=True,
    ):
        communities.append({
            "id": cid,
            "title": c.label,
            "node_count": len(c.nodes),
            "cohesion_score": c.cohesion_score,
            "internal_edges": c.internal_edges,
            "external_edges": c.external_edges,
            "nodes": c.nodes,
        })

    payload = {
        "version": "1.0.0",
        "metadata": {
            "node_count": len(entities),
            "edge_count": len(relationships),
            "community_count": len(communities),
            "density": analysis.metrics.density,
            "modularity": analysis.metrics.modularity,
        },
        "entities": entities,
        "relationships": relationships,
        "communities": communities,
    }

    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return payload


def export_obsidian_vault(
    graph: AnalyticsGraph,
    output_dir: str = "obsidian_vault",
    analysis: Optional[AnalysisResult] = None,
) -> int:
    """
    Export knowledge graph as an Obsidian vault of interconnected Markdown files
    with YAML frontmatter and [[wikilinks]] for graph exploration in Obsidian.
    """
    if analysis is None:
        analysis = analyze_graph(graph)

    vault_path = Path(output_dir)
    vault_path.mkdir(parents=True, exist_ok=True)

    node_to_comm = analysis.community_result.node_to_community
    god_map = {g.node_id: g for g in analysis.god_nodes}

    reserved = {"Index"} | {
        f"Community_{cid}"
        for cid in analysis.community_result.community_info
    }
    vault_names = _unique_vault_names(graph, reserved)

    files_created = 0

    # Create an Index MOC (Map of Content)
    moc_lines = [
        "---",
        "tags: [sot-graph, moc, architecture]",
        "---",
        "# Knowledge Graph Index (Map of Content)",
        "",
        f"- **Total Entities**: `{len(graph.nodes)}`",
        f"- **Total Connections**: `{len(graph.edges)}`",
        f"- **Communities**: `{len(analysis.community_result.communities)}`",
        "",
        "## Communities",
        "",
    ]
    for cid, c in sorted(
        analysis.community_result.community_info.items(),
        key=lambda x: len(x[1].nodes),
        reverse=True,
    ):
        moc_lines.append(f"- [[Community_{cid}|{c.label}]] (`{len(c.nodes)}` entities)")

    (vault_path / "Index.md").write_text("\n".join(moc_lines), encoding="utf-8")
    files_created += 1

    # Write community files
    for cid, c in analysis.community_result.community_info.items():
        comm_lines = [
            "---",
            f"community_id: {cid}",
            f"cohesion: {c.cohesion_score}",
            "tags: [community, cluster]",
            "---",
            f"# Community: {c.label}",
            "",
            f"- **Cohesion Score**: `{int(c.cohesion_score * 100)}%`",
            f"- **Internal Edges**: `{c.internal_edges}`",
            f"- **External Edges**: `{c.external_edges}`",
            "",
            "## Entities in this Cluster",
            "",
        ]
        for nid in c.nodes:
            label = graph.nodes.get(nid, {}).get("label", nid)
            safe_name = vault_names.get(nid, _sanitize_filename(nid))
            comm_lines.append(f"- [[{safe_name}|{label}]]")

        (vault_path / f"Community_{cid}.md").write_text(
            "\n".join(comm_lines), encoding="utf-8"
        )
        files_created += 1

    # Write individual entity files
    for node_id, data in graph.nodes.items():
        safe_name = vault_names[node_id]
        label = data.get("label", node_id)
        kind = data.get("kind", "symbol")
        path = data.get("path", "")
        line_start = data.get("line_start", 1)
        cid = node_to_comm.get(node_id, 0)
        god = god_map.get(node_id)

        # Gather outgoing and incoming relationships
        outgoing = graph._adj_out.get(node_id, [])
        incoming = graph._adj_in.get(node_id, [])

        lines = [
            "---",
            f"id: \"{node_id}\"",
            f"kind: \"{kind}\"",
            f"path: \"{path}\"",
            f"line: {line_start}",
            f"community: {cid}",
            f"is_god_node: {bool(god)}",
            "tags: [sot-node, " + (kind if kind else "symbol") + "]",
            "---",
            f"# {label}",
            "",
            f"- **Kind**: `{kind}`",
            f"- **File Path**: `{path}` (Line: `{line_start}`)",
            f"- **Community**: [[Community_{cid}]]",
            f"- **Connections**: In `{len(incoming)}` / Out `{len(outgoing)}`",
        ]

        if god:
            lines.append(f"- **Risk Level**: `{god.risk_level}` (Blast Radius: `{god.blast_radius}` nodes)")

        if outgoing:
            lines.extend(["", "## Outgoing Dependencies", ""])
            for target_id, rel in outgoing:
                target_lbl = graph.nodes.get(target_id, {}).get("label", target_id)
                target_safe = vault_names.get(target_id, _sanitize_filename(target_id))
                lines.append(f"- `{rel}` -> [[{target_safe}|{target_lbl}]]")

        if incoming:
            lines.extend(["", "## Used By (Incoming)", ""])
            for src_id, rel in incoming:
                src_lbl = graph.nodes.get(src_id, {}).get("label", src_id)
                src_safe = vault_names.get(src_id, _sanitize_filename(src_id))
                lines.append(f"- `{rel}` <- [[{src_safe}|{src_lbl}]]")

        body = data.get("body", "")
        if body:
            lines.extend(["", "## Content / Definition", "", "```", body[:500], "```"])

        (vault_path / f"{safe_name}.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )
        files_created += 1

    return files_created


def export_graphml(
    graph: AnalyticsGraph,
    output_path: str = "graph.graphml",
    analysis: Optional[AnalysisResult] = None,
) -> None:
    """Export knowledge graph to standard GraphML XML for Gephi / Cytoscape."""
    if analysis is None:
        analysis = analyze_graph(graph)

    node_to_comm = analysis.community_result.node_to_community
    god_map = {g.node_id: g for g in analysis.god_nodes}

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '  <key id="label" for="node" attr.name="label" attr.type="string"/>',
        '  <key id="kind" for="node" attr.name="kind" attr.type="string"/>',
        '  <key id="path" for="node" attr.name="path" attr.type="string"/>',
        '  <key id="community" for="node" attr.name="community" attr.type="int"/>',
        '  <key id="is_god" for="node" attr.name="is_god" attr.type="boolean"/>',
        '  <key id="relation" for="edge" attr.name="relation" attr.type="string"/>',
        '  <graph id="sot_graph" edgedefault="directed">',
    ]

    for node_id, data in graph.nodes.items():
        lbl = html.escape(data.get("label", node_id))
        k = html.escape(data.get("kind", "symbol"))
        p = html.escape(data.get("path", ""))
        cid = node_to_comm.get(node_id, 0)
        is_god = "true" if node_id in god_map else "false"

        xml_lines.append(f'    <node id="{html.escape(node_id)}">')
        xml_lines.append(f'      <data key="label">{lbl}</data>')
        xml_lines.append(f'      <data key="kind">{k}</data>')
        xml_lines.append(f'      <data key="path">{p}</data>')
        xml_lines.append(f'      <data key="community">{cid}</data>')
        xml_lines.append(f'      <data key="is_god">{is_god}</data>')
        xml_lines.append('    </node>')

    for i, e in enumerate(graph.edges):
        src = html.escape(e["src"])
        dst = html.escape(e["dst"])
        rel = html.escape(e.get("relation", "relates"))
        xml_lines.append(
            f'    <edge id="e{i}" source="{src}" target="{dst}">'
        )
        xml_lines.append(f'      <data key="relation">{rel}</data>')
        xml_lines.append('    </edge>')

    xml_lines.append('  </graph>')
    xml_lines.append('</graphml>')

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(xml_lines), encoding="utf-8")


def _sanitize_filename(name: str) -> str:
    """Convert arbitrary node ID to a safe filesystem filename."""
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(ch, '_')
    return name[:120]


def _unique_vault_names(
    graph: "AnalyticsGraph", reserved: "set[str]"
) -> "dict[str, str]":
    """Deterministic collision-free vault filenames for every node.

    Two distinct node ids can sanitize to the same filename — illegal
    characters collapsing into ``_``, or the 120-char truncation chopping
    the distinguishing suffix. Without disambiguation the second note
    silently overwrote the first and every ``[[wikilink]]`` pointed at
    the surviving note. ``-2``, ``-3``, ... suffixes (deterministic in
    node iteration order) keep files and links consistent.
    """
    names: dict[str, str] = {}
    used: set[str] = set(reserved)
    for node_id in graph.nodes:
        base = _sanitize_filename(node_id)
        name = base
        n = 2
        while name in used:
            name = f"{base}-{n}"
            n += 1
        names[node_id] = name
        used.add(name)
    return names
