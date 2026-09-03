# Module-Scope Evaluation Report

Generated: 2026-09-04 04:44:11  |  commit: `1a758c2`

| Scope | ruff | pyright | pytest | probes (bugs) | gate |
|---|---|---|---|---|---|
| assurance | ✅ | ✅ | — | 2 (0) | PASS |

**Probes: 0 bug(s) still present, 0 probe error(s).**

## Probes — assurance
- ✅ `coverage-mtime-false-stale` — P1 coverage.py:229 — OK (34ms)
  - state=unknown (sha-based staleness consistent)
- ✅ `tests-to-run-none` — P1 receipts.py:563 — OK (8ms)
  - tests_to_run reads TestImpact.path; no 'test_file' reference
