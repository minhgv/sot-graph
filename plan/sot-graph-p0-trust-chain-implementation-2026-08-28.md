# SOT-Graph P0 — Đóng chuỗi trust: Plan thực hiện (2026-08-28)

**Đầu vào:** `plan/sot-graph-reassessment-vs-roadmap-2026-08-28.md` (đánh giá NO-GO cho `ASSURED_WITHIN_SCOPE`).
**Kết quả verification:** 7/7 claim trong đánh giá đều **CONFIRMED** trên code tại working tree. Không có claim nào bị bác bỏ → tiến hành sửa theo plan này.

---

## 1. Bằng chứng xác nhận (verification receipt)

| # | Claim | Verdict | Anchor chính |
|---|---|---|---|
| 3.1 | Receipt phát hành `ASSURED` dù coverage=0, parser fail, conflict, truncation | CONFIRMED | `receipts.py:346-348` — status chỉ check `gate.blocked` + `stale_files`; `truncated` (L332) không tham gia quyết định |
| 3.2 | Ambiguity bị che bởi `LIMIT 1` | CONFIRMED | `db.py:775-780` (`get_node_by_symbol`), `engine.py:22-36` (`resolve_symbol`) — không có trạng thái AMBIGUOUS |
| 3.3 | Dirty fingerprint không bind content | CONFIRMED | `snapshot.py:86-91` — `_fingerprint` chỉ hash chuỗi porcelain status; v1≠v2 nội dung cho cùng fingerprint |
| 3.4 | `union_evidence` default `SUPPORTED` + ghi ledger không nguyên tử | CONFIRMED | `ledger.py:92` (status khởi tạo SUPPORTED, verify chỉ khi >1 span); `db.py` `record_provider_run/binding/evidence` = 3 transaction riêng |
| 3.5 | MCP `require_external` vẫn chạy builtin | CONFIRMED | `mcp_service.py:391-397`, `602-606` — chỉ ghi `policy_meta`, không fail-closed |
| 3.6 | Receipt không nằm trên production path | CONFIRMED | `diff_impact_receipt` (receipts.py:357) **0 callers** trong `src/`; CLI `cmd_diff_impact` (cli.py:1351-1400) tự dựng pipeline; MCP không expose `sot_scope_receipt` |
| 3.7 | Provider hardcode; mode `all` chỉ chạy provider đầu | CONFIRMED | `orchestrator.py:82` (`target = names[0]`), `routing.py:20` (`QUERYABLE_PROVIDERS` 1 phần tử), hardcode `CodebaseMemoryProvider` (orchestrator.py:94, cli.py:376, mcp_service.py:147) |
| CI | Quality gate dùng `npx ruff`/`npx pyright`, không pin trong pyproject | CONFIRMED | `quality_gates.sh:13,18`; `ci.yml:133` (setup Node); pyproject không có ruff/pyright |
| CI | real-cbm-e2e chỉ assert exit code trên dir rỗng | CONFIRMED | `ci.yml:141-171` — không assert semantic output |

Tần suất CI bị đánh giá ghi nhận: 17 jobs = 5 pass / 11 fail / 1 skipped. 9 test-matrix jobs fail nghi do bước `uv sync --all-extras --dev` (build `tree-sitter-graphql` cần compiler, không có wheel) — **phải lấy raw log bằng `gh run view 33150572364 --log-failed` trước khi sửa, không suy đoán**.

---

## 2. Trạng thái chuẩn hóa (contract cốt lõi)

Sáu trạng thái canonical (thay thế `ASSURED` / `DEGRADED_STALE_SOURCES` / `BLOCKED` ở tầng receipt-status):

```text
ASSURED_WITHIN_SCOPE | PARTIAL | CONFLICTED | STALE | UNVERIFIABLE | ABSTAINED
```

Fail-closed: **mọi fact thiếu/không đạt ngưỡng ⇒ hạ trạng thái kèm reason code**. Không có đường nào mặc định nâng lên.

### Contract 1 — State machine (`src/sot_graph/assurance/state.py`, MỚI)

