"""
sot_graph.db — SQLite schema and storage for the Source-of-Truth Knowledge Graph.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import quote


SCHEMA_VERSION = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS file_journal (
    path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
    mtime_ms INTEGER NOT NULL, generation INTEGER DEFAULT 1, reconciled_at INTEGER NOT NULL,
    parser_outcome TEXT, parser_error TEXT
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
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    repo_root TEXT NOT NULL,
    commit_sha TEXT,
    dirty INTEGER NOT NULL DEFAULT 0,
    dirty_fingerprint TEXT,
    manifest_digest TEXT,
    algo_version TEXT NOT NULL DEFAULT 'sha256-v1',
    generation INTEGER,
    captured_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_runs (
    id TEXT PRIMARY KEY,
    provider_name TEXT NOT NULL,
    provider_version TEXT,
    capability TEXT NOT NULL,
    snapshot_hash TEXT,
    project_root TEXT,
    position_encoding TEXT DEFAULT 'UTF-8',
    arguments_json TEXT,
    status TEXT,
    exit_code INTEGER,
    duration_ms INTEGER,
    command_digest TEXT,
    created_at INTEGER NOT NULL,
    snapshot_id TEXT REFERENCES snapshots(id)
);
CREATE INDEX IF NOT EXISTS idx_provider_runs_prov ON provider_runs(provider_name);
CREATE TABLE IF NOT EXISTS provider_project_bindings (
    id TEXT PRIMARY KEY,
    sot_repo_id TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    provider_project_id TEXT NOT NULL,
    provider_generation INTEGER,
    head_sha TEXT,
    branch TEXT,
    updated_at INTEGER NOT NULL,
    UNIQUE(sot_repo_id, provider_name)
);
CREATE INDEX IF NOT EXISTS idx_ppb_repo ON provider_project_bindings(sot_repo_id);
CREATE TABLE IF NOT EXISTS provider_evidence (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    provider_name TEXT,
    file_path TEXT,
    path TEXT NOT NULL,
    symbol TEXT,
    src_symbol TEXT NOT NULL,
    target_symbol TEXT,
    dst_symbol TEXT,
    role TEXT,
    relation TEXT NOT NULL,
    line_start INTEGER,
    line_end INTEGER,
    col_start INTEGER,
    col_end INTEGER,
    syntax_kind TEXT,
    documentation TEXT,
    confidence REAL DEFAULT 1.0,
    metadata_json TEXT,
    snapshot_hash TEXT,
    invalidated_at INTEGER,
    invalidation_reason TEXT,
    recorded_at INTEGER,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(run_id) REFERENCES provider_runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_p_evidence_run ON provider_evidence(run_id);
CREATE INDEX IF NOT EXISTS idx_p_evidence_prov ON provider_evidence(provider_name);
CREATE INDEX IF NOT EXISTS idx_p_evidence_path ON provider_evidence(path);
CREATE INDEX IF NOT EXISTS idx_p_evidence_src ON provider_evidence(src_symbol);
CREATE INDEX IF NOT EXISTS idx_p_evidence_dst ON provider_evidence(dst_symbol);
CREATE INDEX IF NOT EXISTS idx_p_evidence_sym ON provider_evidence(symbol);
CREATE INDEX IF NOT EXISTS idx_p_evidence_snapshot ON provider_evidence(snapshot_hash);
"""
# Ordered drop list for the disposable-index migration: the filesystem is the
# source of truth, so a legacy schema is dropped and rebuilt by the next
# reconcile instead of being migrated in place.
_DROP_ON_RESET = (
    "DROP TABLE IF EXISTS provider_evidence",
    "DROP TABLE IF EXISTS provider_runs",
    "DROP TABLE IF EXISTS provider_project_bindings",
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
    """SQLite-backed knowledge-graph store.

    Thread model (contract): a ``Database`` instance owns exactly one
    ``sqlite3.Connection`` and is bound to the thread that created it.
    NEVER share an instance across threads. For concurrent access, open one
    ``Database(..., read_only=True)`` per reader thread; writers are
    serialized process-wide via the advisory ``WriteLock``. The MCP server
    already follows this model (per-request ephemeral connections).
    """

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
            self._conn = sqlite3.connect(uri, uri=True, timeout=self.timeout_ms / 1000.0)
        else:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, timeout=self.timeout_ms / 1000.0)
        self._owner_thread = threading.get_ident()

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

    @property
    def conn(self) -> sqlite3.Connection:
        """Underlying connection; enforces the single-thread contract.

        Raises an actionable error instead of sqlite3's cryptic
        "objects created in a thread" ProgrammingError when accessed from a
        foreign thread.
        """
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError(
                "sot_graph.Database is single-thread by design: this instance "
                f"was created in thread {self._owner_thread} but is being used "
                f"in thread {threading.get_ident()}. Fix: open one Database per "
                "thread (use read_only=True for readers); do not share instances."
            )
        return self._conn

    @conn.setter
    def conn(self, value: sqlite3.Connection) -> None:
        # Test seam: fault-injection scenarios swap the raw connection to
        # simulate I/O failures. Swapping also re-binds thread ownership.
        self._conn = value
        self._owner_thread = threading.get_ident()

    def _user_version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def _ensure_columns(self, table: str, columns: Dict[str, str]) -> None:
        """Additively backfill missing columns on a legacy/drifted table.

        Intermediate dev builds may carry an old shape under a newer
        user_version; CREATE TABLE IF NOT EXISTS then no-ops and any index
        or query touching the missing column would fail. Idempotent.
        """
        existing = {
            row[1]
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, ddl in columns.items():
            if name not in existing:
                self.conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"
                )

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

                    # Non-destructive upgrades from v4/v5/v6: provider tables
                    # were added in v5, snapshot binding in v6, and the v7
                    # ledger columns + project-binding table in v7; every
                    # step is purely additive (new tables / nullable
                    # columns), so no disposable-index reset or data loss
                    # occurs. All steps are idempotent, so a v6 database
                    # simply skips the already-applied shapes.
                    if version in (4, 5, 6, 7):
                        with self.conn:
                            self.conn.execute("""
                                CREATE TABLE IF NOT EXISTS provider_runs (
                                    id TEXT PRIMARY KEY,
                                    provider_name TEXT NOT NULL,
                                    provider_version TEXT,
                                    capability TEXT NOT NULL,
                                    snapshot_hash TEXT,
                                    project_root TEXT,
                                    position_encoding TEXT DEFAULT 'UTF-8',
                                    arguments_json TEXT,
                                    created_at INTEGER NOT NULL
                                );
                            """)
                            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_provider_runs_prov ON provider_runs(provider_name);")
                            self.conn.execute("""
                                CREATE TABLE IF NOT EXISTS provider_evidence (
                                    id TEXT PRIMARY KEY,
                                    run_id TEXT NOT NULL,
                                    provider_name TEXT,
                                    file_path TEXT,
                                    path TEXT NOT NULL,
                                    symbol TEXT,
                                    src_symbol TEXT NOT NULL,
                                    target_symbol TEXT,
                                    dst_symbol TEXT,
                                    role TEXT,
                                    relation TEXT NOT NULL,
                                    line_start INTEGER,
                                    line_end INTEGER,
                                    col_start INTEGER,
                                    col_end INTEGER,
                                    syntax_kind TEXT,
                                    documentation TEXT,
                                    confidence REAL DEFAULT 1.0,
                                    metadata_json TEXT,
                                    recorded_at INTEGER NOT NULL,
                                    created_at INTEGER NOT NULL,
                                    FOREIGN KEY(run_id) REFERENCES provider_runs(id) ON DELETE CASCADE
                                );
                            """)
                            # Drifted intermediate builds may carry an old
                            # provider_* shape under user_version 5; backfill
                            # any missing column before indexing it.
                            self._ensure_columns(
                                "provider_runs",
                                {
                                    "provider_version": "TEXT",
                                    "snapshot_hash": "TEXT",
                                    "project_root": "TEXT",
                                    "position_encoding": "TEXT DEFAULT 'UTF-8'",
                                    "arguments_json": "TEXT",
                                },
                            )
                            self._ensure_columns(
                                "provider_evidence",
                                {
                                    "provider_name": "TEXT",
                                    "file_path": "TEXT",
                                    "symbol": "TEXT",
                                    "target_symbol": "TEXT",
                                    "dst_symbol": "TEXT",
                                    "role": "TEXT",
                                    "syntax_kind": "TEXT",
                                    "documentation": "TEXT",
                                    "confidence": "REAL DEFAULT 1.0",
                                    "metadata_json": "TEXT",
                                    "recorded_at": "INTEGER NOT NULL DEFAULT 0",
                                },
                            )
                            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_p_evidence_run ON provider_evidence(run_id);")
                            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_p_evidence_prov ON provider_evidence(provider_name);")
                            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_p_evidence_path ON provider_evidence(path);")
                            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_p_evidence_src ON provider_evidence(src_symbol);")
                            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_p_evidence_dst ON provider_evidence(dst_symbol);")
                            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_p_evidence_sym ON provider_evidence(symbol);")
                        # v5 -> v6: snapshot binding. A new `snapshots` table
                        # plus a nullable `provider_runs.snapshot_id` column;
                        # existing rows stay NULL (= UNBOUND) and are never
                        # backfilled.
                        with self.conn:
                            self.conn.execute("""
                                CREATE TABLE IF NOT EXISTS snapshots (
                                    id TEXT PRIMARY KEY,
                                    repo_root TEXT NOT NULL,
                                    commit_sha TEXT,
                                    dirty INTEGER NOT NULL DEFAULT 0,
                                    dirty_fingerprint TEXT,
                                    manifest_digest TEXT,
                                    algo_version TEXT NOT NULL DEFAULT 'sha256-v1',
                                    generation INTEGER,
                                    captured_at INTEGER NOT NULL
                                );
                            """)
                            run_cols = [
                                r[1] for r in self.conn.execute(
                                    "PRAGMA table_info(provider_runs)"
                                ).fetchall()
                            ]
                            if "snapshot_id" not in run_cols:
                                self.conn.execute(
                                    "ALTER TABLE provider_runs ADD COLUMN "
                                    "snapshot_id TEXT REFERENCES snapshots(id)"
                                )
                            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                        # v6/v5 -> v7: snapshot-scoped ledger. New nullable
                        # run columns (status/exit_code/duration_ms/
                        # command_digest) and evidence column
                        # (snapshot_hash); plus the provider project
                        # identity-mapping table. Existing rows keep NULL
                        # for every new column; nothing is backfilled.
                        with self.conn:
                            self._ensure_columns(
                                "provider_runs",
                                {
                                    "status": "TEXT",
                                    "exit_code": "INTEGER",
                                    "duration_ms": "INTEGER",
                                    "command_digest": "TEXT",
                                },
                            )
                            self._ensure_columns(
                                "provider_evidence",
                                {"snapshot_hash": "TEXT"},
                            )
                            # P1.e: evidence invalidation marking — set, never
                            # deleted, so the ledger can distinguish pre/post
                            # change evidence for conflict adjudication.
                            self._ensure_columns(
                                "provider_evidence",
                                {
                                    "invalidated_at": "INTEGER",
                                    "invalidation_reason": "TEXT",
                                },
                            )
                            self.conn.execute("""
                                CREATE TABLE IF NOT EXISTS provider_project_bindings (
                                    id TEXT PRIMARY KEY,
                                    sot_repo_id TEXT NOT NULL,
                                    provider_name TEXT NOT NULL,
                                    provider_project_id TEXT NOT NULL,
                                    provider_generation INTEGER,
                                    head_sha TEXT,
                                    branch TEXT,
                                    updated_at INTEGER NOT NULL,
                                    UNIQUE(sot_repo_id, provider_name)
                                );
                            """)
                            self.conn.execute(
                                "CREATE INDEX IF NOT EXISTS idx_ppb_repo "
                                "ON provider_project_bindings(sot_repo_id);"
                            )
                            self.conn.execute(
                                "CREATE INDEX IF NOT EXISTS idx_p_evidence_snapshot "
                                "ON provider_evidence(snapshot_hash);"
                            )
                            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                        # v7 -> v8: parser outcome persistence on the file
                        # journal (P5.2). Two nullable columns; existing
                        # rows keep NULL (= parse outcome UNKNOWN).
                        with self.conn:
                            has_journal = bool(self.conn.execute(
                                "SELECT COUNT(*) FROM sqlite_master "
                                "WHERE type='table' AND name='file_journal'"
                            ).fetchone()[0])
                            if has_journal:
                                self._ensure_columns(
                                    "file_journal",
                                    {
                                        "parser_outcome": "TEXT",
                                        "parser_error": "TEXT",
                                    },
                                )
                            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                        return

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
        # P1.e: invalidation marking columns exist on every open, including
        # databases already at SCHEMA_VERSION before this feature shipped.
        try:
            self._ensure_columns(
                "provider_evidence",
                {"invalidated_at": "INTEGER", "invalidation_reason": "TEXT"},
            )
        except Exception:
            pass  # read-only connections degrade to no marking, not failure

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


    def stale_journal_files(self, paths, root: str | None = None) -> List[str]:
        """Paths whose disk state disagrees with the file journal (P1.c).

        Relative paths are resolved against ``root`` (the reconciler stores
        root-relative journal keys). A path is stale when size or mtime
        differ from the journal, or when they match but the content hash no
        longer does (mirrors the reconciler's scan semantics). Paths without
        a journal row are NOT reported stale (never indexed ≠ stale).
        """
        import hashlib as _hashlib

        stale: List[str] = []
        for raw in paths:
            if not raw:
                continue
            prior = self.get_file_journal(str(raw))
            if prior is None:
                continue
            candidate = str(raw)
            if not os.path.isabs(candidate) and root:
                candidate = os.path.join(root, candidate)
            try:
                stat = os.stat(candidate)
            except OSError:
                stale.append(str(raw))  # deleted since reconcile
                continue
            if int(stat.st_size) != prior.get("size") or int(stat.st_mtime * 1000) != prior.get("mtime_ms"):
                stale.append(str(raw))
                continue
            try:
                with open(candidate, "rb") as fh:
                    current_sha = _hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                stale.append(str(raw))
                continue
            if prior.get("sha256") != current_sha:
                stale.append(str(raw))
        return stale

    def mark_evidence_stale(self, paths, reason: str) -> int:
        """Flag provider_evidence rows touching changed paths (P1.e).

        Marks, never deletes: rows keep their original snapshot scope and
        gain ``invalidated_at`` + ``invalidation_reason`` so the ledger can
        separate pre-change from post-change evidence. Idempotent — rows
        already invalidated keep their first reason.
        """
        import time as _time

        candidates = [str(p).replace(os.sep, "/") for p in paths if p]
        if not candidates:
            return 0
        now = int(_time.time())
        marks: List[str] = []
        params: List[Any] = []
        for p in candidates:
            marks.append("(path = ? OR file_path = ?)")
            params.extend([p, p])
        where = " OR ".join(marks)
        with self.conn:
            cur = self.conn.execute(
                "UPDATE provider_evidence SET invalidated_at = ?, invalidation_reason = ? "
                f"WHERE invalidated_at IS NULL AND ({where})",
                [now, reason, *params],
            )
        return cur.rowcount or 0

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
        """Remove one file and all graph rows that depend on its nodes.

        Inbound references are retained as unresolved pending edges so a later
        reconcile can attach them to a moved/recreated definition.  The
        confirmed edge rows themselves are removed in the same transaction,
        including rows published by other source files.
        """
        with self.conn:
            deleted_ids = {
                row[0]
                for row in self.conn.execute(
                    "SELECT id FROM graph_nodes WHERE path = ?", (path,)
                ).fetchall()
            }
            if deleted_ids:
                marks = ",".join("?" for _ in deleted_ids)
                requeued = self.conn.execute(
                    "SELECT e.path, e.src, e.relation, e.line, "
                    "n.symbol, n.fqn, n.kind "
                    "FROM graph_edges e JOIN graph_nodes n ON e.dst = n.id "
                    f"WHERE n.path = ? AND e.path != ? AND e.src NOT IN ({marks})",
                    (path, path, *deleted_ids),
                ).fetchall()
                if requeued:
                    self.conn.executemany(
                        "INSERT INTO pending_edges "
                        "(path, src, dst_symbol, relation, line, call_kind, "
                        "import_source, resolution_state) VALUES (?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(path, src, dst_symbol, relation) DO UPDATE SET "
                        "line = COALESCE(pending_edges.line, excluded.line), "
                        "call_kind = excluded.call_kind, "
                        "import_source = excluded.import_source, "
                        "resolution_state = 'UNRESOLVED'",
                        [
                            (
                                e_path,
                                src,
                                self._requeue_symbol([symbol, fqn, kind]),
                                relation,
                                line,
                                "UNKNOWN",
                                self._requeue_import_source([symbol, fqn, kind]),
                                "UNRESOLVED",
                            )
                            for e_path, src, relation, line, symbol, fqn, kind
                            in requeued
                        ],
                    )
                self.conn.execute(
                    f"DELETE FROM graph_edges WHERE src IN ({marks}) OR dst IN ({marks})",
                    (*deleted_ids, *deleted_ids),
                )
                self.conn.execute(
                    f"DELETE FROM pending_edges WHERE src IN ({marks})",
                    tuple(deleted_ids),
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
        """Rehome a file and every identity reference in one transaction.

        Extracted node IDs contain a 12-character hash of the source path.
        A path move therefore requires more than changing ``graph_nodes.path``:
        all endpoint references, pending rows, and provider evidence must move
        to the new namespace together or the graph temporarily points at
        deleted IDs.
        """
        old_raw = os.fspath(old_path)
        new_raw = os.fspath(new_path)


        def path_variant_pairs(source: str, destination: str) -> Tuple[Tuple[str, str], ...]:
            """Return deterministic source/destination spelling pairs.

            A legacy index can hash either a relative, normalized, absolute,
            canonical, or slash-normalized path.  Build every corresponding
            pair before touching the database so later rewrites cannot change
            the set of source forms being considered.
            """
            source_raw = os.fspath(source)
            destination_raw = os.fspath(destination)
            source_candidates = (
                source_raw,
                os.path.normpath(source_raw),
                os.path.abspath(source_raw),
                os.path.realpath(source_raw),
            )
            destination_candidates = (
                destination_raw,
                os.path.normpath(destination_raw),
                os.path.abspath(destination_raw),
                os.path.realpath(destination_raw),
            )
            pairs: List[Tuple[str, str]] = []
            for source_candidate, destination_candidate in zip(
                source_candidates, destination_candidates
            ):
                pairs.append((source_candidate, destination_candidate))
                pairs.append((
                    source_candidate.replace(os.sep, "/"),
                    destination_candidate.replace(os.sep, "/"),
                ))
            return tuple(pairs)

        path_pairs = path_variant_pairs(old_raw, new_raw)
        old_forms = {source for source, _ in path_pairs if source}
        namespace_targets: Dict[str, str] = {}
        for old_candidate, new_candidate in path_pairs:
            old_namespace = hashlib.sha256(old_candidate.encode("utf-8")).hexdigest()[:12]
            new_namespace = hashlib.sha256(new_candidate.encode("utf-8")).hexdigest()[:12]
            # Duplicate source spellings (for example raw == normpath) must
            # keep their first deterministic destination instead of being
            # overwritten by a later, differently spelled alias.
            namespace_targets.setdefault(old_namespace, new_namespace)

        namespace_rules: Tuple[Tuple[str, str], ...] = tuple(
            sorted(
                (
                    (f"{prefix}{old_namespace}", f"{prefix}{new_namespace}")
                    for old_namespace, new_namespace in namespace_targets.items()
                    for prefix in ("file:", "sym:")
                ),
                key=lambda pair: (-len(pair[0]), pair[0]),
            )
        )

        path_targets: Dict[str, str] = {}
        for source, _ in path_pairs:
            if source:
                path_targets.setdefault(source, new_raw)
        path_pattern = re.compile(
            "|".join(
                re.escape(source)
                for source in sorted(path_targets, key=lambda item: (-len(item), item))
            )
        )

        def remap_id(value: Any) -> Any:
            if not isinstance(value, str) or not value:
                return value
            for token, replacement in namespace_rules:
                if value == token:
                    return replacement
                if value.startswith(token + ":"):
                    return replacement + value[len(token):]
            # Very old indexes used the path itself as the node namespace.
            for old_form in sorted(old_forms, key=lambda item: (-len(item), item)):
                for prefix, replacement_prefix in (
                    ("", new_raw),
                    ("file:", f"file:{new_raw}"),
                    ("sym:", f"sym:{new_raw}"),
                ):
                    token = prefix + old_form
                    if value == token:
                        return replacement_prefix
                    for separator in (":", "|", "#"):
                        if value.startswith(token + separator):
                            return replacement_prefix + value[len(token):]
            return value

        def rewrite_path(value: Any) -> Any:
            if isinstance(value, str):
                return path_targets.get(value, value)
            return value

        def rewrite_text(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            # A single regex pass matches only the original value.  Sequential
            # ``str.replace`` calls could feed ``new_raw`` into a shorter old
            # spelling and rewrite the newly generated destination again.
            return path_pattern.sub(
                lambda match: path_targets[match.group(0)],
                value,
            )

        def rewrite_reference(value: Any) -> Any:
            """Rewrite a stored ID/path once, always matching the source."""
            if not isinstance(value, str) or not value:
                return value
            return remap_id(rewrite_text(value))

        def rewrite_json(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            try:
                decoded = json.loads(value)
            except (TypeError, ValueError):
                return rewrite_text(value)

            def visit(item: Any) -> Any:
                if isinstance(item, str):
                    return rewrite_reference(item)
                if isinstance(item, list):
                    return [visit(entry) for entry in item]
                if isinstance(item, dict):
                    return {key: visit(entry) for key, entry in item.items()}
                return item

            rewritten = visit(decoded)
            if rewritten == decoded:
                return value
            return json.dumps(rewritten, ensure_ascii=False, separators=(",", ":"))

        old_form_values = tuple(sorted(old_forms))
        path_marks = ",".join("?" for _ in old_form_values)

        with self.conn:
            def distinct_paths(table: str, column: str) -> Set[str]:
                rows = self.conn.execute(
                    f"SELECT DISTINCT {column} FROM {table} "
                    f"WHERE {column} IN ({path_marks})",
                    old_form_values,
                ).fetchall()
                return {str(row[0]) for row in rows if row[0] is not None}

            stored_paths: Set[str] = set()
            for table, column in (
                ("file_journal", "path"),
                ("graph_nodes", "path"),
                ("graph_edges", "path"),
                ("pending_edges", "path"),
            ):
                stored_paths.update(distinct_paths(table, column))
            for table, column in (
                ("ui_navigation", "file_path"),
                ("ui_decision_nodes", "file_path"),
                ("be_execution_steps", "file_path"),
                ("api_cross_bindings", "fe_file"),
                ("api_cross_bindings", "be_file"),
                ("provider_evidence", "path"),
                ("provider_evidence", "file_path"),
            ):
                try:
                    stored_paths.update(distinct_paths(table, column))
                except sqlite3.OperationalError:
                    # Keep compatibility with a partially migrated legacy DB.
                    continue

            if not stored_paths:
                stored_paths.add(old_raw)
            if new_raw not in stored_paths:
                for table in ("file_journal", "graph_nodes"):
                    if self.conn.execute(
                        f"SELECT 1 FROM {table} WHERE path = ? LIMIT 1", (new_raw,)
                    ).fetchone():
                        raise ValueError(
                            f"cannot rehome {old_raw!r}: destination {new_raw!r} "
                            "already has indexed rows"
                        )

            node_rows = self.conn.execute(
                f"SELECT id, path, label, body FROM graph_nodes "
                f"WHERE path IN ({path_marks})",
                old_form_values,
            ).fetchall()
            all_node_ids = {
                str(row[0])
                for row in self.conn.execute("SELECT id FROM graph_nodes").fetchall()
            }

            edge_rows = self.conn.execute(
                "SELECT path, src, dst, relation, line FROM graph_edges"
            ).fetchall()
            affected_edges = [
                row
                for row in edge_rows
                if row[0] in stored_paths
                or remap_id(row[1]) != row[1]
                or remap_id(row[2]) != row[2]
            ]
            pending_rows = self.conn.execute(
                "SELECT path, src, dst_symbol, relation, line, language, "
                "call_kind, receiver, import_source, resolution_state "
                "FROM pending_edges"
            ).fetchall()
            affected_pending = [
                row
                for row in pending_rows
                if row[0] in stored_paths or remap_id(row[1]) != row[1]
            ]

            id_map: Dict[str, str] = {}
            for row in node_rows:
                old_id = str(row[0])
                new_id = str(remap_id(old_id))
                if new_id != old_id:
                    id_map[old_id] = new_id
            for row in affected_edges:
                for old_id in (str(row[1]), str(row[2])):
                    new_id = str(remap_id(old_id))
                    if new_id != old_id:
                        id_map.setdefault(old_id, new_id)
            for row in affected_pending:
                old_id = str(row[1])
                new_id = str(remap_id(old_id))
                if new_id != old_id:
                    id_map.setdefault(old_id, new_id)

            old_node_ids = {str(row[0]) for row in node_rows}
            mapped_ids = set(id_map.values())
            for mapped_id in mapped_ids:
                if mapped_id in all_node_ids and mapped_id not in old_node_ids:
                    raise ValueError(
                        f"cannot rehome {old_raw!r}: destination node ID "
                        f"{mapped_id!r} already exists"
                    )
            if len(mapped_ids) != len(id_map):
                raise ValueError(
                    f"cannot rehome {old_raw!r}: node namespace mapping collides"
                )

            # Remove affected keys before changing their path/endpoint values;
            # INSERT OR IGNORE below performs schema-level deduplication.
            if affected_edges:
                self.conn.executemany(
                    "DELETE FROM graph_edges WHERE path = ? AND src = ? "
                    "AND dst = ? AND relation = ?",
                    [(row[0], row[1], row[2], row[3]) for row in affected_edges],
                )
            if affected_pending:
                self.conn.executemany(
                    "DELETE FROM pending_edges WHERE path = ? AND src = ? "
                    "AND dst_symbol = ? AND relation = ?",
                    [(row[0], row[1], row[2], row[3]) for row in affected_pending],
                )

            journal_paths = distinct_paths("file_journal", "path")
            if len(journal_paths) > 1:
                raise ValueError(
                    f"cannot rehome {old_raw!r}: multiple journal aliases exist"
                )
            if journal_paths:
                journal_path = next(iter(journal_paths))
                if (
                    new_sha256 is not None
                    and new_size is not None
                    and new_mtime_ms is not None
                ):
                    self.conn.execute(
                        "UPDATE file_journal SET path = ?, sha256 = ?, size = ?, "
                        "mtime_ms = ?, generation = generation + 1, reconciled_at = ? "
                        "WHERE path = ?",
                        (
                            new_raw,
                            new_sha256,
                            new_size,
                            new_mtime_ms,
                            int(time.time()),
                            journal_path,
                        ),
                    )
                else:
                    self.conn.execute(
                        "UPDATE file_journal SET path = ?, generation = generation + 1, "
                        "reconciled_at = ? WHERE path = ?",
                        (new_raw, int(time.time()), journal_path),
                    )

            # Temporarily free old primary keys, then publish the final IDs
            # after path/label/body updates.  References are reinserted below.
            temp_ids: Dict[str, str] = {
                old_id: f"__sot_rehome__{uuid.uuid4().hex}"
                for old_id in id_map
                if old_id in all_node_ids
            }
            for old_id, temp_id in temp_ids.items():
                self.conn.execute(
                    "UPDATE graph_nodes SET id = ? WHERE id = ?",
                    (temp_id, old_id),
                )

            now = int(time.time())
            for old_id, path_value, label, body in node_rows:
                current_id = temp_ids.get(str(old_id), str(old_id))
                final_id = id_map.get(str(old_id), str(old_id))
                self.conn.execute(
                    "UPDATE graph_nodes SET id = ?, path = ?, label = ?, body = ?, "
                    "updated_at = ? WHERE id = ?",
                    (
                        final_id,
                        new_raw,
                        rewrite_text(label),
                        rewrite_text(body),
                        now,
                        current_id,
                    ),
                )

            if affected_edges:
                self.conn.executemany(
                    "INSERT OR IGNORE INTO graph_edges(path, src, dst, relation, line) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [
                        (
                            rewrite_path(row[0]),
                            remap_id(row[1]),
                            remap_id(row[2]),
                            row[3],
                            row[4],
                        )
                        for row in affected_edges
                    ],
                )
            if affected_pending:
                self.conn.executemany(
                    "INSERT OR IGNORE INTO pending_edges "
                    "(path, src, dst_symbol, relation, line, language, call_kind, "
                    "receiver, import_source, resolution_state) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            rewrite_path(row[0]),
                            remap_id(row[1]),
                            row[2],
                            row[3],
                            row[4],
                            row[5],
                            row[6],
                            row[7],
                            rewrite_text(row[8]),
                            row[9],
                        )
                        for row in affected_pending
                    ],
                )

            for table, column in (
                ("ui_navigation", "file_path"),
                ("ui_decision_nodes", "file_path"),
                ("be_execution_steps", "file_path"),
                ("api_cross_bindings", "fe_file"),
                ("api_cross_bindings", "be_file"),
                ("provider_evidence", "path"),
                ("provider_evidence", "file_path"),
            ):
                try:
                    self.conn.execute(
                        f"UPDATE {table} SET {column} = ? "
                        f"WHERE {column} IN ({path_marks})",
                        (new_raw, *old_form_values),
                    )
                except sqlite3.OperationalError:
                    continue

            try:
                evidence_rows = self.conn.execute(
                    "SELECT id, symbol, src_symbol, target_symbol, dst_symbol, "
                    "metadata_json FROM provider_evidence"
                ).fetchall()
                for evidence_id, symbol, src_symbol, target_symbol, dst_symbol, metadata in evidence_rows:
                    values = {
                        "symbol": rewrite_reference(symbol),
                        "src_symbol": rewrite_reference(src_symbol),
                        "target_symbol": rewrite_reference(target_symbol),
                        "dst_symbol": rewrite_reference(dst_symbol),
                        "metadata_json": rewrite_json(metadata),
                    }
                    if any(
                        values[column] != original
                        for column, original in (
                            ("symbol", symbol),
                            ("src_symbol", src_symbol),
                            ("target_symbol", target_symbol),
                            ("dst_symbol", dst_symbol),
                            ("metadata_json", metadata),
                        )
                    ):
                        self.conn.execute(
                            "UPDATE provider_evidence SET symbol = ?, src_symbol = ?, "
                            "target_symbol = ?, dst_symbol = ?, metadata_json = ? "
                            "WHERE id = ?",
                            (
                                values["symbol"],
                                values["src_symbol"],
                                values["target_symbol"],
                                values["dst_symbol"],
                                values["metadata_json"],
                                evidence_id,
                            ),
                        )
            except sqlite3.OperationalError:
                pass

            try:
                community_rows = self.conn.execute(
                    "SELECT community_id, nodes_json FROM graph_communities"
                ).fetchall()
                for community_id, nodes_json in community_rows:
                    rewritten = rewrite_json(nodes_json)
                    if rewritten != nodes_json:
                        self.conn.execute(
                            "UPDATE graph_communities SET nodes_json = ? "
                            "WHERE community_id = ?",
                            (rewritten, community_id),
                        )
            except sqlite3.OperationalError:
                pass
        return True

    def update_node_path(self, node_id: str, old_path: str, new_path: str) -> None:
        self.rehome_file_atomically(old_path, new_path)
    @staticmethod
    def _record_value(record: Any, name: str) -> Any:
        if isinstance(record, Mapping):
            return record.get(name)
        return getattr(record, name, None)

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
                parser_outcome = self._record_value(record, "parser_outcome")
                parser_error = self._record_value(record, "parser_error")
                self.conn.execute(
                    "INSERT INTO file_journal "
                    "(path,sha256,size,mtime_ms,generation,reconciled_at,parser_outcome,parser_error) "
                    "VALUES (?,?,?,?,1,?,?,?) "
                    "ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256,size=excluded.size, "
                    "mtime_ms=excluded.mtime_ms,generation=generation+1,reconciled_at=excluded.reconciled_at,"
                    "parser_outcome=excluded.parser_outcome,parser_error=excluded.parser_error",
                    (path, sha, size, mtime_ms, now, parser_outcome, parser_error),
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
        caller_imports_cache: Dict[str, Set[str]] = {}

        def path_module_names(path: str) -> Set[str]:
            names = module_cache.get(path)
            if names is None:
                names = project_module_names([path])
                module_cache[path] = names
            return names

        def caller_imported_modules(caller_path: str) -> Set[str]:
            """Project modules imported by a file, from resolved + pending import edges.

            Used to disambiguate legacy pending calls parked without
            ``import_source`` (e.g. Tree-Sitter languages indexed before
            import provenance was attached at extraction time).
            """
            cached = caller_imports_cache.get(caller_path)
            if cached is not None:
                return cached
            modules: Set[str] = set()
            for (dst_id,) in self.conn.execute(
                "SELECT dst FROM graph_edges WHERE relation = 'imports' AND path = ?",
                (caller_path,),
            ):
                dst_row = self.conn.execute(
                    "SELECT path FROM graph_nodes WHERE id = ?", (dst_id,)
                ).fetchone()
                if dst_row:
                    modules |= path_module_names(dst_row[0])
            for (mod_src,) in self.conn.execute(
                "SELECT DISTINCT import_source FROM pending_edges "
                "WHERE relation = 'imports' AND path = ? AND import_source IS NOT NULL",
                (caller_path,),
            ):
                mod_imp = normalize_import(mod_src)
                if mod_imp and mod_imp in project_names:
                    modules.add(mod_imp)
            caller_imports_cache[caller_path] = modules
            return modules


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
            # Priority 3b: Caller-file import fallback for legacy edges parked
            # without import_source. Filters multiple candidates by the
            # modules the calling file itself imports; only resolves when the
            # filter narrows to exactly one candidate.
            if chosen is None and not imp and len(candidates) > 1:
                caller_modules = caller_imported_modules(path)
                if caller_modules:
                    matched = [
                        (node_id, node_path) for node_id, node_path in candidates
                        if any(
                            m in path_module_names(node_path)
                            or any(pm.startswith(m) for pm in path_module_names(node_path))
                            for m in caller_modules
                        )
                    ]
                    if len(matched) == 1:
                        chosen = matched[0]
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
            # LIKE wildcard escaping: a user scope of '%' or '_' must
            # match literally, never open the filter to every row.
            esc = scope.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            sql += " AND (k.path LIKE ? ESCAPE '\\' OR k.body LIKE ? ESCAPE '\\')"
            params.extend([f"%{esc}%", f"%{esc}%"])
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

    def provider_evidence_counts(self, paths: Sequence[str]) -> Dict[Tuple[str, str], int]:
        """Batch count live (non-invalidated) provider evidence rows per
        (path, symbol) — one query for the whole result page, feeding the
        P4 ranking's provider-evidence factor. Empty input -> empty map.
        """
        paths = [p for p in dict.fromkeys(paths) if p]
        if not paths:
            return {}
        placeholders = ",".join("?" * len(paths))
        rows = self.conn.execute(
            f"SELECT file_path, symbol, COUNT(*) FROM provider_evidence "
            f"WHERE invalidated_at IS NULL AND file_path IN ({placeholders}) "
            f"GROUP BY file_path, symbol",
            paths,
        ).fetchall()
        return {(r[0], r[1] or ""): int(r[2]) for r in rows}

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
                "SELECT p.src, n.label, n.path, p.dst_symbol, p.resolution_state "
                "FROM pending_edges p JOIN graph_nodes n ON p.src = n.id "
                "WHERE p.src = ? AND p.relation IN ('extends', 'implements') "
                "AND p.resolution_state != 'RESOLVED' ORDER BY n.path",
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
    def record_provider_run(
        self,
        provider_name: str,
        provider_version: Optional[str] = None,
        capability: str = "COMPILER_INDEXED_SYMBOLS",
        snapshot_hash: Optional[str] = None,
        project_root: Optional[str] = None,
        position_encoding: str = "UTF-8",
        arguments_json: Optional[str] = None,
        run_id: Optional[str] = None,
        status: Optional[str] = None,
        exit_code: Optional[int] = None,
        duration_ms: Optional[int] = None,
        command_digest: Optional[str] = None,
        snapshot_id: Optional[str] = None,
    ) -> str:
        """Persist one provider invocation (v7 snapshot-scoped ledger).

        The whole INSERT runs in a single implicit transaction; a failure
        anywhere before commit leaves ``provider_runs`` untouched.
        """
        import uuid
        rid = run_id or f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        now = int(time.time())
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO provider_runs "
                "(id, provider_name, provider_version, capability, snapshot_hash, "
                "project_root, position_encoding, arguments_json, status, exit_code, "
                "duration_ms, command_digest, created_at, snapshot_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rid,
                    provider_name,
                    provider_version,
                    capability,
                    snapshot_hash,
                    project_root,
                    position_encoding,
                    arguments_json,
                    status,
                    exit_code,
                    duration_ms,
                    command_digest,
                    now,
                    snapshot_id,
                ),
            )
        return rid

    def record_provider_binding(
        self,
        sot_repo_id: str,
        provider_name: str,
        provider_project_id: str,
        *,
        provider_generation: Optional[int] = None,
        head_sha: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> str:
        """Upsert the identity mapping repo -> provider -> project (v7).

        One row per ``(sot_repo_id, provider_name)``: re-binding the same
        pair updates head_sha/branch/generation in place instead of
        duplicating rows. Returns the row id.
        """
        import uuid
        now = int(time.time())
        with self.conn:
            existing = self.conn.execute(
                "SELECT id FROM provider_project_bindings "
                "WHERE sot_repo_id = ? AND provider_name = ?",
                (sot_repo_id, provider_name),
            ).fetchone()
            if existing is not None:
                bid = existing[0]
                self.conn.execute(
                    "UPDATE provider_project_bindings SET provider_project_id = ?, "
                    "provider_generation = ?, head_sha = ?, branch = ?, updated_at = ? "
                    "WHERE id = ?",
                    (provider_project_id, provider_generation, head_sha, branch,
                     now, bid),
                )
            else:
                bid = f"bind_{now}_{uuid.uuid4().hex[:8]}"
                self.conn.execute(
                    "INSERT INTO provider_project_bindings "
                    "(id, sot_repo_id, provider_name, provider_project_id, "
                    "provider_generation, head_sha, branch, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (bid, sot_repo_id, provider_name, provider_project_id,
                     provider_generation, head_sha, branch, now),
                )
        return bid

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single node by its unique id."""
        row = self.conn.execute(
            "SELECT id, path, kind, symbol, fqn, signature, label, body, keywords, "
            "line_start, line_end, col_start, col_end, updated_at "
            "FROM graph_nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "path": row[1], "kind": row[2], "symbol": row[3],
            "fqn": row[4], "signature": row[5], "label": row[6], "body": row[7],
            "keywords": row[8], "line_start": row[9], "line_end": row[10],
            "col_start": row[11], "col_end": row[12], "updated_at": row[13]
        }

    def record_provider_evidence(
        self,
        run_id: str,
        evidence_items: Sequence[Dict[str, Any]],
    ) -> int:
        """Batch insert provider evidence items."""
        if not evidence_items:
            return 0
        now = int(time.time())
        import uuid
        # Lookup provider_name from run_id if available
        p_row = self.conn.execute("SELECT provider_name FROM provider_runs WHERE id = ?", (run_id,)).fetchone()
        p_name = p_row[0] if p_row else "unknown"

        rows = []
        for item in evidence_items:
            eid = item.get("id") or f"ev_{uuid.uuid4().hex}"
            path = item.get("path") or item.get("file_path", "")
            # P3.2: canonical identity in src/dst, wire bare name in the
            # symbol/target alias columns so both lookup shapes work.
            src_symbol = item.get("src_symbol") or item.get("symbol", "")
            dst_symbol = item.get("dst_symbol") or item.get("target_symbol")
            bare_src = item.get("symbol") or src_symbol
            bare_dst = item.get("target_symbol") or dst_symbol
            relation = item.get("relation") or item.get("role", "reference")
            line_start = item.get("line_start")
            line_end = item.get("line_end")
            col_start = item.get("col_start")
            col_end = item.get("col_end")
            syntax_kind = item.get("syntax_kind")
            documentation = item.get("documentation")
            confidence = float(item.get("confidence", 1.0))
            prov_name = item.get("provider_name") or p_name
            meta = item.get("metadata_json")
            if meta is not None and not isinstance(meta, str):
                meta = json.dumps(meta)
            snap = item.get("snapshot_hash")
            rows.append((
                eid, run_id, prov_name, path, path, bare_src, src_symbol,
                bare_dst, dst_symbol, relation, relation,
                line_start, line_end, col_start, col_end,
                syntax_kind, documentation, confidence, meta, snap, now, now
            ))
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO provider_evidence "
                "(id, run_id, provider_name, file_path, path, symbol, src_symbol, target_symbol, dst_symbol, role, relation, line_start, line_end, col_start, col_end, syntax_kind, documentation, confidence, metadata_json, snapshot_hash, recorded_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    insert_provider_evidence = record_provider_evidence

    def get_provider_runs(self) -> List[Dict[str, Any]]:
        """Retrieve all recorded provider runs."""
        rows = self.conn.execute(
            "SELECT id, provider_name, provider_version, capability, snapshot_hash, "
            "project_root, position_encoding, arguments_json, status, exit_code, "
            "duration_ms, command_digest, created_at, snapshot_id "
            "FROM provider_runs ORDER BY created_at DESC"
        ).fetchall()
        return [
            {
                "id": r[0],
                "provider_name": r[1],
                "provider_version": r[2],
                "capability": r[3],
                "snapshot_hash": r[4],
                "project_root": r[5],
                "position_encoding": r[6],
                "arguments_json": r[7],
                "status": r[8],
                "exit_code": r[9],
                "duration_ms": r[10],
                "command_digest": r[11],
                "created_at": r[12],
                "snapshot_id": r[13],
            }
            for r in rows
        ]
    def get_active_providers(self) -> List[Dict[str, str]]:
        """List distinct active providers from provider_runs or default heuristic."""
        try:
            rows = self.conn.execute(
                "SELECT DISTINCT provider_name, provider_version, capability FROM provider_runs"
            ).fetchall()
            if rows:
                return [
                    {
                        "name": r[0],
                        "version": r[1] or "unknown",
                        "capability": r[2] or "UNKNOWN",
                    }
                    for r in rows
                ]
        except Exception:
            pass
        default_name = "tree-sitter-ast"
        default_ver = "unknown"
        try:
            import importlib.metadata
            default_ver = importlib.metadata.version("tree_sitter")
        except Exception:
            try:
                import tree_sitter
                default_ver = getattr(tree_sitter, "__version__", None) or f"{sys.version_info.major}.{sys.version_info.minor}"
            except Exception:
                default_name = "core-ast"
                default_ver = f"python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        return [
            {
                "name": default_name,
                "version": default_ver,
                "capability": "AST_HEURISTIC_PARSER",
            }
        ]

    def get_provider_evidence(
        self,
        run_id: Optional[str] = None,
        provider_name: Optional[str] = None,
        path: Optional[str] = None,
        file_path: Optional[str] = None,
        symbol: Optional[str] = None,
        role: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Query recorded provider evidence with optional filters."""
        query = (
            "SELECT id, run_id, provider_name, file_path, path, symbol, src_symbol, "
            "target_symbol, dst_symbol, role, relation, line_start, line_end, "
            "col_start, col_end, syntax_kind, documentation, confidence, metadata_json, "
            "recorded_at, created_at "
            "FROM provider_evidence WHERE 1=1"
        )
        params: List[Any] = []
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        if provider_name:
            query += " AND (provider_name = ? OR run_id IN (SELECT id FROM provider_runs WHERE provider_name = ?))"
            params.extend([provider_name, provider_name])
        target_path = path or file_path
        if target_path:
            query += " AND (path = ? OR file_path = ?)"
            params.extend([target_path, target_path])
        if symbol:
            query += " AND (src_symbol = ? OR dst_symbol = ? OR symbol = ? OR target_symbol = ?)"
            params.extend([symbol, symbol, symbol, symbol])
        if role:
            query += " AND (role = ? OR relation = ?)"
            params.extend([role, role])
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, tuple(params)).fetchall()
        return [
            {
                "id": r[0],
                "run_id": r[1],
                "provider_name": r[2],
                "file_path": r[3] or r[4],
                "path": r[4] or r[3],
                "symbol": r[5] or r[6],
                "src_symbol": r[6] or r[5],
                "target_symbol": r[7] or r[8],
                "dst_symbol": r[8] or r[7],
                "role": r[9] or r[10],
                "relation": r[10] or r[9],
                "line_start": r[11],
                "line_end": r[12],
                "col_start": r[13],
                "col_end": r[14],
                "syntax_kind": r[15],
                "documentation": r[16],
                "confidence": r[17],
                "metadata_json": r[18],
                "recorded_at": r[19] or r[20],
                "created_at": r[20] or r[19],
            }
            for r in rows
        ]

    def get_symbol_evidence(self, symbol: str) -> List[Dict[str, Any]]:
        """Retrieve all recorded provider evidence for a specific symbol."""
        return self.get_provider_evidence(symbol=symbol)
    def purge_provider_run(self, run_id: str) -> int:
        """Purge a provider run and cascade delete all associated evidence."""
        with self.conn:
            ev_count = self.conn.execute(
                "SELECT COUNT(*) FROM provider_evidence WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            self.conn.execute("DELETE FROM provider_evidence WHERE run_id = ?", (run_id,))
            self.conn.execute("DELETE FROM provider_runs WHERE id = ?", (run_id,))
        return int(ev_count)
