"""SG-107 — collection cap accounting (schema 1.4).

Locks:
- Every capped collector REPORTS its cap accounting: the TRUE enumerated
  row count (twin COUNT over the same WHERE, no LIMIT) next to what the
  cap let through, with derived truncated / cursor_exhausted flags, in
  the receipt's ``collection_stats`` block (per-cap-site tests: edges
  501→500, provider_evidence 51→50, provider_runs 201→200).
- A collection that actually cut emits a named source in
  ``facts.truncation_sources`` and the ``collection_truncated:<source>``
  reason code, degrading the verdict to at most PARTIAL. Under-cap
  collections are reported fully drained and cause no degradation.
- ``reconcile_provenance`` states WHERE reconciliation happened:
  "pipeline" (executor/CLI) vs "surface_pre" (MCP diff_impact writer
  path) — and is digest-affecting by design.
- Receipt digests are stable across identical runs (schema 1.4). Note:
  1.4 digests intentionally differ from 1.3 — the schema added
  ``request.reconcile_provenance``, ``facts.truncation_sources`` and
  per-collector ``collection_stats``, so every receipt's content address
  changed. That is expected, not a regression.
- Transport trimming of an ALREADY collection-truncated receipt keeps
  the WORSE numbers: a transport cut never shrinks a true enumerated
  count to hide a cap cut (build_projection folds transport_truncation
  additively; the trimmer's honest collection_stats compaction keeps
  the true counts and the truncation flags).
"""

from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from sot_graph.assurance.impact_pipeline import build_projection
from sot_graph.assurance.receipts import (
    RECEIPT_SCHEMA_VERSION,
    diff_impact_receipt,
    receipt_digest,
    scope_receipt,
)
from sot_graph.assurance.state import STATUS_SEVERITY


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _db_of(repo: Path):
    from sot_graph.db import Database

    return Database(str(repo / ".sot" / "sot.db"))


def _make_repo(repo: Path) -> Path:
    from test_impact_pipeline import _make_repo as _mk

    return _mk(repo)


@pytest.fixture(scope="module")
def edges_repo(tmp_path_factory) -> Path:
    # Over-cap repo: 501 direct callers of "run" (plus the fixture's own
    # run -> help out-edge), so _edges_of's LIMIT 500 actually cuts.
    repo = _make_repo(tmp_path_factory.mktemp("edges501"))
    db = _db_of(repo)
    try:
        node_id = db.get_node_by_symbol("run")["id"]
        now = 1_700_000_000
        db.conn.executemany(
            "INSERT INTO graph_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (f"caller_{i}", f"src/caller_{i}.py", "function",
                 f"caller_fn_{i}", f"caller_fn_{i}", None, "def", "x",
                 None, 1, 2, None, None, now)
                for i in range(501)
            ],
        )
        db.conn.executemany(
            "INSERT INTO graph_edges VALUES (?,?,?,?,?)",
            [
                (f"src/caller_{i}.py", f"caller_{i}", node_id, "calls", i)
                for i in range(501)
            ],
        )
        db.conn.commit()
    finally:
        db.close()
    return repo


@pytest.fixture(scope="module")
def evidence_repo(tmp_path_factory) -> Path:
    # Over-cap repo: 51 provider_evidence rows bound to one changed path
    # (app.py), so the per-path LIMIT 50 actually cuts.
    repo = _make_repo(tmp_path_factory.mktemp("evid51"))
    db = _db_of(repo)
    try:
        # provider_evidence.run_id FK -> seed the owning run row first.
        db.conn.execute(
            "INSERT INTO provider_runs "
            "(id, provider_name, provider_version, capability, snapshot_hash,"
            " project_root, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            ("run_x", "prov", "1.0", "AST_HEURISTIC_PARSER", None,
             os.path.realpath(repo), "ok", 1_700_000_000),
        )
        db.conn.executemany(
            "INSERT INTO provider_evidence "
            "(id, run_id, provider_name, path, src_symbol, relation, "
            " created_at) VALUES (?,?,?,?,?,?,?)",
            [
                (f"ev_{i}", "run_x", "prov", "app.py", "caller_x",
                 "calls", 1_700_000_000 + i)
                for i in range(51)
            ],
        )
        db.conn.commit()
    finally:
        db.close()
    return repo


