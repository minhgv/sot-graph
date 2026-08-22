# sot-graph Roadmap v3 — Research-Driven

**Edition:** v3.0 — 2026-08-22. Derived from a 3-pronged research pass (competitor landscape,
agentic-context trends, indexing technology) executed by parallel research agents, then
gap-analyzed against the *verified* current inventory of this repository.

---

## 1. Research Method

Three parallel research tracks (August 2026):

| Track | Coverage |
|---|---|
| Competitive landscape | Serena, Aider repo-map, wong2/repo-query, Cursor indexing, Sourcegraph SCIP, ast-grep, Continue |
| Agentic context trends | MCP 2025-06-18 spec features, Anthropic context-engineering patterns, agent memory (Letta/Zep/mem0), PageRank repo maps, hybrid BM25+vector, spec-kit/AGENTS.md |
| Indexing technology | LSP-as-indexer, py-tree-sitter wheels, SCIP schema, incremental-sync strategies, call-graph precision limits, sqlite-vec |

All findings below are anchored to the source list in §8.

---

## 2. Verified Current State (2026-08-22)

Confirmed by direct inspection of this repo:

- **CLI (17 commands):** search, insert, explore, reconcile, verify, doctor, clean, vacuum,
  mcp, report, cluster, viz, export (GraphRAG/Obsidian/GraphML), bundle, setup, pack, watch.
- **MCP server (7 tools):** sot_search, sot_explore, sot_verify_drift,
  sot_architecture_report, sot_communities, sot_bundle, sot_pack.
  Resources: `sot://stats`, `sot://node/{node_id}` (no subscriptions yet).
- **Edge relations:** `calls`, `defines`, `imports`, `implements` (Dart), `uses`.
- **Languages:** Python (stdlib `ast`, binding-aware), JS/TS/TSX (vendored), Dart (vendored).
- **Harness adapters:** OMP, OpenCode, Antigravity, Claude, ZCode (merge-safe provisioning).
- **Storage:** SQLite schema v3 (`user_version`), FTS5 (unicode61 + tokenchars), pending-edge
  resolution states (RESOLVED/UNRESOLVED/AMBIGUOUS/EXTERNAL), 2-phase publication
  (write.lock + generation CAS), file-hash journal.
- **Philosophy (invariant):** zero-dependency core (stdlib only), no daemon, filesystem is
  the single source of truth, optional extras allowed (`[watch]` = watchfiles precedent).

---

## 3. Competitive Landscape Summary

| Tool | Approach | Agent-facing retrieval | Sync | Languages |
|---|---|---|---|---|
| Serena | LSP servers (bundled) | ~30 symbol ops: find_symbol, **find_referencing_symbols**, find_implementations, rename_symbol, replace_symbol_body, memory tools | delegated to LSP runtime | 40+ |
| Aider repo map | tree-sitter + **personalized PageRank** | auto-injected map, token-budgeted (~1k tokens default, binary-search fitted) | full reparse | all tree-sitter langs |
| repo-query (wong2) | AST/LSP QA | NL question → snippets | n/a | TS/JS focus |
| Cursor | embeddings + **Merkle-tree** incremental | @codebase semantic search | Merkle diff | all |
| SCIP (Sourcegraph) | protobuf index format | def/refs/implementations for editors & search | full-snapshot indexers | 12+ |
| ast-grep | tree-sitter + YAML patterns | CLI structural search/replace | on-demand | 15+ |
| Continue | embeddings + rerank | @codebase provider | chunk re-embed | all |

**Table-stakes that recur across the category** (i.e., what agents increasingly expect):

1. Symbol-level navigation: definition / **references / implementations** (Serena, SCIP).
2. Incremental re-indexing of only changed files (Cursor, SCIP, Continue).
3. Token-budgeted ranked output (Aider, Continue).
4. Memory/notes persisted across sessions (Serena memory tools, AGENTS.md convention).
5. Hybrid exact + semantic search (Cursor, Sourcegraph, Continue).

sot-graph already has (2) via hash-journal+CAS and (4) via `sot insert` notes; it is
**missing (1) as a first-class command, (3) entirely, and (5) entirely.**

---

## 4. Trend Findings (2025–2026)

