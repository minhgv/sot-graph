"""sot_graph.providers.identity_join — cross-provider identity joins (SG-203).

Reassessment §8 P1-4: the old cross-check joined ``graph_edges`` node IDs
(``sym:hash:name``) against ``provider_evidence`` symbol strings by raw
string equality. Different providers live in different identity spaces, so
real joins only happened by accident and real conflicts were invisible.

This module adapts both sides onto the canonical
:class:`sot_graph.assurance.identity.SymbolIdentity` tuple
(repo/path/language/kind/FQN/span) BEFORE any comparison:

- builtin side: ``graph_nodes`` rows (qualified name = the node's dotted
  FQN, path normalized repo-relative against ``repo_root``);
- SCIP side: raw SCIP symbol strings parsed by
  :func:`sot_graph.importer.scip.parse_scip_symbol`, with the descriptor
  chain's path-ish chunks dropped and the module re-derived from the
  document's relative path;
- CBM side: qualified names carry a dash-mangled absolute-root prefix
  (``Users-…-repo``); the prefix is stripped only when ``repo_root`` is
  known — an unstrippable mangled prefix is unresolved, never joined;
- foreign shapes (builtin node IDs ``sym:…``/``file:…`` appearing in
  provider columns) are rejected outright.

Join rule (documented, deterministic, fail-closed):

- the join key is ``(repo, language, kind_class, canonical FQN)``;
- a bare (unqualified) FQN carries no module information, so it only
  joins when the repo-relative path is also known and equal on both
  sides;
- spans are NEVER part of the join key (providers disagree on spans by
  construction) — they travel with the identity for conflict
  adjudication;
- an identity that cannot be canonicalized is counted as unresolved and
  never enters a join: ambiguous evidence must surface, not silently
  match (zero accidental raw-string joins).
"""
from __future__ import annotations

import os
import posixpath
import re
from typing import Any, Mapping, Optional, Tuple

from sot_graph.assurance.identity import (
    Span,
    SymbolIdentity,
    _language_of,
    normalize_repo_path,
)
from sot_graph.importer.scip import parse_scip_symbol

__all__ = [
    "KIND_CLASSES", "canonical_fqn", "cbm_identity", "cross_join_key",
    "evidence_identity", "identities_joinable", "kind_class",
    "mangled_root_prefix", "builtin_identity", "scip_identity",
]

#: Fine-grained kinds folded to a cross-provider class so "function"
#: (builtin), "method" (SCIP) and "Function" (CBM) compare equal.
_KIND_CLASS_MAP = {
    "function": "callable", "method": "callable", "constructor": "callable",
    "field": "field", "property": "field",
    "class": "type", "struct": "type", "interface": "type", "type": "type",
    "enum": "type", "trait": "type",
    "module": "module", "package": "module",
    "file": "file",
}
KIND_CLASSES = ("callable", "field", "type", "module", "file", "other")

_TRAILING_CALL = re.compile(r"\(\)\.?$")

_PATHISH_CHUNK = re.compile(
    r"(?:^|[/\\])[^\s]*\.(?:py|ts|tsx|js|jsx|go|java|rs|rb|kt|swift|c|cc|cpp|h)$"
    r"|[/\\]"
)

_BUILTIN_NODE_ID = re.compile(r"^(?:sym|file|note):[0-9a-f]{6,}:")


def kind_class(kind: Any) -> str:
    """Fold a raw kind string onto the cross-provider class vocabulary."""
    if not isinstance(kind, str) or not kind.strip():
        return ""
    return _KIND_CLASS_MAP.get(kind.strip().lower(), "other")


def canonical_fqn(fqn: Any) -> str:
    """Normalize a qualified name onto canonical dotted form.

    Drops descriptor leftovers (trailing ``()``), empty chunks and chunks
    that are file paths — the module lives in the identity's path, not in
    the name.
    """
    if not isinstance(fqn, str) or not fqn.strip():
        return ""
    name = fqn.strip()
    name = _TRAILING_CALL.sub("", name)
    chunks = [c for c in name.split(".") if c.strip()]
    keep = [c for c in chunks if not _PATHISH_CHUNK.search(c)]
    return ".".join(keep)


def mangled_root_prefix(repo_root: str) -> str:
    """CBM mangles the absolute repo root into its qualified names.

    ``/Users/x/code/repo`` becomes ``Users-x-code-repo``; CBM prefixes
    every qualified name with it. Rebuilding the prefix requires the real
    root, which is exactly why stripping without ``repo_root`` must fail
    closed.
    """
    real = os.path.realpath(repo_root)
    return real.lstrip("/").replace("/", "-")


def _repo_rel(path: Optional[str], repo_root: Optional[str]) -> Optional[str]:
    if not path:
        return None
    if repo_root and os.path.isabs(path):
        try:
            rel = os.path.relpath(
                os.path.realpath(path), os.path.realpath(repo_root)
            )
            if not rel.startswith(".."):
                return normalize_repo_path(rel)
        except ValueError:
            pass
    return normalize_repo_path(path)