@pytest.fixture(scope="module")
def runs_repo(tmp_path_factory) -> Path:
    # Over-cap repo: 201 provider_runs for this project root, so the
    # recent-runs LIMIT 200 actually cuts.
    repo = _make_repo(tmp_path_factory.mktemp("runs201"))
    db = _db_of(repo)
    try:
        db.conn.executemany(
            "INSERT INTO provider_runs "
            "(id, provider_name, provider_version, capability, snapshot_hash,"
            " project_root, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            [
                (f"run_{i}", "prov", "1.0", "AST_HEURISTIC_PARSER", None,
                 os.path.realpath(repo), "ok", 1_700_000_000 + i)
                for i in range(201)
            ],
        )
        db.conn.commit()
    finally:
        db.close()
    return repo


def _severe(status: str) -> int:
    return STATUS_SEVERITY[status]


class TestEdgesCapAccounting:
    def test_over_cap_reports_true_enumerated_and_degrades(self, edges_repo):
        db = _db_of(edges_repo)
        try:
            node_id = db.get_node_by_symbol("run")["id"]
            # Live ground truth per direction (the fixture's own edges
            # plus 501 seeded callers): the merged stats must equal the
            # uncapped COUNT pair with the per-query cap applied.
            in_total = int(db.conn.execute(
                "SELECT COUNT(*) FROM graph_edges WHERE dst = ?",
                (node_id,),
            ).fetchone()[0])
            out_total = int(db.conn.execute(
                "SELECT COUNT(*) FROM graph_edges WHERE src = ?",
                (node_id,),
            ).fetchone()[0])
            assert in_total >= 501  # the seeding actually happened
            payload = scope_receipt(db, str(edges_repo), "run")
        finally:
            db.close()
        stats = payload["collection_stats"]["direct_edges"]
        # TRUE totals on both directions; the cap let only 500 of the
        # in-direction rows through — the cut is visible, never read as
        # "no more callers".
        assert stats["enumerated_count"] == in_total + out_total
        assert stats["returned_count"] == min(in_total, 500) + min(out_total, 500)
        assert stats["returned_count"] < stats["enumerated_count"]
        assert stats["cap"] == 500
        assert stats["truncated"] is True
        assert stats["cursor_exhausted"] is False
        assert "edges_cap_500" in payload["assurance_facts"]["truncation_sources"]
        reason = "collection_truncated:edges_cap_500"
        assert reason in payload["assurance"]["reason_codes"]
        assert _severe(payload["assurance"]["status"]) >= _severe("PARTIAL")

    def test_under_cap_fully_drained_no_degradation(self, edges_repo):
        repo = _make_repo(edges_repo.parent / "edges_under")
        db = _db_of(repo)
        try:
            node_id = db.get_node_by_symbol("run")["id"]
            total = _direct_edge_total(db, node_id)
            assert 0 < total < 500  # genuinely under the cap
            payload = scope_receipt(db, str(repo), "run")
        finally:
            db.close()
        stats = payload["collection_stats"]["direct_edges"]
        assert stats["truncated"] is False
        assert stats["cursor_exhausted"] is True
        assert stats["enumerated_count"] == stats["returned_count"] == total
        assert "edges_cap_500" not in payload["assurance_facts"]["truncation_sources"]
        assert "collection_truncated:edges_cap_500" not in (
            payload["assurance"]["reason_codes"]
        )


class TestEvidenceCapAccounting:
    def test_over_cap_reports_true_enumerated_and_degrades(self, evidence_repo):
        db = _db_of(evidence_repo)
        try:
            payload = diff_impact_receipt(db, str(evidence_repo))
        finally:
            db.close()
        stats = payload["collection_stats"]["invalidated_evidence"]
        assert stats["enumerated_count"] == 51
        assert stats["returned_count"] == 50
        assert stats["cap"] == 50
        assert stats["truncated"] is True
        assert stats["cursor_exhausted"] is False
        assert "evidence_cap_50" in payload["assurance_facts"]["truncation_sources"]
        reason = "collection_truncated:evidence_cap_50"
        assert reason in payload["assurance"]["reason_codes"]
        assert _severe(payload["assurance"]["status"]) >= _severe("PARTIAL")

    def test_under_cap_fully_drained_no_degradation(self, evidence_repo):
        # Same fixture shape, but the pristine repo has 0 evidence rows:
        # a short page is exact by construction (no twin COUNT needed).
        repo = _make_repo(evidence_repo.parent / "evid_under")
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo))
        finally:
            db.close()
        stats = payload["collection_stats"]["invalidated_evidence"]
        assert stats["truncated"] is False
        assert stats["cursor_exhausted"] is True
        assert stats["enumerated_count"] == stats["returned_count"] == 0
        assert "evidence_cap_50" not in payload["assurance_facts"]["truncation_sources"]
        assert "collection_truncated:evidence_cap_50" not in (
            payload["assurance"]["reason_codes"]
        )


