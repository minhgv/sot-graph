"""
sot_graph.db — SQLite schema and storage for the Source-of-Truth Knowledge Graph.
Manages file journaling, graph nodes, graph edges, pending cross-file edges, and FTS5 search.
"""

import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple


SCHEMA = """
-- 1. Journal tracking filesystem state
CREATE TABLE IF NOT EXISTS file_journal (
    path          TEXT PRIMARY KEY,
    sha256        TEXT NOT NULL,
    size          INTEGER NOT NULL,
    mtime_ms      INTEGER NOT NULL,
    generation    INTEGER DEFAULT 1,
    reconciled_at INTEGER NOT NULL
);

-- 2. Graph Nodes: Files, Functions, Classes, Types, Notes
CREATE TABLE IF NOT EXISTS graph_nodes (
    id            TEXT PRIMARY KEY,
    path          TEXT NOT NULL,
    kind          TEXT NOT NULL,       -- 'file', 'function', 'class', 'method', 'note'
    symbol        TEXT,              -- Raw symbol name for edge resolution
    label         TEXT NOT NULL,       -- Display title / symbol label
    body          TEXT NOT NULL,       -- Descriptive text / docstring / preview
    keywords      TEXT,              -- Space-separated keywords
    line_start    INTEGER,
    updated_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_path ON graph_nodes(path);
CREATE INDEX IF NOT EXISTS idx_nodes_symbol ON graph_nodes(symbol);

-- 3. Confirmed Graph Edges: Directed relations between concrete nodes
CREATE TABLE IF NOT EXISTS graph_edges (
    path          TEXT NOT NULL,
    src           TEXT NOT NULL,       -- Source node id
    dst           TEXT NOT NULL,       -- Destination node id
    relation      TEXT NOT NULL,       -- 'calls', 'uses', 'defines', 'extends', 'imports'
    line          INTEGER,
    PRIMARY KEY (path, src, dst, relation)
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON graph_edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON graph_edges(dst);

-- 4. Pending Cross-File Edges: Awaiting resolution when target symbol is indexed
CREATE TABLE IF NOT EXISTS pending_edges (
    path          TEXT NOT NULL,       -- Source file path owning the pending edge
    src           TEXT NOT NULL,       -- Source node id
    dst_symbol    TEXT NOT NULL,       -- Target symbol name being looked for
    relation      TEXT NOT NULL,
    line          INTEGER,
    PRIMARY KEY (path, src, dst_symbol, relation)
);
CREATE INDEX IF NOT EXISTS idx_pending_dst ON pending_edges(dst_symbol);

-- 5. FTS5 Full-Text Search Virtual Table
CREATE VIRTUAL TABLE IF NOT EXISTS graph_fts USING fts5(
    label,
    body,
    keywords,
    content='graph_nodes',
    content_rowid='rowid'
);

-- FTS5 Sync Triggers
CREATE TRIGGER IF NOT EXISTS trg_nodes_ai AFTER INSERT ON graph_nodes BEGIN
    INSERT INTO graph_fts(rowid, label, body, keywords)
    VALUES (new.rowid, new.label, new.body, new.keywords);
END;

CREATE TRIGGER IF NOT EXISTS trg_nodes_ad AFTER DELETE ON graph_nodes BEGIN
    INSERT INTO graph_fts(graph_fts, rowid, label, body, keywords)
    VALUES ('delete', old.rowid, old.label, old.body, old.keywords);
END;

CREATE TRIGGER IF NOT EXISTS trg_nodes_au AFTER UPDATE ON graph_nodes BEGIN
    INSERT INTO graph_fts(graph_fts, rowid, label, body, keywords)
    VALUES ('delete', old.rowid, old.label, old.body, old.keywords);
    INSERT INTO graph_fts(rowid, label, body, keywords)
    VALUES (new.rowid, new.label, new.body, new.keywords);
END;
"""


