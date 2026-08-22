## SOT-Graph Knowledge Reuse Protocol

Before implementing any new feature, fix, or refactoring:
1. Check existing work across projects using the Single Source of Truth search:
   `sot search "<what you are looking for>" --scope <optional-dir>`
2. Follow Trust Verdict Guidance:
   - `[STRONG]`: High confidence — file and symbols physically verified on disk.
   - `[WEAK]`: Semantic match only — inspect the file before relying on it.
   - `[REBUILT]`: File has moved location; use the updated reported path.
3. Trace architectural impact before modifying core symbols:
   `sot explore "<symbol_or_function_name>"`
4. After completing reusable work, architecture choices, or tricky fixes, persist it:
   `sot insert --title "<topic>" --body "<details>" --keywords "k1,k2"`
