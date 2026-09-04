"""SG-105 part A — canonical impact-claim pipeline + receipt store.

Locks:
- run_impact_claim is the ONE flow: validated request → pre-change
  snapshot → optional auto-reconcile → diff receipt → request/projection
  augmentation (SG-104 vocabulary) → digest over the augmented payload.
- Digest stability: two runs with one request on an unchanged repo share
  a digest (recursive volatile strip removes wall-clock/timing fields,
  including summary.execution_time_ms); a new commit flips it.
- Swallowed collection faults (edges_of / explore_node /
  provider_evidence) degrade the verdict to UNVERIFIABLE with the source
  recorded — never a crash, never silent emptiness.
- ReceiptStore: content addressing, immutability, verify-on-read.
"""

from __future__ import annotations

import dataclasses
import inspect
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from sot_graph.assurance.impact_pipeline import (
    IMPACT_REQUEST_SCHEMA_VERSION,
    CollectionError,
    ImpactClaimRequest,
    ReceiptIntegrityError,
    ReceiptStore,
    run_impact_claim,
)
from sot_graph.assurance.receipts import RECEIPT_SCHEMA_VERSION, receipt_digest, scope_receipt


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _reconcile(repo: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo), "reconcile"],
        check=True, cwd=repo, capture_output=True,
    )


def _make_repo(repo: Path) -> Path:
    """Same shape as the test_p7_receipts.receipt_repo fixture."""
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".gitignore").write_text(".sot/\n", encoding="utf-8")
    (repo / "app.py").write_text(
        "import util\n\n"
        "def run():\n"
        "    return util.help() + 1\n",
        encoding="utf-8",
    )
    (repo / "util.py").write_text(
        "def help():\n    return 41\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_app.py").write_text(
        "from app import run\n\n"
        "def test_run():\n    assert run()\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c1")
    _reconcile(repo)
    return repo


@pytest.fixture(scope="module")
def impact_repo(tmp_path_factory) -> Path:
    return _make_repo(tmp_path_factory.mktemp("irepo"))


@pytest.fixture(scope="module")
def wiring_repo(tmp_path_factory) -> Path:
    # Own repo (not impact_repo): the CLI wiring tests below mutate
    # evidence ledgers / journals; keep the Part A fixture untouched.
    return _make_repo(tmp_path_factory.mktemp("wirepo"))


def _db_of(repo: Path):
    from sot_graph.db import Database

    return Database(str(repo / ".sot" / "sot.db"))


class _FaultyConn:
    """sqlite3 connection proxy that raises on tripped SQL."""

    def __init__(self, real, trip):
        self._real = real
        self._trip = trip

    def execute(self, sql, *args):
        if self._trip(" ".join(str(sql).split())):
            raise RuntimeError("injected storage fault")
        return self._real.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._real, name)


class TestImpactClaimRequest:
    def test_defaults(self):
        req = ImpactClaimRequest()
        assert req.schema_version == IMPACT_REQUEST_SCHEMA_VERSION == "impact-request/1"
        assert (req.target, req.depth, req.staged, req.working_tree,
                req.auto_reconcile) == ("HEAD", 2, False, False, False)

    def test_normalize_is_frozen_and_idempotent(self):
        req = ImpactClaimRequest(target="  HEAD~1  ")
        norm = req.normalize()
        with pytest.raises(dataclasses.FrozenInstanceError):
            req.target = "x"  # type: ignore[misc]
        assert norm.target == "HEAD~1"
        assert norm.normalize() == norm
        assert req.target == "  HEAD~1  "  # original untouched

    def test_normalize_rejects_empty_target_and_bad_depth(self):
        for target in ("", "   "):
            with pytest.raises(ValueError):
                ImpactClaimRequest(target=target).normalize()
        for depth in (0, -1, 6):
            with pytest.raises(ValueError):
                ImpactClaimRequest(depth=depth).normalize()

    def test_scope_precedence_mirrors_engine_staged_wins(self):
        # GitDeltaExtractor.extract_diff appends --staged first; when both
        # scopes are requested the staged diff wins (engine parity).
        both = ImpactClaimRequest(staged=True, working_tree=True).normalize()
        assert both.staged is True and both.working_tree is False
        wt = ImpactClaimRequest(working_tree=True).normalize()
        assert wt.working_tree is True and wt.staged is False


