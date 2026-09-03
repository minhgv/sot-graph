# Module-Scope Evaluation Report

Generated: 2026-09-04 02:44:28  |  commit: `4b6d0bb`

| Scope | ruff | pyright | pytest | probes (bugs) | gate |
|---|---|---|---|---|---|
| sync-healing | ✅ | ✅ | — | 4 (0) | PASS |

**Probes: 0 bug(s) still present, 0 probe error(s).**

## Probes — sync-healing
- ✅ `polling-deferred-drop` — P1 watcher.py:154 — OK (790ms)
  - LockBusy-deferred path re-published via cross-cycle carry-over
- ✅ `watchfiles-pending-carryover` — P1 watcher.py:76 — OK (0ms)
  - pending is unioned into the next batch and fed from deferred
- ✅ `watcher-unsupported-churn` — P2 reconciler.py:508 — OK (77ms)
  - unsupported binary excluded at the gate; never journaled
- ✅ `jit-fresh-despite-failed-reconcile` — P1 verifier.py:416 — OK (27ms)
  - freshness=FreshnessStatus.STALE gated on reconcile outcome
