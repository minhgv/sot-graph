from __future__ import annotations

import collections
import dataclasses
import math
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from sot_graph.db import Database
else:
    Database = Any

@dataclasses.dataclass
class CommunityInfo:
    community_id: int
    label: str
    nodes: List[str]
    cohesion_score: float
    internal_edges: int
    external_edges: int


@dataclasses.dataclass
class CommunityResult:
    communities: Dict[int, List[str]]
    community_info: Dict[int, CommunityInfo]
    node_to_community: Dict[str, int]
    modularity: float


class AnalyticsGraph:
    """In-memory directed multigraph representation optimized for architectural analytics."""

    def __init__(self) -> None:
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []
        self._adj_out: Dict[str, List[Tuple[str, str]]] = collections.defaultdict(list)
        self._adj_in: Dict[str, List[Tuple[str, str]]] = collections.defaultdict(list)
        self._undirected_adj: Dict[str, Set[str]] = collections.defaultdict(set)

    def add_node(
        self,
        node_id: str,
        label: str = "",
        kind: str = "symbol",
        path: str = "",
        line_start: Optional[int] = None,
        body: str = "",
        keywords: str = "",
        **extra: Any,
    ) -> None:
        self.nodes[node_id] = {
            "id": node_id,
            "label": label or node_id,
            "kind": kind,
            "path": path,
            "line_start": line_start,
            "body": body,
            "keywords": keywords,
            **extra,
        }
        # Ensure adj entries exist
        _ = self._adj_out[node_id]
        _ = self._adj_in[node_id]
        _ = self._undirected_adj[node_id]

    def add_edge(
        self,
        src: str,
        dst: str,
        relation: str = "relates",
        path: str = "",
        line: Optional[int] = None,
        **extra: Any,
    ) -> None:
        edge_data = {
            "src": src,
            "dst": dst,
            "relation": relation,
            "path": path,
            "line": line,
            **extra,
        }
        self.edges.append(edge_data)
        self._adj_out[src].append((dst, relation))
        self._adj_in[dst].append((src, relation))
        self._undirected_adj[src].add(dst)
        self._undirected_adj[dst].add(src)

    @classmethod
    def from_connection(
        cls, conn: sqlite3.Connection, scope: Optional[str] = None
    ) -> "AnalyticsGraph":
        """Build an AnalyticsGraph directly from a SQLite connection in two fast batch queries."""
        graph = cls()

        # Query nodes
        if scope:
            like_pattern = f"{scope}%"
            node_rows = conn.execute(
                "SELECT id, label, kind, path, line_start, body, keywords "
                "FROM graph_nodes WHERE path LIKE ?",
                (like_pattern,),
            ).fetchall()
        else:
            node_rows = conn.execute(
                "SELECT id, label, kind, path, line_start, body, keywords FROM graph_nodes"
            ).fetchall()

        valid_node_ids: Set[str] = set()
        for r in node_rows:
            node_id = r[0]
            valid_node_ids.add(node_id)
            graph.add_node(
                node_id=node_id,
                label=r[1] or "",
                kind=r[2] or "symbol",
                path=r[3] or "",
                line_start=r[4],
                body=r[5] or "",
                keywords=r[6] or "",
            )

        # Query edges
        if scope:
            like_pattern = f"{scope}%"
            edge_rows = conn.execute(
                "SELECT src, dst, relation, path, line "
                "FROM graph_edges WHERE path LIKE ?",
                (like_pattern,),
            ).fetchall()
        else:
            edge_rows = conn.execute(
                "SELECT src, dst, relation, path, line FROM graph_edges"
            ).fetchall()

        for r in edge_rows:
            src, dst = r[0], r[1]
            # Ensure endpoints exist
            if src not in valid_node_ids:
                graph.add_node(src, label=src, kind="inferred")
                valid_node_ids.add(src)
            if dst not in valid_node_ids:
                graph.add_node(dst, label=dst, kind="inferred")
                valid_node_ids.add(dst)

            graph.add_edge(
                src=src,
                dst=dst,
                relation=r[2] or "relates",
                path=r[3] or "",
                line=r[4],
            )

        return graph

    @classmethod
    def from_database(
        cls, db: Database, scope: Optional[str] = None
    ) -> "AnalyticsGraph":
        """Build an AnalyticsGraph from a Database instance."""
        return cls.from_connection(db.conn, scope=scope)

    def in_degree(self, node_id: str) -> int:
        return len(self._adj_in.get(node_id, []))

    def out_degree(self, node_id: str) -> int:
        return len(self._adj_out.get(node_id, []))

    def degree(self, node_id: str) -> int:
        return self.in_degree(node_id) + self.out_degree(node_id)

    def neighbors(self, node_id: str) -> Set[str]:
        return self._undirected_adj.get(node_id, set())

    def connected_components(self) -> List[Set[str]]:
        """Find all connected components using BFS."""
        visited: Set[str] = set()
        components: List[Set[str]] = []

        for node_id in self.nodes:
            if node_id in visited:
                continue
            component: Set[str] = set()
            queue = collections.deque([node_id])
            visited.add(node_id)

            while queue:
                current = queue.popleft()
                component.add(current)
                for neighbor in self._undirected_adj.get(current, set()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            components.append(component)

        components.sort(key=len, reverse=True)
        return components

    def detect_communities(
        self,
        seed: int = 42,
        max_iterations: int = 30,
        min_community_size: int = 1,
    ) -> CommunityResult:
        """
        Detect architectural communities using an asynchronous Label Propagation Algorithm (LPA)
        with modularity refinement in pure Python standard library.
        If networkx is available, leverages Louvain / greedy modularity when beneficial.
        """
        if not self.nodes:
            return CommunityResult(
                communities={},
                community_info={},
                node_to_community={},
                modularity=0.0,
            )

        # Try networkx community detection if installed
        nx_communities = self._try_networkx_community()
        if nx_communities is not None:
            raw_communities = nx_communities
        else:
            raw_communities = self._label_propagation_community(
                seed=seed, max_iterations=max_iterations
            )

        # Filter and normalize communities: sort by size descending, assign 0..N IDs
        sorted_raw = sorted(
            [c for c in raw_communities if len(c) >= min_community_size],
            key=lambda c: (len(c), sorted(list(c))[0] if c else ""),
            reverse=True,
        )

        # Put any small omitted nodes into an 'Other' / singleton communities
        accounted: Set[str] = set()
        for c in sorted_raw:
            accounted.update(c)

        unaccounted = [n for n in self.nodes if n not in accounted]
        if unaccounted:
            sorted_raw.append(set(unaccounted))

        communities: Dict[int, List[str]] = {}
        node_to_comm: Dict[str, int] = {}
        community_info: Dict[int, CommunityInfo] = {}

        for cid, node_set in enumerate(sorted_raw):
            sorted_nodes = sorted(list(node_set))
            communities[cid] = sorted_nodes
            for n in sorted_nodes:
                node_to_comm[n] = cid

            # Compute label and cohesion
            label = self._generate_community_label(sorted_nodes)
            cohesion, internal_e, external_e = self.calculate_cohesion_stats(
                node_set
            )
            community_info[cid] = CommunityInfo(
                community_id=cid,
                label=label,
                nodes=sorted_nodes,
                cohesion_score=cohesion,
                internal_edges=internal_e,
                external_edges=external_e,
            )

        modularity = self.calculate_modularity(node_to_comm)

        return CommunityResult(
            communities=communities,
            community_info=community_info,
            node_to_community=node_to_comm,
            modularity=modularity,
        )
    def _try_networkx_community(self) -> Optional[List[Set[str]]]:
        try:
            import networkx as nx  # type: ignore[import-not-found]

            G = nx.Graph()
            for node_id in self.nodes:
                G.add_node(node_id)
            for e in self.edges:
                G.add_edge(e["src"], e["dst"])

            if G.number_of_nodes() == 0:
                return []

            # Use louvain_communities if available (nx 2.8+)
            if hasattr(nx.community, "louvain_communities"):
                comms = nx.community.louvain_communities(G, seed=42)
                return [set(c) for c in comms]
            elif hasattr(nx.community, "greedy_modularity_communities"):
                comms = nx.community.greedy_modularity_communities(G)
                return [set(c) for c in comms]
        except Exception:
            pass
        return None

    def _label_propagation_community(
        self, seed: int = 42, max_iterations: int = 30
    ) -> List[Set[str]]:
        """Asynchronous Label Propagation Algorithm (pure Python stdlib)."""
        import random

        rng = random.Random(seed)
        # Initialize each node with unique label
        labels: Dict[str, str] = {n: n for n in self.nodes}
        nodes_list = list(self.nodes.keys())

        for _ in range(max_iterations):
            rng.shuffle(nodes_list)
            changed = False
            for node in nodes_list:
                neighbors = self._undirected_adj.get(node, set())
                if not neighbors:
                    continue

                # Count neighbor labels
                label_weights: Dict[str, float] = collections.defaultdict(float)
                for neighbor in neighbors:
                    label_weights[labels[neighbor]] += 1.0

                if not label_weights:
                    continue

                # Find max weight labels
                max_weight = max(label_weights.values())
                best_labels = [
                    lbl
                    for lbl, weight in label_weights.items()
                    if math.isclose(weight, max_weight)
                ]

                # If current label is among best, keep it to ensure stability
                if labels[node] not in best_labels:
                    # Pick deterministically using sorted label
                    new_label = sorted(best_labels)[0]
                    labels[node] = new_label
                    changed = True

            if not changed:
                break

        # Group nodes by final label
        groups: Dict[str, Set[str]] = collections.defaultdict(set)
        for node, lbl in labels.items():
            groups[lbl].add(node)

        return list(groups.values())

    def _repo_path_prefix(self) -> str:
        """Longest common directory prefix across all node paths (effectively
        the project root), computed once. Community labels use it to stay
        repo-relative instead of echoing absolute host paths."""
        cached = getattr(self, "_path_prefix_cache", None)
        if cached is not None:
            return cached
        paths = [
            (d.get("path") or "").replace("\\", "/").rstrip("/")
            for d in self.nodes.values()
        ]
        paths = [p for p in paths if "/" in p]
        prefix = ""
        if paths:
            first = paths[0].split("/")
            for i in range(1, len(first)):
                cand = "/".join(first[:i])
                if all(p == cand or p.startswith(cand + "/") for p in paths):
                    prefix = cand
                else:
                    break
        self._path_prefix_cache = prefix
        return prefix

    def _generate_community_label(self, nodes: List[str]) -> str:
        """Derive a human-readable title for a community based on directory structure and symbols."""
        if not nodes:
            return "Empty Community"

        # Tally file directory paths
        dir_counts: Dict[str, int] = collections.defaultdict(int)
        kind_counts: Dict[str, int] = collections.defaultdict(int)
        prefix = self._repo_path_prefix()

        for n in nodes:
            data = self.nodes.get(n, {})
            path = data.get("path", "")
            if prefix and path.startswith(prefix):
                path = path[len(prefix):]
            if path:
                parts = [p for p in path.replace("\\", "/").split("/") if p]
                if len(parts) >= 2:
                    dir_counts["/".join(parts[:-1])] += 1
                elif parts:
                    dir_counts[parts[0]] += 1

            kind = data.get("kind", "")
            if kind:
                kind_counts[kind] += 1

        if dir_counts:
            top_dir = max(dir_counts.items(), key=lambda x: x[1])[0]
            top_kind = (
                max(kind_counts.items(), key=lambda x: x[1])[0]
                if kind_counts
                else "module"
            )
            return f"{top_dir} ({top_kind.capitalize()}s)"

        # Fallback to symbol naming prefix
        return f"Cluster ({len(nodes)} nodes)"

    def calculate_cohesion_stats(
        self, community_nodes: Set[str]
    ) -> Tuple[float, int, int]:
        internal = 0
        external = 0
        for src in community_nodes:
            for dst, _ in self._adj_out.get(src, []):
                if dst in community_nodes:
                    internal += 1
                else:
                    external += 1

        total = internal + external
        cohesion = (internal / total) if total > 0 else 1.0
        return round(cohesion, 3), internal, external

    def calculate_modularity(self, node_to_comm: Dict[str, int]) -> float:
        """Calculate standard Newman-Girvan modularity Q = sum_c [ e_c/m - (Sigma_tot(c)/(2m))^2 ]."""
        m = len(self.edges)
        if m == 0:
            return 0.0

        # Build community membership groupings and count internal edges
        # Total degree (sum of degrees of nodes in community c in undirected multigraph)
        degrees: Dict[str, float] = collections.defaultdict(float)
        for e in self.edges:
            degrees[e["src"]] += 1.0
            degrees[e["dst"]] += 1.0
        comm_internal_edges: Dict[int, float] = {}
        comm_total_degrees: Dict[int, float] = {}

        for node, c in node_to_comm.items():
            comm_total_degrees[c] = comm_total_degrees.get(c, 0.0) + degrees.get(node, 0.0)
        for e in self.edges:
            src, dst = e["src"], e["dst"]
            c_src = node_to_comm.get(src, -1)
            c_dst = node_to_comm.get(dst, -2)
            if c_src >= 0 and c_src == c_dst:
                comm_internal_edges[c_src] = comm_internal_edges.get(c_src, 0.0) + 1.0

        two_m = 2.0 * m
        q = 0.0
        for c, deg_sum in comm_total_degrees.items():
            e_c = comm_internal_edges.get(c, 0.0)
            q += (e_c / m) - ((deg_sum / two_m) ** 2)

        return round(q, 4)
