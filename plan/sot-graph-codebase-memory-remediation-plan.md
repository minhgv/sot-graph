# SOT-Graph × Codebase Memory — Remediation & Completion Plan

> Execution plan dành cho agent nghiên cứu, sửa lỗi và hoàn thiện tích hợp
>
> Ngày lập: 2026-08-26
>
> Baseline SOT-Graph: `bdb2370923ca2b36674b4fdd49c2ecb5b95fa239`
>
> Baseline Codebase Memory: `010569fa6ce1bc5d6430f858129243ea1a2e3fd5` / binary `0.10.8`
>
> Trạng thái: ĐÃ XÁC MINH 2026-08-26 — 20/22 claim xác nhận tại HEAD `bdb2370`; receipts ở mục 3.

## 1. Mục tiêu cuối

Hoàn thiện SOT-Graph thành **verified coding graph gateway** cho OMP:

- Người dùng và OMP chỉ thấy một CLI/MCP của SOT-Graph.
- Codebase Memory chạy như `FEDERATED_CLI` sidecar nội bộ, không MCP lồng MCP.
- Codebase Memory cung cấp discovery/index/graph candidates.
- SOT-Graph xác minh source, snapshot, coverage và provenance trước khi phát hành evidence.
- `stale`, `unbound`, `ambiguous`, `truncated` hoặc uncovered evidence không được diễn giải thành kết luận chắc chắn.
- OMP nhận được scope receipt trước thay đổi và impact/reconcile receipt sau thay đổi.
- SOT-Graph vẫn hoạt động khi Codebase Memory không được cài hoặc gặp lỗi.

## 2. Nguyên tắc không được phá vỡ

1. Không fork hoặc vendor toàn bộ Codebase Memory trong vòng triển khai này.
2. Không đọc trực tiếp SQLite/schema nội bộ của Codebase Memory.
3. Không tự sửa MCP config của agent.
4. Không tự cài hoặc tự index trong một truy vấn read-only.
5. Không dùng `shell=True` hoặc ghép command string.
6. Không claim “100% callers”, “100% exact” hoặc global completeness.
7. External evidence không được `SUPPORTED` chỉ vì provider trả confidence cao.
8. Không đóng task bằng TODO, pass, scaffold hoặc test mock không phản ánh wire thật.
9. Mỗi phase phải hoàn tất exit gate trước khi mở phase kế tiếp.

## 3. Baseline và blocker đã xác minh (receipts 2026-08-26)

HEAD hiện tại bằng đúng baseline `bdb2370` (không có commit nào sau baseline); working tree sạch trừ file plan này (untracked). 20/22 claim của plan được xác nhận; 2 claim được tinh chỉnh (P0-2 root cause, providers doctor).

### P0 blockers — xác minh tại HEAD

| # | Claim | Verdict | Anchor |
|---|---|---|---|
| P0-1 | `cli.py` dùng `Any` nhưng không import → `NameError` khi import module, mọi lệnh `sot` chết khi khởi động | CONFIRMED | `src/sot_graph/cli.py:12` (`from typing import Dict, List, Mapping, Optional, Sequence` — thiếu `Any`), `cli.py:282` (`_supports_capability` dùng `Any`), không có `from __future__ import annotations` |
| P0-2 | Golden fixtures "chưa được commit" | CONFIRMED — root cause chính xác hơn plan: `.gitignore:31` có rule toàn cục `*.json` nuốt cả `tests/fixtures/cbm_golden/`. 8 file (7 golden JSON + `_meta.json`) tồn tại trên đĩa nhưng `git ls-files` trả rỗng | `.gitignore:31`, `tests/fixtures/cbm_golden/_meta.json` |
| P0-3 | CI baseline: test matrix và package smoke đỏ | CORROBORATED qua CI run 32831825122 (không tái hiện local được). Cấu hình workflow đầy đủ: lint + test matrix 3 OS × Python 3.10/3.11/3.12 + package-smoke + release | `.github/workflows/ci.yml:1-124` |

Lưu ý P0-2: sample repo `tests/fixtures/cbm_sample_repo` ĐÃ được track đầy đủ (9 file trong `app/`, `core/`, `generated/`, `scripts/`) — clean clone chỉ thiếu đúng 8 golden JSON.

### Semantic integration gaps — 8/8 CONFIRMED

