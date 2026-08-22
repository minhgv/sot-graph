from __future__ import annotations

import collections
import dataclasses
import math
from typing import Any, Dict, List, Optional, Set, Tuple
from sot_graph.analytics.graph import AnalyticsGraph, CommunityResult
from sot_graph.analytics.architecture import (
    ArchitectureProfile,
    build_architecture_profile,
)

@dataclasses.dataclass
class GodNodeInfo:
    node_id: str
    label: str
    kind: str
    path: str
    line_start: Optional[int]
    in_degree: int
    out_degree: int
    total_degree: int
    score: float
    risk_level: str  # "CRITICAL", "HIGH", "MEDIUM"
    blast_radius: int  # count of reachable nodes within 2 hops


@dataclasses.dataclass
class SurprisingConnection:
    src_id: str
    src_label: str
    src_community: int
    src_path: str
    dst_id: str
    dst_label: str
    dst_community: int
    dst_path: str
    relation: str
    weight: float
    description: str


@dataclasses.dataclass
class GraphMetrics:
    node_count: int
    edge_count: int
    file_count: int
    symbol_count: int
    density: float
    avg_degree: float
    max_degree: int
    community_count: int
    modularity: float
    isolated_nodes: int


@dataclasses.dataclass
class AnalysisResult:
    metrics: GraphMetrics
    community_result: CommunityResult
    god_nodes: List[GodNodeInfo]
    surprising_connections: List[SurprisingConnection]
    suggested_focus_areas: List[str]
    architecture_profile: Optional[ArchitectureProfile] = None

def calculate_graph_metrics(
    graph: AnalyticsGraph, community_res: CommunityResult
) -> GraphMetrics:
    """Calculate summary topology metrics."""
    n = len(graph.nodes)
    m = len(graph.edges)

    file_count = sum(
        1 for d in graph.nodes.values() if d.get("kind") == "file"
    )
    symbol_count = n - file_count

    max_possible_edges = n * (n - 1) if n > 1 else 1
    density = (m / max_possible_edges) if n > 1 else 0.0

    degrees = [graph.degree(node_id) for node_id in graph.nodes]
    avg_deg = sum(degrees) / n if n > 0 else 0.0
    max_deg = max(degrees) if degrees else 0
    isolated = sum(1 for d in degrees if d == 0)

    return GraphMetrics(
        node_count=n,
        edge_count=m,
        file_count=file_count,
        symbol_count=symbol_count,
        density=round(density, 6),
        avg_degree=round(avg_deg, 2),
        max_degree=max_deg,
        community_count=len(community_res.communities),
        modularity=community_res.modularity,
        isolated_nodes=isolated,
    )


def find_god_nodes(
    graph: AnalyticsGraph,
    threshold_sigma: float = 1.5,
    min_degree: int = 4,
) -> List[GodNodeInfo]:
    """
    Identify architectural God Nodes (super-connected hubs / central dependencies).
    A node is flagged if total degree > max(mean + threshold_sigma * std, min_degree).
    """
    if len(graph.nodes) < 3:
        return []

    degrees: Dict[str, int] = {
        node_id: graph.degree(node_id) for node_id in graph.nodes
    }
    values = list(degrees.values())
    mean_val = sum(values) / len(values)
    variance = sum((x - mean_val) ** 2 for x in values) / len(values)
    std_dev = math.sqrt(variance)

    cutoff = max(float(min_degree), mean_val + (threshold_sigma * std_dev))

    god_nodes: List[GodNodeInfo] = []
    for node_id, deg in degrees.items():
        if deg >= cutoff:
            data = graph.nodes.get(node_id, {})
            in_deg = graph.in_degree(node_id)
            out_deg = graph.out_degree(node_id)

            # Calculate 2-hop blast radius
            blast = _calculate_blast_radius(graph, node_id, max_hops=2)

            # Assign risk level based on degree and blast radius
            if deg >= mean_val + (3.0 * std_dev) or blast >= len(graph.nodes) * 0.3:
                risk = "CRITICAL"
            elif deg >= mean_val + (2.0 * std_dev) or blast >= len(graph.nodes) * 0.15:
                risk = "HIGH"
            else:
                risk = "MEDIUM"

            score = (deg - mean_val) / (std_dev if std_dev > 0 else 1.0)
            god_nodes.append(
                GodNodeInfo(
                    node_id=node_id,
                    label=data.get("label", node_id),
                    kind=data.get("kind", "symbol"),
                    path=data.get("path", ""),
                    line_start=data.get("line_start"),
                    in_degree=in_deg,
                    out_degree=out_deg,
                    total_degree=deg,
                    score=round(score, 2),
                    risk_level=risk,
                    blast_radius=blast,
                )
            )

    god_nodes.sort(key=lambda g: (g.total_degree, g.blast_radius), reverse=True)
    return god_nodes


