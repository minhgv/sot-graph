# Module-Scope Evaluation Report

Generated: 2026-09-04 00:37:48  |  commit: `d0c5bb9`

| Scope | ruff | pyright | pytest | probes (bugs) | gate |
|---|---|---|---|---|---|
| assurance | ✅ | ✅ | ✅ | 2 (0) | PASS |
| core-storage | ✅ | ✅ | ✅ | 2 (0) | PASS |
| extraction | ✅ | ✅ | ✅ | 1 (0) | PASS |
| query-analytics | ✅ | ✅ | ✅ | 2 (0) | PASS |
| surfaces | ✅ | ✅ | ✅ | 1 (0) | PASS |
| sync-healing | ✅ | ✅ | ✅ | 4 (0) | PASS |

**Probes: 0 bug(s) still present, 0 probe error(s).**

## Probes — assurance
- ✅ `coverage-mtime-false-stale` — P1 coverage.py:229 — OK (39ms)
  - state=unknown (sha-based staleness consistent)
- ✅ `tests-to-run-none` — P1 receipts.py:563 — OK (4ms)
  - tests_to_run reads TestImpact.path; no 'test_file' reference

## Probes — core-storage
- ✅ `journal-like-wildcard` — P1 db.py:676 — OK (5ms)
  - wildcard path did not match a different journal row
- ✅ `manifest-digest-collapse` — P1 envelope.py:29 — OK (1ms)
  - fail-closed, states distinguishable: ['<raised:OperationalError>', '<raised:ProgrammingError>']

## Probes — extraction
- ✅ `nested-gitignore` — P2 ignore.py:101,184 — OK (1ms)
  - scoped rules anchored correctly and nested files loaded

## Probes — query-analytics
- ✅ `solution-fabricated-template` — P1 solution.py:426 — OK (4ms)
  - no fabricated template for unknown symbol
- ✅ `repo-map-dead-helper` — P2 repo_map.py:133 — OK (77ms)
  - _estimate_tokens resolves its constant

## Probes — surfaces
- ✅ `cli-hybrid-scope-ignored` — P1 cli.py:210 — OK (43ms)
  - hybrid search honors scope (or rejects the combination)

## Probes — sync-healing
- ✅ `polling-deferred-drop` — P1 watcher.py:154 — OK (687ms)
  - LockBusy-deferred path re-published via cross-cycle carry-over
- ✅ `watchfiles-pending-carryover` — P1 watcher.py:76 — OK (0ms)
  - pending is unioned into the next batch and fed from deferred
- ✅ `watcher-unsupported-churn` — P2 reconciler.py:508 — OK (7ms)
  - unsupported binary excluded at the gate; never journaled
- ✅ `jit-fresh-despite-failed-reconcile` — P1 verifier.py:416 — OK (14ms)
  - freshness=FreshnessStatus.STALE gated on reconcile outcome
