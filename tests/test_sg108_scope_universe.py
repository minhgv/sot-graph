"""SG-108 — absence/exhaustive coverage semantics: adversarial scope suite.

Locks (issue #3, reassessment §7 P0-4 → permanent regressions):
- Counterexample 1: a single PARTIAL_AST file is NOT covered evidence —
  covered_fraction 0.0 (was 1.0), parser capability False, and the
  partial_ast_ceiling reason can never reach ASSURED on an absence claim.
- Counterexample 2: an EXCLUDED file leaves the covered_fraction
  denominator (one indexed + one excluded → 1.0, was 0.5) while staying
  visible as a scope boundary in files/totals/universe.excluded_files.
- Absence/exhaustive/relation claims require 100% universe exhaustion:
  every eligible file enumerated (no unknowns, no walk errors), every
  journaled file fully parser-capable — unmeasured (None) fails closed
  exactly like incomplete. A 0.9 average proves nothing.
- The content Merkle root binds the eligible universe's CONTENT, not
  just names: edit/rename flips it; excluded-file edits cannot.
- check_rename_gate only opens "0 callers" on a REPO-WIDE exhausted
  universe — one unjournaled eligible file anywhere blocks the gate.
- Headline: false-assured rate = 0 across the adversarial matrix.
"""

from __future__ import annotations

import builtins
import hashlib
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from sot_graph.assurance.coverage import (
    UNIVERSE_SAMPLE_CAP,
    CoverageState,
    compile_scope_universe,
    repo_coverage,
)
from sot_graph.assurance.receipts import check_rename_gate, scope_receipt
from sot_graph.assurance.state import AssuranceFacts, decide


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture(scope="module")
def sg108_repo(tmp_path_factory) -> Path:
    """Real mini-repo: lonely has one caller, other has zero callers."""
    repo = tmp_path_factory.mktemp("sg108repo")
    (repo / "target.py").write_text(
        "def lonely():\n    return 1\n", encoding="utf-8"
    )
    (repo / "helper.py").write_text(
        "def other():\n    return 3\n", encoding="utf-8"
    )
    (repo / "caller.py").write_text(
        "import target\n\n\ndef use():\n    return target.lonely() + 1\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c1")
    subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo), "reconcile"],
        check=True, cwd=repo, capture_output=True,
    )
    return repo


def _db_of(repo: Path):
    from sot_graph.db import Database

    return Database(str(repo / ".sot" / "sot.db"))


def _fast_repo(tmp_path: Path, files: dict, journaled: set, outcomes: dict | None = None):
    """Journal-driven mini repo without a reconcile pass.

    Writes ``files`` on disk, then inserts journal rows for ``journaled``
    with the real on-disk sha256/size so repo_coverage does not flag
    STALE. Unjournaled files model never-scanned holes.
    """
    from sot_graph.db import Database

    outcomes = outcomes or {}
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    db = Database(str(tmp_path / "sot.db"))
    for rel in sorted(journaled):
        data = (tmp_path / rel).read_bytes()
        db.conn.execute(
            "INSERT INTO file_journal (path,sha256,size,mtime_ms,"
            "reconciled_at,parser_outcome) VALUES (?,?,?,?,?,?)",
            (rel, hashlib.sha256(data).hexdigest(), len(data), 1, 1,
             outcomes.get(rel, "COMPLETE")),
        )
    db.conn.commit()
    return db


def _facts(**kwargs) -> AssuranceFacts:
    base = {
        "identity_status": "UNIQUE",
        "snapshot_bound": True,
        "stale_files": [],
        "coverage_measured": True,
        "coverage_fraction": 1.0,
        "coverage_floor": 0.9,
        "parser_failures": 0,
        "unresolved_count": 0,
        "unresolved_budget": 0,
        "open_conflicts": 0,
        "truncated": False,
        "enumeration_complete": True,
        "parser_capability_complete": True,
        "partial_ast_present": False,
        "provider_capability_ok": True,
        "absence_claim": True,
        "gate_blocked": False,
        "dynamic_dispatch_unresolved": False,
        "claim_profile": "absence",
    }
    base.update(kwargs)
    return AssuranceFacts(**base)


