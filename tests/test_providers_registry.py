"""Tests for sot_graph.providers_registry — read-only provider detection & CLI."""
from __future__ import annotations

import copy
import json
import os
import stat
from pathlib import Path

import pytest

from sot_graph.cli import main as cli_main
from sot_graph.config import DEFAULT_PROVIDERS, SotConfig
from sot_graph.providers_registry import detect_providers, resolve_capability

HEALTHY_VERSION_SCRIPT = "#!/bin/sh\necho 'gitnexus 1.2.3'\n"
FAILING_VERSION_SCRIPT = "#!/bin/sh\necho 'boom' >&2\nexit 1\n"


def make_fake_exe(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def config_with_defaults(allow_external: bool = True, **scalars) -> SotConfig:
    providers = {name: copy.deepcopy(pcfg) for name, pcfg in DEFAULT_PROVIDERS.items()}
    return SotConfig(providers=providers, allow_external=allow_external, **scalars)


@pytest.fixture()
def fake_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated PATH directory; tests add executables to it explicitly."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    # CLI handlers go through load_config(); opt into external providers.
    monkeypatch.setenv("SOT_PROVIDERS_ALLOW_EXTERNAL", "true")
    return bindir


def names(statuses) -> list[str]:
    return [st.name for st in statuses]


def by_name(statuses) -> dict:
    return {st.name: st for st in statuses}


class TestDetect:
    def test_installed_executable_reports_version(self, tmp_path: Path, fake_bin: Path):
        make_fake_exe(fake_bin, "gitnexus", HEALTHY_VERSION_SCRIPT)
        statuses = detect_providers(str(tmp_path), config_with_defaults())
        found = by_name(statuses)
        assert "gitnexus" in found
        gitnexus = found["gitnexus"]
        assert gitnexus.installed is True
        assert gitnexus.healthy is True
        assert gitnexus.version == "gitnexus 1.2.3"
        assert gitnexus.detail.startswith("executable at ")

    def test_scip_artifact_present_means_installed_with_mtime(self, tmp_path: Path, fake_bin: Path):
        (tmp_path / "index.scip").write_bytes(b"\x00scip")
        statuses = detect_providers(str(tmp_path), config_with_defaults())
        scip = by_name(statuses)["scip"]
        assert scip.installed is True
        assert scip.healthy is True
        assert scip.version is None
        assert "index.scip" in scip.detail
        assert "mtime" in scip.detail

    def test_missing_executable_not_installed(self, tmp_path: Path, fake_bin: Path):
        statuses = detect_providers(str(tmp_path), config_with_defaults())
        gitnexus = by_name(statuses)["gitnexus"]
        assert gitnexus.installed is False
        assert gitnexus.healthy is False
        assert "not found in PATH" in gitnexus.detail

    def test_failing_version_probe_is_unhealthy_with_detail(self, tmp_path: Path, fake_bin: Path):
        make_fake_exe(fake_bin, "gitnexus", FAILING_VERSION_SCRIPT)
        statuses = detect_providers(str(tmp_path), config_with_defaults())
        gitnexus = by_name(statuses)["gitnexus"]
        assert gitnexus.installed is True
        assert gitnexus.healthy is False
        assert "exited with code 1" in gitnexus.detail
        assert "boom" in gitnexus.detail

    def test_allow_external_false_limits_to_builtin_and_scip(self, tmp_path: Path, fake_bin: Path):
        make_fake_exe(fake_bin, "gitnexus", HEALTHY_VERSION_SCRIPT)
        cfg = config_with_defaults(allow_external=False)
        statuses = detect_providers(str(tmp_path), cfg)
        assert sorted(names(statuses)) == ["scip", "sot-builtin"]


class TestResolveCapability:
    def test_impact_ranks_gitnexus_first_builtin_last(self, tmp_path: Path, fake_bin: Path):
        make_fake_exe(fake_bin, "gitnexus", HEALTHY_VERSION_SCRIPT)
        ranked = resolve_capability(str(tmp_path), "impact", config_with_defaults())
        assert names(ranked)[0] == "gitnexus"
        assert names(ranked)[-1] == "sot-builtin"

    def test_impact_without_gitnexus_still_has_builtin_fallback(self, tmp_path: Path, fake_bin: Path):
        ranked = resolve_capability(str(tmp_path), "impact", config_with_defaults())
        # codebase-memory executable is absent too; only the builtin survives.
        assert names(ranked) == ["sot-builtin"]

    def test_pdg_taint_never_return_builtin(self, tmp_path: Path, fake_bin: Path):
        make_fake_exe(fake_bin, "gitnexus", FAILING_VERSION_SCRIPT)
        for cap in ("pdg", "taint"):
            ranked = resolve_capability(str(tmp_path), cap, config_with_defaults())
            assert ranked == []

    def test_allow_external_false_excludes_gitnexus_from_impact(self, tmp_path: Path, fake_bin: Path):
        make_fake_exe(fake_bin, "gitnexus", HEALTHY_VERSION_SCRIPT)
        cfg = config_with_defaults(allow_external=False)
        ranked = resolve_capability(str(tmp_path), "impact", cfg)
        assert "gitnexus" not in names(ranked)

    def test_repo_map_orders_by_coverage(self, tmp_path: Path, fake_bin: Path):
        make_fake_exe(fake_bin, "gitnexus", HEALTHY_VERSION_SCRIPT)
        ranked = resolve_capability(str(tmp_path), "repo-map", config_with_defaults())
        assert names(ranked)[-1] == "sot-builtin"
        # gitnexus advertises 6 capabilities vs codebase-memory's 5.
        assert names(ranked)[0] == "gitnexus"


class TestCliProviders:
    def test_detect_json_smoke(self, tmp_path: Path, fake_bin: Path, capsys: pytest.CaptureFixture):
        make_fake_exe(fake_bin, "gitnexus", HEALTHY_VERSION_SCRIPT)
        rc = cli_main(["--root", str(tmp_path), "providers", "detect", "--format", "json"])
        captured = capsys.readouterr()
        assert rc == 0
        payload = json.loads(captured.out)
        assert isinstance(payload, list)
        entry = next(e for e in payload if e["name"] == "gitnexus")
        assert entry["installed"] is True
        assert entry["version"] == "gitnexus 1.2.3"

    def test_doctor_exit_code_zero_when_optional_missing(
        self, tmp_path: Path, fake_bin: Path, capsys: pytest.CaptureFixture
    ):
        rc = cli_main(["--root", str(tmp_path), "providers", "doctor", "--format", "json"])
        captured = capsys.readouterr()
        assert rc == 0
        report = json.loads(captured.out)
        assert report["ok"] is True

    def test_doctor_exit_code_one_when_required_unhealthy(
        self, tmp_path: Path, fake_bin: Path, capsys: pytest.CaptureFixture
    ):
        make_fake_exe(fake_bin, "gitnexus", FAILING_VERSION_SCRIPT)
        cfg_dir = tmp_path / ".sot"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text('[providers.gitnexus]\nenabled = true\n')
        rc = cli_main(["--root", str(tmp_path), "providers", "doctor"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "gitnexus" in captured.out

    def test_resolve_json_returns_ranked_list(self, tmp_path: Path, fake_bin: Path, capsys: pytest.CaptureFixture):
        make_fake_exe(fake_bin, "gitnexus", HEALTHY_VERSION_SCRIPT)
        rc = cli_main(["--root", str(tmp_path), "providers", "resolve", "--capability", "impact", "--format", "json"])
        captured = capsys.readouterr()
        assert rc == 0
        payload = json.loads(captured.out)
        assert [e["name"] for e in payload][0] == "gitnexus"

    def test_list_json_lists_all_configured(self, tmp_path: Path, fake_bin: Path, capsys: pytest.CaptureFixture):
        rc = cli_main(["--root", str(tmp_path), "providers", "list", "--format", "json"])
        captured = capsys.readouterr()
        assert rc == 0
        payload = json.loads(captured.out)
        assert {"sot-builtin", "gitnexus", "codebase-memory", "scip"} <= {e["name"] for e in payload}
