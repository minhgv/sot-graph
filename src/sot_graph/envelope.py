"""
sot_graph.envelope — North-Star Versioned Response Envelope for CLI and MCP.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Optional, Union


RESPONSE_SCHEMA_VERSION = "2.0.0"


def compute_manifest_digest(db: Any) -> str:
    """Compute deterministic sha256 digest of tracked files in file_journal."""
    try:
        conn = getattr(db, "conn", None) or db
        if not isinstance(conn, sqlite3.Connection):
            return "sha256:empty"
        rows = conn.execute(
            "SELECT path, sha256 FROM file_journal ORDER BY path ASC"
        ).fetchall()
        if not rows:
            return "sha256:empty"
        hasher = hashlib.sha256()
        for p, s in rows:
            hasher.update(f"{p}:{s}\n".encode("utf-8"))
        return f"sha256:{hasher.hexdigest()}"
    except Exception:
        return "sha256:unknown"


def compute_snapshot_generation(db: Any) -> int:
    """Extract max snapshot generation from file_journal."""
    try:
        conn = getattr(db, "conn", None) or db
        if not isinstance(conn, sqlite3.Connection):
            return 1
        row = conn.execute("SELECT MAX(generation) FROM file_journal").fetchone()
        if row and row[0] is not None:
            return int(row[0])
        return 1
    except Exception:
        return 1


def get_active_providers(db: Any) -> List[Dict[str, str]]:
    """Retrieve active providers from provider_runs or default heuristic providers."""
    try:
        if hasattr(db, "get_active_providers"):
            providers = db.get_active_providers()
            if providers:
                return providers
        conn = getattr(db, "conn", None) or db
        if isinstance(conn, sqlite3.Connection):
            has_runs = bool(conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='provider_runs'"
            ).fetchone()[0])
            if has_runs:
                rows = conn.execute(
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
            import sys
            default_ver = getattr(tree_sitter, "__version__", None) or f"{sys.version_info.major}.{sys.version_info.minor}"
        except Exception:
            import sys
            default_name = "core-ast"
            default_ver = f"python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return [
        {
            "name": default_name,
            "version": default_ver,
            "capability": "AST_HEURISTIC_PARSER",
        }
    ]


def wrap_envelope(
    data: Any,
    db: Any = None,
    project_root: Optional[str] = None,
    completeness: str = "COMPLETE_WITHIN_INDEX_CAPABILITY",
    fallbacks_applied: Optional[List[str]] = None,
    conflicts_detected: Optional[List[str]] = None,
    generation: Optional[int] = None,
    manifest_digest: Optional[str] = None,
    providers: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Wrap output in the standard North-Star response envelope.
    
    Guarantees consistent metadata:
    - schema_version
    - snapshot_generation
    - manifest_digest
    - completeness
    - providers
    - fallbacks_applied
    - conflicts_detected
    - data
    """
    snap_gen = generation if generation is not None else compute_snapshot_generation(db)
    digest = manifest_digest if manifest_digest is not None else compute_manifest_digest(db)
    provs = providers if providers is not None else get_active_providers(db)

    # Normalize completeness - never allow GLOBAL_COMPLETE
    if completeness == "GLOBAL_COMPLETE" or completeness == "COMPLETE":
        completeness = "COMPLETE_WITHIN_INDEX_CAPABILITY"

    envelope: Dict[str, Any] = {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "snapshot_generation": snap_gen,
        "manifest_digest": digest,
        "completeness": completeness,
        "providers": provs,
        "fallbacks_applied": fallbacks_applied or [],
        "conflicts_detected": conflicts_detected or [],
        "data": data,
    }

    # Seamless backward compatibility: expose top-level keys if data is a dict
    if isinstance(data, dict):
        for k, v in data.items():
            if k not in envelope:
                envelope[k] = v

    return envelope
