"""sot_graph.assurance.identity — canonical symbol identity (P4.1, guide §7).

A symbol's identity is the FULL tuple::

    (repo, normalized path, language, kind, qualified name, span,
     provider symbol id)

— never its short name. Two ``run()`` functions in different files are
two identities even though they share a name; a moved file is a
different identity (different path); a provider symbol id (SCIP
scheme string, CBM node id) keys the SAME code entity only inside one
provider's namespace and never overrides the filesystem-anchored
fields.

Rules:
- Unknown values are ``None`` / ``"unknown"`` — never fabricated.
- Paths are normalized to POSIX repo-relative form (``./`` stripped).
- Spans are line/column precise when the source has columns, line-only
  otherwise; a ``None`` span never equals a known span.
- :func:`dedup_by_identity` is the ONLY sanctioned dedup: same key
  merges (provenance lists union), different keys stay distinct —
  short-name collisions must survive as separate identities.
"""

from __future__ import annotations

import hashlib
import posixpath
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

__all__ = [
    "Span",
    "SymbolIdentity",
    "identity_key",
    "identity_hash",
    "normalize_repo_path",
    "from_subject",
    "from_graph_row",
    "from_provider_symbol",
    "dedup_by_identity",
]

#: Provider names whose symbol ids are meaningful on their own. Other
#: providers' ids are still stored verbatim — the tuple keeps them, it
#: just never trusts them across providers.
_PROVIDER_ID_NAMESPACES = ("scip", "codebase-memory", "sot-builtin")


@dataclass(frozen=True)
class Span:
    """Line/column-precise source span (1-based, end inclusive)."""

    start_line: Optional[int]
    end_line: Optional[int]
    start_column: Optional[int] = None
    end_column: Optional[int] = None

    def __bool__(self) -> bool:
        return self.start_line is not None


def normalize_repo_path(path: str | None) -> str | None:
    """Normalize a path to POSIX repo-relative form.

    ``None``/empty stays ``None``. Absolute-ish and ``./`` prefixes are
    collapsed without resolving symlinks or case (caller's repo, caller's
    rules) — identity normalization must be stable, not clever.
    """
    if not path:
        return None
    norm = path.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    norm = posixpath.normpath(norm)
    return norm or None


@dataclass(frozen=True)
class SymbolIdentity:
    """Canonical identity tuple for one code symbol."""

    repo_id: str
    path: Optional[str]
    language: str
    kind: str
    qualified_name: str
    span: Optional[Span]
    provider_symbol_id: Optional[str] = None

    @property
    def short_name(self) -> str:
        return self.qualified_name.rsplit(".", 1)[-1].rsplit("::", 1)[-1]

    def key(self) -> tuple:
        return identity_key(self)


def identity_key(identity: SymbolIdentity) -> tuple:
    """Hashable identity tuple — the dedup/join key for symbols."""
    span = identity.span
    return (
        identity.repo_id,
        identity.path,
        identity.language,
        identity.kind,
        identity.qualified_name,
        (
            span.start_line, span.end_line, span.start_column, span.end_column
        ) if span else None,
        identity.provider_symbol_id,
    )


def identity_hash(identity: SymbolIdentity) -> str:
    """Stable short digest of the identity tuple (for receipts/logging)."""
    payload = "\x1f".join(
        "" if part is None else str(part) for part in identity_key(identity)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def from_subject(subject: Any) -> SymbolIdentity:
    """Adapt a contract ``Subject``/``CanonicalSubject`` to SymbolIdentity."""
    path = getattr(subject, "path", None)
    language = getattr(subject, "language", None) or "unknown"
    repo_id = getattr(subject, "repo_id", None) or ""
    sc = getattr(subject, "start_column", None)
    ec = getattr(subject, "end_column", None)
    start_line = getattr(subject, "start_line", None)
    end_line = getattr(subject, "end_line", None)
    return SymbolIdentity(
        repo_id=repo_id,
        path=normalize_repo_path(path),
        language=str(language),
        kind=str(getattr(subject, "kind", "unknown") or "unknown"),
        qualified_name=str(getattr(subject, "qualified_name", "") or ""),
        span=Span(start_line, end_line, sc, ec) if start_line is not None else None,
        provider_symbol_id=None,
    )


def from_graph_row(row: Mapping[str, Any], *, repo_id: str = "") -> SymbolIdentity:
    """Adapt a ``graph_nodes`` row (sqlite3.Row/dict) to SymbolIdentity."""
    start_line = row["line_start"] if "line_start" in row.keys() else None
    end_line = row["line_end"] if "line_end" in row.keys() else None
    sc = row["col_start"] if "col_start" in row.keys() else None
    ec = row["col_end"] if "col_end" in row.keys() else None
    symbol = row["symbol"] if "symbol" in row.keys() else None
    return SymbolIdentity(
        repo_id=repo_id,
        path=normalize_repo_path(row["path"] if "path" in row.keys() else None),
        language=_language_of(row["path"] if "path" in row.keys() else ""),
        kind=str(row["kind"] if "kind" in row.keys() else "unknown"),
        qualified_name=str(symbol or (row["fqn"] if "fqn" in row.keys() else "") or ""),
        span=Span(start_line, end_line, sc, ec) if start_line is not None else None,
        provider_symbol_id=None,
    )


def from_provider_symbol(
    *,
    repo_id: str,
    path: str | None,
    language: str,
    kind: str,
    qualified_name: str,
    span: Span | None,
    provider: str,
    provider_symbol_id: str | None,
) -> SymbolIdentity:
    """Build an identity for a provider-reported symbol.

    The provider symbol id is namespaced (``provider:id``) so ids from
    different providers never accidentally join.
    """
    ns_id = (
        f"{provider}:{provider_symbol_id}"
        if provider_symbol_id and provider in _PROVIDER_ID_NAMESPACES
        else provider_symbol_id or None
    )
    return SymbolIdentity(
        repo_id=repo_id,
        path=normalize_repo_path(path),
        language=language or "unknown",
        kind=kind or "unknown",
        qualified_name=qualified_name or "",
        span=span,
        provider_symbol_id=ns_id,
    )


def dedup_by_identity(
    items: Iterable[SymbolIdentity],
) -> list[SymbolIdentity]:
    """Merge identical identity keys; NEVER collapse by short name.

    Order-preserving: first occurrence wins, later duplicates are
    dropped (their provenance belongs to the caller's ledger, not the
    identity). Two same-named symbols in different files stay two rows.
    """
    seen: set[tuple] = set()
    out: list[SymbolIdentity] = []
    for item in items:
        key = identity_key(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


_LANGUAGE_BY_SUFFIX: tuple[tuple[str, str], ...] = (
    (".py", "python"), (".ts", "typescript"), (".tsx", "tsx"),
    (".js", "javascript"), (".jsx", "jsx"), (".go", "go"),
    (".rs", "rust"), (".java", "java"), (".kt", "kotlin"),
    (".swift", "swift"), (".rb", "ruby"), (".php", "php"),
    (".cs", "c_sharp"), (".c", "c"), (".h", "c"), (".cpp", "cpp"),
)


def _language_of(path: str) -> str:
    low = path.lower()
    for suffix, language in _LANGUAGE_BY_SUFFIX:
        if low.endswith(suffix):
            return language
    return "unknown"