def _direct_edge_total(db, node_id: str) -> int:
    """Live ground truth: both directions joined to the node, uncapped."""
    return int(db.conn.execute(
        "SELECT COUNT(*) FROM graph_edges e "
        "WHERE e.src = ? OR e.dst = ?",
        (node_id, node_id),
    ).fetchone()[0])


class TestLedgerRunsCapAccounting:
    def test_over_cap_reports_true_enumerated_and_degrades(self, runs_repo):
        db = _db_of(runs_repo)
        try:
            payload = scope_receipt(db, str(runs_repo), "run")
        finally:
            db.close()
        stats = payload["collection_stats"]["ledger_runs"]
        assert stats["enumerated_count"] == 201
        assert stats["returned_count"] == 200
        assert stats["cap"] == 200
        assert stats["truncated"] is True
        assert stats["cursor_exhausted"] is False
        assert "ledger_runs_cap_200" in payload["assurance_facts"]["truncation_sources"]
        reason = "collection_truncated:ledger_runs_cap_200"
        assert reason in payload["assurance"]["reason_codes"]
        assert _severe(payload["assurance"]["status"]) >= _severe("PARTIAL")

    def test_under_cap_fully_drained_no_degradation(self, runs_repo):
        repo = _make_repo(runs_repo.parent / "runs_under")
        db = _db_of(repo)
        try:
            payload = scope_receipt(db, str(repo), "run")
        finally:
            db.close()
        stats = payload["collection_stats"]["ledger_runs"]
        assert stats["truncated"] is False
        assert stats["cursor_exhausted"] is True
        assert stats["enumerated_count"] == stats["returned_count"] == 0
        assert "ledger_runs_cap_200" not in (
            payload["assurance_facts"]["truncation_sources"]
        )


class TestReconcileProvenance:
    def test_pipeline_run_records_pipeline_provenance(self, tmp_path):
        repo = _make_repo(tmp_path / "prov_repo")
        from sot_graph.assurance.impact_pipeline import (
            ImpactClaimRequest,
            run_impact_claim,
        )

        db = _db_of(repo)
        try:
            receipt = run_impact_claim(ImpactClaimRequest(), db, str(repo))
            assert receipt["request"]["reconcile_provenance"] == "pipeline"
        finally:
            db.close()

    def test_cli_records_pipeline_provenance(self, tmp_path):
        repo = _make_repo(tmp_path / "prov_cli")
        from sot_graph.cli import build_parser, cmd_diff_impact

        db = _db_of(repo)
        try:
            args = build_parser().parse_args(
                ["diff-impact", "--format", "json"]
            )
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                code = cmd_diff_impact(args, db, str(repo))
            assert code == 0
            envelope = json.loads(buf.getvalue())
            assert envelope["request"]["reconcile_provenance"] == "pipeline"
        finally:
            db.close()

    def test_mcp_auto_reconcile_records_surface_pre(self, tmp_path):
        repo = _make_repo(tmp_path / "prov_mcp")
        from sot_graph.mcp_service import McpService
        from sot_graph.reconciler import ReconcileSummary

        captured = {}
        real = None
        from sot_graph.assurance import impact_pipeline as ip

        real = ip.run_impact_claim

        def spy(request, db, repo_root):
            captured["request"] = request
            return real(request, db, repo_root)

        service = McpService(
            db_path=str(repo / ".sot" / "sot.db"),
            project_root=str(repo),
        )
        try:
            # The surface reconciled on the writer path BEFORE the
            # executor ran -> the receipt must say "surface_pre".
            with mock.patch.object(ip, "run_impact_claim", spy), \
                 mock.patch(
                     "sot_graph.reconciler.Reconciler.reconcile",
                     return_value=ReconcileSummary(1, 1, 0, 0, 0, 0),
                 ):
                service.diff_impact(target="HEAD", auto_reconcile=True,
                                    format="json")
            assert captured["request"].reconcile_provenance == "surface_pre"

            # Without the writer-path reconcile the executor owns it.
            captured.clear()
            with mock.patch.object(ip, "run_impact_claim", spy):
                service.diff_impact(target="HEAD", auto_reconcile=False,
                                    format="json")
            assert captured["request"].reconcile_provenance == "pipeline"
        finally:
            service.close()


