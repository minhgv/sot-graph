"""
sot_graph.verifier — Trust Verdict Engine (Trust Model v2).

Calculates multi-dimensional evidence (Freshness, Relevance, Resolution, Completeness, Confidence)
against physical disk reality, validates file existence, and provides backward-compatible
legacy verdicts ([STRONG], [WEAK], [STALE], [REBUILT], [REMOVED]).
"""

from __future__ import annotations
import ast
import hashlib
import os
import re
from typing import Any, Dict, Optional, Set, Tuple

from sot_graph.db import Database
from sot_graph.evidence import (
    CompletenessStatus,
    FreshnessStatus,
    RelevanceType,
    ResolutionStatus,
    TrustEvidence,
)
from sot_graph.ignore import DEFAULT_IGNORED_DIRS
from sot_graph.parser_outcome import ParserOutcome

# Stop words ignored during lexical coverage calculation
STOP_WORDS: Set[str] = {
    "the", "and", "for", "with", "from", "that", "this", "have", "are", "was",
    "you", "your", "not", "but", "its", "all", "can", "has", "had", "she",
    "her", "him", "his", "our", "their", "them", "who", "whom", "which",
    "what", "when", "where", "why", "how", "into", "than", "then", "they",
    "self", "class", "def", "function", "return", "import", "const", "let", "var",
}

IGNORED_DIRS: Set[str] = set(DEFAULT_IGNORED_DIRS)

#: Rehome basename index (R5): the auto-heal path used to run a full
#: ``os.walk`` of the repo root PER missing file — O(missing x repo) disk
#: traversal for one heal pass over several moved files. The index caches
#: one bounded walk (10k-file cap preserved) per project root so multiple
#: missing files in the same pass share a single walk.
#:
#: Tightest safe scope, deliberately:
#: - keyed by resolved root, small bound on roots retained;
#: - only UNIQUE candidate paths are served from cache, and every cached
#:   path is existence-checked at use time — a stale path invalidates the
#:   whole root index and triggers exactly one rebuild before answering;
#: - "absent" and "ambiguous" basenames are never served from cache: they
#:   force one fresh rebuild, so a purge decision (basename nowhere in the
#:   tree) is always based on a current walk, never on stale bookkeeping.
_REHOME_INDEX: Dict[str, Dict[str, str]] = {}
_REHOME_INDEX_MAX_ROOTS = 8


def _reset_rehome_index() -> None:
    """Drop all cached rehome indexes (test/admin hook)."""
    _REHOME_INDEX.clear()


def _store_rehome_index(root: str, index: Dict[str, str]) -> None:
    _REHOME_INDEX.pop(root, None)
    _REHOME_INDEX[root] = index
    while len(_REHOME_INDEX) > _REHOME_INDEX_MAX_ROOTS:
        _REHOME_INDEX.pop(next(iter(_REHOME_INDEX)))


def _build_rehome_index(root: str, max_scanned_files: int) -> Dict[str, str]:
    """One bounded ``os.walk`` mapping basename -> unique candidate path.

    Mirrors the original per-call scan: ignored dirs are pruned, the scan
    stops after ``max_scanned_files`` files, and a basename seen more than
    once is dropped (ambiguous — never guessed).
    """
    index: Dict[str, str] = {}
    ambiguous: Set[str] = set()
    scanned = 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        scanned += len(files)
        for name in files:
            if name in ambiguous or name in index:
                ambiguous.add(name)
                index.pop(name, None)
                continue
            index[name] = os.path.abspath(os.path.join(dirpath, name))
        if scanned >= max_scanned_files:
            break
    return index


def tokenize(text: str) -> Set[str]:
    """Tokenizes text into normalized alphanumeric keywords >= 3 chars."""
    if not text:
        return set()
    tokens = re.findall(r"[a-zA-Z0-9_.\-/]{3,}", text.lower())
    return {t for t in tokens if t not in STOP_WORDS}


class VerificationResult(Tuple[str, Optional[float], str]):
    """
    Backward-compatible 3-tuple (verdict, coverage, path) that attaches
    a multi-dimensional TrustEvidence instance for Trust Model v2.
    """
    evidence: TrustEvidence

    def __new__(cls, verdict: str, coverage: Optional[float], path: str, evidence: TrustEvidence):
        inst = super().__new__(cls, (verdict, coverage, path))
        inst.evidence = evidence
        return inst