```python
CANONICAL_STATUSES = ("ASSURED_WITHIN_SCOPE", "PARTIAL", "CONFLICTED", "STALE", "UNVERIFIABLE", "ABSTAINED")

@dataclass(frozen=True)
class AssuranceFacts:
    identity_status: str        # UNIQUE | AMBIGUOUS | NOT_FOUND
    snapshot_bound: bool        # scope_digest hiện diện, bind nội dung hiện tại
    stale_files: list[str]
    coverage_measured: bool     # cov.basis == "measured"
    coverage_fraction: float | None
    coverage_floor: float = 0.9
    parser_failures: int = 0
    unresolved_count: int = 0   # evidence ledger không đạt SUPPORTED
    unresolved_budget: int = 0
    open_conflicts: int = 0
    truncated: bool = False
    provider_capability_ok: bool = True
    absence_claim: bool = True  # receipt có phải dựa trên negative claim
    gate_blocked: bool = False  # rename/delete gate

def decide(facts: AssuranceFacts) -> dict:
    # -> {"status": ..., "reason_codes": [str, ...]}
```

Thứ tự đánh giá (first-hit wins, mỗi nhánh kèm reason code):

1. `identity_status != UNIQUE` → `ABSTAINED` (`target_not_found` | `target_ambiguous`)
2. `not snapshot_bound` → `UNVERIFIABLE` (`snapshot_unbound`)
3. `stale_files` → `STALE` (`stale_sources`)
4. `gate_blocked` → `PARTIAL` (`rename_gate_blocked`)
5. `open_conflicts > 0` → `CONFLICTED` (`open_conflicts`)
6. `truncated` → `PARTIAL` (`transitive_truncated`)
7. `parser_failures > 0` → `PARTIAL` (`parser_failures`)
8. `unresolved_count > unresolved_budget` → `PARTIAL` (`unresolved_over_budget`)
9. `absence_claim` và (không measured hoặc fraction < floor) → `PARTIAL` (`coverage_below_floor`)
10. `not provider_capability_ok` → `PARTIAL` (`provider_capability_missing`)
11. còn lại → `ASSURED_WITHIN_SCOPE`

Pure function, không I/O. CLI, MCP, test đều gọi qua đây — không surface nào tự dựng logic assurance.

### Contract 2 — Snapshot content binding (`snapshot.py`)

```python
capture_worktree_snapshot(root, role="query", *, cited_paths=None) -> WorktreeSnapshot
# Field mới: content_digests: dict[str, str]  (relpath -> sha256 nội dung file trên working tree)
#            scope_digest: str | None         ("sha256:<hex>" trên các dòng sorted "path  sha256")
# as_dict() thêm "scope_digest" + "content_digests" (additive, backward-compatible)
# Cited path đọc lỗi -> scope_digest=None + danh sách unreadable (fail-closed)
# cited_paths được cấp -> algo_version = "sha256-v2"
```

`dirty_fingerprint` giữ nguyên (vẫn hữu ích cho diff status), nhưng `descriptor_digest`/`scope_digest` phải phân biệt v1≠v2 nội dung. `assured_query_context` (engine.py) pass `cited_paths` xuống và trả dict có `scope_digest` + `content_digests`.

### Contract 3 — Identity resolver (`engine.py`)

```python
def resolve_symbol_identity(db, query: str) -> dict:
    # {"status": "UNIQUE"|"AMBIGUOUS"|"NOT_FOUND", "candidates": [row...], "selected": row|None}
    # CHỈ dùng exact match (symbol == query OR fqn == query). Không LIKE, không LIMIT 1 ngầm.
```

`resolve_symbol` cũ giữ cho navigation (CLI explain/trace). Đường quyết định (receipts) dùng resolver mới; `AMBIGUOUS` ⇒ receipt `ABSTAINED` + danh sách candidates. `db.get_node_by_symbol` giữ nguyên cho caller hiện có, không dùng trong receipt.

### Contract 4 — Ledger fail-closed + ghi nguyên tử (`ledger.py`, `db.py`)