| # | Claim | Anchor xác minh |
|---|---|---|
| S1 | `trace_path` truyền `max_depth`, CBM yêu cầu `depth`; không gửi `format=json`, không `include_evidence` | `providers/codebase_memory.py:856-861` |
| S2 | Trace normalization mất root, caller/callee relationship, strategy, confidence (chỉ giữ group_qn/name/hop/direction) | `cli.py:437-440`, `cli.py:571-576` |
| S3 | `detect_changes` mặc định text report; impact parser chỉ đọc dict → external impact rơi về `[]` | `providers/codebase_memory.py:935`, `cli.py:549-550` |
| S4 | `diff-impact` không truyền target/depth/staged/working-tree sang provider | `cli.py:383` |
| S5 | Envelope `coverage` chỉ là cờ `queried`, không gọi `check_index_coverage` cho scope thật | `cli.py:703`, `cli.py:717` |
| S6 | Source verifier Python-biased: `.py` dùng AST, ngôn ngữ khác chỉ regex heuristic fallback | `verifier.py:127`, `verifier.py:219`, `providers/verification.py:44`, `providers/verification.py:171` |
| S7 | `search_graph` gửi text args, parser regex từng dòng, không parse cols/groups/pagination | `providers/codebase_memory.py:832`, `cli.py:394-415` |
| S8 | `architecture()` đã cài trong provider nhưng không expose qua SOT CLI/API nào | `providers/codebase_memory.py:942` |

### Wiring gaps — 6/8 CONFIRMED, 2 tinh chỉnh

| # | Claim | Verdict | Anchor |
|---|---|---|---|
| W1 | CLI tạo provider không truyền database ledger | CONFIRMED | `cli.py:350`, `cli.py:825`, `providers_registry.py:119` |
| W2 | `provider_evidence` không ghi trên production query path (chỉ import-scip + tests ghi) | CONFIRMED | `db.py:1957`, `importer/scip.py:809` |
| W3 | `McpService` không invoke provider federation, chỉ đọc tĩnh danh sách provider từ `provider_runs` | CONFIRMED | `mcp_service.py:168-178` |
| W4 | `providers sync codebase-memory` abstain, bắt user tự chạy CBM CLI ngoài | CONFIRMED | `providers/codebase_memory.py:804-818`, `cli.py:826-833` |
| W5 | Query mặc định `builtin`; `auto` bị chặn bởi `allow_external=false`, fallback `names[:1]` | CONFIRMED | `cli.py:307-313`, `cli.py:2109`, `cli.py:2116`, `cli.py:2342` |
| W6 | Chưa có scope/impact receipt và assurance tiers | CONFIRMED — 0 match "receipt" trong `src/sot_graph` | — |
| W7 | `providers doctor` chưa có | TINH CHỈNH: base ĐÃ tồn tại (báo providers_mode, allow_external, conflict_policy, verification_provider, provider status, next_actions); đang thiếu version compatibility, project mapping, snapshot bindability, coverage capability | `providers_registry.py:278-340`, `cli.py:1537-1546` |
| W8 | Ledger chưa nối production path | TINH CHỈNH: cả `provider_runs`, `provider_project_bindings`, `provider_evidence` đã có migrations; adapter đã có write sites (`_persist_run`) — chỉ dead vì W1 (CLI không truyền `db`). G4 chủ yếu là wiring, không phải viết mới schema | `db.py:154`, `db.py:171`, `db.py:415`, `db.py:539`, `db.py:1831`, `db.py:1891`, `providers/codebase_memory.py:518`, `providers/codebase_memory.py:532` |

### Phát hiện mới ngoài plan

- `_meta.json` đã có: binary `0.10.8`, `captured_at`, argv receipts cho cả 7 tool, fixture repo info, wire quirk. Thiếu 4 trường mà G1.3 đòi hỏi: CBM source commit (`010569f`), OS/arch, capture command digest, fixture repo digest.
- Wire quirk 0.10.8 (ghi tại `_meta.json:27`): list-valued flags qua `--flag` không tới server dưới dạng array — `check_index_coverage` ghi nguyên chuỗi JSON thành một `requested_path`. Adapter ở G2 phải dùng `--args-file` cho mọi array argument.
- Duplicate `ensure_index` trong cùng class: `providers/codebase_memory.py:804-819` và `providers/codebase_memory.py:906-921` — G0.6 có target cụ thể.
- Fixture `detect_changes` phụ thuộc git context của repo sot-graph cha (base branch + merge_base) → phải re-capture khi parent repo đổi trạng thái (`_meta.json:26`).