class TrustVerifier:
    @staticmethod
    def calculate_coverage(file_path: str, query_tokens: Set[str], max_bytes: int = 524288) -> Optional[float]:
        """
        Reads up to max_bytes (default 512KB) from physical file and computes
        the fraction of query tokens present in the actual disk content.
        Returns None if file cannot be read, is binary, or is oversized.
        """
        if not query_tokens or not os.path.exists(file_path):
            return None
        try:
            st = os.stat(file_path)
            if st.st_size > max_bytes:
                return None
            with open(file_path, "rb") as f:
                raw = f.read(max_bytes)
            if b"\x00" in raw[:1024]:  # Binary guard
                return None
            content = raw.decode("utf-8", errors="replace").lower()
            hit = sum(1 for t in query_tokens if t in content)
            return hit / len(query_tokens)
        except Exception:
            return None

    @staticmethod
    def find_rehome(project_root: str, basename: str, max_scanned_files: int = 10000) -> Optional[str]:
        """
        Scans project_root for a single unambiguous file with the given basename.
        Used to heal moved/renamed files automatically.

        Served from a per-root basename index (one bounded walk, shared
        across the missing-file lookups of a heal pass — R5). Cached paths
        are existence-checked at use time; a stale path rebuilds the index
        once and re-answers. Absent or ambiguous basenames always force a
        fresh rebuild so purge/ambiguity decisions never ride stale state.
        """
        root = os.path.abspath(project_root)
        for _attempt in (0, 1):
            index = _REHOME_INDEX.get(root)
            if index is None:
                index = _build_rehome_index(root, max_scanned_files)
                _store_rehome_index(root, index)
            candidate = index.get(basename)
            if candidate is not None and os.path.isfile(candidate):
                return candidate
            # Absent from the scanned tree, ambiguous (dropped at build
            # time), or a stale cached path: rebuild exactly once and
            # answer from the fresh walk instead.
            _REHOME_INDEX.pop(root, None)
        return None

    @staticmethod
    def _verify_ast_declaration(
        file_path: str,
        cand_symbol: Optional[str],
        cand_line: Optional[int],
        text_content: str,
        cov: Optional[float],
        threshold: float,
    ) -> Tuple[RelevanceType, str, bool, Optional[str]]:
        """
        Verifies whether cand_symbol genuinely exists as an AST declaration at cand_line.

        Returns (relevance, provenance, ast_verified, parser_outcome):
        - ast_verified is True ONLY when a real parser (Python ``ast`` module)
          confirmed the declaration/span. Regex token coverage over
          comment-stripped text can NEVER confirm — it yields heuristic-level
          evidence only (FILE_TOKEN relevance with a regex_decl:* provenance).
        - parser_outcome mirrors sot_graph.parser_outcome.ParserOutcome for
          the verification pass itself.
        """
        if not cand_symbol or not isinstance(cand_symbol, str):
            if cov is not None and cov >= threshold:
                return RelevanceType.FILE_TOKEN, "lexical:file_token", False, None
            return RelevanceType.UNKNOWN, "lexical:unknown", False, None

        symbol_needle = cand_symbol.rsplit(".", 1)[-1]
        ext = os.path.splitext(file_path)[1].lower()

        # Python AST analysis — the only path allowed to claim EXACT_*
        parse_outcome: Optional[str] = None
        if ext == ".py":
            try:
                tree = ast.parse(text_content, filename=file_path)
            except SyntaxError:
                # Real parser ran and failed: honest PARSE_ERROR, then fall
                # through to regex/lexical heuristics.
                parse_outcome = ParserOutcome.PARSE_ERROR.value
            else:
                parse_outcome = ParserOutcome.COMPLETE.value
                exact_span_found = False
                exact_symbol_found = False

                def _decl_name(node: ast.AST) -> Optional[str]:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        return node.name
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                return target.id
                    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                        return node.target.id
                    return None

                name_hits = sum(
                    1 for n in ast.walk(tree) if _decl_name(n) == symbol_needle
                )
                for node in ast.walk(tree):
                    name = None
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        name = node.name
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                name = target.id
                                break
                    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                        name = node.target.id

                    if name == symbol_needle:
                        exact_symbol_found = True
                        node_start = getattr(node, "lineno", 0)
                        node_end = getattr(node, "end_lineno", node_start)
                        if cand_line and cand_line > 0:
                            in_span = node_start <= cand_line <= node_end
                            # ±2 tolerance only while the name is unique in
                            # this file; with duplicated names (two classes
                            # declaring the same method, adjacent accessors)
                            # the slack confirms the wrong declaration.
                            if in_span or (name_hits <= 1
                                           and (node_start - 2) <= cand_line <= (node_end + 2)):
                                exact_span_found = True
                                break

                if exact_span_found:
                    return RelevanceType.EXACT_SPAN, "ast_visitor:exact_span", True, parse_outcome
                if exact_symbol_found:
                    return RelevanceType.EXACT_SYMBOL, "ast_visitor:exact_symbol", True, parse_outcome
                # If not found in AST, check if it's merely a comment or string
                if symbol_needle in text_content:
                    return (
                        RelevanceType.FILE_TOKEN,
                        "lexical:comment_or_literal",
                        False,
                        parse_outcome,
                    )
                return RelevanceType.NAME_ONLY, "ast_visitor:not_found", False, parse_outcome

        if parse_outcome is None:
            # No real parser for this extension in the verifier: everything
            # below is heuristic-only evidence.
            parse_outcome = ParserOutcome.PARTIAL_AST.value

        # Strip comments and string literals so commented-out code or string
        # literals cannot even reach heuristic level. NOTE: a match after this
        # strip is STILL only regex evidence and must never be confirmed.
        stripped_content = text_content
        if ext in (".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".cs", ".go", ".rs", ".php", ".swift", ".kt"):
            pattern = re.compile(
                r'(/\*[\s\S]*?\*/)'          # block comment
                r'|(//[^\n]*)'               # line comment
                r'|("(?:\\.|[^"\\])*")'      # double-quoted string
                r"|('(?:\\.|[^'\\])*')"      # single-quoted string
                r'|(`(?:\\.|[^`\\])*`)',     # template string
                re.MULTILINE
            )
            def replacer(match):
                s = match.group(0)
                if s.startswith("/*"):
                    return "\n" * s.count("\n")
                elif s.startswith("//"):
                    return ""
                else:
                    return '"' + ("\n" * s.count("\n")) + '"'
            stripped_content = pattern.sub(replacer, text_content)
        elif ext in (".py", ".sh", ".rb"):
            pattern = re.compile(
                r'(#[^\n]*)'
                r'|("""[\s\S]*?""")'
                r"|('''[\s\S]*?''')"
                r'|("(?:\\.|[^"\\])*")'
                r"|('(?:\\.|[^'\\])*')",
                re.MULTILINE
            )
            def replacer(match):
                s = match.group(0)
                if s.startswith("#"):
                    return ""
                else:
                    return '"' + ("\n" * s.count("\n")) + '"'
            stripped_content = pattern.sub(replacer, text_content)

        # Generic regex declaration check for other languages / fallback.
        # Truthfulness contract: regex-declaration matches are HEURISTIC
        # evidence (FILE_TOKEN relevance, low confidence ceiling), never
        # EXACT_SPAN / EXACT_SYMBOL, regardless of coverage.
        decl_pat = re.compile(
            rf"(?:function|class|def|interface|type|const|let|var|func|fn|struct|enum|trait)\s+{re.escape(symbol_needle)}\b",
            re.MULTILINE,
        )
        if decl_pat.search(stripped_content):
            if cand_line and cand_line > 0:
                lines = stripped_content.splitlines()
                start_idx = max(0, cand_line - 5)
                end_idx = min(len(lines), cand_line + 5)
                span_text = "\n".join(lines[start_idx:end_idx])
                if decl_pat.search(span_text):
                    return RelevanceType.FILE_TOKEN, "regex_decl:heuristic_span", False, parse_outcome
                if symbol_needle in span_text:
                    return RelevanceType.FILE_TOKEN, "regex_decl:heuristic_candidate", False, parse_outcome
            return RelevanceType.FILE_TOKEN, "regex_decl:heuristic", False, parse_outcome
        if symbol_needle in text_content:
            return RelevanceType.FILE_TOKEN, "lexical:file_token", False, parse_outcome
        if cov and cov >= threshold:
            return RelevanceType.FILE_TOKEN, "lexical:file_token", False, parse_outcome
        return RelevanceType.NAME_ONLY, "lexical:name_only", False, parse_outcome
    @staticmethod
    def _rehomable(new_path: str, candidate: Dict[str, Any]) -> bool:
        """Guard against basename collisions re-homing nodes onto the wrong file."""
        symbol = candidate.get("symbol")
        if candidate.get("kind") == "file" or not symbol:
            return True
        needle = str(symbol).rsplit(".", 1)[-1]
        if not needle.isidentifier() and not needle.replace("$", "").isalnum():
            return True
        try:
            with open(new_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(524288)
        except OSError:
            return False
        return re.search(rf"\b{re.escape(needle)}\b", content) is not None
    @classmethod
    def verify_evidence(
        cls,
        candidate: Dict[str, Any],
        query_tokens: Set[str],
        project_root: str,
        threshold: float = 0.5,
        db: Optional[Database] = None,
        auto_heal: bool = False,
        jit_reconcile: bool = False,
    ) -> TrustEvidence:
        """
        Produce a multi-dimensional TrustEvidence object for a candidate hit.
        """
        path = candidate.get("path")
        node_id = candidate.get("id", "")
        root = os.path.abspath(project_root)

        if not path or not str(path).strip():
            return TrustEvidence(
                freshness=FreshnessStatus.UNKNOWN,
                relevance=RelevanceType.UNKNOWN,
                resolution=ResolutionStatus.UNRESOLVED,
                completeness=CompletenessStatus.UNKNOWN,
                confidence=0.0,
                provenance="trust_verifier:v2",
                file_path="",
                coverage=1.0,
                details={"nopath": True},
            )

        requested = os.path.abspath(os.path.expanduser(str(path)))

        def _inside_root(value: str) -> bool:
            try:
                return os.path.commonpath([os.path.realpath(root), os.path.realpath(value)]) == os.path.realpath(root)
            except (OSError, ValueError):
                return False

        if not os.path.isabs(str(path)):
            requested = os.path.abspath(os.path.join(root, str(path)))
        if not _inside_root(requested):
            return TrustEvidence(
                freshness=FreshnessStatus.STALE,
                relevance=RelevanceType.UNKNOWN,
                resolution=ResolutionStatus.UNRESOLVED,
                completeness=CompletenessStatus.PARTIAL,
                confidence=0.0,
                provenance="trust_verifier:v2",
                file_path=str(path),
                details={"outside_root": True},
            )

        # 1. File exists on disk
        if os.path.exists(requested) and os.path.isfile(requested):
            try:
                st = os.stat(requested)
                if st.st_size > 524288:  # 512 KB
                    return TrustEvidence(
                        freshness=FreshnessStatus.UNKNOWN,
                        relevance=RelevanceType.UNKNOWN,
                        resolution=ResolutionStatus.EXACT,
                        completeness=CompletenessStatus.COMPLETE,
                        confidence=0.0,
                        provenance="trust_verifier:v2",
                        file_path=requested,
                        coverage=None,
                        details={"oversized": True, "size": st.st_size},
                    )
                with open(requested, "rb") as f:
                    raw = f.read(524288)
                if b"\x00" in raw[:1024]:  # Binary guard
                    return TrustEvidence(
                        freshness=FreshnessStatus.UNKNOWN,
                        relevance=RelevanceType.UNKNOWN,
                        resolution=ResolutionStatus.EXACT,
                        completeness=CompletenessStatus.COMPLETE,
                        confidence=0.0,
                        provenance="trust_verifier:v2",
                        file_path=requested,
                        coverage=None,
                        details={"binary": True},
                    )
                file_hash = hashlib.sha256(raw).hexdigest()
                text_content = raw.decode("utf-8", errors="replace")
                text_lower = text_content.lower()
            except Exception as exc:
                return TrustEvidence(
                    freshness=FreshnessStatus.UNKNOWN,
                    relevance=RelevanceType.UNKNOWN,
                    resolution=ResolutionStatus.EXACT,
                    completeness=CompletenessStatus.COMPLETE,
                    confidence=0.0,
                    provenance="trust_verifier:v2",
                    file_path=requested,
                    coverage=None,
                    details={"error": str(exc)},
                )

            # Calculate coverage
            if query_tokens:
                hit = sum(1 for t in query_tokens if t in text_lower)
                cov = hit / len(query_tokens)
            else:
                cov = None

            # Check freshness strictly against file_journal in DB
            rel_path = os.path.relpath(requested, root).replace(os.sep, "/")
            is_stale = False
            journal_sha256 = None
            if db is not None:
                journal_row = None
                if hasattr(db, "get_file_journal"):
                    journal_row = db.get_file_journal(rel_path) or db.get_file_journal(requested) or db.get_file_journal(str(path))
                elif hasattr(db, "conn"):
                    try:
                        row = db.conn.execute(
                            "SELECT sha256, size, mtime_ms FROM file_journal WHERE path = ? OR path = ?",
                            (rel_path, requested),
                        ).fetchone()
                        if row:
                            journal_row = {"sha256": row[0], "size": row[1], "mtime_ms": row[2]}
                    except Exception:
                        journal_row = None

                if journal_row is None:
                    freshness = FreshnessStatus.UNKNOWN
                else:
                    journal_sha256 = journal_row.get("sha256")
                    disk_mtime_ms = int(st.st_mtime * 1000)
                    journal_mtime_ms = int(journal_row.get("mtime_ms", 0))
                    if (journal_sha256 and file_hash != journal_sha256) or (not journal_sha256 and disk_mtime_ms != journal_mtime_ms):
                        is_stale = True
                        if jit_reconcile and not getattr(db, "_read_only", False):
                            try:
                                from sot_graph.reconciler import Reconciler
                                rec = Reconciler(db, root)
                                summary = rec.reconcile(paths=[requested], workers=1)
                                # Trust FRESH only when the reconcile actually
                                # published this path (or found it clean): a
                                # conflict/failed commit must NOT be laundered
                                # into a FRESH verdict on unindexed content.
                                post = db.get_file_journal(requested) if hasattr(db, "get_file_journal") else None
                                reconciled_clean = bool(
                                    summary is None
                                    or (getattr(summary, "failed", 0) or 0) == 0
                                ) and post is not None and post.get("sha256") == file_hash
                                if reconciled_clean:
                                    freshness = FreshnessStatus.FRESH
                                    is_stale = False
                                    # Post-reconcile check: verify if the candidate node still physically exists in DB
                                    cand_id = candidate.get("id")
                                    if cand_id and hasattr(db, "get_node"):
                                        post_node = db.get_node(cand_id)
                                        if post_node is None:
                                            # Node was purged during reconciliation -> mark REMOVED
                                            return TrustEvidence(
                                                freshness=FreshnessStatus.FRESH,
                                                relevance=RelevanceType.NAME_ONLY,
                                                resolution=ResolutionStatus.UNRESOLVED,
                                                completeness=CompletenessStatus.NOT_APPLICABLE,
                                                confidence=0.0,
                                                provenance="jit_reconcile:purged",
                                                file_path=requested,
                                                file_hash=file_hash,
                                                details={"removed": True, "stale": False},
                                            )
                                else:
                                    freshness = FreshnessStatus.STALE
                            except Exception:
                                freshness = FreshnessStatus.STALE
                        else:
                            freshness = FreshnessStatus.STALE
                    else:
                        freshness = FreshnessStatus.FRESH
            else:
                freshness = FreshnessStatus.UNKNOWN
            # Relevance detection via AST declaration verification
            cand_symbol = candidate.get("symbol")
            cand_line = candidate.get("line_start") or candidate.get("line")
            ast_verified: Optional[bool] = None
            v_parser_outcome: Optional[str] = None
            if candidate.get("kind") == "file":
                relevance = RelevanceType.EXACT_SYMBOL if cov is None or cov >= threshold else RelevanceType.FILE_TOKEN
                prov = "file_node"
            else:
                relevance, prov, ast_verified, v_parser_outcome = cls._verify_ast_declaration(
                    requested, cand_symbol, cand_line, text_content, cov, threshold
                )

            # Stale files MUST NOT claim EXACT_SPAN
            if is_stale or freshness != FreshnessStatus.FRESH:
                if relevance == RelevanceType.EXACT_SPAN:
                    relevance = RelevanceType.FILE_TOKEN

            # Truthfulness flags: only a real AST verification on a fresh
            # file counts as confirmed. File-kind nodes are confirmed by
            # physical existence + hash match, not span parsing.
            if ast_verified is None:
                confirmed = freshness == FreshnessStatus.FRESH
            else:
                confirmed = freshness == FreshnessStatus.FRESH and ast_verified

            # Confidence calculation
            if freshness == FreshnessStatus.FRESH:
                if relevance == RelevanceType.EXACT_SPAN:
                    confidence = max(0.95, cov or 0.95)
                elif relevance == RelevanceType.EXACT_SYMBOL:
                    confidence = max(0.85, cov or 0.85)
                elif prov.startswith("regex_decl:"):
                    # Regex-only declaration match: heuristic ceiling, never
                    # strong enough to look confirmed.
                    confidence = max(0.30, min(0.45, cov if cov is not None else 0.45))
                elif relevance == RelevanceType.FILE_TOKEN:
                    # Token coverage alone is heuristic evidence.
                    confidence = min(0.35, cov or 0.3)
                elif candidate.get("kind") == "file":
                    confidence = 0.9 if cov is None or cov >= threshold else max(0.6, cov)
                else:
                    confidence = 0.25
            elif freshness == FreshnessStatus.STALE:
                confidence = min(0.35, (cov or 0.5) * 0.5)
            else:  # UNKNOWN
                confidence = min(0.5, cov or 0.4)

            return TrustEvidence(
                freshness=freshness,
                relevance=relevance,
                resolution=ResolutionStatus.EXACT if candidate.get("kind") != "file" else ResolutionStatus.NOT_APPLICABLE,
                completeness=CompletenessStatus.COMPLETE_WITHIN_INDEX_CAPABILITY if not is_stale else CompletenessStatus.PARTIAL,
                confidence=min(1.0, max(0.0, confidence)),
                provenance=prov,
                file_path=requested,
                file_hash=file_hash,
                coverage=cov,
                details={
                    "mtime_ms": int(st.st_mtime * 1000),
                    "size": st.st_size,
                    "stale": is_stale,
                    "indexed_sha": journal_sha256,
                    "current_sha": file_hash,
                    "source_span_verified": ast_verified,
                    "confirmed": confirmed,
                    "parser_outcome": v_parser_outcome,
                },
            )
        # 2. File is MISSING on disk
        if not auto_heal or db is None:
            return TrustEvidence(
                freshness=FreshnessStatus.MISSING,
                relevance=RelevanceType.UNKNOWN,
                resolution=ResolutionStatus.UNRESOLVED,
                completeness=CompletenessStatus.PARTIAL,
                confidence=0.0,
                provenance="trust_verifier:v2",
                file_path=requested,
                details={"missing": True},
            )

        # 3. Auto-heal branch (only when explicitly requested by writer/reconciler)
        basename = os.path.basename(requested)
        new_path = cls.find_rehome(root, basename)
        if new_path and _inside_root(new_path) and os.path.exists(new_path):
            if cls._rehomable(new_path, candidate):
                db.update_node_path(node_id, requested, new_path)
                cov = cls.calculate_coverage(new_path, query_tokens)
                return TrustEvidence(
                    freshness=FreshnessStatus.FRESH,
                    relevance=RelevanceType.FILE_TOKEN,
                    resolution=ResolutionStatus.INFERRED,
                    completeness=CompletenessStatus.PARTIAL,
                    confidence=cov or 0.7,
                    provenance="trust_verifier:auto_rehome",
                    file_path=new_path,
                    coverage=cov,
                    details={"rehomed": True, "old_path": requested},
                )
        db.delete_path(requested)
        return TrustEvidence(
            freshness=FreshnessStatus.MISSING,
            relevance=RelevanceType.UNKNOWN,
            resolution=ResolutionStatus.UNRESOLVED,
            completeness=CompletenessStatus.PARTIAL,
            confidence=0.0,
            provenance="trust_verifier:auto_purge",
            file_path=requested,
            coverage=0.0,
            details={"removed": True},
        )

    @classmethod
    def verify_hit(
        cls,
        db: Optional[Database],
        candidate: Dict[str, Any],
        query_tokens: Set[str],
        project_root: str,
        threshold: float = 0.5,
        auto_heal: bool = False,
        jit_reconcile: bool = False,
    ) -> VerificationResult:
        """
        Verify a search hit against disk reality. Returns VerificationResult
        which functions as a (verdict, coverage, path) tuple with attached .evidence.
        """
        evidence = cls.verify_evidence(
            candidate=candidate,
            query_tokens=query_tokens,
            project_root=project_root,
            threshold=threshold,
            db=db,
            auto_heal=auto_heal,
            jit_reconcile=jit_reconcile,
        )
        verdict = evidence.to_legacy_verdict()
        return VerificationResult(verdict, evidence.coverage, evidence.file_path, evidence)