class TestRunImpactClaim:
    def test_receipt_gains_request_and_projection_blocks(self, impact_repo):
        db = _db_of(impact_repo)
        try:
            receipt = run_impact_claim(ImpactClaimRequest(), db, str(impact_repo))
        finally:
            db.close()
        assert receipt["schema_version"] == RECEIPT_SCHEMA_VERSION == "1.6"
        assert receipt["request"] == {
            "schema_version": "impact-request/1",
            "target": "HEAD",
            "staged": False,
            "working_tree": False,
            "depth": 2,
            "auto_reconcile": False,
            "reconcile_provenance": "pipeline",
        }
        projection = receipt["projection"]
        assert projection["next_cursor"] is None
        assert [c["key"] for c in projection["collections"]] == [
            "changed_files", "direct_nodes", "caller_impacts",
            "test_impacts", "api_impacts", "tests_to_run",
        ]
        for entry in projection["collections"]:
            assert entry["returned_count"] == entry["enumerated_count"]
            assert entry["truncated"] is False
        changed = next(
            c for c in projection["collections"] if c["key"] == "changed_files"
        )
        assert changed["enumerated_count"] == len(receipt["changed_files"])
        # The digest covers the AUGMENTED payload, not just the base receipt.
        assert receipt["digest"] == receipt_digest(
            {k: v for k, v in receipt.items() if k != "digest"}
        )

    def test_digest_deterministic_on_unchanged_repo(self, impact_repo):
        db = _db_of(impact_repo)
        try:
            request = ImpactClaimRequest()
            first = run_impact_claim(request, db, str(impact_repo))
            second = run_impact_claim(request, db, str(impact_repo))
        finally:
            db.close()
        assert first["digest"] == second["digest"]
        # Timing stays in the payload for operators — it just never enters
        # the digest (recursive volatile strip, SG-105).
        assert first["summary"].get("execution_time_ms") is not None
        assert second["summary"].get("execution_time_ms") is not None

    def test_digest_flips_after_new_commit(self, tmp_path):
        repo = _make_repo(tmp_path / "flip")
        db = _db_of(repo)
        try:
            before = run_impact_claim(ImpactClaimRequest(), db, str(repo))
            (repo / "app.py").write_text(
                "import util\n\n"
                "def run():\n"
                "    return util.help() + 2\n",
                encoding="utf-8",
            )
            _git(repo, "add", "-A")
            _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "c2")
            after = run_impact_claim(ImpactClaimRequest(), db, str(repo))
        finally:
            db.close()
        assert before["digest"] != after["digest"]
        assert any("app.py" in str(f) for f in after["changed_files"])

    def test_invalid_request_fails_before_any_git_work(self, impact_repo):
        db = _db_of(impact_repo)
        try:
            with pytest.raises(ValueError):
                run_impact_claim(
                    ImpactClaimRequest(target=""), db, str(impact_repo)
                )
            with pytest.raises(TypeError):
                run_impact_claim({"target": "HEAD"}, db, str(impact_repo))
        finally:
            db.close()

    def test_auto_reconcile_reindexes_working_tree_change(self, tmp_path):
        repo = _make_repo(tmp_path / "auto")
        (repo / "util.py").write_text(
            "def help():\n    return 42\n", encoding="utf-8"
        )
        db = _db_of(repo)
        try:
            receipt = run_impact_claim(
                ImpactClaimRequest(working_tree=True, auto_reconcile=True),
                db, str(repo),
            )
        finally:
            db.close()
        assert receipt["request"]["auto_reconcile"] is True
        assert receipt["changed_files"], "fixture broken: empty diff"
        assert not any(
            w.startswith("auto_reconcile_failed") for w in receipt["warnings"]
        )
        # The change was re-indexed BEFORE the receipt measured staleness:
        # journal matches disk, so nothing is stale and closure is
        # reachable (the P1.g pre-snapshot was captured before reconcile).
        assert receipt["assurance_facts"]["stale_files"] == []
        assert receipt["pre_change_snapshot"] is not None


