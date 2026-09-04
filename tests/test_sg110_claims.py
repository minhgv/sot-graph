"""SG-110: machine-readable claim registry + docs claim linter.

Three layers:
  - registry parsing/structural validation on broken YAML fixtures;
  - claim validation inside a real (temporary) git repo — artifact traces,
    provenance ancestry, metric mismatches, docs<->registry drift;
  - the live repo tripwire: `sot claims lint` must be green at HEAD, the
    registry must keep a sanity floor of entries, and every banned-phrase
    hit in the real corpus must be classified (registered/hedged/allowed).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sot_graph.claims import (
    BANNED_PATTERNS,
    Claim,
    lint_claims,
    load_registry,
    main as claims_main,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _commit_all(repo: Path, msg: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg, "--no-gpg-sign")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


REGISTRY_HEADER = """\
claims:
  - id: probe-claim
    claim: "probe metric"
    files: [README.md]
    pattern: "probe precision 100%"
    artifact: artifacts/probe.json
    artifact_field: metrics.precision
    artifact_value: 1.0
    commit: "{commit}"
    ceiling: "advisory: synthetic fixture"
"""


def _fixture_repo(
    tmp_path: Path,
    *,
    extra_registry: str = "",
    readme: str = "probe precision 100%\n",
    probe: dict | None = None,
    commit_probe: bool = True,
) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _write(repo / "README.md", readme)
    _write(repo / "AGENTS.md", "agent rules\n")
    payload = probe if probe is not None else {"metrics": {"precision": 1.0}}
    _write(repo / "artifacts" / "probe.json", json.dumps(payload))
    if commit_probe:
        sha = _commit_all(repo, "fixture: docs + artifact")
    else:
        sha = "0" * 40
    _write(
        repo / "claims" / "registry.yaml",
        REGISTRY_HEADER.format(commit=sha) + extra_registry,
    )
    return repo


class TestRegistryParsing:
    def test_missing_registry_fails_closed(self, tmp_path: Path):
        reg = load_registry(tmp_path / "nope.yaml")
        assert reg.issues
        assert reg.issues[0].code == "registry-missing"

    def test_unparseable_yaml(self, tmp_path: Path):
        p = tmp_path / "registry.yaml"
        p.write_text("claims: [unclosed", encoding="utf-8")
        assert load_registry(p).issues[0].code == "registry-unparseable"

    def test_duplicate_id_and_missing_keys(self, tmp_path: Path):
        p = tmp_path / "registry.yaml"
        p.write_text(
            "claims:\n"
            "  - {id: a, claim: c, files: [README.md], pattern: p,"
            " artifact: x, commit: 1, ceiling: t}\n"
            "  - {id: a, claim: c, files: [README.md], pattern: p,"
            " artifact: x, commit: 1, ceiling: t}\n"
            "  - {id: b, claim: c}\n"
            "allow:\n"
            "  - {file: README.md}\n"
            "skip_files:\n"
            "  - 3\n",
            encoding="utf-8",
        )
        reg = load_registry(p)
        codes = [v.code for v in reg.issues]
        assert codes.count("registry-schema") == 4  # dup + missing + allow + skip

    def test_happy_registry_parses(self, tmp_path: Path):
        repo = _fixture_repo(tmp_path)
        reg = load_registry(repo / "claims" / "registry.yaml")
        assert not reg.issues
        assert [c.id for c in reg.claims] == ["probe-claim"]
        assert isinstance(reg.claims[0], Claim)


class TestClaimValidation:
    def test_happy_path_green(self, tmp_path: Path):
        repo = _fixture_repo(tmp_path)
        report = lint_claims(repo)
        assert report["ok"], report["violations"]
        assert report["claims_checked"] == 1
        # The README hit is covered by the registered pattern.
        assert report["hit_classification"]["registered"] >= 1

    def test_doc_drift_detected(self, tmp_path: Path):
        # Pattern removed from the doc: the registry entry loses its anchor
        # and the stale metric row disappears with it.
        repo = _fixture_repo(tmp_path, readme="probe precision 98%\n")
        report = lint_claims(repo)
        codes = {v["code"] for v in report["violations"]}
        assert "docs-drift" in codes
        assert not report["ok"]

    def test_artifact_missing(self, tmp_path: Path):
        repo = _fixture_repo(tmp_path)
        (repo / "artifacts" / "probe.json").unlink()
        codes = {v["code"] for v in lint_claims(repo)["violations"]}
        assert "artifact-missing" in codes

    def test_artifact_untracked(self, tmp_path: Path):
        repo = _fixture_repo(tmp_path)
        # On disk but not in the index: exactly the docs-only-PR hazard.
        _git(repo, "rm", "-q", "--cached", "artifacts/probe.json")
        codes = {v["code"] for v in lint_claims(repo)["violations"]}
        assert "artifact-untracked" in codes

    def test_commit_unknown(self, tmp_path: Path):
        repo = _fixture_repo(tmp_path)
        head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        reg = (repo / "claims" / "registry.yaml").read_text(encoding="utf-8")
        (repo / "claims" / "registry.yaml").write_text(
            reg.replace(head_sha, "f" * 40), encoding="utf-8"
        )
        codes = {v["code"] for v in lint_claims(repo)["violations"]}
        assert "commit-unknown" in codes

    def test_commit_not_ancestor(self, tmp_path: Path):
        repo = _fixture_repo(tmp_path)
        # Commit on an orphan branch: a real object that is NOT an ancestor
        # of the branch HEAD the linter validates against. `git add` only
        # the marker file so the (untracked) registry survives the switch.
        _git(repo, "checkout", "-q", "--orphan", "side")
        _write(repo / "orphan.txt", "x\n")
        _git(repo, "add", "orphan.txt")
        _git(repo, "commit", "-m", "orphan", "--no-gpg-sign")
        orphan_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "-q", "main")
        reg = (repo / "claims" / "registry.yaml").read_text(encoding="utf-8")
        head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / "claims" / "registry.yaml").write_text(
            reg.replace(head_sha, orphan_sha), encoding="utf-8"
        )
        codes = {v["code"] for v in lint_claims(repo)["violations"]}
        assert "commit-not-ancestor" in codes

    def test_artifact_value_mismatch(self, tmp_path: Path):
        repo = _fixture_repo(
            tmp_path,
            probe={"metrics": {"precision": 0.5}},
            commit_probe=True,
        )
        # Artifact re-committed with the drifted value: tracked + real
        # provenance, but it no longer supports the registered claim.
        _commit_all(repo, "artifact drift")
        codes = {v["code"] for v in lint_claims(repo)["violations"]}
        assert "artifact-mismatch" in codes

    def test_artifact_field_missing(self, tmp_path: Path):
        repo = _fixture_repo(tmp_path, probe={"other": 1}, commit_probe=True)
        codes = {v["code"] for v in lint_claims(repo)["violations"]}
        assert "artifact-field-missing" in codes

    def test_artifact_unparseable(self, tmp_path: Path):
        repo = _fixture_repo(tmp_path)
        _write(repo / "artifacts" / "probe.json", "{not json")
        _commit_all(repo, "corrupt artifact")
        codes = {v["code"] for v in lint_claims(repo)["violations"]}
        assert "artifact-unparseable" in codes

    def test_artifact_symbol_enforced(self, tmp_path: Path):
        repo = _fixture_repo(tmp_path)
        sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        extra = (
            "  - id: prop-claim\n"
            "    claim: enforced property\n"
            "    files: [AGENTS.md]\n"
            '    pattern: "strict isolation"\n'
            "    artifact: tests/test_fake.py\n"
            '    artifact_symbol: "def test_isolation"\n'
            f'    commit: "{sha}"\n'
            "    ceiling: test-enforced\n"
        )
        _write(repo / "AGENTS.md", "agent rules strict isolation\n")
        # Artifact exists and is committed, but lacks the enforcing symbol.
        _write(repo / "tests" / "test_fake.py", "def test_other(): pass\n")
        _commit_all(repo, "prop claim without enforcing symbol")
        (repo / "claims" / "registry.yaml").write_text(
            REGISTRY_HEADER.format(commit=sha) + extra, encoding="utf-8"
        )
        codes = {v["code"] for v in lint_claims(repo)["violations"]}
        assert "artifact-symbol-missing" in codes

    def test_claim_outside_corpus_flagged(self, tmp_path: Path):
        repo = _fixture_repo(tmp_path)
        sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        extra = (
            "  - id: outside\n"
            "    claim: outside corpus\n"
            "    files: [EXTRA.md]\n"
            '    pattern: "x"\n'
            "    artifact: artifacts/probe.json\n"
            f'    commit: "{sha}"\n'
            "    ceiling: t\n"
        )
        _write(repo / "EXTRA.md", "x\n")
        (repo / "claims" / "registry.yaml").write_text(
            REGISTRY_HEADER.format(commit=sha) + extra, encoding="utf-8"
        )
        codes = {v["code"] for v in lint_claims(repo)["violations"]}
        assert "claim-outside-corpus" in codes


class TestBannedScan:
    def _bare(self, tmp_path: Path, readme: str, extra: str = "") -> dict:
        repo = _fixture_repo(tmp_path, readme=readme)
        # Drop the registered claim so the scan sees only `readme` content.
        (repo / "claims" / "registry.yaml").write_text(
            f"claims: []\n{extra}", encoding="utf-8"
        )
        return lint_claims(repo)

    def test_unregistered_absolute_claim(self, tmp_path: Path):
        report = self._bare(tmp_path, "engine is 100% correct\n")
        assert not report["ok"]
        v = report["violations"][0]
        assert v["code"] == "unregistered-absolute-claim"
        assert v["file"] == "README.md" and v["line"] == 1

    def test_hedged_line_passes(self, tmp_path: Path):
        report = self._bare(tmp_path, "100% coverage (advisory, scoped)\n")
        assert report["ok"]
        assert report["hit_classification"]["hedged"] >= 1

    @pytest.mark.parametrize(
        "phrase",
        [
            "zero hallucinated anchors",
            "guaranteed exact",
            "authoritative source",
            "status PRODUCTION_QUALIFIED today",
        ],
    )
    def test_banned_families(self, tmp_path: Path, phrase: str):
        report = self._bare(tmp_path, f"we provide {phrase}\n")
        assert not report["ok"], phrase

    def test_allow_entry_covers_hit(self, tmp_path: Path):
        report = self._bare(
            tmp_path,
            "competitor column (100% Local)\n",
            extra=(
                "allow:\n"
                "  - file: README.md\n"
                "    contains: (100% Local)\n"
                "    reason: competitor description\n"
            ),
        )
        assert report["ok"]
        assert report["hit_classification"]["allowed"] == 1

    def test_stale_allow_entry_fails(self, tmp_path: Path):
        report = self._bare(
            tmp_path,
            "plain text\n",
            extra=(
                "allow:\n"
                "  - file: README.md\n"
                "    contains: vanished phrase\n"
                "    reason: stale\n"
            ),
        )
        codes = {v["code"] for v in report["violations"]}
        assert "allow-stale" in codes

    def test_skip_files_bypass_scan(self, tmp_path: Path):
        repo = _fixture_repo(tmp_path, readme="plain\n")
        _write(repo / "docs" / "FROZEN.md", "frozen 100% record\n")
        (repo / "claims" / "registry.yaml").write_text(
            "claims: []\nskip_files:\n  - docs/FROZEN.md\n", encoding="utf-8"
        )
        report = lint_claims(repo)
        assert report["ok"]
        assert "docs/FROZEN.md" in report["skipped_files"]


class TestRealRepoTripwire:
    """The live repo must lint green — this is the CI gate for docs PRs."""

    def test_live_repo_claims_green(self):
        report = lint_claims(PROJECT_ROOT)
        assert report["ok"], json.dumps(report["violations"], indent=2)

    def test_registry_floor(self):
        reg = load_registry(PROJECT_ROOT / "claims" / "registry.yaml")
        assert not reg.issues
        # Guards against quietly gutting the registry to make lint pass:
        # the public claims we ship today must stay registered.
        ids = {c.id for c in reg.claims}
        assert len(ids) >= 10
        assert {
            "search-exact-row",
            "builtin-oracle-f1",
            "diff-impact-oracle-macro",
            "root-isolation-guarantee",
        } <= ids

    def test_every_claim_artifact_exists_and_tracked(self):
        reg = load_registry(PROJECT_ROOT / "claims" / "registry.yaml")
        for c in reg.claims:
            assert (PROJECT_ROOT / c.artifact).is_file(), c.id
        tracked = set(
            subprocess.run(
                ["git", "-C", str(PROJECT_ROOT), "ls-files"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.splitlines()
        )
        for c in reg.claims:
            assert c.artifact in tracked, f"{c.id}: {c.artifact} untracked"

    def test_all_banned_hits_classified(self):
        report = lint_claims(PROJECT_ROOT)
        h = report["hit_classification"]
        assert h["banned_hits"] == (h["registered"] + h["hedged"] + h["allowed"])
        assert h["banned_hits"] > 0  # the scan must actually see traffic

    def test_cli_entry_exit_codes(self, capsys):
        assert claims_main(["--json", str(PROJECT_ROOT)]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True


class TestBannedPatternContract:
    def test_guaranteeing_matches(self):
        import re

        rx = dict(BANNED_PATTERNS)["guarantee"]
        assert re.search(rx, "guaranteeing strict isolation", re.IGNORECASE)

    def test_line_lookup(self):
        from sot_graph.claims import _line_of

        text = "a\nbb 100%\nccc"
        line_no, line = _line_of(text, text.index("100%"))
        assert line_no == 2 and "bb" in line
