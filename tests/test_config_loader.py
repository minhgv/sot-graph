"""Tests for sot_graph.config — project-local provider federation config."""

from __future__ import annotations

import dataclasses
import os
import sys
if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10 — mirror sot_graph.config's tomli fallback
    import tomli as tomllib
from pathlib import Path

import pytest

from sot_graph.config import (
    CONFIG_RELATIVE_PATH,
    DEFAULT_PROVIDERS,
    ENV_PROVIDERS_ALLOW_EXTERNAL,
    ENV_PROVIDERS_MODE,
    SotConfig,
    load_config,
)

CANONICAL_PROVIDERS = ("sot-builtin", "gitnexus", "codebase-memory", "scip")


def write_config(root: Path, body: str) -> Path:
    config_dir = root / ".sot"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"
    config_path.write_text(body, encoding="utf-8")
    return config_path


class TestDefaultsWithoutFile:
    def test_no_file_yields_full_defaults(self, tmp_path: Path):
        cfg = load_config(str(tmp_path))

        assert isinstance(cfg, SotConfig)
        assert cfg.providers_mode == "auto"
        assert cfg.allow_external is False
        assert cfg.conflict_policy == "abstain"
        assert cfg.verification_provider == "sot-builtin"
        assert set(cfg.providers) == set(CANONICAL_PROVIDERS)

        builtin = cfg.providers["sot-builtin"]
        assert builtin.enabled is True
        assert builtin.command is None
        assert builtin.integration == "embedded"

        gitnexus = cfg.providers["gitnexus"]
        assert gitnexus.command == ["gitnexus"]
        assert gitnexus.timeout_seconds == 30.0
        assert set(gitnexus.capabilities) == {
            "symbols", "callgraph", "impact", "trace", "pdg", "taint",
        }

        cbm = cfg.providers["codebase-memory"]
        assert cbm.command == ["codebase-memory-mcp"]
        assert set(cbm.capabilities) == {
            "symbols", "callgraph", "architecture", "impact",
            "broad-language-discovery",
        }

        scip = cfg.providers["scip"]
        assert scip.enabled is None  # auto-detect

    def test_default_providers_table_matches_module_constant(self, tmp_path: Path):
        cfg = load_config(str(tmp_path))
        for name, default in DEFAULT_PROVIDERS.items():
            assert dataclasses.replace(cfg.providers[name]) == default


class TestFileOverrides:
    def test_partial_field_overrides_merge_onto_defaults(self, tmp_path: Path):
        write_config(
            tmp_path,
            """
            [providers.gitnexus]
            timeout_seconds = 12.5
            enabled = false

            [providers.codebase-memory]
            index_policy = "always-refresh"

            [providers.sot-builtin]
            capabilities = ["baseline"]
            """,
        )
        cfg = load_config(str(tmp_path))

        gitnexus = cfg.providers["gitnexus"]
        assert gitnexus.timeout_seconds == 12.5
        assert gitnexus.enabled is False
        # Untouched fields keep defaults.
        assert gitnexus.command == ["gitnexus"]
        assert gitnexus.integration == "cli"

        assert cfg.providers["codebase-memory"].index_policy == "always-refresh"
        assert cfg.providers["sot-builtin"].capabilities == ["baseline"]

        # Untouched providers untouched.
        assert cfg.providers["scip"].enabled is None

    def test_top_level_scalars_overridden_by_file(self, tmp_path: Path):
        write_config(
            tmp_path,
            """
            providers_mode = "manual"
            allow_external = true
            conflict_policy = "prefer-exact"
            verification_provider = "gitnexus"
            """,
        )
        cfg = load_config(str(tmp_path))
        assert cfg.providers_mode == "manual"
        assert cfg.allow_external is True
        assert cfg.conflict_policy == "prefer-exact"
        assert cfg.verification_provider == "gitnexus"