class TestCollectionFaults:
    """Swallowed storage faults degrade to UNVERIFIABLE — never crash."""

    def test_edges_fault_degrades_scope_receipt(self, impact_repo):
        db = _db_of(impact_repo)
        real = db.conn
        # 'SELECT e.relation, e.line' is _edges_of's literal SQL prefix —
        # no other query in the receipt path shares it.
        db.conn = _FaultyConn(
            real, lambda sql: sql.startswith("SELECT e.relation, e.line")
        )
        try:
            payload = scope_receipt(db, str(impact_repo), "run")
        finally:
            db.conn = real
            db.close()
        assert payload["assurance"]["status"] == "UNVERIFIABLE"
        assert "collection_error" in payload["assurance"]["reason_codes"]
        assert payload["assurance_facts"]["collection_error"] is True
        assert any(
            w.startswith("collection_error:edges_of:") for w in payload["warnings"]
        )
        assert any("injected storage fault" in w for w in payload["warnings"])

    def test_explore_node_fault_degrades_scope_receipt(self, impact_repo):
        db = _db_of(impact_repo)

        def _boom(*args, **kwargs):
            raise RuntimeError("injected storage fault")

        try:
            db.explore_node = _boom
            payload = scope_receipt(db, str(impact_repo), "run")
        finally:
            db.close()
        assert payload["assurance"]["status"] == "UNVERIFIABLE"
        assert "collection_error" in payload["assurance"]["reason_codes"]
        assert any(
            w.startswith("collection_error:explore_node:")
            for w in payload["warnings"]
        )

    def test_evidence_fault_degrades_diff_receipt(self, tmp_path):
        repo = _make_repo(tmp_path / "evfault")
        (repo / "util.py").write_text(
            "def help():\n    return 42\n", encoding="utf-8"
        )
        db = _db_of(repo)
        real = db.conn
        # The invalidated-evidence query selects 'snapshot_hash FROM
        # provider_evidence' without a JOIN; union_evidence's ledger SQL
        # always joins provider_runs, so only the receipt site trips.
        db.conn = _FaultyConn(
            real, lambda sql: "snapshot_hash FROM provider_evidence" in sql
        )
        try:
            receipt = run_impact_claim(
                ImpactClaimRequest(working_tree=True), db, str(repo)
            )
        finally:
            db.conn = real
            db.close()
        assert receipt["changed_files"], "fixture broken: empty diff"
        assert receipt["assurance"]["status"] == "UNVERIFIABLE"
        assert "collection_error" in receipt["assurance"]["reason_codes"]
        assert any(
            w.startswith("collection_error:provider_evidence:")
            for w in receipt["warnings"]
        )
        assert receipt["closure_decision"] == "open"

    def test_collection_error_marker_format(self):
        err = CollectionError("edges_of", "RuntimeError: boom")
        assert err.source == "edges_of"
        assert err.detail == "RuntimeError: boom"
        assert str(err) == "collection_error:edges_of:RuntimeError: boom"


class TestReceiptStore:
    def _receipt(self, impact_repo):
        db = _db_of(impact_repo)
        try:
            return run_impact_claim(ImpactClaimRequest(), db, str(impact_repo))
        finally:
            db.close()

    def test_put_get_roundtrip_is_content_addressed(self, impact_repo, tmp_path):
        receipt = self._receipt(impact_repo)
        store = ReceiptStore(tmp_path / ".sot" / "receipts")
        digest = store.put(receipt)
        assert digest == receipt["digest"]
        assert (store.directory / f"{digest}.json").is_file()
        assert store.list_digests() == [digest]
        loaded = store.get(digest)
        assert loaded["schema_version"] == receipt["schema_version"]
        assert loaded["projection"] == receipt["projection"]
        assert loaded["request"] == receipt["request"]
        # Volatile fields are not part of the address and not persisted.
        assert "captured_at" not in loaded["post_change_snapshot"]
        assert "execution_time_ms" not in loaded["summary"]
        # Verify-on-read: the stored bytes hash back to their address.
        assert receipt_digest(
            {k: v for k, v in loaded.items() if k != "digest"}
        ) == digest

    def test_second_put_is_noop_never_overwrite(self, impact_repo, tmp_path):
        receipt = self._receipt(impact_repo)
        store = ReceiptStore(tmp_path / "store")
        digest = store.put(receipt)
        path = store.directory / f"{digest}.json"
        first = path.read_bytes()
        assert store.put(receipt) == digest
        assert path.read_bytes() == first

    def test_tampered_file_fails_integrity_on_get(self, impact_repo, tmp_path):
        receipt = self._receipt(impact_repo)
        store = ReceiptStore(tmp_path / "store")
        digest = store.put(receipt)
        path = store.directory / f"{digest}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["changed_files"] = ["tampered.py"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ReceiptIntegrityError):
            store.get(digest)

    def test_same_address_different_bytes_is_collision_bug(
        self, impact_repo, tmp_path
    ):
        receipt = self._receipt(impact_repo)
        store = ReceiptStore(tmp_path / "store")
        digest = store.put(receipt)
        # A file already at the address with DIFFERENT bytes can only be
        # a hash collision — refuse instead of overwriting.
        (store.directory / f"{digest}.json").write_bytes(b'{"forged": true}')
        with pytest.raises(ReceiptIntegrityError):
            store.put(receipt)

    def test_missing_or_malformed_digest(self, tmp_path):
        store = ReceiptStore(tmp_path / "store")
        with pytest.raises(KeyError):
            store.get("0" * 64)
        with pytest.raises(ReceiptIntegrityError):
            store.get("../../etc/passwd")
        assert store.list_digests() == []


