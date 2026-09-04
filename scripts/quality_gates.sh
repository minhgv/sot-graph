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
uv run ruff check src/sot_graph/assurance/ src/sot_graph/providers/ \
    src/sot_graph/diff_impact.py src/sot_graph/db.py src/sot_graph/snapshot.py \
    src/sot_graph/providers_registry.py src/sot_graph/mcp_service.py src/sot_graph/mcp_server.py \
    src/sot_graph/claims.py \
    || fail "ruff"

echo "== pyright (core modules)"
uv run pyright src/sot_graph/assurance/ src/sot_graph/providers/ \
    src/sot_graph/diff_impact.py src/sot_graph/db.py src/sot_graph/snapshot.py \
    src/sot_graph/providers_registry.py src/sot_graph/mcp_service.py src/sot_graph/mcp_server.py \
    src/sot_graph/claims.py \
    || fail "pyright"

echo "== coverage floor (core >= 85%, receipts >= 90%)"
COVERAGE_INCLUDES="src/sot_graph/assurance/*,src/sot_graph/providers/*,src/sot_graph/diff_impact.py,src/sot_graph/db.py,src/sot_graph/snapshot.py,src/sot_graph/providers_registry.py,src/sot_graph/mcp_service.py,src/sot_graph/mcp_server.py"

uv run coverage run --source=src/sot_graph \
    --include="$COVERAGE_INCLUDES" \
    -m pytest tests/ -q >/dev/null 2>&1

REPORT=$(uv run coverage report --include="$COVERAGE_INCLUDES")
echo "$REPORT"

for f in "assurance/receipts.py" "assurance/coverage.py" "assurance/state.py" "assurance/routing.py" "assurance/orchestrator.py" "providers/scip.py" "diff_impact.py" "db.py" "snapshot.py" "providers_registry.py" "mcp_service.py" "mcp_server.py"; do
    echo "$REPORT" | grep -q "$f" || fail "expected module $f missing from coverage data"
done

CORE=$(echo "$REPORT" | awk '/^TOTAL/ {print $4+0}')
REC=$(echo "$REPORT" | awk '/receipts\.py/ {print $4+0}')
echo "core=${CORE}% receipts=${REC}%"
[ "$CORE" -ge 85 ] || fail "core coverage ${CORE}% < 85%"
[ "$REC" -ge 90 ] || fail "receipts coverage ${REC}% < 90%"
echo "== bandit (reviewed config: bandit.yaml)"
uvx bandit -q -c bandit.yaml -r src/sot_graph || fail "bandit"

echo "== pip-audit"
uvx pip-audit --skip-editable || fail "pip-audit"

echo "✅ all quality gates passed"
