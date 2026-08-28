# Handoff — SOT-Graph P0 Trust Chain Implementation (2026-08-28 18:15 +0700, FINAL)

## Mục đích
Session trước (model zai-coding-plan/glm-5.3-flash) thực hiện P0 theo plan
`plan/sot-graph-p0-trust-chain-implementation-2026-08-28.md`. Chạy tiếp với model khác
(gemini-3.7-flash-medium). Handoff này là deliverable cuối — session này KHÔNG làm tiếp.

## Trạng thái công việc

### HOÀN THÀNH (verify + code đã đổ vào working tree, CHƯA commit)
1. **Verification 7/7 claims CONFIRMED** (đánh giá ND-GQ đúng):
   - scope_receipt issue ASSURED thiếu gates → `src/sot_graph/assurance/receipts.py`
   - LIMIT 1 ambiguity → `src/sot_graph/db.py` `get_node_by_symbol` (L775-783), `src/sot_graph/assurance/engine.py` `_resolve_symbol` (L128-137)
   - dirty fingerprint chỉ status → `src/sot_graph/snapshot.py` (đã fix, see below)
   - union_evidence default SUPPORTED → `src/sot_graph/assurance/ledger.py` `union_evidence` (L51-134)
   - require_external không fail-closed → `src/sot_graph/mcp_service.py` (L373-397)
   - CLI/MCP receipt fragmentation
   - CI `npx ruff`/`npx pyright` không pin

2. **Worker A1 (state machine + identity + CLI)** — ĐÃ CANCEL 18:13 theo yêu cầu user; code đã đổ vào working tree:
   - `src/sot_graph/assurance/state.py` (MỚI, đã verify bằng đọc trực tiếp, hoàn chỉnh): `AssuranceFacts` frozen dataclass (L32-56) + `decide(facts) -> {"status", "reason_codes"}` (L59-105); canonical statuses `ASSURED_WITHIN_SCOPE | PARTIAL | CONFLICTED | STALE | UNVERIFIABLE | ABSTAINED` (L22-29) — KHÔNG có `BLOCKED`, KHÔNG có `ASSURED` đơn lẻ; thứ tự first-hit: identity → snapshot_bound → stale → rename_gate(→PARTIAL) → open_conflicts → truncated → parser_failures → unresolved_over_budget → coverage_below_floor (chỉ khi absence_claim) → provider_capability → ASSURED_WITHIN_SCOPE.
   - `src/sot_graph/assurance/receipts.py`: gọi `decide(facts)` tại L354 (scope) và L483 (diff_impact); payload scope có `identity.{status, candidates, selected}` (L366-370) — KHÔNG còn key `resolved_target`; `RECEIPT_SCHEMA_VERSION = "1.1"` (L46).
   - `src/sot_graph/assurance/engine.py`: `resolve_symbol_identity` → `{status: UNIQUE|AMBIGUOUS|NOT_FOUND, candidates, selected}`; `assured_query_context` có `scope_digest` + `content_digests`.
   - `src/sot_graph/cli.py`: `cmd_scope_receipt`/`cmd_diff_impact` gọi shared `decide()`; identity resolver wired.
   - A1 KHÔNG kịp update test assertions → 7 test FAIL (bảng bên dưới).

3. **Worker A2 (snapshot/ledger)** — XONG, self-reported 110 tests pass:
   - `snapshot.py`: `capture_worktree_snapshot(..., cited_paths=None)` keyword-only → content binding `content_digests` + `scope_digest` (sha256-v2), fail-closed khi file unreadable, legacy v1 giữ nguyên.
   - `ledger.py`: `union_evidence` fail-closed (UNBOUND/UNVERIFIED/SUPPORTED; verify_spans=True default; `invalidated_at IS NULL`); `record_provider_outcome` atomic single-transaction; `invalidate_provider_evidence` lifecycle helper.
   - `db.py` (+233/-x): `record_provider_run/binding/evidence` migrated; migration + schema updated.
   - `providers/codebase_memory.py`, `importer/scip.py`: migrated to atomic API.
   - Test mới: `tests/test_snapshot_content_binding.py` (15 invariant tests).

4. **Worker A3 (MCP federation)** — XONG, self-reported 42 tests pass:
   - `mcp_service.py`: `_require_satisfiable_policy` raise `McpServiceError('policy_unsatisfiable', ...)` cho require_external trên builtin-only; chỉ `prefer_external` mới fallback + note.
   - `mcp_server.py` (+48): tool `scope_receipt` mới, output schemas; dispatch qua orchestrator `federation_plan` (mode `all` iterate tất cả providers đủ capability).
   - `assurance/orchestrator.py` (210 lines changed): federated planning mode `all`.
   - Test mới: `tests/test_mcp_receipt_tools.py`.

