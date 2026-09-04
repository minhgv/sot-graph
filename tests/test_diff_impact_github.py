"""R4: PR-safe GitHub renderer for sot diff-impact.

Verifies the renderer contract: top-line risk verdict, collapsed
<details> sections, zero ANSI escapes, repo-relative paths only, and
deterministic ordering across repeated renders.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.diff_impact import (
    ApiImpact,
    CallerImpact,
    DiffImpactResult,
    DirectNodeChange,
    TestImpact,
    GITHUB_COMMENT_MARKER,
    format_diff_impact_github,
)


def _result(repo: str = "/repo") -> DiffImpactResult:
    """A fabricated result mimicking engine output with absolute paths + ANSI."""
    summary = {
        "total_changed_files": 2,
        "total_hunks": 3,
        "total_direct_nodes": 2,
        "total_callers": 2,
        "total_apis": 1,
        "total_tests": 2,
        "risk_score": 72,
        "risk_level": "HIGH",
        "execution_time_ms": 42,
    }
    return DiffImpactResult(
        target="HEAD~1",
        repo_path=repo,
        summary=summary,
        changed_files=[
            os.path.join(repo, "src/app/store.py"),
            os.path.join(repo, "src/app/client.py"),
        ],
        direct_nodes=[
            DirectNodeChange(
                id="n2", path=os.path.join(repo, "src/app/client.py"), kind="function",
                symbol="handler", fqn="app.handler", label="handler",
                line_start=3, line_end=4, change_type="modified",
            ),
            DirectNodeChange(
                id="n1", path=os.path.join(repo, "src/app/store.py"), kind="function",
                symbol="fetch", fqn="app.fetch", label="fetch",
                line_start=1, line_end=1, change_type="modified",
            ),
        ],
        caller_impacts=[
            CallerImpact(
                id="c2", path=os.path.join(repo, "src/app/other.py"), kind="function",
                symbol="zcaller", fqn="app.zcaller", label="zcaller",
                line_start=9, depth=1, via_relation="calls",
                callee_id="n1", callee_symbol="fetch",
            ),
            CallerImpact(
                id="c1", path=os.path.join(repo, "src/app/main.py"), kind="function",
                symbol="acaller", fqn="app.acaller", label="acaller",
                line_start=5, depth=1, via_relation="calls",
                callee_id="n1", callee_symbol="fetch",
            ),
        ],
        api_impacts=[
            ApiImpact(
                id="a1", http_method="GET", normalized_uri="/api/items",
                fe_caller_symbol="ui.list", be_controller_symbol="handler",
                impact_source="direct_node",
            ),
        ],
        test_impacts=[
            TestImpact(
                id="t1", path=os.path.join(repo, "tests/test_store.py"), kind="file",
                symbol="test_store.py", impact_reason="direct_test_file",
                target_symbol=None,
            ),
        ],
    )


class GithubRendererTests(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.repo, "src", "app"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def _git(self, *args: str) -> None:
        import subprocess
        subprocess.run(
            ["git", *args], cwd=self.repo, check=True,
            capture_output=True, timeout=60,
        )

    def test_cli_format_flag_choices_and_default_unchanged(self):
        from sot_graph.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["diff-impact", "HEAD~1", "--format", "github"])
        self.assertEqual(args.format, "github")
        # Legacy default: no --format means historical behavior (text/--json).
        legacy = parser.parse_args(["diff-impact"])
        self.assertIsNone(legacy.format)

    def test_cmd_diff_impact_github_end_to_end(self):
        """Real mini repo + real index: stdout must be a redirect-safe PR body."""
        import io
        from contextlib import redirect_stdout

        from sot_graph.cli import build_parser, cmd_diff_impact
        from sot_graph.db import Database
        from sot_graph.reconciler import Reconciler

        self._git("init", "-q")
        self._git("-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "--allow-empty", "-q", "-m", "base")
        Path(self.repo, "src/app").mkdir(parents=True, exist_ok=True)
        Path(self.repo, "src/app/store.py").write_text(
            "def fetch(key):\n    return key\n", encoding="utf-8"
        )
        self._git("add", ".")
        self._git("-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-q", "-m", "add store")

        db = Database(os.path.join(self.repo, ".sot", "test.db"))
        try:
            Reconciler(db, self.repo).reconcile(workers=1)
            # Single revision diffs <rev>~1..<rev>: HEAD = the store.py commit.
            args = build_parser().parse_args(
                ["diff-impact", "HEAD", "--format", "github"]
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = cmd_diff_impact(args, db, self.repo)
        finally:
            db.close()

        self.assertEqual(code, 0)
        out = buffer.getvalue()
        self.assertIn(GITHUB_COMMENT_MARKER, out)
        self.assertIn("<details>", out)
        self.assertIn("SOT-Graph Diff Impact", out)
        self.assertNotIn("\x1b", out)
        self.assertNotIn(self.repo, out)  # runner-absolute paths must not leak
        self.assertIn("`src/app/store.py`", out)

    def test_risk_verdict_line_and_details_blocks(self):
        md = format_diff_impact_github(_result(self.repo), repo_root=self.repo)
        self.assertIn(GITHUB_COMMENT_MARKER, md)
        self.assertIn("HIGH", md)
        self.assertIn("72/100", md)
        self.assertIn("<details>", md)
        self.assertIn("</details>", md)
        self.assertIn("<summary>", md)
        # One collapsed section per report area.
        self.assertGreaterEqual(md.count("<details>"), 4)
        self.assertIn("upstream callers", md)
        self.assertIn("test verification", md)

    def test_no_ansi_escapes(self):
        md = format_diff_impact_github(_result(self.repo), repo_root=self.repo)
        self.assertNotIn("\x1b", md)

    def test_repo_relative_paths_only(self):
        md = format_diff_impact_github(_result(self.repo), repo_root=self.repo)
        self.assertNotIn(self.repo, md)
        self.assertIn("`src/app/store.py`", md)
        self.assertIn("`tests/test_store.py`", md)
        self.assertNotIn("/repo/", md)

    def test_deterministic_ordering(self):
        r = _result()
        first = format_diff_impact_github(r, repo_root=self.repo)
        second = format_diff_impact_github(r, repo_root=self.repo)
        self.assertEqual(first, second)
        # Same-depth callers must appear sorted by symbol, not insertion order.
        self.assertLess(first.index("acaller"), first.index("zcaller"))

    def test_empty_result_renders_placeholder_sections(self):
        empty = DiffImpactResult(
            target="HEAD",
            repo_path=self.repo,
            summary={
                "risk_score": 0, "risk_level": "LOW",
                "total_changed_files": 0, "total_hunks": 0,
                "total_direct_nodes": 0, "total_callers": 0,
                "total_apis": 0, "total_tests": 0,
                "execution_time_ms": 1,
            },
            changed_files=[], direct_nodes=[], caller_impacts=[],
            api_impacts=[], test_impacts=[],
        )
        md = format_diff_impact_github(empty, repo_root=self.repo)
        self.assertIn("LOW", md)
        self.assertIn("<details>", md)
        self.assertNotIn("\x1b", md)


def _zero_caller_result(repo: str = "/repo") -> DiffImpactResult:
    """Same fabricated engine output as _result(), but with no callers."""
    r = _result(repo)
    r.caller_impacts = []
    r.summary = dict(r.summary, total_callers=0)
    return r


class GithubRendererHonestyTests(unittest.TestCase):
    """SG-103: the renderer must state receipt completeness honestly.

    A zero-callers claim is only "low ripple" when an ASSURED receipt
    proves completeness; otherwise the comment says so explicitly.
    """

    def setUp(self):
        self.repo = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    @staticmethod
    def _attach(result: DiffImpactResult, **receipt_fields) -> DiffImpactResult:
        """Thread receipt fields onto a result like cmd_diff_impact does."""
        for key, value in receipt_fields.items():
            setattr(result, key, value)
        return result

    def _receipt(self, status: str, reason_codes=None, truncated: bool = False):
        return {
            "assurance": {"status": status, "reason_codes": reason_codes or []},
            "assurance_facts": {"coverage_fraction": None, "truncated": truncated},
            "changed_files_truncated": truncated,
            "changed_files_total": 7,
            "post_change_snapshot": {
                "commit_sha": "abc123def4567890",
                "descriptor_digest": "deadbeef" * 8,
                "dirty": False,
            },
        }

    def test_partial_status_shows_reasons_and_truncation(self):
        r = self._attach(
            _zero_caller_result(self.repo),
            **self._receipt("PARTIAL", reason_codes=["changed_files_truncated"],
                            truncated=True),
        )
        md = format_diff_impact_github(r, repo_root=self.repo)
        self.assertIn("**Assurance:**", md)
        self.assertIn("status **PARTIAL**", md)
        self.assertIn("`changed_files_truncated`", md)
        self.assertIn("changed-files truncated: yes", md)
        # Snapshot head rendered short (12 chars).
        self.assertIn("snapshot `abc123def456`", md)
        self.assertNotIn("low ripple", md)
        self.assertIn("completeness not proven (status PARTIAL:", md)

    def test_assured_zero_callers_keeps_low_ripple_wording(self):
        r = self._attach(
            _zero_caller_result(self.repo),
            **self._receipt("ASSURED_WITHIN_SCOPE"),
        )
        md = format_diff_impact_github(r, repo_root=self.repo)
        self.assertIn("status **ASSURED_WITHIN_SCOPE**", md)
        self.assertIn("changed-files truncated: no", md)
        self.assertIn("low ripple effect; assured within verified scope", md)

    def test_no_receipt_never_claims_low_ripple(self):
        """Plain engine result (no receipt): honesty falls back to unproven."""
        md = format_diff_impact_github(_zero_caller_result(self.repo), repo_root=self.repo)
        self.assertNotIn("low ripple", md)
        self.assertNotIn("**Assurance:**", md)
        self.assertIn("completeness not proven (status NO_RECEIPT:", md)

    def test_resolved_range_identity_rendered(self):
        """SG-101: resolved request identity is auditable in the comment."""
        r = _zero_caller_result(self.repo)
        r.summary = dict(
            r.summary,
            diff_spec="1234abc...5678def",
            resolved_base="1234abcdef" * 4,
            resolved_head="5678abcdef" * 4,
        )
        md = format_diff_impact_github(r, repo_root=self.repo)
        self.assertIn("**Resolved range:** `1234abc...5678def`", md)
        # Sha identities render short (12 chars).
        self.assertIn("base `1234abcdef12`", md)
        self.assertIn("head `5678abcdef56`", md)


if __name__ == "__main__":
    unittest.main()
