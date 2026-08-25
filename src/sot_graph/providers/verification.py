"""sot_graph.providers.verification — P2 source/span verification.

Pure-function verifiers: they re-check a CBM subject's span/token claims
against the *current* source on disk (filesystem reads only, no network,
no subprocess). An evidence assertion may only reach SUPPORTED when the
snapshot is bound+fresh AND the claimed span still matches the live file.

Verdict vocabulary (VerificationOutcome.status):
    VERIFIED        span + unique defining occurrence confirmed on disk
    SPAN_MISMATCH   file exists but the span no longer pins the symbol
    MISSING         file absent (or path rejected as escaping repo root)
    AMBIGUOUS       target not unique inside the claimed span
    NOT_APPLICABLE  nothing to verify (no span, generated/vendor path)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = [
    "VERIFIED",
    "SPAN_MISMATCH",
    "MISSING",
    "AMBIGUOUS",
    "NOT_APPLICABLE",
    "DEFINING_KINDS",
    "VerificationOutcome",
    "verify_subject",
    "verify_edge",
]

#: Outcome statuses.
VERIFIED = "VERIFIED"
SPAN_MISMATCH = "SPAN_MISMATCH"
MISSING = "MISSING"
AMBIGUOUS = "AMBIGUOUS"
NOT_APPLICABLE = "NOT_APPLICABLE"

#: Kinds for which a definition-shaped line is required to count an
#: occurrence as *the* definition of the symbol.
DEFINING_KINDS = frozenset({"function", "method", "class"})

_DEF_PATTERNS: dict[str, re.Pattern[str]] = {
    "function": re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\("),
    "method": re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\("),
    "class": re.compile(r"^\s*class\s+(\w+)\b"),
}

#: Heuristic generated/vendor markers: any path part equal to one of these,
#: or a file name matching *_pb2*, is treated as machine-owned source whose
#: spans are never trusted as human-authored evidence.
_GENERATED_DIR_PARTS = frozenset({"node_modules", ".venv", "venv", "dist", "build"})
_PB2_RE = re.compile(r"_pb2|_pb\d*_grpc")


@dataclass(frozen=True)
class VerificationOutcome:
    """Result of checking one subject/edge claim against current source."""

    status: str
    detail: str = ""
    known_gaps: tuple[str, ...] = field(default_factory=tuple)


def _fld(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from a mapping or attribute-style subject."""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _is_generated(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    if _PB2_RE.search(parts[-1]):
        return True
    return any(part in _GENERATED_DIR_PARTS for part in parts[:-1])


def _safe_resolve(repo_root: str, rel_path: str) -> str | None:
    """Resolve ``rel_path`` under ``repo_root``, rejecting escapes.

    Returns the canonical absolute path when it stays inside the root
    (symlinks resolved), otherwise ``None`` — callers MUST NOT read the
    returned-None target.
    """
    if not rel_path:
        return None
    root_real = os.path.realpath(repo_root)
    joined = (
        rel_path
        if os.path.isabs(rel_path)
        else os.path.join(root_real, rel_path)
    )
    resolved = os.path.realpath(joined)
    try:
        if os.path.commonpath([resolved, root_real]) != root_real:
            return None
    except ValueError:  # different drives on Windows
        return None
    return resolved


def _token_for(qualified_name: Any, path: Any) -> str | None:
    qn = qualified_name or ""
    token = qn.rsplit(".", 1)[-1].strip() if isinstance(qn, str) else ""
    if not token and isinstance(path, str):
        token = os.path.splitext(os.path.basename(path))[0]
    return token or None


def verify_subject(subject: Any, repo_root: str) -> VerificationOutcome:
    """Verify one canonical subject's path/span/token claim on live source.

    ``subject`` is a :class:`~sot_graph.providers.normalization.CanonicalSubject`
    or any mapping/duck-typed object exposing ``path``, ``start_line``,
    ``end_line``, ``kind`` and ``qualified_name``.
    """
    path = _fld(subject, "path")
    start_line = _fld(subject, "start_line")
    end_line = _fld(subject, "end_line")

    if not isinstance(path, str) or not path.strip():
        return VerificationOutcome(NOT_APPLICABLE, "subject carries no source path")

    if _is_generated(path):
        gap = f"generated/vendor path excluded from source verification: {path}"
        return VerificationOutcome(NOT_APPLICABLE, gap, (gap,))

    resolved = _safe_resolve(repo_root, path)
    if resolved is None:
        return VerificationOutcome(
            MISSING, f"path rejected: {path!r} escapes repository root {repo_root!r}"
        )

    if start_line is None:
        return VerificationOutcome(
            NOT_APPLICABLE, f"subject has no span to verify: {path}"
        )

    if not os.path.isfile(resolved):
        return VerificationOutcome(MISSING, f"source file no longer exists: {path}")

    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        return VerificationOutcome(MISSING, f"unreadable source {path}: {exc}")

    try:
        start, end = int(start_line), int(end_line if end_line is not None else start_line)
    except (TypeError, ValueError):
        return VerificationOutcome(SPAN_MISMATCH, f"non-integer span on {path}: "
                                                   f"{start_line!r}-{end_line!r}")
    if start < 1 or end < start or end > len(lines):
        return VerificationOutcome(
            SPAN_MISMATCH,
            f"span {start}-{end} out of bounds for {path} ({len(lines)} lines)",
        )

    kind = str(_fld(subject, "kind") or "").strip().lower()
    token = _token_for(_fld(subject, "qualified_name"), path)
    if token is None:
        return VerificationOutcome(
            NOT_APPLICABLE, f"no symbol token recoverable for {path}"
        )

    span_text = "".join(lines[start - 1:end])
    occurrences = len(re.findall(rf"\b{re.escape(token)}\b", span_text))
    if occurrences == 0:
        return VerificationOutcome(
            SPAN_MISMATCH,
            f"symbol {token!r} not present in claimed span {start}-{end} of {path}",
        )

    if kind in DEFINING_KINDS:
        def_re = _DEF_PATTERNS[kind]
        def_count = sum(
            1
            for line in lines[start - 1:end]
            if def_re.match(line) and def_re.match(line).group(1) == token
        )
        if def_count == 0:
            return VerificationOutcome(
                SPAN_MISMATCH,
                f"span {start}-{end} of {path} mentions {token!r} but does not "
                "define it",
            )
        if def_count > 1:
            return VerificationOutcome(
                AMBIGUOUS,
                f"{def_count} definitions of {token!r} inside span "
                f"{start}-{end} of {path}; target not unique",
            )
        return VerificationOutcome(
            VERIFIED, f"{token!r} uniquely defined at {path}:{start}-{end}"
        )

    # Non-definition kinds: presence alone must be unique to pin a target.
    if occurrences > 1:
        return VerificationOutcome(
            AMBIGUOUS,
            f"{occurrences} occurrences of {token!r} inside span "
            f"{start}-{end} of {path}; target not unique",
        )
    return VerificationOutcome(
        VERIFIED, f"{token!r} occurs exactly once at {path}:{start}-{end}"
    )


def verify_edge(assertion: Any, repo_root: str) -> VerificationOutcome:
    """Verify the source span of the *originating* subject of an edge.

    Edges without a source span are explicitly NOT_APPLICABLE — absence of
    span evidence must never silently pass as verified.
    """
    subject = _fld(assertion, "subject")
    if subject is None:
        return VerificationOutcome(NOT_APPLICABLE, "edge carries no subject")
    if _fld(subject, "start_line") is None:
        return VerificationOutcome(
            NOT_APPLICABLE,
            f"edge source {_fld(subject, 'path') or '<unknown>'} has no span; "
            "nothing to verify on disk",
        )
    return verify_subject(subject, repo_root)
