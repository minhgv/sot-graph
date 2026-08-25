"""Project-local configuration for SOT-Graph provider federation.

Loads ``<repo_root>/.sot/config.toml`` and merges four layers, lowest to
highest precedence::

    built-in defaults  <  .sot/config.toml  <  environment variables  <  overrides

Environment variables honored:

* ``SOT_PROVIDERS_MODE``            -> ``providers_mode``   (auto | manual)
* ``SOT_PROVIDERS_ALLOW_EXTERNAL``  -> ``allow_external``   (boolean)

Unknown keys in the TOML file are silently ignored (forward compatibility).
Simple type mistakes (e.g. a string where a list is required) raise
:class:`ValueError` with an actionable message naming the file and key.
"""

from __future__ import annotations

import copy
import os
import sys
from dataclasses import dataclass, field
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python < 3.11
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError as _exc:  # pragma: no cover
        raise ImportError(
            "Parsing '.sot/config.toml' on Python < 3.11 requires 'tomli'. "
            "Install it with: pip install 'tomli>=1.1'"
        ) from _exc

__all__ = [
    "CONFIG_RELATIVE_PATH",
    "ENV_PROVIDERS_MODE",
    "ENV_PROVIDERS_ALLOW_EXTERNAL",
    "DEFAULT_PROVIDERS",
    "ProviderConfig",
    "SotConfig",
    "load_config",
]

CONFIG_RELATIVE_PATH = os.path.join(".sot", "config.toml")
ENV_PROVIDERS_MODE = "SOT_PROVIDERS_MODE"
ENV_PROVIDERS_ALLOW_EXTERNAL = "SOT_PROVIDERS_ALLOW_EXTERNAL"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off", ""}

_TOP_LEVEL_ENUMS: dict[str, tuple[str, ...]] = {
    "providers_mode": ("auto", "manual"),
    "conflict_policy": ("abstain", "prefer-exact", "prefer-fresh"),
}
_TOP_LEVEL_BOOLS = ("allow_external",)
_TOP_LEVEL_STRINGS = ("verification_provider",)

_PROVIDER_ENUMS: dict[str, tuple[str, ...]] = {
    "integration": ("cli", "mcp", "import", "embedded"),
    "index_policy": ("reuse", "refresh-if-stale", "always-refresh", "never"),
}
_PROVIDER_OPTIONAL_BOOLS = ("enabled",)
_PROVIDER_LISTS = ("command", "capabilities")
_PROVIDER_FLOATS = ("timeout_seconds",)


@dataclass
class ProviderConfig:
    """Configuration for a single ``[providers.<name>]`` entry."""

    name: str
    enabled: bool | None = None  # None = auto-detect
    command: list[str] | None = None
    integration: str = "cli"
    index_policy: str = "reuse"
    timeout_seconds: float = 30.0
    capabilities: list[str] = field(default_factory=list)


@dataclass
class SotConfig:
    """Resolved provider-federation configuration for a repository."""

    providers_mode: str = "auto"
    allow_external: bool = False
    conflict_policy: str = "abstain"
    verification_provider: str = "sot-builtin"
    providers: dict[str, ProviderConfig] = field(default_factory=dict)


#: Built-in defaults, keyed by canonical provider name.
DEFAULT_PROVIDERS: dict[str, ProviderConfig] = {
    "sot-builtin": ProviderConfig(
        name="sot-builtin",
        enabled=True,
        command=None,
        integration="embedded",
        index_policy="reuse",
        timeout_seconds=0.0,
        capabilities=["baseline", "fallback", "source-verification"],
    ),
    "gitnexus": ProviderConfig(
        name="gitnexus",
        enabled=None,
        command=["gitnexus"],
        integration="cli",
        index_policy="reuse",
        timeout_seconds=30.0,
        capabilities=["symbols", "callgraph", "impact", "trace", "pdg", "taint"],
    ),
    "codebase-memory": ProviderConfig(
        name="codebase-memory",
        enabled=None,
        command=["codebase-memory-mcp"],
        integration="cli",
        index_policy="reuse",
        timeout_seconds=30.0,
        capabilities=[
            "symbols",
            "callgraph",
            "architecture",
            "impact",
            "broad-language-discovery",
        ],
    ),
    "scip": ProviderConfig(
        name="scip",
        enabled=None,
        command=["scip"],
        integration="import",
        index_policy="reuse",
        timeout_seconds=30.0,
        capabilities=["symbols", "require-snapshot-match"],
    ),
}


def _value_error(source: str, key: str, expected: str, value: Any) -> ValueError:
    return ValueError(
        f"{source}: invalid value for key '{key}': expected {expected}, "
        f"got {type(value).__name__} ({value!r})"
    )


def _coerce_enum(source: str, key: str, value: Any, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str):
        raise _value_error(source, key, f"a string in {'/'.join(allowed)}", value)
    if value not in allowed:
        raise _value_error(
            source, key, f"one of {'/'.join(allowed)}", value
        )
    return value


