#!/usr/bin/env python3
"""Deterministic context-cost benchmark: `sot pack` vs naive whole-file reads.

For each target symbol this measures the two retrieval protocols an agent
could use for a deep-dive task:
  - pack: ContextBundle YAML (k-hop slice, signature stubs, source span)
  - naive: read every whole file touched by the same k-hop neighbourhood
    (the grep-then-read sprawl baseline)

Token cost is estimated as bytes/4 for code-shaped text. Fully offline and
reproducible — the LLM-in-the-loop D1-vs-D2 protocol from the research
sessions lives in docs/BENCHMARKS.md; this script is its deterministic core.

Usage:
  python3 scripts/benchmark_context.py [--targets a,b] [--json] [--root DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def measure(db, root: str, target: str) -> dict | None:
    from sot_graph.pack import PackError, build_bundle, render_yaml

    try:
        bundle = build_bundle(db, root, target)
    except PackError as exc:
        return {"target": target, "error": str(exc)}

    yaml_text = render_yaml(bundle)
    pack_tokens = _tokens(yaml_text)

    paths = {bundle["target"].get("relative_path")}
    for key in ("inbound_callers", "outbound_callees", "transitive_stubs"):
        for entry in bundle.get(key) or []:
            rel = entry.get("relative_path")
            if rel:
                paths.add(rel)

    naive_bytes = 0
    files_read = 0
    for rel in sorted(p for p in paths if p):
        candidate = rel if os.path.isabs(rel) else os.path.join(root, rel)
        if os.path.isfile(candidate):
            naive_bytes += os.path.getsize(candidate)
            files_read += 1
    naive_tokens = naive_bytes // 4

    saved = round(100 * (1 - pack_tokens / naive_tokens), 1) if naive_tokens else 0.0
    return {
        "target": target,
        "pack_tokens": pack_tokens,
        "naive_tokens": naive_tokens,
        "naive_files": files_read,
        "saved_percent": saved,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--targets", default=",".join([
        "Database.commit_file_batch", "build_bundle", "parse_file_graph",
    ]), help="Comma-separated target symbols")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--root", default=os.getcwd(), help="Project root (default: cwd)")
    args = parser.parse_args(argv)

    from sot_graph.cli import default_db_path
    from sot_graph.db import Database

    db_path = default_db_path(args.root)
    if not os.path.isfile(db_path):
        print(f"❌ No index at {db_path} — run `sot reconcile` first.", file=sys.stderr)
        return 2
    db = Database(db_path)
    try:
        rows = [measure(db, args.root, t.strip())
                for t in args.targets.split(",") if t.strip()]
    finally:
        db.close()

    rows = [r for r in rows if r]
    if args.json:
        print(json.dumps({"results": rows}, indent=2))
        return 0

    print(f"{'target':<32} {'pack':>8} {'naive':>8} {'files':>6} {'saved':>7}")
    print("-" * 66)
    for row in rows:
        if "error" in row:
            print(f"{row['target']:<32} {'ERROR: ' + row['error'][:38]}")
            continue
        print(f"{row['target']:<32} {row['pack_tokens']:>8} {row['naive_tokens']:>8} "
              f"{row['naive_files']:>6} {row['saved_percent']:>6}%")
    print("-" * 66)
    ok = [r for r in rows if "error" not in r]
    if ok:
        avg = sum(r["saved_percent"] for r in ok) / len(ok)
        print(f"average saved: {avg:.1f}%  (tokens estimated as bytes/4)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
