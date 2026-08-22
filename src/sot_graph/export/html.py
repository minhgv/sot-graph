from __future__ import annotations

import json
import os
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

from sot_graph.analytics.diagnostics import AnalysisResult, analyze_graph
from sot_graph.analytics.graph import AnalyticsGraph


def generate_html_visualizer(
    graph: AnalyticsGraph,
    analysis: Optional[AnalysisResult] = None,
    title: str = "SOT-Graph Knowledge Visualizer",
) -> str:
    """
    Generate a self-contained, standalone interactive HTML visualizer with D3.js.
    Zero external backend needed; embeds nodes, edges, communities, and god-node diagnostics.
    """
    if analysis is None:
        analysis = analyze_graph(graph)

    node_to_comm = analysis.community_result.node_to_community
    god_node_ids = {g.node_id: g for g in analysis.god_nodes}

    # Format nodes for D3
    d3_nodes: List[Dict[str, Any]] = []
    for node_id, data in graph.nodes.items():
        comm_id = node_to_comm.get(node_id, 0)
        comm_info = analysis.community_result.community_info.get(comm_id)
        comm_label = comm_info.label if comm_info else f"Community {comm_id}"

        is_god = node_id in god_node_ids
        god_info = god_node_ids.get(node_id)

        d3_nodes.append({
            "id": node_id,
            "label": data.get("label", node_id),
            "kind": data.get("kind", "symbol"),
            "path": data.get("path", ""),
            "line_start": data.get("line_start"),
            "community": comm_id,
            "community_label": comm_label,
            "in_degree": graph.in_degree(node_id),
            "out_degree": graph.out_degree(node_id),
            "total_degree": graph.degree(node_id),
            "is_god_node": is_god,
            "risk_level": god_info.risk_level if god_info else "NORMAL",
            "blast_radius": god_info.blast_radius if god_info else 0,
        })

    # Format edges for D3
    d3_links: List[Dict[str, Any]] = []
    for e in graph.edges:
        d3_links.append({
            "source": e["src"],
            "target": e["dst"],
            "relation": e.get("relation", "relates"),
            "line": e.get("line"),
        })

    # Community summaries
    communities_data = [
        {
            "id": cid,
            "label": c.label,
            "node_count": len(c.nodes),
            "cohesion": c.cohesion_score,
            "internal_edges": c.internal_edges,
            "external_edges": c.external_edges,
        }
        for cid, c in sorted(
            analysis.community_result.community_info.items(),
            key=lambda x: len(x[1].nodes),
            reverse=True,
        )
    ]

    # Metrics summary
    metrics_data = {
        "node_count": analysis.metrics.node_count,
        "edge_count": analysis.metrics.edge_count,
        "file_count": analysis.metrics.file_count,
        "symbol_count": analysis.metrics.symbol_count,
        "community_count": analysis.metrics.community_count,
        "density": analysis.metrics.density,
        "avg_degree": analysis.metrics.avg_degree,
        "modularity": analysis.metrics.modularity,
    }

    graph_payload = {
        "nodes": d3_nodes,
        "links": d3_links,
        "communities": communities_data,
        "metrics": metrics_data,
        "title": title,
    }

    payload_json = json.dumps(graph_payload)

    # HTML template with embedded D3.js and responsive UI
    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <script src="https://d3js.org/d3.v7.min.js"></script>
  <style>
    :root {{
      --bg: #0d1117;
      --card-bg: #161b22;
      --border: #30363d;
      --text: #c9d1d9;
      --text-muted: #8b949e;
      --primary: #58a6ff;
      --success: #3fb950;
      --warning: #d29922;
      --danger: #f85149;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      display: flex;
      height: 100vh;
      overflow: hidden;
    }}
    #sidebar {{
      width: 360px;
      background: var(--card-bg);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      z-index: 10;
      box-shadow: 2px 0 10px rgba(0,0,0,0.5);
    }}
    .sidebar-header {{
      padding: 16px;
      border-bottom: 1px solid var(--border);
    }}
    .sidebar-header h1 {{
      font-size: 1.1rem;
      color: #fff;
      margin-bottom: 8px;
    }}
    .search-box {{
      width: 100%;
      padding: 8px 12px;
      background: #090d13;
      border: 1px solid var(--border);
      border-radius: 6px;
      color: #fff;
      outline: none;
      font-size: 0.9rem;
    }}
    .search-box:focus {{ border-color: var(--primary); }}
    .stats-bar {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      padding: 12px 16px;
      background: #0e1217;
      border-bottom: 1px solid var(--border);
      font-size: 0.8rem;
      text-align: center;
    }}
    .stat-val {{ font-size: 1.1rem; font-weight: bold; color: var(--primary); }}
    .stat-lbl {{ color: var(--text-muted); font-size: 0.75rem; }}
    .sidebar-content {{
      flex: 1;
      overflow-y: auto;
      padding: 16px;
    }}
    .section-title {{
      font-size: 0.85rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      margin: 12px 0 8px 0;
    }}
    .community-item {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 6px 8px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 0.85rem;
      margin-bottom: 4px;
    }}
    .community-item:hover {{ background: rgba(255,255,255,0.05); }}
    .comm-badge {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 8px;
    }}
    .node-detail-card {{
      background: #090d13;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      margin-top: 8px;
      font-size: 0.85rem;
    }}
    .node-detail-card h3 {{ color: var(--primary); margin-bottom: 6px; font-size: 1rem; word-break: break-all; }}
    .tag {{
      display: inline-block;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 600;
      margin-right: 4px;
    }}
    .tag-file {{ background: #238636; color: #fff; }}
    .tag-symbol {{ background: #1f6feb; color: #fff; }}
    .tag-god {{ background: #da3633; color: #fff; }}
    #graph-container {{
      flex: 1;
      position: relative;
      background: #090d13;
    }}
    svg {{ width: 100%; height: 100%; }}
    .link {{ stroke: #484f58; stroke-opacity: 0.6; stroke-width: 1.2px; }}
    .link.highlighted {{ stroke: #58a6ff; stroke-opacity: 1; stroke-width: 2.5px; }}
    .node {{ cursor: pointer; }}
    .node circle {{ stroke: #30363d; stroke-width: 1.5px; }}
    .node.highlighted circle {{ stroke: #fff; stroke-width: 3px; }}
    .node text {{
      font-size: 11px;
      fill: #8b949e;
      pointer-events: none;
      text-shadow: 0 1px 4px #000;
    }}
    .node.highlighted text {{ fill: #fff; font-weight: bold; }}
    .controls {{
      position: absolute;
      top: 16px;
      right: 16px;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 8px;
      display: flex;
      gap: 8px;
    }}
    .btn {{
      background: #21262d;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 6px 12px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 0.8rem;
    }}
    .btn:hover {{ background: #30363d; color: #fff; }}
  </style>
</head>
<body>
  <div id="sidebar">
    <div class="sidebar-header">
      <h1 id="viz-title">{title}</h1>
      <input type="text" id="search-input" class="search-box" placeholder="Filter symbol, file, community...">
    </div>
    <div class="stats-bar">
      <div><div class="stat-val" id="stat-nodes">0</div><div class="stat-lbl">NODES</div></div>
      <div><div class="stat-val" id="stat-edges">0</div><div class="stat-lbl">EDGES</div></div>
      <div><div class="stat-val" id="stat-comms">0</div><div class="stat-lbl">COMMUNITIES</div></div>
    </div>
    <div class="sidebar-content">
      <div id="inspector-panel" style="display: none;">
        <div class="section-title">Selected Node Details</div>
        <div id="inspector-content" class="node-detail-card"></div>
      </div>
      <div class="section-title">Communities / Modules</div>
      <div id="communities-list"></div>
    </div>
  </div>

  <div id="graph-container">
    <div class="controls">
      <button class="btn" id="btn-reset">Reset Zoom</button>
      <button class="btn" id="btn-gods">Highlight God Nodes</button>
    </div>
    <svg id="viz-svg"></svg>
  </div>

  <script>
    const DATA = {payload_json};

    document.getElementById("stat-nodes").textContent = DATA.metrics.node_count;
    document.getElementById("stat-edges").textContent = DATA.metrics.edge_count;
    document.getElementById("stat-comms").textContent = DATA.metrics.community_count;

    const colors = d3.schemeTableau10.concat(d3.schemePaired);
    const colorScale = d3.scaleOrdinal()
      .domain(DATA.communities.map(c => c.id))
      .range(colors);

    // Populate communities list
    const commList = document.getElementById("communities-list");
    DATA.communities.forEach(c => {{
      const div = document.createElement("div");
      div.className = "community-item";
      div.innerHTML = `
        <div>
          <span class="comm-badge" style="background: ${{colorScale(c.id)}}"></span>
          <span>${{c.label}}</span>
        </div>
        <span style="color: var(--text-muted); font-size: 0.75rem;">${{c.node_count}}</span>
      `;
      div.onclick = () => filterByCommunity(c.id);
      commList.appendChild(div);
    }});

    const svg = d3.select("#viz-svg");
    const container = document.getElementById("graph-container");
    const width = container.clientWidth;
    const height = container.clientHeight;

    const g = svg.append("g");

    const zoom = d3.zoom()
      .scaleExtent([0.1, 8])
      .on("zoom", (e) => g.attr("transform", e.transform));
    svg.call(zoom);

    document.getElementById("btn-reset").onclick = () => {{
      svg.transition().duration(750).call(zoom.transform, d3.zoomIdentity);
    }};

    const simulation = d3.forceSimulation(DATA.nodes)
      .force("link", d3.forceLink(DATA.links).id(d => d.id).distance(60))
      .force("charge", d3.forceManyBody().strength(-180))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(d => (d.is_god_node ? 18 : (d.kind === 'file' ? 14 : 9)) + 2));

    const link = g.append("g")
      .attr("class", "links")
      .selectAll("line")
      .data(DATA.links)
      .enter().append("line")
      .attr("class", "link");

    const node = g.append("g")
      .attr("class", "nodes")
      .selectAll("g")
      .data(DATA.nodes)
      .enter().append("g")
      .attr("class", "node")
      .call(d3.drag()
        .on("start", dragstarted)
        .on("drag", dragged)
        .on("end", dragended))
      .on("click", (e, d) => inspectNode(d));

    node.append("circle")
      .attr("r", d => d.is_god_node ? 14 : (d.kind === "file" ? 10 : 6))
      .attr("fill", d => d.is_god_node ? "#da3633" : colorScale(d.community));

    node.append("text")
      .attr("dx", 12)
      .attr("dy", ".35em")
      .text(d => d.label.length > 24 ? d.label.substring(0, 22) + "..." : d.label);

    simulation.on("tick", () => {{
      link
        .attr("x1", d => d.source.x)
        .attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x)
        .attr("y2", d => d.target.y);

      node
        .attr("transform", d => `translate(${{d.x}},${{d.y}})`);
    }});

    function dragstarted(event, d) {{
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    }}

    function dragged(event, d) {{
      d.fx = event.x;
      d.fy = event.y;
    }}

    function dragended(event, d) {{
      if (!event.active) simulation.alphaTarget(0);
      d.fx = null;
      d.fy = null;
    }}

    function inspectNode(d) {{
      document.getElementById("inspector-panel").style.display = "block";
      const ic = document.getElementById("inspector-content");
      const kindTag = d.kind === "file" ? '<span class="tag tag-file">FILE</span>' : '<span class="tag tag-symbol">SYMBOL</span>';
      const godTag = d.is_god_node ? `<span class="tag tag-god">GOD NODE (${{d.risk_level}})</span>` : '';

      ic.innerHTML = `
        <h3>${{d.label}}</h3>
        <div style="margin-bottom: 8px;">${{kindTag}} ${{godTag}}</div>
        <p><strong>Path:</strong> ${{d.path ? d.path : 'N/A'}}</p>
        <p><strong>Location:</strong> Line ${{d.line_start || 1}}</p>
        <p><strong>Community:</strong> ${{d.community_label}}</p>
        <p><strong>Connections:</strong> Total ${{d.total_degree}} (In: ${{d.in_degree}}, Out: ${{d.out_degree}})</p>
        ${{d.is_god_node ? `<p><strong>Blast Radius:</strong> ${{d.blast_radius}} nodes</p>` : ''}}
      `;

      // Highlight neighbors
      node.classed("highlighted", n => n.id === d.id);
      link.classed("highlighted", l => l.source.id === d.id || l.target.id === d.id);
    }}

    function filterByCommunity(commId) {{
      node.style("opacity", d => d.community === commId ? 1 : 0.15);
      link.style("opacity", l => (l.source.community === commId && l.target.community === commId) ? 0.8 : 0.05);
    }}

    document.getElementById("search-input").oninput = (e) => {{
      const query = e.target.value.toLowerCase().trim();
      if (!query) {{
        node.style("opacity", 1);
        link.style("opacity", 0.6);
        return;
      }}
      node.style("opacity", d => (d.label.toLowerCase().includes(query) || (d.path && d.path.toLowerCase().includes(query))) ? 1 : 0.1);
      link.style("opacity", 0.1);
    }};

    let godHighlight = false;
    document.getElementById("btn-gods").onclick = () => {{
      godHighlight = !godHighlight;
      if (godHighlight) {{
        node.style("opacity", d => d.is_god_node ? 1 : 0.15);
        link.style("opacity", l => (l.source.is_god_node || l.target.is_god_node) ? 0.9 : 0.05);
      }} else {{
        node.style("opacity", 1);
        link.style("opacity", 0.6);
      }}
    }};
  </script>
</body>
</html>
"""
    return html_template


def save_html_visualizer(
    html_content: str, output_path: str = "graph.html", open_browser: bool = False
) -> str:
    """Save HTML visualizer to disk and optionally launch web browser."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html_content, encoding="utf-8")

    if open_browser:
        abs_path = os.path.abspath(output_path)
        try:
            webbrowser.open(f"file://{abs_path}")
        except Exception:
            pass

    return str(p)