class TestSurfaceWiring:
    """SG-105 part B — CLI and MCP are projections of the ONE executor.

    Locks:
    - Wiring parity: the same request through run_impact_claim, through
      McpService.diff_impact_receipt, and through the CLI json path
      produces the SAME digest (the store address is surface-invariant).
    - ReceiptStore persistence on both surfaces is content-addressed:
      re-running the same request creates no duplicate file.
    - The CLI receipt carries the ``request`` block (auto_reconcile
      reflected) and --gate semantics are unchanged.
    - McpService.diff_impact projects the canonical receipt: envelope
      keys stable, markdown still rendered, assurance/assurance_facts/
      digest embedded, and SG-104 trim degradation applies to them.
    """

    def _service(self, wiring_repo: Path):
        from sot_graph.mcp_service import McpService

        return McpService(
            db_path=str(wiring_repo / ".sot" / "sot.db"),
            project_root=str(wiring_repo),
        )

    def _cli_json(self, wiring_repo: Path, db, *extra: str) -> dict:
        from sot_graph.cli import build_parser, cmd_diff_impact

        args = build_parser().parse_args(
            ["diff-impact", "--format", "json", *extra]
        )
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            code = cmd_diff_impact(args, db, str(wiring_repo))
        return {"code": code, "envelope": json.loads(buf.getvalue())}

    # NOTE: defined first — the two tests after it run the CLI, which
    # marks evidence stale / reconciles; parity must observe pristine
    # graph state on all three surfaces.
    def test_parity_same_digest_pipeline_mcp_cli(self, wiring_repo):
        db = _db_of(wiring_repo)
        try:
            pipeline = run_impact_claim(ImpactClaimRequest(), db, str(wiring_repo))
            service = self._service(wiring_repo)
            try:
                mcp = service.diff_impact_receipt()
            finally:
                service.close()
            cli = self._cli_json(wiring_repo, db)
            assert cli["code"] == 0
            assert cli["envelope"]["digest"] == mcp["digest"] == pipeline["digest"]
            # The augmented payload is the receipt itself on every surface.
            assert cli["envelope"]["request"]["target"] == "HEAD"
            assert cli["envelope"]["projection"]["next_cursor"] is None
            assert mcp["closure_decision"] == pipeline["closure_decision"]
        finally:
            db.close()

    def test_receipt_store_persistence_is_content_addressed(self, wiring_repo):
        store_dir = wiring_repo / ".sot" / "receipts"
        service = self._service(wiring_repo)
        try:
            first = service.diff_impact_receipt()
            assert (store_dir / f"{first['digest']}.json").is_file()
            # Same request → same address, no duplicate file.
            second = service.diff_impact_receipt()
            assert second["digest"] == first["digest"]
            assert ReceiptStore(store_dir).list_digests() == [first["digest"]]
            # The store holds the canonical (volatile-stripped) form.
            loaded = ReceiptStore(store_dir).get(first["digest"])
            assert loaded["request"]["target"] == "HEAD"
        finally:
            service.close()

    def test_mcp_diff_impact_envelope_projects_receipt(self, wiring_repo):
        service = self._service(wiring_repo)
        try:
            res = service.diff_impact(target="HEAD", format="markdown")
            for key in (
                "ok", "status", "target", "depth", "format", "providers",
                "summary", "result", "snapshot", "stale_files", "markdown",
                "assurance", "assurance_facts", "digest",
            ):
                assert key in res, f"missing envelope key: {key}"
            assert res["ok"] is True and res["status"] == "success"
            assert "# SOT-Graph Diff Impact Analysis Report" in res["markdown"]
            assert res["result"]["summary"] == res["summary"]
            assert isinstance(res["assurance"]["status"], str)
            assert res["assurance_facts"] == res.get("assurance_facts")
        finally:
            service.close()

    def test_mcp_diff_impact_trim_degrades_embedded_assurance(self, wiring_repo):
        from sot_graph.mcp_service import McpService, ServiceLimits

        service = McpService(
            db_path=str(wiring_repo / ".sot" / "sot.db"),
            project_root=str(wiring_repo),
            limits=ServiceLimits(response_bytes=3200),
        )
        try:
            res = service.diff_impact(target="HEAD", format="json")
            assert res.get("truncated") is True
            # SG-104 invariant protects the projected envelope too.
            assert res["assurance_facts"]["truncated"] is True
            assert "transitive_truncated" in res["assurance"]["reason_codes"]
            assert res["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
            assert res["digest"] == receipt_digest(
                {k: v for k, v in res.items() if k != "digest"}
            )
        finally:
            service.close()

    def test_cli_gate_semantics_unchanged(self, wiring_repo):
        from sot_graph.assurance.state import ASSURED_STATUSES

        db = _db_of(wiring_repo)
        try:
            out = self._cli_json(wiring_repo, db, "--gate")
            status = out["envelope"]["assurance"]["status"]
            assert out["code"] == (0 if status in ASSURED_STATUSES else 1)
        finally:
            db.close()

    def test_cli_request_block_reflects_auto_reconcile_flag(self, wiring_repo):
        # Mutates graph journals via a real reconcile — keep last.
        db = _db_of(wiring_repo)
        try:
            out = self._cli_json(wiring_repo, db)
            assert out["code"] == 0
            assert out["envelope"]["request"]["auto_reconcile"] is False
            out = self._cli_json(wiring_repo, db, "--auto-reconcile")
            assert out["code"] == 0
            assert out["envelope"]["request"]["auto_reconcile"] is True
        finally:
            db.close()


# ---------------------------------------------------------------------------
# SG-105 part C — exit-gate test suite (parity, surface faults, guards,
# store contract). Shared surface helpers below mirror the ones inside
# TestSurfaceWiring but are module-level so every part C class reuses them.
# ---------------------------------------------------------------------------


def _service_of(repo: Path):
    from sot_graph.mcp_service import McpService

    return McpService(
        db_path=str(repo / ".sot" / "sot.db"),
        project_root=str(repo),
    )


def _cli_diff_json(repo: Path, db, *extra: str) -> dict:
    """Run the real ``diff-impact --format json`` CLI projection in-process."""
    from sot_graph.cli import build_parser, cmd_diff_impact

    args = build_parser().parse_args(["diff-impact", "--format", "json", *extra])
    buf = io.StringIO()
    with mock.patch("sys.stdout", buf):
        code = cmd_diff_impact(args, db, str(repo))
    return {"code": code, "envelope": json.loads(buf.getvalue())}


def _cli_extra_args(req_kwargs: dict) -> list:
    """Translate executor request kwargs into the equivalent CLI flags."""
    extra = []
    target = req_kwargs.get("target", "HEAD")
    if target != "HEAD":
        extra.append(target)
    if req_kwargs.get("depth", 2) != 2:
        extra += ["--depth", str(req_kwargs["depth"])]
    if req_kwargs.get("staged"):
        extra.append("--staged")
    if req_kwargs.get("working_tree"):
        extra.append("--working-tree")
    return extra


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message)


