---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, and graph analytics.
---

# sot-graph for Google Antigravity / Gemini CLI

Ground agent actions in physical filesystem reality using the SOT knowledge layer:

## 1. Verified Knowledge Search
Search the codebase with Trust Verdicts before implementing new logic:
```bash
sot search "<query>" -n 5
```
Or use the MCP tool `sot_search(query="...")`.

Trust Verdicts:
- `[STRONG]`: High confidence — file and symbols physically verified on disk.
- `[WEAK]`: Semantic match only — inspect before relying on it.
- `[REBUILT]`: File has moved location; use the updated path.

## 2. AST Call Graph & Dependency Exploration
Trace cross-file call graphs and references before modifying functions:
```bash
sot explore "<symbol_or_function_name>" --depth 2
```
Or use the MCP tool `sot_explore(target="...")`.

## 3. Drift Audit & Self-Healing
```bash
sot verify --deep        # Check for phantom anchors and dead paths
sot reconcile            # Re-synchronize SQLite DB with disk state
```

## 4. Knowledge Anchoring
Record non-obvious architecture decisions and tricky bug fixes:
```bash
sot insert --title "<topic>" --body "<details>" --keywords "k1,k2"
```
