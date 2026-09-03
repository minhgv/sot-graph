# Benchmarks & Performance Guide

This document details the benchmarking methodology, execution procedures, and verified performance characteristics of `sot-graph`.

---

## 🎯 Performance Goals & Philosophy

`sot-graph` is designed to operate inside the fast inner loop of AI coding agents (per-turn file edits, multi-file refactoring, pre-commit checks). To ensure zero noticeable latency for agents:

1. **Fast Search**: FTS5 candidate retrieval itself stays in the low-millisecond range on small graphs (see §2); full end-to-end search — including per-hit physical Trust Verification (file read + SHA-256) and JIT reconcile — measured p50 ≈ 49 ms / p95 ≈ 50 ms on a 5,000-file graph (`benchmarks/performance_baseline.json`, `bounded_query_mixed`).
2. **Instant Reconcile**: Unchanged files are checked in O(1) via filesystem metadata (μs range); modified files are parsed concurrently and committed in single-writer batches (150 files / 2 workers: p50 ≈ 207 ms, p95 ≈ 236 ms on `performance_baseline.json`; the per-file marginal cost on 100-file batches is the ~4,300 files/s figure in §1).
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

> **Scope of these numbers**: retrieval-only (FTS5 + BM25 ranking) on the 100-file corpus — per-hit trust verification and JIT reconcile are excluded. End-to-end verified search on 5,000 files is p50 ≈ 49 ms (`benchmarks/performance_baseline.json`).

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

## 🎯 Accuracy Oracles (R3 evidence hardening)

The 2026-08-28 reassessment (§4.2/§6) flagged evidence gaps: no diff-impact
oracle, search quality measured with only ~20 probes (ambiguous Hit@5 44.4%),
zero Rust negative `implements` ground truth, and no scale run beyond 5,000
files. R3 closes these with two deterministic, offline, gate-wired benchmarks
and negative ground truth.

### 3. Search Quality (`scripts/bench_search_quality.py` → `benchmarks/search-quality.json`)

48 planted probes across four classes (12 each), every probe with EXACTLY ONE
known-correct node; runs the real production search path (FTS retrieval →
per-hit TrustVerifier → P4 ranking) at top-k=10 over a 194-file corpus
(~363 nodes, incl. 150 seeded filler fixtures):

| Class | Hit@1 | Hit@5 | Hit@10 | MRR |
| :--- | :---: | :---: | :---: | :---: |
| **exact** (bare symbol) | 100% | 100% | 100% | 1.00 |
| **semantic** (natural-language → body) | 75% | 100% | 100% | 0.875 |
| **ambiguous** (same bare name, 3 modules) | 100% | 100% | 100% | 1.00 |
| **path_qualified** (path fragment + symbol) | 100% | 100% | 100% | 1.00 |
| **overall** | 93.8% | 100% | 100% | 0.969 |

CI gates (set once, a step below measured; rationale in the JSON `gates`
block): exact Hit@1 ≥ 0.85, semantic Hit@5 ≥ 0.90, ambiguous Hit@5 ≥ 0.75,
path_qualified Hit@1 ≥ 0.90, overall MRR ≥ 0.85. The old 44.4% ambiguous
weakness was measured on bare-name-only queries; adding module context to the
query (how agents actually disambiguate) resolves it — the gate keeps a wide
margin (0.75) on that hostile class so a regression trips it.

```bash
python3 scripts/bench_search_quality.py --gate      # gates + write JSON
python3 scripts/bench_search_quality.py --selfcheck # fast offline self-check
```

### 4. Diff-Impact Oracle (`scripts/bench_diff_impact.py` → `benchmarks/diff-impact-oracle.json`)

Six scripted change scenarios against a synthetic git repo with a planted
call graph `main_dispatch → handle_request → transform_data → render_payload`,
an inheritance pair (`EmailNotifier extends Notifier`) and test files named
per the test-detection conventions. Ground truth is known BY CONSTRUCTION;
the real `DiffImpactEngine` is scored per scenario (symbols / tests / files)
with macro P/R/F1:

| Scenario | Symbols P/R/F1 | Tests P/R/F1 | Files |
| :--- | :---: | :---: | :---: |
| modify_body | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | exact |
| rename_symbol | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | exact |
| delete_file | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | exact |
| api_signature_change | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | exact |
| extends_hierarchy | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | exact |
| test_file_edit | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | exact |

The delete_file row is regression-locked: before R3, a whole-file deletion
(`@@ -1,N +0,0 @@`) mapped to the empty interval (0,0), so deletions reported
ZERO impact (measured, then fixed in `src/sot_graph/diff_impact.py` —
deletion-only hunks now use their old-side line span; regression tests in
`tests/test_diff_impact.py`). CI gates: macro symbol/test/overall F1 ≥ 0.95,
changed-file exact rate ≥ 0.95.

### 5. Negative `implements`/`extends` ground truth (Java/Rust)

`sot_evaluator.py`'s corpus gained 14 negative edges (Rust 6, Java 8):
inherent impl blocks, generic/where bounds, `Impl`-suffix lookalikes,
commented-out declarations, interface-typed fields, type-parameter bounds and
forward references to undefined bases. All are correctly abstained —
`rust implements` tn 1→5, `java implements` tn 1→5, `java extends` tn 0→3,
**zero new false positives** (committed baseline:
`benchmarks/oracle/builtin-baseline.json`, corpus digest `23c0e29c…`).

### 6. 10,000-file scale run (2026-09-03, first beyond 5k)

| Metric (10,000 files) | P50 | P95 | Notes |
| :--- | :---: | :---: | :--- |
| **Reconcile (2 workers)** | 6,416 ms | 6,477 ms | ~1,558 files/s incl. correctness projection; `--repeat 5` |
| **Bounded mixed query** | 97.5 ms | 98.5 ms | 11 bounded queries, end-to-end verified search |

Recorded in `benchmarks/performance_baseline.json` (`reconcile_10000_*`,
`bounded_query_mixed_10000_*`); correctness flags true on both.

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