class TestCounterexamples:
    """The two §7 P0-4 counterexamples, inverted into regressions."""

    def test_single_partial_ast_file_is_not_covered(self, tmp_path):
        db = _fast_repo(
            tmp_path,
            files={"a.py": "def f():\n    return 1\n"},
            journaled={"a.py"},
            outcomes={"a.py": "PARTIAL_AST"},
        )
        try:
            report = repo_coverage(db, str(tmp_path))
            assert report.files[0].state == CoverageState.PARTIAL
            # Was 1.0 pre-SG-108: one PARTIAL file must not read as
            # full coverage.
            assert report.covered_fraction == 0.0

            universe = compile_scope_universe(db, str(tmp_path))
            assert universe.parser_capability_complete is False
            assert universe.partial_ast_present is True

            res = decide(_facts(partial_ast_present=True))
            assert res["status"] == "PARTIAL"
            assert "partial_ast_ceiling" in res["reason_codes"]
        finally:
            db.close()

    def test_excluded_file_leaves_denominator_stays_visible(self, tmp_path):
        db = _fast_repo(
            tmp_path,
            files={
                "src/app.py": "def run():\n    return 1\n",
                "node_modules/x/index.js": "module.exports = 1;\n",
                "src/app.min.js": "var x=1;\n",
            },
            journaled={"src/app.py", "node_modules/x/index.js"},
        )
        try:
            report = repo_coverage(db, str(tmp_path))
            states = {f.path: f.state for f in report.files}
            assert states["node_modules/x/index.js"] == CoverageState.EXCLUDED
            # Was 0.5 pre-SG-108: exclusions are boundary, not scope.
            assert report.covered_fraction == 1.0
            assert report.totals.get(CoverageState.EXCLUDED) == 1

            universe = compile_scope_universe(db, str(tmp_path))
            assert list(universe.eligible_files) == ["src/app.py"]
            # Walked-but-excluded files stay visible as boundary.
            assert "src/app.min.js" in universe.excluded_files
            assert universe.enumeration_complete is True
        finally:
            db.close()


class TestUniverseAxes:
    def test_unknown_file_breaks_enumeration(self, tmp_path):
        db = _fast_repo(
            tmp_path,
            files={"a.py": "def f():\n    return 1\n",
                   "junk.py": "def j():\n    return 0\n"},
            journaled={"a.py"},
        )
        try:
            universe = compile_scope_universe(db, str(tmp_path))
            assert list(universe.unknown_files) == ["junk.py"]
            assert universe.enumeration_complete is False
            assert universe.enumeration_fraction == 0.5

            res = decide(_facts(enumeration_complete=False))
            assert res["status"] == "PARTIAL"
            assert "enumeration_incomplete" in res["reason_codes"]
        finally:
            db.close()

    def test_walk_error_breaks_enumeration(self, tmp_path, monkeypatch):
        db = _fast_repo(
            tmp_path,
            files={"a.py": "def f():\n    return 1\n"},
            journaled={"a.py"},
        )
        try:
            real_walk = os.walk

            def noisy_walk(top, topdown=True, onerror=None, **kw):
                if onerror is not None:
                    onerror(OSError("EACCES: simulated unreadable dir"))
                yield from real_walk(top, topdown=topdown,
                                     onerror=onerror, **kw)

            monkeypatch.setattr(os, "walk", noisy_walk)
            universe = compile_scope_universe(db, str(tmp_path))
            assert any("EACCES" in e for e in universe.walk_errors)
            assert list(universe.eligible_files) == ["a.py"]
            # An unreadable corner means the enumeration is unproven,
            # even when every walked file happened to be journaled.
            assert universe.enumeration_complete is False
        finally:
            db.close()

    def test_journal_unreadable_fails_closed(self, tmp_path):
        class _BoomConn:
            def execute(self, q, *a):
                raise RuntimeError("journal locked")

        class _BoomDB:
            conn = _BoomConn()

        universe = compile_scope_universe(_BoomDB(), str(tmp_path))
        assert universe.enumeration_complete is False
        assert universe.parser_capability_complete is None
        assert universe.enumeration_fraction is None

        res = decide(_facts(enumeration_complete=False,
                            parser_capability_complete=None))
        assert res["status"] == "PARTIAL"
        assert {"enumeration_incomplete",
                "parser_capability_incomplete"} <= set(res["reason_codes"])

    def test_missing_file_is_boundary_not_eligible(self, tmp_path):
        db = _fast_repo(
            tmp_path,
            files={"a.py": "def f():\n    return 1\n", "gone.py": "x = 1\n"},
            journaled={"a.py", "gone.py"},
        )
        (tmp_path / "gone.py").unlink()
        try:
            universe = compile_scope_universe(db, str(tmp_path))
            assert list(universe.missing_files) == ["gone.py"]
            assert "gone.py" not in universe.eligible_files
            # Disk is ground truth: a vanished file cannot hide a
            # caller, so it does not break enumeration — it stays
            # visible as a boundary fact.
            assert universe.enumeration_complete is True
        finally:
            db.close()

    def test_target_paths_restrict_universe(self, tmp_path):
        db = _fast_repo(
            tmp_path,
            files={"a.py": "def f():\n    return 1\n",
                   "sub/b.py": "def g():\n    return 2\n",
                   "sub/deep/d.py": "def h():\n    return 3\n"},
            journaled={"a.py"},
        )
        try:
            by_dir = compile_scope_universe(db, str(tmp_path),
                                            target_paths=["sub"])
            assert sorted(by_dir.eligible_files) == [
                "sub/b.py", "sub/deep/d.py",
            ]
            by_file = compile_scope_universe(db, str(tmp_path),
                                             target_paths=["sub/b.py"])
            assert list(by_file.eligible_files) == ["sub/b.py"]
        finally:
            db.close()

    def test_custom_exclusion_is_boundary(self, tmp_path):
        db = _fast_repo(
            tmp_path,
            files={"src/a.py": "def f():\n    return 1\n",
                   "src/gen_stub.py": "x = 1\n"},
            journaled={"src/a.py"},
        )
        try:
            universe = compile_scope_universe(
                db, str(tmp_path), excluded_patterns=["*_stub.py"]
            )
            assert "src/gen_stub.py" in universe.excluded_files
            assert list(universe.eligible_files) == ["src/a.py"]
        finally:
            db.close()