```text
G0 Release recovery
  -> G1 Wire contract & golden truth
    -> G2 Structured semantic adapter
      -> G3 Snapshot + coverage + multilingual verification
        -> G4 Ledger persistence + evidence union
          -> G5 SOT MCP + OMP receipts
            -> G6 UX, sync, docs and release hardening
```

Không chạy song song G2–G5 vì contract và evidence semantics của phase trước là dependency của phase sau.

---

## G0 — Khôi phục release gate

### Mục tiêu

Đưa repo trở lại trạng thái CLI chạy được và CI có thể đánh giá chính xác các phase sau.

### Tasks

- [x] `G0.1` Thêm `Any` vào `from typing import ...` tại `src/sot_graph/cli.py:12` (đã verify: walk-import toàn package 0 failure).
- [x] `G0.2` Thêm smoke test import `sot_graph.cli` (`tests/test_cli_smoke.py`, 3 test). Lưu ý: `tests/test_cli_provider_wiring.py:16` và `tests/test_omp_integration.py:48` đã xanh lại sau P0-1.
- [x] `G0.3` Đã chạy `sot --version` (`sot 0.3.0`), `--help`, `providers --help` từ source checkout, wheel VÀ sdist cài vào temp venv sạch.
- [x] `G0.4` Xác nhận package smoke và test matrix 13/13 jobs xanh trên Python 3.10, 3.11, 3.12 × Linux, macOS, Windows (CI run `32944368819`, commit `7d03014`).
- [x] `G0.5` Đã verify `.github/workflows/ci.yml` không có `continue-on-error`/`if: always` — job đỏ chặn merge theo cấu trúc.
- [x] `G0.6` Đã xóa định nghĩa `ensure_index` thứ hai (`providers/codebase_memory.py:906-923`, byte-identical với bản giữ lại).

### Tests bắt buộc

```bash
python -c "import sot_graph.cli"
sot --version
sot --help
pytest -q tests/test_cli_provider_wiring.py
pytest -q tests/test_omp_integration.py
```

### Exit gate

- CLI import và chạy được trong source checkout, wheel và sdist.
- Không dùng runtime shim hoặc monkeypatch `builtins.Any` để làm test pass.
- CI package smoke xanh trên Linux, macOS và Windows.

---

## G1 — Đóng băng wire contract bằng bằng chứng thật

### Mục tiêu

Biến ADR/compatibility matrix thành contract có thể tái lập trong CI.

### Tasks

- [x] `G1.1` 7/7 fixture tồn tại và được commit (c2); argv/cwd/exit receipts trong `_meta.json`. Lưu ý còn hợp lệ: fixture capture dạng `cli --json`; tổ hợp `format=json`/`include_evidence` ở tool-level sẽ do G2 xử lý qua `--args-file`.
- [x] `G1.2` Đã sửa `.gitignore:31` (exception `!tests/fixtures/**/*.json`), commit 8 file golden + `_meta.json`.
- [x] `G1.3` `_meta.json` đã bổ sung: source commit `010569fa`, OS/arch, `capture_command_digest`, `fixture_repo_digest` (kèm recipe tái lập trong `receipts[]`).
- [x] `G1.4` Divergence đã ghi trong ADR §6 (binary 0.10.8 thiếu `head_sha`/`branch` so với source; list-flag quirk) + G1 addendum.
- [x] `G1.5` Version gate triển khai: `version_compatibility()` 4 trạng thái; INCOMPATIBLE fail-closed; UNTESTED/UNKNOWN cap `UNVERIFIABLE` qua `trust_ceiling(version_compatibility=...)`; test matrix trong `TestVersionGate` + ceiling tests.
  - tested version → chạy adapter;
  - version chưa biết → `UNVERIFIABLE` hoặc require explicit override;
  - incompatible version → fail closed với next action.
- [x] `G1.6` Matrix failure-mode map đầy đủ sang test anchors (ADR G1 addendum): exit code, malformed, multi-JSON, stdout-log, cap/truncated, schema drift, version sai/thiếu/chưa test, pagination.
- [x] `G1.7` Receipts per-tool + gate + provenance đã append vào ADR (`### G1 addendum`).

### Test matrix

