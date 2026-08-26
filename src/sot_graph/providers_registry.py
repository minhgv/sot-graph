"""sot_graph.providers_registry — Read-only provider detection & capability resolution.

Detects which evidence providers (gitnexus, codebase-memory, scip artifacts,
sot-builtin) are installed and healthy on this machine, ranks the available
ones per capability (guide §11.3), and produces a doctor report with
recommended next actions.

Strictly read-only by construction:
- only ``shutil.which`` executable lookup,
- a bounded ``<command> --version`` probe via :func:`sot_graph.proc.run_command`,
- filesystem existence checks for SCIP artifacts.
No package installation, no indexing, no daemon, no network.
"""
from __future__ import annotations

import importlib.metadata
import os
import shutil
import time
from dataclasses import asdict, dataclass

from sot_graph.config import ProviderConfig, SotConfig, load_config
from sot_graph.proc import run_command
from sot_graph.providers.codebase_memory import CodebaseMemoryProvider


#: Wall-clock budget for one ``<command> --version`` probe.
VERSION_PROBE_TIMEOUT_SECONDS = 10.0

#: Artifact locations (relative to ``repo_root``) that count as an installed
#: SCIP provider. SCIP is not an executable — presence of a fresh index file
#: is the installation signal.
SCIP_ARTIFACTS = ("index.scip", os.path.join(".scip", "index.scip"))

#: Canonical ranking of providers per capability (guide §11.3). Providers not
#: listed here but advertising the capability are appended after the table in
#: config order; sot-builtin is always the final fallback where listed.
CAPABILITY_PRIORITY: dict[str, tuple[str, ...]] = {
    "source-verification": ("sot-builtin",),
    "symbols": ("scip", "codebase-memory", "gitnexus", "sot-builtin"),
    "callgraph": ("scip", "codebase-memory", "gitnexus", "sot-builtin"),
    "impact": ("gitnexus", "codebase-memory", "sot-builtin"),
    "pdg": ("gitnexus",),
    "taint": ("gitnexus",),
    "broad-language-discovery": ("codebase-memory", "gitnexus", "sot-builtin"),
}

#: sot-builtin measured per language x relation F1 (oracle P0 baseline,
#: benchmarks/oracle/builtin-baseline.json — regenerated after the P3.3b
#: recall work: Go 100, TS 99.5, Rust 98.5 overall). The builtin does NOT
#: advertise a blanket callgraph capability: it declares where it is
#: strong and names the weak cells (rust/java implements extraction) so
#: routing and reports stay honest.
BUILTIN_LANGUAGE_SCORECARD: dict[str, dict[str, float]] = {
    "python": {"calls": 0.997, "extends": 1.0},
    "java": {"calls": 0.996, "implements": 0.0},
    "typescript": {"calls": 0.995, "implements": 1.0},
    "go": {"calls": 1.0},
    "rust": {"calls": 0.988, "implements": 0.0},
}



@dataclass
class ProviderStatus:
    """Outcome of probing one configured provider."""

    name: str
    mode: str  # integration mode: cli / mcp / import / embedded
    installed: bool
    version: str | None
    healthy: bool
    capabilities: list[str]
    detail: str  # why missing/unhealthy, or short ok note
    #: which engine produced this status: "manual" (<cmd> --version here) or
    #: "adapter" (the provider's own EvidenceProvider.probe). Additive field.
    probe_engine: str = "manual"
    #: measured per language x relation F1 (P3.3); None for non-extractors.
    language_capability: dict[str, dict[str, float]] | None = None


def _package_version() -> str:
    try:
        return importlib.metadata.version("sot-graph")
    except Exception:  # pragma: no cover - only when package metadata is stripped
        return "0.3.0"


def _external_allowed(name: str, cfg: SotConfig) -> bool:
    """External providers are gated behind ``allow_external``; builtin and
    local SCIP artifacts stay usable without it."""
    if cfg.allow_external:
        return True
    return name in ("sot-builtin", "scip")


def _join_detail(parts: list[str]) -> str:
    return "; ".join(p for p in parts if p)


def _probe_scip(pcfg: ProviderConfig, repo_root: str) -> ProviderStatus:
    for rel in SCIP_ARTIFACTS:
        path = os.path.join(repo_root, rel)
        if os.path.isfile(path):
            mtime = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(path)))
            detail = f"artifact {rel} present (mtime {mtime})"
            return ProviderStatus(
                name=pcfg.name,
                mode=pcfg.integration,
                installed=True,
                version=None,
                healthy=True,
                capabilities=list(pcfg.capabilities),
                detail=detail,
            )
    return ProviderStatus(
        name=pcfg.name,
        mode=pcfg.integration,
        installed=False,
        version=None,
        healthy=False,
        capabilities=list(pcfg.capabilities),
        detail=f"no SCIP artifact found (looked for: {', '.join(SCIP_ARTIFACTS)})",
    )