class TestContentMerkle:
    def _root(self, tmp_path):
        from sot_graph.db import Database

        db = Database(str(tmp_path / "sot.db"))
        try:
            return compile_scope_universe(db, str(tmp_path)).content_merkle_root
        finally:
            db.close()

    def test_deterministic(self, tmp_path):
        _fast_repo(
            tmp_path,
            files={"a.py": "def f():\n    return 1\n",
                   "b.py": "def g():\n    return 2\n"},
            journaled={"a.py", "b.py"},
        ).close()
        assert self._root(tmp_path) == self._root(tmp_path)

    def test_sensitive_to_content_and_rename(self, tmp_path):
        _fast_repo(
            tmp_path,
            files={"a.py": "def f():\n    return 1\n",
                   "b.py": "def g():\n    return 2\n"},
            journaled={"a.py", "b.py"},
        ).close()
        base = self._root(tmp_path)

        (tmp_path / "b.py").write_text(
            "def g():\n    return 42\n", encoding="utf-8"
        )
        assert self._root(tmp_path) != base

        (tmp_path / "b.py").write_text(
            "def g():\n    return 2\n", encoding="utf-8"
        )
        assert self._root(tmp_path) == base  # restored → same root
        (tmp_path / "b.py").rename(tmp_path / "bb.py")
        assert self._root(tmp_path) != base

    def test_insensitive_to_excluded_content(self, tmp_path):
        _fast_repo(
            tmp_path,
            files={"src/a.py": "def f():\n    return 1\n",
                   "src/app.min.js": "var x=1;\n"},
            journaled={"src/a.py"},
        ).close()
        base = self._root(tmp_path)
        (tmp_path / "src" / "app.min.js").write_text(
            "var x=2;\n", encoding="utf-8"
        )
        # Excluded files are outside the universe their changes cannot
        # move the root.
        assert self._root(tmp_path) == base

    def test_unhashable_file_fails_closed(self, tmp_path, monkeypatch):
        _fast_repo(
            tmp_path,
            files={"a.py": "def f():\n    return 1\n",
                   "poison.py": "def p():\n    return 0\n"},
            journaled={"a.py"},
        ).close()

        real_open = builtins.open

        def selective_open(file, *args, **kwargs):
            if str(file).endswith("poison.py"):
                raise OSError("EACCES: unreadable")
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", selective_open)
        from sot_graph.db import Database

        db = Database(str(tmp_path / "sot.db"))
        try:
            universe = compile_scope_universe(db, str(tmp_path))
            assert universe.content_merkle_root.startswith("sha256:")
            assert "poison.py" in universe.walk_errors
            assert universe.enumeration_complete is False
        finally:
            db.close()


