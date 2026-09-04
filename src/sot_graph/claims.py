"""Machine-readable trust-claim registry + docs claim linter (SG-110).

The reassessment (§7 P0-7) caught public trust claims drifting beyond the
evidence: hand-edited docs cite metrics, ceilings and guarantees that nothing
enforces, and CI paths-ignores every Markdown file, so docs-only PRs run no
validation at all.

This module closes that loop with a registry-driven linter:

  ``claims/registry.yaml`` lists every public trust claim we make, the doc
  lines that carry it, and the same-commit artifact that substantiates it
  (benchmark JSON, enforcing test, or source invariant). The linter then:

  1. Registry integrity — artifact exists, is git-tracked, the provenance
     commit is an ancestor of HEAD, and the cited metric value still matches
     the artifact at this commit.
  2. Docs<->registry sync — every registered pattern must still appear in
     every doc it claims to live in, so neither side drifts silently.
  3. Unregistered absolutes — README/AGENTS/docs are scanned for banned
     absolute phrases ("100%", "guarantee", "authoritative", ...). A hit is
     acceptable only when it is covered by a registry entry, explicitly
     hedged on the same line, or carries a reviewed ``allow:`` exemption.

Exit contract: 0 clean, 1 any violation. Pure reads; no database access.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Absolute phrases that constitute a public trust claim when unhedged.
BANNED_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("pct-100", r"\b100\s*%"),
    ("zero-hallucination", r"\bzero\s+hallucinat\w*"),
    ("guarantee", r"\bguarantee\w*\b"),
    ("authoritative", r"\bauthoritative\b"),
    ("production-qualified", r"\bPRODUCTION_QUALIFIED\b"),
)

# Same-line markers that bound an absolute phrase into an honest ceiling
# statement ("advisory", "bounded", explicit negations, ...).
HEDGE_MARKERS: Tuple[str, ...] = (
    "advisory",
    "not guaranteed",
    "not a guarantee",
    "no guarantee",
    "not an absence",
    "not an exhaustiveness",
    "does not claim",
    "does not guarantee",
    "cannot guarantee",
    "bounded",
    "fail-closed",
    "within the verified",
    "within scope",
    "scoped",
)

# Default docs corpus (repo-relative). Registry ``skip_files`` may extend it.
DEFAULT_CORPUS: Tuple[str, ...] = (
    "README.md",
    "AGENTS.md",
    # docs/*.md — RELEASE_NOTES*/adr are frozen records, not product claims;
    # they are skipped via the registry's default_skip_files below.
)
DEFAULT_DOCS_GLOB = "docs/*.md"

_CLAIM_REQUIRED = ("id", "claim", "files", "pattern", "artifact", "commit", "ceiling")
_FLOAT_TOL = 1e-9


@dataclass(frozen=True)
class Claim:
    """One public trust claim and its same-commit artifact trace."""

    id: str
    claim: str
    files: Tuple[str, ...]
    pattern: str
    artifact: str
    commit: str
    ceiling: str
    capability: str = ""
    language: str = ""
    provider: str = ""
    corpus: str = ""
    artifact_field: str = ""
    artifact_value: Any = None
    artifact_symbol: str = ""


@dataclass(frozen=True)
class AllowEntry:
    """A reviewed exemption: a banned phrase that is not a trust claim."""

    file: str
    contains: str
    reason: str


@dataclass
class Violation:
    code: str
    detail: str
    file: str = ""
    line: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "file": self.file,
            "line": self.line,
            "detail": self.detail,
        }


@dataclass
class Registry:
    claims: List[Claim] = field(default_factory=list)
    allows: List[AllowEntry] = field(default_factory=list)
    skip_files: List[str] = field(default_factory=list)
    issues: List[Violation] = field(default_factory=list)


def _violation(code: str, detail: str, file: str = "", line: int = 0) -> Violation:
    return Violation(code=code, detail=detail, file=file, line=line)


def _norm_rel(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def load_registry(path: Path) -> Registry:
    """Parse + structurally validate claims/registry.yaml."""
    import yaml  # deferred: keeps CLI startup lean for non-claims commands

    reg = Registry()
    if not path.is_file():
        reg.issues.append(
            _violation("registry-missing", f"registry not found at {path}")
        )
        return reg
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        reg.issues.append(_violation("registry-unparseable", str(exc)))
        return reg

    seen_ids: Dict[str, str] = {}
    for raw in data.get("claims") or []:
        if not isinstance(raw, dict):
            reg.issues.append(
                _violation("registry-schema", f"claim entry is not a mapping: {raw!r}")
            )
            continue
        missing = [k for k in _CLAIM_REQUIRED if not raw.get(k)]
        if missing:
            reg.issues.append(
                _violation(
                    "registry-schema",
                    f"claim entry missing required key(s) {missing}: {raw!r}",
                )
            )
            continue
        cid = str(raw["id"])
        if cid in seen_ids:
            reg.issues.append(
                _violation(
                    "registry-schema",
                    f"duplicate claim id {cid!r} (also on {seen_ids[cid]})",
                )
            )
            continue
        seen_ids[cid] = ", ".join(map(str, raw["files"]))
        files = tuple(_norm_rel(str(f)) for f in raw["files"])
        value = raw.get("artifact_value")
        if isinstance(value, float) or isinstance(value, int):
            pass  # numeric compare with tolerance
        reg.claims.append(
            Claim(
                id=cid,
                claim=str(raw["claim"]),
                files=files,
                pattern=str(raw["pattern"]),
                artifact=_norm_rel(str(raw["artifact"])),
                commit=str(raw["commit"]),
                ceiling=str(raw["ceiling"]),
                capability=str(raw.get("capability") or ""),
                language=str(raw.get("language") or ""),
                provider=str(raw.get("provider") or ""),
                corpus=str(raw.get("corpus") or ""),
                artifact_field=str(raw.get("artifact_field") or ""),
                artifact_value=value,
                artifact_symbol=str(raw.get("artifact_symbol") or ""),
            )
        )

    for raw in data.get("allow") or []:
        if not isinstance(raw, dict) or not all(
            raw.get(k) for k in ("file", "contains", "reason")
        ):
            reg.issues.append(
                _violation("registry-schema", f"malformed allow entry: {raw!r}")
            )
            continue
        reg.allows.append(
            AllowEntry(
                file=_norm_rel(str(raw["file"])),
                contains=str(raw["contains"]),
                reason=str(raw["reason"]),
            )
        )

    for raw in data.get("skip_files") or []:
        if isinstance(raw, str) and raw.strip():
            reg.skip_files.append(_norm_rel(raw.strip()))
        else:
            reg.issues.append(
                _violation("registry-schema", f"malformed skip_files entry: {raw!r}")
            )
    return reg


def _resolve_dotpath(obj: Any, dotpath: str) -> Tuple[bool, Any]:
    """Walk a.b.3.c through nested dicts/lists; numeric segments index lists."""
    cur = obj
    for seg in dotpath.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        elif isinstance(cur, list) and seg.isdigit() and int(seg) < len(cur):
            cur = cur[int(seg)]
        else:
            return False, None
    return True, cur


def _values_match(expected: Any, actual: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= _FLOAT_TOL
    return expected == actual


def _git_ok(repo_root: Path, *args: str) -> Tuple[bool, str]:
    """Run a git query; returns (ok, stderr). Fail-closed on any error."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()[:200]
    return True, ""