- `union_evidence`: entry chỉ `SUPPORTED` khi **đồng thời**: `snapshot_hash` non-empty, `path` non-empty, đúng 1 distinct span, và span được `verify_subject` VERIFIED (param `verify_spans: bool = True`). Trạng thái thay thế: `UNBOUND` (thiếu snapshot/path), `UNVERIFIED` (span có nhưng chưa verify, hoặc 0 span). Row có `invalidated_at` bị loại khỏi union.
- `db.py`: thêm cột `provider_evidence.invalidated_at` (migration ALTER TABLE nếu thiếu); `mark_evidence_stale` set nó; thay filter `metadata_json LIKE '%stale%'` bằng `invalidated_at IS NULL`.
- API nguyên tử mới: `record_provider_outcome(run: dict, binding: dict|None, evidence: Sequence[dict]) -> str` — MỘT transaction. `providers/codebase_memory.py` và `importer/scip.py` chuyển sang API này.

### Contract 5 — MCP & federation (`mcp_service.py`, `mcp_server.py`, `orchestrator.py`)

- `search`/`usages`: `provider_policy == "require_external"` → raise `McpServiceError("policy_unsatisfiable", ...)` (fail-closed, không fallback im lặng). `prefer_external` → chạy builtin + warning trung thực trong `policy_meta`.
- Service method mới `scope_receipt` / `diff_impact_receipt` gọi thẳng `assurance.receipts.*` (read-only conn, không ghi ledger); register tool `sot_scope_receipt`, `sot_diff_impact_receipt` trong `mcp_server.py`.
- `federation_plan`: mode `all` probe **tất cả** provider trong `QUERYABLE_PROVIDERS`, trả `plan["providers"]` (danh sách healthy; `plan["provider"]` = đầu tiên để backward-compat). `federated_extras` lặp qua `plan["providers"]`, gộp candidates, giữ provenance per-provider.

---

## 3. Phân bổ thực hiện (3 worker song song, không trùng file)

### A1 — State machine + receipts + identity + CLI (owner: `assurance/state.py` MỚI, `assurance/receipts.py`, `assurance/engine.py`, `cli.py`)
- Tạo `state.py` theo Contract 1.
- `scope_receipt`: dùng `resolve_symbol_identity`; bỏ `LIMIT 1`; gom facts (stale, coverage từ `repo_coverage`, conflicts từ `_ledger_cross_check`, truncation, gate, snapshot binding từ `assured_query_context` mở rộng) → `decide()`; status mới + `reason_codes`; nhúng `scope_digest`/`content_digests` vào payload; công khai gaps/exclusions + unresolved evidence summary.
- `diff_impact_receipt`: post-change facts → `decide()` (snapshot bind `changed_files` ∪ cited paths).
- Bump `RECEIPT_SCHEMA_VERSION` (minor) do vocabulary đổi.
- CLI `cmd_scope_receipt` gọi `scope_receipt` như hiện tại; `cmd_diff_impact` refactor gọi `diff_impact_receipt()` rồi format từ receipt payload (bỏ pipeline ad hoc), giữ phần federated extras.
- Tests: sửa `tests/test_p7_receipts.py` (status mới, counterexample coverage=0 ⇒ không ASSURED); thêm `tests/test_assurance_state.py` (bảng quyết định pure-function, test identity AMBIGUOUS/NOT_FOUND). KHÔNG sửa `tests/test_p8_omp_integration.py` (thuộc A3).

### A2 — Snapshot bind + ledger + DB nguyên tử (owner: `snapshot.py`, `assurance/ledger.py`, `db.py`, `providers/codebase_memory.py`, `importer/scip.py`)
- Contract 2 (snapshot content binding), Contract 4 (ledger fail-closed, `invalidated_at`, `record_provider_outcome`).
- Migrate 2 caller ghi ledger sang API nguyên tử.
- Tests: sửa `tests/test_p6_ledger.py`, `tests/test_cbm_snapshot_p2.py`, `tests/test_cbm_adapter.py`, `tests/test_p9_chaos_migration.py`, `tests/test_phase1_scip_and_schema_v5.py`; thêm invariant test: cùng dirty file 2 nội dung ⇒ scope_digest khác nhau; evidence thiếu snapshot/path ⇒ không bao giờ SUPPORTED.