def _coerce_bool(source: str, key: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise _value_error(source, key, "a boolean (true/false)", value)


def _coerce_float(source: str, key: str, value: Any) -> float:
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _value_error(source, key, "a number", value)
    return float(value)


def _coerce_str_list(source: str, key: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _value_error(source, key, "an array of strings", value)
    return list(value)


def _apply_top_level(target: dict[str, Any], raw: dict[str, Any], source: str) -> None:
    """Validate and copy known top-level keys from ``raw`` into ``target``."""
    for key, allowed in _TOP_LEVEL_ENUMS.items():
        if key in raw:
            target[key] = _coerce_enum(source, key, raw[key], allowed)
    for key in _TOP_LEVEL_BOOLS:
        if key in raw:
            target[key] = _coerce_bool(source, key, raw[key])
    for key in _TOP_LEVEL_STRINGS:
        if key in raw:
            if not isinstance(raw[key], str):
                raise _value_error(source, key, "a string", raw[key])
            target[key] = raw[key]
    # Unknown keys: silently ignored (forward compatibility).


def _merge_provider(
    base: ProviderConfig | None, name: str, raw: Any, source: str
) -> ProviderConfig:
    if not isinstance(raw, dict):
        raise _value_error(source, f"providers.{name}", "[providers] table", raw)
    merged = copy.deepcopy(base) if base is not None else ProviderConfig(name=name)
    merged.name = name

    for key, allowed in _PROVIDER_ENUMS.items():
        if key in raw:
            setattr(merged, key, _coerce_enum(source, f"providers.{name}.{key}", raw[key], allowed))
    for key in _PROVIDER_OPTIONAL_BOOLS:
        if key in raw:
            value = raw[key]
            if value is not None:
                setattr(merged, key, _coerce_bool(source, f"providers.{name}.{key}", value))
            else:
                setattr(merged, key, None)
    for key in _PROVIDER_LISTS:
        if key in raw:
            setattr(merged, key, _coerce_str_list(source, f"providers.{name}.{key}", raw[key]))
    for key in _PROVIDER_FLOATS:
        if key in raw:
            setattr(merged, key, _coerce_float(source, f"providers.{name}.{key}", raw[key]))
    return merged


def _parse_toml(path: str) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: malformed TOML: {exc}") from exc


def load_config(repo_root: str, overrides: dict[str, Any] | None = None) -> SotConfig:
    """Load the effective :class:`SotConfig` for ``repo_root``.

    Merge precedence (lowest to highest): built-in defaults, then
    ``<repo_root>/.sot/config.toml``, then the ``SOT_PROVIDERS_*``
    environment variables, then ``overrides``.

    Raises :class:`ValueError` with the offending file/key when a known key
    holds a value of the wrong type or outside its allowed set.
    """
    scalars: dict[str, Any] = {}
    providers_raw: dict[str, dict[str, Any]] = {}
    raw_sources: dict[str, str] = {}

    config_path = os.path.join(repo_root, CONFIG_RELATIVE_PATH)

    # Layer 2: project-local file (defaults already stand when absent).
    if os.path.exists(config_path):
        document = _parse_toml(config_path)
        _apply_top_level(scalars, document, config_path)
        raw_providers = document.get("providers", {})
        if not isinstance(raw_providers, dict):
            raise _value_error(config_path, "providers", "table of [providers.<name>]", raw_providers)
        providers_raw.update(raw_providers)

    # Layer 3: environment variables.
    env_mode = os.environ.get(ENV_PROVIDERS_MODE)
    if env_mode is not None:
        scalars["providers_mode"] = _coerce_enum(
            f"environment variable {ENV_PROVIDERS_MODE}",
            "providers_mode",
            env_mode,
            _TOP_LEVEL_ENUMS["providers_mode"],
        )
    env_allow = os.environ.get(ENV_PROVIDERS_ALLOW_EXTERNAL)
    if env_allow is not None:
        normalized = env_allow.strip().lower()
        if normalized in _TRUTHY:
            scalars["allow_external"] = True
        elif normalized in _FALSY:
            scalars["allow_external"] = False
        else:
            raise ValueError(
                f"environment variable {ENV_PROVIDERS_ALLOW_EXTERNAL}: expected "
                f"a boolean ({'/'.join(sorted(_TRUTHY))} or {'/'.join(sorted(_FALSY))}), "
                f"got {env_allow!r}"
            )

    # Layer 4: explicit overrides (same shape as the TOML document).
    if overrides:
        _apply_top_level(scalars, overrides, "<overrides>")
        override_providers = overrides.get("providers", {})
        if not isinstance(override_providers, dict):
            raise _value_error("<overrides>", "providers", "dict of provider dicts", override_providers)
        for name, patch in override_providers.items():
            if isinstance(patch, dict):
                providers_raw.setdefault(name, {}).update(patch)
            else:
                providers_raw[name] = patch
            raw_sources[name] = "<overrides>"

    providers: dict[str, ProviderConfig] = {}
    for name, raw in providers_raw.items():
        providers[name] = _merge_provider(
            DEFAULT_PROVIDERS.get(name), name, raw, raw_sources.get(name, config_path)
        )
    # Providers never mentioned anywhere still contribute their defaults.
    for name, default in DEFAULT_PROVIDERS.items():
        if name not in providers:
            providers[name] = copy.deepcopy(default)

    return SotConfig(**scalars, providers=providers)