| Case | Expected |
|---|---|
| Binary đúng 0.10.8 | Parse fixtures thành công |
| Binary thiếu | Optional mode fallback; required mode fail closed |
| Version output sai | Provider unhealthy |
| Version chưa kiểm thử | Không phát hành verified evidence |
| JSON thiếu field | Schema drift, abstain |
| Nhiều JSON documents | Reject |
| stdout chứa log | Reject contract violation |
| stderr chứa diagnostic | Không làm hỏng payload |
| Payload vượt cap | Reject partial evidence |

### Exit gate

- Golden suite chạy được từ clean clone.
- Không còn fixture được mô tả trong docs nhưng thiếu trong Git.
- Compatibility matrix và code gate dùng cùng một version vocabulary.

---

## G2 — Structured semantic adapter

### Mục tiêu

Không parse human-readable text để tạo evidence graph khi provider đã có JSON model.

> Wire quirk 0.10.8 (`_meta.json:27`): list-valued flags qua `--flag` không tới server dạng array. Adapter phải dùng `--args-file` cho mọi array argument (ảnh hưởng `check_index_coverage` ở G3.2 và mọi query nhiều giá trị).

### G2.1 Search

- [ ] Gửi `format=json` cho `search_graph`.
- [ ] Parse `cols`, row arrays, groups, `total`, `offset`, `has_more`.
- [ ] Giữ nguyên qualified name, path, kind, span, rank và provider fields.
- [ ] Hỗ trợ path có space, Unicode và platform separator.
- [ ] Không đồng nhất symbol chỉ bằng short name.

### G2.2 Trace

- [ ] Map `TraceRequest.max_depth` sang CBM field `depth`.
- [ ] Gửi `format=json` và `include_evidence=true`.
- [ ] Chuẩn hóa thành directed edge:

```text
root --outbound--> callee
caller --inbound--> root
```

- [ ] Giữ direction, hop, strategy, confidence, cursor và total.
- [ ] Không dùng cùng một QN làm cả source và target.
- [ ] Tách `CALLS`, `CALL_REFERENCE`, `USAGE`/`REFERENCES`; không map mọi usage thành `CALLS`.
- [ ] Nếu trace row thiếu path/span, resolve bằng structured search hoặc đánh dấu low-resolution; không tự tạo span.

### G2.3 Diff impact

- [ ] Gửi `format=json` cho `detect_changes`.
- [ ] Map SOT target sang `since` hoặc `base_branch` với semantics được test.
- [ ] Map SOT `depth` sang CBM `depth`.
- [ ] Làm rõ staged/working-tree support:
  - nếu CBM hỗ trợ cùng scope → truyền đúng;
  - nếu không → ghi conflict scope và không merge như cùng một analysis.
- [ ] Parse `changed_files`, seeds, impacted, impacted_total, modules, direction và truncated.
- [ ] Gắn một `diff_identity` chung trước khi hợp nhất builtin và CBM output.

### G2.4 Architecture

- [ ] Expose architecture provider method qua public SOT query/API.
- [ ] Chuẩn hóa languages, packages, entry points, dependencies, boundaries, clusters và cycles thành candidate architecture evidence.
- [ ] Architecture inference không được coi là source-verified nếu thiếu anchors.

### Exit gate

- Không còn production evidence parser phụ thuộc whitespace layout của text report.
- Trace test chứng minh đúng source, target, direction và hop.
- Diff-impact builtin và CBM luôn mang cùng diff identity trước khi so sánh.
- Pagination/truncation không bị mất trong envelope.

---

## G3 — Snapshot, coverage và verifier đa ngôn ngữ

### Mục tiêu

Một candidate chỉ được nâng độ tin cậy khi chứng minh được freshness và source anchor trên worktree hiện tại.

### G3.1 Snapshot binding

- [ ] Tạo SOT snapshot trước provider query:
  - HEAD SHA;
  - dirty flag;
  - dirty fingerprint;
  - manifest digest;
  - generation;
  - snapshot ID.
- [ ] So sánh CBM Git metadata khi provider trả được.
- [ ] Với CBM 0.10.8 không có `head_sha`, giữ verdict tối đa `UNVERIFIABLE`.
- [ ] Không dùng path-level coverage để suy ra global snapshot equality.
- [ ] Gắn `snapshot_id` và `snapshot_hash` vào provider run/evidence.

### G3.2 Coverage

- [ ] Gọi `check_index_coverage` cho mọi cited path.
- [ ] Gọi bounded scope coverage trước negative/exhaustive claim.
- [ ] Propagate:
  - indexed/partial/skipped/excluded;
  - parse-error ranges;
  - hash freshness;
  - pagination;
  - caveat và recommended action.
