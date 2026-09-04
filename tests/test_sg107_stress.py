"""SG-107 part B — issue #2 exit-gate stress suite.

Stresses the SG-107 collection-accounting machinery (part A, schema 1.4)
at issue-#2 scale and locks the no-false-assure invariant across every
surface (executor / CLI json / MCP receipt, plus transport trimming).

Locks:
- Stress matrix at cap scale: 201 changed files in one commit
  (cited 200 / total 201, truncated, digest parity across surfaces),
  501+ edges on one symbol (edges_cap_500), 51 evidence rows on one
  path pair (evidence_cap_50), 5001 provider_evidence rows across paths
  (ledger_union_cap_5000), and the combined worst case where every cap
  that fired names itself in ``facts.truncation_sources`` and no surface
  produces an ASSURED verdict.
- Exit-gate invariant sweep: on EVERY surface, whenever any collection
  is truncated (collection-side or transport-side) the status is never
  ASSURED_WITHIN_SCOPE, the reason codes name the true sources, and
  counts never lie (returned > enumerated or a hidden cut).
- Characterization of part A's three residual risks (pinned as
  documented limitations, named as such — NOT silently blessed):
  nested-list-heavy receipts raise response_too_large (trimmer Phase 1
  only empties top-level + ``result`` lists); eviction is bounded at
  3 re-degrade rounds (``for _round in range(3)``) after which the
  trimmer raises honestly; MCP vs CLI payload normalization is pinned
  field-by-field (digests match; the only additive CLI field is
  ``stale_files``).
- Regression tripwire: every SQL ``LIMIT`` site under
  ``src/sot_graph/assurance/`` must stay in the accounted registry
  (a CollectionStats-reporting cap site) or the known non-truncating
  list, so a new silent cap cannot land unnoticed.
"""

from __future__ import annotations

import copy
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from sot_graph.assurance.impact_pipeline import (
    ImpactClaimRequest,
    run_impact_claim,
)
from sot_graph.assurance.receipts import (
    RECEIPT_SCHEMA_VERSION,
    diff_impact_receipt,
    receipt_digest,
    scope_receipt,
)
from sot_graph.assurance.state import STATUS_SEVERITY

from test_impact_pipeline import _commit_all, _make_repo


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _db_of(repo: Path):
    from sot_graph.db import Database

    return Database(str(repo / ".sot" / "sot.db"))


def _severe(status: str) -> int:
    return STATUS_SEVERITY[status]


def _write_mods(repo: Path, count: int) -> None:
    for i in range(count):
        (repo / f"mod_{i:03d}.py").write_text(
            f"def fn_{i}():\n    return {i}\n", encoding="utf-8"
        )


def _seed_edges(db, prefix: str, n_in: int, n_out: int) -> Tuple[int, int]:
    """Batch-seed n_in callers -> 'run' and 'run' -> n_out callees.

    Returns the live (in_total, out_total) ground truth after seeding.
    ``graph_edges`` columns are (path, src, dst, relation, line); the
    JOIN partners in ``_edges_of`` need graph_nodes rows whose ``id``
    equals the edge's opposite endpoint.
    """
    node_id = db.get_node_by_symbol("run")["id"]
    now = 1_700_000_000
    rows = []
    for i in range(n_in):
        rows.append((f"c_{prefix}{i}", f"src/caller_{prefix}{i}.py",
                     "function", f"caller_fn_{prefix}{i}",
                     f"caller_fn_{prefix}{i}", None, "def", "x",
                     None, 1, 2, None, None, now))
    for i in range(n_out):
        rows.append((f"k_{prefix}{i}", f"src/callee_{prefix}{i}.py",
                     "function", f"callee_fn_{prefix}{i}",
                     f"callee_fn_{prefix}{i}", None, "def", "x",
                     None, 1, 2, None, None, now))
    db.conn.executemany(
        "INSERT INTO graph_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.conn.executemany(
        "INSERT INTO graph_edges VALUES (?,?,?,?,?)",
        [(f"src/caller_{prefix}{i}.py", f"c_{prefix}{i}", node_id,
          "calls", i) for i in range(n_in)]
        + [(f"src/callee_{prefix}{i}.py", node_id, f"k_{prefix}{i}",
            "calls", 10_000 + i) for i in range(n_out)],
    )
    db.conn.commit()
    in_total = int(db.conn.execute(
        "SELECT COUNT(*) FROM graph_edges WHERE dst = ?", (node_id,)
    ).fetchone()[0])
    out_total = int(db.conn.execute(
        "SELECT COUNT(*) FROM graph_edges WHERE src = ?", (node_id,)
    ).fetchone()[0])
    assert in_total >= n_in and out_total >= n_out  # seeding really landed
    return in_total, out_total