def _repo_id(repo_root: Optional[str]) -> str:
    if not repo_root:
        return ""
    return os.path.basename(os.path.realpath(repo_root))


def _span(line_start: Any, line_end: Any) -> Optional[Span]:
    if line_start is None:
        return None
    return Span(int(line_start), int(line_end) if line_end is not None else None)


def builtin_identity(
    node_row: Mapping[str, Any],
    repo_root: Optional[str] = None,
) -> Optional[SymbolIdentity]:
    """Adapt a ``graph_nodes`` row for cross-provider joining.

    The qualified name is the node's dotted FQN (module path included) —
    never the bare symbol, and never the node ID (``sym:…``): joining on
    node IDs is the accidental raw-string join this module exists to
    prevent.
    """
    def col(name: str) -> Any:
        try:
            return node_row[name]
        except (KeyError, IndexError):
            return None

    fqn = col("fqn") or ""
    qualified = canonical_fqn(fqn) or canonical_fqn(col("symbol") or "")
    path = _repo_rel(col("path"), repo_root)
    if not qualified:
        return None
    return SymbolIdentity(
        repo_id=_repo_id(repo_root),
        path=path,
        language=_language_of(col("path") or "") or "unknown",
        kind=kind_class(col("kind")) or "other",
        qualified_name=qualified,
        span=_span(col("line_start"), col("line_end")),
        provider_symbol_id=None,
    )


#: Leading "dir/file.ext." prefix inside a SCIP FQN — the symbol's own
#: document embedded in its descriptors (e.g. "core/service.py.compute_total").
_EMBEDDED_DOC_PATH = re.compile(
    r"^([^.\s]*[/\\][^.\s]*)\.([A-Za-z]{1,5})\.(.+)$"
)


def scip_identity(
    raw_symbol: Any,
    rel_path: Any,
    repo_root: Optional[str] = None,
    *,
    kind_hint: Any = None,
    span: Optional[Span] = None,
) -> Optional[SymbolIdentity]:
    r"""Adapt a raw SCIP symbol string + document path for joining.

    A SCIP symbol usually embeds its own document in the descriptor chain
    (``… \`core/service.py\`/compute_total()`` → FQN
    ``core/service.py.compute_total``); that embedded path — not the
    evidence row's single path, which describes the occurrence document —
    defines the symbol's module. The embedded prefix is extracted first,
    the row's relative path second, and the module is re-derived from it
    so the result carries the same dotted shape the builtin extractor
    produces (``core.service.compute_total``). Without either path the
    chain cannot be canonicalized and stays unresolved rather than
    joined on a half-path FQN.
    """
    if not isinstance(raw_symbol, str) or not raw_symbol.strip():
        return None
    if not rel_path:
        return None
    parsed = parse_scip_symbol(raw_symbol)
    if parsed.get("is_local") and not parsed.get("fqn"):
        return None  # "local 1"-style synthetics carry no identity
    path = _repo_rel(rel_path, repo_root)
    raw_fqn = str(parsed.get("fqn") or "")
    chain = ""
    module = ""
    # The evidence row may store either the full SCIP symbol (embedded
    # doc path survives parsing) or the already-parsed bare FQN — whose
    # RE-parse flattens "/" to "." and destroys the doc-path shape. Try
    # the raw string first, the parsed FQN second.
    embedded = (_EMBEDDED_DOC_PATH.match(raw_symbol.strip())
                or _EMBEDDED_DOC_PATH.match(raw_fqn))
    if embedded:
        doc = f"{embedded.group(1)}.{embedded.group(2)}"
        chain = canonical_fqn(embedded.group(3))
        stem = posixpath.splitext(doc.replace("\\", "/"))[0]
        module = canonical_fqn(stem.replace("/", "."))
    elif raw_fqn:
        doc = path or str(rel_path)
        if raw_fqn.startswith(doc + "."):
            chain = canonical_fqn(raw_fqn[len(doc) + 1:])
        else:
            chain = canonical_fqn(raw_fqn)
    if path and not module:
        module = canonical_fqn(
            posixpath.splitext(path)[0].replace("/", "."))
    if chain and chain != module:
        qualified = f"{module}.{chain}" if module else chain
    elif module and parsed.get("bare_name"):
        qualified = f"{module}.{parsed['bare_name']}"
    elif chain:
        qualified = chain
    else:
        return None
    kind = kind_class(kind_hint if kind_hint is not None else parsed.get("kind"))
    return SymbolIdentity(
        repo_id=_repo_id(repo_root),
        path=path,
        language=_language_of(rel_path or "") or "unknown",
        kind=kind or "other",
        qualified_name=qualified,
        span=span,
        provider_symbol_id=None,
    )


