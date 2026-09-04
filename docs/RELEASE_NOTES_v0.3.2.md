# Release Notes — v0.3.2 (2026-09)

Truth/surface fixes only (commit range `523e9cf..c9c5107`): every place the
tool *claims* something about a diff, an assurance verdict, or a metric now
matches what it actually measured. No new features beyond the honest-surface
work below.

## Highlights

- **PR diff-impact bot analyzes the true merge-base range** (SG-101/102/103):
  the reusable action now computes `base...head` from the merge-base instead
  of the single-revision `R~1 R` pair — a 50-file PR range was previously
  reported as 2 changed files.
- **Truncation can no longer keep an ASSURED verdict** (SG-104): any trimmed
  collection re-runs the canonical `decide()` with `facts.truncated=True`, so
  `returned_count < enumerated_count` always degrades the receipt.
- **Evaluator regression gate** (SG-106): `sot eval-oracle --gate` enforces
  per language×relation precision/recall floors from the baseline (−
  tolerance) plus a clean-bucket regression rule and exits 1 on regression;
  the CI accuracy job now runs it.

## PR diff-impact bot (SG-101/102/103)

- Range correctness: changed-file enumeration uses the true merge-base
  range `base...head` (verified: the `2666c583...HEAD` smoke reports 50
  changed files where the old single-rev read reported 2).
- The workflow dogfoods the PR checkout for `minhgv/sot-graph`; external
  consumers can pin a released build with the new `pypi-version` input, and
  the harmful consumer-repo git fallback was removed.
- The posted GitHub comment now renders the receipt honestly: assurance
  status, reason codes, coverage, truncation flags, snapshot head, and the
  resolved analysis range.
- "Low ripple effect" is only claimed when the receipt is ASSURED.
- New `--gate` exit semantics: the gate exit code (1 on regression) is
  separate from the advisory exit 0, so CI can fail closed without breaking
  advisory use.

## MCP honesty (SG-104 + default parity)

- Transport truncation invariant: if any response collection is trimmed, the
  canonical `decide()` re-runs with `facts.truncated=True` — a trimmed
  response can never keep `ASSURED_WITHIN_SCOPE`. Per-collection counts are
  exposed so the gap is visible. Regression test reproduces the
  400→13 counterexample.
- `diff_impact` / `diff_impact_receipt` MCP tools now default to
  `target=HEAD` (matching the CLI) instead of `HEAD~1`.

## Exact-oracle regression gate (SG-106)

- `--gate`: per language×relation P/R floors derived from the baseline minus
  tolerance, plus a clean-bucket regression rule; exit 1 on regression.
- Baseline JSON normalized to corpus-relative paths; metrics identical
  (TP 1007 / FN 5 / FP 2 / TN 123; macro P 99.8 / R 99.5 / F1 99.7).
- The CI accuracy job runs the evaluator with `--gate`.

## Docs bounded to evidence (SG-110)

- README advisory phrasing aligned with reality; the accuracy badge now
  states the enforced floors (≥85% precision / ≥90% recall), not peak
  metrics.
- `RELEASE_DECISION` superseded → CONDITIONAL_GO / HUMAN_GATED; Tier-A
  ceiling marked VERIFIED_PRESENCE.
- AGENTS.md deduplicated 257 → 101 lines and pinned to schema v8.

## Verification

- Full suite: **1047 passed / 2 skipped** (35 new tests).
- Quality gates green: core 86% / receipts 91% coverage.
- Diff-impact smoke on `2666c583...HEAD`: 50 changed files with an honest
  assurance block.

## Known limitations (unchanged)

`diff-impact` remains an **advisory** tool: it is not an autonomous
assurance gate. The new `--gate` flags are explicit, human-opt-in fail-closed
semantics.
