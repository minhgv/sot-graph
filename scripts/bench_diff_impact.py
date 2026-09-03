#!/usr/bin/env python3
"""bench_diff_impact.py — diff-impact oracle: precision / recall / F1 (R3).

The reassessment (plan/sot-graph-reassessment-vs-roadmap-2026-08-28.md §4.2/§6)
flagged that the accuracy corpus had no diff-impact oracle. This benchmark
builds a synthetic git repo with a planted call graph
A(main_dispatch) -> B(handle_request) -> C(transform_data) -> D(render_payload),
an inheritance pair (EmailNotifier extends Notifier) and test files named per
the repo's test-detection conventions, then replays six scripted change
scenarios whose ground truth is known BY CONSTRUCTION:

  (a) modify_body            — edit inside the leaf function body
  (b) rename_symbol          — rename a mid-chain function definition
  (c) delete_file            — delete the leaf module outright
  (d) api_signature_change   — add a keyword-only parameter to a public def
  (e) extends_hierarchy      — edit the base-class method an override shadows
  (f) test_file_edit         — edit a test function directly

Each scenario runs the REAL DiffImpactEngine (git -U0 diff extraction ->
AST coordinate mapping -> reverse call-graph BFS -> test discovery) against
the pre-change reconciled graph, and compares predicted impacted symbols /
tests / files against the planted expectation. Expected sets follow the
engine's documented contract: BFS over calls/extends/implements/uses/imports
to the same depth, test-shaped callers reported under tests (never as
production callers), file-level import nodes excluded from symbol scoring.

Writes benchmarks/diff-impact-oracle.json (digest, per-scenario records,
per-scenario and macro P/R/F1). `--gate` exits 1 when any threshold fails.

Usage:
  python3 scripts/bench_diff_impact.py [--json benchmarks/diff-impact-oracle.json]
  python3 scripts/bench_diff_impact.py --gate
  python3 scripts/bench_diff_impact.py --selfcheck
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Set, Tuple

_REPO = Path(__file__).resolve().parents[1]
for _path in (_REPO, _REPO / "src", _REPO / "vendor"):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from sot_graph.db import Database  # noqa: E402
from sot_graph.diff_impact import DiffImpactEngine  # noqa: E402
from sot_graph.reconciler import Reconciler  # noqa: E402

SCHEMA_VERSION = 1
BENCHMARK = "diff-impact-oracle"
TRAVERSAL_DEPTH = 4
ENGINE_RELATIONS = ("calls", "extends", "implements", "uses", "imports")

# ---------------------------------------------------------------------------
# Planted corpus (base commit) and planted symbol graph.
# ---------------------------------------------------------------------------

BASE_FILES: Dict[str, str] = {}


def _add(rel: str, body: str) -> None:
    BASE_FILES[rel] = body


_add("src/leaf.py", '''"""Leaf rendering module."""


def render_payload(items):
    """Render payload items into a summary string."""
    total = sum(items)
    return f"payload:{total}"
''')

_add("src/mid.py", '''"""Mid-tier transformation."""
from src.leaf import render_payload


def transform_data(items):
    """Transform raw items via the leaf renderer."""
    rendered = render_payload(items)
    return rendered.upper()
''')

_add("src/top.py", '''"""Top-level request handling."""
from src.mid import transform_data


def handle_request(req):
    """Handle a request through the transform tier."""
    return transform_data(req.get("items", []))
''')

_add("src/entry.py", '''"""Dispatch entrypoint."""
from src.top import handle_request


def main_dispatch(req):
    """Dispatch an inbound request."""
    return handle_request(req)
''')

_add("src/notifier.py", '''"""Notification base contract."""


class Notifier:
    """Base notifier interface."""

    def send(self, msg):
        """Transport a message."""
        return msg
''')

_add("src/alerting.py", '''"""Alerting implementations."""
from src.notifier import Notifier


class EmailNotifier(Notifier):
    """Email transport with an overridden send."""

    def send(self, msg):
        """Send the message over the email transport."""
        return f"email:{msg}"


def notify_user(msg):
    """Notify a user through the email transport."""
    notifier = EmailNotifier()
    return notifier.send(msg)
''')

_add("tests/test_render.py", '''from src.leaf import render_payload


def test_render_payload():
    assert render_payload([1, 2]) is not None
''')

_add("tests/test_chain.py", '''from src.entry import main_dispatch


def test_full_chain():
    assert main_dispatch({"items": [1]}) is not None
''')

_add("tests/test_alerts.py", '''from src.alerting import notify_user


def test_notify_user():
    assert notify_user("hi") is not None
''')

# Planted symbol edges (file-local qualified names; ground truth by construction).
PLANTED_EDGES: List[Tuple[str, str, str]] = [
    ("transform_data", "render_payload", "calls"),
    ("handle_request", "transform_data", "calls"),
    ("main_dispatch", "handle_request", "calls"),
    ("EmailNotifier", "Notifier", "extends"),
    ("notify_user", "EmailNotifier", "calls"),       # constructor instantiation
    ("notify_user", "EmailNotifier.send", "calls"),
    ("test_render_payload", "render_payload", "calls"),
    ("test_full_chain", "main_dispatch", "calls"),
    ("test_notify_user", "notify_user", "calls"),
]

# Symbols per file, for delete_file expectations.
FILE_SYMBOLS: Dict[str, Set[str]] = {
    "src/leaf.py": {"render_payload"},
    "src/mid.py": {"transform_data"},
    "src/top.py": {"handle_request"},
    "src/entry.py": {"main_dispatch"},
    "src/notifier.py": {"Notifier", "Notifier.send"},
    "src/alerting.py": {"EmailNotifier", "EmailNotifier.send", "notify_user"},
    "tests/test_render.py": {"test_render_payload"},
    "tests/test_chain.py": {"test_full_chain"},
    "tests/test_alerts.py": {"test_notify_user"},
}

TEST_FILES = {"tests/test_render.py", "tests/test_chain.py", "tests/test_alerts.py"}

# Module-level imports of the planted test files (structural import edges are
# part of the engine's allowed relation set, so an importing test FILE is a
# contracted test impact when the imported symbol is impacted).
TEST_FILE_IMPORTS: Dict[str, str] = {
    "tests/test_render.py": "render_payload",
    "tests/test_chain.py": "main_dispatch",
    "tests/test_alerts.py": "notify_user",
}


def is_test_symbol(symbol: str) -> bool:
    """Mirror DiffImpactEngine._is_test_symbol (leading test, trailing Test/IT/Spec)."""
    return symbol.startswith("test") or symbol.endswith(("Test", "Tests", "IT", "Spec"))


# ---------------------------------------------------------------------------
# Scenarios: (name, description, files_after_edit, expected)
# ---------------------------------------------------------------------------

SCENARIOS: List[Dict[str, Any]] = [
    {
        "name": "modify_body",
        "description": "edit a line inside render_payload's body",
        "edits": {"src/leaf.py": ("total = sum(items) * 2", "total = sum(items)")},
        "expected": {
            "files": {"src/leaf.py"},
            "direct_symbols": {"render_payload"},
        },
    },
    {
        "name": "rename_symbol",
        "description": "rename transform_data to transform_data_v2 (def line only)",
        "edits": {"src/mid.py": ("def transform_data_v2(items):", "def transform_data(items):")},
        "expected": {
            "files": {"src/mid.py"},
            "direct_symbols": {"transform_data"},
        },
    },
    {
        "name": "delete_file",
        "description": "delete src/leaf.py from the working tree",
        "delete": "src/leaf.py",
        "expected": {
            "files": {"src/leaf.py"},
            "direct_symbols": {"render_payload"},
        },
    },
    {
        "name": "api_signature_change",
        "description": "add keyword-only retry parameter to handle_request",
        "edits": {"src/top.py": ("def handle_request(req, *, retry: bool = False):",
                                 "def handle_request(req):")},
        "expected": {
            "files": {"src/top.py"},
            "direct_symbols": {"handle_request"},
        },
    },
    {
        "name": "extends_hierarchy",
        "description": "edit Notifier.send body (line also intersects the class node)",
        "edits": {"src/notifier.py": ('return ["sent", msg]', "return msg")},
        "expected": {
            "files": {"src/notifier.py"},
            "direct_symbols": {"Notifier", "Notifier.send"},
        },
    },
    {
        "name": "test_file_edit",
        "description": "tighten the assertion inside test_render_payload",
        "edits": {"tests/test_render.py": ('assert render_payload([1, 2]) == "payload:3"',
                                           "assert render_payload([1, 2]) is not None")},
        "expected": {
            "files": {"tests/test_render.py"},
            "direct_symbols": {"test_render_payload"},
        },
    },
]


def full_expectation(scenario: Dict[str, Any]) -> Dict[str, Set[str]]:
    """Derive the complete expected sets from the planted graph.

    Follows the DiffImpactEngine contract exactly: BFS inward over
    calls/extends/implements/uses/imports from the directly-edited symbols;
    test-shaped closure members are expected under tests (never as callers);
    a planted test FILE is expected when it is itself changed or when it
    imports any impacted symbol (structural import edges are in the engine's
    allowed relation set)."""
    direct = set(scenario["expected"]["direct_symbols"])
    if "delete" in scenario:
        direct |= FILE_SYMBOLS.get(scenario["delete"], set())
    callers, tests = expected_closure(direct, TRAVERSAL_DEPTH)
    impacted = direct | callers | tests
    changed = set(scenario["expected"]["files"])
    test_files = (changed & TEST_FILES) | {
        f for f, sym in TEST_FILE_IMPORTS.items() if sym in impacted
    }
    return {
        "files": changed,
        "direct_symbols": direct,
        "callers": callers,
        "tests": tests,
        "test_files": test_files,
    }

GATES: Dict[str, float] = {
    "macro_symbol_f1": 0.95,
    "macro_test_f1": 0.95,
    "macro_f1": 0.95,
    "files_exact_rate": 0.95,
}
GATE_RATIONALE = (
    "Thresholds were fixed ONCE from the first measured run on the planted "
    "corpus (macro symbol F1 1.00, macro test F1 1.00, macro F1 1.00, files "
    "exact 1.00 — after the R3 deletion-interval fix in diff_impact.py; "
    "before that fix the delete_file scenario scored 0.00 across the board "
    "because whole-file deletions mapped to an empty line interval). The "
    "0.95 floor leaves headroom for cross-platform rank/parsing jitter while "
    "still failing on any real blast-radius regression, including a "
    "reintroduction of the deletion bug. The planted corpus is small by "
    "design; its purpose is regression detection, not capability claims."
)


# ---------------------------------------------------------------------------
# Ground-truth closure over the planted graph (pure, selfcheck-able)
# ---------------------------------------------------------------------------

def expected_closure(direct: Set[str], depth: int) -> Tuple[Set[str], Set[str]]:
    """BFS inward over planted edges with the engine's relation set.

    Returns (non-test callers, test symbols reachable) — mirroring the engine
    contract where test-shaped callers are reported under tests, never as
    production callers."""
    inward: Dict[str, List[Tuple[str, str]]] = {}
    for src, dst, _rel in PLANTED_EDGES:
        if _rel in ENGINE_RELATIONS:
            inward.setdefault(dst, []).append(src)
    callers: Set[str] = set()
    tests: Set[str] = set()
    frontier = set(direct)
    visited = set(direct)
    for _ in range(depth):
        nxt: Set[str] = set()
        for node in frontier:
            for src in inward.get(node, []):
                if src in visited:
                    continue
                visited.add(src)
                if is_test_symbol(src):
                    tests.add(src)
                else:
                    callers.add(src)
                nxt.add(src)
        frontier = nxt
        if not frontier:
            break
    return callers, tests


def prf1(predicted: Set[str], expected: Set[str]) -> Dict[str, float]:
    tp = len(predicted & expected)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(expected) if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


# ---------------------------------------------------------------------------
# Repo / DB harness
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


def build_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".gitignore").write_text(".sot/\n", encoding="utf-8")
    for rel, body in BASE_FILES.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.name", "bench")
    _git(repo, "config", "user.email", "bench@example.com")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "planted base graph")


def apply_scenario(repo: Path, scenario: Dict[str, Any]) -> None:
    if "delete" in scenario:
        (repo / scenario["delete"]).unlink()
        return
    rel, (new, old) = next(iter(scenario["edits"].items()))
    p = repo / rel
    p.write_text(p.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def restore_repo(repo: Path) -> None:
    for rel, body in BASE_FILES.items():
        p = repo / rel
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def classify_result(engine: DiffImpactEngine, result: Any, repo: Path) -> Dict[str, Set[str]]:
    """Project a DiffImpactResult onto (files, direct_symbols, callers, tests, test_files)
    using the engine's own test-classification contract. Paths are relativized
    against the repo root for comparison."""
    def rel(p: str) -> str:
        try:
            return Path(p).resolve().relative_to(repo.resolve()).as_posix()
        except (ValueError, OSError):
            return p

    files = {rel(f) for f in result.changed_files}
    direct_symbols = {n.symbol for n in result.direct_nodes
                      if n.kind != "file" and n.symbol}
    callers: Set[str] = set()
    tests: Set[str] = set()
    test_files: Set[str] = set()
    for c in result.caller_impacts:
        if c.kind == "file" or not c.symbol:
            continue  # file-level import nodes are contract-excluded from symbols
        if engine._is_test_path(c.path) or engine._is_test_symbol(c.symbol):
            tests.add(c.symbol)
        else:
            callers.add(c.symbol)
    for t in result.test_impacts:
        if t.kind == "file":
            test_files.add(rel(t.path))
        elif t.symbol:
            tests.add(t.symbol)
    return {"files": files, "direct_symbols": direct_symbols,
            "callers": callers, "tests": tests, "test_files": test_files}


def corpus_digest() -> str:
    payload = json.dumps({
        "files": {p: BASE_FILES[p] for p in sorted(BASE_FILES)},
        "edges": sorted(PLANTED_EDGES),
        "scenarios": [{k: v for k, v in s.items() if k != "expected"} for s in SCENARIOS],
    }, ensure_ascii=False, sort_keys=True, default=sorted)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_benchmark() -> Dict[str, Any]:
    repo_root = _REPO / ".sot"
    repo_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bench-diff-impact-", dir=repo_root) as directory:
        repo = Path(directory)
        build_repo(repo)
        db_path = repo / ".sot" / "sot.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = Database(str(db_path))
        engine = DiffImpactEngine(db, repo_path=str(repo))
        try:
            Reconciler(db, str(repo)).reconcile(workers=1)
            records: List[Dict[str, Any]] = []
            for scenario in SCENARIOS:
                restore_repo(repo)
                apply_scenario(repo, scenario)
                result = engine.analyze_diff_impact(working_tree=True,
                                                    depth=TRAVERSAL_DEPTH)
                predicted = classify_result(engine, result, repo)
                expected = full_expectation(scenario)
                rec: Dict[str, Any] = {
                    "scenario": scenario["name"],
                    "description": scenario["description"],
                    "predicted": {k: sorted(v) for k, v in predicted.items()},
                    "expected": {k: sorted(v) for k, v in expected.items()},
                }
                rec["files"] = prf1(predicted["files"], expected["files"])
                rec["files"]["exact"] = predicted["files"] == expected["files"]
                rec["symbols"] = prf1(predicted["direct_symbols"] | predicted["callers"],
                                      expected["direct_symbols"] | expected["callers"])
                rec["tests"] = prf1(predicted["tests"] | predicted["test_files"],
                                    expected["tests"] | expected["test_files"])
                records.append(rec)
        finally:
            db.close()

    macro: Dict[str, float] = {}
    for key in ("files", "symbols", "tests"):
        macro[f"{key}_precision"] = round(sum(r[key]["precision"] for r in records) / len(records), 4)
        macro[f"{key}_recall"] = round(sum(r[key]["recall"] for r in records) / len(records), 4)
        macro[f"{key}_f1"] = round(sum(r[key]["f1"] for r in records) / len(records), 4)
    macro["files_exact_rate"] = round(
        sum(1 for r in records if r["files"]["exact"]) / len(records), 4)
    macro_f1 = round(sum(r["symbols"]["f1"] + r["tests"]["f1"] for r in records)
                     / (2 * len(records)), 4)

    measured = {
        "macro_symbol_f1": macro["symbols_f1"],
        "macro_test_f1": macro["tests_f1"],
        "macro_f1": macro_f1,
        "files_exact_rate": macro["files_exact_rate"],
    }
    gate_results = {
        name: {"threshold": GATES[name], "measured": measured[name],
               "passed": measured[name] + 1e-9 >= GATES[name]}
        for name in GATES
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": BENCHMARK,
        "corpus": {
            "digest": corpus_digest(),
            "files": len(BASE_FILES),
            "planted_edges": len(PLANTED_EDGES),
            "scenarios": len(SCENARIOS),
        },
        "config": {"depth": TRAVERSAL_DEPTH, "engine_relations": list(ENGINE_RELATIONS),
                   "mode": "working_tree", "diff": "git -U0"},
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "sqlite": sqlite3.sqlite_version,
            "cpu_count": os.cpu_count(),
        },
        "metrics": {"per_scenario": records, "macro": macro, "macro_f1": macro_f1},
        "gates": {
            "thresholds": dict(GATES),
            "results": gate_results,
            "passed": all(g["passed"] for g in gate_results.values()),
            "rationale": GATE_RATIONALE,
        },
    }


def print_summary(payload: Dict[str, Any]) -> None:
    print("=" * 72)
    print(f"DIFF-IMPACT ORACLE — {payload['corpus']['scenarios']} scenarios, "
          f"depth {payload['config']['depth']}, corpus {payload['corpus']['digest'][:16]}")
    print("=" * 72)
    print(f"  {'scenario':20s} {'sym P':>7s} {'sym R':>7s} {'sym F1':>7s} "
          f"{'test P':>7s} {'test R':>7s} {'test F1':>8s} {'files':>6s}")
    for r in payload["metrics"]["per_scenario"]:
        s, t, f = r["symbols"], r["tests"], r["files"]
        print(f"  {r['scenario']:20s} {s['precision']:7.2f} {s['recall']:7.2f} "
              f"{s['f1']:7.2f} {t['precision']:7.2f} {t['recall']:7.2f} "
              f"{t['f1']:8.2f} {'exact' if f['exact'] else 'MISS':>6s}")
    m = payload["metrics"]["macro"]
    print("-" * 72)
    print(f"  macro symbol P/R/F1 {m['symbols_precision']:.2f}/{m['symbols_recall']:.2f}/"
          f"{m['symbols_f1']:.2f}   test P/R/F1 {m['tests_precision']:.2f}/"
          f"{m['tests_recall']:.2f}/{m['tests_f1']:.2f}   macro_f1 "
          f"{payload['metrics']['macro_f1']:.2f}   files exact "
          f"{m['files_exact_rate']*100:.0f}%")
    gate_block = payload["gates"]
    for name, g in gate_block["results"].items():
        print(f"  gate {name:18s} measured {g['measured']:.2f} >= {g['threshold']:.2f} "
              f"-> {'ok' if g['passed'] else 'FAIL'}")
    print(f"  gates: {'PASS' if gate_block['passed'] else 'FAIL'}")
    for r in payload["metrics"]["per_scenario"]:
        for key in ("direct_symbols", "callers", "tests", "test_files"):
            missed = sorted(set(r["expected"][key]) - set(r["predicted"][key]))
            extra = sorted(set(r["predicted"][key]) - set(r["expected"][key]))
            if missed:
                print(f"  [fn] {r['scenario']}/{key}: missed {missed}")
            if extra:
                print(f"  [fp] {r['scenario']}/{key}: unexpected {extra}")


def run_selfcheck() -> List[str]:
    """Fast offline checks: P/R/F1 math, closure math, one end-to-end run."""
    failures: List[str] = []
    if prf1({"a", "b"}, {"b", "c"}) != {"precision": 0.5, "recall": 0.5, "f1": 0.5}:
        failures.append("prf1 math wrong")
    if prf1(set(), {"a"})["recall"] != 0.0 or prf1(set(), set())["recall"] != 1.0:
        failures.append("prf1 empty-set convention wrong")
    callers, tests = expected_closure({"render_payload"}, TRAVERSAL_DEPTH)
    if callers != {"transform_data", "handle_request", "main_dispatch"}:
        failures.append(f"closure callers wrong: {callers}")
    if tests != {"test_render_payload", "test_full_chain"}:
        failures.append(f"closure tests wrong: {tests}")
    callers, tests = expected_closure({"Notifier"}, TRAVERSAL_DEPTH)
    if callers != {"EmailNotifier", "notify_user"} or tests != {"test_notify_user"}:
        failures.append(f"extends closure wrong: {callers} {tests}")
    callers, _ = expected_closure({"Notifier.send"}, TRAVERSAL_DEPTH)
    if callers:
        failures.append(f"override body closure must be empty: {callers}")

    with tempfile.TemporaryDirectory(prefix="bench-di-selfcheck-") as directory:
        repo = Path(directory)
        build_repo(repo)
        db = Database(str(repo / ".sot" / "sot.db"))
        engine = DiffImpactEngine(db, repo_path=str(repo))
        try:
            Reconciler(db, str(repo)).reconcile(workers=1)
            leaf = repo / "src" / "leaf.py"
            leaf.write_text(leaf.read_text(encoding="utf-8")
                            .replace("total = sum(items)", "total = sum(items) + 1"),
                            encoding="utf-8")
            result = engine.analyze_diff_impact(working_tree=True, depth=2)
            predicted = classify_result(engine, result, repo)
            if "render_payload" not in predicted["direct_symbols"]:
                failures.append("selfcheck body-edit missed direct symbol")
            if "transform_data" not in predicted["callers"]:
                failures.append("selfcheck body-edit missed 1-hop caller")
        finally:
            db.close()
    return failures


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=_REPO / "benchmarks" / "diff-impact-oracle.json",
                        help="output JSON path (default benchmarks/diff-impact-oracle.json)")
    parser.add_argument("--gate", action="store_true",
                        help="exit 1 when any oracle gate threshold fails")
    parser.add_argument("--selfcheck", action="store_true",
                        help="run offline self-checks and exit")
    args = parser.parse_args(argv)

    if args.selfcheck:
        failures = run_selfcheck()
        if failures:
            print("SELF-CHECK FAILED:")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("self-check: OK (prf1 math, planted closure, real-engine mini run)")
        return 0

    payload = run_benchmark()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print_summary(payload)
    print(f"\nWritten to: {args.json}")
    return 0 if payload["gates"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
