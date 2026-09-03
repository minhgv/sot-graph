# Benchmarks & Performance Guide

This document details the benchmarking methodology, execution procedures, and verified performance characteristics of `sot-graph`.

---

## 🎯 Performance Goals & Philosophy

`sot-graph` is designed to operate inside the fast inner loop of AI coding agents (per-turn file edits, multi-file refactoring, pre-commit checks). To ensure zero noticeable latency for agents:

1. **Sub-millisecond Search**: Candidate retrieval and trust scoring must take < 2 ms.
2. **Instant Reconcile**: Unchanged files are checked in O(1) via filesystem metadata (μs range); modified files are parsed concurrently and committed in single-writer batches (< 30 ms for 100 files).
3. **Ultra-Low Memory Footprint**: Core operations run under 25 MB RSS with zero external background daemons.

---

## 📊 Verified Benchmark Results

### Environment Fingerprint
- **Hardware**: Apple M1 Max (10-core CPU, 64GB Unified Memory)
- **OS**: macOS Sonoma (Darwin 25.3.0) / Linux Kernel 6.x
- **Python**: Python 3.14 / 3.10+
- **Database Engine**: SQLite 3.46+ (WAL mode + FTS5, page size 4096, synchronous NORMAL)

---

### 1. Reconciliation Throughput & Worker Scaling (`bench_reconcile`)

Evaluates parsing, SHA-256 dirty checking, node/edge generation, and SQLite single-writer commit batching across worker pool sizes (1, 2, 4, 8 workers) on 100 generated multi-language source files (Python, TypeScript, Go, Rust, Dart, Markdown):

| Configuration | Min (ms) | Median (ms) | P95 (ms) | Max (ms) | Throughput (files/sec) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Sequential (1 worker)** | 22.85 | **23.10** | 24.07 | 24.68 | ~4,330 files/s |
| **Parallel (2 workers)** | 28.12 | 29.40 | 31.25 | 32.10 | ~3,400 files/s |
| **Parallel (4 workers)** | 35.40 | 37.10 | 39.80 | 41.20 | ~2,700 files/s |
| **Parallel (8 workers)** | 48.20 | 50.15 | 53.40 | 55.60 | ~2,000 files/s |

> **Adaptive Worker Threshold Invariant**: For small-to-medium batches (< 16 files), `sot-graph` automatically switches to in-process sequential parsing to avoid OS process spawn / IPC overhead. For large batches (> 100 files), parallel worker pools scale horizontally.

---

### 2. Query Latency & FTS5 BM25 Retrieval (`bench_query`)

Evaluates cold and warm query latency for FTS5 full-text indexing, BM25 rank scoring, and physical disk Trust Verification checks:

| Query Type | Median (ms) | P95 (ms) | P99 (ms) | Memory RSS |
| :--- | :---: | :---: | :---: | :---: |
| **Exact Symbol Search** (`sot search "Database"`) | 0.82 | 1.15 | 1.34 | < 18 MB |
| **Multi-token Fuzzy Query** (`sot search "reconcile file"`) | 0.95 | 1.22 | 1.48 | < 20 MB |
| **Scoped Path Query** (`--scope src/sot_graph`) | 0.78 | 1.08 | 1.25 | < 18 MB |
| **Call Graph Traversal** (`sot explore "Reconciler" --depth 2`) | 1.10 | 1.45 | 1.80 | < 22 MB |

---

## 🛠️ Reproducing Benchmarks Locally

`sot-graph` includes a fully deterministic, self-contained benchmark suite in `benchmarks/`:

### Run Reconcile Benchmark
```bash
# Test 100 files with 3 repetitions across worker configurations
PYTHONPATH=".:src" python3 -m benchmarks.bench_reconcile --files 100 --repeat 3

# Test 1,000 files with custom worker counts and JSON export
PYTHONPATH=".:src" python3 -m benchmarks.bench_reconcile --files 1000 --workers 1,2,4,8 --repeat 5 --json reconcile_results.json
```

### Run Query Latency Benchmark
```bash
# Test query latency against 100 generated nodes
PYTHONPATH=".:src" python3 -m benchmarks.bench_query --files 100 --repeat 5

# Export query performance profile to JSON
PYTHONPATH=".:src" python3 -m benchmarks.bench_query --files 500 --repeat 5 --json query_results.json
```

---

## 💡 Performance Optimization Best Practices

1. **Keep Database on Local SSD**: SQLite WAL mode thrives on NVMe / SSD random I/O.
2. **Periodic Maintenance**:
   - Run `sot clean --all` to purge stale paths from renamed/deleted files.
   - Run `sot vacuum --analyze` to checkpoint WAL logs and update SQLite query planner statistics.
3. **Use Scoped Searches for Massive Repositories**:
   - `sot search "query" --scope <subfolder>` restricts FTS candidate generation to relevant modules.

---

## 📦 Context-Cost Benchmark (v3, deterministic)

The LLM-in-the-loop protocol (sub-agent D1 pack vs D2 grep: 18.8k vs 58.6k tokens,
−68%, 0 vs 2 dead paths) motivated a reproducible offline harness:

```bash
python3 scripts/benchmark_context.py            # defaults to 3 core targets
python3 scripts/benchmark_context.py --targets build_bundle,parse_file_graph --json
```

Method: for each target, compare `sot pack` YAML tokens (k-hop slice: source span
+ caller/callee contracts + signature stubs) against the naive protocol of reading
every whole file in the same k-hop neighbourhood (the grep-then-read baseline).
Tokens estimated as bytes/4. No LLM, no network — numbers are stable across runs.

Results on this repository (2026-08-23, 138 tests green):

| Target | pack | naive | files | saved |
|---|---|---|---|---|
| Database.commit_file_batch | 1,680 | 10,388 | 1 | 83.8% |
| build_bundle | 3,375 | 29,377 | 6 | 88.5% |
| parse_file_graph | 3,442 | 17,624 | 6 | 80.5% |
| **average** | | | | **84.3%** |

Notes:
- Micro-repos (<5 tiny files) can invert the ratio because the bundle's structural
  YAML outweighs file bytes; the harness reports the numbers honestly either way.
- The LLM protocol adds dead-path avoidance on top (0 vs 2 dead paths measured),
  which the deterministic core cannot capture.
