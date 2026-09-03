"""
sot_graph.diff_impact — Git Diff Impact Analysis and Commit Risk Engine for SOT-Graph.

Extracts modified line intervals from git unified diffs, maps changes to AST nodes in
SQLite schema v5 (.sot/sot.db), computes reverse call-graph blast radius (in-degree callers),
identifies affected cross-stack API endpoints, and flags impacted test suites.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

__all__ = [
    "DiffHunk",
    "DirectNodeChange",
    "CallerImpact",
    "ApiImpact",
    "TestImpact",
    "DiffImpactResult",
    "CommitSummary",
    "CommitHistoryResult",
    "GitDeltaExtractor",
    "ASTCoordinateMapper",
    "CommitHistoryEngine",
    "DiffImpactEngine",
    "analyze_diff_impact",
    "analyze_commit_history",
    "format_diff_impact_markdown",
    "format_diff_impact_github",
    "format_diff_impact_json",
    "format_commit_history_markdown",
    "format_commit_history_json",
]


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class DiffHunk:
    """Represents a unified diff hunk in a file."""
    file_path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    heading: str = ""
    lines_added: int = 0
    lines_deleted: int = 0
    intervals: List[Tuple[int, int]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DirectNodeChange:
    """AST node directly intersected by diff line changes."""
    id: str
    path: str
    kind: str
    symbol: str
    fqn: str
    label: str
    line_start: int
    line_end: int
    change_type: str  # 'modified', 'added', 'deleted'
    intersected_lines: List[Tuple[int, int]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CallerImpact:
    """Upstream caller node impacted via reverse call-graph traversal."""
    id: str
    path: str
    kind: str
    symbol: str
    fqn: str
    label: str
    line_start: int
    depth: int
    via_relation: str
    callee_id: str
    callee_symbol: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApiImpact:
    """API endpoint or cross-stack binding affected by modified symbols."""
    id: str
    http_method: str
    normalized_uri: str
    fe_caller_symbol: str
    be_controller_symbol: str
    fe_file: Optional[str] = None
    be_file: Optional[str] = None
    impact_source: str = "direct_node"  # 'direct_node', 'caller_node', 'file_match'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TestImpact:
    """Test file or test symbol requiring re-execution."""
    id: str
    path: str
    symbol: str
    kind: str
    impact_reason: str  # 'direct_test_file', 'calls_modified_node', 'imports_modified_module'
    target_symbol: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DiffImpactResult:
    """Comprehensive impact analysis result for a git target or working tree."""
    target: str
    repo_path: str
    changed_files: List[str] = field(default_factory=list)
    hunks: List[DiffHunk] = field(default_factory=list)
    direct_nodes: List[DirectNodeChange] = field(default_factory=list)
    caller_impacts: List[CallerImpact] = field(default_factory=list)
    api_impacts: List[ApiImpact] = field(default_factory=list)
    test_impacts: List[TestImpact] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "repo_path": self.repo_path,
            "changed_files": self.changed_files,
            "hunks": [h.to_dict() for h in self.hunks],
            "direct_nodes": [n.to_dict() for n in self.direct_nodes],
            "caller_impacts": [c.to_dict() for c in self.caller_impacts],
            "api_impacts": [a.to_dict() for a in self.api_impacts],
            "test_impacts": [t.to_dict() for t in self.test_impacts],
            "summary": self.summary,
        }


@dataclass
class CommitSummary:
    """Risk and churn summary for a single git commit."""
    commit_hash: str
    short_hash: str
    author: str
    date: str
    message: str
    files_changed: List[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    touched_symbols: List[str] = field(default_factory=list)
    risk_level: str = "LOW"  # 'LOW', 'MEDIUM', 'HIGH'
    risk_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CommitHistoryResult:
    """Collection of analyzed commits with risk assessment breakdown."""
    commits: List[CommitSummary] = field(default_factory=list)
    total_commits: int = 0
    risk_breakdown: Dict[str, int] = field(default_factory=lambda: {"LOW": 0, "MEDIUM": 0, "HIGH": 0})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "commits": [c.to_dict() for c in self.commits],
            "total_commits": self.total_commits,
            "risk_breakdown": self.risk_breakdown,
        }


# ============================================================================
# Git Delta Extractor
# ============================================================================

class GitDeltaExtractor:
    """
    Executes git diff commands and parses unified diff output into line intervals.
    Handles commit hashes, ranges, staged diffs, untracked/working-tree changes,
    binary files, renames, and deletions.
    """

    HUNK_HEADER_REGEX = re.compile(
        r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@(?:\s+(?P<heading>.*))?$"
    )

    def __init__(self, repo_path: str = ".") -> None:
        self.repo_path = os.path.abspath(repo_path)

    def run_git(self, args: List[str], timeout_sec: int = 30) -> Tuple[int, str, str]:
        """Run a git subcommand safely in repo_path."""
        try:
            proc = subprocess.run(
                ["git"] + args,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="surrogateescape",
                timeout=timeout_sec,
                check=False,
            )
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
            return -1, "", str(e)

    def extract_diff(
        self,
        target: str = "HEAD",
        staged: bool = False,
        working_tree: bool = False,
    ) -> Tuple[Dict[str, List[Tuple[int, int]]], List[DiffHunk]]:
        """
        Extract modified line intervals and DiffHunks.
        
        Args:
            target: Git revision (e.g. 'HEAD', 'HEAD~1', commit hash, 'main..feature')
            staged: If True, inspects staged changes (--staged)
            working_tree: If True, inspects unstaged working tree changes
            
        Returns:
            Tuple of (file_intervals_map, list_of_hunks)
        """
        # Git treats option-like positional arguments as options, even after
        # diff-specific flags. Reject them before any primary or fallback invocation.
        if target and target.startswith("-"):
            return {}, []

        diff_args = ["diff", "--no-ext-diff", "--no-textconv", "-U0"]

        if staged:
            diff_args.append("--staged")
        elif working_tree:
            # Working tree unstaged diff
            pass
        elif target:
            # Check if target is a range or single commit
            if ".." in target or "..." in target:
                diff_args.append(target)
            else:
                # If target is a single commit (like HEAD or hash), check if diffing target~1 target
                # or working tree vs target
                diff_args.extend([f"{target}~1", target])

        code, stdout, stderr = self.run_git(diff_args)

        # Fallback: If single commit diff failed (e.g. root commit without parent), try git show
        if code != 0 and target and not staged and not working_tree:
            code, stdout, stderr = self.run_git(
                ["show", "--no-ext-diff", "--no-textconv", "-U0", "--format=", target]
            )

        # Second fallback: If range or standard diff failed, try plain diff against target
        if code != 0 and target and not staged and not working_tree:
            code, stdout, stderr = self.run_git(
                ["diff", "--no-ext-diff", "--no-textconv", "-U0", target]
            )

        if code == 0 and stdout.strip():
            file_intervals, hunks = self.parse_unified_diff(stdout)
        else:
            file_intervals, hunks = {}, []

        # Include untracked files when inspecting working tree / unstaged changes
        if working_tree or (not staged and not target):
            untracked_code, untracked_out, _ = self.run_git(
                ["ls-files", "-z", "--others", "--exclude-standard"]
            )
            canonical_root = os.path.realpath(self.repo_path)
            if untracked_code == 0 and untracked_out:
                for raw_p in untracked_out.split("\0"):
                    if not raw_p:
                        continue
                    full_p = os.path.realpath(os.path.join(canonical_root, raw_p))
                    try:
                        is_inside = os.path.commonpath([canonical_root, full_p]) == canonical_root
                    except ValueError:
                        is_inside = False
                    if not is_inside or not os.path.isfile(full_p):
                        continue
                    line_count = 1
                    try:
                        with open(full_p, "rb") as f:
                            line_count = max(1, sum(1 for _ in f))
                    except Exception:
                        pass
                    if raw_p not in file_intervals:
                        file_intervals[raw_p] = [(1, line_count)]
                    else:
                        file_intervals[raw_p].append((1, line_count))
                    hunks.append(
                        DiffHunk(
                            file_path=raw_p,
                            old_start=0,
                            old_count=0,
                            new_start=1,
                            new_count=line_count,
                            heading="untracked file",
                            lines_added=line_count,
                            lines_deleted=0,
                            intervals=[(1, line_count)],
                        )
                    )
        return file_intervals, hunks
    @staticmethod
    def unquote_git_path(path_str: str) -> str:
        """Decode a Git C-quoted path if enclosed in double quotes."""
        s = path_str.strip()
        if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
            raw_body = s[1:-1]
            try:
                b = raw_body.encode("latin1").decode("unicode_escape").encode("latin1")
                return b.decode("utf-8", errors="surrogateescape")
            except Exception:
                import re
                def _replace(m: Any) -> str:
                    esc = m.group(1)
                    if esc.isdigit():
                        return chr(int(esc, 8))
                    mapping = {"t": "\t", "n": "\n", "r": "\r", "\\": "\\", '"': '"', "b": "\b", "f": "\f", "a": "\a", "v": "\v"}
                    return str(mapping.get(esc, esc))
                return re.sub(r'\\([0-7]{1,3}|[trn"\\bfa])', _replace, raw_body)
        return s

    def parse_unified_diff(self, diff_text: str) -> Tuple[Dict[str, List[Tuple[int, int]]], List[DiffHunk]]:
        """
        Parse raw git unified diff text into line interval mappings and DiffHunks.
        """
        file_intervals: Dict[str, List[Tuple[int, int]]] = {}
        hunks: List[DiffHunk] = []

        current_file_old: Optional[str] = None
        current_file_new: Optional[str] = None
        current_is_binary = False

        for line in diff_text.splitlines():
            # Handle diff header
            if line.startswith("diff --git "):
                current_is_binary = False
                rest = line[11:].strip()
                if rest.startswith('"'):
                    import re
                    qmatches = re.findall(r'"(?:[^"\\]|\\.)*"', rest)
                    if len(qmatches) >= 2:
                        a_path = self.unquote_git_path(qmatches[0])
                        b_path = self.unquote_git_path(qmatches[1])
                        current_file_old = a_path[2:] if a_path.startswith("a/") else a_path
                        current_file_new = b_path[2:] if b_path.startswith("b/") else b_path
                else:
                    parts = rest.split(" ")
                    if len(parts) >= 2:
                        a_path = parts[0]
                        b_path = parts[1]
                        current_file_old = a_path[2:] if a_path.startswith("a/") else a_path
                        current_file_new = b_path[2:] if b_path.startswith("b/") else b_path
                continue

            if line.startswith("Binary files "):
                # Only the literal 'Binary files … differ' header marks a
                # binary file — an 'in line' check false-positives on ANY
                # content line mentioning "differ" (logs, docs) and then
                # skips every remaining hunk of that file.
                current_is_binary = True
                continue

            if line.startswith("--- "):
                path_part = self.unquote_git_path(line[4:])
                if path_part == "/dev/null":
                    current_file_old = None
                elif path_part.startswith("a/"):
                    current_file_old = path_part[2:]
                else:
                    current_file_old = path_part
                continue

            if line.startswith("+++ "):
                path_part = self.unquote_git_path(line[4:])
                if path_part == "/dev/null":
                    current_file_new = None
                elif path_part.startswith("b/"):
                    current_file_new = path_part[2:]
                else:
                    current_file_new = path_part
                continue
            if current_is_binary:
                continue

            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            if line.startswith("@@"):
                match = self.HUNK_HEADER_REGEX.match(line)
                if not match:
                    continue

                old_start = int(match.group("old_start"))
                old_count_str = match.group("old_count")
                old_count = int(old_count_str) if old_count_str is not None else 1

                new_start = int(match.group("new_start"))
                new_count_str = match.group("new_count")
                new_count = int(new_count_str) if new_count_str is not None else 1

                heading = (match.group("heading") or "").strip()

                active_file = current_file_new or current_file_old
                if not active_file:
                    continue

                # Standardize path separators
                norm_file = active_file.replace("\\", "/") if os.sep == "\\" else active_file
                if norm_file.startswith("./"):
                    norm_file = norm_file[2:]
                # Calculate modified interval. The AST coordinate mapper
                # intersects intervals against the PRE-change graph (old
                # line spans), so a deletion-only hunk must use its OLD-side
                # coordinates. Using new_start here previously mapped a
                # whole-file deletion (`@@ -1,N +0,0 @@`) to the empty
                # interval (0, 0), hiding every deleted symbol from the
                # blast radius (file deletion reported zero impact).
                if new_count > 0:
                    interval = (new_start, new_start + new_count - 1)
                else:
                    interval = (old_start, max(old_start, old_start + old_count - 1))

                hunk = DiffHunk(
                    file_path=norm_file,
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    heading=heading,
                    lines_added=new_count if new_count > 0 else 0,
                    lines_deleted=old_count if old_count > 0 else 0,
                    intervals=[interval],
                )
                hunks.append(hunk)

                if norm_file not in file_intervals:
                    file_intervals[norm_file] = []
                file_intervals[norm_file].append(interval)

        return file_intervals, hunks


# ============================================================================
# AST Coordinate Mapper
# ============================================================================

class ASTCoordinateMapper:
    """
    Maps modified line intervals (start, end) to `graph_nodes` in `.sot/sot.db`
    using line interval overlap intersection logic.
    """

    def __init__(self, db: Any) -> None:
        self.db = db
        self.conn = getattr(db, "conn", db)

    def _normalize_path(self, path: str) -> str:
        """Normalize file paths for consistent SQLite matching."""
        norm = path.replace("\\", "/") if os.sep == "\\" else path
        if norm.startswith("./"):
            norm = norm[2:]
        return norm

    def map_intervals_to_nodes(
        self,
        file_intervals: Dict[str, List[Tuple[int, int]]],
        repo_path: Optional[str] = None,
    ) -> List[DirectNodeChange]:
        """
        Query graph_nodes for all symbols intersecting the changed line intervals.
        """
        direct_nodes: List[DirectNodeChange] = []
        seen_node_ids: Set[str] = set()

        for file_path, intervals in file_intervals.items():
            if not intervals:
                continue

            norm_path = self._normalize_path(file_path)
            norm_fwd = norm_path
            norm_back = norm_path.replace("/", "\\")
            like_fwd = "%/" + norm_fwd.lstrip("/")
            like_back = "%\\" + norm_back.lstrip("\\")

            # Query all candidate nodes for this file that have line coordinates
            try:
                rows = self.conn.execute(
                    "SELECT id, path, kind, symbol, fqn, label, line_start, line_end "
                    "FROM graph_nodes "
                    "WHERE (path = ? OR path = ? OR path LIKE ? OR path LIKE ?) "
                    "AND line_start IS NOT NULL AND line_end IS NOT NULL "
                    "ORDER BY (line_end - line_start) ASC",
                    (norm_fwd, norm_back, like_fwd, like_back),
                ).fetchall()
            except Exception:
                return []
            for row in rows:
                node_id = row[0]
                n_path = row[1]
                kind = row[2]
                symbol = row[3] or ""
                fqn = row[4] or ""
                label = row[5] or ""
                line_start = int(row[6]) if row[6] is not None else 1
                line_end = int(row[7]) if row[7] is not None else 1

                if node_id in seen_node_ids:
                    continue

                # Check line intersection with any hunk interval:
                # Overlap condition: node.line_start <= interval.end AND node.line_end >= interval.start
                intersected: List[Tuple[int, int]] = []
                for start, end in intervals:
                    if line_start <= end and line_end >= start:
                        intersected.append((start, end))

                if intersected:
                    seen_node_ids.add(node_id)
                    direct_nodes.append(
                        DirectNodeChange(
                            id=node_id,
                            path=n_path,
                            kind=kind,
                            symbol=symbol,
                            fqn=fqn,
                            label=label,
                            line_start=line_start,
                            line_end=line_end,
                            change_type="modified",
                            intersected_lines=intersected,
                        )
                    )

        # Sort direct nodes by path and line_start
        direct_nodes.sort(key=lambda n: (n.path, n.line_start))
        return direct_nodes


# ============================================================================
# Commit History Engine
# ============================================================================

class CommitHistoryEngine:
    """
    Analyzes recent git commit log, calculates file churn, maps touched symbols,
    and computes heuristic commit risk (LOW / MEDIUM / HIGH).
    """

    CRITICAL_PATTERNS = [
        re.compile(p, re.IGNORECASE)
        for p in [
            r"migration",
            r"schema",
            r"auth",
            r"security",
            r"crypto",
            r"secret",
            r"payment",
            r"billing",
            r"lock",
            r"permission",
            r"database",
            r"alembic",
            r"flyway",
        ]
    ]

    CONFIG_FILES = {
        "package.json",
        "cargo.toml",
        "pyproject.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "dockerfile",
        "docker-compose.yml",
        "tsconfig.json",
    }

    def __init__(self, repo_path: str = ".") -> None:
        self.repo_path = os.path.abspath(repo_path)
        self.extractor = GitDeltaExtractor(self.repo_path)

    def analyze_history(
        self,
        count: int = 10,
        author: Optional[str] = None,
        since: Optional[str] = None,
        db: Optional[Any] = None,
        with_impact: bool = True,
    ) -> CommitHistoryResult:
        """
        Fetch and evaluate the last `count` commits.
        """
        # Format: Hash <0x1f> ShortHash <0x1f> Author <0x1f> Date <0x1f> Subject
        delimiter = "%x1f"
        git_fmt = f"%H{delimiter}%h{delimiter}%an{delimiter}%ad{delimiter}%s"
        git_args = ["log", f"-n{count}", f"--pretty=format:{git_fmt}", "--date=iso", "--numstat"]
        if author:
            git_args.append(f"--author={author}")
        if since:
            git_args.append(f"--since={since}")
        code, stdout, stderr = self.extractor.run_git(git_args)
        if code != 0 or not stdout.strip():
            return CommitHistoryResult(commits=[], total_commits=0)

        raw_commits = self._parse_log_numstat(stdout, delimiter="\x1f")
        commit_summaries: List[CommitSummary] = []
        risk_breakdown = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}

        conn = getattr(db, "conn", db) if db else None

        for c in raw_commits:
            # Map touched symbols if DB connection provided and impact analysis enabled
            touched_symbols = []
            if with_impact and conn and c["files"]:
                touched_symbols = self._find_touched_symbols(conn, c["files"])
            risk_level, reasons = self._calculate_commit_risk(
                files=c["files"],
                insertions=c["insertions"],
                deletions=c["deletions"],
                message=c["message"],
                touched_symbols=touched_symbols,
                conn=conn,
            )

            risk_breakdown[risk_level] = risk_breakdown.get(risk_level, 0) + 1

            summary = CommitSummary(
                commit_hash=c["hash"],
                short_hash=c["short_hash"],
                author=c["author"],
                date=c["date"],
                message=c["message"],
                files_changed=c["files"],
                insertions=c["insertions"],
                deletions=c["deletions"],
                touched_symbols=touched_symbols,
                risk_level=risk_level,
                risk_reasons=reasons,
            )
            commit_summaries.append(summary)

        return CommitHistoryResult(
            commits=commit_summaries,
            total_commits=len(commit_summaries),
            risk_breakdown=risk_breakdown,
        )

    def _parse_log_numstat(self, text: str, delimiter: str = "\x1f") -> List[Dict[str, Any]]:
        """Parse git log output containing format header followed by numstat rows."""
        commits: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None

        for line in text.splitlines():
            line_str = line.strip()
            if not line_str:
                continue

            if delimiter in line:
                # Commit header
                if current:
                    commits.append(current)
                parts = line.split(delimiter)
                current = {
                    "hash": parts[0] if len(parts) > 0 else "",
                    "short_hash": parts[1] if len(parts) > 1 else "",
                    "author": parts[2] if len(parts) > 2 else "",
                    "date": parts[3] if len(parts) > 3 else "",
                    "message": parts[4] if len(parts) > 4 else "",
                    "files": [],
                    "insertions": 0,
                    "deletions": 0,
                }
            elif current:
                # Numstat row: <ins> \t <del> \t <file>
                tokens = line.split("\t")
                if len(tokens) >= 3:
                    ins_str, del_str, file_path = tokens[0].strip(), tokens[1].strip(), tokens[2].strip()
                    ins = int(ins_str) if ins_str.isdigit() else 0
                    dels = int(del_str) if del_str.isdigit() else 0
                    current["insertions"] += ins
                    current["deletions"] += dels
                    norm_path = file_path.replace("\\", "/") if os.sep == "\\" else file_path
                    if norm_path.startswith("./"):
                        norm_path = norm_path[2:]
                    current["files"].append(norm_path)

        if current:
            commits.append(current)

        return commits

    def _find_touched_symbols(self, conn: sqlite3.Connection, files: List[str]) -> List[str]:
        """Find prominent symbols defined in the modified files."""
        symbols: List[str] = []
        seen = set()
        for f in files:
            norm = f.replace("\\", "/")
            if norm.startswith("./"):
                norm = norm[2:]
            norm_fwd = norm
            norm_back = norm.replace("/", "\\")
            like_fwd = "%/" + norm_fwd.lstrip("/")
            like_back = "%\\" + norm_back.lstrip("\\")
            try:
                rows = conn.execute(
                    "SELECT symbol FROM graph_nodes "
                    "WHERE (path = ? OR path = ? OR path LIKE ? OR path LIKE ?) AND symbol != '' AND kind != 'file' "
                    "LIMIT 5",
                    (norm_fwd, norm_back, like_fwd, like_back),
                ).fetchall()
                for r in rows:
                    sym = r[0]
                    if sym and sym not in seen:
                        seen.add(sym)
                        symbols.append(sym)
            except Exception:
                continue
        return symbols

    def _calculate_commit_risk(
        self,
        files: List[str],
        insertions: int,
        deletions: int,
        message: str,
        touched_symbols: List[str],
        conn: Optional[sqlite3.Connection] = None,
    ) -> Tuple[str, List[str]]:
        """Calculate heuristic risk score and explanations."""
        score = 0
        reasons: List[str] = []

        total_churn = insertions + deletions

        # 1. File count churn
        file_count = len(files)
        if file_count > 15:
            score += 4
            reasons.append(f"High file blast radius ({file_count} files changed)")
        elif file_count > 5:
            score += 2
            reasons.append(f"Multi-file modification ({file_count} files changed)")

        # 2. Line churn
        if total_churn > 800:
            score += 4
            reasons.append(f"Massive code churn ({total_churn} lines modified)")
        elif total_churn > 250:
            score += 2
            reasons.append(f"Moderate code churn ({total_churn} lines modified)")

        # 3. Critical domain paths
        critical_hits = []
        for f in files:
            lower_f = f.lower()
            for pat in self.CRITICAL_PATTERNS:
                if pat.search(lower_f):
                    critical_hits.append(f)
                    break
        if critical_hits:
            score += 4
            reasons.append(f"Touches critical security/database/schema paths ({len(critical_hits)} files)")

        # 4. Root config churn
        config_hits = [f for f in files if Path(f).name.lower() in self.CONFIG_FILES]
        if config_hits:
            score += 2
            reasons.append(f"Touches build/dependency manifest ({', '.join(config_hits[:2])})")

        # 5. High in-degree callers on touched symbols
        if conn and touched_symbols:
            try:
                for sym in touched_symbols[:3]:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM graph_edges e "
                        "JOIN graph_nodes n ON e.dst = n.id "
                        "WHERE n.symbol = ? AND e.relation != 'defines'",
                        (sym,),
                    ).fetchone()
                    if row and row[0] >= 5:
                        score += 3
                        reasons.append(f"Touches high-in-degree core symbol '{sym}' ({row[0]} incoming callers)")
                        break
            except Exception:
                pass

        if score >= 5:
            return "HIGH", reasons
        elif score >= 2:
            return "MEDIUM", reasons
        else:
            if not reasons:
                reasons.append("Small localized change with low churn")
            return "LOW", reasons


# ============================================================================
# Diff Impact Engine (Core Engine)
# ============================================================================

class DiffImpactEngine:
    """
    Core engine orchestrating git delta extraction, AST coordinate mapping,
    reverse call-graph traversal (in-degree blast radius), API cross-binding matching,
    and affected test discovery.
    """

    TEST_PATTERNS = [
        re.compile(r"(^|/)(?:tests?|__tests?|spec)/", re.IGNORECASE),
        re.compile(r"(?:_test|\.test|\.spec|test_)[a-zA-Z0-9_]*\.[a-zA-Z0-9]+$", re.IGNORECASE),
        re.compile(r"Test[a-zA-Z0-9_]*\.(?:java|kt|scala|php|cs)$"),
    ]

    def __init__(self, db: Any, repo_path: str = ".") -> None:
        self.db = db
        self.conn = getattr(db, "conn", db)
        self.repo_path = os.path.abspath(repo_path)
        self.extractor = GitDeltaExtractor(self.repo_path)
        self.mapper = ASTCoordinateMapper(self.db)

    def analyze_diff_impact(
        self,
        target: str = "HEAD",
        depth: int = 2,
        staged: bool = False,
        working_tree: bool = False,
    ) -> DiffImpactResult:
        """
        Execute the 4-step impact analysis pipeline.
        
        Args:
            target: Git revision / range (e.g. 'HEAD~1', 'main..feat', 'a1b2c3d')
            depth: Reverse call-graph exploration depth (default 2)
            staged: If True, inspects staged changes
            working_tree: If True, inspects working tree changes
        """
        start_time = time.monotonic()

        # Step 1: Git Delta Extraction
        file_intervals, hunks = self.extractor.extract_diff(
            target=target,
            staged=staged,
            working_tree=working_tree,
        )
        changed_files = sorted(list(file_intervals.keys()))

        # Step 2: AST Coordinate Mapping
        direct_nodes = self.mapper.map_intervals_to_nodes(file_intervals, repo_path=self.repo_path)

        # Step 3: Reverse Call-Graph Traversal (In-Degree Callers)
        caller_impacts = self._traverse_reverse_call_graph(direct_nodes, max_depth=depth)

        # Step 4: API Cross-Bindings & Impacted Tests
        api_impacts = self._match_api_endpoints(direct_nodes, caller_impacts, changed_files)
        test_impacts = self._discover_impacted_tests(direct_nodes, caller_impacts, changed_files)

        elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)

        # Compute Summary & Risk
        summary = self._compute_summary(
            changed_files=changed_files,
            hunks=hunks,
            direct_nodes=direct_nodes,
            caller_impacts=caller_impacts,
            api_impacts=api_impacts,
            test_impacts=test_impacts,
            elapsed_ms=elapsed_ms,
        )

        effective_target = (
            "--staged" if staged
            else "--working-tree" if working_tree
            else target
        )

        return DiffImpactResult(
            target=effective_target,
            repo_path=self.repo_path,
            changed_files=changed_files,
            hunks=hunks,
            direct_nodes=direct_nodes,
            caller_impacts=caller_impacts,
            api_impacts=api_impacts,
            test_impacts=test_impacts,
            summary=summary,
        )

    def _traverse_reverse_call_graph(
        self,
        direct_nodes: List[DirectNodeChange],
        max_depth: int = 2,
    ) -> List[CallerImpact]:
        """
        Perform BFS upward traversal on graph_edges to locate all callers, implementers,
        and subclasses up to `max_depth` hops.
        """
        if not direct_nodes or max_depth <= 0:
            return []

        callers: List[CallerImpact] = []
        visited_nodes: Set[str] = {node.id for node in direct_nodes}

        # Queue contains: (current_node_id, current_node_symbol, current_depth)
        queue: List[Tuple[str, str, int]] = [(node.id, node.symbol, 1) for node in direct_nodes]

        allowed_relations = ("calls", "extends", "implements", "uses", "imports")
        rel_placeholders = ",".join("?" * len(allowed_relations))

        while queue:
            curr_id, curr_symbol, curr_depth = queue.pop(0)
            if curr_depth > max_depth:
                continue

            # Query inward edges: who calls/extends curr_id?
            query = (
                f"SELECT e.src, e.relation, n.id, n.path, n.kind, n.symbol, n.fqn, n.label, n.line_start "
                f"FROM graph_edges e "
                f"JOIN graph_nodes n ON e.src = n.id "
                f"WHERE e.dst = ? AND e.relation IN ({rel_placeholders}) "
                f"ORDER BY n.path, n.line_start"
            )
            params = [curr_id] + list(allowed_relations)

            try:
                rows = self.conn.execute(query, params).fetchall()
            except Exception:
                break
            for row in rows:
                src_id = row[0]
                relation = row[1]
                n_id = row[2]
                n_path = row[3]
                n_kind = row[4]
                n_symbol = row[5] or ""
                n_fqn = row[6] or ""
                n_label = row[7] or ""
                n_line_start = int(row[8]) if row[8] is not None else 1

                if src_id not in visited_nodes:
                    visited_nodes.add(src_id)
                    caller = CallerImpact(
                        id=n_id,
                        path=n_path,
                        kind=n_kind,
                        symbol=n_symbol,
                        fqn=n_fqn,
                        label=n_label,
                        line_start=n_line_start,
                        depth=curr_depth,
                        via_relation=relation,
                        callee_id=curr_id,
                        callee_symbol=curr_symbol,
                    )
                    callers.append(caller)

                    # Enqueue for next depth hop
                    if curr_depth < max_depth:
                        queue.append((src_id, n_symbol, curr_depth + 1))

        # Sort callers by depth, path, line_start
        callers.sort(key=lambda c: (c.depth, c.path, c.line_start))
        return callers

    def _match_api_endpoints(
        self,
        direct_nodes: List[DirectNodeChange],
        caller_impacts: List[CallerImpact],
        changed_files: List[str],
    ) -> List[ApiImpact]:
        """
        Cross-reference modified symbols and callers with `api_cross_bindings` table.
        """
        api_impacts: List[ApiImpact] = []
        seen_api_ids: Set[str] = set()

        direct_symbols = {n.symbol for n in direct_nodes if n.symbol}
        caller_symbols = {c.symbol for c in caller_impacts if c.symbol}

        # Check if table exists
        has_table = self.conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='api_cross_bindings'"
        ).fetchone()[0] > 0

        if not has_table:
            return []

        # 1. Match by Direct Node Symbols
        for sym in direct_symbols:
            rows = self.conn.execute(
                "SELECT id, fe_caller_symbol, http_method, normalized_uri, be_controller_symbol, fe_file, be_file "
                "FROM api_cross_bindings "
                "WHERE fe_caller_symbol = ? OR be_controller_symbol = ?",
                (sym, sym),
            ).fetchall()
            for r in rows:
                if r[0] not in seen_api_ids:
                    seen_api_ids.add(r[0])
                    api_impacts.append(
                        ApiImpact(
                            id=r[0],
                            fe_caller_symbol=r[1],
                            http_method=r[2],
                            normalized_uri=r[3],
                            be_controller_symbol=r[4] or "",
                            fe_file=r[5],
                            be_file=r[6],
                            impact_source="direct_node",
                        )
                    )

        # 2. Match by Caller Symbols
        for sym in caller_symbols:
            rows = self.conn.execute(
                "SELECT id, fe_caller_symbol, http_method, normalized_uri, be_controller_symbol, fe_file, be_file "
                "FROM api_cross_bindings "
                "WHERE fe_caller_symbol = ? OR be_controller_symbol = ?",
                (sym, sym),
            ).fetchall()
            for r in rows:
                if r[0] not in seen_api_ids:
                    seen_api_ids.add(r[0])
                    api_impacts.append(
                        ApiImpact(
                            id=r[0],
                            fe_caller_symbol=r[1],
                            http_method=r[2],
                            normalized_uri=r[3],
                            be_controller_symbol=r[4] or "",
                            fe_file=r[5],
                            be_file=r[6],
                            impact_source="caller_node",
                        )
                    )

        # 3. Match by Changed File Paths
        for f in changed_files:
            norm_f = f.replace("\\", "/")
            if norm_f.startswith("./"):
                norm_f = norm_f[2:]
            norm_fwd = norm_f
            norm_back = norm_f.replace("/", "\\")
            like_fwd = "%/" + norm_fwd.lstrip("/")
            like_back = "%\\" + norm_back.lstrip("\\")
            rows = self.conn.execute(
                "SELECT id, fe_caller_symbol, http_method, normalized_uri, be_controller_symbol, fe_file, be_file "
                "FROM api_cross_bindings "
                "WHERE fe_file = ? OR fe_file = ? OR fe_file LIKE ? OR fe_file LIKE ? "
                "OR be_file = ? OR be_file = ? OR be_file LIKE ? OR be_file LIKE ?",
                (norm_fwd, norm_back, like_fwd, like_back, norm_fwd, norm_back, like_fwd, like_back),
            ).fetchall()
            for r in rows:
                if r[0] not in seen_api_ids:
                    seen_api_ids.add(r[0])
                    api_impacts.append(
                        ApiImpact(
                            id=r[0],
                            fe_caller_symbol=r[1],
                            http_method=r[2],
                            normalized_uri=r[3],
                            be_controller_symbol=r[4] or "",
                            fe_file=r[5],
                            be_file=r[6],
                            impact_source="file_match",
                        )
                    )

        return api_impacts

    def _discover_impacted_tests(
        self,
        direct_nodes: List[DirectNodeChange],
        caller_impacts: List[CallerImpact],
        changed_files: List[str],
    ) -> List[TestImpact]:
        """
        Identify test files and test functions that exercise the changed symbols.
        """
        test_impacts: List[TestImpact] = []
        seen_test_keys: Set[str] = set()

        # 1. Directly modified test files
        for f in changed_files:
            if self._is_test_path(f):
                key = f"file:{f}"
                if key not in seen_test_keys:
                    seen_test_keys.add(key)
                    test_impacts.append(
                        TestImpact(
                            id=f"test:{f}",
                            path=f,
                            symbol="",
                            kind="file",
                            impact_reason="direct_test_file",
                        )
                    )

        # 2. Callers residing in test files
        for c in caller_impacts:
            if self._is_test_path(c.path) or self._is_test_symbol(c.symbol):
                key = f"caller:{c.id}"
                if key not in seen_test_keys:
                    seen_test_keys.add(key)
                    test_impacts.append(
                        TestImpact(
                            id=c.id,
                            path=c.path,
                            symbol=c.symbol,
                            kind=c.kind,
                            impact_reason="calls_modified_node",
                            target_symbol=c.callee_symbol,
                        )
                    )

        # 3. Test functions in DB referencing direct symbols
        for d in direct_nodes:
            if not d.symbol:
                continue
            try:
                rows = self.conn.execute(
                    "SELECT n.id, n.path, n.symbol, n.kind FROM graph_edges e "
                    "JOIN graph_nodes n ON e.src = n.id "
                    "WHERE e.dst = ?",
                    (d.id,),
                ).fetchall()
                rows = [r for r in rows
                        if self._is_test_path(r[1])
                        or self._is_test_symbol(r[2])]
                for r in rows:
                    key = f"db_edge:{r[0]}"
                    if key not in seen_test_keys:
                        seen_test_keys.add(key)
                        test_impacts.append(
                            TestImpact(
                                id=r[0],
                                path=r[1],
                                symbol=r[2],
                                kind=r[3],
                                impact_reason="calls_modified_node",
                                target_symbol=d.symbol,
                            )
                        )
            except Exception:
                pass

        return test_impacts

    def _is_test_path(self, path: str) -> bool:
        """Check if a file path belongs to test directories or test naming conventions."""
        norm = path.replace("\\", "/")
        return any(pat.search(norm) for pat in self.TEST_PATTERNS)

    @staticmethod
    def _is_test_symbol(symbol: str | None) -> bool:
        """Test-shaped symbol name.

        Leading ``test``/``Test`` covers pytest, Go and JUnit4 conventions;
        case-sensitive trailing ``Test``/``Tests``/``IT``/``Spec`` recovers
        JUnit5 suites, Maven failsafe integration tests and RSpec-style
        specs, which the old ``startswith("test")``-only check silently
        dropped from affected-test discovery.
        """
        if not symbol:
            return False
        return symbol.lower().startswith("test") or symbol.endswith(
            ("Test", "Tests", "IT", "Spec")
        )

    def _compute_summary(
        self,
        changed_files: List[str],
        hunks: List[DiffHunk],
        direct_nodes: List[DirectNodeChange],
        caller_impacts: List[CallerImpact],
        api_impacts: List[ApiImpact],
        test_impacts: List[TestImpact],
        elapsed_ms: float,
    ) -> Dict[str, Any]:
        """Compute aggregate metrics and heuristic risk score."""
        total_files = len(changed_files)
        total_nodes = len(direct_nodes)
        total_callers = len(caller_impacts)
        total_apis = len(api_impacts)
        total_tests = len(test_impacts)

        # Calculate Risk Score (0 - 100)
        risk_score = 0
        risk_score += min(total_files * 5, 25)
        risk_score += min(total_nodes * 8, 30)
        risk_score += min(total_callers * 4, 25)
        risk_score += min(total_apis * 10, 20)

        if risk_score >= 60 or total_apis >= 3 or total_callers >= 10:
            risk_level = "HIGH"
        elif risk_score >= 25 or total_callers >= 3 or total_apis >= 1:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        return {
            "total_changed_files": total_files,
            "total_hunks": len(hunks),
            "total_direct_nodes": total_nodes,
            "total_callers": total_callers,
            "total_apis": total_apis,
            "total_tests": total_tests,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "execution_time_ms": elapsed_ms,
        }


# ============================================================================
# Standalone Convenience Functions
# ============================================================================

def analyze_diff_impact(
    db: Any,
    repo_path: str = ".",
    target: str = "HEAD",
    depth: int = 2,
    staged: bool = False,
    working_tree: bool = False,
) -> DiffImpactResult:
    """Analyze blast radius and impact for a git target or working tree changes."""
    engine = DiffImpactEngine(db, repo_path=repo_path)
    return engine.analyze_diff_impact(
        target=target,
        depth=depth,
        staged=staged,
        working_tree=working_tree,
    )


def analyze_commit_history(
    repo_path: str = ".",
    count: int = 10,
    author: Optional[str] = None,
    since: Optional[str] = None,
    db: Optional[Any] = None,
    with_impact: bool = True,
) -> CommitHistoryResult:
    """Extract and analyze risk for recent git commit history."""
    engine = CommitHistoryEngine(repo_path=repo_path)
    return engine.analyze_history(
        count=count,
        author=author,
        since=since,
        db=db,
        with_impact=with_impact,
    )


# ============================================================================
# Report Formatters (Markdown & JSON)
# ============================================================================

def _sanitize_cell(text: Any) -> str:
    """Sanitize string for Markdown table cell (escape pipes, remove newlines)."""
    if text is None:
        return ""
    return str(text).replace("|", "\\|").replace("\n", " ").replace("\r", "")


def format_diff_impact_markdown(result: DiffImpactResult) -> str:
    """Render DiffImpactResult into an informative Markdown report."""
    summary = result.summary
    risk_level = summary.get("risk_level", "LOW")
    risk_icon = "🔴" if risk_level == "HIGH" else "🟡" if risk_level == "MEDIUM" else "🟢"

    lines: List[str] = [
        "# SOT-Graph Diff Impact Analysis Report",
        "",
        f"**Target:** `{_sanitize_cell(result.target)}` | **Risk Level:** {risk_icon} **{risk_level}** (Score: {summary.get('risk_score', 0)}/100) | **Execution Time:** {summary.get('execution_time_ms', 0)}ms",
        "",
        "## 📊 Summary Metrics",
        "",
        "| Metric | Count |",
        "| :--- | :--- |",
        f"| Changed Files | **{summary.get('total_changed_files', 0)}** |",
        f"| Diff Hunks | **{summary.get('total_hunks', 0)}** |",
        f"| Directly Modified Symbols | **{summary.get('total_direct_nodes', 0)}** |",
        f"| Blast Radius Callers (In-Degree) | **{summary.get('total_callers', 0)}** |",
        f"| Impacted API Endpoints | **{summary.get('total_apis', 0)}** |",
        f"| Tests to Re-Run | **{summary.get('total_tests', 0)}** |",
        "",
    ]

    # Direct Nodes Table
    lines.append("## 🎯 1. Directly Modified AST Symbols")
    lines.append("")
    if result.direct_nodes:
        lines.append("| Symbol | Kind | File | Lines | Change Type |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for n in result.direct_nodes:
            sym = _sanitize_cell(n.symbol or n.label)
            kind = _sanitize_cell(n.kind)
            path = _sanitize_cell(n.path)
            chg = _sanitize_cell(n.change_type)
            lines.append(f"| `{sym}` | `{kind}` | `{path}` | L{n.line_start}-L{n.line_end} | **{chg}** |")
    else:
        lines.append("_No matching AST nodes in knowledge graph for modified line intervals._")
    lines.append("")

    # Callers Table
    lines.append("## 💥 2. Blast Radius: Upstream Inward Callers")
    lines.append("")
    if result.caller_impacts:
        lines.append("| Depth | Caller Symbol | Kind | File : Line | Relation | Target Symbol |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for c in result.caller_impacts:
            sym = _sanitize_cell(c.symbol or c.label)
            kind = _sanitize_cell(c.kind)
            loc = _sanitize_cell(f"{c.path}:{c.line_start}")
            rel = _sanitize_cell(c.via_relation)
            callee = _sanitize_cell(c.callee_symbol)
            lines.append(f"| Hop {c.depth} | `{sym}` | `{kind}` | `{loc}` | `{rel}` | `{callee}` |")
    else:
        lines.append("_Zero inward caller dependencies detected (low ripple effect)._")
    lines.append("")

    # API Endpoints Table
    lines.append("## 🌐 3. Affected Cross-Stack API Endpoints")
    lines.append("")
    if result.api_impacts:
        lines.append("| Method | Normalized URI | Frontend Caller | Backend Controller | Impact Source |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for a in result.api_impacts:
            method = _sanitize_cell(a.http_method)
            uri = _sanitize_cell(a.normalized_uri)
            fe = _sanitize_cell(a.fe_caller_symbol)
            be = _sanitize_cell(a.be_controller_symbol)
            src = _sanitize_cell(a.impact_source)
            lines.append(f"| **{method}** | `{uri}` | `{fe}` | `{be}` | `{src}` |")
    else:
        lines.append("_No direct or indirect API contract bindings affected._")
    lines.append("")

    # Impacted Tests Table
    lines.append("## 🧪 4. Recommended Test Coverage Verification")
    lines.append("")
    if result.test_impacts:
        lines.append("| Test Target | Kind | File | Reason |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for t in result.test_impacts:
            target_desc = f" -> `{_sanitize_cell(t.target_symbol)}`" if t.target_symbol else ""
            target_str = _sanitize_cell(t.symbol or t.path)
            kind = _sanitize_cell(t.kind)
            path = _sanitize_cell(t.path)
            reason = _sanitize_cell(t.impact_reason)
            lines.append(f"| `{target_str}` | `{kind}` | `{path}` | `{reason}`{target_desc} |")
    else:
        lines.append("_No existing test suites mapped directly to modified symbols. Consider adding new test coverage._")
    lines.append("")

    return "\n".join(lines)


def format_diff_impact_json(result: DiffImpactResult, indent: int = 2) -> str:
    """Serialize DiffImpactResult into formatted JSON."""
    return json.dumps(result.to_dict(), indent=indent, ensure_ascii=False)


# --- PR-safe GitHub comment renderer -----------------------------------------

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

#: HTML comment marker anchoring idempotent PR-comment updates (the GitHub
#: Action edits the previous comment carrying this marker instead of spamming).
GITHUB_COMMENT_MARKER = "<!-- sot-diff-impact -->"


def _strip_ansi(text: Any) -> str:
    """Remove ANSI escape sequences; GitHub comments render them as noise."""
    if text is None:
        return ""
    return _ANSI_ESCAPE_RE.sub("", str(text))


def _repo_relative(raw: Any, repo_root: Optional[str]) -> str:
    """Cite a path repo-relative (POSIX separators) or verbatim when outside.

    Constraint: PR comments must never leak runner-absolute local paths.
    """
    text = _strip_ansi(raw)
    if not text or not repo_root:
        return text
    root_abs = os.path.abspath(repo_root)
    candidate = text if os.path.isabs(text) else os.path.join(root_abs, text)
    candidate_abs = os.path.normpath(os.path.abspath(candidate))
    try:
        rel = os.path.relpath(candidate_abs, root_abs)
    except ValueError:
        return text
    if rel == ".." or rel.startswith(".." + os.sep):
        return text
    return rel.replace(os.sep, "/")


def _details_block(title: str, body_lines: List[str]) -> List[str]:
    """One collapsed <details> section; blank lines keep the inner Markdown live."""
    return ["<details>", f"<summary><strong>{title}</strong></summary>", "", *body_lines, "", "</details>", ""]


def format_diff_impact_github(result: DiffImpactResult, repo_root: Optional[str] = None) -> str:
    """Render DiffImpactResult as a PR-comment-optimized Markdown body.

    Constraints (R4): top-line risk verdict (emoji + score), collapsed
    <details> sections for blast radius / callers / affected tests, zero
    ANSI escape codes, repo-relative paths only, and deterministic
    ordering of every row. Reuses the engine's computed data — no impact
    is recomputed here.
    """
    summary = result.summary
    risk_level = _strip_ansi(summary.get("risk_level", "LOW")).upper() or "LOW"
    risk_icon = "🔴" if risk_level == "HIGH" else "🟡" if risk_level == "MEDIUM" else "🟢"
    target = _strip_ansi(result.target)
    changed = sorted({_repo_relative(f, repo_root) for f in (result.changed_files or [])})

    lines: List[str] = [GITHUB_COMMENT_MARKER, ""]
    lines.append(
        f"## {risk_icon} SOT-Graph Diff Impact: **{risk_level}** "
        f"(risk score {summary.get('risk_score', 0)}/100)"
    )
    lines.append("")
    lines.append(
        f"**Target:** `{target}` · "
        f"{summary.get('total_changed_files', 0)} changed files · "
        f"{summary.get('total_direct_nodes', 0)} modified symbols · "
        f"{summary.get('total_callers', 0)} callers · "
        f"{summary.get('total_tests', 0)} tests to re-run"
    )
    lines.append("")

    if changed:
        lines.append("**Changed files:** " + " · ".join(f"`{c}`" for c in changed))
        lines.append("")

    # 1. Directly modified symbols.
    direct_nodes = sorted(
        result.direct_nodes or [],
        key=lambda n: (_repo_relative(n.path, repo_root), _strip_ansi(n.symbol or n.label)),
    )
    direct_lines: List[str] = []
    if direct_nodes:
        direct_lines.append("| Symbol | Kind | File | Lines | Change |")
        direct_lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for n in direct_nodes:
            sym = _strip_ansi(n.symbol or n.label).replace("|", "\\|")
            path = _repo_relative(n.path, repo_root).replace("|", "\\|")
            kind = _strip_ansi(n.kind).replace("|", "\\|")
            chg = _strip_ansi(n.change_type).replace("|", "\\|")
            direct_lines.append(f"| `{sym}` | `{kind}` | `{path}` | L{n.line_start}-L{n.line_end} | **{chg}** |")
    else:
        direct_lines.append("_No matching AST nodes in the knowledge graph for the modified line intervals._")
    lines.extend(_details_block(
        f"🎯 Directly modified symbols ({len(direct_nodes)})", direct_lines,
    ))

    # 2. Blast radius: upstream inward callers.
    callers = sorted(
        result.caller_impacts or [],
        key=lambda c: (c.depth, _repo_relative(c.path, repo_root), _strip_ansi(c.symbol or c.label)),
    )
    caller_lines: List[str] = []
    if callers:
        caller_lines.append("| Hop | Caller | File : Line | Relation | Callee |")
        caller_lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for c in callers:
            sym = _strip_ansi(c.symbol or c.label).replace("|", "\\|")
            path = _repo_relative(c.path, repo_root).replace("|", "\\|")
            rel = _strip_ansi(c.via_relation).replace("|", "\\|")
            callee = _strip_ansi(c.callee_symbol).replace("|", "\\|")
            caller_lines.append(f"| {c.depth} | `{sym}` | `{path}:{c.line_start}` | `{rel}` | `{callee}` |")
    else:
        caller_lines.append("_Zero inward caller dependencies detected (low ripple effect)._")
    lines.extend(_details_block(
        f"💥 Blast radius — upstream callers ({len(callers)})", caller_lines,
    ))

    # 3. Cross-stack API endpoints.
    apis = sorted(
        result.api_impacts or [],
        key=lambda a: (_strip_ansi(a.http_method), _strip_ansi(a.normalized_uri)),
    )
    api_lines: List[str] = []
    if apis:
        api_lines.append("| Method | URI | Frontend caller | Backend controller | Source |")
        api_lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for a in apis:
            uri = _strip_ansi(a.normalized_uri).replace("|", "\\|")
            fe = _strip_ansi(a.fe_caller_symbol).replace("|", "\\|")
            be = _strip_ansi(a.be_controller_symbol).replace("|", "\\|")
            src = _strip_ansi(a.impact_source).replace("|", "\\|")
            api_lines.append(f"| **{_strip_ansi(a.http_method)}** | `{uri}` | `{fe}` | `{be}` | `{src}` |")
    else:
        api_lines.append("_No direct or indirect API contract bindings affected._")
    lines.extend(_details_block(
        f"🌐 Affected API endpoints ({len(apis)})", api_lines,
    ))

    # 4. Recommended test verification.
    tests = sorted(
        result.test_impacts or [],
        key=lambda t: (_repo_relative(t.path, repo_root), _strip_ansi(t.symbol or t.path)),
    )
    test_lines: List[str] = []
    if tests:
        test_lines.append("| Test target | Kind | File | Reason |")
        test_lines.append("| :--- | :--- | :--- | :--- |")
        for t in tests:
            tgt = _strip_ansi(t.symbol or t.path).replace("|", "\\|")
            kind = _strip_ansi(t.kind).replace("|", "\\|")
            path = _repo_relative(t.path, repo_root).replace("|", "\\|")
            reason = _strip_ansi(t.impact_reason).replace("|", "\\|")
            test_lines.append(f"| `{tgt}` | `{kind}` | `{path}` | `{reason}` |")
    else:
        test_lines.append("_No existing test suites mapped to the modified symbols. Consider adding coverage._")
    lines.extend(_details_block(
        f"🧪 Recommended test verification ({len(tests)})", test_lines,
    ))

    lines.append(
        f"<sub>Generated by sot-graph · engine execution {summary.get('execution_time_ms', 0)}ms · "
        "evidence bounded by the reconciled knowledge-graph index</sub>"
    )
    lines.append("")
    return "\n".join(lines)


def format_commit_history_markdown(result: CommitHistoryResult) -> str:
    """Render CommitHistoryResult into a Markdown table with risk assessment badges."""
    breakdown = result.risk_breakdown
    lines: List[str] = [
        "# SOT-Graph Commit History & Risk Assessment",
        "",
        f"**Total Commits Analyzed:** {result.total_commits} | 🔴 High Risk: {breakdown.get('HIGH', 0)} | 🟡 Medium Risk: {breakdown.get('MEDIUM', 0)} | 🟢 Low Risk: {breakdown.get('LOW', 0)}",
        "",
        "| Hash | Author | Date | Churn | Risk | Message | Reasons |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for c in result.commits:
        risk_icon = "🔴" if c.risk_level == "HIGH" else "🟡" if c.risk_level == "MEDIUM" else "🟢"
        churn_str = f"+{c.insertions}/-{c.deletions} ({len(c.files_changed)} files)"
        reasons_str = "; ".join(_sanitize_cell(r) for r in c.risk_reasons) if c.risk_reasons else "-"
        safe_msg = _sanitize_cell(c.message)
        safe_author = _sanitize_cell(c.author)
        safe_date = _sanitize_cell(c.date[:10])
        safe_hash = _sanitize_cell(c.short_hash)
        lines.append(
            f"| `{safe_hash}` | {safe_author} | {safe_date} | {churn_str} | {risk_icon} **{c.risk_level}** | {safe_msg} | {reasons_str} |"
        )

    lines.append("")
    return "\n".join(lines)


def format_commit_history_json(result: CommitHistoryResult, indent: int = 2) -> str:
    """Serialize CommitHistoryResult into formatted JSON."""
    return json.dumps(result.to_dict(), indent=indent, ensure_ascii=False)
