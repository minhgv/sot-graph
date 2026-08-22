"""
sot_graph.db — SQLite schema and storage for the Source-of-Truth Knowledge Graph.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import quote



SCHEMA = """
CREATE TABLE IF NOT EXISTS file_journal (
    path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
    mtime_ms INTEGER NOT NULL, generation INTEGER DEFAULT 1, reconciled_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS graph_nodes (
    id TEXT PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL, symbol TEXT,
    label TEXT NOT NULL, body TEXT NOT NULL, keywords TEXT, line_start INTEGER,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_path ON graph_nodes(path);
CREATE INDEX IF NOT EXISTS idx_nodes_symbol ON graph_nodes(symbol);
CREATE TABLE IF NOT EXISTS graph_edges (
    path TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL, relation TEXT NOT NULL,
    line INTEGER, PRIMARY KEY (path, src, dst, relation)
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON graph_edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON graph_edges(dst);
CREATE TABLE IF NOT EXISTS pending_edges (
    path TEXT NOT NULL, src TEXT NOT NULL, dst_symbol TEXT NOT NULL,
    relation TEXT NOT NULL, line INTEGER,
    PRIMARY KEY (path, src, dst_symbol, relation)
);
CREATE INDEX IF NOT EXISTS idx_pending_dst ON pending_edges(dst_symbol);
CREATE VIRTUAL TABLE IF NOT EXISTS graph_fts USING fts5(
    label, body, keywords, content='graph_nodes', content_rowid='rowid'
);
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


@dataclass(frozen=True)
class CleanPlan:
    mode: str
    paths: tuple[str, ...]
    counts: dict[str, int]
    errors: tuple[str, ...] = ()
    include_notes: bool = False


@dataclass(frozen=True)
class VacuumResult:
    before_bytes: int
    after_bytes: int
    before_wal_bytes: int
    after_wal_bytes: int
    page_size: int
    before_page_count: int
    after_page_count: int
    before_freelist_pages: int
    after_freelist_pages: int
    estimated_reclaimable_bytes: int
    reclaimed_bytes: int
    checkpoint_status: str
    elapsed_ms: int
    optimized: bool
    dry_run: bool


class Database:
    def __init__(
        self,
        db_path: str,
        *,
        read_only: bool = False,
        timeout_ms: int = 5_000,
        initialize: bool = True,
    ) -> None:
        if timeout_ms < 0:
            raise ValueError("timeout_ms must be non-negative")
        self.db_path = os.path.abspath(db_path)
        self.read_only = read_only
        self.timeout_ms = int(timeout_ms)
        if read_only:
            if not os.path.isfile(self.db_path):
                raise FileNotFoundError(f"read-only database does not exist: {self.db_path}")
            # quote() keeps URI query delimiters unambiguous while permitting slashes.
            uri = "file:" + quote(self.db_path, safe="/") + "?mode=ro"
            self.conn = sqlite3.connect(uri, uri=True, timeout=self.timeout_ms / 1000.0)
        else:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self.conn = sqlite3.connect(self.db_path, timeout=self.timeout_ms / 1000.0)

        self.conn.execute(f"PRAGMA busy_timeout = {self.timeout_ms}")
        self.conn.execute("PRAGMA foreign_keys = ON")
        if read_only:
            self.conn.execute("PRAGMA query_only = ON")
        else:
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = NORMAL")
            if initialize:
                self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def get_file_journal(self, path: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT sha256, size, mtime_ms, generation, reconciled_at "
            "FROM file_journal WHERE path = ?", (path,)
        ).fetchone()
        if row is None:
            return None
        return {"sha256": row[0], "size": row[1], "mtime_ms": row[2],
                "generation": row[3], "reconciled_at": row[4]}

    def all_journal_paths(self) -> List[str]:
        return [r[0] for r in self.conn.execute("SELECT path FROM file_journal ORDER BY path")]

    def delete_path(self, path: str) -> None:
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
        with self.conn:
            self.conn.execute(
                "UPDATE graph_nodes SET path = ?, label = REPLACE(label, ?, ?), "
                "body = REPLACE(body, ?, ?) WHERE id = ?",
                (new_path, old_path, new_path, old_path, new_path, node_id),
            )
            self.conn.execute("DELETE FROM file_journal WHERE path = ?", (old_path,))

    @staticmethod
    def _record_value(record: Any, name: str) -> Any:
        if isinstance(record, Mapping):
            return record[name]
        return getattr(record, name)

    def commit_file_batch(self, records: Sequence[Any]) -> int:
        """Atomically replace a deterministically sorted batch of parsed files."""
        ordered = sorted(records, key=lambda r: os.path.normcase(os.path.normpath(
            str(self._record_value(r, "path"))))
        )
        if not ordered:
            return 0
        now = int(time.time())
        with self.conn:
            for record in ordered:
                path = str(self._record_value(record, "path"))
                nodes = self._record_value(record, "nodes")
                edges = self._record_value(record, "edges")
                pending = self._record_value(record, "pending")
                self.conn.execute("DELETE FROM graph_nodes WHERE path = ?", (path,))
                self.conn.execute("DELETE FROM graph_edges WHERE path = ?", (path,))
                self.conn.execute("DELETE FROM pending_edges WHERE path = ?", (path,))
                node_rows = []
                for n in nodes:
                    kw = n.get("keywords", [])
                    node_rows.append((n["id"], path, n["kind"], n.get("symbol"), n["label"],
                                      n["body"], " ".join(kw) if kw else "", n.get("line_start"), now))
                self.conn.executemany(
                    "INSERT INTO graph_nodes "
                    "(id,path,kind,symbol,label,body,keywords,line_start,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", node_rows)
                self.conn.executemany(
                    "INSERT OR REPLACE INTO graph_edges (path,src,dst,relation,line) VALUES (?,?,?,?,?)",
                    [(path, e["src"], e["dst"], e["relation"], e.get("line")) for e in edges],
                )
                self.conn.executemany(
                    "INSERT OR REPLACE INTO pending_edges "
                    "(path,src,dst_symbol,relation,line) VALUES (?,?,?,?,?)",
                    [(path, p["src"], p["dst_symbol"], p["relation"], p.get("line")) for p in pending],
                )
                sha = self._record_value(record, "sha256")
                size = self._record_value(record, "size")
                mtime_ms = self._record_value(record, "mtime_ms")
                self.conn.execute(
                    "INSERT INTO file_journal "
                    "(path,sha256,size,mtime_ms,generation,reconciled_at) VALUES (?,?,?,?,1,?) "
                    "ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256,size=excluded.size, "
                    "mtime_ms=excluded.mtime_ms,generation=generation+1,reconciled_at=excluded.reconciled_at",
                    (path, sha, size, mtime_ms, now),
                )
        return len(ordered)

    def commit_file(self, path: str, sha256: str, size: int, mtime_ms: int,
                    nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
                    pending: List[Dict[str, Any]]) -> None:
        self.commit_file_batch([{"path": path, "sha256": sha256, "size": size,
                                 "mtime_ms": mtime_ms, "nodes": nodes,
                                 "edges": edges, "pending": pending}])

    def resolve_all_pending_edges(self) -> int:
        """Promote all pending edges whose destination symbol is now indexed."""
        with self.conn:
            count = self.conn.execute(
                "SELECT COUNT(*) FROM pending_edges p WHERE EXISTS "
                "(SELECT 1 FROM graph_nodes n WHERE n.symbol = p.dst_symbol)"
            ).fetchone()[0]
            self.conn.execute(
                "INSERT OR REPLACE INTO graph_edges(path,src,dst,relation,line) "
                "SELECT p.path,p.src,(SELECT n.id FROM graph_nodes n "
                "WHERE n.symbol=p.dst_symbol ORDER BY n.id LIMIT 1),p.relation,p.line "
                "FROM pending_edges p WHERE EXISTS "
                "(SELECT 1 FROM graph_nodes n WHERE n.symbol=p.dst_symbol)"
            )
            self.conn.execute(
                "DELETE FROM pending_edges WHERE EXISTS "
                "(SELECT 1 FROM graph_nodes n WHERE n.symbol=pending_edges.dst_symbol)"
            )
        return int(count)

    def resolve_pending_edges(self, new_symbols: List[str], current_file_path: Optional[str] = None) -> int:
        # Keep the old API's filtering semantics while using the all-pending set operation.
        if not new_symbols and not current_file_path:
            return 0
        if new_symbols:
            placeholders = ",".join("?" for _ in new_symbols)
            with self.conn:
                count = self.conn.execute(
                    f"SELECT COUNT(*) FROM pending_edges p WHERE p.dst_symbol IN ({placeholders}) "
                    "AND EXISTS (SELECT 1 FROM graph_nodes n WHERE n.symbol=p.dst_symbol)", new_symbols
                ).fetchone()[0]
                self.conn.execute(
                    f"INSERT OR REPLACE INTO graph_edges(path,src,dst,relation,line) "
                    f"SELECT p.path,p.src,(SELECT n.id FROM graph_nodes n WHERE n.symbol=p.dst_symbol "
                    f"ORDER BY n.id LIMIT 1),p.relation,p.line FROM pending_edges p "
                    f"WHERE p.dst_symbol IN ({placeholders}) AND EXISTS "
                    f"(SELECT 1 FROM graph_nodes n WHERE n.symbol=p.dst_symbol)", new_symbols
                )
                self.conn.execute(
                    f"DELETE FROM pending_edges WHERE dst_symbol IN ({placeholders}) AND EXISTS "
                    f"(SELECT 1 FROM graph_nodes n WHERE n.symbol=pending_edges.dst_symbol)", new_symbols
                )
            resolved = int(count)
        else:
            resolved = 0
        if current_file_path:
            with self.conn:
                count = self.conn.execute(
                    "SELECT COUNT(*) FROM pending_edges p WHERE p.path=? AND EXISTS "
                    "(SELECT 1 FROM graph_nodes n WHERE n.symbol=p.dst_symbol)", (current_file_path,)
                ).fetchone()[0]
                self.conn.execute(
                    "INSERT OR REPLACE INTO graph_edges(path,src,dst,relation,line) "
                    "SELECT p.path,p.src,(SELECT n.id FROM graph_nodes n WHERE n.symbol=p.dst_symbol "
                    "ORDER BY n.id LIMIT 1),p.relation,p.line FROM pending_edges p WHERE p.path=? AND EXISTS "
                    "(SELECT 1 FROM graph_nodes n WHERE n.symbol=p.dst_symbol)", (current_file_path,)
                )
                self.conn.execute(
                    "DELETE FROM pending_edges WHERE path=? AND EXISTS "
                    "(SELECT 1 FROM graph_nodes n WHERE n.symbol=pending_edges.dst_symbol)", (current_file_path,)
                )
            resolved += int(count)
        return resolved

    def _path_inside(self, path: str, root_dir: str) -> bool:
        try:
            return os.path.commonpath([os.path.realpath(path), os.path.realpath(root_dir)]) == os.path.realpath(root_dir)
        except ValueError:
            return False

    def plan_clean(self, root_dir: str, *, reset: bool = False,
                   include_notes: bool = False) -> CleanPlan:
        if include_notes and not reset:
            raise ValueError("--include-notes requires reset mode (--all)")
        root = os.path.realpath(root_dir)
        errors: List[str] = []
        stale: List[str] = []
        if not reset:
            for path in self.all_journal_paths():
                if not self._path_inside(path, root):
                    errors.append(f"tracked path outside root: {path}")
                    continue
                try:
                    if not stat.S_ISREG(os.stat(path).st_mode):
                        stale.append(path)
                except FileNotFoundError:
                    stale.append(path)
                except OSError as exc:
                    errors.append(f"cannot inspect {path}: {exc.strerror or exc}")
        if reset:
            notes = int(self.conn.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE kind='note' OR id LIKE 'note:%'"
            ).fetchone()[0]) if include_notes else 0
            counts = {
                "paths": int(self.conn.execute("SELECT COUNT(*) FROM file_journal").fetchone()[0]),
                "nodes": int(self.conn.execute(
                    "SELECT COUNT(*) FROM graph_nodes WHERE NOT (kind='note' OR id LIKE 'note:%')"
                ).fetchone()[0]),
                "edges": int(self.conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]),
                "pending": int(self.conn.execute("SELECT COUNT(*) FROM pending_edges").fetchone()[0]),
                "notes": notes,
            }
            return CleanPlan("reset", tuple(), counts, tuple(errors), include_notes)

        if stale:
            placeholders = ",".join("?" for _ in stale)
            path_clause = f" IN ({placeholders})"
            path_params: List[Any] = list(stale)
        else:
            path_clause = " IN (NULL)"
            path_params = []
        counts = {
            "paths": len(stale),
            "nodes": int(self.conn.execute(
                f"SELECT COUNT(*) FROM graph_nodes WHERE path{path_clause} "
                "AND NOT (kind='note' OR id LIKE 'note:%')", path_params
            ).fetchone()[0]),
            # Notes are intentionally preserved by stale cleanup.
            "notes": 0,
        }
        edge_orphan = (
            "NOT EXISTS (SELECT 1 FROM graph_nodes n WHERE n.id=e.src) "
            "OR NOT EXISTS (SELECT 1 FROM graph_nodes n WHERE n.id=e.dst)"
        )
        counts["edges"] = int(self.conn.execute(
            f"SELECT COUNT(*) FROM graph_edges e WHERE e.path{path_clause} OR {edge_orphan}",
            path_params,
        ).fetchone()[0])
        pending_orphan = (
            "NOT EXISTS (SELECT 1 FROM graph_nodes n WHERE n.id=p.src) "
            "OR NOT EXISTS (SELECT 1 FROM file_journal j WHERE j.path=p.path)"
        )
        counts["pending"] = int(self.conn.execute(
            f"SELECT COUNT(*) FROM pending_edges p WHERE p.path{path_clause} OR {pending_orphan}",
            path_params,
        ).fetchone()[0])
        return CleanPlan("stale", tuple(sorted(stale)), counts, tuple(errors), False)

    def apply_clean(self, plan: CleanPlan) -> Dict[str, int]:
        if plan.mode not in {"stale", "reset"}:
            raise ValueError(f"unknown clean plan mode: {plan.mode}")
        deleted = {k: 0 for k in ("paths", "nodes", "edges", "pending", "notes")}
        with self.conn:
            if plan.mode == "reset":
                if plan.include_notes:
                    deleted["notes"] = int(self.conn.execute(
                        "SELECT COUNT(*) FROM graph_nodes WHERE kind='note' OR id LIKE 'note:%'"
                    ).fetchone()[0])
                    self.conn.execute("DELETE FROM graph_nodes")
                else:
                    self.conn.execute(
                        "DELETE FROM graph_nodes WHERE NOT (kind='note' OR id LIKE 'note:%')"
                    )
                self.conn.execute("DELETE FROM graph_edges")
                self.conn.execute("DELETE FROM pending_edges")
                self.conn.execute("DELETE FROM file_journal")
                deleted.update({
                    "paths": plan.counts.get("paths", 0),
                    "nodes": plan.counts.get("nodes", 0),
                    "edges": plan.counts.get("edges", 0),
                    "pending": plan.counts.get("pending", 0),
                })
                return deleted
            for path in plan.paths:
                try:
                    if stat.S_ISREG(os.stat(path).st_mode):
                        continue
                except OSError:
                    pass
                deleted["paths"] += self.conn.execute(
                    "DELETE FROM file_journal WHERE path=?", (path,)
                ).rowcount
                deleted["nodes"] += self.conn.execute(
                    "DELETE FROM graph_nodes WHERE path=? "
                    "AND NOT (kind='note' OR id LIKE 'note:%')", (path,)
                ).rowcount
                deleted["edges"] += self.conn.execute(
                    "DELETE FROM graph_edges WHERE path=?", (path,)
                ).rowcount
                deleted["pending"] += self.conn.execute(
                    "DELETE FROM pending_edges WHERE path=?", (path,)
                ).rowcount
            deleted["edges"] += self.conn.execute(
                "DELETE FROM graph_edges WHERE NOT EXISTS "
                "(SELECT 1 FROM graph_nodes n WHERE n.id=graph_edges.src) "
                "OR NOT EXISTS (SELECT 1 FROM graph_nodes n WHERE n.id=graph_edges.dst)"
            ).rowcount
            deleted["pending"] += self.conn.execute(
                "DELETE FROM pending_edges WHERE NOT EXISTS "
                "(SELECT 1 FROM graph_nodes n WHERE n.id=pending_edges.src) "
                "OR NOT EXISTS (SELECT 1 FROM file_journal j WHERE j.path=pending_edges.path)"
            ).rowcount
        return deleted


    def _metrics(self) -> Tuple[int, int, int, int, int, int]:
        size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        wal = self.db_path + "-wal"
        wal_size = os.path.getsize(wal) if os.path.exists(wal) else 0
        page_size = int(self.conn.execute("PRAGMA page_size").fetchone()[0])
        pages = int(self.conn.execute("PRAGMA page_count").fetchone()[0])
        free = int(self.conn.execute("PRAGMA freelist_count").fetchone()[0])
        return size, wal_size, page_size, pages, free, free * page_size

    def vacuum(self, *, optimize: bool = False, dry_run: bool = False) -> VacuumResult:
        if self.read_only:
            raise sqlite3.OperationalError("vacuum requires a read-write database")
        if self.conn.in_transaction:
            raise sqlite3.OperationalError("cannot vacuum while a transaction is active")
        started = time.monotonic()
        before_size, before_wal, page_size, before_pages, before_free, estimate = self._metrics()
        if dry_run:
            return VacuumResult(before_size, before_size, before_wal, before_wal, page_size,
                                before_pages, before_pages, before_free, before_free, estimate, 0,
                                "not-run", 0, False, True)
        available = shutil.disk_usage(os.path.dirname(self.db_path) or ".").free
        if available < max(before_size, page_size):
            raise sqlite3.OperationalError(
                f"insufficient free space for VACUUM: {available} bytes available, {before_size} required"
            )
        self.conn.commit()
        checkpoint = self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint and int(checkpoint[0]) != 0:
            raise sqlite3.OperationalError("database busy during WAL checkpoint")
        checkpoint_status = "ok"
        try:
            self.conn.commit()
            self.conn.execute("VACUUM")
            if optimize:
                self.conn.execute("PRAGMA optimize")
            self.conn.commit()
        except sqlite3.Error as exc:
            raise sqlite3.OperationalError(f"VACUUM failed: {exc}") from exc
        quick_check = self.conn.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise sqlite3.DatabaseError(f"PRAGMA quick_check failed: {quick_check}")
        after_size, after_wal, _, after_pages, after_free, _ = self._metrics()
        return VacuumResult(before_size, after_size, before_wal, after_wal, page_size,
                            before_pages, after_pages, before_free, after_free, estimate,
                            max(0, before_size - after_size), checkpoint_status,
                            int((time.monotonic() - started) * 1000), bool(optimize), False)

    def search_fts(self, query: str, limit: int = 10, scope: Optional[str] = None) -> List[Dict[str, Any]]:
        clean_q = "".join(c if c.isalnum() or c.isspace() else " " for c in query).strip()
        if not clean_q or limit <= 0:
            return []
        tokens = [f'"{t}"*' for t in clean_q.split() if len(t) >= 2] or [f'"{t}"' for t in clean_q.split()]
        sql = "SELECT k.id,k.path,k.kind,k.symbol,k.label,k.body,k.keywords,k.line_start,bm25(graph_fts) " \
              "FROM graph_fts f JOIN graph_nodes k ON f.rowid=k.rowid WHERE graph_fts MATCH ?"
        params: List[Any] = [" OR ".join(tokens)]
        if scope:
            sql += " AND (k.path LIKE ? OR k.body LIKE ?)"
            params.extend([f"%{scope}%", f"%{scope}%"])
        sql += " ORDER BY bm25(graph_fts) ASC LIMIT ?"
        params.append(limit * 3)
        return [{"id": r[0], "path": r[1], "kind": r[2], "symbol": r[3], "label": r[4],
                 "body": r[5], "keywords": r[6], "line_start": r[7], "score": abs(r[8])}
                for r in self.conn.execute(sql, params).fetchall()]

    def explore_node(self, node_id: str, depth: int = 1, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        if depth < 0 or (limit is not None and limit <= 0):
            return []
        visited: Set[str] = set()
        result: List[Dict[str, Any]] = []
        queue: List[Tuple[str, int]] = [(node_id, 0)]
        while queue and (limit is None or len(result) < limit):
            current, current_depth = queue.pop(0)
            if current in visited or current_depth > depth:
                continue
            visited.add(current)
            remaining = "" if limit is None else f" LIMIT {max(0, limit - len(result))}"
            rows = self.conn.execute(
                "SELECT e.relation,n.id,n.label,n.path,n.line_start,n.kind FROM graph_edges e "
                "JOIN graph_nodes n ON e.dst=n.id WHERE e.src=? ORDER BY n.id" + remaining, (current,)
            ).fetchall()
            for rel, target, label, path, line, kind in rows:
                result.append({"direction": "outward", "relation": rel, "target_id": target,
                               "label": label, "path": path, "line": line, "kind": kind,
                               "depth": current_depth + 1})
                if target not in visited and current_depth + 1 <= depth:
                    queue.append((target, current_depth + 1))
                if limit is not None and len(result) >= limit:
                    break
            if limit is not None and len(result) >= limit:
                break
            remaining = "" if limit is None else f" LIMIT {max(0, limit - len(result))}"
            rows = self.conn.execute(
                "SELECT e.relation,n.id,n.label,n.path,n.line_start,n.kind FROM graph_edges e "
                "JOIN graph_nodes n ON e.src=n.id WHERE e.dst=? ORDER BY n.id" + remaining, (current,)
            ).fetchall()
            for rel, source, label, path, line, kind in rows:
                result.append({"direction": "inward", "relation": f"used_by ({rel})", "target_id": source,
                               "label": label, "path": path, "line": line, "kind": kind,
                               "depth": current_depth + 1})
                if source not in visited and current_depth + 1 <= depth:
                    queue.append((source, current_depth + 1))
                if limit is not None and len(result) >= limit:
                    break
        return result

    def stats(self) -> Dict[str, int]:
        def count(sql: str) -> int:
            return int(self.conn.execute(sql).fetchone()[0])
        return {"paths": count("SELECT COUNT(*) FROM file_journal"),
                "nodes": count("SELECT COUNT(*) FROM graph_nodes"),
                "edges": count("SELECT COUNT(*) FROM graph_edges"),
                "pending": count("SELECT COUNT(*) FROM pending_edges")}