def _line_of(text: str, index: int) -> Tuple[int, str]:
    line_start = text.rfind("\n", 0, index) + 1
    line_end = text.find("\n", index)
    if line_end < 0:
        line_end = len(text)
    return text.count("\n", 0, index) + 1, text[line_start:line_end]


def _occurrences(text: str, needle: str) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    if not needle:
        return out
    start = 0
    while True:
        idx = text.find(needle, start)
        if idx < 0:
            return out
        out.append((idx, idx + len(needle)))
        start = idx + 1


def lint_claims(
    repo_root: Path,
    registry_path: Optional[Path] = None,
    *,
    corpus: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Validate the registry and every doc claim it covers.

    Returns a JSON-ready report; ``ok`` is False when any violation exists.
    Pure reads: touches the working tree, git metadata and nothing else.
    """
    root = Path(repo_root).resolve()
    reg = load_registry(registry_path or (root / "claims" / "registry.yaml"))
    violations: List[Violation] = list(reg.issues)

    if corpus is None:
        corpus = list(DEFAULT_CORPUS)
        for p in sorted((root / "docs").glob("*.md")):
            corpus.append(_norm_rel(str(p.relative_to(root))))
    skip = set(reg.skip_files)
    corpus = [f for f in corpus if _norm_rel(f) not in skip]
    corpus = sorted(set(_norm_rel(f) for f in corpus))

    texts: Dict[str, str] = {}
    for rel in corpus:
        p = root / rel
        if not p.is_file():
            # A corpus file listed but absent is itself a claim-surface gap.
            violations.append(_violation("corpus-missing", str(p), file=rel))
            continue
        texts[rel] = p.read_text(encoding="utf-8", errors="replace")

    # --- 1. Registry integrity + 2. docs<->registry sync -----------------
    for c in reg.claims:
        for rel in c.files:
            text = texts.get(rel)
            if text is None:
                p = root / rel
                if not p.is_file():
                    violations.append(
                        _violation(
                            "claim-file-missing",
                            f"{c.id}: doc file {rel} does not exist",
                            file=rel,
                        )
                    )
                else:
                    violations.append(
                        _violation(
                            "claim-outside-corpus",
                            f"{c.id}: doc {rel} exists but is not in the lint "
                            "corpus; add it or fix the registry",
                            file=rel,
                        )
                    )
                continue
            if not _occurrences(text, c.pattern):
                violations.append(
                    _violation(
                        "docs-drift",
                        f"{c.id}: pattern no longer appears in {rel} — the doc "
                        "claim and the registry have drifted apart",
                        file=rel,
                    )
                )

        art = root / c.artifact
        if not art.is_file():
            violations.append(
                _violation(
                    "artifact-missing",
                    f"{c.id}: artifact {c.artifact} does not exist on disk",
                    file=c.artifact,
                )
            )
            continue
        ok, err = _git_ok(root, "ls-files", "--error-unmatch", c.artifact)
        if not ok:
            violations.append(
                _violation(
                    "artifact-untracked",
                    f"{c.id}: artifact {c.artifact} is not tracked by git "
                    f"({err}); claims must trace to committed artifacts",
                    file=c.artifact,
                )
            )
        ok, err = _git_ok(root, "cat-file", "-e", f"{c.commit}^{{commit}}")
        if not ok:
            violations.append(
                _violation(
                    "commit-unknown",
                    f"{c.id}: provenance commit {c.commit} not found ({err})",
                    file=c.artifact,
                )
            )
        else:
            ok, err = _git_ok(root, "merge-base", "--is-ancestor", c.commit, "HEAD")
            if not ok:
                violations.append(
                    _violation(
                        "commit-not-ancestor",
                        f"{c.id}: provenance commit {c.commit} is not an "
                        "ancestor of HEAD; the claim cites evidence from an "
                        "unmerged future",
                        file=c.artifact,
                    )
                )

        if c.artifact_field:
            try:
                data = json.loads(art.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                violations.append(
                    _violation(
                        "artifact-unparseable",
                        f"{c.id}: artifact {c.artifact} is not valid JSON: {exc}",
                        file=c.artifact,
                    )
                )
                data = None
            if data is not None:
                found, actual = _resolve_dotpath(data, c.artifact_field)
                if not found:
                    violations.append(
                        _violation(
                            "artifact-field-missing",
                            f"{c.id}: field {c.artifact_field} not present in "
                            f"{c.artifact}",
                            file=c.artifact,
                        )
                    )
                elif not _values_match(c.artifact_value, actual):
                    violations.append(
                        _violation(
                            "artifact-mismatch",
                            f"{c.id}: {c.artifact}#{c.artifact_field} is "
                            f"{actual!r}, registry cites {c.artifact_value!r} "
                            "— the artifact no longer supports the claim",
                            file=c.artifact,
                        )
                    )
        if c.artifact_symbol:
            art_text = art.read_text(encoding="utf-8", errors="replace")
            if c.artifact_symbol not in art_text:
                violations.append(
                    _violation(
                        "artifact-symbol-missing",
                        f"{c.id}: symbol {c.artifact_symbol!r} not found in "
                        f"{c.artifact}",
                        file=c.artifact,
                    )
                )

    # --- 3. Unregistered absolute claims ---------------------------------
    registered_spans: Dict[str, List[Tuple[int, int]]] = {}
    for c in reg.claims:
        for rel in c.files:
            text = texts.get(rel)
            if text is not None:
                registered_spans.setdefault(rel, []).extend(
                    _occurrences(text, c.pattern)
                )

    stats = {"registered": 0, "hedged": 0, "allowed": 0, "banned_hits": 0}
    for rel, text in texts.items():
        for tag, rx in BANNED_PATTERNS:
            for m in re.finditer(rx, text, re.IGNORECASE):
                stats["banned_hits"] += 1
                line_no, line = _line_of(text, m.start())
                low = line.lower()
                if any(h in low for h in HEDGE_MARKERS):
                    stats["hedged"] += 1
                    continue
                if any(s <= m.start() < e for s, e in registered_spans.get(rel, [])):
                    stats["registered"] += 1
                    continue
                if any(a.file == rel and a.contains in line for a in reg.allows):
                    stats["allowed"] += 1
                    continue
                violations.append(
                    _violation(
                        "unregistered-absolute-claim",
                        f"[{tag}] {m.group(0)!r} is an unhedged absolute claim "
                        "with no registry entry; register it with an artifact "
                        "trace, hedge it, or add a reviewed allow entry",
                        file=rel,
                        line=line_no,
                    )
                )

    # Keep allow entries honest: an exemption for text that no longer
    # exists would silently rot into a blanket pass.
    for a in reg.allows:
        text = texts.get(a.file)
        if text is None:
            p = root / a.file
            if not p.is_file():
                violations.append(
                    _violation(
                        "allow-file-missing",
                        f"allow entry targets missing file {a.file}",
                        file=a.file,
                    )
                )
            continue
        if a.contains not in text:
            violations.append(
                _violation(
                    "allow-stale",
                    f"allow entry for {a.file} no longer matches (missing "
                    f"{a.contains!r}); remove or update it",
                    file=a.file,
                )
            )

    violations.sort(key=lambda v: (v.file, v.line, v.code))
    return {
        "ok": not violations,
        "corpus_files": len(texts),
        "claims_checked": len(reg.claims),
        "allow_entries": len(reg.allows),
        "skipped_files": sorted(skip),
        "hit_classification": stats,
        "violations": [v.to_dict() for v in violations],
    }


def format_report(report: Dict[str, Any]) -> str:
    """Human-readable rendering of a lint_claims() report."""
    if report["ok"]:
        return (
            f"✅ claims clean: {report['claims_checked']} registered "
            f"claims traced, {report['corpus_files']} corpus files "
            f"scanned, {report['hit_classification']['banned_hits']} "
            "absolute-phrase hits all covered"
        )
    lines = [f"❌ claims lint: {len(report['violations'])} violation(s)"]
    for v in report["violations"]:
        where = f"{v['file']}:{v['line']}" if v["file"] else "-"
        lines.append(f"  [{v['code']}] {where}\n      {v['detail']}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None, repo_root: Optional[Path] = None) -> int:
    """Standalone entry: python -m sot_graph.claims [--json] [root]."""
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    root = Path(args[0]).resolve() if args else (repo_root or Path.cwd())
    report = lint_claims(root)
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
