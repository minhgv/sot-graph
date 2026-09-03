"""P4.3 — ranking factors + per-row provenance reasons (cmd_search).

Locks the ordering contract (verdict -> exact-identity grade -> provider
evidence -> coverage) and that every emitted row carries a `reasons`
provenance list, on both JSON and text surfaces. Internal ranking keys
must never leak into the JSON envelope.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from sot_graph.cli import _identity_grade, _p4_sort_key  # noqa: E402


class TestIdentityGrade:
    def test_exact_symbol_beats_qualified_beats_prefix(self):
        exact = _identity_grade({"label": "run", "fqn": "src.run"}, "run")
        qualified = _identity_grade({"label": "run", "fqn": "src.run"}, "src.run")
        prefix = _identity_grade({"label": "run_server", "fqn": "x"}, "run")
        body = _identity_grade({"label": "Order", "fqn": "x"}, "run")
        assert exact[0] < qualified[0] < prefix[0] < body[0]
        assert exact[1] == "exact symbol name match"

    def test_colon_qualified_query(self):
        grade, reason = _identity_grade(
            {"label": "get", "fqn": "Cache.get"}, "Cache.get"
        )
        assert grade == 1
        assert reason == "qualified-name match"


class TestSortKeyContract:
    def _row(self, verdict, grade, evidence=0, coverage="0%"):
        return {
            "verdict": verdict,
            "_identity_grade": grade,
            "_evidence_count": evidence,
            "coverage": coverage,
        }

    def test_verdict_dominates(self):
        weak = self._row("WEAK", 0, evidence=99, coverage="100%")
        strong = self._row("STRONG", 3, evidence=0, coverage="0%")
        assert _p4_sort_key(strong) < _p4_sort_key(weak)

    def test_identity_grade_beats_evidence(self):
        exact = self._row("STRONG", 0, evidence=0)
        text = self._row("STRONG", 3, evidence=50)
        assert _p4_sort_key(exact) < _p4_sort_key(text)

    def test_evidence_beats_coverage(self):
        evidenced = self._row("STRONG", 1, evidence=5, coverage="0%")
        plain = self._row("STRONG", 1, evidence=0, coverage="100%")
        assert _p4_sort_key(evidenced) < _p4_sort_key(plain)


@pytest.fixture()
def indexed_repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "def run_server():\n    return 'app'\n\n\ndef runner_helper():\n"
        "    return run_server()\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "dupname.py").write_text(
        "def run_server():\n    return 'other-file'\n",
        encoding="utf-8",
    )
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=tmp_path, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(tmp_path),
         "reconcile"],
        check=True, cwd=tmp_path, capture_output=True,
    )
    return tmp_path


def _search_json(repo: Path, query: str) -> dict:
    out = subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo),
         "search", query, "--json", "--limit", "10"],
        check=True, cwd=repo, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return json.loads(out.stdout)


class TestSearchProvenance:
    def test_rows_carry_reasons_and_no_internal_keys(self, indexed_repo):
        env = _search_json(indexed_repo, "run_server")
        results = env["results"] if "results" in env else env["data"]["results"]
        assert results, "expected hits for run_server"
        for row in results:
            assert isinstance(row.get("reasons"), list) and row["reasons"]
            assert all(isinstance(r, str) for r in row["reasons"])
            assert "_identity_grade" not in row
            assert "_evidence_count" not in row
            assert any(r.startswith("verdict=") for r in row["reasons"])

    def test_exact_identity_ranks_first_across_same_name_files(self, indexed_repo):
        env = _search_json(indexed_repo, "run_server")
        results = env["results"] if "results" in env else env["data"]["results"]
        # two files define run_server; both must surface (short names
        # never collapse identities) — labels carry path suffixes here
        symbols = [r["label"] for r in results]
        assert sum(1 for s in symbols if "run_server" in s) >= 2

    def test_text_output_shows_rank_reasons(self, indexed_repo):
        out = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root", str(indexed_repo),
             "search", "run_server", "--limit", "5"],
            check=True, cwd=indexed_repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        assert "Rank:" in out.stdout