1. **MCP 2025-06-18** added structured tool output (`outputSchema` + `structuredContent`),
   Resource Links in tool results, resource subscriptions with
   `notifications/resources/updated`, cursor-based pagination, elicitation, sampling.
2. **Context engineering** (Anthropic et al.) codified: compaction, just-in-time retrieval,
   progressive disclosure, structured note-taking. sot-graph's search→explore→pack chain
   already implements JIT retrieval + progressive disclosure; what is missing is a
   *coarse-orientation* artifact (repo map) for compaction-friendly workflows.
3. **Agent memory systems** (Letta, Zep/Graphiti, mem0) are complementary, not competing:
   sot-graph should own the structural/trust layer and expose it as composable MCP
   resources rather than build a general memory product.
4. **Personalized PageRank + token budget** (Aider) is the proven recipe for repo maps:
   graph ranking with personalization on the current working set, binary-search the symbol
   count to fit N tokens.
5. **sqlite-vec** makes local hybrid search a pip-extra away: FTS5 BM25 + vec0 cosine
   similarity in one SQLite file, zero infrastructure.
6. **AGENTS.md is the standard agent entry point** (agents.md, GitHub spec-kit, Claude Code,
   Aider). Tools that auto-surface it as trusted context win integration points.
7. **LSP gives precision** (exact references, rename) but costs per-language daemon
   processes with 5–15s cold starts — incompatible with the no-daemon default, viable as an
   on-demand optional extra.
8. **SCIP** is the interchange format for code intelligence (occurrence roles, def/ref
   relationships) — worth an export bridge, wrong as internal storage.

---

## 5. Roadmap

Prioritized by agent utility per unit cost, respecting the zero-dependency/no-daemon
philosophy. Phases 1–3 are stdlib-only. Phases 4–5 are optional extras (watchfiles
precedent). Phase 6 is interop polish.

### Phase 1 — Navigation Table-Stakes *(pure graph; S–M effort)*

Close the biggest gap vs Serena/SCIP: reference-finding as a first-class operation.

- **`sot usages <symbol>`** (CLI + MCP `sot_usages`): every reference site —
  file:line, relation (calls/uses/imports/implements), call_kind, grouped by caller.
  Acceptance: `usages Database.commit_file_batch` returns the same caller set as the
  verified blast-radius case, zero AMBIGUOUS edges silently attached.
- **`sot implementations <symbol>`**: resolve `implements`/base-class edges in both
  directions (base→derived list, derived→base lookup). Requires adding an `inherits`
  relation for Python class bases during extraction.
- **`sot rename --plan <old> <new>`** (report-only): list all affected definition + usage
  sites, flag risk where pending edges are AMBIGUOUS. No filesystem writes — MCP-safe.

### Phase 2 — Orientation & Context Engineering *(pure graph; M effort)*

- **`sot map [--tokens N] [--focus sym1,sym2]`** (CLI + MCP `sot_map`): Aider-style
  personalized PageRank over the file↔symbol graph; binary-search the symbol count to fit
  the token budget (default 1k). This is the cheapest high-utility feature in this
  roadmap — the graph already exists; no new deps.
- **pack: trusted tier** — auto-embed repo-root `AGENTS.md` (and `plan/*.md` spec files on
  request) as a `content_is_trusted: true` section of the ContextBundle, keeping all code
  content under the existing untrusted banner.
- **Notes as MCP resources**: `sot://notes`, `sot://notes/{id}` + `sot_notes` tool —
  parity with Serena's memory tools without building a memory product.

### Phase 3 — MCP 2025-06-18 Modernization *(stdlib; M effort)*

- `outputSchema` + `structuredContent` on sot_search / sot_explore / sot_usages / sot_pack.
- **Resource Links** in search results (`sot://node/{id}`) so clients lazily fetch bodies
  instead of ingesting full results.
- **resources/subscribe** on `sot://stats` (and node URIs): emit
  `notifications/resources/updated` when `file_journal.generation` bumps — push-based
  staleness signal replaces client polling.
- Cursor-based pagination on `resources/list`.

### Phase 4 — Hybrid Retrieval *(optional `[vector]` extra; M–L effort)*

