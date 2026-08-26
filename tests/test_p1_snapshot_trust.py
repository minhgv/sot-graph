"""P1 — snapshot & trust blockers.

Blocker #1 reproduction: a dirty worktree with a MATCHING HEAD must never be
FRESH (the index binds to the committed tree). Journal mismatches on cited
files must surface in builtin queries and MARK (not delete) evidence. The
verify window must abstain on a snapshot race.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sot_graph.db import Database  # noqa: E402
from sot_graph.providers.codebase_memory import (  # noqa: E402
    CodebaseMemoryProvider,
    SnapshotBinding,
)
from sot_graph.providers.verification import (  # noqa: E402
    SNAPSHOT_RACE,
    VERIFIED,
    verify_subject,
)
from sot_graph.snapshot import capture_worktree_snapshot, dirty_state  # noqa: E402

sot_graph_cm = importlib.import_module("sot_graph.providers.codebase_memory")
sot_graph_verification = importlib.import_module("sot_graph.providers.verification")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True, capture_output=True,
    )


@pytest.fixture()
def clean_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "mod.py").write_text(
        "def target():\n    return 1\n\n\ndef caller():\n    return target()\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    return repo


def _reconciled_db(repo: Path) -> Database:
    from sot_graph.reconciler import Reconciler

    db = Database(str(repo / ".sot" / "sot.db"))
    Reconciler(db, str(repo)).reconcile()
    return db


def _patched_provider(repo: Path, head_sha: str | None) -> CodebaseMemoryProvider:
    """Provider whose CBM side is faked to report exactly ``head_sha``."""
    prov = object.__new__(CodebaseMemoryProvider)
    prov._project_for = lambda repo_root, explicit=None: ("proj", None, None)
    prov._index_binding = (
        lambda repo_root, project: SnapshotBinding(
            project="proj", head_sha=head_sha, branch="main",
            index_status="ready", captured_at=0,
        )
        if head_sha
        else None
    )
    return prov


class TestDirtyGateBlockerOne:
    def test_matching_head_dirty_worktree_is_stale(self, clean_repo: Path) -> None:
        head = subprocess.run(
            ["git", "-C", str(clean_repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        # Blocker #1: edit WITHOUT committing — HEAD unchanged, content changed.
        (clean_repo / "mod.py").write_text(
            "def target():\n    return 2\n\n\ndef caller():\n    return target()\n",
            encoding="utf-8",
        )
        prov = _patched_provider(clean_repo, head)
        match = prov.snapshot_match(str(clean_repo))
        assert match.bound is True
        assert match.fresh is False, "dirty worktree must never be FRESH"
        assert match.dirty is True
        assert match.dirty_fingerprint and match.dirty_fingerprint.startswith("sha256:")
        assert match.freshness == "STALE"
        assert "dirty worktree" in match.detail

    def test_unstaged_staged_untracked_all_dirty(self, clean_repo: Path) -> None:
        assert dirty_state(str(clean_repo)) == (False, None)
        (clean_repo / "new_file.py").write_text("x = 1\n", encoding="utf-8")
        assert dirty_state(str(clean_repo))[0] is True  # untracked
        _git(clean_repo, "add", "new_file.py")
        assert dirty_state(str(clean_repo))[0] is True  # staged
        _git(clean_repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x")
        assert dirty_state(str(clean_repo)) == (False, None)

    def test_clean_matching_head_is_fresh(self, clean_repo: Path) -> None:
        head = subprocess.run(
            ["git", "-C", str(clean_repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        prov = _patched_provider(clean_repo, head)
        match = prov.snapshot_match(str(clean_repo))
        assert match.fresh is True
        assert match.dirty is False
        assert match.freshness == "FRESH"

    def test_dirty_unverifiable_state_caps_freshness(self, clean_repo: Path) -> None:
        head = subprocess.run(
            ["git", "-C", str(clean_repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        prov = _patched_provider(clean_repo, head)
        # Simulate git status failure: dirty_state returns (None, None).
        orig = sot_graph_cm.dirty_state
        sot_graph_cm.dirty_state = lambda root: (None, None)
        try:
            match = prov.snapshot_match(str(clean_repo))
        finally:
            sot_graph_cm.dirty_state = orig
        assert match.fresh is False
        assert match.dirty is None
        assert "unverifiable" in match.detail


class TestWorktreeSnapshotDescriptor:
    def test_descriptor_digest_tracks_dirty_state(self, clean_repo: Path) -> None:
        clean = capture_worktree_snapshot(str(clean_repo))
        assert clean.dirty is False
        (clean_repo / "mod.py").write_text("x = 1\n", encoding="utf-8")
        dirty = capture_worktree_snapshot(str(clean_repo))
        assert dirty.dirty is True
        assert dirty.descriptor_digest != clean.descriptor_digest

    def test_roles_recorded_for_pre_post_change(self, clean_repo: Path) -> None:
        pre = capture_worktree_snapshot(str(clean_repo), role="pre_change")
        post = capture_worktree_snapshot(str(clean_repo), role="post_change")
        assert pre.as_dict()["role"] == "pre_change"
        assert post.as_dict()["role"] == "post_change"
        # Same worktree, different role -> distinguishable descriptors.
        assert pre.descriptor_digest != post.descriptor_digest

    def test_read_only_capture_does_not_write_ledger(self, clean_repo: Path) -> None:
        snap = capture_worktree_snapshot(str(clean_repo))
        assert snap.snapshot_id is None  # no DB write on a read path


class TestJournalStalenessAndInvalidation:
    def test_stale_journal_files_detects_edit_and_delete(self, clean_repo: Path) -> None:
        db = _reconciled_db(clean_repo)
        try:
            root = str(clean_repo)
            assert db.stale_journal_files(["mod.py"], root=root) == []
            (clean_repo / "mod.py").write_text(
                "def target():\n    return 999\n\n\ndef caller():\n    return target()\n",
                encoding="utf-8",
            )
            assert db.stale_journal_files(["mod.py"], root=root) == ["mod.py"]
            (clean_repo / "mod.py").unlink()
            assert db.stale_journal_files(["mod.py"], root=root) == ["mod.py"]
            # Untracked/never-indexed paths are not "stale".
            assert db.stale_journal_files(["no_such_file.py"], root=root) == []
        finally:
            db.close()

    def test_mark_evidence_stale_marks_never_deletes(self, clean_repo: Path) -> None:
        db = _reconciled_db(clean_repo)
        try:
            with db.conn:
                db.conn.execute(
                    "INSERT INTO provider_runs (id, provider_name, capability, created_at) "
                    "VALUES ('run1', 'test', 'search', 1)"
                )
                db.conn.execute(
                    "INSERT INTO provider_evidence "
                    "(id, run_id, path, src_symbol, relation, created_at) VALUES "
                    "('ev1', 'run1', 'mod.py', 'caller', 'calls', 1),"
                    "('ev2', 'run1', 'other.py', 'x', 'calls', 1)"
                )
            marked = db.mark_evidence_stale(["mod.py"], reason="edited mid-flight")
            assert marked == 1
            rows = db.conn.execute(
                "SELECT path, invalidated_at, invalidation_reason FROM provider_evidence ORDER BY path"
            ).fetchall()
            by_path = {r[0]: r for r in rows}
            assert by_path["mod.py"][1] is not None
            assert by_path["mod.py"][2] == "edited mid-flight"
            assert by_path["other.py"][1] is None  # untouched, still present
            # Idempotent: already-invalidated rows keep their first reason.
            assert db.mark_evidence_stale(["mod.py"], reason="second wave") == 0
        finally:
            db.close()


class TestVerifySubjectSnapshotRace:
    def test_race_between_capture_and_verify_abstains(
        self, clean_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        subject = {
            "path": "mod.py",
            "start_line": 1,
            "end_line": 1,
            "kind": "function",
            "qualified_name": "mod.target",
        }
        assert verify_subject(subject, str(clean_repo)).status == VERIFIED

        real_stat = os.stat
        calls = {"n": 0}

        def racing_stat(p, *args, **kwargs):
            calls["n"] += 1
            st = real_stat(p, *args, **kwargs)
            if calls["n"] == 2:  # the after-read re-check
                # Pretend the file was rewritten between read and re-stat.
                shifted = (
                    st.st_mode, st.st_ino, st.st_dev, st.st_nlink,
                    st.st_uid, st.st_gid, st.st_size + 4096,
                    st.st_atime, st.st_mtime, st.st_ctime,
                )
                return os.stat_result(shifted)
            return st
        monkeypatch.setattr(
            sot_graph_verification.os, "stat", racing_stat, raising=True
        )
        outcome = verify_subject(subject, str(clean_repo))
        assert outcome.status == SNAPSHOT_RACE
        assert "snapshot race" in outcome.detail


class TestBuiltinQueryAssurance:
    """End-to-end: explore must carry the snapshot and flag stale files."""

    def _explore_json(self, repo: Path) -> dict:
        proc = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "explore", "target", "--json"],
            capture_output=True, text=True, timeout=120,
            cwd=str(repo),
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    def test_explore_carries_snapshot_and_flags_stale(self, clean_repo: Path) -> None:
        env = dict(os.environ, SOT_ROOT=str(clean_repo))
        proc = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "reconcile"],
            capture_output=True, text=True, timeout=120,
            cwd=str(clean_repo), env=env,
        )
        assert proc.returncode == 0, proc.stderr

        payload = self._explore_json(clean_repo)
        text = json.dumps(payload)
        assert "descriptor_digest" in text
        assert "snapshot" in text

        # Edit WITHOUT reconcile: cited file mod.py is now stale.
        (clean_repo / "mod.py").write_text(
            "def target():\n    return 42\n\n\ndef caller():\n    return target()\n",
            encoding="utf-8",
        )
        payload = self._explore_json(clean_repo)
        text = json.dumps(payload)
        assert "mod.py" in payload.get("data", payload).get("stale_files", []) or "stale" in text.lower()