class TestDecideTruthTable:
    POISONS = [
        ("enumeration_false", {"enumeration_complete": False},
         "enumeration_incomplete"),
        ("enumeration_none", {"enumeration_complete": None},
         "enumeration_incomplete"),
        ("parser_false", {"parser_capability_complete": False},
         "parser_capability_incomplete"),
        ("parser_none", {"parser_capability_complete": None},
         "parser_capability_incomplete"),
        ("partial_ast", {"partial_ast_present": True},
         "partial_ast_ceiling"),
        ("below_floor", {"coverage_fraction": 0.5},
         "coverage_below_floor"),
    ]
    PROFILES = [
        ("absence", {"absence_claim": True, "claim_profile": "absence"}),
        ("exhaustive", {"absence_claim": False,
                        "claim_profile": "exhaustive"}),
        ("relation", {"absence_claim": False, "claim_profile": "relation"}),
    ]

    @pytest.mark.parametrize("profile_name,profile_kw", PROFILES)
    @pytest.mark.parametrize("poison_name,poison_kw,reason", POISONS)
    def test_poison_never_assures(self, poison_name, poison_kw, reason,
                                  profile_name, profile_kw):
        res = decide(_facts(**poison_kw, **profile_kw))
        assert res["status"] != "ASSURED_WITHIN_SCOPE", (
            f"{poison_name} + {profile_name} falsely assured: {res}"
        )
        assert reason in res["reason_codes"]

    def test_presence_profile_unaffected_by_exhaustion_facts(self):
        # Presence claims do not rest on universe exhaustion — the
        # exhaustion facts must not degrade them.
        res = decide(_facts(absence_claim=False,
                            claim_profile="presence",
                            enumeration_complete=False,
                            parser_capability_complete=None))
        assert res["status"] == "ASSURED_WITHIN_SCOPE"

    def test_all_clear_absence_assures(self):
        res = decide(_facts())
        assert res["status"] == "ASSURED_WITHIN_SCOPE"
        assert res["reason_codes"] == []

    def test_none_fails_exactly_like_false(self):
        # SG-108 doctrine: unmeasured (None) must degrade identically to
        # measured-incomplete — "cannot prove" never reads as "proved".
        res_none = decide(_facts(enumeration_complete=None,
                                 parser_capability_complete=None))
        res_false = decide(_facts(enumeration_complete=False,
                                  parser_capability_complete=False))
        assert res_none["status"] == res_false["status"] == "PARTIAL"
        assert (set(res_none["reason_codes"])
                == set(res_false["reason_codes"])
                == {"enumeration_incomplete", "parser_capability_incomplete"})


class TestRenameGate:
    def test_zero_callers_gate_opens_on_exhausted_universe(self, sg108_repo):
        db = _db_of(sg108_repo)
        try:
            gate = check_rename_gate(db, str(sg108_repo), "other")
            assert gate["resolved"] is True
            assert gate["callers_found"] == 0
            assert gate["blocked"] is False
        finally:
            db.close()

    def test_one_unjournaled_file_blocks_gate_repo_wide(self, sg108_repo):
        # The hole lives OUTSIDE the target's own file — only a
        # REPO-WIDE universe requirement catches it (scoped-universe
        # gating would falsely open here).
        junk = sg108_repo / "junk.py"
        junk.write_text("def junk():\n    return 0\n", encoding="utf-8")
        try:
            db = _db_of(sg108_repo)
            try:
                gate = check_rename_gate(db, str(sg108_repo), "other")
                assert gate["blocked"] is True
                assert "universe not exhausted" in gate["reason"]
            finally:
                db.close()
        finally:
            junk.unlink()

    def test_partial_ast_in_scope_blocks_gate(self, sg108_repo):
        db = _db_of(sg108_repo)
        row = db.conn.execute(
            "SELECT path FROM file_journal WHERE path LIKE '%helper.py'"
        ).fetchone()
        assert row is not None
        journal_path = row[0]
        db.conn.execute(
            "UPDATE file_journal SET parser_outcome='PARTIAL_AST' "
            "WHERE path = ?", (journal_path,),
        )
        db.conn.commit()
        try:
            gate = check_rename_gate(db, str(sg108_repo), "other")
            assert gate["blocked"] is True
            assert "universe not exhausted" in gate["reason"]
        finally:
            db.conn.execute(
                "UPDATE file_journal SET parser_outcome='COMPLETE' "
                "WHERE path = ?", (journal_path,),
            )
            db.conn.commit()
            db.close()

    def test_nonzero_callers_pass_regardless_of_universe(self, sg108_repo):
        junk = sg108_repo / "junk2.py"
        junk.write_text("def junk2():\n    return 0\n", encoding="utf-8")
        try:
            db = _db_of(sg108_repo)
            try:
                gate = check_rename_gate(db, str(sg108_repo), "lonely")
                assert gate["callers_found"] >= 1
                # Presence claim: callers were SEEN; the dirty universe
                # cannot retro-hide them.
                assert gate["blocked"] is False
            finally:
                db.close()
        finally:
            junk.unlink()