- [ ] Phân biệt `queried=true` với actual coverage result.
- [ ] Nếu coverage API lỗi, completeness phải downgrade.

### G3.3 Multilingual source verification

- [ ] Tách verifier theo language hoặc dùng AST/span verifier chung.
- [ ] Tối thiểu hỗ trợ Python, TS/JS, Go, Rust, Java và C/C++ trước khi claim broad verification.
- [ ] Verify file containment, content hash, line/column span và symbol identity.
- [ ] Đối với generated/vendor paths, giữ explicit known gap.
- [ ] Dynamic dispatch, reflection, macros, DI registration và function pointers phải có gap taxonomy.

### Correctness fixtures

Mỗi language fixture phải có:

- direct caller;
- same-name symbols trong hai scope;
- alias import;
- interface/virtual call;
- dynamic/reflection case;
- generated/excluded file;
- dirty edit, rename và delete;
- caller ngoài module target.

### Exit gate

- Dirty worktree không thể được đánh dấu fresh chỉ vì HEAD không đổi.
- Verifier không dùng Python regex cho symbol thuộc ngôn ngữ khác.
- Zero-result không trở thành negative claim nếu scope coverage chưa đủ.
- Stale/unbound evidence không bao giờ đạt `SUPPORTED`.

---

## G4 — Ledger persistence và evidence union

### Mục tiêu

Nối schema/provider tests hiện có vào production query path.

### Tasks

- [ ] `G4.1` Truyền active `Database`/ledger vào provider từ CLI và MCP service.
- [ ] `G4.2` Persist mỗi provider invocation vào `provider_runs`.
- [ ] `G4.3` Persist project mapping/generation vào `provider_project_bindings`.
- [ ] `G4.4` Persist normalized assertions vào `provider_evidence`.
- [ ] `G4.5` Ghi provider version, capability, command digest, snapshot, status, duration, exit code và trust metadata.
- [ ] `G4.6` Commit run + evidence atomically; parse/verify hoàn tất trước transaction.
- [ ] `G4.7` Merge theo canonical identity và relation, không winner-takes-all.
- [ ] `G4.8` Giữ support/contradict provenance của từng provider.
- [ ] `G4.9` Query chỉ liệt kê provider active cho snapshot hiện tại, không trộn historic stale runs.
- [ ] `G4.10` Sidecar/ledger failure không được corrupt `.sot/sot.db`.

### Merge policy

```text
same identity + same relation + same target
  -> evidence union; retain provider list

same identity + conflicting targets
  -> source verification attempts adjudication
  -> unresolved => CONFLICT / abstain

different snapshot
  -> never merge as corroboration
```

### Exit gate

- Một CLI query thật tạo được provider run và evidence rows có snapshot.
- Purge một run không làm mất evidence của provider/run khác.
- MCP query không hiển thị provider lịch sử như provider active hiện tại.
- Conflict không bị âm thầm bỏ qua.

---

## G5 — Một SOT MCP và OMP receipts

### Mục tiêu

OMP không cần khai báo Codebase Memory MCP nhưng vẫn dùng được external graph evidence qua SOT.

### G5.1 MCP federation

- [ ] Đưa provider orchestration vào `McpService` hoặc shared service layer, không gọi private CLI functions.
- [ ] CLI và MCP dùng cùng normalization, merge, coverage và trust engine.
- [ ] Không thêm public MCP server/tool namespace của Codebase Memory.
- [ ] MCP input hỗ trợ `provider` và `assurance` policy.

### G5.2 Assurance tiers

| Tier | Hành vi |
|---|---|
| `scout` | Builtin + candidate discovery; latency thấp; không negative claim |
| `verify` | Snapshot/source verification và path coverage cho cited evidence |
| `audit` | Multi-provider union, full bounded pagination, scope coverage và conflict report |

### G5.3 Scope receipt

Receipt trước thay đổi phải có:

- resolved target và source anchor;
- direct callers/callees;
- imports, implementations và inheritance;
- affected files/modules;
- candidate tests;
- provider/run/version;
- snapshot;
- coverage/exclusions/unresolved;
- conflicts/truncated;
- live-LSP/source confirmations OMP cần thực hiện.

### G5.4 Impact/reconcile receipt

Receipt sau thay đổi phải có:

