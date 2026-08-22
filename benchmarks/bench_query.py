"""Benchmark bounded FTS search and graph exploration queries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
for _path in (_REPO / "src", _REPO / "vendor"):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from benchmarks.fixtures import environment_fingerprint, generate_fixture, jsonable  # noqa: E402
from sot_graph.db import Database  # noqa: E402
from sot_graph.reconciler import Reconciler  # noqa: E402


def _percentile(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) * percentile + 0.999999) - 1)))
    return ordered[index]


def _connection(db: Any) -> Any:
    connection = getattr(db, "_conn", None) or getattr(db, "conn", None)
    if connection is None:
        raise AttributeError("Database does not expose its connection")
    return connection


def _query_once(db: Database, search_queries: tuple[str, ...], node_ids: tuple[str, ...]) -> dict[str, Any]:
    search = {query: db.search_fts(query, limit=10) for query in search_queries}
    explored = {node_id: db.explore_node(node_id, depth=1, limit=100) for node_id in node_ids}
    return {"search": search, "explore": explored}


def run(files: int, repeat: int, batch_size: int, seed: int) -> dict[str, Any]:
    if files < 1 or repeat < 1 or batch_size < 1:
        raise ValueError("files, repeat, and batch_size must be positive")
    runtime_parent = _REPO / ".sot"
    runtime_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bench-query-", dir=runtime_parent) as directory:
        root = Path(directory)
        generated = generate_fixture(root, files=files, seed=seed)
        db_path = root / ".sot" / "sot.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = Database(str(db_path))
        try:
            summary = Reconciler(db, str(root)).scan_and_reconcile(workers=1, batch_size=batch_size)
            search_queries = ("fixture", f"fixture_{seed}_0", f"fixture_{seed}_10")
            rows = _connection(db).execute("SELECT id FROM graph_nodes ORDER BY id LIMIT 8").fetchall()
            node_ids = tuple(str(row[0]) for row in rows)
            warmup = _query_once(db, search_queries, node_ids)
            del warmup
            samples: list[int] = []
            last: dict[str, Any] = {}
            for _ in range(repeat):
                start = time.perf_counter_ns()
                last = _query_once(db, search_queries, node_ids)
                samples.append(time.perf_counter_ns() - start)
            return {
                "schema_version": 1,
                "benchmark": "query",
                "config": {"files": files, "repeat": repeat, "batch_size": batch_size, "seed": seed},
                "environment": environment_fingerprint(
                    files=files,
                    repeat=repeat,
                    batch_size=batch_size,
                    seed=seed,
                    generated_bytes=sum((root / path).stat().st_size for path in generated),
                    host_kernel=platform.release(),
                ),
                "reconcile_summary": jsonable(summary),
                "query_count": len(search_queries) + len(node_ids),
                "samples_ns": samples,
                "median_ms": statistics.median(samples) / 1_000_000,
                "p95_ms": _percentile(samples, 0.95) / 1_000_000,
                "min_ms": min(samples) / 1_000_000,
                "correctness": bool(last),
                "result_sample": jsonable(last),
            }
        finally:
            db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=5000)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--seed", type=int, default=20250219)
    parser.add_argument("--json", type=Path, default=None, help="write JSON results to this path")
    args = parser.parse_args(argv)
    payload = run(args.files, args.repeat, args.batch_size, args.seed)
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if payload["correctness"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