class TestEnvOverrides:
    def test_env_mode_beats_file_and_defaults(self, tmp_path: Path, monkeypatch):
        write_config(tmp_path, 'providers_mode = "auto"\n')
        monkeypatch.setenv(ENV_PROVIDERS_MODE, "manual")
        cfg = load_config(str(tmp_path))
        assert cfg.providers_mode == "manual"

    def test_env_allow_external_parses_boolean(self, tmp_path: Path, monkeypatch):
        for raw, expected in (("1", True), ("true", True), ("yes", True),
                              ("0", False), ("false", False), ("off", False)):
            monkeypatch.setenv(ENV_PROVIDERS_ALLOW_EXTERNAL, raw)
            assert load_config(str(tmp_path)).allow_external is expected, raw

    def test_invalid_env_boolean_raises_value_error(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv(ENV_PROVIDERS_ALLOW_EXTERNAL, "maybe")
        with pytest.raises(ValueError, match=ENV_PROVIDERS_ALLOW_EXTERNAL):
            load_config(str(tmp_path))

    def test_invalid_env_mode_raises_value_error(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv(ENV_PROVIDERS_MODE, "yolo")
        with pytest.raises(ValueError, match=ENV_PROVIDERS_MODE):
            load_config(str(tmp_path))


class TestOverridesDict:
    def test_overrides_beat_file_and_env(self, tmp_path: Path, monkeypatch):
        write_config(
            tmp_path,
            """
            providers_mode = "manual"
            [providers.gitnexus]
            timeout_seconds = 10.0
            enabled = true
            """,
        )
        monkeypatch.setenv(ENV_PROVIDERS_MODE, "manual")

        cfg = load_config(
            str(tmp_path),
            overrides={
                "providers_mode": "auto",
                "conflict_policy": "prefer-fresh",
                "providers": {"gitnexus": {"timeout_seconds": 99.0}},
            },
        )
        assert cfg.providers_mode == "auto"          # beats env + file
        assert cfg.conflict_policy == "prefer-fresh"  # beats default
        assert cfg.providers["gitnexus"].timeout_seconds == 99.0
        # File-only field survives when overrides don't touch it.
        assert cfg.providers["gitnexus"].enabled is True

    def test_override_introduces_unknown_provider(self, tmp_path: Path):
        cfg = load_config(
            str(tmp_path),
            overrides={
                "providers": {"my-lsp": {"command": ["mylsp", "--serve"],
                                         "integration": "cli"}},
            },
        )
        assert set(cfg.providers) >= {"my-lsp"} | set(CANONICAL_PROVIDERS)
        my_lsp = cfg.providers["my-lsp"]
        assert my_lsp.name == "my-lsp"
        assert my_lsp.command == ["mylsp", "--serve"]


class TestForwardCompatibilityAndValidation:
    def test_unknown_keys_silently_ignored(self, tmp_path: Path):
        write_config(
            tmp_path,
            """
            future_top_level = "whatever"
            [providers.gitnexus]
            timeout_seconds = 5.0
            some_future_flag = true

            [providers.brand-new-thing]
            enabled = false
            """,
        )
        cfg = load_config(str(tmp_path))
        assert cfg.providers["gitnexus"].timeout_seconds == 5.0
        assert "brand-new-thing" in cfg.providers

    @pytest.mark.parametrize(
        ("body", "key"),
        [
            ('[providers.gitnexus]\ntimeout_seconds = "fast"\n', "timeout_seconds"),
            ('[providers.gitnexus]\ncapabilities = "symbols"\n', "capabilities"),
            ('[providers.gitnexus]\ncommand = "gitnexus"\n', "command"),
            ('[providers.gitnexus]\nenabled = "sure"\n', "enabled"),
            ('providers_mode = 2\n', "providers_mode"),
            ('allow_external = "true"\n', "allow_external"),
            ('conflict_policy = "win-anyway"\n', "conflict_policy"),
            ('[providers.gitnexus]\nintegration = "carrier-pigeon"\n', "integration"),
            ('[providers.gitnexus]\nindex_policy = "sometimes"\n', "index_policy"),
        ],
    )
    def test_wrong_type_or_value_raises_value_error_naming_key(
        self, tmp_path: Path, body: str, key: str
    ):
        config_path = write_config(tmp_path, body)
        with pytest.raises(ValueError) as excinfo:
            load_config(str(tmp_path))
        message = str(excinfo.value)
        assert key in message
        assert str(config_path) in message

    def test_malformed_toml_raises_value_error_with_file(self, tmp_path: Path):
        config_path = write_config(tmp_path, "[providers.gitnexus\nbroken ===")
        with pytest.raises(ValueError, match="malformed TOML") as excinfo:
            load_config(str(tmp_path))
        assert str(config_path) in str(excinfo.value)

    def test_override_dict_type_error_names_overrides_source(self, tmp_path: Path):
        with pytest.raises(ValueError, match="<overrides>") as excinfo:
            load_config(str(tmp_path), overrides={"providers": {"gitnexus": 7}})
        assert "gitnexus" in str(excinfo.value)


class TestPathHandling:
    def test_repo_root_with_spaces_and_unicode(self, tmp_path: Path):
        root = tmp_path / "My Repo ✨ và Dự Án"
        root.mkdir()
        write_config(root, '[providers.gitnexus]\ntimeout_seconds = 42.0\n')
        cfg = load_config(str(root))
        assert cfg.providers["gitnexus"].timeout_seconds == 42.0

    def test_config_relative_path_layout(self):
        assert CONFIG_RELATIVE_PATH == os.path.join(".sot", "config.toml")


class TestTomllibFallback:
    def test_tomllib_available_on_current_interpreter(self):
        import sot_graph.config as cfg_mod

        # The module must expose a working TOML parser either way.
        assert hasattr(cfg_mod, "tomllib")
        parsed = cfg_mod.tomllib.loads('a = [1, 2]\nb = "x"\n')
        assert parsed == {"a": [1, 2], "b": "x"}

        if sys.version_info >= (3, 11):
            assert cfg_mod.tomllib is tomllib
        else:
            import tomli

            assert cfg_mod.tomllib is tomli
