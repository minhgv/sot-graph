# Agent Rules & Protocols (SOT-Graph SSOT v0.3.0)

## SOT-Graph Knowledge Reuse & Multi-Provider Protocol

Before implementing any new feature, fix, or refactoring:
1. Check existing work across projects using the Single Source of Truth search:
   `sot search "<what you are looking for>" --scope <optional-dir> [--json]`
2. Follow Multi-Provider Trust Verdict Guidance:
   - `[STRONG]`: High confidence — file and symbols physically verified on disk (Schema v8).
   - `[WEAK]`: Semantic match only — inspect the file snippet before relying on it.
   - `[REBUILT]`: File has moved location; use the updated reported path.
   - `[REMOVED]`: Node deleted on disk; do NOT reference or hallucinate.
3. Check `providers` in response envelope to distinguish AST heuristic extractions from compiler-backed SCIP indices.
4. Trace architectural impact before modifying core symbols:
   `sot explore "<symbol_or_function_name>" --depth 2`
5. Ingest compiler indices for 100% exact cross-file references:
   `sot import-scip <path_to_index.scip>`
6. Package subgraphs for subagents under strict token ceilings:
   `sot pack "<symbol>" --tokens 1500 --json`
7. After completing reusable work, architecture choices, or tricky fixes, persist it:
   `sot insert --title "<topic>" --body "<details>" --keywords "k1,k2"`
   *(User notes are permanently preserved even when resetting disposable graph indexes).*