class TestDigestStability:
    def test_identical_runs_same_digest_schema_14(self, tmp_path):
        # Schema 1.4 digests intentionally differ from 1.3 (new request
        # field, truncation_sources, collection_stats) — but two runs
        # over the same evidenced state must produce the SAME digest.
        repo = _make_repo(tmp_path / "digest_repo")
        from sot_graph.assurance.impact_pipeline import (
            ImpactClaimRequest,
            run_impact_claim,
        )

        db = _db_of(repo)
        try:
            first = run_impact_claim(ImpactClaimRequest(), db, str(repo))
            second = run_impact_claim(ImpactClaimRequest(), db, str(repo))
        finally:
            db.close()
        assert first["schema_version"] == RECEIPT_SCHEMA_VERSION == "1.6"
        assert second["digest"] == first["digest"]
        assert first["digest"]


class TestTransportTrimInterplay:
    def test_projection_folds_transport_cut_additively(self):
        # Unit lock of the worse-numbers fold: the receipt was cut by
        # its COLLECTOR cap (250 enumerated / 200 returned) and then cut
        # AGAIN for transport (3 seen / 1 returned). The projection must
        # keep the true enumerated count (250, never 3) and the worse
        # returned count.
        receipt = {
            "changed_files": [f"f{i}.py" for i in range(3)],
            "collection_stats": {
                "changed_files": {
                    "enumerated_count": 250,
                    "returned_count": 200,
                    "cap": 200,
                    "truncated": True,
                    "cursor_exhausted": False,
                },
            },
            "transport_truncation": {
                "text_truncated": False,
                "collections": [
                    {"container": "root", "key": "changed_files",
                     "enumerated_count": 3, "returned_count": 1},
                ],
            },
        }
        projection = build_projection(receipt)
        entry = next(
            c for c in projection["collections"] if c["key"] == "changed_files"
        )
        assert entry["enumerated_count"] == 250  # a trim never shrinks it
        # worse of the two returned counts: collector 200 vs transport 1
        assert entry["returned_count"] == 1
        assert entry["truncated"] is True
        assert entry["cursor_exhausted"] is False

    def test_collection_truncated_receipt_survives_transport_trim(
        self, tmp_path
    ):
        # End-to-end: a receipt that is BOTH collection-truncated (201
        # changed files > cap 200; 51 evidence rows > cap 50 on one
        # path) AND transport-trimmed (tiny response budget). The worse
        # numbers must survive the transport cut: enumerated counts stay
        # true, truncation flags stay, verdict stays non-ASSURED.
        repo = _make_repo(tmp_path / "trim201")
        for i in range(201):
            (repo / f"mod_{i:03}.py").write_text(
                f"def fn_{i}():\n    return {i}\n", encoding="utf-8"
            )
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c2")
        db = _db_of(repo)
        try:
            # provider_evidence.run_id FK -> seed the owning run row.
            db.conn.execute(
                "INSERT INTO provider_runs "
                "(id, provider_name, provider_version, capability, snapshot_hash,"
                " project_root, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                ("run_x", "prov", "1.0", "AST_HEURISTIC_PARSER", None,
                 os.path.realpath(repo), "ok", 1_700_000_000),
            )
            db.conn.executemany(
                "INSERT INTO provider_evidence "
                "(id, run_id, provider_name, path, src_symbol, relation, "
                " created_at) VALUES (?,?,?,?,?,?,?)",
                [
                    (f"ev_{i}", "run_x", "prov", "mod_000.py", "caller_x",
                     "calls", 1_700_000_000 + i)
                    for i in range(51)
                ],
            )
            db.conn.commit()
            base = diff_impact_receipt(db, str(repo))
            true_changed = base["collection_stats"]["changed_files"]
            true_evidence = base["collection_stats"]["invalidated_evidence"]
            assert true_changed["truncated"] is True
            assert true_evidence["truncated"] is True
        finally:
            db.close()

        from sot_graph.mcp_service import McpService, ServiceLimits

        # Budget floor derivation (environment-independent): first
        # capture the EXACT payload the service would trim (huge budget,
        # spy on _fits_response), then compute the least form the
        # trimmer can HONESTLY emit — top-level trimmable lists emptied
        # (Phase 1 scope: root and ``result``) and the collection_stats
        # detail compacted. The post_change_snapshot's per-file content
        # digests and facts.stale_files are state the trimmer cannot
        # drop without changing what the receipt attests. The real
        # budget sits just above that floor, so the transport cut really
        # fires and the trim provably converges.
        LIST_KEYS = [
            "caller_impacts", "test_impacts", "direct_nodes", "api_impacts",
            "invalidated_evidence", "results", "drift", "relations",
            "nodes", "edges", "changed_files", "commits", "timeline",
            "impacted", "affected_tests", "affected_files",
            "candidate_tests", "callers", "callees", "transitive", "runs",
            "hunks", "stale_files", "quarantined_files",
            "unsupported_constructs", "parser_error_files",
            "source_anchors", "tests_to_run",
        ]

        def _enc(v: Any) -> int:
            return len(
                json.dumps(v, ensure_ascii=False, separators=(",", ":")).encode()
            )

        def _honest_floor(payload: Dict[str, Any]) -> int:
            sk = copy.deepcopy(payload)
            for k in LIST_KEYS:
                if isinstance(sk.get(k), list) and sk[k]:
                    sk[k] = []
            for name, st in (sk.get("collection_stats") or {}).items():
                if isinstance(st, dict):
                    sk["collection_stats"][name] = {
                        "enumerated_count": st.get("enumerated_count"),
                        "returned_count": st.get("returned_count"),
                        "truncated": st.get("truncated"),
                    }
            return _enc(sk)

        captured: Any = {}
        real_fits = McpService._fits_response

        def _spy(svc, value):
            captured["v"] = value
            return real_fits(svc, value)

        def _service(budget: int) -> McpService:
            return McpService(
                db_path=str(repo / ".sot" / "sot.db"),
                project_root=str(repo),
                limits=ServiceLimits(response_bytes=budget),
            )

        try:
            with mock.patch.object(McpService, "_fits_response", _spy):
                service = _service(64 * 1024 * 1024)
                try:
                    service.diff_impact_receipt()
                finally:
                    service.close()
            whole = captured["v"]
            floor = _honest_floor(whole)
            assert _enc(whole) > floor + 2048  # a real transport cut fires
            service = _service(floor + 2048)
            try:
                res = service.diff_impact_receipt()
            finally:
                service.close()
        finally:
            McpService._fits_response = real_fits
        assert res.get("truncated") is True  # transport cut happened
        stats = res["collection_stats"]
        # The trimmer may compact the stats detail (drop cap /
        # cursor_exhausted), but the true enumerated counts and the
        # truncation flags must survive untouched.
        assert stats["changed_files"]["enumerated_count"] == (
            true_changed["enumerated_count"]
        )
        assert stats["changed_files"]["enumerated_count"] > 200
        assert stats["changed_files"]["truncated"] is True
        assert stats["invalidated_evidence"]["enumerated_count"] == 51
        assert stats["invalidated_evidence"]["truncated"] is True
        # The projection (computed over TRUE collector stats) never
        # mistakes the transport-trimmed payload list for the truth.
        changed = next(
            c for c in res["projection"]["collections"]
            if c["key"] == "changed_files"
        )
        assert changed["enumerated_count"] == true_changed["enumerated_count"]
        assert changed["truncated"] is True
        # The degradation block survives the trim and names both cuts.
        assert res["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
        codes = res["assurance"]["reason_codes"]
        assert "collection_truncated:changed_files_cap_200" in codes
        assert "collection_truncated:evidence_cap_50" in codes
        assert res["digest"] == receipt_digest(
            {k: v for k, v in res.items() if k != "digest"}
        )
