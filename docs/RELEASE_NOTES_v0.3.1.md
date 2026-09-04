# Release Notes — v0.3.1 (2026-09)

First publicly installable release (`pip install sot-graph`, see
[RELEASE.md](RELEASE.md) for the trusted-publishing runbook). This version
lands the post-audit remediation roadmap (G7–G10) and the R1–R5 gap-closure
roadmap from the 2026-09 ecosystem assessment.

## Highlights

- **CI-native blast radius**: `sot diff-impact --format github` renders a
  PR-safe report, and the reusable composite action
  `.github/actions/diff-impact` posts/updates an idempotent PR comment
  (dogfooded by `.github/workflows/diff-impact.yml`; see
  [CI_INTEGRATION.md](CI_INTEGRATION.md)).
- **MCP prompts**: `sot_deep_dive` (embeds a token-budgeted ContextBundle)
  and `sot_refactor_checklist` (embeds a PRE-change scope receipt) join the
  22 read tools and 3 resources.
- **Provider cross-check**: `sot providers cross-check` compares builtin AST
  edges against external provider evidence (agreements / builtin-only /
  external-only) with normalized relations.
- **Real release path**: PyPI trusted publishing wired into CI; releases now
  require the accuracy-oracle job; `module_eval --strict-probes` fails
  closed on probe crashes; test matrix extended to Python 3.13/3.14.

## Performance

- Watcher debounce batches now run the global pending-edge resolver and
  orphan janitor **once per batch** instead of once per file (a branch
  switch touching N files costs one full-graph pass, not N).
- `explore_node` BFS is level-batched (chunked `IN` queries per hop);
  rehome healing caches its basename walk per heal pass; `_fits_response`
  is single-pass incremental instead of O(n²) re-serialization.
- Ledger history retention: `sot providers sync` prunes to the newest 10
  runs per provider and 20 unreferenced snapshots per repo
  (`snapshots`/`provider_runs`/`provider_evidence` no longer grow
  unbounded).
- 10,000-file scale run recorded: reconcile p50 6.4 s (~1,560 files/s incl.
  projection), verified search p50 97.5 ms (`benchmarks/performance_baseline.json`).

## Evidence hardening

- **Search-quality benchmark** (48 probes × 4 query classes, Hit@1/5/10 +
  MRR, CI-gated) and **diff-impact oracle** (6 scenarios, ground truth by
  construction, macro P/R/F1, CI-gated).
- +14 Rust/Java negative `implements`/`extends` ground-truth cases — zero
  misresolutions (previously Rust had zero negatives).
- Fixed a real bug the new oracle exposed immediately: whole-file deletions
  mapped to an empty interval, reporting zero impacted nodes/callers/tests.

## Trust truth-telling (audit P2 debt)

- Post-change receipts no longer silently cap cited files at 200:
  `changed_files_total` / `changed_files_truncated` (receipt schema 1.2) plus
  an explicit partial-closure warning; oversized diffs degrade to PARTIAL.
- `verify_drift` MCP calls are cancellable between files; SCIP decoding
  stays loud on truncation; vector embedding is incremental and never
  silently rotates past its cap.

## Internal

- Windows Job Object process-tree kill (G9), append-only ledger with
  `synchronous=FULL` commits (G8), strict module-eval CI gate (G7).
- Full suite: **1014 collected** (1012 pass / 2–3 skips: 2 win32-only + 1
  Bun-dependent adapter test that skips when Bun is not installed);
  module-eval 6 scopes × ruff/pyright/pytest + 12 probes all green.