#: Providers whose probing is delegated to their own adapter instead of the
#: generic manual ``<cmd> --version`` probe. The adapter applies the provider's
#: anchored version contract and redaction rules; still strictly read-only.
ADAPTER_PROBED_PROVIDERS = frozenset({"codebase-memory"})


def _probe_via_adapter(pcfg: ProviderConfig, repo_root: str) -> ProviderStatus:
    command = list(pcfg.command or [pcfg.name])
    provider = CodebaseMemoryProvider(
        command=command,
        query_timeout_seconds=min(pcfg.timeout_seconds, VERSION_PROBE_TIMEOUT_SECONDS)
        or VERSION_PROBE_TIMEOUT_SECONDS,
    )
    st = provider.probe(repo_root)
    if st.installed and st.healthy:
        exe = shutil.which(command[0]) or command[0]
        detail = f"executable at {exe}"
    else:
        detail = st.detail or "unhealthy"
    return ProviderStatus(
        name=pcfg.name,
        mode=pcfg.integration,
        installed=st.installed,
        version=st.version,
        healthy=st.healthy,
        capabilities=list(pcfg.capabilities),
        detail=detail,
        probe_engine="adapter",
    )


def _probe_executable(pcfg: ProviderConfig, repo_root: str) -> ProviderStatus:
    command = list(pcfg.command or [pcfg.name])
    exe = shutil.which(command[0])
    if exe is None:
        return ProviderStatus(
            name=pcfg.name,
            mode=pcfg.integration,
            installed=False,
            version=None,
            healthy=False,
            capabilities=list(pcfg.capabilities),
            detail=f"executable '{command[0]}' not found in PATH",
        )

    result = run_command(
        [command[0], "--version"],
        cwd=repo_root,
        timeout_seconds=VERSION_PROBE_TIMEOUT_SECONDS,
    )
    if result.error is not None:
        detail = f"'{command[0]} --version' failed to run: {result.error}"
    elif result.timed_out:
        detail = f"'{command[0]} --version' timed out after {VERSION_PROBE_TIMEOUT_SECONDS:g}s"
    elif result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()
        snippet = tail[-1][:200] if tail else "(no output)"
        detail = f"'{command[0]} --version' exited with code {result.returncode}: {snippet}"
    else:
        first_line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        return ProviderStatus(
            name=pcfg.name,
            mode=pcfg.integration,
            installed=True,
            version=first_line or None,
            healthy=True,
            capabilities=list(pcfg.capabilities),
            detail=f"executable at {exe}",
        )
    return ProviderStatus(
        name=pcfg.name,
        mode=pcfg.integration,
        installed=True,
        version=None,
        healthy=False,
        capabilities=list(pcfg.capabilities),
        detail=detail,
    )


def _status_for(pcfg: ProviderConfig, repo_root: str) -> ProviderStatus:
    if pcfg.name == "sot-builtin":
        weak = sorted(
            f"{lang}.{rel}"
            for lang, rels in BUILTIN_LANGUAGE_SCORECARD.items()
            for rel, f1 in rels.items() if f1 < 0.5
        )
        status = ProviderStatus(
            name="sot-builtin",
            mode=pcfg.integration,
            installed=True,
            version=_package_version(),
            healthy=True,
            capabilities=list(pcfg.capabilities),
            language_capability={
                lang: dict(rels) for lang, rels in BUILTIN_LANGUAGE_SCORECARD.items()
            },
            detail=(
                "built-in verifier; measured F1 per language x relation "
                "(oracle P0)" + (f"; weak: {', '.join(weak)}" if weak else "")
            ),
        )
    elif pcfg.name == "scip":
        status = _probe_scip(pcfg, repo_root)
    elif pcfg.integration == "cli" and pcfg.name in ADAPTER_PROBED_PROVIDERS:
        status = _probe_via_adapter(pcfg, repo_root)
    else:
        status = _probe_executable(pcfg, repo_root)
    if pcfg.enabled is False:
        status.detail = _join_detail([status.detail, "disabled via config"])
    return status