- diff identity và changed symbols;
- upstream/downstream impact;
- new/removed/changed edges;
- stale evidence bị invalidated;
- targeted test receipt;
- reconcile result và snapshot mới.

### Exit gate

- OMP config chỉ chứa SOT MCP.
- Một E2E task thực hiện được:

```text
scope receipt -> plan -> edit -> targeted tests
-> diff-impact receipt -> reconcile -> reviewer receipt
```

- Pre-change receipt không được dùng làm proof cho post-change snapshot.

---

## G6 — UX, sync, documentation và release hardening

### G6.1 Provider UX

- [ ] Giữ `allow_external=false` làm security opt-in mặc định.
- [ ] Khi người dùng bật `allow_external=true` và `providers_mode=auto`, query tự dùng provider khả dụng mà không cần lặp `--provider auto`.
- [ ] `prefer` fallback trung thực; `require` fail closed.
- [ ] `all` phải thật sự invoke tất cả queryable providers hoặc không quảng bá semantics này.
- [ ] Mở rộng `providers doctor` — base ĐÃ tồn tại tại `providers_registry.py:278-340` và `cli.py:1537-1546` (hiện báo providers_mode, allow_external, conflict_policy, verification_provider, provider status, next_actions). Bổ sung: version compatibility, project mapping, snapshot bindability, coverage capability.

### G6.2 Explicit sync

- [ ] `sot providers sync codebase-memory` bọc `index_repository` như một hành động explicit.
- [ ] Không index implicit trong read query.
- [ ] Có timeout riêng, progress, cancellation, lock và receipt.
- [ ] User không phải tự chạy lệnh CBM trực tiếp.
- [ ] Không cài binary trong `sync`; managed install thuộc P4 riêng.

### G6.3 Documentation cleanup

- [ ] Xóa/đổi toàn bộ claim:
  - `100% exact cross-file references`
  - `100% reliable anchor`
  - `100% verified`
  - `100% grounded facts`
- [ ] Thay bằng capability- và coverage-scoped wording.
- [ ] Cập nhật AGENTS, OMP rules, generated adapter templates, skills và docs cùng lúc.
- [ ] Ghi rõ `SUPPORTED` không đồng nghĩa global completeness.

### G6.4 Release qualification

- [ ] Clean-install CI trên Python 3.10–3.12 và ba OS.
- [ ] Wheel/sdist smoke.
- [ ] Actual CBM binary E2E job trên ít nhất Linux.
- [ ] Closed-world positive/negative accuracy oracle.
- [ ] Latency/memory/indexing benchmark.
- [ ] License/third-party notice check nếu phân phối sidecar ở P4.

### Exit gate

- Người dùng dùng một SOT interface cho detect, sync và query.
- Tất cả CI và package smoke xanh.
- Không còn absolute reliability claim trong agent-facing instructions.

## 5. Test pyramid

### Unit

- Wire envelope parser.
- Relation mapping.
- Canonical identity.
- Trust ceilings.
- Language-aware span verification.
- Snapshot comparison.
- Coverage completeness.
- Conflict merge.

### Contract

- Golden binary fixtures.
- Version compatibility.
- Schema drift.
- Pagination/cursor.
- JSON/text format selection.

### Integration

- Fake executable failure matrix.
- Real CBM 0.10.8 fixture repository.
- SQLite transaction and crash injection.
- Dirty/rename/delete/reindex lifecycle.
- CLI provider modes.

### End-to-end

- CLI-only workflow.
- SOT MCP-only OMP workflow.
- Optional provider missing.
- Required provider missing.
- Provider stale.
- Provider conflict.
- Post-change reconcile.

## 6. Definition of Done tổng thể

- [ ] `sot --version` và full CI pass từ clean clone.
- [ ] Golden fixtures tồn tại và có capture receipts.
- [ ] Structured JSON dùng cho search, trace và impact.
- [ ] Trace giữ đúng caller/callee direction, hop và evidence strategy.
- [ ] Diff scope giữa builtin và CBM được đồng nhất hoặc báo conflict.
- [ ] Coverage là kết quả coverage thật, không phải cờ queried.
- [ ] Snapshot bao gồm dirty state; stale/unbound không `SUPPORTED`.
- [ ] Verifier hỗ trợ tối thiểu sáu language families mục tiêu.
- [ ] Production CLI/MCP persist provider runs và normalized evidence.
- [ ] MCP gọi federation qua SOT, không lộ CBM MCP.
- [ ] Scope/impact receipts có provenance, snapshot, gaps và conflicts.
- [ ] Explicit SOT sync không yêu cầu người dùng gọi CBM CLI.
- [ ] Không còn claim “100%” gây overtrust.
- [ ] SOT vẫn hoạt động đầy đủ bằng builtin khi CBM vắng mặt.

