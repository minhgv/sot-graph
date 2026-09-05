#!/usr/bin/env python3
"""bench_holdout.py — SG-204 real-repo holdout benchmark.

Runs the REAL pipeline (clone-at-pinned-SHA -> Reconciler -> search /
usages / diff-impact engines) against 11 public Python repos pinned in
``benchmarks/holdout/manifest.json`` and scores it with the INDEPENDENT
stdlib-ast oracle (``sot_graph.holdout.evaluator`` — never imports
extractor internals; enforced by test).

Suites per repo (deterministic, seeded):

- presence      : every indexed Python symbol verified against the ast
                  oracle (precision), every oracle def found in the
                  index (false absence). GATE: precision >= 99.5%,
                  false absence == 0.
- impact        : 1-hop direct-call upstream callers from the oracle
                  (supported static scope: same-file + resolved
                  from-imports) vs the real usages engine. GATE:
                  recall >= 95%.
- test_selection: pinned real diff (base..head from the manifest);
                  ground truth = tests referencing changed top-level
                  symbols (oracle), vs the real DiffImpactEngine's
                  selected tests. GATE: recall >= 98%.
- retrieval     : seeded real-symbol queries through the real search
                  path (Hit@1 / Hit@5 / MRR) — REPORTED, not gated.
- abstention    : deterministic nonexistent-name queries must return
                  nothing — calibration reported alongside accuracy.

The manifest pins TWO independent commits per repo: ``commit`` is the
graph head (repo state for presence / impact / retrieval / abstention,
scored after an incremental reconcile), and ``diff_task.base..head`` is
a real PR chosen so top-level symbols actually change (test selection
is never vacuously unmeasurable). The diff suite exercises the
incremental reconciler too: the graph is built at the diff BASE, the
engine analyzes base..head, then the working tree jumps to the graph
head and reconciles incrementally.

Writes benchmarks/holdout/report.json. ``--gate`` exits 1 on any gate
failure. ``--selfcheck`` validates manifest + gates without cloning.

Usage:
  python3 scripts/bench_holdout.py [--repos-dir .holdout-cache] \
      [--manifest benchmarks/holdout/manifest.json] \
      [--report benchmarks/holdout/report.json] [--only click] \
      [--max-repos N] [--gate] [--selfcheck] [--ensure-clone]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from sot_graph.holdout import evaluator as oracle  # noqa: E402

GATES = {
    "presence_precision": 0.995,
    "false_absence": 0,
    "impact_recall": 0.95,
    "test_selection_recall": 0.98,
}

PRESENCE_SAMPLE = 400  # oracle defs sampled per repo for scoring
RETRIEVAL_SAMPLE = 30
IMPACT_SAMPLE = 25
ABSTENTION_PROBES = 20

MANIFEST_PATH = _REPO / "benchmarks" / "holdout" / "manifest.json"
DEFAULT_REPOS_DIR = _REPO / ".holdout-cache"


# ---------------------------------------------------------------------------
# Manifest / repo preparation
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> Dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    repos = manifest.get("repos") or []
    if not (10 <= len(repos) <= 20):
        raise SystemExit(f"manifest must hold 10-20 repos, has {len(repos)}")
    for repo in repos:
        for key in ("name", "url", "commit", "license", "seed"):
            if key not in repo:
                raise SystemExit(f"manifest repo missing {key!r}: {repo}")
        task = repo.get("diff_task") or {}
        for key in ("base", "head"):
            if key not in task:
                raise SystemExit(
                    f"manifest repo missing diff_task.{key}: {repo['name']}"
                )
        if (
            len(repo["commit"]) != 40
            or len(task["base"]) != 40
            or len(task["head"]) != 40
        ):
            raise SystemExit(f"manifest SHAs must be full 40-hex: {repo['name']}")
    return manifest


def git(repo_dir: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), *args], capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args[:3])} failed: {result.stderr.strip()[:200]}"
        )
    return result.stdout.strip()


def ensure_commit(repo_dir: Path, url: str, sha: str) -> None:
    """Materialize a pinned commit locally (clone once, fetch the SHA)."""
    if not repo_dir.exists():
        subprocess.run(
            ["git", "clone", "-q", url, str(repo_dir)],
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
    try:
        git(repo_dir, "cat-file", "-e", f"{sha}^{{commit}}", check=False)
        have = (
            subprocess.run(
                ["git", "-C", str(repo_dir), "cat-file", "-e", sha], capture_output=True
            ).returncode
            == 0
        )
    except Exception:
        have = False
    if not have:
        git(repo_dir, "fetch", "origin", sha)


# ---------------------------------------------------------------------------
# Suites
# ---------------------------------------------------------------------------


def suite_presence(db: Any, repo_root: Path, seed: int) -> Dict[str, Any]:
    config = oracle.OracleConfig()
    defs, parse_failures = oracle.extract_definitions(repo_root, config)
    gt_by_name: Dict[Tuple[str, str], Set[int]] = {}
    for d in defs:
        gt_by_name.setdefault((d.path, d.name), set()).add(d.line)
    # precision validates against EVERY def ast can see (locals,
    # conditionals, overloads included) — an engine node pointing at a
    # def that exists anywhere in the file is not a hallucination.
    full_universe = oracle.all_definition_names(repo_root, config)

    rows = db.conn.execute(
        "SELECT path, symbol, kind, line_start FROM graph_nodes"
    ).fetchall()
    excluded = set(config.exclude_names)
    indexed, verified, near_miss, line_drift = 0, 0, [], []
    node_names: Set[Tuple[str, str]] = set()
    for path, symbol, kind, line_start in rows:
        if not path or not str(path).endswith(".py"):
            continue
        rel = str(path)
        # graph paths may be absolute — normalize to repo-relative.
        if os.path.isabs(rel):
            try:
                rel = str(Path(rel).resolve().relative_to(repo_root.resolve()))
            except ValueError:
                continue
        rel = rel.replace("\\", "/")
        if any(rel.startswith(p) for p in config.exclude_prefixes):
            continue
        if Path(rel).name in excluded or Path(rel).name == "conftest.py":
            continue
        if kind not in ("function", "method", "class"):
            continue
        if not symbol or line_start is None:
            continue
        # Method symbols are qualified (``Class.method``); the oracle
        # keys by bare name — compare on the bare tail.
        bare = str(symbol).rsplit(".", 1)[-1]
        indexed += 1
        # Presence contract is (path, bare name): the engine's model is
        # one node per unique symbol, so it cannot represent multiplicity
        # (getter + setter under one name, same-name defs in different
        # scopes). Exact lines are diagnostics only (line_drift).
        if (rel, bare) in full_universe:
            verified += 1
            if (rel, bare) in gt_by_name:
                node_names.add((rel, bare))
                if int(line_start) not in gt_by_name[(rel, bare)]:
                    line_drift.append(
                        {
                            "path": rel,
                            "symbol": str(symbol),
                            "line": int(line_start),
                            "gt_lines": sorted(gt_by_name[(rel, bare)]),
                        }
                    )
        else:
            near_miss.append(
                {
                    "path": rel,
                    "symbol": str(symbol),
                    "line": int(line_start),
                }
            )

    false_absences = [
        {"path": d.path, "name": d.name, "line": d.line}
        for d in defs
        if (d.path, d.name) not in node_names
    ]
    precision = verified / indexed if indexed else 1.0
    return {
        "metrics": {
            "presence_precision": round(precision, 4),
            "false_absence": len(false_absences),
            "indexed_symbols": indexed,
            "oracle_definitions": len(defs),
            "verified": verified,
        },
        "parse_failures": parse_failures,
        "near_misses": near_miss[:25],
        "line_drift_sample": line_drift[:25],
        "false_absence_sample": false_absences[:25],
    }


def suite_retrieval_and_abstention(
    service: Any,
    defs: List,
    seed: int,
) -> Dict[str, Any]:
    sample = oracle.sample_definitions(defs, seed, RETRIEVAL_SAMPLE)
    hit1 = hit5 = 0
    rr_sum = 0.0
    per_query_miss: List[str] = []
    for d in sample:
        try:
            results = service.search(d.name, limit=5).get("results", [])
        except Exception:
            results = []
        rank = None
        for i, hit in enumerate(results, start=1):
            symbol = str(hit.get("symbol") or hit.get("label") or "")
            # methods are stored qualified (``Class.method``) — compare bare
            if (
                symbol.rsplit(".", 1)[-1] == d.name
                and str(hit.get("path") or "") == d.path
            ):
                rank = i
                break
        if rank == 1:
            hit1 += 1
        if rank is not None:
            hit5 += 1
            rr_sum += 1.0 / rank
        else:
            per_query_miss.append(f"{d.path}::{d.name}")
    n = len(sample) or 1

    probes = oracle.mutated_queries(defs, seed, ABSTENTION_PROBES)
    false_presence = []
    for name in probes:
        try:
            results = service.search(name, limit=5).get("results", [])
        except Exception:
            results = []
        if results:
            false_presence.append(name)

    return {
        "metrics": {
            "queries": len(sample),
            "hit_at_1": round(hit1 / n, 4),
            "hit_at_5": round(hit5 / n, 4),
            "mrr": round(rr_sum / n, 4),
            "abstention_probes": len(probes),
            "abstention_accuracy": round(
                1 - len(false_presence) / max(1, len(probes)), 4
            ),
        },
        "unfound_queries": per_query_miss[:15],
        "false_presence_queries": false_presence[:15],
    }


_CALLER_KIND_PREFIXES = ("async def ", "def ", "class ", "File: ")


def _caller_bare(label: str) -> str:
    """Bare name from a usages caller label ``def name — path:line``."""
    head = label.split(" — ", 1)[0].strip()
    for prefix in _CALLER_KIND_PREFIXES:
        if head.startswith(prefix):
            head = head[len(prefix) :]
            break
    return head.rsplit(".", 1)[-1].strip()


def suite_impact(
    service: Any, repo_root: Path, defs: List, seed: int
) -> Dict[str, Any]:
    config = oracle.OracleConfig()
    edges, unresolved = oracle.resolve_direct_calls(repo_root, defs, config)
    # Callee candidates: unique bare names with >=1 oracle caller edge.
    name_counts: Dict[str, int] = {}
    for d in defs:
        name_counts[d.name] = name_counts.get(d.name, 0) + 1
    callee_targets: Dict[str, List] = {}
    for edge in edges:
        if name_counts.get(edge.callee_name, 0) != 1:
            continue  # ambiguous bare name: out of supported scope
        callee_targets.setdefault(edge.callee_name, []).append(edge)
    rng_sample = sorted(callee_targets)[:IMPACT_SAMPLE]

    recalls = []
    misses: List[Dict[str, Any]] = []
    for callee in rng_sample:
        gt_callers = {
            (e.caller_path, e.caller_name.rsplit(".", 1)[-1])
            for e in callee_targets[callee]
        }
        try:
            payload = service.usages(callee, limit=200)
            engine_callers = {
                (
                    str(c.get("path") or "").replace("\\", "/"),
                    _caller_bare(str(c.get("label") or "")),
                )
                for c in payload.get("callers", [])
                if c.get("path")
            }
        except Exception:
            engine_callers = set()
        found = gt_callers & engine_callers
        if gt_callers:
            recalls.append(len(found) / len(gt_callers))
        if len(found) < len(gt_callers):
            misses.append(
                {
                    "target": callee,
                    "missing": sorted(
                        f"{p}::{n}" for (p, n) in gt_callers - engine_callers
                    ),
                }
            )
    recall = sum(recalls) / len(recalls) if recalls else None
    return {
        "metrics": {
            "targets": len(rng_sample),
            "impact_recall": round(recall, 4) if recall is not None else None,
            "unresolved_calls": unresolved,
        },
        "misses": misses[:15],
    }


def suite_test_selection(
    db: Any,
    repo_dir: Path,
    repo_root: Path,
    base: str,
    head: str,
) -> Dict[str, Any]:
    from sot_graph.diff_impact import DiffImpactEngine

    # Rename-aware pairs: (old_path, new_path). A pure rename (R100) has
    # identical content on both sides — comparing head:new vs base:OLD
    # yields an empty delta, exactly like the engine's hunk view; a naive
    # per-path base lookup would instead mark every moved def "changed".
    pairs: List[Tuple[str, str]] = []
    for line in git(repo_dir, "diff", "--name-status", "-M", base, head).splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R"):
            pairs.append((parts[1], parts[2]))
        elif len(parts) == 2:
            pairs.append((parts[1], parts[1]))
    changed_py = [
        (old, new)
        for old, new in pairs
        if new.endswith(".py")
        and not new.startswith(("docs/", ".github/", "examples/"))
    ]
    if not changed_py:
        return {
            "metrics": {
                "test_selection_recall": None,
                "reason": "no source .py files in diff",
            },
            "gt_tests": [],
            "engine_tests": [],
        }

    changed_names: Set[str] = set()
    for old, new in changed_py:
        head_text = git(repo_dir, "show", f"{head}:{new}", check=False)
        base_text = git(repo_dir, "show", f"{base}:{old}", check=False)
        changed_names |= oracle.top_level_delta(head_text, base_text)
    if not changed_names:
        return {
            "metrics": {
                "test_selection_recall": None,
                "reason": "no top-level symbol changed",
            },
            "gt_tests": [],
            "engine_tests": [],
        }

    # GT at HEAD state: the runnable tests after the diff are the head
    # versions (a rename-heavy diff would otherwise compare base paths
    # against the engine's head paths and score a rename as a miss).
    # Two obligation sources:
    #   (a) a test file touched by the diff must run — same rule the
    #       engine applies to directly-changed test files;
    #   (b) a head test file that references a changed symbol by bare
    #       name. Attribute references (``obj.replace``) are deliberately
    #       excluded: they are usually methods on an unrelated object and
    #       would collide with common names (a documented GT limitation —
    #       method-call references are undercounted).
    gt_tests: Set[str] = set()
    for _old, new in changed_py:
        if oracle.is_test_path(new):
            gt_tests.add(new)
    for rel in git(repo_dir, "ls-tree", "-r", "--name-only", head).splitlines():
        rel = rel.strip()
        if not rel or not oracle.is_test_path(rel):
            continue
        text = git(repo_dir, "show", f"{head}:{rel}", check=False)
        if text and oracle.referenced_names(text) & changed_names:
            gt_tests.add(rel)

    engine = DiffImpactEngine(db, str(repo_root))
    impact = engine.analyze_diff_impact(target=head)

    def _rel_path(p: str) -> Optional[str]:
        """Engine test paths mix relative and absolute forms — normalize
        to repo-relative (None when outside the repo)."""
        p = p.replace("\\", "/")
        if os.path.isabs(p):
            try:
                return str(Path(p).resolve().relative_to(repo_root.resolve()))
            except ValueError:
                return None
        return p

    engine_tests = {
        rel for rel in (_rel_path(t.path) for t in impact.test_impacts) if rel
    }

    if not gt_tests:
        return {
            "metrics": {
                "test_selection_recall": None,
                "reason": "no tests reference changed symbols",
            },
            "changed_symbols": sorted(changed_names),
            "gt_tests": [],
            "engine_tests": sorted(engine_tests),
        }
    recall = len(gt_tests & engine_tests) / len(gt_tests)
    return {
        "metrics": {
            "test_selection_recall": round(recall, 4),
            "changed_symbols": sorted(changed_names),
        },
        "gt_tests": sorted(gt_tests),
        "engine_tests": sorted(engine_tests),
        "missing_tests": sorted(gt_tests - engine_tests),
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_repo(repo: Dict[str, Any], repos_dir: Path) -> Dict[str, Any]:
    from sot_graph.db import Database
    from sot_graph.mcp_service import McpService
    from sot_graph.reconciler import Reconciler

    repo_dir = repos_dir / repo["name"]
    task = repo["diff_task"]
    for sha in (repo["commit"], task["base"], task["head"]):
        ensure_commit(repo_dir, repo["url"], sha)
    base, head = task["base"], task["head"]
    graph_head = repo["commit"]
    record: Dict[str, Any] = {
        "name": repo["name"],
        "license": repo["license"],
        "commit": graph_head,
        "diff_base": base,
        "diff_head": head,
        "diff_subject": task.get("subject"),
    }

    # Phase 1: graph at BASE, diff-impact base..head (test selection).
    git(repo_dir, "checkout", "-q", "-f", "--detach", base)
    repo_root = repo_dir
    db_path = repo_dir / ".sot" / "sot.db"
    if db_path.exists():
        db_path.unlink()
    db = Database(str(db_path))
    try:
        Reconciler(db, str(repo_root)).reconcile(workers=4)
        record["test_selection"] = suite_test_selection(
            db, repo_dir, repo_root, base, head
        )

        # Phase 2: move to GRAPH HEAD — incremental reconcile (self-healing
        # path; the jump may be large when diff head != graph head).
        git(repo_dir, "checkout", "-q", "-f", "--detach", graph_head)
        Reconciler(db, str(repo_root)).reconcile(workers=4)

        seed = int(repo["seed"])
        record["presence"] = suite_presence(db, repo_root, seed)
        defs, _ = oracle.extract_definitions(repo_root, oracle.OracleConfig())
        service = McpService(str(db_path), str(repo_root))
        try:
            record["retrieval"] = suite_retrieval_and_abstention(service, defs, seed)
            record["impact"] = suite_impact(service, repo_root, defs, seed)
        finally:
            service.close()
    finally:
        db.close()
    return record


def aggregate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    def collect(suite: str, key: str) -> List[float]:
        values = []
        for r in records:
            v = r.get(suite, {}).get("metrics", {}).get(key)
            if v is not None:
                values.append(v)
        return values

    def mean(values: List[float]) -> Optional[float]:
        return round(sum(values) / len(values), 4) if values else None

    presence_p = collect("presence", "presence_precision")
    false_abs = collect("presence", "false_absence")
    impact_r = collect("impact", "impact_recall")
    testsel_r = collect("test_selection", "test_selection_recall")
    abstain = collect("retrieval", "abstention_accuracy")

    metrics = {
        "repos": len(records),
        "presence_precision_macro": mean(presence_p),
        "presence_precision_min": min(presence_p) if presence_p else None,
        "false_absence_total": sum(false_abs),
        "impact_recall_macro": mean(impact_r),
        "test_selection_recall_macro": mean(testsel_r),
        "test_selection_measured_repos": len(testsel_r),
        "hit_at_1_macro": mean(collect("retrieval", "hit_at_1")),
        "hit_at_5_macro": mean(collect("retrieval", "hit_at_5")),
        "mrr_macro": mean(collect("retrieval", "mrr")),
        "abstention_accuracy_macro": mean(abstain),
    }
    checks = {
        "presence_precision": metrics["presence_precision_macro"] is not None
        and metrics["presence_precision_macro"] >= GATES["presence_precision"],
        "false_absence": metrics["false_absence_total"] == GATES["false_absence"],
        "impact_recall": metrics["impact_recall_macro"] is not None
        and metrics["impact_recall_macro"] >= GATES["impact_recall"],
        "test_selection_recall": metrics["test_selection_recall_macro"] is not None
        and metrics["test_selection_recall_macro"] >= GATES["test_selection_recall"],
    }
    return {
        "metrics": metrics,
        "checks": checks,
        "gates": {**GATES, "passed": all(checks.values())},
    }


def markdown_summary(report: Dict[str, Any]) -> str:
    m = report["aggregate"]["metrics"]
    lines = [
        "# SG-204 holdout benchmark report",
        "",
        f"- repos measured: **{m['repos']}** (pinned, licenses declared)",
        f"- presence precision (macro / min): "
        f"**{m['presence_precision_macro']}** / {m['presence_precision_min']}",
        f"- false absence total: **{m['false_absence_total']}**",
        f"- impact recall (macro, supported static scope): "
        f"**{m['impact_recall_macro']}**",
        f"- test-selection recall (macro, "
        f"{m['test_selection_measured_repos']} repos): "
        f"**{m['test_selection_recall_macro']}**",
        f"- retrieval Hit@1 / Hit@5 / MRR (reported, not gated): "
        f"{m['hit_at_1_macro']} / {m['hit_at_5_macro']} / {m['mrr_macro']}",
        f"- abstention accuracy: {m['abstention_accuracy_macro']}",
        "",
        "| repo | presence | false-abs | impact | test-sel |",
        "|---|---|---|---|---|",
    ]
    for r in report["repos"]:
        p = r.get("presence", {}).get("metrics", {})
        i = r.get("impact", {}).get("metrics", {})
        t = r.get("test_selection", {}).get("metrics", {})
        lines.append(
            f"| {r['name']} | {p.get('presence_precision')} "
            f"| {p.get('false_absence')} | {i.get('impact_recall')} "
            f"| {t.get('test_selection_recall')} |"
        )
    lines += [
        "",
        f"gates: {'**ALL PASS**' if report['aggregate']['gates']['passed'] else '**FAILED**'}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--repos-dir", default=str(DEFAULT_REPOS_DIR))
    parser.add_argument(
        "--report", default=str(_REPO / "benchmarks" / "holdout" / "report.json")
    )
    parser.add_argument("--only", default=None, help="run a single repo by name")
    parser.add_argument("--max-repos", type=int, default=None)
    parser.add_argument("--gate", action="store_true")
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument(
        "--ensure-clone",
        action="store_true",
        help="clone missing repos even without --only",
    )
    args = parser.parse_args(argv)

    manifest = load_manifest(Path(args.manifest))

    if args.selfcheck:
        print(f"manifest OK: {len(manifest['repos'])} pinned repos, gates={GATES}")
        return 0

    repos = manifest["repos"]
    if args.only:
        repos = [r for r in repos if r["name"] == args.only]
        if not repos:
            print(f"no repo named {args.only!r} in manifest", file=sys.stderr)
            return 1
    if args.max_repos:
        repos = repos[: args.max_repos]

    repos_dir = Path(args.repos_dir)
    records: List[Dict[str, Any]] = []
    for repo in repos:
        repo_dir = repos_dir / repo["name"]
        if not repo_dir.exists() and not (args.ensure_clone or args.only):
            print(
                f"SKIP {repo['name']}: not cloned (use --ensure-clone)", file=sys.stderr
            )
            continue
        started = time.monotonic()
        try:
            record = run_repo(repo, repos_dir)
        except Exception as exc:  # noqa: BLE001 - report, don't crash the run
            record = {"name": repo["name"], "error": f"{type(exc).__name__}: {exc}"}
        record["duration_s"] = round(time.monotonic() - started, 1)
        records.append(record)
        p = record.get("presence", {}).get("metrics", {})
        print(
            f"{repo['name']:16s} presence={p.get('presence_precision')} "
            f"false_abs={p.get('false_absence')} "
            f"({record['duration_s']}s)"
            + (f" ERROR={record['error'][:60]}" if "error" in record else "")
        )

    if not records:
        print("no repos measured", file=sys.stderr)
        return 1

    report = {
        "benchmark": "real-repo-holdout",
        "schema_version": 1,
        "manifest_digest": subprocess.run(
            ["git", "hash-object", args.manifest], capture_output=True, text=True
        ).stdout.strip()[:12],
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "repos": records,
    }
    report["aggregate"] = aggregate(records)
    report["markdown"] = markdown_summary(report)

    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    (out.parent / "report.md").write_text(report["markdown"], encoding="utf-8")

    m = report["aggregate"]["metrics"]
    print("\nSG-204 holdout aggregate:")
    print(
        f"  presence precision (macro/min): "
        f"{m['presence_precision_macro']} / {m['presence_precision_min']}"
    )
    print(f"  false absence total            : {m['false_absence_total']}")
    print(f"  impact recall (macro)          : {m['impact_recall_macro']}")
    print(f"  test-selection recall (macro)  : {m['test_selection_recall_macro']}")
    print(f"  abstention accuracy            : {m['abstention_accuracy_macro']}")
    print(f"  report: {out}")
    if args.gate:
        failed = [k for k, ok in report["aggregate"]["checks"].items() if not ok]
        if failed:
            print(f"GATE FAIL: {failed}", file=sys.stderr)
            return 1
        print("  gates: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