def _detect_all(repo_root: str, cfg: SotConfig) -> dict[str, ProviderStatus]:
    return {name: _status_for(pcfg, repo_root) for name, pcfg in cfg.providers.items()}


def detect_providers(repo_root: str, config: SotConfig | None = None) -> list[ProviderStatus]:
    """Probe every configured provider under ``repo_root``.

    When ``allow_external`` is false the result is restricted to sot-builtin
    and scip artifacts. Read-only: PATH lookups, ``--version`` probes, artifact
    existence checks only.
    """
    cfg = config or load_config(repo_root)
    statuses = _detect_all(repo_root, cfg)
    return [st for name, st in statuses.items() if _external_allowed(name, cfg)]


def _rank_names(capability: str, cfg: SotConfig) -> list[str]:
    order = list(cfg.providers.keys())
    capable = [n for n in order if capability in cfg.providers[n].capabilities]
    table = CAPABILITY_PRIORITY.get(capability)
    if capability == "repo-map":
        # repo-map is not an advertised capability: rank every external
        # provider by advertised coverage, highest first; builtin last-resort.
        ranked = sorted(
            (n for n in order if n != "sot-builtin"),
            key=lambda n: (-len(cfg.providers[n].capabilities), order.index(n)),
        )
        if "sot-builtin" in order:
            ranked.append("sot-builtin")
        return ranked
    if table is None:
        # Unknown capability: capable providers in config order, builtin last.
        ranked = [n for n in capable if n != "sot-builtin"]
        if "sot-builtin" in order:
            ranked.append("sot-builtin")
        return ranked
    head = [n for n in table if n in order]
    tail = [n for n in capable if n not in head]
    return head + tail


def resolve_capability(
    repo_root: str, capability: str, config: SotConfig | None = None
) -> list[ProviderStatus]:
    """Rank available providers for ``capability``, best candidate first.

    Filters out uninstalled, unhealthy, disabled, and (when
    ``allow_external`` is false) external providers before applying the
    guide §11.3 priority table.
    """
    cfg = config or load_config(repo_root)
    statuses = _detect_all(repo_root, cfg)
    available: dict[str, ProviderStatus] = {}
    for name, st in statuses.items():
        pcfg = cfg.providers[name]
        if pcfg.enabled is False:
            continue
        if not (st.installed and st.healthy):
            continue
        if not _external_allowed(name, cfg):
            continue
        available[name] = st
    return [available[n] for n in _rank_names(capability, cfg) if n in available]


def providers_doctor(repo_root: str, config: SotConfig | None = None) -> dict:
    """Aggregate provider health with actionable recommendations.

    ``ok`` is true when every explicitly enabled (``enabled = true``) provider
    is installed and healthy; auto-detect providers may be missing without
    failing the check.
    """
    cfg = config or load_config(repo_root)
    statuses = _detect_all(repo_root, cfg)
    entries: list[dict] = []
    next_actions: list[str] = []
    ok = True
    for name, st in statuses.items():
        pcfg = cfg.providers[name]
        entry = asdict(st)
        entry["enabled"] = pcfg.enabled
        entry["usable"] = bool(
            st.installed and st.healthy and pcfg.enabled is not False and _external_allowed(name, cfg)
        )
        entries.append(entry)

        required_broken = pcfg.enabled is True and not (st.installed and st.healthy)
        if required_broken:
            ok = False
            state = f"unhealthy ({st.detail})" if st.installed else f"missing ({st.detail})"
            next_actions.append(
                f"{name}: required by config but {state} — fix the installation "
                f"or set enabled=false in .sot/config.toml"
            )
        elif pcfg.enabled is False:
            next_actions.append(f"{name}: disabled via config — re-enable it in .sot/config.toml to use its capabilities")
        elif not st.installed and name != "sot-builtin":
            caps = ", ".join(st.capabilities) or "(none)"
            next_actions.append(
                f"{name}: optional, not installed ({st.detail}) — install it to unlock: {caps}"
            )
        elif st.installed and st.healthy and not _external_allowed(name, cfg):
            next_actions.append(
                f"{name}: detected and healthy but ignored because allow_external=false — "
                f"set allow_external=true in .sot/config.toml to use it"
            )

    return {
        "root": repo_root,
        "providers_mode": cfg.providers_mode,
        "allow_external": cfg.allow_external,
        "conflict_policy": cfg.conflict_policy,
        "verification_provider": cfg.verification_provider,
        "ok": ok,
        "providers": entries,
        "next_actions": next_actions,
    }