## 7. Stop conditions

Agent phải dừng và báo blocker nếu:

- Binary output không khớp source/schema và chưa có golden proof.
- Không xác định được diff identity chung giữa SOT và CBM.
- Provider không cung cấp dữ liệu đủ để bind snapshot.
- Không phân biệt được caller/callee direction.
- Coverage không chứng minh được scope của negative claim.
- Một thay đổi cần fork/vendor hoặc sửa external agent config.
- Full suite phát sinh regression ngoài phạm vi và chưa xác định nguyên nhân.

UNKNOWN phải được giữ là UNKNOWN; không dựng giả contract để tiếp tục.

## 8. Prompt giao agent

```text
Hãy thực hiện kế hoạch trong
`sot-graph-codebase-memory-remediation-plan.md` theo đúng thứ tự G0 -> G6.

Phạm vi turn đầu tiên chỉ gồm G0 và G1. Không tự mở rộng sang G2 khi exit gate
G0/G1 chưa xanh.

Quy tắc thực thi:
1. Đọc đầy đủ AGENTS.md và instruction files liên quan.
2. Khởi tạo todo cho từng task; chỉ một task in_progress.
3. Xác nhận HEAD và working tree trước khi sửa; không ghi đè thay đổi của người dùng.
4. Mỗi phát hiện phải có file:line receipt và command/test receipt.
5. Dùng source và tests của Codebase Memory tại commit đã pin; không dựa riêng README.
6. Không shell=True, không direct CBM DB access, không MCP-over-MCP, không fork/vendor.
7. Viết hoặc sửa test cùng implementation; mock không được thay golden binary evidence.
8. Chạy targeted tests trước, sau đó full suite, package smoke và clean-install checks.
9. Reviewer độc lập kiểm tra correctness, security, snapshot honesty, schema drift,
   backward compatibility và documentation overclaims.
10. Kết thúc bằng deliverable proof:
    - changed files và line anchors;
    - command, exit code và test counts;
    - CI/status;
    - acceptance checklist pass/fail;
    - known gaps;
    - phase kế tiếp được phép mở hay chưa.

G0 bắt buộc sửa CLI runtime import và chứng minh wheel/sdist chạy.
G1 bắt buộc commit golden fixtures thật, chốt version compatibility và làm golden
suite chạy được từ clean clone. Không tuyên bố hoàn thành nếu fixture vẫn chỉ tồn tại
trên máy cá nhân hoặc trong tài liệu.
```

## 9. Khuyến nghị tổ chức commit

Giữ commit nhỏ, có thể review và rollback:

1. `fix(cli): restore runtime import and package smoke`
2. `test(cbm): add reproducible 0.10.8 golden captures`
3. `fix(cbm): enforce tested wire compatibility`
4. `feat(cbm): consume structured search and trace models`
5. `fix(impact): align provider diff identity and JSON impact model`
6. `feat(trust): bind dirty snapshot and scoped coverage`
7. `feat(verify): add multilingual source-span verification`
8. `feat(ledger): persist and merge federated evidence`
9. `feat(mcp): expose federation and assurance through SOT only`
10. `feat(omp): emit scope and impact receipts`
11. `feat(providers): explicit SOT-managed index sync`
12. `docs(trust): remove absolute completeness claims`

Không gom tất cả vào một commit lớn vì sẽ khó xác định regression giữa wire parsing, trust semantics và MCP workflow.

## 10. Nguồn baseline

- [SOT-Graph baseline](https://github.com/minhgv/sot-graph/tree/bdb2370923ca2b36674b4fdd49c2ecb5b95fa239)
- [Codebase Memory baseline](https://github.com/DeusData/codebase-memory-mcp/tree/010569fa6ce1bc5d6430f858129243ea1a2e3fd5)
- [SOT ADR federated CLI](https://github.com/minhgv/sot-graph/blob/bdb2370923ca2b36674b4fdd49c2ecb5b95fa239/docs/adr/0001-federated-cli-provider.md)
- [Baseline CI run](https://github.com/minhgv/sot-graph/actions/runs/32831825122)
