# ADR-0001: Codebase Memory integration via FEDERATED_CLI sidecar

- **Status:** Accepted
- **Date:** 2026-08-25
- **Research pins:**
  - SOT-Graph studied at commit `ba99fbe0db8ead483a76a92070cfe86f63358f17` (= this repo's HEAD at decision time)
  - Codebase Memory source studied at commit `010569fa6ce1bc5d6430f858129243ea1a2e3fd5`
  - Binary actually exercised: `/Users/giapminh79/.local/bin/codebase-memory-mcp`, version `codebase-memory-mcp 0.10.8`
- **Reference:** `sot-graph-codebase-memory-integration-solution.md` (P0–P5 roadmap; §13 test plan)

## 1. Context

SOT-Graph owns the **verified evidence layer** for agent navigation: an AST/SCIP-backed knowledge
graph whose Trust Verdicts (`[STRONG]`, `[WEAK]`, `[REBUILT]`, `[REMOVED]`) are derived from the
physical filesystem and compiler-grade indices. Codebase Memory (CBM) is an independent indexer
that provides complementary *candidate* signals: semantic search, architecture summaries,
coverage hints, and change impact over its own graph.

We need candidate evidence without sacrificing the verification guarantees of SOT-Graph.
Three architectures were considered:

| Option | Description | Rejected because |
|---|---|---|
| Embedded library | Link CBM internals into SOT process | Couples release cycles; requires maintaining C, grammars, LSP adapters and security updates ourselves |
| Fork | Maintain a private CBM fork | Same maintenance burden plus permanent upstream drift |
| **FEDERATED_CLI sidecar** | SOT invokes the standalone `codebase-memory-mcp` binary via argv subprocess | Process boundary overhead, mitigated by contract below |

## 2. Decision

Adopt **FEDERATED_CLI**: SOT treats Codebase Memory strictly as an external provider process.

Wire contract (verified from CBM source @`010569f`, re-confirmed against binary 0.10.8):

- Invocation: `codebase-memory-mcp cli --json <tool> [--flag value | --args-file path]`.
- stdout carries exactly one MCP envelope:
  `{"content":[{"type":"text","text":"..."}],"isError":<bool>,"structuredContent":{...}?}`.
- Diagnostics go to stderr; exit codes: `0` = ok, `1` = error/`isError`, `2` = bad args.
- Version probe: `--version` → `codebase-memory-mcp <ver>` (gates adapter start).
- Subprocess launched with explicit argv (never `shell=True`), with timeout, output cap,
  JSON validation, and child-process cleanup.
- `allow_external` defaults to **False**: external providers are strict opt-in.
- SOT never mutates agent MCP configuration; CBM is never vendored into this repo;
  the query path never triggers a CBM index refresh implicitly.

## 3. Responsibility boundary

| Concern | Owner | Evidence class |
|---|---|---|
| Candidate signals (semantic search, arch summary, coverage hints, change detection) | Codebase Memory | **Candidate evidence** — advisory only |
| Verified truth (existence, location, call edges, Trust Verdicts) | SOT-Graph | **Verified evidence** — filesystem + compiler-backed |

Rule: a claim is never promoted to SUPPORTED in SOT solely from CBM output. Every external
assertion must carry provider name, version, and run identity; stale or unbound evidence can
never reach SUPPORTED. CBM candidates may direct attention (e.g., "look here"), but SOT must
verify against the filesystem/compiler index before granting trust.

## 4. Consequences

Positive:

- Independent release cycles; CBM upgrades are a version-gate, not a code merge.
- Failure isolation: CBM crashes/timeouts degrade gracefully instead of corrupting SOT state.
- Clear audit trail: each assertion records which provider/version produced it.

Negative / accepted costs:

- Per-call process spawn overhead (~seconds including allocator init observed on M1 Max).
- Environment sensitivity of some tools (see matrix); goldens must be re-captured per version.
- Two graph models to reconcile at the evidence-binding layer.

## 5. Reconsider conditions (per solution doc §P5)

Re-evaluate embedded/fork **only if at least one strong criterion holds, backed by benchmarks**:

1. CLI overhead measurably exceeds the real latency budget;
2. process-boundary failure rate cannot be remediated;
3. a required API is missing upstream and cannot be opened;
4. a genuine zero-external-binary requirement emerges;
5. the team accepts owning C, grammars, LSP adapters and security updates.

Otherwise, keep FEDERATED_CLI.

## 6. Compatibility matrix — provider version 0.10.8 (binary), source @010569f

Legend: **source-verified** = confirmed by reading CBM source @010569f ·
**binary-captured** = exercised against binary 0.10.8, golden stored in `tests/fixtures/cbm_golden/` ·
**UNKNOWN** = not yet verified either way.

Common envelope fields:

| Field | Status | Notes |
|---|---|---|
| `content[0].type == "text"` | source-verified + binary-captured | all 7 tools |
| `isError: bool` | source-verified + binary-captured | mirrors exit code semantics |
| `structuredContent` | source-verified + binary-captured | present ONLY when the tool payload itself is JSON (index_status, list_projects, check_index_coverage); text-report tools omit it |
| stderr log separation | source-verified + binary-captured | `level=info …` lines never leak into stdout |
| exit codes 0/1/2 | source-verified + binary-captured | missing-required-arg → isError=true, exit 1 |
| list-valued flags via `--flag` | binary-captured (quirk) | value arrives server-side as a single string; prefer `--args-file` for arrays |

Per-tool:

| Tool | Key input field(s) | Key output field(s) | Status |
|---|---|---|---|
| `list_projects` | — (none) | `projects[].name/root_path`, `total`, `offset`, `limit`, `returned`, `has_more` | binary-captured |
| `index_status` | `project` (required) | `project`, `nodes`, `edges`, `status="ready"`, `root_path`, `parse_partial{}`, `skipped{}`, `not_indexed{}` | binary-captured; **binary 0.10.8 does NOT emit `head_sha`/`base_sha`/`branch`** (present in source @010569f) ⇒ Git snapshot binding unprovable on this binary; adapter fail-closes to `UNVERIFIABLE` per solution doc §8 |
| `search_graph` | `project`; `query` (optional) | text report: `total`, `search_mode` (bm25), results rows `qn label file lines rank`, `has_more` | binary-captured |
| `trace_path` | `function_name` (required), `direction` (default `both`) | text report: `callees_total/callees[]`, `callers_total/callers[]` | binary-captured |
| `get_architecture` | `project`; `aspects` (optional) | text report: `total_nodes`, `total_edges`, `node_labels[]`, `edge_types[]`, `languages[]`, `packages[]` | binary-captured |
| `check_index_coverage` | `paths` or `scopes` arrays (max 128 paths / 32 scopes) | `signal`, `indexed_at`, `metadata.coverage_version`, `paths[].status/recommended_action`, `caveat` | binary-captured; array-via-flag quirk ⇒ array passing = UNKNOWN until re-tested with `--args-file` |
| `detect_changes` | `project`; git context from repo enclosing project root | `base`, `merge_base`, `direction=inbound`, `changed_files`, `impacted[]` | binary-captured; **environment-dependent** (parent-repo branch/HEAD) |

UNKNOWN items are tracked for re-verification whenever the pinned CBM version changes; any
version bump requires re-running the golden capture (`tests/fixtures/cbm_golden/_meta.json`)
and updating this matrix.

### P2 addendum — snapshot binding reality (2026-08-25)

P2 snapshot machinery (schema v7: `provider_project_bindings`, snapshot-scoped
`provider_runs`/`provider_evidence`, staleness downgrade, span verification) is fully
wired and proven against fake executables that serve `head_sha`. Against the real
0.10.8 binary, `index_status` carries no Git identity (see matrix above), so live
binding is honestly `UNVERIFIABLE` until either (a) CBM exposes git metadata again,
or (b) a future version adds a manifest/file-set digest we can bind. Path-level
freshness via `check_index_coverage` (`hash_status`) is used as the staleness
authority for coverage but never elevates a verdict past `UNVERIFIABLE` on its own.