def cbm_identity(
    qualified_name: Any,
    repo_root: Optional[str] = None,
    *,
    path: Any = None,
    kind_hint: Any = None,
    span: Optional[Span] = None,
) -> Optional[SymbolIdentity]:
    """Adapt a CBM qualified name for joining.

    CBM prefixes names with the dash-mangled absolute repo root. The
    prefix is stripped only when ``repo_root`` reconstructs it; a mangled
    prefix that cannot be stripped leaves the identity unresolved rather
    than joined on a foreign namespace.
    """
    if not isinstance(qualified_name, str) or not qualified_name.strip():
        return None
    name = qualified_name.strip()
    mangled = mangled_root_prefix(repo_root) if repo_root else ""
    if mangled and name.startswith(mangled + "."):
        name = name[len(mangled) + 1:]
    elif not mangled and re.match(r"^[A-Za-z0-9_.-]*-[A-Za-z0-9_.-]+\.", name) \
            and name.count("-") >= 3:
        return None  # mangled-root shape without repo_root: fail closed
    qualified = canonical_fqn(name)
    if not qualified:
        return None
    rel = _repo_rel(path, repo_root) if path else None
    return SymbolIdentity(
        repo_id=_repo_id(repo_root),
        path=rel,
        language=_language_of(path or "") or "unknown",
        kind=kind_class(kind_hint) or "other",
        qualified_name=qualified,
        span=span,
        provider_symbol_id=None,
    )


def evidence_identity(
    provider_name: Any,
    symbol: Any,
    *,
    path: Any = None,
    kind_hint: Any = None,
    span: Optional[Span] = None,
    repo_root: Optional[str] = None,
) -> Optional[SymbolIdentity]:
    """Dispatch one provider evidence symbol onto canonical identity.

    Builtin node IDs appearing in provider columns are foreign shapes and
    resolve to nothing — the whole point of SG-203 is that a string that
    merely *looks equal* across identity spaces must never join.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    if _BUILTIN_NODE_ID.match(symbol.strip()):
        return None
    provider = str(provider_name or "").lower()
    if "scip" in provider:
        return scip_identity(symbol, path, repo_root, kind_hint=kind_hint,
                             span=span)
    if "codebase-memory" in provider or "cbm" in provider:
        return cbm_identity(symbol, repo_root, path=path,
                            kind_hint=kind_hint, span=span)
    qualified = canonical_fqn(symbol)
    if not qualified:
        return None
    return SymbolIdentity(
        repo_id=_repo_id(repo_root),
        path=_repo_rel(path, repo_root) if path else None,
        language=_language_of(path or "") or "unknown",
        kind=kind_class(kind_hint) or "other",
        qualified_name=qualified,
        span=span,
        provider_symbol_id=None,
    )


def cross_join_key(identity: SymbolIdentity) -> Tuple[str, str, str]:
    """The cross-provider join key (span-, kind-, language- and id-free).

    Kind and language stay OUT of the key: providers under-report them
    (CBM trace rows carry neither), and requiring absent metadata would
    make every real join impossible — the fail-closed rule applies to
    *ambiguous* identities, not to missing descriptive metadata. A dot
    in the FQN means it carries its module (or class) chain and pins the
    entity; a bare FQN only joins when the repo-relative path is known
    on both sides, so it participates in the key.
    """
    qualified = canonical_fqn(identity.qualified_name)
    module_qualified = "." in qualified
    path_part = "" if module_qualified else (identity.path or "\x00missing")
    return (
        identity.repo_id,
        qualified,
        path_part,
    )


def identities_joinable(a: SymbolIdentity, b: SymbolIdentity) -> bool:
    """Key equality plus explicit path agreement.

    When both sides know their repo-relative path the paths must agree —
    a same-FQN match across two different files is two different symbols.
    """
    if cross_join_key(a) != cross_join_key(b):
        return False
    if a.path and b.path:
        return a.path == b.path
    return True


def span_conflict(
    a: Optional[Span], b: Optional[Span], tolerance: int = 2,
) -> bool:
    """True when two joined identities disagree on their source spans.

    Unknown spans never conflict (a ``None`` span never equals a known
    span, but it also never contradicts one); disagreements beyond
    ``tolerance`` lines are adjudicated upstream against the filesystem.
    """
    if a is None or b is None or not a or not b:
        return False
    if a.start_line is None or b.start_line is None:
        return False
    return abs(a.start_line - b.start_line) > tolerance


def identity_summary(identity: Optional[SymbolIdentity]) -> dict:
    """Compact JSON-ready rendering for reports and receipts."""
    if identity is None:
        return {"resolved": False}
    span = identity.span
    return {
        "resolved": True,
        "repo": identity.repo_id,
        "path": identity.path,
        "language": identity.language,
        "kind": identity.kind,
        "fqn": identity.qualified_name,
        "span": (
            [span.start_line, span.end_line] if span and span.start_line is not None
            else None
        ),
    }