def _rev_parse(repo: Path, rev: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", rev], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


_C2_UTIL = "def help():\n    return 42\n"
_C3_APP = "import util\n\ndef run():\n    return util.help() + 2\n"


def _parity_repo(mode: str, root: Path):
    """Fresh fixture repo per parity mode + the executor request kwargs.

    Each mode ends in a quiescent state (commits reconciled, or the
    uncommitted change sitting in the index/worktree) so all three
    surfaces observe the SAME repo/db content. A fresh repo per mode
    keeps the CLI's evidence-staleness mutations (it marks cited files
    stale in the DB after its receipt is built) from bleeding across
    cases.
    """
    repo = _make_repo(root)  # c1, reconciled
    if mode == "single_rev_head":
        (repo / "util.py").write_text(_C2_UTIL, encoding="utf-8")
        _commit_all(repo, "c2")
        _reconcile(repo)
        return repo, {"target": "HEAD"}
    if mode == "explicit_range":
        (repo / "util.py").write_text(_C2_UTIL, encoding="utf-8")
        _commit_all(repo, "c2")
        (repo / "app.py").write_text(_C3_APP, encoding="utf-8")
        _commit_all(repo, "c3")
        _reconcile(repo)
        return repo, {
            "target": f"{_rev_parse(repo, 'HEAD~2')}...{_rev_parse(repo, 'HEAD')}",
        }
    if mode == "staged":
        (repo / "util.py").write_text(_C2_UTIL, encoding="utf-8")
        _git(repo, "add", "util.py")  # staged, NOT committed
        return repo, {"target": "HEAD", "staged": True}
    if mode == "working_tree":
        (repo / "app.py").write_text(_C3_APP, encoding="utf-8")  # unstaged
        return repo, {"target": "HEAD", "working_tree": True}
    if mode == "rename_commit":
        _git(repo, "mv", "util.py", "helper.py")
        # git diff enables rename detection by default: a 100%-similar
        # rename emits no @@ hunks and the hunk-based engine would see an
        # empty diff — change the content so the rename carries a real one.
        (repo / "helper.py").write_text(_C2_UTIL, encoding="utf-8")
        _commit_all(repo, "rename util -> helper")
        _reconcile(repo)
        return repo, {"target": "HEAD"}
    if mode == "delete_commit":
        _git(repo, "rm", "-q", "tests/test_app.py")
        _commit_all(repo, "delete tracked test")
        _reconcile(repo)
        return repo, {"target": "HEAD"}
    if mode == "empty_diff":
        return repo, {"target": "HEAD...HEAD"}
    raise AssertionError(f"unknown parity mode: {mode}")


_PARITY_MODES = (
    "single_rev_head",
    "explicit_range",
    "staged",
    "working_tree",
    "rename_commit",
    "delete_commit",
    "empty_diff",
)


class TestParityMatrix:
    """SG-105 part C — THE exit gate: ONE digest per evidenced state.

    For the SAME request the three surfaces — ``run_impact_claim``
    (direct executor), the CLI ``diff-impact --format json`` projection,
    and ``McpService.diff_impact_receipt`` — must return the SAME
    digest, and the executor must be deterministic across consecutive
    calls. Every mode runs on a FRESH fixture repo; within one test the
    order is executor (x2) → MCP → CLI, CLI last: none of the surfaces
    mutate repo content, but the CLI marks cited evidence stale in the
    DB after its receipt is built (see the note on TestSurfaceWiring).
    """

    @pytest.mark.parametrize("mode", _PARITY_MODES)
    def test_digest_parity_executor_mcp_cli(self, mode, tmp_path):
        repo, req_kwargs = _parity_repo(mode, tmp_path / f"parity-{mode}")
        request = ImpactClaimRequest(**req_kwargs)
        db = _db_of(repo)
        try:
            first = run_impact_claim(request, db, str(repo))
            second = run_impact_claim(request, db, str(repo))
            service = _service_of(repo)
            try:
                mcp = service.diff_impact_receipt(
                    target=req_kwargs.get("target", "HEAD"),
                    staged=bool(req_kwargs.get("staged")),
                    working_tree=bool(req_kwargs.get("working_tree")),
                )
            finally:
                service.close()
            cli = _cli_diff_json(repo, db, *_cli_extra_args(req_kwargs))
        finally:
            db.close()

        if mode == "empty_diff":
            assert first["changed_files"] == [], (
                "fixture broken: HEAD...HEAD must be an empty diff"
            )
        else:
            assert first["changed_files"], (
                f"fixture broken: mode {mode} produced no diff"
            )
        assert first["digest"] == second["digest"], (
            "run_impact_claim is not deterministic: two consecutive calls "
            "on an unchanged repo produced different digests"
        )
        assert cli["code"] == 0, (
            "CLI diff-impact --format json must exit 0 in advisory mode"
        )
        assert mcp["digest"] == first["digest"], (
            f"parity broken [{mode}]: McpService.diff_impact_receipt digest "
            f"{mcp['digest']} != executor digest {first['digest']}"
        )
        assert cli["envelope"]["digest"] == first["digest"], (
            f"parity broken [{mode}]: CLI diff-impact json digest "
            f"{cli['envelope']['digest']} != executor digest {first['digest']}"
        )


class TestSurfaceFaultInjection:
    """Swallowed collection faults degrade through the SURFACES too.

    Part A proved the executor's degradation at the DB-connection seam;
    part C re-proves it through a real McpService.diff_impact_receipt
    call and a real CLI cmd_diff_impact invocation. Seam note: the diff
    receipt's collection query is the invalidated-evidence lookup
    (``snapshot_hash FROM provider_evidence`` — part A's
    test_evidence_fault_degrades_diff_receipt). ``_edges_of`` only serves
    the pre-change scope_receipt path, so its SQL prefix never fires on
    this path; tripping it here would leave the receipt ASSURED and prove
    nothing. Expected outcome on both surfaces: normal return (tool ok /
    CLI exit 0 advisory), assurance.status == UNVERIFIABLE, reason_codes
    containing ``collection_error``, one machine-readable
    ``collection_error:provider_evidence:...`` warning — never ASSURED,
    never a crash.
    """

    def _faulty_repo(self, root: Path) -> Path:
        repo = _make_repo(root)
        # Uncommitted change → non-empty working-tree diff → the cited
        # files actually reach the faulted collection query.
        (repo / "util.py").write_text(_C2_UTIL, encoding="utf-8")
        return repo

    def test_mcp_diff_impact_receipt_degrades_on_collection_fault(
        self, tmp_path
    ):
        from sot_graph import mcp_service

        repo = self._faulty_repo(tmp_path / "fault-mcp")
        service = _service_of(repo)
        real_view = mcp_service._ConnView

        def _trip(sql: str) -> bool:
            # Literal prefix-free match: only the receipt's invalidated-
            # evidence query selects 'snapshot_hash FROM provider_evidence'
            # without a JOIN (union_evidence's ledger SQL joins provider_runs).
            return "snapshot_hash FROM provider_evidence" in sql

        class _FaultyView(real_view):
            def __init__(self, conn):
                super().__init__(_FaultyConn(conn, _trip))

        try:
            with mock.patch.object(mcp_service, "_ConnView", _FaultyView):
                # Must return normally — a raise here IS the failure.
                payload = service.diff_impact_receipt(working_tree=True)
        finally:
            service.close()

        assert payload["changed_files"], "fixture broken: empty diff"
        assert payload["assurance"]["status"] == "UNVERIFIABLE"
        assert payload["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
        assert "collection_error" in payload["assurance"]["reason_codes"]
        assert payload["assurance_facts"]["collection_error"] is True
        warnings = [
            w for w in payload["warnings"]
            if w.startswith("collection_error:provider_evidence:")
        ]
        assert warnings, "machine-readable collection warning not recorded"
        assert "injected storage fault" in warnings[0]
        # The receipt itself still completes: address + request intact.
        assert len(payload["digest"]) == 64
        assert payload["request"]["working_tree"] is True

    def test_cli_diff_impact_degrades_on_collection_fault(self, tmp_path):
        repo = self._faulty_repo(tmp_path / "fault-cli")
        db = _db_of(repo)
        real = db.conn
        db.conn = _FaultyConn(
            real,
            lambda sql: "snapshot_hash FROM provider_evidence" in sql,
        )
        try:
            out = _cli_diff_json(repo, db, "--working-tree")
        finally:
            db.conn = real
            db.close()

        envelope = out["envelope"]
        assert envelope["changed_files"], "fixture broken: empty diff"
        # Advisory mode: degraded evidence exits 0, never crashes.
        assert out["code"] == 0
        assert envelope["assurance"]["status"] == "UNVERIFIABLE"
        assert envelope["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
        assert "collection_error" in envelope["assurance"]["reason_codes"]
        assert any(
            w.startswith("collection_error:provider_evidence:")
            for w in envelope["warnings"]
        )
        assert len(envelope["digest"]) == 64


class TestArchitectureGuard:
    """Regression tripwire: no surface runs its own engine/receipt path.

    SG-105's whole point is ONE executor (``run_impact_claim``) with
    CLI/MCP as projections. If any of these assertions fails, a surface
    has regrown a private diff-impact/receipt path and the parity matrix
    above is no longer guaranteed by construction.
    """

    def test_mcp_service_has_no_private_diff_engine(self):
        src = (
            Path(__file__).resolve().parent.parent
            / "src" / "sot_graph" / "mcp_service.py"
        ).read_text(encoding="utf-8")
        assert "DiffImpactEngine" not in src, (
            "mcp_service.py references DiffImpactEngine directly; MCP "
            "diff tools must build their receipt via "
            "run_impact_claim (impact_pipeline), never their own engine"
        )

    def test_cli_diff_impact_has_no_private_receipt_path(self):
        from sot_graph import cli

        src = inspect.getsource(cli.cmd_diff_impact)
        assert "diff_impact_receipt(" not in src, (
            "cmd_diff_impact calls assurance.receipts.diff_impact_receipt "
            "directly; it must go through run_impact_claim so the "
            "request/projection augmentation and digest stay canonical"
        )
        assert "run_impact_claim" in src, (
            "cmd_diff_impact no longer invokes the ONE executor "
            "(run_impact_claim); the CLI has regrown a private pipeline"
        )

    def test_mcp_diff_impact_receipt_goes_through_executor(self):
        from sot_graph.mcp_service import McpService

        src = inspect.getsource(McpService.diff_impact_receipt)
        assert "run_impact_claim" in src, (
            "McpService.diff_impact_receipt no longer invokes the ONE "
            "executor (run_impact_claim); the MCP surface has regrown a "
            "private receipt path and surface parity is not guaranteed"
        )


class TestReceiptStoreContract:
    """Store-level contract additions (part C).

    Put-immutability (second put is a no-op that never overwrites) and
    tamper-on-get integrity failure are already locked by TestReceiptStore
    (test_second_put_is_noop_never_overwrite,
    test_tampered_file_fails_integrity_on_get); the tests here close the
    remaining gaps: put-twice yields exactly ONE file, and
    ``list_digests`` reflects the exact stored address set.
    """

    def test_put_twice_writes_exactly_one_file(self, impact_repo, tmp_path):
        store = ReceiptStore(tmp_path / "store")
        db = _db_of(impact_repo)
        try:
            receipt = run_impact_claim(ImpactClaimRequest(), db, str(impact_repo))
        finally:
            db.close()
        first = store.put(receipt)
        second = store.put(receipt)
        assert first == second == receipt["digest"]
        assert [p.name for p in sorted(store.directory.iterdir())] == [
            f"{first}.json"
        ]
        assert store.list_digests() == [first]

    def test_list_digests_reflects_exact_stored_set(self, impact_repo, tmp_path):
        store = ReceiptStore(tmp_path / "store")
        db = _db_of(impact_repo)
        try:
            base = run_impact_claim(ImpactClaimRequest(), db, str(impact_repo))
            # Distinct request block (depth) → distinct content address,
            # even though the measured diff is unchanged.
            other = run_impact_claim(
                ImpactClaimRequest(depth=3), db, str(impact_repo)
            )
        finally:
            db.close()
        assert base["digest"] != other["digest"], (
            "distinct request blocks must produce distinct addresses"
        )
        d1, d2 = store.put(base), store.put(other)
        assert store.list_digests() == sorted([d1, d2])
        # Every listed address loads and verifies against its name.
        for digest in store.list_digests():
            assert receipt_digest(store.get(digest)) == digest
