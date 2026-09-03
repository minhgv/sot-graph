# CI Integration: PR-Native Blast Radius Bot (R4)

`sot diff-impact --format github` renders a PR-comment-optimized report:
a top-line risk verdict, collapsed `<details>` sections for blast radius,
callers and affected tests, zero ANSI escapes, repo-relative paths only,
and deterministic row ordering. The composite action in this repository
wraps it into a dependency-light GitHub workflow (only `gh`, `git`, and
`pip`/`uv` — all preinstalled on GitHub runners).

## 1. Use the action from another repository

Copy `.github/actions/diff-impact/` into your repo (or reference it after
checking out sot-graph), then:

```yaml
name: blast-radius
on:
  pull_request:
    branches: [main]

permissions:
  contents: read
  pull-requests: write

jobs:
  blast-radius:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # so the PR base sha is local
      - uses: ./.github/actions/diff-impact
        with:
          # PRs check out the merge commit; the base sha is the right target.
          base: ${{ github.event.pull_request.base.sha }}
          format: github          # default
          install-extra: ''       # pip extras for the repo-fallback install
```

Behavior:

- Installs `sot-graph` from PyPI (`uv tool install`, then `pip`), falling
  back to `pip install git+<this repo>` when PyPI is unavailable/lagging.
- Runs `sot reconcile --workers 4`, then
  `sot diff-impact <base> --format github` (engine steps fail the job).
- Posts one idempotent PR comment (anchored on the
  `<!-- sot-diff-impact -->` marker) and edits it on subsequent pushes
  (comment step is tolerant: `continue-on-error: true`).
- Outside a `pull_request` context the report is appended to
  `$GITHUB_STEP_SUMMARY` instead.

## 2. Local dogfood workflow

This repository runs the same bot on its own PRs via
`.github/workflows/diff-impact.yml` (`pull_request` on `main` plus
`workflow_dispatch` with a `base` input):

```yaml
- uses: ./.github/actions/diff-impact
  with:
    base: ${{ github.event.pull_request.base.sha }}
```

The engine step is `continue-on-error: false`; only the comment-posting
step tolerates failure, so a broken index still blocks the PR signal.

## Rendering locally

```bash
sot diff-impact HEAD~1 --format github | pbcopy   # paste into a PR comment
sot diff-impact main...HEAD --format github -o comment.md
```
