---
name: sot-graph
description: Single Source of Truth (SOT) verified knowledge graph for AI coding agents. Provides verified codebase search with Trust Verdicts ([STRONG], [WEAK], [REBUILT]), AST cross-file dependency exploration, zero-daemon SQLite storage, self-healing synchronization, and graph analytics.
---

# sot-graph for OpenCode

Use SOT-Graph to ground OpenCode agent actions in physical filesystem reality:

## 1. Verified Code Search (Before Writing Code)
Search the knowledge graph with Trust Verdicts:
```bash
sot search "<query>" -n 5
```
Or use the MCP tool `sot_search(query="...")` if SOT MCP server is enabled.

Trust Verdicts:
- `[STRONG]`: High confidence — file and symbols physically verified on disk.
- `[WEAK]`: Semantic match only — inspect before relying on it.
- `[REBUILT]`: File has moved location; use the updated path.

## 2. AST Dependency Exploration (Before Modifying Functions)
Trace cross-file call graphs and references:
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