class Database:
    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA synchronous = NORMAL;")
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def get_file_journal(self, path: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT sha256, size, mtime_ms, generation, reconciled_at FROM file_journal WHERE path = ?",
            (path,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "sha256": row[0],
            "size": row[1],
            "mtime_ms": row[2],
            "generation": row[3],
            "reconciled_at": row[4],
        }

    def all_journal_paths(self) -> List[str]:
        cur = self.conn.execute("SELECT path FROM file_journal ORDER BY path")
        return [r[0] for r in cur.fetchall()]

    def delete_path(self, path: str) -> None:
        """Atomic deletion of all records associated with a file path."""
        with self.conn:
            self.conn.execute("DELETE FROM graph_nodes WHERE path = ?", (path,))
            self.conn.execute("DELETE FROM graph_edges WHERE path = ?", (path,))
            self.conn.execute("DELETE FROM pending_edges WHERE path = ?", (path,))
            self.conn.execute("DELETE FROM file_journal WHERE path = ?", (path,))

    def delete_node_by_id(self, node_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM graph_nodes WHERE id = ?", (node_id,))
            self.conn.execute("DELETE FROM graph_edges WHERE src = ? OR dst = ?", (node_id, node_id))
            self.conn.execute("DELETE FROM pending_edges WHERE src = ?", (node_id,))

    def update_node_path(self, node_id: str, old_path: str, new_path: str) -> None:
        """Re-anchor a node to a new path after a file move/rename."""
        with self.conn:
            self.conn.execute("""
                UPDATE graph_nodes
                SET path = ?,
                    label = REPLACE(label, ?, ?),
                    body = REPLACE(body, ?, ?)
                WHERE id = ?
            """, (new_path, old_path, new_path, old_path, new_path, node_id))
            self.conn.execute("DELETE FROM file_journal WHERE path = ?", (old_path,))

    def commit_file(
        self,
        path: str,
        sha256: str,
        size: int,
        mtime_ms: int,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        pending: List[Dict[str, Any]],
    ) -> None:
        """Atomic transaction: replaces all nodes/edges/pending owned by path and updates journal."""
        now = int(time.time())
        with self.conn:
            self.conn.execute("DELETE FROM graph_nodes WHERE path = ?", (path,))
            self.conn.execute("DELETE FROM graph_edges WHERE path = ?", (path,))
            self.conn.execute("DELETE FROM pending_edges WHERE path = ?", (path,))

            for n in nodes:
                kw_str = " ".join(n.get("keywords", [])) if n.get("keywords") else ""
                self.conn.execute("""
                    INSERT INTO graph_nodes (id, path, kind, symbol, label, body, keywords, line_start, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    n["id"], path, n["kind"], n.get("symbol"), n["label"],
                    n["body"], kw_str, n.get("line_start"), now
                ))

            for e in edges:
                self.conn.execute("""
                    INSERT OR REPLACE INTO graph_edges (path, src, dst, relation, line)
                    VALUES (?, ?, ?, ?, ?)
                """, (path, e["src"], e["dst"], e["relation"], e.get("line")))

            for p in pending:
                self.conn.execute("""
                    INSERT OR REPLACE INTO pending_edges (path, src, dst_symbol, relation, line)
                    VALUES (?, ?, ?, ?, ?)
                """, (path, p["src"], p["dst_symbol"], p["relation"], p.get("line")))

            self.conn.execute("""
                INSERT INTO file_journal (path, sha256, size, mtime_ms, generation, reconciled_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(path) DO UPDATE SET
                    sha256 = excluded.sha256,
                    size = excluded.size,
                    mtime_ms = excluded.mtime_ms,
                    generation = generation + 1,
                    reconciled_at = excluded.reconciled_at
            """, (path, sha256, size, mtime_ms, now))

    def resolve_pending_edges(self, new_symbols: List[str], current_file_path: Optional[str] = None) -> int:
        """
        Two-way pending edge resolution:
        1. Promotes pending edges from OTHER files waiting for newly introduced symbols.
        2. Promotes pending edges from THIS file whose targets are already known.
        """
        resolved_count = 0
        with self.conn:
            # Direction 1: Other files waiting for symbols defined in this file
            if new_symbols:
                placeholders = ",".join("?" * len(new_symbols))
                cur = self.conn.execute(f"""
                    SELECT path, src, dst_symbol, relation, line
                    FROM pending_edges
                    WHERE dst_symbol IN ({placeholders})
                """, new_symbols)
                for p_path, src, dst_sym, rel, line in cur.fetchall():
                    target = self.conn.execute(
                        "SELECT id FROM graph_nodes WHERE symbol = ? LIMIT 1", (dst_sym,)
                    ).fetchone()
                    if target:
                        target_id = target[0]
                        self.conn.execute("""
                            INSERT OR REPLACE INTO graph_edges (path, src, dst, relation, line)
                            VALUES (?, ?, ?, ?, ?)
                        """, (p_path, src, target_id, rel, line))
                        self.conn.execute("""
                            DELETE FROM pending_edges
                            WHERE path = ? AND src = ? AND dst_symbol = ? AND relation = ?
                        """, (p_path, src, dst_sym, rel))
                        resolved_count += 1

            # Direction 2: Pending edges created by current_file_path that might match existing symbols
            if current_file_path:
                cur = self.conn.execute("""
                    SELECT path, src, dst_symbol, relation, line
                    FROM pending_edges
                    WHERE path = ?
                """, (current_file_path,))
                for p_path, src, dst_sym, rel, line in cur.fetchall():
                    target = self.conn.execute(
                        "SELECT id FROM graph_nodes WHERE symbol = ? LIMIT 1", (dst_sym,)
                    ).fetchone()
                    if target:
                        target_id = target[0]
                        self.conn.execute("""
                            INSERT OR REPLACE INTO graph_edges (path, src, dst, relation, line)
                            VALUES (?, ?, ?, ?, ?)
                        """, (p_path, src, target_id, rel, line))
                        self.conn.execute("""
                            DELETE FROM pending_edges
                            WHERE path = ? AND src = ? AND dst_symbol = ? AND relation = ?
                        """, (p_path, src, dst_sym, rel))
                        resolved_count += 1

        return resolved_count

    def search_fts(self, query: str, limit: int = 10, scope: Optional[str] = None) -> List[Dict[str, Any]]:
        clean_q = "".join(c if c.isalnum() or c.isspace() else " " for c in query).strip()
        if not clean_q:
            return []

        tokens = [f'"{t}"*' for t in clean_q.split() if len(t) >= 2]
        if not tokens:
            tokens = [f'"{t}"' for t in clean_q.split()]
        fts_expr = " OR ".join(tokens)

        sql = """
            SELECT k.id, k.path, k.kind, k.symbol, k.label, k.body, k.keywords, k.line_start,
                   bm25(graph_fts) as rank_score
            FROM graph_fts f
            JOIN graph_nodes k ON f.rowid = k.rowid
            WHERE graph_fts MATCH ?
        """
        params: List[Any] = [fts_expr]
        if scope:
            sql += " AND (k.path LIKE ? OR k.body LIKE ?)"
            params.extend([f"%{scope}%", f"%{scope}%"])

        sql += " ORDER BY rank_score ASC LIMIT ?"
        params.append(limit * 3)

        cur = self.conn.execute(sql, params)
        results = []
        for r in cur.fetchall():
            results.append({
                "id": r[0],
                "path": r[1],
                "kind": r[2],
                "symbol": r[3],
                "label": r[4],
                "body": r[5],
                "keywords": r[6],
                "line_start": r[7],
                "score": abs(r[8]),
            })
        return results

    def explore_node(self, node_id: str, depth: int = 1) -> List[Dict[str, Any]]:
        visited: Set[str] = set()
        edges_out: List[Dict[str, Any]] = []
        queue: List[Tuple[str, int]] = [(node_id, 0)]

        while queue:
            curr_id, d = queue.pop(0)
            if curr_id in visited or d > depth:
                continue
            visited.add(curr_id)

            # Outward edges (curr -> target)
            cur = self.conn.execute("""
                SELECT e.relation, n.id, n.label, n.path, n.line_start, n.kind
                FROM graph_edges e
                JOIN graph_nodes n ON e.dst = n.id
                WHERE e.src = ?
            """, (curr_id,))
            for rel, target_id, label, path, line, kind in cur.fetchall():
                edges_out.append({
                    "direction": "outward",
                    "relation": rel,
                    "target_id": target_id,
                    "label": label,
                    "path": path,
                    "line": line,
                    "kind": kind,
                    "depth": d + 1,
                })
                if target_id not in visited and d + 1 <= depth:
                    queue.append((target_id, d + 1))

            # Inward edges (source -> curr)
            cur2 = self.conn.execute("""
                SELECT e.relation, n.id, n.label, n.path, n.line_start, n.kind
                FROM graph_edges e
                JOIN graph_nodes n ON e.src = n.id
                WHERE e.dst = ?
            """, (curr_id,))
            for rel, source_id, label, path, line, kind in cur2.fetchall():
                edges_out.append({
                    "direction": "inward",
                    "relation": f"used_by ({rel})",
                    "target_id": source_id,
                    "label": label,
                    "path": path,
                    "line": line,
                    "kind": kind,
                    "depth": d + 1,
                })
                if source_id not in visited and d + 1 <= depth:
                    queue.append((source_id, d + 1))

        return edges_out

    def stats(self) -> Dict[str, int]:
        def _count(query: str) -> int:
            return self.conn.execute(query).fetchone()[0]

        return {
            "paths": _count("SELECT COUNT(*) FROM file_journal"),
            "nodes": _count("SELECT COUNT(*) FROM graph_nodes"),
            "edges": _count("SELECT COUNT(*) FROM graph_edges"),
            "pending": _count("SELECT COUNT(*) FROM pending_edges"),
        }
