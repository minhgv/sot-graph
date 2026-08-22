"""Benchmark reconciliation throughput and gate worker-count correctness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
for _path in (_REPO / "src", _REPO / "vendor"):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from benchmarks.fixtures import (  # noqa: E402
    correctness_projection,
    environment_fingerprint,
    generate_fixture,
    jsonable,
)
from sot_graph.db import Database  # noqa: E402
from sot_graph.reconciler import Reconciler  # noqa: E402


def _percentile(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) * percentile + 0.999999) - 1)))
    return ordered[index]


def _summary_dict(summary: Any) -> dict[str, Any]:
    return jsonable(summary) if hasattr(summary, "__dataclass_fields__") else dict(summary)


def _run_once(root: Path, workers: int, batch_size: int, queries: tuple[str, ...]) -> tuple[dict[str, Any], dict[str, Any]]:
    db_path = root / ".sot" / "sot.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(db_path) + suffix)
        if candidate.exists():
            candidate.unlink()
    db = Database(str(db_path))
    try:
        reconciler = Reconciler(db, str(root))
        summary = reconciler.scan_and_reconcile(workers=workers, batch_size=batch_size)
        projection = correctness_projection(db, queries)
        return _summary_dict(summary), projection
    finally:
        db.close()


def _measure(root: Path, workers: int, batch_size: int, repeat: int, queries: tuple[str, ...]) -> dict[str, Any]:
    warmup_summary, warmup_projection = _run_once(root, workers, batch_size, queries)
    del warmup_summary, warmup_projection
    samples: list[int] = []
    last_summary: dict[str, Any] = {}
    last_projection: dict[str, Any] = {}
    for _ in range(repeat):
        start = time.perf_counter_ns()
        last_summary, last_projection = _run_once(root, workers, batch_size, queries)
        samples.append(time.perf_counter_ns() - start)
    return {
        "workers": workers,
        "batch_size": batch_size,
        "repeat": repeat,
        "warmup": True,
        "samples_ns": samples,
        "median_ms": statistics.median(samples) / 1_000_000,
        "p95_ms": _percentile(samples, 0.95) / 1_000_000,
        "min_ms": min(samples) / 1_000_000,
        "summary": last_summary,
        "projection": last_projection,
    }


def run(files: int, workers: list[int], batch_size: int, repeat: int, seed: int) -> dict[str, Any]:
    if files < 1 or repeat < 1 or batch_size < 1 or not workers or any(item < 1 for item in workers):
        raise ValueError("files, repeat, batch_size, and workers must be positive")
    runtime_parent = _REPO / ".sot"
    runtime_parent.mkdir(parents=True, exist_ok=True)
    queries = ("fixture", f"fixture_{seed}_0", f"fixture_{seed}_10")
    with tempfile.TemporaryDirectory(prefix="bench-reconcile-", dir=runtime_parent) as directory:
        root = Path(directory)
        generated = generate_fixture(root, files=files, seed=seed)
        baseline_summary, baseline_projection = _run_once(root, workers[0], batch_size, queries)
        results: list[dict[str, Any]] = []
        for worker_count in workers:
            item = _measure(root, worker_count, batch_size, repeat, queries)
            item["correctness"] = item["projection"] == baseline_projection
            results.append(item)
        return {
            "schema_version": 1,
            "benchmark": "reconcile",
            "config": {
                "files": files,
                "workers": workers,
                "batch_size": batch_size,
                "repeat": repeat,
                "seed": seed,
            },
            "environment": environment_fingerprint(
                files=files,
                workers=workers,
                batch_size=batch_size,
                repeat=repeat,
                seed=seed,
                generated_bytes=sum((root / path).stat().st_size for path in generated),
            ),
            "correctness": {
                "baseline_workers": workers[0],
                "baseline_summary": baseline_summary,
                "all_passed": all(item["correctness"] for item in results),
            },
            "results": results,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=5000)
    parser.add_argument("--workers", default="1,2,4,8", help="comma-separated worker counts")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20250219)
    parser.add_argument("--json", type=Path, default=None, help="write JSON results to this path")
    args = parser.parse_args(argv)
    worker_counts = [int(value) for value in args.workers.split(",") if value.strip()]
    payload = run(args.files, worker_counts, args.batch_size, args.repeat, args.seed)
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if payload["correctness"]["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