- `[vector]` extra: sqlite-vec (vec0 virtual table) + pluggable embedder interface.
  FTS5 BM25 remains the always-available floor; when vectors exist, fuse
  BM25 rank ↔ cosine similarity (reciprocal-rank fusion) and surface the fused score in
  search output. Trust verdicts remain orthogonal to score fusion.
- Embedder stays injectable (local model, API, or none) — the core never requires one.

### Phase 5 — Language Breadth *(optional `[tree-sitter]` extra; L effort)*

- `[tree-sitter]` extra with pinned `py-tree-sitter` + grammar wheels
  (Go, Rust, Java, Kotlin, Swift first). Stdlib/vendored extractors remain the default;
  the extra registers additional extensions into the same `parse_file_graph` contract.
- Grammar pinning policy documented (`tree-sitter>=0.23,<0.24` style) to avoid the known
  grammar-API breakage between minor releases.

### Phase 6 — Ecosystem Interop *(S–M effort each)*

- **`sot export --format scip`**: protobuf SCIP index (def/ref occurrences, relationships)
  for editor/Sourcegraph interop (~200 LOC bridge; internal storage stays SQLite).
- **`sot setup --hooks`**: provision git `post-merge` / `post-checkout` hooks that run
  `sot reconcile` — event-driven sync for the no-daemon model.
- **Benchmark harness**: productize the D1-vs-D2 protocol (pack vs grep token cost,
  dead-path count) into `docs/BENCHMARKS.md` methodology + repeatable script, so each
  phase's utility claim is measurable, not asserted.
- **`[lsp]` extra (future)**: on-demand LSP bridge for exact references/rename when the
  user opts in; never the default path.

---

## 6. Explicit Non-Goals

- **Daemon-first operation** — conflicts with the filesystem-is-SOT model; watch mode and
  git hooks cover reactive sync without resident processes.
- **Embeddings-only search** — FTS5 BM25 stays the zero-dep floor; vectors are additive.
- **MCP write operations without explicit user-initiated commands** — search/explore/pack
  remain read-only; inserts stay CLI/user-driven.
- **Merkle-tree reindexing** — the hash journal + generation CAS already delivers
  Cursor-equivalent incremental sync in SQLite; a tree structure adds nothing here.
- **General agent-memory product** — compose with Letta/Zep/mem0 via resources instead.

---

## 7. Success Metrics

| Metric | Baseline (2026-08) | Target |
|---|---|---|
| MCP tool count | 7 | 11 (+usages, +map, +notes, +implementations) |
| Token cost, orientation task (repo overview) | 58.6k (grep protocol) | < 15k via `sot map` |
| Token cost, deep-dive task (pack vs grep) | 18.8k vs 58.6k (−68%) | −70% sustained |
| Dead paths in retrieval | 2 (grep protocol) | 0 |
| Languages (zero-dep default) | py/js/ts/dart | unchanged |
| Languages (with extras) | py/js/ts/dart | +go/rust/java/kotlin/swift |
| Test suite | 97 green | keep ≥ 97, new features land with regression tests |

---

## 8. Source Index

- Serena — https://github.com/oraios/serena , tools: https://oraios.github.io/serena/01-about/035_tools.html
- Aider repo map — https://aider.chat/docs/repomap.html , https://aider.chat/2023/10/22/repomap.html ,
  implementation: https://github.com/paul-gauthier/aider/blob/main/aider/repomap.py
- SCIP — https://github.com/sourcegraph/scip , https://scip-code.org/ , schema: scip.proto
- ast-grep — https://github.com/ast-grep/ast-grep
- Continue embeddings — https://docs.continue.dev/customize/model-roles/embeddings
- MCP spec 2025-06-18 — https://modelcontextprotocol.io/specification/2025-06-18/server/tools ,
  .../server/resources , .../client/elicitation , .../client/sampling , .../utilities/pagination
- Context engineering — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Letta — https://github.com/letta-ai/letta ; Zep/Graphiti — https://github.com/getzep/graphiti ;
  mem0 — https://github.com/mem0ai/mem0
- sqlite-vec — https://github.com/asg017/sqlite-vec
- py-tree-sitter + grammar wheels — https://pypi.org/project/tree-sitter/
- AGENTS.md — https://agents.md ; spec-kit — https://github.com/github/spec-kit
- Cursor indexing (Merkle) — https://cursor.com/docs
