"""
sot_graph.snapshot — Git worktree snapshot binding (schema v6).

Captures a verifiable binding between knowledge-graph evidence and the exact
repository state it was produced from: the HEAD commit, the dirty flag, and a
deterministic fingerprint of every uncommitted change (staged, unstaged, and
untracked). All git access is read-only, shell-free (argv list), and bounded
by a hard subprocess timeout.
"""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import time
import uuid

GIT_TIMEOUT_SECONDS = 30


def _run_git(repo_root: str, *args: str) -> subprocess.CompletedProcess | None:
    """Run a read-only git command in ``repo_root``; None on any failure."""
    try:
        return subprocess.run(
            ["git", "-C", repo_root, *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def _status_entries(repo_root: str) -> list[str] | None:
    """Porcelain-v1 status entries (NUL-delimited), or None outside a git repo.

    Rename/copy records carry a second NUL-terminated path; it is folded into
    the same entry so each worktree change maps to exactly one list element.
    """
    proc = _run_git(repo_root, "status", "--porcelain=v1", "-z")
    if proc is None or proc.returncode != 0:
        return None
    fields = proc.stdout.split("\0")
    entries: list[str] = []
    i = 0
    while i < len(fields):
        record = fields[i]
        i += 1
        if not record:
            continue
        if len(record) >= 2 and ("R" in record[:2] or "C" in record[:2]) and i < len(fields):
            entries.append(f"{record}\0{fields[i]}")
            i += 1
        else:
            entries.append(record)
    return entries


def get_head_sha(repo_root: str) -> str | None:
    """Full SHA of HEAD; None outside a git repo or before the first commit."""
    proc = _run_git(repo_root, "rev-parse", "HEAD")
    if proc is None or proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def is_dirty(repo_root: str) -> bool:
    """True when the worktree has any staged, unstaged, or untracked change."""
    entries = _status_entries(repo_root)
    return entries is not None and len(entries) > 0


def compute_dirty_fingerprint(repo_root: str) -> str | None:
    """Deterministic sha256 over all uncommitted changes.

    Entries are sorted before hashing so the fingerprint is stable regardless
    of git's listing order. Returns None when ``repo_root`` is not a git repo.
    """
    entries = _status_entries(repo_root)
    if entries is None:
        return None
    hasher = hashlib.sha256()
    for entry in sorted(entries):
        hasher.update(entry.encode("utf-8"))
        hasher.update(b"\x00")
    return f"sha256:{hasher.hexdigest()}"


def bind_snapshot(conn: sqlite3.Connection, repo_root: str) -> str:
    """Insert one snapshot row describing ``repo_root`` and return its id.

    Populates every column of ``snapshots``: HEAD sha, dirty flag, dirty
    fingerprint, plus the journal-derived manifest digest and generation
    (reusing the envelope helpers so CLI/MCP and bindings agree on semantics).
    The caller owns the surrounding transaction. Old provider_runs rows keep
    ``snapshot_id IS NULL`` (= UNBOUND); nothing is backfilled here.
    """
    from sot_graph.envelope import compute_manifest_digest, compute_snapshot_generation

    now = int(time.time())
    snapshot_id = f"snap_{now}_{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO snapshots "
        "(id, repo_root, commit_sha, dirty, dirty_fingerprint, manifest_digest, "
        "algo_version, generation, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            snapshot_id,
            repo_root,
            get_head_sha(repo_root),
            int(is_dirty(repo_root)),
            compute_dirty_fingerprint(repo_root),
            compute_manifest_digest(conn),
            "sha256-v1",
            compute_snapshot_generation(conn),
            now,
        ),
    )
    return snapshot_id