class TestScopeReceiptUniverse:
    def test_clean_receipt_assures_with_universe_block(self, sg108_repo):
        db = _db_of(sg108_repo)
        try:
            payload = scope_receipt(db, str(sg108_repo), "other")
        finally:
            db.close()
        assert payload["schema_version"] == "1.6"
        # Positive end-to-end control: an exhausted, fully-capable,
        # fully-covered universe keeps the absence claim ASSURED.
        assert payload["assurance"]["status"] == "ASSURED_WITHIN_SCOPE"

        uni = payload["scope_universe"]
        assert set(uni.keys()) == {
            "eligible_count", "excluded_count", "unknown_count",
            "missing_count", "walk_error_count", "enumeration_fraction",
            "enumeration_complete", "parser_capability_complete",
            "content_merkle_root", "excluded_files", "unknown_files",
        }
        assert uni["enumeration_complete"] is True
        assert uni["parser_capability_complete"] is True
        assert uni["eligible_count"] == 3  # target/helper/caller
        assert uni["unknown_count"] == 0
        assert uni["content_merkle_root"].startswith("sha256:")
        for sample in (uni["excluded_files"], uni["unknown_files"]):
            assert set(sample.keys()) == {"returned", "cap", "truncated",
                                          "total"}
            assert sample["cap"] == UNIVERSE_SAMPLE_CAP

    def test_unjournaled_file_degrades_receipt(self, sg108_repo):
        junk = sg108_repo / "junk3.py"
        junk.write_text("def junk3():\n    return 0\n", encoding="utf-8")
        try:
            db = _db_of(sg108_repo)
            try:
                payload = scope_receipt(db, str(sg108_repo), "other")
            finally:
                db.close()
        finally:
            junk.unlink()
        assert payload["assurance"]["status"] == "PARTIAL"
        assert "enumeration_incomplete" in payload["assurance"]["reason_codes"]
        assert payload["scope_universe"]["unknown_count"] == 1

    def test_unknown_sample_bounding_is_presentation_only(self, tmp_path):
        files = {"a.py": "def f():\n    return 1\n"}
        files.update(
            {f"junk/j{i:02d}.py": f"j = {i}\n" for i in range(
                UNIVERSE_SAMPLE_CAP + 5)}
        )
        db = _fast_repo(tmp_path, files=files, journaled={"a.py"})
        try:
            universe = compile_scope_universe(db, str(tmp_path))
            sample = universe.to_dict()["unknown_files"]
            assert sample["total"] == UNIVERSE_SAMPLE_CAP + 5
            assert len(sample["returned"]) == UNIVERSE_SAMPLE_CAP
            assert sample["truncated"] is True
            assert sample["cap"] == UNIVERSE_SAMPLE_CAP
            # The full set stays on the dataclass — the cap hides
            # nothing from callers that need the exact accounting.
            assert len(universe.unknown_files) == UNIVERSE_SAMPLE_CAP + 5
        finally:
            db.close()


class TestAdversarialSweep:
    def test_false_assured_rate_zero(self):
        """Headline exit gate: no poisoned combination ever assures."""
        enum_states = [False, None, True]
        parser_states = [False, None, True]
        partial_states = [False, True]
        coverage_states = [0.5, 1.0]
        profiles = ["absence", "exhaustive", "relation"]

        poisoned = 0
        falsely_assured = []
        for enum in enum_states:
            for parser in parser_states:
                for partial in partial_states:
                    for cov in coverage_states:
                        is_clean = (
                            enum is True and parser is True
                            and not partial and cov == 1.0
                        )
                        for profile in profiles:
                            res = decide(_facts(
                                enumeration_complete=enum,
                                parser_capability_complete=parser,
                                partial_ast_present=partial,
                                coverage_fraction=cov,
                                absence_claim=(profile == "absence"),
                                claim_profile=profile,
                            ))
                            if res["status"].startswith("ASSURED"):
                                if not is_clean:
                                    falsely_assured.append(
                                        (enum, parser, partial, cov, profile)
                                    )
                            else:
                                if not is_clean:
                                    poisoned += 1
        assert not falsely_assured, (
            f"false-assured combos: {falsely_assured}"
        )
        assert poisoned >= 100  # the matrix actually exercised poisons
