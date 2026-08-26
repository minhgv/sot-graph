"""P2 snapshot binding, persistence, and staleness-downgrade tests (schema v7).

Every CBM executable is a FAKE script on a private PATH whose ``index_status``
head_sha / ``check_index_coverage`` hash_status are controlled through
environment variables, so a test can mutate the git repo between calls and
simulate "index not yet reindexed" precisely. The real
``codebase-memory-mcp`` binary is never invoked.
"""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
import uuid

import pytest

from sot_graph.db import SCHEMA_VERSION, Database
from sot_graph.providers.base import SymbolRequest, CoverageRequest
from sot_graph.providers.codebase_memory import (
    PROVIDER_NAME,
    CodebaseMemoryProvider,
    SnapshotMatch,
    snapshot_flags,
)
from sot_graph.providers.normalization import (
    normalize_assertion,
    trust_ceiling,
)

PY = sys.executable


# --------------------------------------------------------------------- fakes

def make_exe(directory, name: str, body: str) -> str:
    if os.name == "nt":
        # CreateProcess cannot exec shebang scripts; install a .cmd wrapper
        # that forwards to this interpreter, keeping a single spawnable argv[0].
        script = directory / f"{name}.py"
        script.write_text(body, encoding="utf-8")
        wrapper = directory / f"{name}.cmd"
        wrapper.write_text(f'@"{sys.executable}" "%~dp0{name}.py" %*\r\n', encoding="utf-8")
        return str(wrapper)
    path = directory / name
    path.write_text(f"#!{PY}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def dispatch_exe(directory, name: str = "cbm-p2") -> str:
    """Fake CLI: env-controlled index_status / check_index_coverage."""
    body = (
        "import json, os, sys\n"
        "tool = sys.argv[sys.argv.index('--json') + 1]\n"
        "req = None\n"
        "if '--args-file' in sys.argv:\n"
        "    i = sys.argv.index('--args-file')\n"
        "    with open(sys.argv[i + 1], encoding='utf-8') as fh:\n"
        "        req = json.load(fh)\n"
        "head = os.environ.get('CBM_FAKE_HEAD_SHA', '')\n"
        "if tool == 'list_projects':\n"
        "    payload = {'projects': [{'name': 'proj-fake',\n"
        "                             'root_path': os.getcwd()}],\n"
        "               'has_more': False}\n"
        "elif tool == 'index_status':\n"
        "    payload = {'status': 'ok', 'nodes': 3, 'edges': 2,\n"
        "               'root_path': os.getcwd(),\n"
        "               'head_sha': head or None, 'base_sha': None,\n"
        "               'branch': os.environ.get('CBM_FAKE_BRANCH', 'main'),\n"
        "               'coverage_report': {}}\n"
        "elif tool == 'check_index_coverage':\n"
        "    statuses = json.loads(os.environ.get('CBM_FAKE_COVERAGE', '{}'))\n"
        "    paths = (req or {}).get('paths', [])\n"
        "    entries = [{'path': p, 'hash_status': statuses.get(p, 'fresh')}\n"
        "               for p in paths]\n"
        "    payload = {'entries': entries, 'caveat': ''}\n"
        "else:\n"
        "    payload = {'symbols': [\n"
        "        {'name': 'foo', 'kind': 'function',\n"
        "         'qualified_name': 'mod::foo', 'path': 'a.py',\n"
        "         'language': 'python',\n"
        "         'span': {'start_line': 1, 'end_line': 3}}]}\n"
        "env = {'content': [{'type': 'text', 'text': json.dumps(payload)}],\n"
        "       'isError': False, 'structuredContent': {}}\n"
        "print(json.dumps(env))\n"
    )
    return make_exe(directory, name, body)


def git(repo: str, *args: str) -> None:
    subprocess.run(
        ["git", "-C", repo, *args], check=True, capture_output=True,
    )


def head_sha(repo: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return proc.stdout.strip()


def write_file(repo: str, name: str, content: str) -> None:
    with open(os.path.join(repo, name), "w", encoding="utf-8") as fh:
        fh.write(content)


def make_git_repo(tmp_path) -> str:
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "p2@test")
    git(repo, "config", "user.name", "P2 Test")
    write_file(repo, "a.py", "def foo():\n    return 1\n\n\nfoo()\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def open_db(tmp_path, name: str = "sot.db") -> Database:
    return Database(str(tmp_path / name))


def search(provider: CodebaseMemoryProvider, repo: str):
    return provider.search_symbols(
        SymbolRequest(repo_root=repo, query="foo")
    )


RAW_SUBJECT = {
    "name": "foo",
    "kind": "function",
    "qualified_name": "mod::foo",
    "path": "a.py",
    "language": "python",
    "span": {"start_line": 1, "end_line": 3},
}


# --------------------------------------------------- 1. clean HEAD binding

class TestFreshBinding:
    def test_clean_head_binds_correctly(self, tmp_path, monkeypatch):
        repo = make_git_repo(tmp_path)
        sha1 = head_sha(repo)
        monkeypatch.setenv("CBM_FAKE_HEAD_SHA", sha1)
        db = open_db(tmp_path)
        provider = CodebaseMemoryProvider(
            command=[dispatch_exe(tmp_path)], db=db,
        )
        outcome = search(provider, repo)

        assert outcome.ok is True
        assert outcome.metadata["freshness"] == "FRESH"
        assert outcome.metadata["snapshot_bound"] is True
        assert outcome.metadata["source_changed"] is False
        snap = outcome.metadata["snapshot"]
        assert snap["cbm_head_sha"] == sha1
        assert snap["sot_head_sha"] == sha1
        assert snap["branch"] == "main"

    def test_run_and_binding_rows_persisted(self, tmp_path, monkeypatch):
        repo = make_git_repo(tmp_path)
        monkeypatch.setenv("CBM_FAKE_HEAD_SHA", head_sha(repo))
        db = open_db(tmp_path)
        provider = CodebaseMemoryProvider(
            command=[dispatch_exe(tmp_path)], db=db,
        )
        outcome = search(provider, repo)
        assert outcome.ok

        runs = db.get_provider_runs()
        main_runs = [r for r in runs if r["capability"] == "search_graph"]
        assert len(main_runs) == 1
        run = main_runs[0]
        assert run["provider_name"] == PROVIDER_NAME
        assert run["status"] == "ok"
        assert run["exit_code"] == 0
        assert isinstance(run["duration_ms"], int) and run["duration_ms"] >= 0
        assert len(run["command_digest"]) == 64
        int(run["command_digest"], 16)  # hex digest
        assert run["snapshot_hash"] == head_sha(repo)

        rows = db.conn.execute(
            "SELECT sot_repo_id, provider_name, provider_project_id, "
            "head_sha, branch FROM provider_project_bindings"
        ).fetchall()
        assert len(rows) == 1
        sot_repo_id, pname, project_id, bind_sha, branch = rows[0]
        assert sot_repo_id == os.path.realpath(repo)
        assert pname == PROVIDER_NAME
        assert project_id == "proj-fake"
        assert bind_sha == head_sha(repo)
        assert branch == "main"


# ------------------------------- 2. staleness downgrade after repo mutation

MUTATIONS = {
    "edit_body": lambda repo: (
        write_file(repo, "a.py", "def foo():\n    return 42\n\n\nfoo()\n"),
        git(repo, "add", "."), git(repo, "commit", "-q", "-m", "edit"),
    ),
    "add_caller": lambda repo: (
        write_file(repo, "caller.py", "from a import foo\n\nfoo()\n"),
        git(repo, "add", "."), git(repo, "commit", "-q", "-m", "caller"),
    ),
    "rename_file": lambda repo: (
        git(repo, "mv", "a.py", "b.py"),
        git(repo, "commit", "-q", "-m", "rename"),
    ),
    "delete_file": lambda repo: (
        git(repo, "rm", "-q", "a.py"),
        git(repo, "commit", "-q", "-m", "delete"),
    ),
}


class TestStalenessDowngrade:
    @pytest.mark.parametrize("mutation", sorted(MUTATIONS))
    def test_mutation_without_reindex_downgrades_to_stale(
        self, tmp_path, monkeypatch, mutation,
    ):
        repo = make_git_repo(tmp_path)
        stale_sha = head_sha(repo)          # fake index stays at old HEAD
        monkeypatch.setenv("CBM_FAKE_HEAD_SHA", stale_sha)
        db = open_db(tmp_path)
        provider = CodebaseMemoryProvider(
            command=[dispatch_exe(tmp_path)], db=db,
        )
        first = search(provider, repo)
        assert first.ok and first.metadata["freshness"] == "FRESH"

        MUTATIONS[mutation](repo)           # HEAD moves; fake does NOT
        assert head_sha(repo) != stale_sha

        second = search(provider, repo)
        assert second.ok
        assert second.metadata["freshness"] == "STALE"
        assert second.metadata["source_changed"] is True
        assert second.metadata["snapshot"]["cbm_head_sha"] == stale_sha
        assert second.metadata["snapshot"]["sot_head_sha"] == head_sha(repo)

        # Exit gate: candidates derived from the stale run can NEVER be
        # SUPPORTED — trust_ceiling caps them at STALE.
        bound, changed = snapshot_flags(second.metadata)
        assertion = normalize_assertion(
            raw_subject=RAW_SUBJECT,
            provider_relation="defines",
            targets=("a.py",),
            snapshot_bound=bound,
            source_changed=changed,
        )
        assert assertion.verdict == "STALE"
        assert assertion.verdict != "SUPPORTED"

    def test_unbound_index_never_supported(self, tmp_path, monkeypatch):
        repo = make_git_repo(tmp_path)
        # Fake reports no head_sha at all -> unbound -> UNVERIFIABLE.
        monkeypatch.setenv("CBM_FAKE_HEAD_SHA", "")
        provider = CodebaseMemoryProvider(command=[dispatch_exe(tmp_path)])
        outcome = search(provider, repo)
        assert outcome.ok
        assert outcome.metadata["freshness"] == "UNBOUND"
        bound, changed = snapshot_flags(outcome.metadata)
        verdict, _ = trust_ceiling(
            snapshot_bound=bound, has_span=True, unique_target=True,
            source_changed=changed,
        )
        assert verdict == "UNVERIFIABLE"

    def test_reindex_restores_freshness(self, tmp_path, monkeypatch):
        repo = make_git_repo(tmp_path)
        stale_sha = head_sha(repo)
        monkeypatch.setenv("CBM_FAKE_HEAD_SHA", stale_sha)
        provider = CodebaseMemoryProvider(command=[dispatch_exe(tmp_path)])
        assert search(provider, repo).metadata["freshness"] == "FRESH"

        write_file(repo, "a.py", "def foo():\n    return 7\n")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "edit")
        new_sha = head_sha(repo)
        assert search(provider, repo).metadata["freshness"] == "STALE"

        # Reindex: the (fake) index now reports the NEW head.
        monkeypatch.setenv("CBM_FAKE_HEAD_SHA", new_sha)
        fresh = search(provider, repo)
        assert fresh.metadata["freshness"] == "FRESH"
        bound, changed = snapshot_flags(fresh.metadata)
        verdict, resolution = trust_ceiling(
            snapshot_bound=bound, has_span=True, unique_target=True,
            source_changed=changed,
        )
        assert (verdict, resolution) == ("SUPPORTED", "EXACT")


# --------------------------------------- 3. coverage-driven staleness (paths)

class TestCoverageStaleness:
    def test_stale_coverage_entry_downgrades_even_with_matching_head(
        self, tmp_path, monkeypatch,
    ):
        repo = make_git_repo(tmp_path)
        monkeypatch.setenv("CBM_FAKE_HEAD_SHA", head_sha(repo))
        monkeypatch.setenv("CBM_FAKE_COVERAGE", json.dumps({"a.py": "stale"}))
        provider = CodebaseMemoryProvider(command=[dispatch_exe(tmp_path)])
        outcome = provider.coverage(
            CoverageRequest(repo_root=repo, paths=("a.py",))
        )
        assert outcome.ok
        assert outcome.metadata["freshness"] == "STALE"
        assert outcome.metadata["source_changed"] is True
        assert outcome.metadata["snapshot"]["stale_paths"] == ["a.py"]
        bound, changed = snapshot_flags(outcome.metadata)
        verdict, _ = trust_ceiling(
            snapshot_bound=bound, has_span=True, unique_target=True,
            source_changed=changed,
        )
        assert verdict == "STALE"

    def test_all_fresh_coverage_stays_fresh(self, tmp_path, monkeypatch):
        repo = make_git_repo(tmp_path)
        monkeypatch.setenv("CBM_FAKE_HEAD_SHA", head_sha(repo))
        provider = CodebaseMemoryProvider(command=[dispatch_exe(tmp_path)])
        outcome = provider.coverage(
            CoverageRequest(repo_root=repo, paths=("a.py",))
        )
        assert outcome.ok
        assert outcome.metadata["freshness"] == "FRESH"


# ------------------------------------------------- 4. fail-closed UNKNOWN

class TestUnknownFailClosed:
    def test_non_git_dir_yields_unknown_never_supported(
        self, tmp_path, monkeypatch,
    ):
        plain = str(tmp_path / "not-a-repo")
        os.makedirs(plain)
        monkeypatch.setenv("CBM_FAKE_HEAD_SHA", "f" * 40)
        provider = CodebaseMemoryProvider(command=[dispatch_exe(tmp_path)])
        outcome = search(provider, plain)
        assert outcome.ok
        assert outcome.metadata["freshness"] == "UNKNOWN"
        assert outcome.metadata["snapshot_bound"] is True
        # UNKNOWN must fail closed: treated as unbound by trust ceilings.
        bound, changed = snapshot_flags(outcome.metadata)
        assert (bound, changed) == (False, False)


# --------------------------------------------- 5. schema v6 -> v7 migration

_V6_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_journal (
    path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
    mtime_ms INTEGER NOT NULL, generation INTEGER DEFAULT 1,
    reconciled_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS graph_nodes (
    id TEXT PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL, symbol TEXT,
    fqn TEXT, signature TEXT, label TEXT NOT NULL, body TEXT NOT NULL,
    keywords TEXT, line_start INTEGER, line_end INTEGER, col_start INTEGER,
    col_end INTEGER, updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY, repo_root TEXT NOT NULL, commit_sha TEXT,
    dirty INTEGER NOT NULL DEFAULT 0, dirty_fingerprint TEXT,
    manifest_digest TEXT, algo_version TEXT NOT NULL DEFAULT 'sha256-v1',
    generation INTEGER, captured_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS provider_runs (
    id TEXT PRIMARY KEY, provider_name TEXT NOT NULL,
    provider_version TEXT, capability TEXT NOT NULL, snapshot_hash TEXT,
    project_root TEXT, position_encoding TEXT DEFAULT 'UTF-8',
    arguments_json TEXT, created_at INTEGER NOT NULL,
    snapshot_id TEXT REFERENCES snapshots(id));
CREATE TABLE IF NOT EXISTS provider_evidence (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, provider_name TEXT,
    file_path TEXT, path TEXT NOT NULL, symbol TEXT,
    src_symbol TEXT NOT NULL, target_symbol TEXT, dst_symbol TEXT,
    role TEXT, relation TEXT NOT NULL, line_start INTEGER,
    line_end INTEGER, col_start INTEGER, col_end INTEGER,
    syntax_kind TEXT, documentation TEXT, confidence REAL DEFAULT 1.0,
    metadata_json TEXT, recorded_at INTEGER, created_at INTEGER NOT NULL,
    FOREIGN KEY(run_id) REFERENCES provider_runs(id) ON DELETE CASCADE);
"""


def make_v6_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(_V6_SCHEMA)
    conn.execute(
        "INSERT INTO graph_nodes (id, path, kind, label, body, updated_at) "
        "VALUES ('note:1', 'notes.md', 'note', 'My note', 'keep me', 1)"
    )
    conn.execute(
        "INSERT INTO snapshots (id, repo_root, commit_sha, dirty, captured_at) "
        "VALUES ('snap_old', '/old/repo', 'abc', 0, 1)"
    )
    conn.execute(
        "INSERT INTO provider_runs (id, provider_name, capability, created_at) "
        "VALUES ('run_old', 'codebase-memory', 'search_graph', 1)"
    )
    conn.execute(
        "INSERT INTO provider_evidence (id, run_id, path, src_symbol, "
        "relation, recorded_at, created_at) "
        "VALUES ('ev_old', 'run_old', 'a.py', 'foo', 'CALLS', 1, 1)"
    )
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
    conn.commit()
    conn.close()


class TestMigrationV6ToV7:
    def test_v6_database_migrates_additively(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        make_v6_db(db_path)

        db = Database(db_path)
        try:
            assert db._user_version() == SCHEMA_VERSION
            assert db.schema_was_reset is False
            # Old ledger data intact.
            runs = db.get_provider_runs()
            assert [r["id"] for r in runs] == ["run_old"]
            ev = db.conn.execute(
                "SELECT COUNT(*) FROM provider_evidence WHERE id='ev_old'"
            ).fetchone()[0]
            assert ev == 1
            note = db.conn.execute(
                "SELECT label FROM graph_nodes WHERE id='note:1'"
            ).fetchone()
            assert note == ("My note",)
            # New v7 columns exist and default to NULL for legacy rows.
            run_cols = [
                r[1] for r in db.conn.execute(
                    "PRAGMA table_info(provider_runs)"
                ).fetchall()
            ]
            for col in ("status", "exit_code", "duration_ms", "command_digest"):
                assert col in run_cols
            ev_cols = [
                r[1] for r in db.conn.execute(
                    "PRAGMA table_info(provider_evidence)"
                ).fetchall()
            ]
            assert "snapshot_hash" in ev_cols
            # Identity-mapping table exists and is usable.
            bid = db.record_provider_binding("/repo", PROVIDER_NAME, "proj")
            assert bid.startswith("bind_")
        finally:
            db.close()

    def test_reopening_migrated_db_is_idempotent(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        make_v6_db(db_path)
        first = Database(db_path)
        first.close()
        second = Database(db_path)
        try:
            assert second._user_version() == SCHEMA_VERSION
            assert second.schema_was_reset is False
            assert second.conn.execute(
                "SELECT COUNT(*) FROM provider_runs"
            ).fetchone()[0] == 1
            assert second.conn.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE kind='note'"
            ).fetchone()[0] == 1
        finally:
            second.close()

    def test_fresh_database_creates_v7_directly(self, tmp_path):
        db = open_db(tmp_path)
        try:
            assert db._user_version() == SCHEMA_VERSION
            tables = {
                r[0] for r in db.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "provider_project_bindings" in tables
        finally:
            db.close()


# ------------------------------------------------- 6. run persistence robustness

class ExplodingConn:
    """Proxy connection raising on a matching statement (crash simulator)."""

    def __init__(self, real, needle: str):
        self._real = real
        self._needle = needle
        self.armed = True

    def execute(self, sql, *args, **kwargs):
        if self.armed and self._needle in sql:
            raise sqlite3.OperationalError("simulated crash before commit")
        return self._real.execute(sql, *args, **kwargs)

    def __enter__(self):
        return self._real.__enter__()

    def __exit__(self, *exc_info):
        return self._real.__exit__(*exc_info)

    def __getattr__(self, name):
        return getattr(self._real, name)


class TestRunPersistenceRobustness:
    def test_record_provider_run_persists_every_field(self, tmp_path):
        db = open_db(tmp_path)
        try:
            rid = db.record_provider_run(
                PROVIDER_NAME,
                provider_version="0.10.8",
                capability="search_graph",
                snapshot_hash="a" * 40,
                project_root="/repo",
                status="ok",
                exit_code=0,
                duration_ms=12,
                command_digest="d" * 64,
                run_id="run_fields",
            )
            assert rid == "run_fields"
            row = db.conn.execute(
                "SELECT provider_version, capability, snapshot_hash, "
                "project_root, status, exit_code, duration_ms, command_digest "
                "FROM provider_runs WHERE id='run_fields'"
            ).fetchone()
            assert row == (
                "0.10.8", "search_graph", "a" * 40, "/repo",
                "ok", 0, 12, "d" * 64,
            )
        finally:
            db.close()

    def test_crash_before_commit_leaves_no_partial_row(self, tmp_path):
        db = open_db(tmp_path)
        try:
            real = db._conn
            db.conn = ExplodingConn(real, "INSERT OR REPLACE INTO provider_runs")
            with pytest.raises(sqlite3.OperationalError):
                db.record_provider_run(PROVIDER_NAME, run_id="run_boom")
            db.conn = real  # restore via the documented test seam
            count = db.conn.execute(
                "SELECT COUNT(*) FROM provider_runs WHERE id='run_boom'"
            ).fetchone()[0]
            assert count == 0  # nothing half-written

        finally:
            db.close()

    def test_adapter_survives_exploding_ledger(self, tmp_path, monkeypatch):
        repo = make_git_repo(tmp_path)
        monkeypatch.setenv("CBM_FAKE_HEAD_SHA", head_sha(repo))

        class BoomLedger:
            def record_provider_run(self, *a, **k):
                raise RuntimeError("ledger disk on fire")

        provider = CodebaseMemoryProvider(
            command=[dispatch_exe(tmp_path)], db=BoomLedger(),
        )
        outcome = search(provider, repo)   # must NOT raise
        assert outcome.ok is True
        assert outcome.metadata["freshness"] == "FRESH"

    def test_provider_binding_upsert_is_idempotent(self, tmp_path):
        db = open_db(tmp_path)
        try:
            db.record_provider_binding(
                "/repo", PROVIDER_NAME, "proj-old", head_sha="1" * 40,
            )
            db.record_provider_binding(
                "/repo", PROVIDER_NAME, "proj-new",
                head_sha="2" * 40, branch="dev",
            )
            rows = db.conn.execute(
                "SELECT provider_project_id, head_sha, branch "
                "FROM provider_project_bindings WHERE sot_repo_id='/repo'"
            ).fetchall()
            assert len(rows) == 1  # updated in place, never duplicated
            assert rows[0] == ("proj-new", "2" * 40, "dev")
        finally:
            db.close()

    def test_evidence_rows_are_snapshot_scoped(self, tmp_path):
        db = open_db(tmp_path)
        try:
            db.record_provider_run(PROVIDER_NAME, run_id="run_ev")
            n = db.record_provider_evidence("run_ev", [{
                "path": "a.py", "src_symbol": "foo", "relation": "CALLS",
                "snapshot_hash": "c" * 40,
            }])
            assert n == 1
            stored = db.conn.execute(
                "SELECT snapshot_hash FROM provider_evidence WHERE run_id='run_ev'"
            ).fetchall()
            assert stored == [("c" * 40,)]
        finally:
            db.close()


# -------------------------------------------------- 7. match object contract

class TestSnapshotMatchContract:
    def test_snapshot_flags_fail_closed_by_default(self):
        assert snapshot_flags({}) == (False, False)
        assert snapshot_flags({"freshness": "UNBOUND"}) == (False, False)
        assert snapshot_flags({"freshness": "UNKNOWN"}) == (False, False)
        assert snapshot_flags({"freshness": "FRESH"}) == (True, False)
        assert snapshot_flags({"freshness": "STALE"}) == (True, True)

    def test_freshness_property_vocabulary(self):
        assert SnapshotMatch(bound=False, fresh=False, detail="").freshness \
            == "UNBOUND"
        assert SnapshotMatch(bound=True, fresh=True, detail="").freshness \
            == "FRESH"
        assert SnapshotMatch(
            bound=True, fresh=False, detail="",
            cbm_head_sha="a", sot_head_sha="b",
        ).freshness == "STALE"
        assert SnapshotMatch(bound=True, fresh=False, detail="").freshness \
            == "UNKNOWN"
