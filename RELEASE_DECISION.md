# Release Decision: SOT-Graph v0.3.0 Precision Gate & Flexible Impact-Assurance

**Date**: 2026-08-28  
**Release Gate Verdict**: 🟢 **GO**

### Verification Summary
1. **Independent Evaluator**: `uv run python evaluation/run.py` -> 100.00% Strict Precision, 100.00% Strict Recall, 100.00% F1, 100.00% Forbidden Rejection, 0 False Spans.
2. **Regression, Property & Assurance Tests**: 269 passing P0-P9 test cases across Python 3.10–3.14 (including metamorphic, differential, chaos, and provider golden suites).
3. **Security Invariant**: Repository instructions quarantined in context-pack; fail-closed exact span policy active; zero unredacted secrets or unbound fresh claims.
4. **Autonomous Navigation & Assurance Suitability**: Certified for autonomous code navigation, refactoring, and evidence-backed impact-assurance.

---

### Definition of Done: Flexible Impact-Assurance Certification (Roadmap §11)

All 15 Definition of Done criteria for the **Flexible Impact-Assurance System** have been verified and satisfied:

1. **Builtin-Only Independence**: SOT functions completely in standalone mode without any external provider binary installed or configured (`tests/test_p2_orchestrator.py::TestBuiltinUntouched`, `tests/test_p8_omp_integration.py`).
2. **Pluggable Provider Architecture**: External providers (Codebase Memory, SCIP, plugins) can be added, updated, or removed without breaking CLI/MCP public interfaces (`src/sot_graph/providers/contract.py`, `tests/test_p3_plugin_contract.py`).
3. **Unified Assurance Engine**: CLI and MCP surfaces share the identical orchestration, normalization, routing, and verification pipeline (`src/sot_graph/assurance/`, `tests/test_p2_orchestrator.py::TestCliMcpParity`).
4. **Per-Language Search Quality Floors**: Target symbol identity satisfies precision/recall floors across Tier-A languages (`tests/test_p4_quality_gate.py::TestReleaseFloor`).
5. **Exact Tuple Evaluator**: Caller and impact evaluation verified against exact `(repo, path, source identity, relation, target identity, span)` tuples (`evaluation/run.py`, `tests/test_p4_identity.py`).
6. **Strict Snapshot Freshness**: Dirty, staged, untracked, or stale worktrees never produce `FRESH` or `ASSURED_WITHIN_SCOPE` verdicts (`tests/test_p1_snapshot_trust.py::TestDirtyGateBlockerOne`).
7. **True Scope Coverage**: Coverage engine measures parsed/indexed/skipped file spans rather than shallow query status (`src/sot_graph/assurance/coverage.py`, `tests/test_p5_coverage_verification.py`).
8. **Language-Aware Source Verification**: Multi-language AST/grammar verification active for Python, TypeScript/JavaScript, Go, Rust, Java, and C/C++ (`src/sot_graph/assurance/verification.py`, `tests/test_p5_coverage_verification.py`).
9. **Durable Evidence Ledger**: Production CLI/MCP executions record snapshot-scoped provider runs and normalized evidence (`src/sot_graph/assurance/ledger.py`, `tests/test_p6_ledger.py`).
10. **Preserved Conflicts & Gaps**: Unresolved contradictions and unknown gaps are explicitly reported rather than silently overwritten (`tests/test_p6_ledger.py::TestUnionByIdentity`, `tests/test_p7_receipts.py`).
11. **Deterministic Receipt Digests**: Pre-change Scope Receipts and post-change Diff-Impact Receipts include schema versions and SHA-256 digests (`src/sot_graph/assurance/receipts.py`, `tests/test_p7_receipts.py`).
12. **Bounded Negative Claims**: "0 callers" statements are strictly forbidden unless scope coverage, manifest, and parser completeness are mathematically proven (`src/sot_graph/assurance/coverage.py`, `tests/test_p7_receipts.py::TestRenameGate`).
13. **Full OMP Change Loop**: End-to-end assurance cycle executes: `receipt` -> `plan` -> `edit` -> `test` -> `reconcile` -> `review` (`tests/test_p8_omp_integration.py::TestAssuredChangeLoop`).
14. **Honest Provider Degradation & Abstention**: Missing, failing, or timed-out providers fall back gracefully or abstain with typed outcomes (`tests/test_p2_orchestrator.py::TestDeadProviderDegrades`).
15. **Overtrust Claim Elimination**: All absolute 100% claims removed from agent-facing prompt templates and documentation (`tests/test_p8_omp_integration.py::TestAssuredChangeLoop::test_omp_skill_and_rules_no_absolute_claims`).
