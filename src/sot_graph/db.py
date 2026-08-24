"""
sot_graph.db — SQLite schema and storage for the Source-of-Truth Knowledge Graph.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import stat
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import quote


SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS file_journal (
    path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
    mtime_ms INTEGER NOT NULL, generation INTEGER DEFAULT 1, reconciled_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS graph_nodes (
    id TEXT PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL, symbol TEXT,
    fqn TEXT, signature TEXT,
    label TEXT NOT NULL, body TEXT NOT NULL, keywords TEXT,
    line_start INTEGER, line_end INTEGER, col_start INTEGER, col_end INTEGER,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_path ON graph_nodes(path);
CREATE INDEX IF NOT EXISTS idx_nodes_symbol ON graph_nodes(symbol);
CREATE INDEX IF NOT EXISTS idx_nodes_fqn ON graph_nodes(fqn);
CREATE TABLE IF NOT EXISTS graph_edges (
    path TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL, relation TEXT NOT NULL,
    line INTEGER, PRIMARY KEY (path, src, dst, relation)
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON graph_edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON graph_edges(dst);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON graph_edges(relation);
CREATE TABLE IF NOT EXISTS pending_edges (
    path TEXT NOT NULL, src TEXT NOT NULL, dst_symbol TEXT NOT NULL,
    relation TEXT NOT NULL, line INTEGER,
    language TEXT NOT NULL DEFAULT '',
    call_kind TEXT NOT NULL DEFAULT 'UNKNOWN',
    receiver TEXT,
    import_source TEXT,
    resolution_state TEXT NOT NULL DEFAULT 'UNRESOLVED',
    PRIMARY KEY (path, src, dst_symbol, relation)
);
CREATE INDEX IF NOT EXISTS idx_pending_dst ON pending_edges(dst_symbol);
CREATE VIRTUAL TABLE IF NOT EXISTS graph_fts USING fts5(
    label, fqn, body, keywords, content='graph_nodes', content_rowid='rowid',
    tokenize="unicode61 remove_diacritics 0 tokenchars '_-.:$@'"
);
CREATE TRIGGER IF NOT EXISTS trg_nodes_ai AFTER INSERT ON graph_nodes BEGIN
    INSERT INTO graph_fts(rowid, label, fqn, body, keywords)
    VALUES (new.rowid, new.label, new.fqn, new.body, new.keywords);
END;
CREATE TRIGGER IF NOT EXISTS trg_nodes_ad AFTER DELETE ON graph_nodes BEGIN
    INSERT INTO graph_fts(graph_fts, rowid, label, fqn, body, keywords)
    VALUES ('delete', old.rowid, old.label, old.fqn, old.body, old.keywords);
END;
CREATE TRIGGER IF NOT EXISTS trg_nodes_au AFTER UPDATE ON graph_nodes BEGIN
    INSERT INTO graph_fts(graph_fts, rowid, label, fqn, body, keywords)
    VALUES ('delete', old.rowid, old.label, old.fqn, old.body, old.keywords);
    INSERT INTO graph_fts(rowid, label, fqn, body, keywords)
    VALUES (new.rowid, new.label, new.fqn, new.body, new.keywords);
END;
CREATE TABLE IF NOT EXISTS graph_communities (
    community_id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    cohesion_score REAL DEFAULT 0.0,
    node_count INTEGER DEFAULT 0,
    nodes_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ui_navigation (
    id TEXT PRIMARY KEY,
    menu_label TEXT,
    route_path TEXT NOT NULL,
    component_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    parent_id TEXT,
    FOREIGN KEY(parent_id) REFERENCES ui_navigation(id)
);
CREATE INDEX IF NOT EXISTS idx_ui_nav_route ON ui_navigation(route_path);
CREATE INDEX IF NOT EXISTS idx_ui_nav_comp ON ui_navigation(component_name);
CREATE TABLE IF NOT EXISTS ui_decision_nodes (
    id TEXT PRIMARY KEY,
    component_name TEXT NOT NULL,
    handler_symbol TEXT NOT NULL,
    trigger_element TEXT,
    condition_expr TEXT NOT NULL,
    branch_type TEXT NOT NULL,
    ui_effect TEXT NOT NULL,
    ui_target TEXT,
    file_path TEXT NOT NULL,
    line_number INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ui_dec_comp ON ui_decision_nodes(component_name);
CREATE INDEX IF NOT EXISTS idx_ui_dec_handler ON ui_decision_nodes(handler_symbol);
CREATE TABLE IF NOT EXISTS api_cross_bindings (
    id TEXT PRIMARY KEY,
    fe_caller_symbol TEXT NOT NULL,
    http_method TEXT NOT NULL,
    normalized_uri TEXT NOT NULL,
    be_controller_symbol TEXT,
    request_dto TEXT,
    response_dto TEXT,
    fe_file TEXT,
    be_file TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_binding_uri ON api_cross_bindings(normalized_uri);
CREATE INDEX IF NOT EXISTS idx_api_binding_fe ON api_cross_bindings(fe_caller_symbol);
CREATE INDEX IF NOT EXISTS idx_api_binding_be ON api_cross_bindings(be_controller_symbol);
CREATE TABLE IF NOT EXISTS be_execution_steps (
    id TEXT PRIMARY KEY,
    service_symbol TEXT NOT NULL,
    step_order INTEGER NOT NULL,
    step_name TEXT NOT NULL,
    code_statement TEXT NOT NULL,
    step_description TEXT NOT NULL,
    step_category TEXT NOT NULL,
    datasource_target TEXT,
    file_path TEXT NOT NULL,
    line_number INTEGER
);
CREATE INDEX IF NOT EXISTS idx_be_steps_service ON be_execution_steps(service_symbol);
CREATE TABLE IF NOT EXISTS related_features_index (
    id TEXT PRIMARY KEY,
    module_name TEXT NOT NULL,
    feature_name TEXT NOT NULL,
    feature_category TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    short_description TEXT NOT NULL,
    key_files TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rel_feat_module ON related_features_index(module_name);
"""