5. **CI fixes (main thread, GREEN locally)**:
   - `pyproject.toml`: ruff>=0.14,<0.15 + pyright>=1.1.406,<1.2 pin trong cả `[project.optional-dependencies].dev` và `[dependency-groups].dev`; LOẠI tree-sitter-graphql khỏi extras + lock (đã regen uv.lock).
   - `scripts/quality_gates.sh`: `uv run ruff/pyright` thay npx; `uvx bandit`/`uvx pip-audit`.
   - `.github/workflows/ci.yml`: quality-gates bỏ Node setup; E2E fix `sot usages "extract_graphql" --provider auto || sot search "extract"`; audit tools qua `uv tool install`.
   - Local `quality_gates.sh` chạy XANH (ruff, pyright 0 errors, core=91% receipts=93%, bandit, pip-audit) — nhưng LÚC TRƯỚC khi A1 chưa xong sửa code.

6. Plan file: `plan/sot-graph-p0-trust-chain-implementation-2026-08-28.md` (12KB, contracts 1-5, file ownership A1/A2/A3, 3 waves).

## 7 test đang FAIL (root cause ĐÃ xác định, CHƯA fix)

Nguyên nhân duy nhất: A1 đổi contract (`schema_version = "1.1"` + status vocab mới) nhưng chưa kịp update test assertions. Full suite: 7 failed / ~810 test. Chi tiết:

| Test | Assertion cũ (fail) | Contract mới phải dùng |
|---|---|---|
| `tests/test_p7_receipts.py::TestScopeReceipt::test_field_families_present` (L85) | `schema_version == RECEIPT_SCHEMA_VERSION == 1` | bỏ `== 1` — "1.1" |
| `::TestScopeReceipt::test_unresolved_target_is_not_assured` (L122) | `payload["resolved_target"] is None` | `payload["identity"]["selected"] is None` + status `ABSTAINED`/reason `target_not_found` |
| `::TestRenameGate::test_scope_receipt_blocks_rename_with_uncovered_scope` (L183) | status `== "BLOCKED"` | state.py không có BLOCKED → `== "PARTIAL"` + reason `rename_gate_blocked` |
| `::TestCliSurface::test_scope_receipt_json_has_digest` (L252) | `schema_version == 1` | `== RECEIPT_SCHEMA_VERSION` |
| `tests/test_p8_omp_integration.py::TestAssuredChangeLoop::test_full_loop_builtin_only` | `in ('ASSURED', 'DEGRADED_STALE_SOURCES')` | `== 'ASSURED_WITHIN_SCOPE'` |
| `tests/test_p9_chaos_migration.py::TestChaos::test_corrupt_sidecar_does_not_break_reads` (L72, L85) | `schema_version == 1` | `== RECEIPT_SCHEMA_VERSION` |
| `::TestChaos::test_schema_drift_future_version_degrades_not_crashes` (L177) | `schema_version == 1` (kèm `lifecycle_manifest`) | `== RECEIPT_SCHEMA_VERSION` — kiểm tra cả manifest của lifecycle |

Fix direction: sửa TESTS theo contract mới (state.py là canonical theo Contract 1 của plan); KHÔNG đổi state.py/receipts.py cho khớp test cũ. Sau khi fix: `bash scripts/quality_gates.sh` — ruff/pyright đã XANH, coverage floor hiện fail chỉ vì pytest fail.

## VIỆC CÒN LẠI (cho session mới)
1. **Fix 7 test assertion drift** (bảng trên) — chỉ sửa `tests/test_p7_receipts.py`, `tests/test_p8_omp_integration.py`, `tests/test_p9_chaos_migration.py` theo contract `state.py`/`receipts.py`.
2. **Contract sync A2/A3 ↔ A1**:
   - A2 `union_evidence` trả UNBOUND/UNVERIFIED — map vào `AssuranceFacts.unresolved_count`/`open_conflicts`.
   - Callers `capture_worktree_snapshot(..., cited_paths=...)`: `receipts.py`, `cli.py cmd_diff_impact`, `diff_impact.py` phải truyền cited_paths.
   - Consumers `resolve_symbol_identity`: `cli.py` explore/trace, `mcp_service.py` assured_query_context.
3. **Chạy lại full gates**: `bash scripts/quality_gates.sh` (expect XANH sau khi fix tests).
4. **Full pytest**: `uv run pytest -q` (~810 test; A2/A3 self-report pass, A1 dở test updates).
5. **Sau khi xanh**: update plan checklist, commit (message gợi ý: `feat(assurance): P0 trust chain - fail-closed state machine, snapshot content binding, MCP policy enforcement`).

## Rủi ro đã biết
- A1 đã cancel sạch (không còn process ghi file); `state.py` đã verify trực tiếp là hoàn chỉnh (decide L59-105 khớp Contract 1).
- `plan/archived.zip` — archive cũ của plan đã xoá, giữ lại không sao.
- `git status` cho thấy vài plan/*.md cũ đã DELETE (dọn dẹp chủ đích từ session trước).

## Env
- macOS arm64, uv-managed; `.venv` Python 3.14.
- Chạy tests: `uv run pytest tests/test_p7_receipts.py tests/test_snapshot_content_binding.py tests/test_mcp_receipt_tools.py -q`
- Full: `uv run pytest -q` (~810 tests, vài phút).
- Chất lượng: `bash scripts/quality_gates.sh` (~95s, cần network cho pip-audit).
