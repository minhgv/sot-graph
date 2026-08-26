#!/usr/bin/env bash
# P9 quality gates: lint, types, coverage floor, security scan.
#
# Every gate is designed to run offline except pip-audit (PyPI advisory
# DB). Exit non-zero on the first failing gate with a short receipt.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
fail() { echo "❌ gate failed: $1" >&2; exit 1; }

echo "== ruff (core modules)"
npx -y ruff check src/sot_graph/assurance/ src/sot_graph/providers/ \
    src/sot_graph/diff_impact.py src/sot_graph/db.py \
    || fail "ruff"

echo "== pyright (core modules)"
npx -y pyright src/sot_graph/assurance/ src/sot_graph/providers/ \
    src/sot_graph/diff_impact.py src/sot_graph/db.py \
    || fail "pyright"

echo "== coverage floor (core >= 85%, receipts >= 90%)"
"$PY" -m coverage run --source=src/sot_graph/assurance,src/sot_graph/providers,src/sot_graph/diff_impact,src/sot_graph/db -m pytest -q >/dev/null
CORE=$("$PY" -m coverage report 2>/dev/null | awk '/^TOTAL/ {print $4+0}')
REC=$("$PY" -m coverage report 2>/dev/null | awk '/receipts.py/ {print $4+0}')
echo "core=${CORE}% receipts=${REC}%"
[ "$CORE" -ge 85 ] || fail "core coverage ${CORE}% < 85%"
[ "$REC" -ge 90 ] || fail "receipts coverage ${REC}% < 90%"

echo "== bandit (reviewed config: bandit.yaml)"
"$PY" -m bandit -q -c bandit.yaml -r src/sot_graph || fail "bandit"

echo "== pip-audit"
"$PY" -m pip_audit --skip-editable || fail "pip-audit"

echo "✅ all quality gates passed"