# Ordered drop list for the disposable-index migration: the filesystem is the
# source of truth, so a legacy schema is dropped and rebuilt by the next
# reconcile instead of being migrated in place.
_DROP_ON_RESET = (
    "DROP TABLE IF EXISTS related_features_index",
    "DROP TABLE IF EXISTS be_execution_steps",
    "DROP TABLE IF EXISTS api_cross_bindings",
    "DROP TABLE IF EXISTS ui_decision_nodes",
    "DROP TABLE IF EXISTS ui_navigation",
    "DROP TABLE IF EXISTS graph_fts",
    "DROP TABLE IF EXISTS graph_communities",
    "DROP TABLE IF EXISTS pending_edges",
    "DROP TABLE IF EXISTS graph_edges",
    "DROP TABLE IF EXISTS graph_nodes",
    "DROP TABLE IF EXISTS file_journal",
)

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
        self.schema_was_reset = False
        if read_only:
            if self._user_version() != SCHEMA_VERSION:
                self.conn.close()
                raise RuntimeError(
                    "database schema is outdated; run `sot reconcile` once to rebuild"
                )
            # Reader profile: bounded caches keep 50 concurrent agents well
            # under 250MB RSS instead of relying on per-connection defaults.
            self.conn.execute("PRAGMA query_only = ON")
            self.conn.execute("PRAGMA cache_size = -4000")   # 4MB page cache
            self.conn.execute("PRAGMA temp_store = FILE")    # guard VPS RAM
        else:
            # Writer profile: single-writer with a bounded 8MB page cache.
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = NORMAL")
            self.conn.execute("PRAGMA cache_size = -8000")   # 8MB page cache
            self.conn.execute("PRAGMA mmap_size = 67108864") # 64MB shared mmap
            if initialize:
                self._init_schema()

    def _user_version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def transactional_mutation(self, action):
        """Execute a mutating action under the stable write lock and connection transaction."""
        with self.write_lock():
            with self.conn:
                return action(self)

    def maintenance_mutation(self, action):
        """Execute an autocommit maintenance action (e.g. VACUUM) under the write lock."""
        with self.write_lock():
            return action(self)

    def _migrate_database(self) -> None:
        """Perform safe schema migration with live backup under the write lock."""
        with self.write_lock():
            version = self._user_version()
            if version != SCHEMA_VERSION:
                if version != 0 or self._schema_objects_present():
                    # Create a backup before modifying schema
                    backup_path = self.db_path + f".bak.{int(time.time())}"
                    bck_conn = None
                    try:
                        bck_conn = sqlite3.connect(backup_path)
                        self.conn.backup(bck_conn)
                    except Exception as e:
                        if bck_conn is not None:
                            try:
                                bck_conn.close()
                            except Exception:
                                pass
                            bck_conn = None
                        if os.path.exists(backup_path):
                            try:
                                os.unlink(backup_path)
                            except OSError:
                                pass
                        raise RuntimeError(f"Database backup failed before migration: {e}") from e
                    finally:
                        if bck_conn is not None:
                            bck_conn.close()

                    # Preserve user notes before resetting disposable index
                    notes: List[Tuple[Any, ...]] = []
                    has_nodes = bool(self.conn.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='graph_nodes'"
                    ).fetchone()[0])
                    if has_nodes:
                        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(graph_nodes)").fetchall()]
                        req_cols = ["id", "path", "kind", "symbol", "fqn", "signature", "label", "body", "keywords", "line_start", "line_end", "col_start", "col_end", "updated_at"]
                        selected_cols = [c if c in cols else "NULL" for c in req_cols]
                        cursor = self.conn.execute(
                            f"SELECT {', '.join(selected_cols)} FROM graph_nodes WHERE kind = 'note' OR id LIKE 'note:%'"
                        )
                        notes = cursor.fetchall()

                    with self.conn:
                        for statement in _DROP_ON_RESET:
                            self.conn.execute(statement)
                    self.schema_was_reset = True

                    with self.conn:
                        self.conn.executescript(SCHEMA)
                        if notes:
                            self.conn.executemany(
                                "INSERT OR REPLACE INTO graph_nodes "
                                "(id, path, kind, symbol, fqn, signature, label, body, keywords, line_start, line_end, col_start, col_end, updated_at) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                notes,
                            )
                        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                else:
                    with self.conn:
                        self.conn.executescript(SCHEMA)
                        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    def _init_schema(self) -> None:
        version = self._user_version()
        if version != SCHEMA_VERSION:
            self._migrate_database()
    def _schema_objects_present(self) -> bool:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name IN ('file_journal','graph_nodes','graph_edges',"
            "'pending_edges','graph_fts','graph_communities')"
        ).fetchone()
        return int(row[0]) > 0

    def write_lock(self):
        """Stable project-wide publication lock (`.sot/write.lock`)."""
        from sot_graph.locking import WriteLock
        return WriteLock(
            os.path.join(os.path.dirname(self.db_path), "write.lock"),
            timeout_ms=self.timeout_ms,
        )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def get_file_journal(self, path: str) -> Optional[Dict[str, Any]]:
        norm_path = path.replace(os.sep, "/")
        try:
            real_path = os.path.realpath(path).replace(os.sep, "/")
        except Exception:
            real_path = norm_path
        row = self.conn.execute(
            "SELECT sha256, size, mtime_ms, generation, reconciled_at "
            "FROM file_journal WHERE path = ? OR path = ? OR path = ? "
            "OR path LIKE ? OR path LIKE ? LIMIT 1",
            (path, norm_path, real_path, f"%/{norm_path.lstrip('/')}", f"%/{path.lstrip('/')}"),
        ).fetchone()
        if row is None:
            return None
        return {
            "sha256": row[0],
            "size": row[1],
            "mtime_ms": row[2],
            "generation": row[3],
            "reconciled_at": row[4],
        }

    def get_all_file_journals(self) -> Dict[str, Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT path, sha256, size, mtime_ms, generation, reconciled_at FROM file_journal"
        ).fetchall()
        return {
            r[0]: {
                "sha256": r[1],
                "size": r[2],
                "mtime_ms": r[3],
                "generation": r[4],
                "reconciled_at": r[5],
            }
            for r in rows
        }

    def all_journal_paths(self) -> List[str]:
        return [r[0] for r in self.conn.execute("SELECT path FROM file_journal ORDER BY path")]

    def get_node_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT id, path, kind, symbol, fqn, line_start, line_end, updated_at "
            "FROM graph_nodes WHERE symbol = ? OR fqn = ? OR fqn LIKE ? OR symbol LIKE ? LIMIT 1",
            (symbol, symbol, f"%.{symbol}", f"%.{symbol}"),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "path": row[1],
            "kind": row[2],
            "symbol": row[3],
            "fqn": row[4],
            "line_start": row[5],
            "line_end": row[6],
            "updated_at": row[7],
        }

    def get_node_by_id(self, node_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT id, path, kind, symbol, fqn, line_start, line_end, updated_at "
            "FROM graph_nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "path": row[1],
            "kind": row[2],
            "symbol": row[3],
            "fqn": row[4],
            "line_start": row[5],
            "line_end": row[6],
            "updated_at": row[7],
        }

    def delete_path(self, path: str) -> None:
        """Remove a file's rows.

        Inbound edges from OTHER files that point at this file's nodes would
        dangle once the nodes are gone; re-queue them as pending rows so the
        next resolution pass can re-attach them wherever the symbols now live
        (e.g. after the file is moved or renamed).
        """
        with self.conn:
            requeued = self.conn.execute(
                "SELECT e.path, e.src, e.relation, e.line, n.symbol, n.fqn, n.kind "
                "FROM graph_edges e JOIN graph_nodes n ON e.dst = n.id "
                "WHERE n.path = ? AND e.path != ?",
                (path, path),
            ).fetchall()
            if requeued:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO pending_edges"
                    "(path, src, dst_symbol, relation, line, call_kind, import_source) "
                    "VALUES (?,?,?,?,?,?,?)",
                    [
                        (e_path, src, self._requeue_symbol(row), relation, line,
                         "UNKNOWN", self._requeue_import_source(row))
                        for e_path, src, relation, line, *row in requeued
                    ],
                )
            self.conn.execute("DELETE FROM graph_nodes WHERE path = ?", (path,))
            self.conn.execute("DELETE FROM graph_edges WHERE path = ?", (path,))
            self.conn.execute("DELETE FROM pending_edges WHERE path = ?", (path,))
            self.conn.execute("DELETE FROM file_journal WHERE path = ?", (path,))

    @staticmethod
    def _requeue_symbol(dst_node: list) -> str:
        """Bare reference name for a re-queued edge: the symbol itself, or the
        module's last segment when the edge pointed at a file node."""
        symbol, fqn, kind = dst_node
        if kind == "file":
            return (fqn or "").rsplit(".", 1)[-1] or (symbol or "")
        return symbol or ""

    @staticmethod
    def _requeue_import_source(dst_node: list) -> Optional[str]:
        """File-node targets keep their dotted module as the import hint so
        the resolver can find the module's new file; symbol targets resolve by
        name (unique candidate) instead of a stale module path."""
        symbol, fqn, kind = dst_node
        return fqn if kind == "file" else None

    def cleanup_orphan_edges(self) -> Dict[str, int]:
        """Delete edge rows whose endpoint nodes no longer exist.

        Mirrors the integrity statements of apply_clean for callers that need
        a standalone sweep (e.g. after reconcile).
        """
        with self.conn:
            edges = self.conn.execute(
                "DELETE FROM graph_edges WHERE NOT EXISTS "
                "(SELECT 1 FROM graph_nodes n WHERE n.id=graph_edges.src) "
                "OR NOT EXISTS (SELECT 1 FROM graph_nodes n WHERE n.id=graph_edges.dst)"
            ).rowcount
            pending = self.conn.execute(
                "DELETE FROM pending_edges WHERE NOT EXISTS "
                "(SELECT 1 FROM graph_nodes n WHERE n.id=pending_edges.src) "
                "OR NOT EXISTS (SELECT 1 FROM file_journal j WHERE j.path=pending_edges.path)"
            ).rowcount
        return {"edges": int(edges), "pending": int(pending)}

    def delete_node_by_id(self, node_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM graph_nodes WHERE id = ?", (node_id,))
            self.conn.execute("DELETE FROM graph_edges WHERE src = ? OR dst = ?", (node_id, node_id))
            self.conn.execute("DELETE FROM pending_edges WHERE src = ?", (node_id,))

    def rehome_file_atomically(
        self,
        old_path: str,
        new_path: str,
        new_sha256: Optional[str] = None,
        new_mtime_ms: Optional[int] = None,
        new_size: Optional[int] = None,
    ) -> bool:
        """Atomically rehome a file and all its nodes, edges, and journal in 01 SQLite transaction."""
        now = int(time.time())
        with self.conn:
            # 1. Update file_journal
            if new_sha256 is not None and new_size is not None and new_mtime_ms is not None:
                self.conn.execute(
                    "UPDATE file_journal SET path = ?, sha256 = ?, size = ?, mtime_ms = ?, "
                    "generation = generation + 1, reconciled_at = ? WHERE path = ?",
                    (new_path, new_sha256, new_size, new_mtime_ms, now, old_path),
                )
            else:
                self.conn.execute(
                    "UPDATE file_journal SET path = ?, generation = generation + 1, "
                    "reconciled_at = ? WHERE path = ?",
                    (new_path, now, old_path),
                )

            # 2. Update graph_nodes (triggers will maintain FTS5)
            self.conn.execute(
                "UPDATE graph_nodes SET path = ?, "
                "id = REPLACE(id, ?, ?), "
                "label = REPLACE(label, ?, ?), "
                "body = REPLACE(body, ?, ?), "
                "updated_at = ? WHERE path = ?",
                (new_path, old_path, new_path, old_path, new_path, old_path, new_path, now, old_path),
            )

            # 3. Update graph_edges
            self.conn.execute(
                "UPDATE graph_edges SET path = ?, "
                "src = REPLACE(src, ?, ?), "
                "dst = REPLACE(dst, ?, ?) "
                "WHERE path = ?",
                (new_path, old_path, new_path, old_path, new_path, old_path),
            )
            self.conn.execute(
                "UPDATE graph_edges SET src = REPLACE(src, ?, ?) "
                "WHERE path != ? AND src LIKE ? || '%'",
                (old_path, new_path, new_path, old_path),
            )
            self.conn.execute(
                "UPDATE graph_edges SET dst = REPLACE(dst, ?, ?) "
                "WHERE path != ? AND dst LIKE ? || '%'",
                (old_path, new_path, new_path, old_path),
            )

            # 4. Update pending_edges
            self.conn.execute(
                "UPDATE pending_edges SET path = ?, "
                "src = REPLACE(src, ?, ?) "
                "WHERE path = ?",
                (new_path, old_path, new_path, old_path),
            )
            self.conn.execute(
                "UPDATE pending_edges SET src = REPLACE(src, ?, ?) "
                "WHERE path != ? AND src LIKE ? || '%'",
                (old_path, new_path, new_path, old_path),
            )

            # 5. Domain tables
            for tbl, col in [
                ("ui_navigation", "file_path"),
                ("ui_decision_nodes", "file_path"),
                ("be_execution_steps", "file_path"),
                ("api_cross_bindings", "fe_file"),
                ("api_cross_bindings", "be_file"),
            ]:
                try:
                    self.conn.execute(
                        f"UPDATE {tbl} SET {col} = ? WHERE {col} = ?",
                        (new_path, old_path),
                    )
                except Exception:
                    pass
        return True

    def update_node_path(self, node_id: str, old_path: str, new_path: str) -> None:
        self.rehome_file_atomically(old_path, new_path)
    @staticmethod
    def _record_value(record: Any, name: str) -> Any:
        if isinstance(record, Mapping):
            return record[name]
        return getattr(record, name)

    def commit_file_batch(
        self,
        records: Sequence[Any],
        expected_generations: Optional[Mapping[str, int]] = None,
    ) -> Dict[str, Any]:
        """Atomically replace a deterministically sorted batch of parsed files.

        When ``expected_generations`` maps a path to the ``file_journal``
        generation observed at parse time, that record is only committed if
        the stored generation still matches (compare-and-swap). A record that
        loses the race is skipped and reported under ``conflicts`` instead of
        silently overwriting the newer publication.
        """
        ordered = sorted(records, key=lambda r: os.path.normcase(os.path.normpath(
            str(self._record_value(r, "path"))))
        )
        if not ordered:
            return {"committed": 0, "conflicts": []}
        now = int(time.time())
        conflicts: List[str] = []
        with self.conn:
            for record in ordered:
                path = str(self._record_value(record, "path"))
                if expected_generations is not None:
                    row = self.conn.execute(
                        "SELECT generation FROM file_journal WHERE path = ?", (path,)
                    ).fetchone()
                    current_gen = int(row[0]) if row else 0
                    expected_gen = int(expected_generations.get(path, 0))
                    if current_gen != expected_gen:
                        conflicts.append(path)
                        continue
                nodes = self._record_value(record, "nodes")
                edges = self._record_value(record, "edges")
                pending = self._record_value(record, "pending")
                self.conn.execute("DELETE FROM graph_nodes WHERE path = ?", (path,))
                self.conn.execute("DELETE FROM graph_edges WHERE path = ?", (path,))
                self.conn.execute("DELETE FROM pending_edges WHERE path = ?", (path,))
                node_rows = []
                for n in nodes:
                    kw = n.get("keywords", [])
                    node_rows.append((
                        n["id"], path, n["kind"], n.get("symbol"),
                        n.get("fqn"), n.get("signature"),
                        n.get("label") or n.get("id") or "",
                        n.get("body") or "",
                        " ".join(kw) if kw else "",
                        n.get("line_start"), n.get("line_end"),
                        n.get("col_start"), n.get("col_end"), now))
                self.conn.executemany(
                    "INSERT OR REPLACE INTO graph_nodes "
                    "(id,path,kind,symbol,fqn,signature,label,body,keywords,"
                    "line_start,line_end,col_start,col_end,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", node_rows)
                self.conn.executemany(
                    "INSERT OR REPLACE INTO graph_edges (path,src,dst,relation,line) VALUES (?,?,?,?,?)",
                    [(path, e["src"], e["dst"], e["relation"], e.get("line")) for e in edges],
                )
                self.conn.executemany(
                    "INSERT OR REPLACE INTO pending_edges "
                    "(path,src,dst_symbol,relation,line,language,call_kind,receiver,"
                    "import_source,resolution_state) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [(path, p["src"], p["dst_symbol"], p["relation"], p.get("line"),
                      p.get("language", ""), p.get("call_kind", "UNKNOWN"),
                      p.get("receiver"), p.get("import_source"),
                      p.get("resolution_state", "UNRESOLVED")) for p in pending],
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
        return {"committed": len(ordered) - len(conflicts), "conflicts": conflicts}

    def commit_file(self, path: str, sha256: str, size: int, mtime_ms: int,
                    nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
                    pending: List[Dict[str, Any]]) -> None:
        self.commit_file_batch([{"path": path, "sha256": sha256, "size": size,
                                 "mtime_ms": mtime_ms, "nodes": nodes,
                                 "edges": edges, "pending": pending}])

    def _resolve_pending_edges_pass(
        self,
        row_filter=None,
    ) -> Dict[str, int]:
        """Binding-aware pending-edge resolution.

        Resolution precedence (audit contract — never ``ORDER BY id LIMIT 1``):
        explicit import module -> module-qualified candidate -> unique symbol
        candidate -> ambiguous candidate set (kept, never arbitrarily attached)
        -> unresolved. Pending rows whose import source is a non-project
        module are pruned as EXTERNAL; unshadowed bare builtins never reach
        this table at all (pruned at extraction time).
        """
        from sot_graph.modutil import normalize_import, project_module_names, resolve_relative, dotted_module

        project_names = project_module_names(self.all_journal_paths())

        # 1. Symbol Index
        symbol_index: Dict[str, List[Tuple[str, str]]] = {}
        class_methods: Dict[str, Dict[str, Tuple[str, str]]] = {}
        for node_id, node_path, symbol, kind, fqn in self.conn.execute(
            "SELECT id, path, symbol, kind, fqn FROM graph_nodes WHERE symbol IS NOT NULL"
        ):
            symbol_index.setdefault(symbol, []).append((node_id, node_path))
            if fqn and fqn != symbol:
                symbol_index.setdefault(fqn, []).append((node_id, node_path))
            if kind == "method" and symbol:
                if "." in symbol:
                    cls_name, m_name = symbol.rsplit(".", 1)
                    class_methods.setdefault(cls_name, {})[m_name] = (node_id, node_path)

        # 2. Class Hierarchy (Inheritance & MRO)
        class_bases: Dict[str, List[str]] = {}
        for src_rel, dst_rel in self.conn.execute(
            "SELECT src, dst FROM graph_edges WHERE relation IN ('extends', 'inherits', 'implements')"
        ):
            src_sym = src_rel.split(":")[-1] if ":" in src_rel else src_rel
            dst_sym = dst_rel.split(":")[-1] if ":" in dst_rel else dst_rel
            class_bases.setdefault(src_sym, []).append(dst_sym)
        for p_src, p_dst in self.conn.execute(
            "SELECT src, dst_symbol FROM pending_edges WHERE relation IN ('extends', 'inherits', 'implements')"
        ):
            src_sym = p_src.split(":")[-1] if ":" in p_src else p_src
            dst_sym = p_dst.split(":")[-1] if ":" in p_dst else p_dst
            if dst_sym not in class_bases.get(src_sym, []):
                class_bases.setdefault(src_sym, []).append(dst_sym)

        def lookup_class_method(cls_name: str, method_name: str) -> Optional[Tuple[str, str]]:
            if not cls_name:
                return None
            if cls_name in class_methods and method_name in class_methods[cls_name]:
                return class_methods[cls_name][method_name]
            visited = {cls_name}
            queue = list(class_bases.get(cls_name, []))
            while queue:
                base = queue.pop(0)
                if base in class_methods and method_name in class_methods[base]:
                    return class_methods[base][method_name]
                for next_base in class_bases.get(base, []):
                    if next_base not in visited:
                        visited.add(next_base)
                        queue.append(next_base)
            return None

        file_nodes: List[Tuple[str, str]] = [
            (row[0], row[1]) for row in self.conn.execute(
                "SELECT id, path FROM graph_nodes WHERE kind = 'file'"
            )
        ]

        module_cache: Dict[str, Set[str]] = {}

        def path_module_names(path: str) -> Set[str]:
            names = module_cache.get(path)
            if names is None:
                names = project_module_names([path])
                module_cache[path] = names
            return names

        # 3. Re-export Map (e.g. __init__.py re-exports)
        reexport_map: Dict[Tuple[str, str], Tuple[str, str]] = {}
        for imp_path, imp_src, imp_dst, imp_line in self.conn.execute(
            "SELECT path, src, dst, line FROM graph_edges WHERE relation = 'imports'"
        ):
            dst_row = self.conn.execute("SELECT path, symbol FROM graph_nodes WHERE id = ?", (imp_dst,)).fetchone()
            if dst_row and dst_row[1]:
                dst_path, dst_symbol = dst_row
                for mod_name in path_module_names(imp_path):
                    reexport_map[(mod_name, dst_symbol)] = (imp_dst, dst_path)

        rows = self.conn.execute(
            "SELECT rowid, path, src, dst_symbol, relation, line, import_source, receiver, call_kind "
            "FROM pending_edges"
        ).fetchall()

        promoted = external = ambiguous = unresolved = 0
        edge_rows: List[Tuple[str, str, str, str, Optional[int]]] = []
        promote_deletes: List[int] = []
        external_deletes: List[int] = []
        ambiguous_updates: List[int] = []

        for rowid, path, src, dst_symbol, relation, line, import_source, receiver, call_kind in rows:
            if row_filter is not None and not row_filter(path, dst_symbol):
                continue
            imp = normalize_import(import_source)
            if import_source and import_source.startswith("."):
                abs_imp = resolve_relative(import_source, dotted_module(path), is_package=path.endswith("__init__.py"))
                if abs_imp:
                    imp = abs_imp

            if imp and imp not in project_names:
                is_proj = any(p == imp or p.startswith(imp + ".") or imp.startswith(p + ".") for p in project_names)
                if not is_proj:
                    external_deletes.append(rowid)
                    external += 1
                    continue

            candidates = symbol_index.get(dst_symbol, [])
            chosen: Optional[Tuple[str, str]] = None

            # Priority 1: Receiver Type & MRO Resolution
            if receiver:
                recv_cls = receiver.split(":")[-1]
                chosen = lookup_class_method(recv_cls, dst_symbol)
                if chosen is None and "." in src:
                    caller_cls = src.split(":")[-1].rsplit(".", 1)[0]
                    chosen = lookup_class_method(caller_cls, dst_symbol)

            # Priority 2: Re-export Resolution
            if chosen is None and imp:
                if (imp, dst_symbol) in reexport_map:
                    chosen = reexport_map[(imp, dst_symbol)]

            # Priority 3: Import module matching against candidate file path
            if chosen is None and imp:
                matched = [
                    (node_id, node_path) for node_id, node_path in candidates
                    if imp in path_module_names(node_path) or any(m.startswith(imp) for m in path_module_names(node_path))
                ]
                if len(matched) == 1:
                    chosen = matched[0]
                elif len(matched) > 1:
                    ambiguous_updates.append(rowid)
                    ambiguous += 1
                    continue

            # Priority 4: Unique project symbol (cross-file only; same-file shadowed calls stay unresolved)
            if chosen is None and len(candidates) == 1:
                if candidates[0][1] != path:
                    chosen = candidates[0]
            # Priority 5: Project import to file node
            if chosen is None and relation == "imports" and imp:
                file_matches = [
                    (node_id, node_path) for node_id, node_path in file_nodes
                    if imp in path_module_names(node_path)
                ]
                if len(file_matches) == 1:
                    chosen = file_matches[0]

            # Handle unresolved / ambiguous
            if chosen is None:
                if len(candidates) > 1:
                    ambiguous_updates.append(rowid)
                    ambiguous += 1
                else:
                    unresolved += 1
                continue

            edge_rows.append((path, src, chosen[0], relation, line))
            promote_deletes.append(rowid)
            promoted += 1
        with self.conn:
            if edge_rows:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO graph_edges(path,src,dst,relation,line) "
                    "VALUES (?,?,?,?,?)", edge_rows)
            if promote_deletes:
                self.conn.executemany(
                    "DELETE FROM pending_edges WHERE rowid = ?",
                    [(rid,) for rid in promote_deletes])
            if external_deletes:
                self.conn.executemany(
                    "DELETE FROM pending_edges WHERE rowid = ?",
                    [(rid,) for rid in external_deletes])
            if ambiguous_updates:
                self.conn.executemany(
                    "UPDATE pending_edges SET resolution_state = 'AMBIGUOUS' "
                    "WHERE rowid = ?", [(rid,) for rid in ambiguous_updates])

        return {
            "promoted": promoted,
            "external": external,
            "ambiguous": ambiguous,
            "unresolved": unresolved,
        }

    def resolve_all_pending_edges(self) -> int:
        """Promote resolvable pending edges; prune external imports.

        Returns the number of edges promoted to ``graph_edges``.
        """
        return self._resolve_pending_edges_pass()["promoted"]

    def resolve_pending_edges(self, new_symbols: List[str], current_file_path: Optional[str] = None) -> int:
        """Legacy v1 API: resolve only rows matching the new symbols or path."""
        if not new_symbols and not current_file_path:
            return 0
        wanted = set(new_symbols)

        def row_filter(path: str, dst_symbol: str) -> bool:
            if wanted and dst_symbol in wanted:
                return True
            return bool(current_file_path) and path == current_file_path

        return self._resolve_pending_edges_pass(row_filter=row_filter)["promoted"]

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

        batch_size = 500
        stale_nodes = 0
        for i in range(0, len(stale), batch_size):
            chunk = stale[i:i + batch_size]
            placeholders = ",".join("?" for _ in chunk)
            stale_nodes += int(self.conn.execute(
                f"SELECT COUNT(*) FROM graph_nodes WHERE path IN ({placeholders}) "
                "AND NOT (kind='note' OR id LIKE 'note:%')", list(chunk)
            ).fetchone()[0])

        edge_orphan = (
            "NOT EXISTS (SELECT 1 FROM graph_nodes n WHERE n.id=e.src) "
            "OR NOT EXISTS (SELECT 1 FROM graph_nodes n WHERE n.id=e.dst)"
        )
        orphan_edges = int(self.conn.execute(
            f"SELECT COUNT(*) FROM graph_edges e WHERE {edge_orphan}"
        ).fetchone()[0])
        stale_edges = 0
        for i in range(0, len(stale), batch_size):
            chunk = stale[i:i + batch_size]
            placeholders = ",".join("?" for _ in chunk)
            stale_edges += int(self.conn.execute(
                f"SELECT COUNT(*) FROM graph_edges e WHERE e.path IN ({placeholders}) AND NOT ({edge_orphan})",
                list(chunk)
            ).fetchone()[0])

        pending_orphan = (
            "NOT EXISTS (SELECT 1 FROM graph_nodes n WHERE n.id=p.src) "
            "OR NOT EXISTS (SELECT 1 FROM file_journal j WHERE j.path=p.path)"
        )
        orphan_pending = int(self.conn.execute(
            f"SELECT COUNT(*) FROM pending_edges p WHERE {pending_orphan}"
        ).fetchone()[0])
        stale_pending = 0
        for i in range(0, len(stale), batch_size):
            chunk = stale[i:i + batch_size]
            placeholders = ",".join("?" for _ in chunk)
            stale_pending += int(self.conn.execute(
                f"SELECT COUNT(*) FROM pending_edges p WHERE p.path IN ({placeholders}) AND NOT ({pending_orphan})",
                list(chunk)
            ).fetchone()[0])

        counts = {
            "paths": len(stale),
            "nodes": stale_nodes,
            "edges": orphan_edges + stale_edges,
            "pending": orphan_pending + stale_pending,
            "notes": 0,
        }
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
                for aux_table in (
                    "ui_navigation",
                    "ui_decision_nodes",
                    "api_cross_bindings",
                    "be_execution_steps",
                    "related_features_index",
                    "graph_communities",
                ):
                    try:
                        self.conn.execute(f"DELETE FROM {aux_table}")
                    except sqlite3.OperationalError:
                        pass
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
        raw_tokens = [t.strip("\"'") for t in query.split() if t.strip("\"'")]
        tokens: Set[str] = set()
        tokens_l: List[str] = []
        for raw in raw_tokens:
            cleaned = re.sub(r'[\*\^\"(){}:]', '', raw)
            if not cleaned:
                continue
            if len(cleaned) >= 2:
                tokens.add(f'"{cleaned}"*')
            for part in re.split(r'[_\.\-:\$@\s]+', cleaned):
                if len(part) >= 2:
                    tokens.add(f'"{part}"*')
                    tokens_l.append(part.lower())
                part_strip = part.strip('_')
                if len(part_strip) >= 2:
                    tokens.add(f'"{part_strip}"*')
                    tokens_l.append(part_strip.lower())
        if not tokens or limit <= 0:
            return []
        sql = "SELECT k.id,k.path,k.kind,k.symbol,k.fqn,k.label,k.body,k.keywords,k.line_start,bm25(graph_fts) " \
              "FROM graph_fts f JOIN graph_nodes k ON f.rowid=k.rowid WHERE graph_fts MATCH ?"
        params: List[Any] = [" OR ".join(sorted(tokens))]
        if scope:
            sql += " AND (k.path LIKE ? OR k.body LIKE ?)"
            params.extend([f"%{scope}%", f"%{scope}%"])
        sql += " ORDER BY bm25(graph_fts) ASC LIMIT ?"
        params.append(limit * 3)
        rows = self.conn.execute(sql, params).fetchall()
        def _rank(r: Any) -> Tuple[int, float]:
            # bm25 is negative-better; keep the raw value for ordering.
            score = r[9]
            text = f"{r[3] or ''} {r[5] or ''}".lower()
            if r[2] != "file" and any(t in text for t in tokens_l):
                return (0, score)
            return (1, score)

        rows = sorted(rows, key=_rank)
        return [{"id": r[0], "path": r[1], "kind": r[2], "symbol": r[3], "fqn": r[4],
                 "label": r[5], "body": r[6], "keywords": r[7], "line_start": r[8], "score": abs(r[9])}
                for r in rows]

    def explore_node(self, node_id: str, depth: int = 1, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        if depth < 0 or (limit is not None and limit <= 0):
            return []
        visited: Set[str] = set()
        result: List[Dict[str, Any]] = []
        # queue stores (node_id, current_depth, via_id, via_label, via_path)
        queue: List[Tuple[str, int, Optional[str], Optional[str], Optional[str]]] = [(node_id, 0, None, None, None)]
        sql = (
            "SELECT 'outward' AS dir, e.relation, n.id, n.label, n.path, n.line_start, n.kind "
            "FROM graph_edges e JOIN graph_nodes n ON e.dst=n.id "
            "WHERE e.src=? AND e.relation != 'defines' "
            "UNION ALL "
            "SELECT 'inward' AS dir, e.relation, n.id, n.label, n.path, n.line_start, n.kind "
            "FROM graph_edges e JOIN graph_nodes n ON e.src=n.id "
            "WHERE e.dst=? AND e.relation != 'defines' "
            "ORDER BY dir DESC, n.id"
        )
        while queue and (limit is None or len(result) < limit):
            current, current_depth, via_id, via_label, via_path = queue.pop(0)
            if current in visited or current_depth >= depth:
                continue
            visited.add(current)
            rows = self.conn.execute(sql, (current, current)).fetchall()
            for direction, rel, target, label, path, line, kind in rows:
                if target == node_id:  # avoid trivial direct loopback to root
                    continue
                rel_label = rel if direction == "outward" else f"used_by ({rel})"
                hop_num = current_depth + 1
                result.append({
                    "direction": direction,
                    "relation": rel_label,
                    "target_id": target,
                    "label": label,
                    "path": path,
                    "line": line,
                    "kind": kind,
                    "depth": hop_num,
                    "hop": hop_num,
                    "via_id": via_id if hop_num > 1 else None,
                    "via_label": via_label if hop_num > 1 else None,
                    "via_path": via_path if hop_num > 1 else None,
                })
                if target not in visited and hop_num < depth:
                    queue.append((target, hop_num, target, label, path))
                if limit is not None and len(result) >= limit:
                    break
        return result

    def usages(self, node_id: str, symbol: str) -> Dict[str, Any]:
        """Every reference site of a symbol, grouped by caller.

        Calls/uses/imports edges pointing at ``node_id`` plus the unresolved
        pending edges whose bare name matches ``symbol`` (renaming risk).
        Returns structured completeness status, resolved vs unresolved counts,
        and honest next steps.
        """
        rows = self.conn.execute(
            "SELECT e.src, n.label, n.path, n.kind, e.relation, e.line "
            "FROM graph_edges e JOIN graph_nodes n ON e.src = n.id "
            "WHERE e.dst = ? AND e.relation != 'defines' "
            "ORDER BY n.path, e.line", (node_id,)
        ).fetchall()
        callers: List[Dict[str, Any]] = []
        by_caller: Dict[str, Dict[str, Any]] = {}
        for src, label, path, kind, rel, line in rows:
            entry = by_caller.get(src)
            if entry is None:
                entry = {"caller_id": src, "label": label, "path": path, "kind": kind, "sites": []}
                by_caller[src] = entry
                callers.append(entry)
            entry["sites"].append({"relation": rel, "line": line})

        names = [symbol]
        bare = symbol.rsplit(".", 1)[-1]
        if bare != symbol:
            names.append(bare)
        placeholders = ",".join("?" * len(names))
        risk = [
            {"src": r[0], "label": r[1], "path": r[2], "dst_symbol": r[3],
             "relation": r[4], "line": r[5], "state": r[6]}
            for r in self.conn.execute(
                f"SELECT p.src, n.label, n.path, p.dst_symbol, p.relation, p.line, p.resolution_state "
                f"FROM pending_edges p JOIN graph_nodes n ON p.src = n.id "
                f"WHERE p.dst_symbol IN ({placeholders}) "
                f"AND p.resolution_state IN ('UNRESOLVED', 'AMBIGUOUS') "
                f"AND p.src != ? ORDER BY p.resolution_state, n.path, p.line",
                (*names, node_id),
            ).fetchall()
        ]
        resolved_count = sum(len(c["sites"]) for c in callers)
        unresolved_count = len(risk)
        status = "COMPLETE" if unresolved_count == 0 else "PARTIAL"
        next_steps = []
        if unresolved_count > 0:
            next_steps = [
                "Inspect the pending edge candidates listed in risk/unresolved",
                "Run 'sot reconcile' if workspace files were recently updated",
                "Inspect dynamic callers in source code via LSP or grep",
            ]
        return {
            "symbol": symbol,
            "node_id": node_id,
            "status": status,
            "completeness": status,
            "resolved_count": resolved_count,
            "unresolved_count": unresolved_count,
            "callers": callers,
            "risk": risk,
            "confirmed": callers,
            "unresolved": risk,
            "next_steps": next_steps,
        }

    def inheritance_edges(self, node_id: str, symbol: str) -> Dict[str, Any]:
        """extends/implements edges around a node, both directions, plus
        unresolved pending links that could not be promoted."""
        def _around(where_col: str, join_col: str) -> List[Dict[str, Any]]:
            return [
                {"node_id": r[0], "label": r[1], "path": r[2], "kind": r[3],
                 "relation": r[4], "line": r[5]}
                for r in self.conn.execute(
                    f"SELECT n.id, n.label, n.path, n.kind, e.relation, e.line "
                    f"FROM graph_edges e JOIN graph_nodes n ON {join_col} = n.id "
                    f"WHERE {where_col} = ? AND e.relation IN ('extends', 'implements') "
                    f"ORDER BY n.path", (node_id,)
                ).fetchall()
            ]

        names = [symbol]
        bare = symbol.rsplit(".", 1)[-1]
        if bare != symbol:
            names.append(bare)
        placeholders = ",".join("?" * len(names))
        pending_bases = [
            {"src": r[0], "label": r[1], "path": r[2], "dst_symbol": r[3], "state": r[4]}
            for r in self.conn.execute(
                f"SELECT p.src, n.label, n.path, p.dst_symbol, p.resolution_state "
                f"FROM pending_edges p JOIN graph_nodes n ON p.src = n.id "
                f"WHERE p.src = ? AND p.relation IN ('extends', 'implements') "
                f"AND p.resolution_state != 'RESOLVED' ORDER BY n.path",
                (node_id,),
            ).fetchall()
        ]
        pending_derived = [
            {"src": r[0], "label": r[1], "path": r[2], "dst_symbol": r[3], "state": r[4]}
            for r in self.conn.execute(
                f"SELECT p.src, n.label, n.path, p.dst_symbol, p.resolution_state "
                f"FROM pending_edges p JOIN graph_nodes n ON p.src = n.id "
                f"WHERE p.dst_symbol IN ({placeholders}) "
                f"AND p.relation IN ('extends', 'implements') "
                f"AND p.resolution_state != 'RESOLVED' AND p.src != ? ORDER BY n.path",
                (*names, node_id),
            ).fetchall()
        ]
        return {
            "bases": _around("e.src", "e.dst"),
            "derived": _around("e.dst", "e.src"),
            "pending_bases": pending_bases,
            "pending_derived": pending_derived,
        }

    def stats(self) -> Dict[str, int]:
        row = self.conn.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM file_journal), "
            "(SELECT COUNT(*) FROM graph_nodes), "
            "(SELECT COUNT(*) FROM graph_edges), "
            "(SELECT COUNT(*) FROM pending_edges), "
            "(SELECT COUNT(*) FROM pending_edges WHERE resolution_state = 'AMBIGUOUS'), "
            "(SELECT COUNT(*) FROM pending_edges WHERE resolution_state = 'UNRESOLVED')"
        ).fetchone()
        return {
            "paths": int(row[0]),
            "nodes": int(row[1]),
            "edges": int(row[2]),
            "pending": int(row[3]),
            "pending_ambiguous": int(row[4]),
            "pending_unresolved": int(row[5]),
        }

    def integrity_check(self) -> Dict[str, Any]:
        """Perform comprehensive SQLite integrity, schema validation, and graph consistency checks."""
        errors: List[str] = []
        warnings: List[str] = []
        
        # 1. PRAGMA quick_check
        try:
            row = self.conn.execute("PRAGMA quick_check;").fetchone()
            quick_check_ok = row is not None and row[0] == "ok"
            if not quick_check_ok:
                errors.append(f"PRAGMA quick_check failed: {row[0] if row else 'empty result'}")
        except Exception as exc:
            quick_check_ok = False
            errors.append(f"PRAGMA quick_check exception: {exc}")

        # 2. PRAGMA foreign_key_check
        try:
            fk_rows = self.conn.execute("PRAGMA foreign_key_check;").fetchall()
            if fk_rows:
                errors.append(f"Foreign key violations detected: {len(fk_rows)} rows")
        except Exception as exc:
            errors.append(f"PRAGMA foreign_key_check exception: {exc}")

        # 3. Pragmas info
        try:
            user_ver = int(self.conn.execute("PRAGMA user_version;").fetchone()[0])
            if user_ver != SCHEMA_VERSION:
                warnings.append(f"Schema version mismatch: DB is v{user_ver}, expected v{SCHEMA_VERSION}")
            journal_mode = str(self.conn.execute("PRAGMA journal_mode;").fetchone()[0]).upper()
            page_size = int(self.conn.execute("PRAGMA page_size;").fetchone()[0])
            page_count = int(self.conn.execute("PRAGMA page_count;").fetchone()[0])
            db_size_bytes = page_size * page_count
        except Exception as exc:
            user_ver = -1
            journal_mode = "UNKNOWN"
            page_size = 0
            page_count = 0
            db_size_bytes = 0
            errors.append(f"Pragma query error: {exc}")

        # 4. Consistency checks
        orphaned_nodes_count = 0
        pending_by_state: Dict[str, int] = {}
        pending_by_relation: Dict[str, int] = {}
        fts_count = 0
        node_count = 0
        try:
            # Check orphaned nodes (code nodes with file path not in file_journal)
            orphaned_nodes_count = int(self.conn.execute(
                "SELECT COUNT(*) FROM graph_nodes n WHERE NOT (n.kind='note' OR n.id LIKE 'note:%') "
                "AND NOT EXISTS (SELECT 1 FROM file_journal j WHERE j.path = n.path)"
            ).fetchone()[0])
            if orphaned_nodes_count > 0:
                warnings.append(f"Found {orphaned_nodes_count} orphaned code nodes (path missing from file_journal)")

            # Check pending edges breakdown
            pending_rows = self.conn.execute(
                "SELECT resolution_state, relation, COUNT(*) FROM pending_edges GROUP BY resolution_state, relation"
            ).fetchall()
            for state, rel, count in pending_rows:
                pending_by_state[str(state)] = pending_by_state.get(str(state), 0) + int(count)
                pending_by_relation[str(rel)] = pending_by_relation.get(str(rel), 0) + int(count)

            # Check FTS5 sync integrity
            fts_count = int(self.conn.execute("SELECT COUNT(*) FROM graph_fts").fetchone()[0])
            node_count = int(self.conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0])
            if fts_count != node_count:
                warnings.append(f"FTS index count disparity: {fts_count} FTS records vs {node_count} graph nodes")
        except Exception as exc:
            errors.append(f"Consistency check error: {exc}")

        base_stats = self.stats()
        base_stats["orphaned_nodes"] = orphaned_nodes_count
        base_stats["fts_count"] = fts_count

        return {
            "ok": len(errors) == 0,
            "is_healthy": len(errors) == 0,
            "quick_check": "ok" if quick_check_ok else "failed",
            "schema_version": user_ver,
            "expected_schema_version": SCHEMA_VERSION,
            "journal_mode": journal_mode,
            "page_size": page_size,
            "page_count": page_count,
            "db_size_bytes": db_size_bytes,
            "stats": base_stats,
            "pending_breakdown": {
                "by_state": pending_by_state,
                "by_relation": pending_by_relation,
            },
            "warnings": warnings,
            "errors": errors,
        }

    def save_communities(self, communities_data: List[Dict[str, Any]]) -> None:
        """Persist detected communities to SQLite."""
        now = int(time.time())
        with self.conn:
            self.conn.execute("DELETE FROM graph_communities")
            for c in communities_data:
                nodes = c.get("nodes", [])
                nodes_json = json.dumps(nodes) if not isinstance(nodes, str) else nodes
                self.conn.execute(
                    "INSERT INTO graph_communities (community_id, label, cohesion_score, node_count, nodes_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        int(c["community_id"]),
                        str(c["label"]),
                        float(c.get("cohesion_score", 0.0)),
                        int(c.get("node_count", len(nodes))),
                        nodes_json,
                        now,
                    ),
                )

    def get_communities(self) -> List[Dict[str, Any]]:
        """Retrieve all stored communities."""
        rows = self.conn.execute(
            "SELECT community_id, label, cohesion_score, node_count, nodes_json, created_at "
            "FROM graph_communities ORDER BY node_count DESC, community_id ASC"
        ).fetchall()
        result = []
        for r in rows:
            try:
                nodes = json.loads(r[4])
            except Exception:
                nodes = []
            result.append({
                "community_id": r[0],
                "label": r[1],
                "cohesion_score": r[2],
                "node_count": r[3],
                "nodes": nodes,
                "created_at": r[5],
            })
        return result

    def get_community(self, community_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a specific community by ID."""
        row = self.conn.execute(
            "SELECT community_id, label, cohesion_score, node_count, nodes_json, created_at "
            "FROM graph_communities WHERE community_id = ?",
            (community_id,),
        ).fetchone()
        if not row:
            return None
        try:
            nodes = json.loads(row[4])
        except Exception:
            nodes = []
        return {
            "community_id": row[0],
            "label": row[1],
            "cohesion_score": row[2],
            "node_count": row[3],
            "nodes": nodes,
            "created_at": row[5],
        }
