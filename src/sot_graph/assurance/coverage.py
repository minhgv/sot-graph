"""sot_graph.assurance.coverage — coverage model + completeness engine (P5).

Coverage is a MEASURED property of the index, never a count of query
results:

- :data:`CoverageState` — indexed/parsed/partial/skipped/excluded/
  stale/unknown per file, derived from the file journal's persisted
  parser outcome plus live disk state.
- :data:`GAP_TAXONOMY` — the declared reason families that keep a
  completeness claim honest (dynamic dispatch, reflection, DI, macros,
  fn pointers, generated code, cross-repo edges). Gaps are REPORTED,
  never cut through.
- :func:`repo_coverage` — build a :class:`CoverageReport` for the repo
  or an explicit path set; a storage/API error degrades the report to
  ``basis="unknown"`` instead of fabricating numbers.
- :func:`completeness` — combine coverage + capability into a single
  honest score (or ``None`` when unmeasurable). A zero-result query on
  an incompletely covered scope stays "not found WITHIN covered scope"
  — never a negative claim about the whole repo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "CoverageState",
    "GAP_TAXONOMY",
    "FileCoverage",
    "CoverageReport",
    "ScopeManifest",
    "build_scope_manifest",
    "is_quarantined",
    "repo_coverage",
    "completeness",
    "coverage_note",
]

import os
import re


class CoverageState:
    """Per-file coverage states (string enum — sqlite friendly)."""

    INDEXED = "indexed"          # parsed, journal clean, outcome COMPLETE/VALID_EMPTY
    PARSED = "parsed"            # indexed with nodes (legacy rows: outcome NULL)
    PARTIAL = "partial"          # PARTIAL_AST — regex fallback ceiling applied
    SKIPPED = "skipped"          # PARSE_ERROR / PARSER_UNAVAILABLE
    EXCLUDED = "excluded"        # generated/vendor path, never indexed
    STALE = "stale"              # journal disagrees with disk (pre-reconcile)
    UNKNOWN = "unknown"          # never scanned, or storage could not tell


#: Declared gap taxonomy (P5.4): every incompleteness reason a receipt
#: may cite. Keys are stable codes; values are human explanations.
GAP_TAXONOMY: Dict[str, str] = {
    "dynamic-dispatch": "runtime-resolved call targets (virtual/dynamic dispatch)",
    "reflection": "string/reflection-based symbol resolution",
    "di": "dependency-injection wiring invisible to static extraction",
    "framework-routing": "framework route/annotation-driven call edges",
    "macros": "macro-generated symbols and calls",
    "fn-pointers": "function-pointer / callback indirection",
    "generated": "generated/vendor sources excluded from verification",
    "cross-repo": "edges leaving this repository boundary",
    "parser-partial": "files parsed only by the regex fallback (PARTIAL_AST)",
    "parser-failed": "files whose parse failed (PARSE_ERROR/PARSER_UNAVAILABLE)",
    "unresolved-edge": "pending edges still UNRESOLVED/AMBIGUOUS",
}
_DYNAMIC_PATTERNS: Dict[str, List[Tuple[re.Pattern, str]]] = {
    "python": [
        (re.compile(r"\b(getattr|setattr|eval|exec|importlib|__import__)\b"), "dynamic_reflection"),
        (re.compile(r"\b(globals|locals)\(\)\s*\["), "dynamic_symbol_lookup"),
    ],
    "typescript": [
        (re.compile(r"\beval\s*\("), "dynamic_eval"),
        (re.compile(r"\bimport\s*\("), "dynamic_import"),
        (re.compile(r"\b(window|globalThis)\s*\["), "dynamic_global_lookup"),
    ],
    "javascript": [
        (re.compile(r"\beval\s*\("), "dynamic_eval"),
        (re.compile(r"\bimport\s*\("), "dynamic_import"),
        (re.compile(r"\b(window|globalThis)\s*\["), "dynamic_global_lookup"),
    ],
    "java": [
        (re.compile(r"\bClass\.forName\b"), "dynamic_class_loading"),
        (re.compile(r"\b(getMethod|getDeclaredMethod|invoke)\b"), "dynamic_reflection"),
        (re.compile(r"\bProxy\.newProxyInstance\b"), "dynamic_proxy"),
    ],
    "go": [
        (re.compile(r"\breflect\.(ValueOf|TypeOf|New|MakeFunc)\b"), "dynamic_reflection"),
        (re.compile(r"\.\(\s*type\s*\)"), "dynamic_type_switch"),
        (re.compile(r"\.\(\s*any\s*\)|\.\(\s*interface\{\}\s*\)"), "dynamic_any_assertion"),
    ],
    "rust": [
        (re.compile(r"\b(std::any::Any|downcast_ref)\b"), "dynamic_any_downcast"),
        (re.compile(r"(&\s*dyn\s+\w+|Box<\s*dyn\s+[^>]+>|\bdyn\s+[A-Z]\w*)"), "dynamic_trait_object"),
    ],
    "c": [
        (re.compile(r"\b(dlopen|dlsym)\b"), "dynamic_library_loading"),
    ],
    "cpp": [
        (re.compile(r"\b(dlopen|dlsym)\b"), "dynamic_library_loading"),
    ],
}

_GENERATED_PARTS = frozenset(
    {"node_modules", ".venv", "venv", "dist", "build", "vendor", "target"}
)
_PB_RE = re.compile(r"_pb\d|_pb\d*_grpc|\.min\.|\.generated\.")

_OUTCOME_TO_STATE = {
    "COMPLETE": CoverageState.INDEXED,
    "VALID_EMPTY": CoverageState.INDEXED,
    "PARTIAL_AST": CoverageState.PARTIAL,
    "PARSE_ERROR": CoverageState.SKIPPED,
    "PARSER_UNAVAILABLE": CoverageState.SKIPPED,
}
def _is_excluded(path: str) -> bool:
    if os.sep == "\\":
        parts = path.replace("\\", "/").split("/")
    else:
        parts = path.split("/")
    return any(p in _GENERATED_PARTS for p in parts[:-1]) or bool(_PB_RE.search(parts[-1]))


def _normalize_rel_path(rel_path: str) -> str:
    """Normalize directory separators on Windows while preserving POSIX literal backslashes."""
    if os.sep == "\\":
        return rel_path.replace("\\", "/")
    return rel_path

@dataclass(frozen=True)
class FileCoverage:
    path: str
    state: str
    language: str
    parser_outcome: Optional[str] = None
    parser_error: Optional[str] = None
    detail: str = ""


@dataclass(frozen=True)
class CoverageReport:
    basis: str  # "measured" | "unknown"
    files: List[FileCoverage] = field(default_factory=list)
    totals: Dict[str, int] = field(default_factory=dict)
    gaps: List[str] = field(default_factory=list)
    detail: str = ""

    @property
    def covered_fraction(self) -> Optional[float]:
        """Fraction of source files in a covered state; None if unknown."""
        if self.basis != "measured" or not self.files:
            return None
        good = sum(
            1 for f in self.files
            if f.state in (CoverageState.INDEXED, CoverageState.PARSED,
                           CoverageState.PARTIAL)
        )
        return good / len(self.files)


def _language_of(path: str) -> str:
    from sot_graph.assurance.identity import _language_of as lang

    return lang(path)


def repo_coverage(
    db: Any,
    repo_root: str,
    paths: Sequence[str] = (),
) -> CoverageReport:
    """Measure real coverage from the journal + disk (never result counts).

    ``paths`` restricts the report to an explicit scope (empty = whole
    journal). Storage failures degrade to ``basis="unknown"`` — the
    caller must treat that as "cannot claim coverage", not as zero.
    """
    try:
        rows = db.conn.execute(
            "SELECT path, parser_outcome, parser_error, sha256, size, mtime_ms "
            "FROM file_journal"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 - degrade, never fabricate
        return CoverageReport(
            basis="unknown",
            detail=f"coverage storage error: {type(exc).__name__}",
        )

    journal = {r[0]: r for r in rows}
    # Journals may store absolute paths (legacy reconcilers did); the
    # coverage report speaks repo-relative so scope filters line up.
    root_norm = os.path.abspath(repo_root)
    for abs_path in [p for p in journal if os.path.isabs(p)]:
        try:
            rel = os.path.relpath(abs_path, root_norm)
            if os.sep == "\\":
                rel = rel.replace("\\", "/")
        except ValueError:
            continue
        if not rel.startswith("..") and rel not in journal:
            journal[rel] = journal.pop(abs_path)

    def _norm_scope_path(p: str) -> str:
        norm = p.replace("\\", "/") if os.sep == "\\" else p
        if norm.startswith("./"):
            norm = norm[2:]
        return norm

    scope = [_norm_scope_path(p) for p in paths] if paths else None
    files: List[FileCoverage] = []
    for path, row in sorted(journal.items()):
        if scope is not None and path not in scope:
            continue
        outcome, perr = row[1], row[2]
        if _is_excluded(path):
            state = CoverageState.EXCLUDED
        elif outcome is None:
            state = CoverageState.PARSED  # legacy row: indexed, outcome unrecorded
        else:
            state = _OUTCOME_TO_STATE.get(str(outcome), CoverageState.UNKNOWN)
        # Staleness beats parse state: a re-written file is stale until
        # the next reconcile, whatever the last parse achieved.
        disk = _disk_state(os.path.join(repo_root, path))
        if disk is not None and state != CoverageState.EXCLUDED:
            sha, size = row[3], row[4]
            # Content identity only (sha+size), mirroring
            # db.stale_journal_files: mtime drift alone (git checkout,
            # rebase, editor rewrite of identical content) is NOT
            # staleness — the bytes on disk are still the indexed bytes.
            same = bool(sha) and disk[0] == sha and disk[1] == size
            if not same:
                state = CoverageState.STALE
        files.append(FileCoverage(
            path=path,
            state=state,
            language=_language_of(path),
            parser_outcome=str(outcome) if outcome is not None else None,
            parser_error=perr,
        ))

    if scope is not None:
        # Explicit scope may name files never scanned — UNKNOWN, honestly.
        known = {f.path for f in files}
        for p in scope:
            if p not in known:
                st = (CoverageState.EXCLUDED if _is_excluded(p)
                      else CoverageState.UNKNOWN)
                files.append(FileCoverage(
                    path=p, state=st, language=_language_of(p),
                ))

    totals: Dict[str, int] = {}
    for f in files:
        totals[f.state] = totals.get(f.state, 0) + 1

    gaps: List[str] = []
    if totals.get(CoverageState.PARTIAL):
        gaps.append("parser-partial")
    if totals.get(CoverageState.SKIPPED):
        gaps.append("parser-failed")
    if totals.get(CoverageState.EXCLUDED):
        gaps.append("generated")
    if totals.get(CoverageState.STALE):
        gaps.append("stale-content")  # disk bytes differ from the indexed hash
    try:
        pending = db.conn.execute(
            "SELECT COUNT(*) FROM pending_edges WHERE resolution_state "
            "IN ('UNRESOLVED','AMBIGUOUS')"
        ).fetchone()
        if pending and int(pending[0]) > 0:
            gaps.append("unresolved-edge")
    except Exception:  # noqa: BLE001 - totals already measured
        pass

    return CoverageReport(basis="measured", files=files, totals=totals, gaps=gaps)


def _disk_state(abs_path: str) -> Optional[tuple]:
    import hashlib

    try:
        st = os.stat(abs_path)
        with open(abs_path, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        return (sha, int(st.st_size), int(st.st_mtime * 1000))
    except OSError:
        return None


def completeness(report: CoverageReport, capability: str = "callgraph") -> Optional[float]:
    """Honest completeness for one capability given measured coverage.

    Returns None when the report is unmeasurable; otherwise the covered
    fraction DISCOUNTED by declared gap families relevant to the
    capability. Not a count of results — an empty result set on full
    coverage is still completeness 1.0.
    """
    if report.basis != "measured":
        return None
    frac = report.covered_fraction
    if frac is None:
        return None
    behavioural_gaps = {
        "dynamic-dispatch": 0.02,
        "reflection": 0.01,
        "di": 0.01,
        "framework-routing": 0.01,
        "macros": 0.005,
        "fn-pointers": 0.005,
        "cross-repo": 0.005,
    }
    structural_gaps = {
        "generated": 0.005,
        "parser-partial": 0.02,
        "parser-failed": 0.02,
        "unresolved-edge": 0.01,
    }
    if capability in ("symbols", "search", "architecture", "repo-map"):
        caps = structural_gaps
    else:  # callgraph / trace / impact / pdg / taint
        caps = {**structural_gaps, **behavioural_gaps}
    penalty = sum(caps.get(g, 0.0) for g in report.gaps)
    return max(0.0, frac - penalty)


def coverage_note(report: CoverageReport) -> str:
    """One-line honest coverage statement for receipts/envelopes."""
    if report.basis != "measured":
        return f"coverage: UNKNOWN ({report.detail or 'unmeasured'})"
    total = sum(report.totals.values())
    frac = report.covered_fraction
    pct = f"{frac * 100:.0f}%" if frac is not None else "?"
    gaps = f"; gaps: {', '.join(sorted(report.gaps))}" if report.gaps else ""
    return f"coverage: {pct} of {total} journal files measured{gaps}"


@dataclass(frozen=True)
class ScopeManifest:
    """Explicit Bounded Scope declaration (P1 / R5)."""

    included_files: List[str] = field(default_factory=list)
    excluded_patterns: List[str] = field(default_factory=list)
    parser_error_files: List[str] = field(default_factory=list)
    unsupported_constructs: List[str] = field(default_factory=list)
    quarantined_files: List[str] = field(default_factory=list)
    manifest_digest: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "included_files": list(self.included_files),
            "excluded_patterns": list(self.excluded_patterns),
            "parser_error_files": list(self.parser_error_files),
            "unsupported_constructs": list(self.unsupported_constructs),
            "quarantined_files": list(self.quarantined_files),
            "manifest_digest": self.manifest_digest,
        }


def _matches_exclusion(path: str, exclusions: Sequence[str]) -> bool:
    """Match path against standard exclusions and custom exclusion patterns."""
    if _is_excluded(path):
        return True
    if os.sep == "\\":
        norm_path = path.replace("\\", "/")
        parts = norm_path.split("/")
    else:
        norm_path = path
        parts = path.split("/")
    filename = parts[-1]
    import fnmatch
    for exc in exclusions:
        if not exc:
            continue
        exc_norm = exc.replace("\\", "/") if os.sep == "\\" else exc
        # Direct directory / segment match (e.g. "build", "dist", "vendor")
        if any(part == exc or part == exc_norm for part in parts[:-1]):
            return True
        if filename == exc or filename == exc_norm:
            return True
        if fnmatch.fnmatch(norm_path, exc_norm) or fnmatch.fnmatch(filename, exc_norm):
            return True
        if fnmatch.fnmatch(path, exc) or fnmatch.fnmatch(filename, exc):
            return True
    return False


def build_scope_manifest(
    db: Any,
    repo_root: str,
    target_paths: Sequence[str] = (),
    excluded_patterns: Sequence[str] = (),
) -> ScopeManifest:
    """Build deterministic ScopeManifest for explicit bounded scope."""
    import hashlib

    default_exclusions = sorted(set(list(_GENERATED_PARTS) + list(excluded_patterns)))
    canonical_root = os.path.realpath(repo_root)

    try:
        rows = db.conn.execute(
            "SELECT path, parser_outcome, parser_error FROM file_journal"
        ).fetchall()
    except Exception:
        rows = []

    included: List[str] = []
    parser_errors: List[str] = []
    quarantined: List[str] = []
    unsupported: List[str] = []

    targets: Optional[set[str]] = None
    if target_paths:
        targets = set()
        for tp in target_paths:
            if not tp:
                continue
            tp_str = str(tp)
            try:
                abs_tp = os.path.realpath(
                    tp_str if os.path.isabs(tp_str) else os.path.join(canonical_root, tp_str)
                )
                rel_tp = _normalize_rel_path(os.path.relpath(abs_tp, canonical_root))
                targets.add(rel_tp)
            except Exception:
                targets.add(_normalize_rel_path(tp_str))
    journal_paths: Dict[str, Tuple[Optional[str], Optional[str]]] = {}

    for r in rows:
        p_raw, outcome, p_err = str(r[0]), r[1], r[2]
        abs_cand = os.path.realpath(
            p_raw if os.path.isabs(p_raw) else os.path.join(canonical_root, p_raw)
        )
        try:
            is_inside = os.path.commonpath([canonical_root, abs_cand]) == canonical_root
        except ValueError:
            is_inside = False

        if not is_inside:
            parser_errors.append(p_raw)
            quarantined.append(p_raw)
            unsupported.append(f"{p_raw}:path_traversal_out_of_repo")
            continue

        p = _normalize_rel_path(os.path.relpath(abs_cand, canonical_root))
        journal_paths[p] = (outcome, p_err)

    # Filesystem audit: discover unjournaled candidate files on disk
    ignored_dir_names = set(_GENERATED_PARTS) | {
        ".git", ".sot", ".venv", "venv", ".idea", ".vscode", "__pycache__", ".scip"
    }
    def _on_walk_error(err: OSError) -> None:
        err_msg = str(err)
        quarantined.append(err_msg)
        parser_errors.append(err_msg)
        unsupported.append(f"walk_error:{err_msg}")

    try:
        for root_dir, dirs, files in os.walk(canonical_root, followlinks=False, onerror=_on_walk_error):
            surviving_dirs: list[str] = []
            for d in dirs:
                abs_d_target = os.path.join(root_dir, d)
                abs_d_real = os.path.realpath(abs_d_target)
                try:
                    d_inside = os.path.commonpath([canonical_root, abs_d_real]) == canonical_root
                except ValueError:
                    d_inside = False

                rel_d = _normalize_rel_path(os.path.relpath(abs_d_target, canonical_root))
                if not d_inside:
                    quarantined.append(rel_d)
                    parser_errors.append(rel_d)
                    unsupported.append(f"{rel_d}:outside_symlink")
                    continue

                if d in ignored_dir_names:
                    continue
                if _matches_exclusion(rel_d, default_exclusions):
                    continue
                surviving_dirs.append(d)
            dirs[:] = surviving_dirs
            for f in files:
                abs_f_target = os.path.join(root_dir, f)
                abs_f_real = os.path.realpath(abs_f_target)
                try:
                    f_inside = os.path.commonpath([canonical_root, abs_f_real]) == canonical_root
                except ValueError:
                    f_inside = False

                rel_f = _normalize_rel_path(os.path.relpath(abs_f_target, canonical_root))
                if not f_inside:
                    quarantined.append(rel_f)
                    parser_errors.append(rel_f)
                    unsupported.append(f"{rel_f}:outside_symlink")
                    continue

                if _matches_exclusion(rel_f, default_exclusions):
                    continue
                if targets is not None and rel_f not in targets:
                    continue
                _, ext = os.path.splitext(f)
                from sot_graph.reconciler import EXT_DISPATCH, TEXT_EXTENSIONS
                supported_exts = frozenset(EXT_DISPATCH.keys()) | frozenset(TEXT_EXTENSIONS)
                if ext.lower() not in supported_exts and rel_f not in journal_paths:
                    continue
                if rel_f not in journal_paths:
                    included.append(rel_f)
                    parser_errors.append(rel_f)
                    quarantined.append(rel_f)
                    unsupported.append(f"{rel_f}:unjournaled_file")
    except OSError as exc:
        _on_walk_error(exc)
    # Process journaled files
    for p, (outcome, _) in journal_paths.items():
        if _matches_exclusion(p, default_exclusions):
            continue
        if targets is not None and p not in targets:
            continue
        if p not in included:
            included.append(p)
        if outcome in ("PARSE_ERROR", "PARSER_UNAVAILABLE"):
            parser_errors.append(p)
            quarantined.append(p)

    included.sort()
    for inc in included:
        abs_p = os.path.join(canonical_root, inc)
        if not os.path.isfile(abs_p):
            parser_errors.append(inc)
            quarantined.append(inc)
            unsupported.append(f"{inc}:missing_source")
            continue
        lang = _language_of(inc)
        patterns = _DYNAMIC_PATTERNS.get(lang, [])
        if patterns:
            try:
                with open(abs_p, "r", encoding="utf-8", errors="ignore") as fh:
                    buffer = ""
                    for chunk in iter(lambda: fh.read(65536), ""):
                        combined = (buffer[-1024:] + chunk) if buffer else chunk
                        buffer = chunk
                        for pat, kind in patterns:
                            tag = f"{inc}:{kind}"
                            if tag not in unsupported and pat.search(combined):
                                unsupported.append(tag)
            except OSError:
                parser_errors.append(inc)
                quarantined.append(inc)
                unsupported.append(f"{inc}:unreadable_source")
    parser_errors = sorted(list(set(parser_errors)))
    quarantined = sorted(list(set(quarantined)))
    unsupported = sorted(list(set(unsupported)))
    hasher = hashlib.sha256()
    for inc in included:
        hasher.update(f"inc:{inc}\n".encode("utf-8", errors="surrogateescape"))
    for exc in default_exclusions:
        hasher.update(f"exc:{exc}\n".encode("utf-8", errors="surrogateescape"))
    digest = f"sha256:{hasher.hexdigest()}"

    return ScopeManifest(
        included_files=included,
        excluded_patterns=default_exclusions,
        parser_error_files=parser_errors,
        unsupported_constructs=unsupported,
        quarantined_files=quarantined,
        manifest_digest=digest,
    )


def is_quarantined(path: str, manifest: ScopeManifest) -> bool:
    """Check if a file path is quarantined by scope manifest."""
    return path in manifest.quarantined_files or path in manifest.parser_error_files
