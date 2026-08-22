"""
sot_graph.reconciler — Level-triggered Single-Writer Reconciler.
Idempotently reconciles the SQLite knowledge graph with filesystem reality using SHA-256 content hashes.
Provides file scanning, batch reconciliation, and deep drift audit.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from sot_graph.db import Database
from sot_graph.extractor import EXT_DISPATCH, parse_file_graph

IGNORED_DIRS: Set[str] = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    "target", ".cache", ".idea", ".vscode", "coverage", ".next", ".turbo",
}


class Reconciler:
    def __init__(self, db: Database, root_dir: str):
        self.db = db
        self.root_dir = os.path.abspath(root_dir)

    def reconcile_path(self, path: str) -> str:
        """
        Reconciles a single path against the database.
        Returns one of: 'indexed', 'unchanged', 'deleted', 'error'.
        """
        abs_path = os.path.abspath(path)

        # 1. File was deleted or is not a regular file
        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            self.db.delete_path(abs_path)
            return "deleted"

        # 2. Check if file is dirty via size/mtime and SHA-256
        st = os.stat(abs_path)
        mtime_ms = int(st.st_mtime * 1000)
        size = st.st_size

        prior = self.db.get_file_journal(abs_path)

        # Quick check: parse file AST and compute SHA-256
        parsed = parse_file_graph(abs_path, self.root_dir)
        if parsed.get("error") and not parsed.get("nodes"):
            return "error"

        sha = parsed["sha256"]

        # If hash matches prior recorded journal, skip re-indexing (idempotent fast path)
        if prior and prior["sha256"] == sha:
            return "unchanged"

        # 3. Commit new nodes and edges atomically
        new_symbols = [n["symbol"] for n in parsed["nodes"] if n.get("symbol")]
        self.db.commit_file(
            path=abs_path,
            sha256=sha,
            size=size,
            mtime_ms=mtime_ms,
            nodes=parsed["nodes"],
            edges=parsed["edges"],
            pending=parsed["pending"],
        )

        # 4. Resolve 2-way pending cross-file edges
        self.db.resolve_pending_edges(new_symbols, current_file_path=abs_path)
        return "indexed"

    def scan_and_reconcile(self) -> Dict[str, int]:
        """
        Recursively scans root_dir, reconciles all known and new files,
        and purges records for files that no longer exist on disk.
        """
        stats = {"indexed": 0, "unchanged": 0, "deleted": 0, "error": 0}
        known_paths = set(self.db.all_journal_paths())
        current_disk_paths = set()

        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for f in files:
                ext = Path(f).suffix.lower()
                # Index files with known extensions or common text documents (.md, .txt, .json, .yaml, .toml)
                if ext in EXT_DISPATCH or ext in {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".sh", ".sql"}:
                    p = os.path.abspath(os.path.join(root, f))
                    current_disk_paths.add(p)
                    action = self.reconcile_path(p)
                    stats[action] = stats.get(action, 0) + 1

        # Purge records for files that disappeared from disk
        for dead_path in known_paths - current_disk_paths:
            self.db.delete_path(dead_path)
            stats["deleted"] += 1

        return stats

    def audit_drift(self, deep: bool = False) -> List[Dict[str, str]]:
        """
        Read-only comparison of journaled records against the filesystem.
        Returns a list of drifted items: [{ 'path': ..., 'why': 'missing'|'mtime_size'|'hash' }].
        Safe to run in CI pipelines.
        """
        drift = []
        for path in self.db.all_journal_paths():
            if not os.path.exists(path) or not os.path.isfile(path):
                drift.append({"path": path, "why": "missing"})
                continue

            st = os.stat(path)
            prior = self.db.get_file_journal(path)
            if not prior:
                drift.append({"path": path, "why": "unrecorded"})
                continue

            if deep:
                import hashlib
                try:
                    with open(path, "rb") as f:
                        current_sha = hashlib.sha256(f.read()).hexdigest()
                    if current_sha != prior["sha256"]:
                        drift.append({"path": path, "why": "hash_mismatch"})
                except Exception:
                    drift.append({"path": path, "why": "unreadable"})
            else:
                if st.st_size != prior["size"] or int(st.st_mtime * 1000) != prior["mtime_ms"]:
                    drift.append({"path": path, "why": "mtime_size_mismatch"})

        return drift
