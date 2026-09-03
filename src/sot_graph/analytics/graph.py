from __future__ import annotations

import collections
import dataclasses
import math
import sqlite3
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from sot_graph.db import Database
else:
    Database = Any


class OperationCancelledError(Exception):
    """Standardized error raised when an analytics operation is cancelled by the client."""

    def __init__(self, message: str = "Analytics operation cancelled by client") -> None:
        super().__init__(message)
        self.message = message
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
        self._precomputed_degrees: Optional[Dict[str, Dict[str, int]]] = None
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
        if self._precomputed_degrees is not None and node_id not in self._precomputed_degrees:
            in_cnt = len(self._adj_in.get(node_id, []))
            out_cnt = len(self._adj_out.get(node_id, []))
            self._precomputed_degrees[node_id] = {"in": in_cnt, "out": out_cnt, "total": in_cnt + out_cnt}

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
        if self._precomputed_degrees is not None:
            if src not in self._precomputed_degrees:
                in_cnt = len(self._adj_in.get(src, []))
                out_cnt = len(self._adj_out.get(src, []))
                self._precomputed_degrees[src] = {"in": in_cnt, "out": out_cnt, "total": in_cnt + out_cnt}
            if dst not in self._precomputed_degrees:
                in_cnt = len(self._adj_in.get(dst, []))
                out_cnt = len(self._adj_out.get(dst, []))
                self._precomputed_degrees[dst] = {"in": in_cnt, "out": out_cnt, "total": in_cnt + out_cnt}
            self._precomputed_degrees[src]["out"] += 1
            self._precomputed_degrees[src]["total"] += 1
            self._precomputed_degrees[dst]["in"] += 1
            self._precomputed_degrees[dst]["total"] += 1
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

        try:
            graph._precomputed_degrees = cls.compute_degrees_sql(conn, scope=scope)
        except Exception:
            graph._precomputed_degrees = None

        return graph

    @classmethod
    def from_database(
        cls, db: Database, scope: Optional[str] = None
    ) -> "AnalyticsGraph":
        """Build an AnalyticsGraph from a Database instance."""
        return cls.from_connection(db.conn, scope=scope)

    @staticmethod
    def compute_degrees_sql(
        conn: Any, scope: Optional[str] = None
    ) -> Dict[str, Dict[str, int]]:
        """Compute in-degree, out-degree, and total degree per node directly in SQLite
        without loading all edges into Python memory.
        """
        raw_conn = getattr(conn, "conn", conn)
        degrees: Dict[str, Dict[str, int]] = collections.defaultdict(
            lambda: {"in": 0, "out": 0, "total": 0}
        )
        if scope:
            like_pattern = f"{scope}%"
            sql = """
                SELECT n.id,
                       (COALESCE(o.cnt, 0) + COALESCE(i.cnt, 0)) AS deg,
                       COALESCE(i.cnt, 0) AS in_deg,
                       COALESCE(o.cnt, 0) AS out_deg
                FROM graph_nodes n
                LEFT JOIN (SELECT src, COUNT(*) AS cnt FROM graph_edges WHERE path LIKE ? GROUP BY src) o ON n.id = o.src
                LEFT JOIN (SELECT dst, COUNT(*) AS cnt FROM graph_edges WHERE path LIKE ? GROUP BY dst) i ON n.id = i.dst
                WHERE n.path LIKE ?
            """
            rows = raw_conn.execute(sql, (like_pattern, like_pattern, like_pattern)).fetchall()
        else:
            sql = """
                SELECT n.id,
                       (COALESCE(o.cnt, 0) + COALESCE(i.cnt, 0)) AS deg,
                       COALESCE(i.cnt, 0) AS in_deg,
                       COALESCE(o.cnt, 0) AS out_deg
                FROM graph_nodes n
                LEFT JOIN (SELECT src, COUNT(*) AS cnt FROM graph_edges GROUP BY src) o ON n.id = o.src
                LEFT JOIN (SELECT dst, COUNT(*) AS cnt FROM graph_edges GROUP BY dst) i ON n.id = i.dst
            """
            rows = raw_conn.execute(sql).fetchall()

        for r in rows:
            degrees[r[0]] = {
                "in": int(r[2]),
                "out": int(r[3]),
                "total": int(r[1]),
            }
        return dict(degrees)
    @staticmethod
    def compute_top_nodes_by_degree_sql(
        conn: Any, limit: int = 50, scope: Optional[str] = None
    ) -> List[Tuple[str, int, int, int]]:
        """Compute top nodes by total degree directly in SQLite with grouping and aggregation."""
        raw_conn = getattr(conn, "conn", conn)
        if scope:
            like_pattern = f"{scope}%"
            sql = """
                WITH out_deg AS (
                    SELECT src AS node_id, COUNT(*) AS out_c FROM graph_edges WHERE path LIKE ? GROUP BY src
                ),
                in_deg AS (
                    SELECT dst AS node_id, COUNT(*) AS in_c FROM graph_edges WHERE path LIKE ? GROUP BY dst
                ),
                combined AS (
                    SELECT node_id FROM out_deg UNION SELECT node_id FROM in_deg
                )
                SELECT c.node_id,
                       COALESCE(i.in_c, 0) AS in_degree,
                       COALESCE(o.out_c, 0) AS out_degree,
                       (COALESCE(i.in_c, 0) + COALESCE(o.out_c, 0)) AS total_degree
                FROM combined c
                LEFT JOIN in_deg i ON c.node_id = i.node_id
                LEFT JOIN out_deg o ON c.node_id = o.node_id
                ORDER BY total_degree DESC
                LIMIT ?
            """
            rows = raw_conn.execute(sql, (like_pattern, like_pattern, limit)).fetchall()
        else:
            sql = """
                WITH out_deg AS (
                    SELECT src AS node_id, COUNT(*) AS out_c FROM graph_edges GROUP BY src
                ),
                in_deg AS (
                    SELECT dst AS node_id, COUNT(*) AS in_c FROM graph_edges GROUP BY dst
                ),
                combined AS (
                    SELECT node_id FROM out_deg UNION SELECT node_id FROM in_deg
                )
                SELECT c.node_id,
                       COALESCE(i.in_c, 0) AS in_degree,
                       COALESCE(o.out_c, 0) AS out_degree,
                       (COALESCE(i.in_c, 0) + COALESCE(o.out_c, 0)) AS total_degree
                FROM combined c
                LEFT JOIN in_deg i ON c.node_id = i.node_id
                LEFT JOIN out_deg o ON c.node_id = o.node_id
                ORDER BY total_degree DESC
                LIMIT ?
            """
            rows = raw_conn.execute(sql, (limit,)).fetchall()
        return [(r[0], int(r[1]), int(r[2]), int(r[3])) for r in rows]

    @staticmethod
    def compute_graph_metrics_sql(
        conn: sqlite3.Connection, scope: Optional[str] = None
    ) -> Dict[str, Any]:
        """Compute basic graph topology metrics directly via SQL streaming aggregations."""
        if scope:
            like_pattern = f"{scope}%"
            n_row = conn.execute(
                "SELECT COUNT(*), SUM(CASE WHEN kind = 'file' THEN 1 ELSE 0 END) "
                "FROM graph_nodes WHERE path LIKE ?",
                (like_pattern,),
            ).fetchone()
            e_row = conn.execute(
                "SELECT COUNT(*) FROM graph_edges WHERE path LIKE ?",
                (like_pattern,),
            ).fetchone()
        else:
            n_row = conn.execute(
                "SELECT COUNT(*), SUM(CASE WHEN kind = 'file' THEN 1 ELSE 0 END) FROM graph_nodes"
            ).fetchone()
            e_row = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()

        node_count = int(n_row[0] or 0)
        file_count = int(n_row[1] or 0)
        symbol_count = max(0, node_count - file_count)
        edge_count = int(e_row[0] or 0)
        max_possible = node_count * (node_count - 1) if node_count > 1 else 1
        density = (edge_count / max_possible) if node_count > 1 else 0.0
        avg_degree = (2.0 * edge_count / node_count) if node_count > 0 else 0.0

        return {
            "node_count": node_count,
            "edge_count": edge_count,
            "file_count": file_count,
            "symbol_count": symbol_count,
            "density": round(density, 6),
            "avg_degree": round(avg_degree, 2),
        }

    def in_degree(self, node_id: str) -> int:
        if self._precomputed_degrees is not None and node_id in self._precomputed_degrees:
            return self._precomputed_degrees[node_id]["in"]
        return len(self._adj_in.get(node_id, []))

    def out_degree(self, node_id: str) -> int:
        if self._precomputed_degrees is not None and node_id in self._precomputed_degrees:
            return self._precomputed_degrees[node_id]["out"]
        return len(self._adj_out.get(node_id, []))

    def degree(self, node_id: str) -> int:
        if self._precomputed_degrees is not None and node_id in self._precomputed_degrees:
            return self._precomputed_degrees[node_id]["total"]
        return self.in_degree(node_id) + self.out_degree(node_id)
    def neighbors(self, node_id: str) -> Set[str]:
        return self._undirected_adj.get(node_id, set())

    def connected_components(
        self, cancel_check: Optional[Callable[[], bool]] = None
    ) -> List[Set[str]]:
        """Find all connected components using BFS with cancellation check."""
        visited: Set[str] = set()
        components: List[Set[str]] = []

        for node_id in self.nodes:
            if cancel_check and cancel_check():
                raise OperationCancelledError("Analytics operation cancelled by client")
            if node_id in visited:
                continue
            component: Set[str] = set()
            queue = collections.deque([node_id])
            visited.add(node_id)

            while queue:
                if cancel_check and cancel_check():
                    raise OperationCancelledError("Analytics operation cancelled by client")
                current = queue.popleft()
                component.add(current)
                for neighbor in self._undirected_adj.get(current, set()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            components.append(component)

        components.sort(key=len, reverse=True)
        return components

    def calculate_blast_radius(
        self,
        start_node: str,
        max_hops: int = 2,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> int:
        """Calculate the number of unique nodes affected within max_hops."""
        visited: Set[str] = {start_node}
        queue: collections.deque[Tuple[str, int]] = collections.deque([(start_node, 0)])

        while queue:
            if cancel_check and cancel_check():
                raise OperationCancelledError("Analytics operation cancelled by client")
            curr, depth = queue.popleft()
            if depth >= max_hops:
                continue
            for neighbor in self.neighbors(curr):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))

        return len(visited) - 1

    def pagerank(
        self,
        personalization: Optional[Dict[str, float]] = None,
        damping: float = 0.85,
        iterations: int = 30,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, float]:
        """Power iteration PageRank with cooperative cancellation."""
        nodes = list(self.nodes.keys())
        n = len(nodes)
        if n == 0:
            return {}

        base = personalization or {u: 1.0 / n for u in nodes}
        total = sum(base.values()) or 1.0
        base = {u: base.get(u, 0.0) / total for u in nodes}
        rank = dict(base)
        out_count = {u: len(self._adj_out.get(u, [])) for u in nodes}

        for _ in range(iterations):
            if cancel_check and cancel_check():
                raise OperationCancelledError("Analytics operation cancelled by client")
            nxt = {u: (1.0 - damping) * base.get(u, 0.0) for u in nodes}
            dangling = damping * sum(rank[u] for u in nodes if out_count[u] == 0) / n
            for u in nodes:
                nxt[u] += dangling
            for u in nodes:
                if out_count[u]:
                    share = damping * rank[u] / out_count[u]
                    for dst, _ in self._adj_out[u]:
                        nxt[dst] = nxt.get(dst, 0.0) + share
            rank = nxt
        return rank

    def detect_cycles(
        self,
        max_cycles: int = 100,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[List[str]]:
        """Detect simple directed cycles with cooperative cancellation.

        Iterative three-colour DFS: deep import chains must not hit the
        interpreter recursion limit (a minified dependency graph nests far
        beyond it) — one long chain used to raise RecursionError and lose
        the whole analysis.
        """
        # WHITE = unvisited (absent), GRAY = on the current path, BLACK = done.
        colour: Dict[str, int] = {}
        GRAY, BLACK = 1, 2
        path: List[str] = []
        path_set: Set[str] = set()
        cycles: List[List[str]] = []

        for root in self.nodes:
            if len(cycles) >= max_cycles:
                break
            if colour.get(root) is not None:
                continue
            stack: List[Tuple[str, Iterator[Tuple[str, Any]]]] = [
                (root, iter(self._adj_out.get(root, [])))
            ]
            colour[root] = GRAY
            path.append(root)
            path_set.add(root)
            while stack:
                if cancel_check and cancel_check():
                    raise OperationCancelledError(
                        "Analytics operation cancelled by client"
                    )
                node, neighbours = stack[-1]
                advanced = False
                for dst, _ in neighbours:
                    if len(cycles) >= max_cycles:
                        break
                    state = colour.get(dst)
                    if state is None:
                        colour[dst] = GRAY
                        path.append(dst)
                        path_set.add(dst)
                        stack.append((dst, iter(self._adj_out.get(dst, []))))
                        advanced = True
                        break
                    if state == GRAY:
                        # Back edge: the cycle runs from dst's position on
                        # the current path back around to dst.
                        idx = path.index(dst)
                        cycles.append(list(path[idx:]) + [dst])
                    # BLACK neighbours are fully explored — no new cycle.
                if not advanced:
                    stack.pop()
                    path.pop()
                    path_set.remove(node)
                    colour[node] = BLACK

        return cycles

    def detect_communities(
        self,
        seed: int = 42,
        max_iterations: int = 30,
        min_community_size: int = 1,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> CommunityResult:
        """
        Detect architectural communities using an asynchronous Label Propagation Algorithm (LPA)
        with modularity refinement in pure Python standard library.
        If networkx is available, leverages Louvain / greedy modularity when beneficial.
        """
        if cancel_check and cancel_check():
            raise OperationCancelledError("Analytics operation cancelled by client")

        if not self.nodes:
            return CommunityResult(
                communities={},
                community_info={},
                node_to_community={},
                modularity=0.0,
            )

        # Try networkx Louvain detection if installed and cancel_check is None
        if cancel_check is None:
            nx_communities = self._try_networkx_community(cancel_check=cancel_check)
        else:
            nx_communities = None

        if nx_communities is not None:
            raw_communities = nx_communities
        else:
            raw_communities = self._louvain_community(
                seed=seed, max_iterations=max_iterations, cancel_check=cancel_check
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
    def cluster_louvain(
        self,
        seed: int = 42,
        max_iterations: int = 30,
        min_community_size: int = 1,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> CommunityResult:
        """Detect architectural communities using Louvain modularity optimization with cooperative cancellation."""
        return self.detect_communities(
            seed=seed,
            max_iterations=max_iterations,
            min_community_size=min_community_size,
            cancel_check=cancel_check,
        )

    def _louvain_community(
        self,
        seed: int = 42,
        max_iterations: int = 30,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[Set[str]]:
        """Cancellable Louvain modularity optimization algorithm (pure Python stdlib)."""
        import random

        if cancel_check and cancel_check():
            raise OperationCancelledError("Analytics operation cancelled by client")

        nodes = list(self.nodes.keys())
        n = len(nodes)
        if n == 0:
            return []

        # Build undirected edge weights
        neighbor_weights: Dict[str, Dict[str, float]] = collections.defaultdict(
            lambda: collections.defaultdict(float)
        )
        for e in self.edges:
            u, v = e["src"], e["dst"]
            if u != v:
                neighbor_weights[u][v] += 1.0
                neighbor_weights[v][u] += 1.0
            else:
                neighbor_weights[u][u] += 2.0

        degrees: Dict[str, float] = {}
        for u in nodes:
            degrees[u] = sum(neighbor_weights[u].values())

        total_weight = sum(degrees.values())
        if total_weight == 0:
            return [{node} for node in nodes]

        two_m = total_weight
        rng = random.Random(seed)

        # Initialize each node in its own community
        community: Dict[str, int] = {node: idx for idx, node in enumerate(nodes)}
        community_nodes: Dict[int, Set[str]] = {
            idx: {node} for idx, node in enumerate(nodes)
        }
        tot_degree: Dict[int, float] = {
            idx: degrees[node] for idx, node in enumerate(nodes)
        }

        nodes_list = list(nodes)
        for iter_idx in range(max_iterations):
            if cancel_check and cancel_check():
                raise OperationCancelledError("Analytics operation cancelled by client")

            rng.shuffle(nodes_list)
            improved = False

            for node in nodes_list:
                if cancel_check and cancel_check():
                    raise OperationCancelledError("Analytics operation cancelled by client")

                k_i = degrees[node]
                if k_i == 0:
                    continue

                curr_comm = community[node]

                # Weight of links from node to its current community (excluding self loops)
                k_i_in_curr = sum(
                    wt
                    for nbr, wt in neighbor_weights[node].items()
                    if community[nbr] == curr_comm and nbr != node
                )

                # Temporarily remove node from its current community
                tot_degree[curr_comm] -= k_i
                community_nodes[curr_comm].remove(node)

                # Find candidate neighbor communities
                candidate_comms: Set[int] = {
                    community[nbr] for nbr in neighbor_weights[node]
                }
                candidate_comms.add(curr_comm)

                best_comm = curr_comm
                best_gain = 0.0
                # Baseline gain if staying in current community (relative to being isolated)
                base_gain = k_i_in_curr - (tot_degree[curr_comm] * k_i / two_m)

                for cand in candidate_comms:
                    if cand == curr_comm:
                        gain = base_gain
                    else:
                        k_i_in_cand = sum(
                            wt
                            for nbr, wt in neighbor_weights[node].items()
                            if community[nbr] == cand
                        )
                        gain = k_i_in_cand - (tot_degree[cand] * k_i / two_m)

                    if gain > best_gain:
                        best_gain = gain
                        best_comm = cand

                # Place node into best community
                community[node] = best_comm
                tot_degree[best_comm] += k_i
                community_nodes[best_comm].add(node)

                if best_comm != curr_comm:
                    improved = True

            if not improved:
                break

        res: List[Set[str]] = [
            st for st in community_nodes.values() if len(st) > 0
        ]
        return res
    def _try_networkx_community(
        self, cancel_check: Optional[Callable[[], bool]] = None
    ) -> Optional[List[Set[str]]]:
        try:
            if cancel_check and cancel_check():
                raise OperationCancelledError("Analytics operation cancelled by client")
            import networkx as nx  # type: ignore[import-not-found]

            G = nx.Graph()
            for node_id in self.nodes:
                G.add_node(node_id)
            for e in self.edges:
                G.add_edge(e["src"], e["dst"])

            if G.number_of_nodes() == 0:
                return []

            if cancel_check and cancel_check():
                raise OperationCancelledError("Analytics operation cancelled by client")

            # Use louvain_communities if available (nx 2.8+)
            if hasattr(nx.community, "louvain_communities"):
                comms = nx.community.louvain_communities(G, seed=42)
                if cancel_check and cancel_check():
                    raise OperationCancelledError("Analytics operation cancelled by client")
                return [set(c) for c in comms]
            elif hasattr(nx.community, "greedy_modularity_communities"):
                comms = nx.community.greedy_modularity_communities(G)
                if cancel_check and cancel_check():
                    raise OperationCancelledError("Analytics operation cancelled by client")
                return [set(c) for c in comms]
        except OperationCancelledError:
            raise
        except Exception:
            pass
        return None

    def _label_propagation_community(
        self,
        seed: int = 42,
        max_iterations: int = 30,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[Set[str]]:
        """Asynchronous Label Propagation Algorithm (pure Python stdlib)."""
        import random

        rng = random.Random(seed)
        # Initialize each node with unique label
        labels: Dict[str, str] = {n: n for n in self.nodes}
        nodes_list = list(self.nodes.keys())

        for _ in range(max_iterations):
            if cancel_check and cancel_check():
                raise OperationCancelledError("Analytics operation cancelled by client")
            rng.shuffle(nodes_list)
            changed = False
            for node in nodes_list:
                if cancel_check and cancel_check():
                    raise OperationCancelledError("Analytics operation cancelled by client")
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