### A3 — MCP fail-closed + receipt tools + federation `all` (owner: `mcp_service.py`, `mcp_server.py`, `assurance/orchestrator.py`)
- Contract 5.
- Tests: sửa `tests/test_p2_orchestrator.py`, `tests/test_p8_omp_integration.py` (`require_external` ⇒ lỗi; status vocabulary mới theo Contract 1), thêm test tool `sot_scope_receipt` end-to-end qua `mcp_service`.

**Ràng buộc chung:** không chạy formatter toàn repo; không sửa file ngoài danh sách owner; mọi status/field theo Contract 1-5 ở trên; test phải fail trên bug (counterexample trong assessment phải trở thành regression test).

## 4. Wave B — CI release gate (main thread, không trùng worker)

1. Lấy raw log CI fail: `gh run view 33150572364 --log-failed` → root cause thật của 9 test jobs (ưu tiên chứng cứ, không đoán).
2. Reproduce locally: `uv sync --all-extras --dev` trong venv sạch (temp dir) → xác nhận/loại trừ `tree-sitter-graphql`. Nếu build fail: tách grammar ra extra riêng không nằm trong `dev`/`all` HOẶC pin version có wheel.
3. `pyproject.toml`: thêm `ruff==<pin>` + `pyright==<pin>` vào `[dependency-groups].dev` (uv sync mặc định cài).
4. `scripts/quality_gates.sh`: `npx -y ruff` → `uv run ruff`, `npx -y pyright` → `uv run pyright`; bỏ setup Node trong `ci.yml:133-136`.
5. `scripts/e2e_real_cbm.py` (MỚI): fixture repo có symbol đã biết → index → federated query `--provider auto` → assert semantic (tìm đúng symbol, provider run nằm trong ledger, snapshot/provenance bind). Thay bước e2e hiện tại trong `ci.yml`.
6. Chạy verification: targeted tests (p6/p7/p8/p2/cbm) → full `pytest` → quality_gates.sh local.

## 5. Acceptance criteria (ánh xạ DoD assessment §8)

| Điều kiện DoD | Đến từ |
|---|---|
| Target resolve duy nhất (UNIQUE/AMBIGUOUS/NOT_FOUND) | A1 Contract 3 |
| Snapshot bind nội dung bounded scope | A2 Contract 2 |
| Fail-closed mọi fact thiếu (coverage=0, parser fail, conflict, truncation không cho ASSURED) | A1 Contract 1 |
| Ledger chỉ chứa evidence verified cho current snapshot, ghi nguyên tử | A2 Contract 4 |
| CLI và MCP cùng decision function | A1 (CLI) + A3 (MCP tools mới) |
| Provider policy thực thi đúng; mode `all` federation đủ | A3 Contract 5 |
| CI quality gate xanh, e2e real-provider có semantic assert | Wave B |

**Không nằm trong phạm vi đợt này** (theo khuyến nghị §7 assessment): P2 benchmark holdout/diff-impact oracle, SCIP peer-provider hóa đầy đủ, provider mới. Ưu tiên là đóng 5 invariant trust trước.

---

## 6. Verification receipt (2026-08-28, session 2)

- 7/7 test assertion drift đã fix theo contract `state.py` (test_p7_receipts, test_p8_omp_integration, test_p9_chaos_migration).
- Contract sync A2/A3 ↔ A1: cited_paths wired ở mọi caller `capture_worktree_snapshot`; `resolve_symbol_identity` wired vào cli explore/trace + mcp `assured_query_context`; union_evidence map vào AssuranceFacts.
- Fix root cause riêng: `_content_binding` (snapshot.py) fail khi cited path là ABSOLUTE (DB lưu absolute) — normalize realpath về repo-relative, ngoài repo fail-closed. Đây là nguyên nhân digest CLI≠MCP trong `TestCliMcpParity`.
- Fix stub test: `providers: [SimpleNamespace(name="cbm")]` trong test_cbm_verification (orchestrator đọc `provider.name`).
- Full pytest: **843 passed / 0 failed**.
- quality_gates.sh: ruff XANH, pyright 0 errors, core=91% receipts=94%, bandit, pip-audit — **tất cả pass**.