def _calculate_blast_radius(
    graph: AnalyticsGraph, start_node: str, max_hops: int = 2
) -> int:
    """Calculate the number of unique nodes affected within max_hops."""
    visited: Set[str] = {start_node}
    queue: collections.deque[Tuple[str, int]] = collections.deque([(start_node, 0)])

    while queue:
        curr, depth = queue.popleft()
        if depth >= max_hops:
            continue
        # Follow inward and outward edges
        for neighbor in graph.neighbors(curr):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))

    return len(visited) - 1


def find_surprising_connections(
    graph: AnalyticsGraph, community_res: CommunityResult
) -> List[SurprisingConnection]:
    """
    Identify cross-cutting edges connecting different architectural clusters.
    Flags dependencies that bridge separate functional boundaries.
    """
    node_to_comm = community_res.node_to_community
    surprising: List[SurprisingConnection] = []

    # Map inter-community edge frequencies
    comm_links: Dict[Tuple[int, int], List[Dict[str, Any]]] = (
        collections.defaultdict(list)
    )

    for edge in graph.edges:
        src, dst = edge["src"], edge["dst"]
        c_src = node_to_comm.get(src, -1)
        c_dst = node_to_comm.get(dst, -1)

        if c_src != c_dst and c_src != -1 and c_dst != -1:
            comm_links[(c_src, c_dst)].append(edge)

    for (c_src, c_dst), edge_list in comm_links.items():
        src_info = community_res.community_info.get(c_src)
        dst_info = community_res.community_info.get(c_dst)

        src_lbl = src_info.label if src_info else f"Community {c_src}"
        dst_lbl = dst_info.label if dst_info else f"Community {c_dst}"

        # If cross-community coupling exists, capture representative sample
        for e in edge_list[:3]:  # Top 3 links per pair
            src_node = graph.nodes.get(e["src"], {})
            dst_node = graph.nodes.get(e["dst"], {})

            surprising.append(
                SurprisingConnection(
                    src_id=e["src"],
                    src_label=src_node.get("label", e["src"]),
                    src_community=c_src,
                    src_path=src_node.get("path", ""),
                    dst_id=e["dst"],
                    dst_label=dst_node.get("label", e["dst"]),
                    dst_community=c_dst,
                    dst_path=dst_node.get("path", ""),
                    relation=e.get("relation", "relates"),
                    weight=float(len(edge_list)),
                    description=f"Couples '{src_lbl}' -> '{dst_lbl}' via {e.get('relation', 'call')}",
                )
            )

    surprising.sort(key=lambda s: s.weight, reverse=True)
    return surprising


def suggest_focus_areas(
    metrics: GraphMetrics,
    god_nodes: List[GodNodeInfo],
    community_res: CommunityResult,
) -> List[str]:
    """Generate actionable architecture recommendations."""
    suggestions: List[str] = []

    if god_nodes:
        top_god = god_nodes[0]
        suggestions.append(
            f"Review central bottleneck '{top_god.label}' ({top_god.total_degree} connections, blast radius {top_god.blast_radius} nodes) before major refactors."
        )

    # Check for low cohesion communities
    low_cohesion = [
        c
        for c in community_res.community_info.values()
        if c.cohesion_score < 0.4 and len(c.nodes) >= 3
    ]
    if low_cohesion:
        c = low_cohesion[0]
        suggestions.append(
            f"Cluster '{c.label}' has low cohesion ({c.cohesion_score:.2f}) - consider modularizing tightly coupled cross-cutting symbols."
        )

    if metrics.isolated_nodes > 0:
        suggestions.append(
            f"{metrics.isolated_nodes} isolated node(s) detected without active call/import relationships."
        )

    if not suggestions:
        suggestions.append(
            "Architecture structure is well-balanced with clean module boundaries."
        )

    return suggestions


def analyze_graph(
    graph: AnalyticsGraph,
    min_community_size: int = 1,
    threshold_sigma: float = 1.5,
) -> AnalysisResult:
    """Execute complete end-to-end graph intelligence analysis."""
    comm_res = graph.detect_communities(min_community_size=min_community_size)
    metrics = calculate_graph_metrics(graph, comm_res)
    god_nodes = find_god_nodes(graph, threshold_sigma=threshold_sigma)
    surprising = find_surprising_connections(graph, comm_res)
    focus_areas = suggest_focus_areas(metrics, god_nodes, comm_res)

    arch_profile = build_architecture_profile(graph, comm_res)

    return AnalysisResult(
        metrics=metrics,
        community_result=comm_res,
        god_nodes=god_nodes,
        surprising_connections=surprising,
        suggested_focus_areas=focus_areas,
        architecture_profile=arch_profile,
    )
