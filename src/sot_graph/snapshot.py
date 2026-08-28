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
import os
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass, field, replace
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


def dirty_state(repo_root: str) -> tuple[bool | None, str | None]:
    """Tri-state worktree dirtiness with a content fingerprint.

    Returns ``(dirty, fingerprint)``. ``dirty`` is None when git status
    itself failed (unverifiable — callers must treat that as NOT clean),
    False for a clean tree, True for any staged/unstaged/untracked change.
    The fingerprint is a deterministic sha256 over the sorted status
    entries (None only when git failed or the tree is clean).
    """
    entries = _status_entries(repo_root)
    if entries is None:
        return None, None
    if not entries:
        return False, None
    return True, _fingerprint(entries)


def _fingerprint(entries: list[str]) -> str:
    hasher = hashlib.sha256()
    for entry in sorted(entries):
        hasher.update(entry.encode("utf-8"))
        hasher.update(b"\x00")
    return f"sha256:{hasher.hexdigest()}"

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
    return _fingerprint(entries)


@dataclass(frozen=True)
class WorktreeSnapshot:
    """In-memory worktree snapshot descriptor (P1.b/P1.g).

    ``snapshot_id`` is only set when the descriptor was persisted into the
    ``snapshots`` table (``bind_snapshot``); read-only query paths carry the
    content ``descriptor_digest`` instead so pre/post-change snapshots can
    still be compared without a DB write.
    """

    repo_root: str
    commit_sha: str | None
    dirty: bool | None
    dirty_fingerprint: str | None
    captured_at: int
    role: str = "query"  # query | pre_change | post_change
    manifest_digest: str | None = None
    generation: int | None = None
    algo_version: str = "sha256-v1"
    snapshot_id: str | None = None
    descriptor_digest: str = field(default="", compare=False)
    # P0 content binding (Contract 2): when cited_paths are supplied, every
    # cited file is hashed from the working tree and the per-file digests
    # fold into scope_digest. Any unreadable cited path forces
    # scope_digest=None (fail-closed) and names the path in ``unreadable``.
    content_digests: dict[str, str] = field(default_factory=dict)
    scope_digest: str | None = None
    unreadable: list[str] = field(default_factory=list)


    def as_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "snapshot_id": self.snapshot_id,
            "descriptor_digest": self.descriptor_digest,
            "role": self.role,
            "commit_sha": self.commit_sha,
            "dirty": self.dirty,
            "dirty_fingerprint": self.dirty_fingerprint,
            "manifest_digest": self.manifest_digest,
            "generation": self.generation,
            "algo_version": self.algo_version,
            "captured_at": self.captured_at,
        }
        if self.content_digests:
            d["content_digests"] = dict(self.content_digests)
        if self.scope_digest is not None:
            d["scope_digest"] = self.scope_digest
        if self.unreadable:
            d["unreadable"] = list(self.unreadable)
        return d


def _content_binding(
    repo_root: str, cited_paths: list[str] | None
) -> tuple[dict[str, str], str | None, list[str]]:
    """Hash every cited file from the working tree (Contract 2).

    Returns ``(content_digests, scope_digest, unreadable)``. Paths are
    deduplicated and normalized to forward slashes; digests fold into a
    single ``scope_digest`` over the sorted ``"path  hexdigest"`` lines.
    Any read failure is fail-closed: the offending path lands in
    ``unreadable`` and ``scope_digest`` comes back None.
    """
    if not cited_paths:
        return {}, None, []
    digests: dict[str, str] = {}
    unreadable: list[str] = []
    root_real = os.path.realpath(repo_root)
    for raw in cited_paths:
        raw_s = str(raw).replace(os.sep, "/")
        if os.path.isabs(raw_s):
            # Graph nodes store absolute paths; normalize anything under
            # the repo root to repo-relative so CLI and MCP citing the
            # same node produce identical digest keys (Contract 2).
            real = os.path.realpath(raw_s)
            if real == root_real or real.startswith(root_real + os.sep):
                rel = os.path.relpath(real, root_real).replace(os.sep, "/")
            else:
                # Cited path outside the repo: fail-closed below.
                rel = raw_s.strip("/")
        else:
            rel = raw_s.strip("/")
        abs_path = os.path.join(root_real, *rel.split("/"))
        try:
            with open(abs_path, "rb") as fh:
                digests[rel] = hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            unreadable.append(rel)
    if unreadable:
        return digests, None, sorted(unreadable)
    hasher = hashlib.sha256()
    for rel in sorted(digests):
        hasher.update(f"{rel}  {digests[rel]}\n".encode("utf-8"))
    return digests, f"sha256:{hasher.hexdigest()}", []


def capture_worktree_snapshot(
    repo_root: str,
    conn: sqlite3.Connection | None = None,
    *,
    role: str = "query",
    cited_paths: list[str] | None = None,
) -> WorktreeSnapshot:
    """Capture the common snapshot descriptor shared by assured queries.

    With ``conn`` the descriptor is ALSO persisted (reusing
    ``bind_snapshot`` semantics); without it this stays a read-only capture
    — no writes happen on read paths.

    With ``cited_paths`` the descriptor additionally binds file CONTENT
    (not just git status): each cited file is sha256-hashed from the
    working tree and the per-file digests fold into ``scope_digest``.
    Unreadable cited paths leave ``scope_digest`` unset (fail-closed) and
    are reported in ``unreadable``.
    """
    from sot_graph.envelope import compute_manifest_digest, compute_snapshot_generation

    root = os.path.realpath(repo_root)
    dirty, fingerprint = dirty_state(root)
    content_digests, scope_digest, unreadable = _content_binding(
        root, cited_paths
    )
    snapshot = WorktreeSnapshot(
        repo_root=root,
        commit_sha=get_head_sha(root),
        dirty=dirty,
        dirty_fingerprint=fingerprint,
        captured_at=int(time.time()),
        role=role,
        manifest_digest=compute_manifest_digest(conn) if conn is not None else None,
        generation=compute_snapshot_generation(conn) if conn is not None else None,
    )
    if cited_paths is not None:
        snapshot = replace(snapshot, algo_version="sha256-v2")
    if content_digests:
        snapshot = replace(snapshot, content_digests=content_digests)
    if scope_digest is not None:
        snapshot = replace(snapshot, scope_digest=scope_digest)
    if unreadable:
        snapshot = replace(snapshot, unreadable=unreadable)
    hasher = hashlib.sha256()
    for part in (
        str(snapshot.commit_sha), str(snapshot.dirty),
        str(snapshot.dirty_fingerprint), str(snapshot.manifest_digest),
        str(snapshot.generation), snapshot.role,
        # Contract 2: content binding must be part of the descriptor so
        # v1 (status-only) and v2 (content-bound) captures of the same
        # git state never collide.
        snapshot.algo_version, str(snapshot.scope_digest),
    ):
        hasher.update(part.encode("utf-8"))
        hasher.update(b"\x00")
    digest = f"sha256:{hasher.hexdigest()}"
    snapshot = replace(snapshot, descriptor_digest=digest)
    if conn is not None:
        return replace(snapshot, snapshot_id=bind_snapshot(conn, root))
    return snapshot


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