def _seed_evidence(db, repo: Path, run_id: str, paths: Iterable[str],
                   per_path: int = 1) -> int:
    """Batch-seed provider_evidence rows bound to a fresh 'ok' run."""
    db.conn.execute(
        "INSERT INTO provider_runs "
        "(id, provider_name, provider_version, capability, snapshot_hash,"
        " project_root, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (run_id, "prov", "1.0", "AST_HEURISTIC_PARSER", None,
         os.path.realpath(repo), "ok", 1_700_000_000),
    )
    rows = []
    n = 0
    for path in paths:
        for _ in range(per_path):
            rows.append((f"ev_{run_id}_{n}", run_id, "prov", path,
                         "caller_x", "calls", 1_700_000_000 + n))
            n += 1
    db.conn.executemany(
        "INSERT INTO provider_evidence "
        "(id, run_id, provider_name, path, src_symbol, relation, "
        " created_at) VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    db.conn.commit()
    return n


def _edge_totals(db, symbol: str = "run") -> Tuple[int, int]:
    node_id = db.get_node_by_symbol(symbol)["id"]
    in_total = int(db.conn.execute(
        "SELECT COUNT(*) FROM graph_edges WHERE dst = ?", (node_id,)
    ).fetchone()[0])
    out_total = int(db.conn.execute(
        "SELECT COUNT(*) FROM graph_edges WHERE src = ?", (node_id,)
    ).fetchone()[0])
    return in_total, out_total


# ---------------------------------------------------------------------------
# Module-scoped stress fixtures (one repo per scenario; batched inserts)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def files201_repo(tmp_path_factory) -> Path:
    """Issue-#2 scale diff: exactly 201 changed files in one commit."""
    repo = _make_repo(tmp_path_factory.mktemp("s107_files201"))
    _write_mods(repo, 201)
    _commit_all(repo, "c2: 201 new modules")
    return repo


@pytest.fixture(scope="module")
def edges_repo(tmp_path_factory) -> Path:
    """501 edges MIXING in/out on one symbol ('run').

    NOTE the cap is PER DIRECTION (one LIMIT 500 query per direction in
    ``_edges_of``), so the in-direction is driven past the cap (501) and
    60 out-edges make the cut visible in the merged, direction-joined
    stats rather than as a one-direction artifact.
    """
    repo = _make_repo(tmp_path_factory.mktemp("s107_edges"))
    db = _db_of(repo)
    try:
        _seed_edges(db, "e", n_in=501, n_out=60)
    finally:
        db.close()
    return repo


@pytest.fixture(scope="module")
def evidence51_repo(tmp_path_factory) -> Path:
    """51 provider_evidence rows for one path pair (app.py)."""
    repo = _make_repo(tmp_path_factory.mktemp("s107_evid51"))
    db = _db_of(repo)
    try:
        _seed_evidence(db, repo, "run_ev", ["app.py"], per_path=51)
    finally:
        db.close()
    return repo


@pytest.fixture(scope="module")
def ledger_repo(tmp_path_factory) -> Path:
    """5001 provider_evidence rows across distinct paths.

    Queried with an EMPTY diff target (HEAD...HEAD) so the post-change
    snapshot binds no content and the ledger union runs UNSCOPED (no
    snapshot filter) — the union row cap (5000) is what must fire, while
    the runs window (1 seeded run < 200) must NOT.
    """
    repo = _make_repo(tmp_path_factory.mktemp("s107_ledger"))
    db = _db_of(repo)
    try:
        _seed_evidence(
            db, repo, "run_led",
            (f"led/saturate_{i:05d}.py" for i in range(5001)),
        )
    finally:
        db.close()
    return repo


@pytest.fixture(scope="module")
def combined_repo(tmp_path_factory) -> Path:
    """Worst case: 201-file commit + 501 edges + 51 evidence rows."""
    repo = _make_repo(tmp_path_factory.mktemp("s107_combined"))
    _write_mods(repo, 201)
    _commit_all(repo, "c2: 201 new modules")
    db = _db_of(repo)
    try:
        _seed_edges(db, "x", n_in=501, n_out=60)
        _seed_evidence(db, repo, "run_cx", ["mod_000.py"], per_path=51)
    finally:
        db.close()
    return repo


@pytest.fixture(scope="class")
def plain_repo(tmp_path_factory) -> Path:
    """Minimal repo for synthetic-payload trimmer characterization."""
    return _make_repo(tmp_path_factory.mktemp("s107_plain"))


# ---------------------------------------------------------------------------
# Shared honesty invariants (the exit gate)
# ---------------------------------------------------------------------------

_STATS_TO_SOURCE = {
    # collection_stats key -> the truncation source id its collector emits
    "direct_edges": lambda st: "edges_cap_500",
    "relations": lambda st: "edges_cap_500",
    "transitive": lambda st: "transitive_cap_200",
    "changed_files": lambda st: "changed_files_cap_200",
    "invalidated_evidence": lambda st: "evidence_cap_50",
    "ledger_runs": lambda st: "ledger_runs_cap_200",
    "ledger_union": lambda st: f"ledger_union_cap_{int(st.get('cap') or 0)}",
}


def _assert_honest(payload: Dict[str, Any], expected_sources: Iterable[str],
                   ctx: str) -> None:
    """Exit-gate invariant: a cut is NAMED, DEGRADING, and never lying."""
    expected = set(expected_sources)
    facts = payload.get("assurance_facts") or {}
    assurance = payload.get("assurance") or {}
    codes = list(assurance.get("reason_codes") or [])
    sources = set(facts.get("truncation_sources") or ())

    assert expected <= sources, (
        f"[{ctx}] missing truncation sources: {sorted(expected - sources)} "
        f"(got {sorted(sources)})"
    )
    if sources:
        # a named cut must degrade — never a clean ASSURED
        assert facts.get("truncated") is True, (
            f"[{ctx}] truncation_sources set but facts.truncated is not"
        )
        assert assurance.get("status") != "ASSURED_WITHIN_SCOPE", (
            f"[{ctx}] truncated collection still ASSURED"
        )
        for src in sources:
            code = ("transitive_truncated" if src == "transitive_cap_200"
                    else f"collection_truncated:{src}")
            assert code in codes, (
                f"[{ctx}] source {src} has no reason code {code!r} "
                f"in {codes}"
            )

    stats = payload.get("collection_stats") or {}
    for name, st in stats.items():
        if not isinstance(st, dict):
            continue
        enumerated = int(st.get("enumerated_count") or 0)
        returned = int(st.get("returned_count") or 0)
        assert returned <= enumerated, (
            f"[{ctx}] lying counts: collection_stats.{name} returned "
            f"{returned} > enumerated {enumerated}"
        )
        if st.get("truncated"):
            mapper = _STATS_TO_SOURCE.get(name)
            assert mapper is not None, (
                f"[{ctx}] unaccounted truncated stats block: {name}"
            )
            src_id = mapper(st)
            assert src_id in sources, (
                f"[{ctx}] hidden cut: collection_stats.{name} truncated "
                f"but {src_id!r} not in facts.truncation_sources"
            )
            assert facts.get("truncated") is True

    projection = payload.get("projection")
    if isinstance(projection, dict):
        for entry in projection.get("collections") or []:
            if not isinstance(entry, dict):
                continue
            key = entry.get("key")
            assert int(entry.get("returned_count") or 0) <= int(
                entry.get("enumerated_count") or 0
            ), f"[{ctx}] projection lying for {key}: {entry}"
            st = stats.get(key)
            if isinstance(st, dict):
                # the projection consumes the TRUE collector stats
                assert entry["enumerated_count"] == int(
                    st["enumerated_count"]
                ), (
                    f"[{ctx}] projection ignores true stats for {key}: "
                    f"{entry} vs {st}"
                )
                assert entry["truncated"] == bool(st.get("truncated")), (
                    f"[{ctx}] projection truncation flag drift for {key}"
                )


def _service_of(repo: Path, budget: int = None):
    from sot_graph.mcp_service import McpService, ServiceLimits

    limits = None if budget is None else ServiceLimits(response_bytes=budget)
    return McpService(
        db_path=str(repo / ".sot" / "sot.db"),
        project_root=str(repo),
        limits=limits,
    )


def _cli_diff_json(repo: Path, db, *extra: str) -> Dict[str, Any]:
    from sot_graph.cli import build_parser, cmd_diff_impact

    args = build_parser().parse_args(
        ["diff-impact", "--format", "json", *extra])
    buf = io.StringIO()
    with mock.patch("sys.stdout", buf):
        code = cmd_diff_impact(args, db, str(repo))
    return {"code": code, "envelope": json.loads(buf.getvalue())}


# The trimmer's exact Phase-1 scope (mirrors McpService._fits_response's
# list_keys) — used to derive an environment-independent budget floor.
_TRIMMABLE_LIST_KEYS = [
    "caller_impacts", "test_impacts", "direct_nodes", "api_impacts",
    "invalidated_evidence", "results", "drift", "relations",
    "nodes", "edges", "changed_files", "commits", "timeline",
    "impacted", "affected_tests", "affected_files", "candidate_tests",
    "callers", "callees", "transitive", "runs", "hunks", "stale_files",
    "quarantined_files", "unsupported_constructs", "parser_error_files",
]


def _enc(value: Any) -> int:
    return len(json.dumps(
        value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _honest_floor(payload: Dict[str, Any]) -> int:
    """Least form the trimmer can honestly emit (part A residual #1).

    Phase 1 empties only top-level (and ``result``) lists whose key is
    in ``_TRIMMABLE_LIST_KEYS``; it then compacts collection_stats
    detail. Anything nested deeper is state the trimmer cannot shed.
    """
    skeleton = copy.deepcopy(payload)
    for k in _TRIMMABLE_LIST_KEYS:
        if isinstance(skeleton.get(k), list) and skeleton[k]:
            skeleton[k] = []
    for name, st in (skeleton.get("collection_stats") or {}).items():
        if isinstance(st, dict):
            skeleton["collection_stats"][name] = {
                "enumerated_count": st.get("enumerated_count"),
                "returned_count": st.get("returned_count"),
                "truncated": st.get("truncated"),
            }
    return _enc(skeleton)


def _tight_budget_receipt(repo: Path, **kwargs) -> Tuple[Dict[str, Any],
                                                         Dict[str, Any]]:
    """Run the MCP receipt under a budget derived from the payload floor.

    Returns ``(trimmed, untrimmed)``. Per part A residual risk #1 the
    budget is NEVER hardcoded: it is the minimal honest form of the
    ACTUAL payload plus a small margin, so the transport cut provably
    fires and the trimmer provably converges (or fails honestly).
    """
    from sot_graph.mcp_service import McpService

    captured: Dict[str, Any] = {}
    real_fits = McpService._fits_response

    def _spy(svc, value):
        captured["v"] = value
        return real_fits(svc, value)

    try:
        with mock.patch.object(McpService, "_fits_response", _spy):
            service = _service_of(repo, 64 * 1024 * 1024)
            try:
                service.diff_impact_receipt(**kwargs)
            finally:
                service.close()
        # captured["v"] is the exact pre-trim payload the service saw
        # (the fitting path returns a sanitized COPY, never the same
        # object, so identity does not hold — content equality does).
        untrimmed = captured["v"]
        floor = _honest_floor(untrimmed)
        assert _enc(untrimmed) > floor + 1024, (
            "fixture drift: payload is within 1 KiB of its honest floor; "
            "the transport cut would not fire"
        )
        service = _service_of(repo, floor + 1024)
        try:
            return service.diff_impact_receipt(**kwargs), untrimmed
        finally:
            service.close()
    finally:
        McpService._fits_response = real_fits


# ---------------------------------------------------------------------------
# 1. Stress matrix at issue-#2 scale
# ---------------------------------------------------------------------------


class TestStressMatrix:
    def test_201_changed_files_accounting_and_surface_parity(
        self, files201_repo
    ):
        repo = files201_repo
        db = _db_of(repo)
        try:
            first = run_impact_claim(ImpactClaimRequest(), db, str(repo))
            second = run_impact_claim(ImpactClaimRequest(), db, str(repo))
            service = _service_of(repo)
            try:
                mcp = service.diff_impact_receipt()
            finally:
                service.close()
            # CLI LAST: its post-receipt staleness marking mutates the DB.
            cli = _cli_diff_json(repo, db)
        finally:
            db.close()

        # cited 200 / total 201 / truncated
        assert first["changed_files_total"] == 201
        stats = first["collection_stats"]["changed_files"]
        assert stats["enumerated_count"] == 201
        assert stats["returned_count"] == 200
        assert stats["cap"] == 200
        assert stats["truncated"] is True
        assert stats["cursor_exhausted"] is False
        # the snapshot binds exactly the 200 CITED paths' content
        post = first["post_change_snapshot"]
        assert len(post.get("content_digests") or {}) == 200
        assert first["assurance_facts"]["truncation_sources"] == (
            "changed_files_cap_200",
        )
        assert "collection_truncated:changed_files_cap_200" in (
            first["assurance"]["reason_codes"]
        )
        # STALE here is HONEST: the 201-file commit landed after the
        # last reconcile, so post-change staleness is real. The cap
        # accounting must hold regardless of which severity wins.
        assert first["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
        assert _severe(first["assurance"]["status"]) >= _severe("PARTIAL")
        # parity digest holds at stress scale too
        assert first["digest"] == second["digest"]
        assert mcp["digest"] == first["digest"], (
            "MCP diff_impact_receipt digest diverges at stress scale"
        )
        assert cli["code"] == 0
        assert cli["envelope"]["digest"] == first["digest"], (
            "CLI diff-impact json digest diverges at stress scale"
        )

    def test_501_edges_mixed_directions_stats_exact(self, edges_repo):
        repo = edges_repo
        db = _db_of(repo)
        try:
            in_total, out_total = _edge_totals(db)
            payload = scope_receipt(db, str(repo), "run")
        finally:
            db.close()
        # the intended mix: in-direction over cap, plus live out-edges
        # (the fixture's own run -> help edge included)
        assert in_total >= 501 and out_total >= 60
        stats = payload["collection_stats"]["direct_edges"]
        assert stats["enumerated_count"] == in_total + out_total
        # per-direction cap: min(in,500) + min(out,500) — the cut is
        # visible in the merged stats, never read as "no more callers"
        assert stats["returned_count"] == (
            min(in_total, 500) + min(out_total, 500)
        )
        assert stats["returned_count"] < stats["enumerated_count"]
        assert stats["cap"] == 500
        assert stats["truncated"] is True
        assert stats["cursor_exhausted"] is False
        assert "edges_cap_500" in (
            payload["assurance_facts"]["truncation_sources"]
        )
        assert "collection_truncated:edges_cap_500" in (
            payload["assurance"]["reason_codes"]
        )
        assert payload["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
        assert _severe(payload["assurance"]["status"]) >= _severe("PARTIAL")

    def test_51_evidence_rows_on_one_path_truncated(self, evidence51_repo):
        repo = evidence51_repo
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo))
        finally:
            db.close()
        stats = payload["collection_stats"]["invalidated_evidence"]
        assert stats["enumerated_count"] == 51
        assert stats["returned_count"] == 50
        assert stats["cap"] == 50
        assert stats["truncated"] is True
        assert stats["cursor_exhausted"] is False
        assert payload["assurance_facts"]["truncation_sources"] == (
            "evidence_cap_50",
        )
        assert "collection_truncated:evidence_cap_50" in (
            payload["assurance"]["reason_codes"]
        )
        assert _severe(payload["assurance"]["status"]) >= _severe("PARTIAL")

    def test_5001_evidence_rows_degrade_ledger_union_not_runs(
        self, ledger_repo
    ):
        repo = ledger_repo
        request = ImpactClaimRequest(target="HEAD...HEAD")  # empty diff
        db = _db_of(repo)
        try:
            payload = run_impact_claim(request, db, str(repo))
        finally:
            db.close()
        union = payload["collection_stats"]["ledger_union"]
        assert union["enumerated_count"] == 5001
        assert union["returned_count"] == 5000
        assert union["cap"] == 5000
        assert union["truncated"] is True
        assert union["cursor_exhausted"] is False
        runs = payload["collection_stats"]["ledger_runs"]
        assert runs["truncated"] is False  # 1 seeded run < 200
        # whichever caps fired are REPORTED, not silent: exactly the
        # union cap, and never a phantom runs cap
        assert payload["assurance_facts"]["truncation_sources"] == (
            "ledger_union_cap_5000",
        )
        codes = payload["assurance"]["reason_codes"]
        assert "collection_truncated:ledger_union_cap_5000" in codes
        assert "collection_truncated:ledger_runs_cap_200" not in codes
        assert payload["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
        assert _severe(payload["assurance"]["status"]) >= _severe("PARTIAL")

    def test_combined_worst_case_all_sources_no_assured(self, combined_repo):
        repo = combined_repo
        db = _db_of(repo)
        try:
            first = run_impact_claim(ImpactClaimRequest(), db, str(repo))
            second = run_impact_claim(ImpactClaimRequest(), db, str(repo))
        finally:
            db.close()
        sources = set(first["assurance_facts"]["truncation_sources"])
        # The diff-impact receipt names the collections IT enumerated...
        assert sources == {"changed_files_cap_200", "evidence_cap_50"}
        assert first["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
        assert first["digest"] == second["digest"]

        # ...and the edges cap is named by the scope receipt over the
        # SAME repo state. Each receipt kind honestly reports its own
        # bounded collections; together they must cover every fired cap.
        db = _db_of(repo)
        try:
            scoped = scope_receipt(db, str(repo), "run")
        finally:
            db.close()
        scope_sources = set(scoped["assurance_facts"]["truncation_sources"])
        assert "edges_cap_500" in scope_sources
        assert scoped["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
        all_named = sources | scope_sources
        assert {"changed_files_cap_200", "evidence_cap_50",
                "edges_cap_500"} <= all_named
        # nothing UNKNOWN fired silently alongside them
        assert all_named <= {
            "changed_files_cap_200", "evidence_cap_50", "edges_cap_500",
            "transitive_cap_200", "ledger_runs_cap_200",
            "ledger_union_cap_5000",
        }, f"unrecognized truncation sources: {all_named}"


# ---------------------------------------------------------------------------
# 2. No-false-assure invariant sweep across surfaces (exit gate)
# ---------------------------------------------------------------------------

# (repo fixture name, executor kwargs, surface kwargs, expected sources)
_SWEEP_CASES = [
    ("files201_repo", {}, {}, ["changed_files_cap_200"]),
    ("evidence51_repo", {}, {}, ["evidence_cap_50"]),
    ("ledger_repo", {"target": "HEAD...HEAD"}, {"target": "HEAD...HEAD"},
     ["ledger_union_cap_5000"]),
    ("combined_repo", {}, {}, ["changed_files_cap_200", "evidence_cap_50"]),
]
_SWEEP_EXPECTED = {case[0]: case[3] for case in _SWEEP_CASES}


class TestNoFalseAssureSweep:
    """For every stress scenario: NO surface assures a truncated scope."""

    @pytest.mark.parametrize(
        "repo_attr,req,surface_kwargs,expected", _SWEEP_CASES,
        ids=[case[0] for case in _SWEEP_CASES],
    )
    def test_executor_cli_mcp_never_assure_truncated(
        self, repo_attr, req, surface_kwargs, expected, request
    ):
        repo = request.getfixturevalue(repo_attr)
        cli_extra = [surface_kwargs["target"]] if surface_kwargs else []
        db = _db_of(repo)
        try:
            executor = run_impact_claim(ImpactClaimRequest(**req), db,
                                        str(repo))
            service = _service_of(repo)
            try:
                mcp = service.diff_impact_receipt(**surface_kwargs)
            finally:
                service.close()
            # CLI LAST: it may mark cited evidence stale in the DB.
            cli = _cli_diff_json(repo, db, *cli_extra)
        finally:
            db.close()

        for surface, payload in (
            ("executor", executor), ("mcp", mcp),
            ("cli", cli["envelope"]),
        ):
            _assert_honest(payload, expected, f"{repo_attr}/{surface}")
            assert payload["digest"] == executor["digest"], (
                f"[{repo_attr}/{surface}] digest parity broken under stress"
            )

    def test_edges_scenario_scope_surfaces_never_assure(self, edges_repo):
        repo = edges_repo
        db = _db_of(repo)
        try:
            executor = scope_receipt(db, str(repo), "run")
            service = _service_of(repo)
            try:
                mcp = service.scope_receipt("run")
            finally:
                service.close()
        finally:
            db.close()
        # The scope receipt has no CLI diff-impact surface (its caps live
        # in the assurance collectors, not the diff engine), so the sweep
        # covers executor + MCP here.
        for surface, payload in (("executor", executor), ("mcp", mcp)):
            _assert_honest(payload, ["edges_cap_500"],
                           f"edges_repo/{surface}")

    @pytest.mark.parametrize("repo_attr", [
        "files201_repo", "evidence51_repo", "combined_repo",
    ])
    def test_tight_mcp_budget_degrades_or_raises_never_assures(
        self, repo_attr, request
    ):
        repo = request.getfixturevalue(repo_attr)
        from sot_graph.mcp_service import McpServiceError

        try:
            trimmed, untrimmed = _tight_budget_receipt(repo)
        except McpServiceError as exc:
            # an honest hard failure is acceptable — a clean ASSURED is not
            assert exc.code == "response_too_large", exc.code
            return
        expected = _SWEEP_EXPECTED[repo_attr]
        _assert_honest(trimmed, expected, f"{repo_attr}/mcp-trimmed")
        # the transport cut really happened and degraded the verdict
        assert trimmed.get("truncated") is True
        assert trimmed["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
        codes = trimmed["assurance"]["reason_codes"]
        for src in expected:
            assert f"collection_truncated:{src}" in codes
        # true enumerated counts survive the trim untouched (a transport
        # cut never shrinks a collector's true count)
        for name, true_st in (untrimmed.get("collection_stats") or {}).items():
            got = trimmed["collection_stats"].get(name)
            if isinstance(true_st, dict) and isinstance(got, dict):
                assert got["enumerated_count"] == true_st["enumerated_count"]
                if true_st.get("truncated"):
                    assert got["truncated"] is True
        assert trimmed["digest"] == receipt_digest(
            {k: v for k, v in trimmed.items() if k != "digest"}
        )


# ---------------------------------------------------------------------------
# 3. Characterization of part A's residual risks (pinned, named gaps)
# ---------------------------------------------------------------------------


class TestCharacterizationResidualRisks:
    def _fits(self, plain_repo: Path, budget: int, payload: Dict[str, Any]):
        from sot_graph.mcp_service import McpService, ServiceLimits

        service = McpService(
            db_path=str(plain_repo / ".sot" / "sot.db"),
            project_root=str(plain_repo),
            limits=ServiceLimits(response_bytes=budget),
        )
        try:
            return service._fits_response(payload)
        finally:
            service.close()

    def test_nested_list_heavy_receipt_raises_response_too_large(
        self, plain_repo
    ):
        """RESIDUAL RISK (part A #1 family): trimmer Phase 1 only empties
        top-level and ``result`` lists whose key is in its list_keys.
        Bulk bytes nested inside dicts are unreachable, so a
        nested-list-heavy receipt can be untrimmable. CURRENT behavior:
        an honest ``response_too_large`` raise — pinned here as a
        documented limitation for a future SG (a deeper trimmer), NOT as
        desired behavior."""
        from sot_graph.mcp_service import McpServiceError

        payload = {
            "digest": "a" * 64,
            "changed_files": ["a.py", "b.py"],
            # NOTE: facts MUST carry identity_status — _degrade_assurance_
            # after_trim tolerates schema drift by silently skipping
            # degradation on AssuranceFacts construction failures, which
            # would leave this synthetic payload ASSURED. Real receipts
            # always carry the full facts block.
            "assurance_facts": {"identity_status": "UNIQUE",
                                "truncated": False, "stale_files": []},
            "assurance": {"status": "ASSURED_WITHIN_SCOPE",
                          "reason_codes": []},
            # the bulk hides one level deep: NOT a Phase-1 target
            "post_change_snapshot": {
                "files": [
                    {"path": f"d{i}.py", "digest": "h" * 64}
                    for i in range(400)
                ],
            },
        }
        whole = _enc(payload)
        with pytest.raises(McpServiceError) as excinfo:
            self._fits(plain_repo, whole - 2048, payload)
        assert excinfo.value.code == "response_too_large"

    def test_eviction_bounded_at_three_rounds(self, plain_repo):
        """RESIDUAL RISK: eviction runs ``for _round in range(3)`` in
        McpService._fits_response — at most 3 shrink-then-re-degrade
        rounds. Pinned BOTH sides of that cap:

        - a payload whose deficit is absorbed within the cap FITS, with
          truthful post-eviction counts; while
        - a payload needing MORE shrink than eviction can ever deliver
          (the bulk sits in a field neither Phase 1 nor eviction can
          touch) exhausts the rounds and RAISES response_too_large —
          the trimmer never lies its way under the ceiling."""
        from sot_graph.mcp_service import McpServiceError

        def _receipt(items: List[Dict[str, Any]], blob: str = ""):
            payload = {
                "digest": "a" * 64,
                "changed_files": list(items),
                "collection_stats": {
                    "changed_files": {
                        "enumerated_count": len(items),
                        "returned_count": len(items),
                        "cap": 200,
                        "truncated": False,
                        "cursor_exhausted": True,
                    },
                },
                # identity_status required so the degrade path fires (see
                # the schema-drift note in the nested-heavy test above)
                "assurance_facts": {"identity_status": "UNIQUE",
                                    "truncated": False,
                                    "stale_files": []},
                "assurance": {"status": "ASSURED_WITHIN_SCOPE",
                              "reason_codes": []},
            }
            if blob:
                payload["blob"] = blob
            return payload

        # (a) converges within the 3-round cap: Phase 2 refills almost
        # everything, the appended degradation block overshoots the
        # ceiling, and a few evictions give those bytes back.
        items = [{"n": i, "pad": "p" * 40} for i in range(100)]
        payload = _receipt(items)
        whole = _enc(payload)
        item_bytes = _enc(items[0]) + 1
        budget = whole - 5 * item_bytes
        result = self._fits(plain_repo, budget, payload)
        assert result["truncated"] is True
        entry = result["transport_truncation"]["collections"][0]
        assert 0 < entry["returned_count"] < entry["enumerated_count"]
        assert len(result["changed_files"]) == entry["returned_count"]
        assert result["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"

        # (b) needs more than eviction can ever free -> honest raise
        # after the bounded 3-round loop.
        blob_payload = _receipt(items[:5], blob="B" * 24_000)
        blob_whole = _enc(blob_payload)
        with pytest.raises(McpServiceError) as excinfo:
            self._fits(plain_repo, blob_whole - 4096, blob_payload)
        assert excinfo.value.code == "response_too_large"

    def test_mcp_vs_cli_payload_normalization_field_parity(
        self, files201_repo
    ):
        """RESIDUAL RISK (path normalization): the same repo state is
        projected through the MCP writer path and the CLI writer path.
        Pinned field-by-field, comparing the payload each transport
        actually emits (both sides JSON round-tripped): digests MATCH,
        and the CLI envelope's embedded receipt (``data``) differs from
        the MCP payload by EXACTLY one ADDITIVE field — ``stale_files``
        (a CLI surface extra). If a future change introduces real
        divergence (e.g. absolute vs relative paths in stale_files /
        snapshot blocks), the assertion below names the exact fields for
        the follow-up SG."""
        repo = files201_repo
        db = _db_of(repo)
        try:
            executor = run_impact_claim(ImpactClaimRequest(), db, str(repo))
            service = _service_of(repo)
            try:
                mcp = service.diff_impact_receipt()
            finally:
                service.close()
            cli = _cli_diff_json(repo, db)
        finally:
            db.close()

        # digests match across all three surfaces — pin it
        assert executor["digest"] == mcp["digest"] == (
            cli["envelope"]["digest"]
        )
        # compare the wire-visible forms (tuples become lists in JSON)
        mcp_wire = json.loads(json.dumps(mcp, default=str))
        data = json.loads(json.dumps(cli["envelope"]["data"], default=str))
        added = set(data) - set(mcp_wire)
        removed = set(mcp_wire) - set(data)
        diverging = sorted(
            k for k in set(mcp_wire) & set(data)
            if mcp_wire[k] != data[k]
        )
        # Pin the KNOWN inconsistency surface: exactly one additive
        # CLI-only key, zero removals, and at most TWO value divergences
        # — both wall-clock volatile in the PAYLOAD while receipt_digest
        # strips them (so digests still match):
        #   summary.execution_time_ms        (float ms, per-surface run)
        #   post_change_snapshot.captured_at (int seconds; surfaces that
        #       capture across a second boundary disagree)
        assert added == {"stale_files"}, (
            f"CLI-only fields beyond stale_files: {sorted(added)}"
        )
        assert not removed, f"MCP-only fields: {sorted(removed)}"
        assert set(diverging) <= {"summary", "post_change_snapshot"}, (
            "MCP vs CLI receipt normalization diverged in fields "
            f"{diverging} — capture exact per-field values for the "
            "path-normalization SG (e.g. absolute vs relative paths in "
            "stale_files/snapshot blocks)"
        )
        if "summary" in diverging:
            volatile = {
                k for k in set(mcp_wire["summary"]) | set(data["summary"])
                if mcp_wire["summary"].get(k) != data["summary"].get(k)
            }
            assert volatile <= {"execution_time_ms"}, (
                "summary divergence beyond wall-clock timing: "
                f"{sorted(volatile)} — real normalization drift for the "
                "follow-up SG"
            )
        if "post_change_snapshot" in diverging:
            ps_mcp = mcp_wire["post_change_snapshot"]
            ps_cli = data["post_change_snapshot"]
            volatile_ps = {
                k for k in set(ps_mcp) | set(ps_cli)
                if ps_mcp.get(k) != ps_cli.get(k)
            }
            assert volatile_ps <= {"captured_at"}, (
                "post_change_snapshot divergence beyond the int-second "
                f"capture clock: {sorted(volatile_ps)} — real "
                "normalization drift for the follow-up SG"
            )


# ---------------------------------------------------------------------------
# 4. Regression tripwire: every assurance LIMIT is accounted
# ---------------------------------------------------------------------------


class TestLimitTripwire:
    """Every SQL LIMIT in src/sot_graph/assurance/ must be a KNOWN site.

    Mirrors part A's cap-site sweep: a new LIMIT that silently bounds a
    collection without CollectionStats accounting + a truncation source
    is exactly the false-assure bug SG-107 exists to prevent. If this
    test fails for you: either (a) your new cap MUST emit accounting
    (twin COUNT + CollectionStats.counted + a named source in
    ``facts.truncation_sources``) and get registered in
    ``_ACCOUNTED_LIMITS`` below, or (b) it genuinely does not bound a
    receipt collection (e.g. a LIMIT 1 identity probe) and belongs in
    ``_NON_TRUNCATING_LIMITS`` — with a justification.
    """

    _ACCOUNTED_LIMITS: Dict[Tuple[str, int], str] = {
        ("receipts.py", 180): "edges_cap_500",
        ("receipts.py", 240): "ledger_runs_cap_200",
        ("receipts.py", 253): "ledger_runs_cap_200",
        ("receipts.py", 763): "evidence_cap_50",
        ("ledger.py", 104): "ledger_union_cap_5000",
        ("ledger.py", 132): "ledger_union_cap_5000 (legacy fallback query)",
    }
    _NON_TRUNCATING_LIMITS: Dict[Tuple[str, int], str] = {
        ("engine.py", 29): "exact-symbol identity probe; LIMIT 1 returns "
                           "0/1 rows — a lookup, not a bounded collection",
        ("engine.py", 35): "LIKE disambiguation probe; decision paths use "
                           "resolve_symbol_identity (no LIMIT — ambiguity "
                           "surfaced)",
    }

    def test_every_assurance_limit_is_accounted(self):
        import sot_graph

        assurance_dir = (Path(sot_graph.__file__).resolve().parent
                         / "assurance")
        limit_re = re.compile(r"\bLIMIT\s+(\d|\?|\{)")
        found: Dict[Tuple[str, int], str] = {}
        for path in sorted(assurance_dir.glob("*.py")):
            for lineno, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#") or "``" in line:
                    continue  # comments / docstring mentions
                if limit_re.search(line):
                    found[(path.name, lineno)] = stripped

        unaccounted = {
            site: line for site, line in found.items()
            if site not in self._ACCOUNTED_LIMITS
            and site not in self._NON_TRUNCATING_LIMITS
        }
        assert not unaccounted, (
            "NEW UNACCOUNTED CAP SITE(S) in src/sot_graph/assurance/: "
            + "; ".join(
                f"{fname}:{line} -> {text}"
                for (fname, line), text in sorted(unaccounted.items())
            )
            + ". A collection-bounding LIMIT must report CollectionStats "
            "(twin COUNT without LIMIT) and a named truncation source "
            "(SG-107), then be registered in _ACCOUNTED_LIMITS — or be "
            "justified in _NON_TRUNCATING_LIMITS."
        )

        # Registry honesty: no stale entries (line drift must be fixed,
        # not ignored).
        stale_entries = [
            site for site in
            list(self._ACCOUNTED_LIMITS) + list(self._NON_TRUNCATING_LIMITS)
            if site not in found
        ]
        assert not stale_entries, (
            "stale tripwire registry entries (LIMIT moved/removed): "
            f"{stale_entries} — update the registry to the new lines"
        )
