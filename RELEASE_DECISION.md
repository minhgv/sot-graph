# Release Decision: SOT-Graph v0.3.0 Precision Gate

**Date**: 2026-08-25  
**Release Gate Verdict**: 🟢 **GO**

### Verification Summary
1. **Independent Evaluator**: `uv run python evaluation/run.py` -> 100.00% Strict Precision, 100.00% Strict Recall, 100.00% F1, 100.00% Forbidden Rejection, 0 False Spans.
2. **Regression & Property Tests**: 333 passing pytest tests (including new metamorphic & differential test suites).
3. **Security Invariant**: Repository instructions quarantined in context-pack; fail-closed exact span policy active.
4. **Autonomous Navigation Suitability**: Certified for autonomous code navigation and refactoring.
