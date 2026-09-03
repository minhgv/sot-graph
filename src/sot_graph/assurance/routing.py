"""Provider routing tables and --provider spec parsing (P2).

Pure data + parsing, no I/O: the same tables drive CLI flag parsing and MCP
service negotiation, so capability routing cannot drift between surfaces.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

__all__ = [
    "QUERYABLE_PROVIDERS",
    "CAPABILITY_ALIASES",
    "COMMAND_CAPABILITY",
    "parse_provider_spec",
    "supports_capability",
]

#: Providers this codebase can actually query through an adapter (P1: CBM & SCIP).
QUERYABLE_PROVIDERS = frozenset({"codebase-memory", "scip"})
#: METHOD_CAPABILITIES speaks in method-ish capability strings while provider
#: config advertises guide §11.3 names; alias so negotiation stays table-driven.
CAPABILITY_ALIASES: Dict[str, Tuple[str, ...]] = {
    "trace": ("trace", "callgraph"),
    "callgraph": ("callgraph", "trace"),
    "impact": ("impact",),
    "search_symbols": ("symbols", "search_symbols"),
    "symbols": ("symbols", "search_symbols"),
    "usages": ("usages", "references", "callgraph", "trace"),
    "references": ("references", "usages", "callgraph", "trace"),
}

#: Command kind -> guide §11.3 capability used for registry ranking.
COMMAND_CAPABILITY: Dict[str, str] = {
    "explore": "callgraph",
    "usages": "usages",
    "diff-impact": "impact",
    "architecture": "architecture",
}
def parse_provider_spec(value: Optional[str]) -> Tuple[str, Optional[str]]:
    """Validate a provider spec string; returns ``(mode, name)``.

    Modes: builtin (default), auto, all, prefer:<name>, require:<name>.
    """
    if value is None or value == "builtin":
        return "builtin", None
    if value in ("auto", "all"):
        return value, None
    if ":" in value:
        mode, _, name = value.partition(":")
        if mode in ("prefer", "require") and name.strip():
            return mode, name.strip()
    raise ValueError(
        f"invalid provider spec {value!r}; expected "
        "builtin | auto | prefer:<name> | require:<name> | all"
    )


def effective_provider_spec(
    explicit: Optional[str], providers_mode: str, allow_external: bool
) -> Optional[str]:
    """Resolve the spec a query should actually use (P2.c').

    Precedence: an explicit ``--provider`` (or tool argument) always wins.
    Without one, ``providers_mode = "auto"`` in config takes effect — no need
    to repeat the flag per command — but only while external providers are
    allowed. Otherwise builtin.
    """
    if explicit is not None:
        return explicit
    if providers_mode == "auto" and allow_external:
        return "auto"
    return None


def supports_capability(provider: Any, method: str) -> bool:
    """supports_method negotiation plus §11.3 capability-name aliases."""
    from sot_graph.providers.base import supports_method

    if supports_method(provider, method):
        return True
    caps = tuple(getattr(provider, "capabilities", ()) or ())
    if method in caps:
        return True
    return any(alias in caps for alias in CAPABILITY_ALIASES.get(method, ()))
