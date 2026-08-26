# SOT-Graph — Impact-Assurance Execution Plan (P0–P9)

> Execution plan chi tiết triển khai roadmap `plan/sot-graph-flexible-impact-assurance-roadmap.md` (R0–R9).
>
> Supersede `plan/sot-graph-codebase-memory-remediation-plan.md` **từ G2 trở đi**: G0/G1 đã hoàn tất (CI run `32944368819`, 13/13); mọi việc còn lại của G2–G6 được hấp thụ vào P-phase tương ứng (bảng mapping mục 2).
>
> Baseline: `cb1bf693d2fbcc703018207bd2e665fb708ab32c` · kiểm chứng 2026-08-26 · CBM contract `010569fa…/0.10.8` (`tests/fixtures/cbm_golden/_meta.json:8`).

## 1. Kết quả kiểm chứng roadmap §2 (receipts 2026-08-26, HEAD `cb1bf69`)

### 1.1 Baseline §2.1

| Claim | Verdict | Receipt |
|---|---|---|
| CLI/wheel/sdist/MCP smoke chạy được | CONFIRMED | G0 receipts; `sot 0.3.0` từ wheel+sdist |
| 13/13 CI jobs xanh (py 3.10–3.12 × 3 OS) | CONFIRMED | `.github/workflows/ci.yml` = 1 lint + 9 test + 3 package-smoke + 1 release (không tag → không chạy) |
| Full local suite "595 passed" | **REFUTED (số sai)** | Thực tế `595` là TỔNG: 589 passed + 1 failed + 5 skipped. **Đã fix P0.a**: sau bump timeout, 595 = **590 passed + 5 skipped, 0 failed × 3 runs liên tiếp** (2026-08-26) |
| Line coverage ~80% | NOT-VERIFIABLE-FROM-REPO | `pyproject.toml:139-146` không có `--cov`/`[tool.coverage]`; không artifact. Con số chỉ xuất hiện trong doc plan cũ |
| Golden CBM 0.10.8 + capture receipts | CONFIRMED | `tests/fixtures/cbm_golden/_meta.json` — đủ 11 keys gồm `source_commit`, `os_arch`, `capture_command_digest`, `fixture_repo_digest` (G1.3 đã bổ sung xong) |
| Adapter argv-only/args-file/timeout/killpg/redaction/version gate | CONFIRMED | `src/sot_graph/proc.py:66-150`; `providers/codebase_memory.py:378-450` |
| Stress test 100 vòng mutation/reconcile/integrity | CONFIRMED | `tests/test_storage_integrity.py:78-105` |
| Context pack giảm 81,4–92,2% token | CONFIRMED (script, số runtime) | `scripts/benchmark_context.py:40-75`, 3 target mặc định; chưa có artifact JSON commit |

### 1.2 Blockers §2.2

| # | Claim | Verdict | Receipt |
|---|---|---|---|
| 1 | Dirty edit vẫn FRESH nếu HEAD khớp | CONFIRMED | `providers/codebase_memory.py:829-843` chỉ so `head_sha`; khi `paths=()` không gọi `is_dirty()`. Builtin `explore`/`usages` đọc SQLite không check dirty/hash (`cli.py:850-865`). **Lưu ý: snapshots table ĐÃ có dirty flag + sha256 dirty_fingerprint** (`snapshot.py:61-67`) — data model sẵn, chỉ thiếu wiring |
| 2 | Benchmark không match đúng tuple | CONFIRMED | `scripts/benchmark_accuracy.py:165-201` match 3-tuple `(file, src, target)`, bỏ `relation` + span |
| 3 | Oracle TS 61,5% / Go 41,7% | **MEASURED (P0.e)** | Exact oracle v2.0.0 trên corpus độc lập: TS **60,4%** / Go **40,9%** recall — xác nhận gần đúng claim roadmap. Rust phát hiện mới: R **2,3%**. `benchmarks/oracle/builtin-baseline.json` |
| 4 | CBM text parser mất semantic fields | CONFIRMED | S1/S2/S3/S7 remediation plan (đã verify 2026-08-26) |
| 5 | diff-impact không truyền target/depth/staged/worktree | CONFIRMED | S4 — `cli.py:383` |
| 6 | Coverage chỉ là cờ `queried` | CONFIRMED | S5 — `cli.py:703,717` |
| 7 | CLI không truyền active DB; runs/evidence không persist | CONFIRMED | W1/W8 — `cli.py:350,825`; `providers_registry.py:119`; write sites chết `providers/codebase_memory.py:518,532` |
| 8 | MCP chưa gọi federation | CONFIRMED | W3 — `mcp_service.py:168-178` chỉ đọc tĩnh `provider_runs` |
| 9 | Chưa có receipt/assurance tiers | CONFIRMED | W6 — 0 match "receipt" trong `src/sot_graph` |
| 10 | Verifier Python-biased | CONFIRMED | S6 — `verifier.py:127,219`; `providers/verification.py:44,171` |
| 11 | Templates còn claim "100%" | CONFIRMED | 12 chỗ agent-facing: `adapters/AGENTS.md:43`; `adapters/antigravity.py:35,116`; `adapters/claude.py:49`; `adapters/omp.py:30,108`; `adapters/opencode.py:36,115`; `adapters/zcode.py:37,116`; `templates/ARCHITECTURE_TEMPLATE.md:23,72,74` |
| 12 | CI lint chỉ compile | CONFIRMED | `ci.yml:31` chỉ `compileall`; không ruff/mypy/coverage/security |
| 13 | Output cắt sau `communicate()`, không streaming cap | CONFIRMED | `proc.py:117-140` — buffer toàn bộ vào RAM rồi slice; chỉ kill khi timeout, không kill khi vượt cap |

### 1.3 Phát hiện thêm (ngoài roadmap)

- Test flaky stderr-capture (mục 1.1) — phải fix trước khi baseline P0 có ý nghĩa.
- `snapshots` schema đã có dirty fingerprint → R1 nhẹ hơn roadmap dự đoán: chủ yếu là wiring + so sánh, không phải thiết kế schema mới.
- ~~Số "595 passed" phải sửa~~ Đã sửa: baseline thật 590+5 (P0.a, 3 runs). Số liệu oracle thật đã commit machine-readable (P0.e).

## 2. Thứ tự phase và mapping hai plan cũ

```text
P0 Accuracy oracle (R0)
  -> P1 Snapshot & trust blocker (R1)
    -> P2 Shared assurance orchestrator (R2)
      -> P3 Provider adapters hoàn thiện (R3 ≈ G2 + G6.2)
        -> P4 Canonical identity & search accuracy (R4)
          -> P5 Coverage & multilingual verification (R5 ≈ G3.2/G3.3)
            -> P6 Evidence ledger & conflict (R6 ≈ G4)
              -> P7 Impact engine & receipts (R7 ≈ G5.3/G5.4)
                -> P8 OMP integration (R8 ≈ G5.1/G5.2 + G6.3)
                  -> P9 Hardening & release (R9 ≈ G6.1/G6.4 + mở rộng)
```

Lý do giữ thứ tự R thay vì tiếp G2 ngay (đã cân nhắc):

1. **P0 trước P3**: sửa Go/TS recall (R3.3) và mọi claim "adapter tốt hơn" cần oracle đúng tuple; không có oracle thì structured parse không thể chứng minh cải thiện semantic.
2. **P1 trước P2/P3**: canonical candidate (roadmap §5.2) mang `snapshot_claim`; parse mà không gắn snapshot ngay sẽ làm 2 lần.
3. **P2 trước P3**: parser đặt trong `assurance/` ngay từ đầu, tránh viết structured parser trong `_cbm_candidates_from_outcome` (`cli.py:500-580`) rồi chuyển lớp sau.

Cho phép song song trong cùng phase (roadmap §10): corpus ngôn ngữ độc lập, golden capture độc lập, benchmark hiệu năng sau khi correctness xanh.

Mapping G→P (không mất việc đã lên): G2.1→P3.1, G2.2→P3.1, G2.3→P3.1+P7, G2.4→P3.1, G3.1→P1, G3.2→P5, G3.3→P5, G4.*→P6, G5.1→P2+P8, G5.2→P8, G5.3→P7, G5.4→P7, G6.1→P8/P9, G6.2→P3.1, G6.3→P8, G6.4→P9.

## 3. Đầu vào sẵn có (không làm lại)

- Golden fixtures CBM 0.10.8 cho 7 tool + `_meta.json` đầy đủ (argv receipts, digests) — dùng cho P3 contract tests.
- Wire quirk đã đóng băng (`_meta.json:27`): array argument bắt buộc qua `--args-file`.
- `WriteLock` CAS (`.sot/write.lock`, `locking.py:20-113`) — tái dùng cho P1/P3 sync indexing.
- `snapshots` table có `dirty` + `dirty_fingerprint` sha256 (`snapshot.py:61-67`).
- Trust ceiling ladder 7 bậc + verdicts (`normalization.py:240-340`) — chỉ mở rộng, không nới trần.
- Ledger migrations + `_persist_run` write sites (`db.py:154,171,415,539`; `codebase_memory.py:518,532`) — P6 chủ yếu wiring.
- Honest guards: 0-caller pending guard (`cli.py:965-968`), fail-closed require/auto (`cli.py:726-738`).

## 4. Nguyên tắc bất biến

Kế thừa toàn bộ roadmap §3 (12 invariant) + non-negotiables plan cũ: không fork/vendor CBM, không đọc SQLite nội bộ CBM, không MCP lồng MCP, không `shell=True`, không index implicit trong read query, UNKNOWN giữ nguyên là UNKNOWN, không runtime shim/monkeypatch để test pass, không claim "100%". Mỗi phase: commit nhỏ review-able, chạy `.venv/bin/python -m pytest -q` local trước push, CI 13/13 xanh là điều kiện merge phase.

## P0 — Accuracy oracle và truth baseline (R0)

### Mục tiêu

Thay proxy-test bằng evaluator phát hiện sai caller/target thật. Mọi con số accuracy về sau lấy từ oracle này.

### Việc

- [x] P0.a Vệ sinh baseline: fix flaky `test_stderr_captured_when_timeout_kills` (bump `timeout_seconds` 0.5→2.0 tại `tests/test_proc_process_group.py:87`); full suite 3 lần liên tiếp **0 failed**: 590 passed + 5 skipped (61.65s / 52.87s / 53.56s) — receipt 2026-08-26.
- [x] P0.b Oracle exact 6-tuple `(repo, path, src identity, relation, dst identity, span)`: viết lại `scripts/sot_evaluator.py` v2.0.0 (matching group-aware vì PK `(path,src,dst,relation)` collapse nhiều call-site; FN ladder: span_mismatch → identity_unqualified → wrong_target_same_bare_name → wrong_relation → pending_unresolved → edge_absent; legacy 3-tier matcher giữ lại CHỈ làm diagnostic `legacy_loose_recall_diagnostic`). `scripts/benchmark_accuracy.py` chuyển sang exact identity+span (6/6 TP, P=R=1.0 trên corpus Python).
- [x] P0.c Corpus 3 tập polarity: static_positive (910→1012 sau khi thêm constructor-call) / static_negative (110) / dynamic_positive (26, claim optional — never merged vào static P/R). Đủ 12 case bắt buộc: same-name 2 scope, alias import, shadowing (param/local/for-target), nested scope, overload, virtual/interface dispatch, reflection, DI, macros, function pointers, generated file, caller ngoài module.
- [x] P0.d 5 ngôn ngữ Tier-A: Python, TypeScript, Go, Rust, Java — 234 files, corpus digest sha256 frozen trong baseline JSON.
- [x] P0.e `benchmarks/oracle/builtin-baseline.json` commit: overall P 99.2% / R 69.4% / F1 81.6%; per-language: python 99.7/99.7, java 100/98.5, typescript 98.5/**60.4**, go 98.5/**40.9**, rust 60.0/**2.3**. **Xác nhận 2 con số roadmap**: TS 60.4% ≈ claim 61.5%, Go 40.9% ≈ claim 41.7% (mặc dù corpus mới độc lập). Phát hiện mới ngoài roadmap: Rust impl-block gần như mất hết cạnh (R 2.3%); resolver bind cross-language (Go `Stage.Process→normalizeStage` vào node TypeScript); 3 false positive thật trên bẫy same-name-two-scopes (py/ts/rust).
- [x] P0.f Top-k symbol-search oracle k∈{1,5,10} trên `search_fts`: hit@1 50%, hit@5 75%, hit@10 85% (20 probes: 12 unique + 8 ambiguous, tách riêng trong JSON).
- [x] P0.g CBM probe (binary 0.10.8 có sẵn tại `~/.local/bin/codebase-memory-mcp`): `benchmarks/oracle/cbm-probe.json` — exploratory sample (hop-1 callees, qualified-name level, không check được span qua trace_path); CBM resolve đúng `run_pipeline→Pipeline.process` và CẢ HAI `Doc.save`/`Blob.save` Rust mà builtin sai/thiếu.
- [x] P0 test bắt buộc: `tests/test_oracle_selfcheck.py` 13 test — synthetic discrimination (wrong-target ≠ TP; bare-name khác cạnh ≠ recall, legacy loose đếm được chính cạnh đó = chứng minh phân biệt; span mismatch; call-site collapse; negative FP; identity_unqualified không double-punish) + integration (JSON contract, per-language breakdown, confusion line-anchored, Go/TS defect visible). CI job `accuracy-oracle` (selfcheck + full run + corpus-digest guard + artifact).

### Test bắt buộc

- Oracle tự kiểm: fixture một edge sai target KHÔNG tính true positive; một tên xuất hiện ở cạnh khác KHÔNG tính recall (viết test nhỏ trên corpus nhân tạo).
- Benchmark cũ phải fail trên defect Go/TS hiện biết (chứng minh oracle phân biệt được).

### Exit gate

- `benchmarks/oracle/builtin-baseline.json` commit, có per-language/per-relation precision/recall/F1 + confusion set line-anchored.
- Baseline suite local: 0 failed, số liệu ghi trong plan khớp output chạy thật.
- Không thay đổi hành vi production (P0 chỉ thêm evaluator + sửa test).

## P1 — Snapshot & trust blocker (R1)

### Mục tiêu

Không evidence nào được FRESH/assured khi worktree đổi sau index/query; output subprocess có streaming hard cap.

### Việc

- [x] P1.a Dirty wire vào `snapshot_match` (`codebase_memory.py`): thêm `dirty_state()` tri-state (True/False/None-unverifiable) trong `snapshot.py`; dirty → `fresh=False` + `freshness="STALE"` **kể cả khi head_sha khớp và paths=()**; git-status fail → `fresh=False` ("unknown: unverifiable"). `SnapshotMatch` thêm field `dirty` + `dirty_fingerprint`. Blocker #1 reproduction: `tests/test_p1_snapshot_trust.py::test_matching_head_dirty_worktree_is_stale`.
- [x] P1.b `capture_worktree_snapshot()` (`snapshot.py`) — descriptor chung (HEAD sha, tri-state dirty, sha256 dirty fingerprint, manifest digest + generation khi có conn, role, `descriptor_digest` so sánh được); read-path KHÔNG ghi DB (`snapshot_id=None`); persist qua `bind_snapshot` khi cần. `explore`/`usages` gắn `snapshot` vào envelope; external run rows đã có cột `snapshot_id` sẵn (wire active-Database vào provider thuộc P6/W1, ghi nhận trong P6).
- [x] P1.c `db.stale_journal_files(paths, root)` (so size+mtime_ms rồi sha256 — mirror reconciler scan); wire vào `cmd_explore`, `cmd_usages`, `cmd_diff_impact` trên mọi cited file (target + relations/callers/risk; diff-impact: changed_files + direct_nodes + caller_impacts). Stale → warning + `stale_files` trong payload JSON.
- [x] P1.d TOCTOU trong `verify_subject`: stat (size, mtime_ns) trước read + re-stat sau read; lệch → verdict mới `SNAPSHOT_RACE` (abstain). Test: fake stat giữa chừng → SNAPSHOT_RACE.
- [x] P1.e `db.mark_evidence_stale(paths, reason)` — UPDATE `provider_evidence.invalidated_at/invalidation_reason` (columns thêm vào SCHEMA + ensure无条件 mỗi open), mark-không-xóa, idempotent; trigger từ stale-detection của P1.c. Nền cho P6 pre/post-change ledger.
- [x] P1.f `proc.py` viết lại: `_StreamReader` (thread/pipe, `read1` 64KB chunk, buffer cap cứng) + supervisor poll 10ms — vượt cap → `_kill_process_group` **giữa chừng** (`truncated=True`, returncode thật vd -9), deadline → `timed_out=True`/returncode None. Contract `RunResult` giữ nguyên. Tests `tests/test_proc_streaming_cap.py` 5 test (flood stdout/stderr/grandchild, exact-cap boundary, small output).
- [x] P1.g `diff-impact` capture `pre_change` snapshot TRƯỚC auto-reconcile + `post_change` SAU analysis (envelope JSON + stderr line cho plain JSON); `WorktreeSnapshot.role` ∈ {query, pre_change, post_change}. Nền cho P7 receipts.

### Test bắt buộc (từ roadmap R1)

- Dirty unstaged/staged edit, untracked caller, rename, delete → không FRESH — `test_unstaged_staged_untracked_all_dirty`, `test_stale_journal_files_detects_edit_and_delete` (delete→stale; rename rơi vào dirty-status của P1.a).
- HEAD giữ nguyên nhưng file content đổi → STALE/UNVERIFIABLE (reproduction blocker #1) — `test_matching_head_dirty_worktree_is_stale` + `test_dirty_unverifiable_state_caps_freshness`.
- Provider HEAD khớp nhưng cited path stale — `test_clean_matching_head_is_fresh` (ngược) + `stale_journal_files` unit; end-to-end `test_explore_carries_snapshot_and_flags_stale`.
- Output vô hạn/oversized bị kill giữa chừng, memory giữ ổn định — `test_proc_streaming_cap.py` (5 test, kill < 10s vs deadline 30s; buffer ≤ cap).
- Snapshot race: file đổi giữa query và verification → abstention — `test_race_between_capture_and_verify_abstains` (SNAPSHOT_RACE).

### Exit gate — receipts 2026-08-27

- [x] Zero `SUPPORTED`/`ASSURED_WITHIN_SCOPE` trên stale/unbound evidence: dirty/stale ⇒ `fresh=False` từ cả 3 lớp (snapshot_match dirty gate, `stale_journal_files`, `SNAPSHOT_RACE` abstain).
- [x] Reproduction blocker #1 chuyển FRESH → STALE/UNVERIFIABLE khi HEAD giữ nguyên + content đổi (`test_matching_head_dirty_worktree_is_stale`, `test_dirty_unverifiable_state_caps_freshness`).
- [x] `test_proc_process_group.py` + streaming-cap xanh ổn định 5/5 runs liên tiếp (4.7-4.9s/run) sau bump grandchild timeout 0.6→2.0s (cùng fix class như P0.a).
- [x] Full suite: **619 passed + 5 skipped, 0 failed** (11 test P1 trust + 5 streaming-cap mới).


## P2 — Shared assurance orchestrator (R2)

### Mục tiêu

Provider orchestration ra khỏi private CLI helpers; CLI và MCP dùng chung một engine.

### Việc

- [x] P2.a Tạo `src/sot_graph/assurance/` package: `orchestrator.py`, `models.py`, `routing.py`, `identity.py`, `normalization.py`, `coverage.py`, `verification.py`, `conflicts.py`, `receipts.py`.
  — Receipt: package tạo với các module THỰC SỰ carry code: `routing.py` (spec parse + capability tables), `orchestrator.py` (plan/query/candidates/conflicts), `engine.py` (resolve_symbol + assured_query_context), `__init__.py` re-export. KHÔNG tạo rỗng identity/normalization/coverage/verification/conflicts/receipts/models — logic tương ứng đang sống ở `providers/normalization.py`, `providers/verification.py`; chúng MOVE vào assurance/ ở phase sở hữu (P4 identity, P5 coverage, P7 receipts) theo đúng nguyên tắc move-không-copy, tránh re-export shell rỗng.
- [x] P2.b Di chuyển (không copy): `_federation_plan` (`cli.py:295-335`), `_run_federated_query` (`cli.py:367`), `_cbm_candidates_from_outcome` (`cli.py:500-580`), `_target_conflicts` (`cli.py:606`) vào orchestrator; CLI chỉ parse args + render.
  — Receipt: cli.py 2746→2032 dòng; 10 private helper bị cắt hẳn (`_resolve_symbol`, `_QUERYABLE_PROVIDERS/_CAPABILITY_ALIASES/_COMMAND_CAPABILITY`, `_parse_provider_spec`, `_supports_capability`, `_federation_plan`, `_run_federated_query`, `_SEARCH_ROW_LINES`+2 parser, `_candidate_entry`, `_snapshot_match_of`, `_cbm_candidates_from_outcome`, `_target_conflicts`, `federated_extras`, `_envelope_fed_kwargs`, `_assured_query_context`, `_stale_files_warning`); signature đổi args→`provider_spec: str|None` để MCP gọi được không cần argparse. CLI giữ `_print_fed_warnings`/`_print_federation_notes` (presentation-only). Test guard: `TestOrchestratorModuleBoundaries` assert không còn private orchestration attribute trong cli.
- [x] P2.c `McpService` gọi orchestrator (thay đọc tĩnh `provider_runs` — `mcp_service.py:168-178`); không gọi private CLI function.
  — Receipt: `McpService.explore/usages/diff_impact` giờ gọi `assurance.assured_query_context` (mark_ledger=False — conn mode=ro chỉ detect, không ghi ledger); `_ConnView` bind `Database.stale_journal_files`/`get_file_journal` unbound. `_providers()` (stats display) vẫn đọc `provider_runs` — đó là hiển thị ledger đã ghi, không phải negotiation; negotiation/sync thật nằm ở `sot providers sync` (P3.1). MCP federation full (truyền provider spec qua tool call) defer sang P3 sau khi adapter structured parse xong — MCP surface hiện là read-only bounded.
- [x] P2.c' Đúng semantics `builtin/auto/prefer:/require:/all`; `providers_mode=auto` trong config có hiệu lực không cần lặp `--provider` (W5/G6.1); `all` thật sự invoke mọi provider queryable hoặc không quảng bá.
  — Receipt: `effective_provider_spec(explicit, providers_mode, allow_external)`: explicit thắng → config auto+allow_external → "auto" → builtin. CLI gọi qua `resolve_federated_spec`. Tests: `TestEffectiveSpec` (explicit wins / config auto applies / auto без allow_external stays builtin). `all` mode: registry-ranked mọi queryable provider; P1 chỉ có 1 queryable (CBM) nên all ≡ auto top-1 — trung thực với tập queryable hiện có, không quảng bá thêm.
- [x] P2.d Route theo capability + language + assurance tier; provider failure là typed outcome, không throw xuyên lớp; builtin giữ tương thích ngược.
  — Receipt: routing table `COMMAND_CAPABILITY` + `CAPABILITY_ALIASES` dùng chung CLI/MCP; provider failure → `QueryOutcome` typed (ok/error/next_action), federated_extras không throw xuyên lớp (fail_message cho require, warnings cho auto/prefer). Builtin compat: `test_default_builtin_never_spawns` (legacy shape không federation keys) vẫn xanh.
- [x] P2.e Canonical candidate model đúng roadmap §5.2 (field thiếu là `null`/`unknown`, không invent).
  — Receipt: `_candidate_entry` dùng `getattr(subj, field, None)` — field thiếu là None, không invent; verdict/resolution luôn str.

### Test bắt buộc

- [x] CLI/MCP parity: cùng request + snapshot → cùng canonical evidence/receipt digest.
  — Receipt: `tests/test_p2_orchestrator.py::TestCliMcpParity::test_explore_assurance_digest_matches` — SHA-256 canonical digest của snapshot descriptor CLI vs MCP bằng nhau; stale files identical.
- [x] `require` fail closed exit code ổn định; `auto/prefer` provider chết không phá builtin.
  — Receipt: `test_require_blocked_by_config_exit_code_is_stable` (exit 2), `TestDeadProviderDegrades` (auto/prefer PATH rỗng → warnings + builtin tiếp tục, candidates rỗng; require → fail_message "failing closed").

### Exit gate

- [x] Không còn orchestration logic trong `cli.py` ngoài parse/render.
- [x] Full suite xanh; hành vi CLI cũ không đổi (backward-compat invariant #9). — 646 passed + 5 skipped, 0 failed; smoke: builtin explore/usages legacy shape, require exit 2.

## P3 — Provider adapters hoàn thiện (R3)

### Mục tiêu

Structured parse thay text report; sync explicit; builtin capability trung thực theo oracle P0.

### P3.1 Codebase Memory (≈ G2 + G6.2)

- [x] `search_graph`: gửi `format=json` qua `--args-file`; parse `cols`/rows/groups/`total`/`offset`/`has_more`; giữ qualified name + span + rank; không đồng nhất short name (thay `codebase_memory.py:832`, `cli.py:394-415`).
  — Receipt: adapter gửi `format=json`; `orchestrator.search_rows_from_payload` cols-by-NAME (yêu cầu `qn`+`file`), giữ full qualified name + span (`_span_from_lines`) + rank; row thiếu col → skip, payload thiếu cols → abstain. `tests/test_p3_adapters.py::TestSearchStructuredParse` (7 test), wire shapes khớp binary thật v0.10.8 (probe 2026-08-27).
- [x] `trace_path`: map `max_depth`→`depth`; `format=json` + `include_evidence=true`; directed edge root→callee / caller→root; giữ direction/hop/strategy/confidence/cursor/total; tách `CALLS`/`CALL_REFERENCE`/`USAGE`; thiếu span → low-resolution, không tự tạo (thay `codebase_memory.py:856-861`, `cli.py:437-440,571-576`).
  — Receipt: adapter gửi `depth`/`format=json`/`include_evidence`; `orchestrator.trace_edges_from_payload` → directed edges `{direction, qualified_name=qn_prefix.name, root, hop, edge_type, strategy, confidence}`; col `edge_type` đi theo khi có, strategy thiếu → None. `TestTraceStructuredParse` (4 test) asserts source/target/direction/hop đúng chiều callees/callers.
- [x] `detect_changes`: `format=json`; map SOT target→`since`/`base_branch` + `depth`; staged/working-tree không hỗ trợ → ghi scope conflict, không merge; parse `changed_files`/seeds/impacted/modules/truncated; `diff_identity` chung trước khi so builtin+CBM (thay `codebase_memory.py:935`, `cli.py:549-550`, `cli.py:383`).
  — Receipt: `ImpactRequest` + `since/depth/staged/working_tree`; adapter gửi `{project, scope:"impact", direction:"inbound", depth, format:"json", since}`; `orchestrator._diff_identity` (`git rev-parse` → `base12..head12`) vào envelope cho mọi diff-impact; staged/working_tree → `federated_extras` trả warnings + known_gaps scope-conflict KHÔNG gọi provider (`TestImpactScoping::test_staged/working_tree_scope_conflicts_not_merges`).
- [x] `architecture()`: expose qua orchestrator (thay `codebase_memory.py:942`); inference thiếu anchor không được source-verified.
  — Receipt: `orchestrator.architecture(provider_spec, root)` passthrough (CBM text-only wire — không `--format` flag trên binary thật v0.10.8); `routing.COMMAND_CAPABILITY["architecture"]`.
- [x] `check_index_coverage`: args-file + explicit project (dùng cho P5).
  — Receipt: `CoverageRequest.project`; `CodebaseMemoryProvider.coverage` yêu cầu explicit project qua args-file, không auto-detect ngầm.
- [x] `sot providers sync codebase-memory`: bọc `index_repository` explicit — có timeout riêng, progress, cancellation, lock (tái dùng WriteLock), receipt; không bắt user chạy CLI CBM tay (thay `codebase_memory.py:804-818`, `cli.py:826-833`).
  — Receipt: `cli.cmd_providers_sync` = `WriteLock(.sot/write.lock)` + `provider.index(IndexRequest, progress)` (timeout riêng `--timeout`, `--progress`, `LockBusy`→exit 1); receipt qua ledger `record_provider_run`; `ensure_index` vẫn abstain mọi implicit path (`test_sync_never_runs_without_explicit_command`); smoke thật trên /tmp/p2dbg rc 0.

### P3.2 SCIP

- [x] Normalize definitions/references vào identity model chung; bind index metadata vào source snapshot; không suy call từ reference đơn thuần; invalidate khi commit/manifest lệch (`importer/scip.py:623-809`).
  — Receipt: src/dst_symbol = qualified identity (`parse_scip_symbol().fqn`, không short-name normalization), bare name đi cột alias `symbol`/`target_symbol` (writer `db.record_provider_evidence` honor cả hai) → `get_symbol_evidence` resolve cả bare lẫn qualified. Occurrence thường luôn `relation='references'` — không có code path nào upgrade thành call (test invariant). Run bind journal: `manifest_digest` = sha256 của sorted (path, sha256) journal rows; doc text/disk lệch journal → `mark_evidence_stale("scip index stale: indexed content differs from file_journal")` ngay trong import; chưa reconcile → `journal_bound=False` (never-indexed ≠ stale). `tests/test_p3_scip_binding.py` (7 test) + `test_scip_enclosing_symbol_attribution` cập nhật sang qualified.

### P3.3 Builtin

- [x] Capability theo từng language×relation (không quảng bá chung), dựa trên scorecard P0.
- [x] Sửa Go/TS recall theo exact oracle; nâng canonical qualified identity Rust/Go/TS methods; regex fallback giữ ở heuristic ceiling.
  — Receipt: baseline oracle regen: **P 99.8 / R 99.2 / F1 99.5** (trước: 99.2/69.4/81.6). Go calls 100/100/100, TS 99.5, Rust 98.5 (trước 4.4), Java/Py giữ. Cơ chế (đều AST-anchored, không đụng regex fallback — PARTIAL_AST vẫn cap 0.45/WEAK ở verifier): (1) `module_form_of_import` — Go slash-package 'go_pkg/storage'→dotted (trước bị prune external), TS relative absolutize theo dir-module; (2) receiver typing TS `const v = new C()`/typed params, Go receiver+value params `r *T` + `r := &T{}`, Rust `let r = T{..}`/unit + `r: &T` → `v.m()` resolve `C.m` TRƯỚC bare-match (module-level same-name không bao giờ thắng — sửa 3 FP same_name_two_scopes); (3) Rust `impl T` container → method canonical `T.save`; (4) TS constructor edge (`new C()`→C), `this.m()`, alias import `{x as y}` retarget. Tests: `tests/test_p3_builtin_recall.py` (12 test) + treesitter rust canonical update + tripwire P0 đổi sang lock fix (go/ts ≥0.99, rust ≥0.95) + residual (rust implements <0.5). Residual 8 FN + 2 FP (python annotation binding, TS closure nested scope, rust `use ... as` alias, `impl Trait for T`, java static import, virtual dispatch dynamic) — từng cái một cơ chế riêng, để lại cho phase sau, có anchor trong confusion list.

### P3.4 Plugin contract
- [x] Entry-point versioned; adapter mới phải qua contract tests (dùng golden capture pattern G1); không sửa orchestrator core; không auto-install trong read query.
  — Receipt: `providers/contract.py` — `PROVIDER_CONTRACT_VERSION=1` + `static_contract_problems` (gate load-time, spawn-free: version match, capabilities shape, advertise-mà-thiếu-method) + `run_contract_checks` (golden capture G1: text-report reply cho `format=json` phải fail-closed `wire_status=schema_drift`; ensure_index trong read context chỉ abstain/no-op; mọi method bounded — failure là data không exception) + `validate_entry_point_provider`. CBM adapter khai báo `contract_version=1`/`name` và pass full golden contract. `providers_registry.discover_plugin_providers()` quét entry-point group `sot_graph.providers` — read-only, không install, không query; plugin hỏng degrade thành status unhealthy không phá detect. Orchestrator core không import plugin machinery (boundary test). `tests/test_p3_plugin_contract.py` (8 test: reference pass, version mismatch fail-closed, advertise-without-method, broken EP degrade, read-only discovery, orchestrator untouched).

### Exit gate
- [x] Không production evidence parser nào phụ thuộc whitespace text report.
  — Receipt: CBM wire toàn JSON (P3.1), text reply → schema_drift fail-closed; SCIP protobuf/JSON có cấu trúc; regex fallback chỉ là extractor fallback (PARTIAL_AST, ceiling 0.45/WEAK) không phải evidence parser.
- [x] Golden tests chạy từ clean clone; schema drift/unknown version/partial payload → abstain.
  — Receipt: mọi fake binary là script Python self-contained sinh runtime (không artifact ngoài repo); `tests/test_cbm_adapter.py::TestSchemaDrift`, `test_p3_adapters.py::TestSearchStructuredParse` (partial/missing cols → abstain), version gate UNKNOWN không bump.
- [x] Trace test chứng minh đúng source/target/direction/hop; builtin+CBM cùng `diff_identity`.
  — Receipt: `TestTraceStructuredParse` (direction callees/callers, hop, root preserved, targets=[root]); `TestImpactScoping::test_diff_identity_pins_commit_pair` (base12..head12 shared envelope field trước khi so sánh).

## P4 — Canonical identity & search accuracy (R4)

- [x] Identity tuple `(repo, normalized path, language, kind, qualified name, span, provider symbol ID?)`; không dedup short name.
  — Receipt: `assurance/identity.py` — `SymbolIdentity` + `identity_key/identity_hash` + adapters `from_subject` (CanonicalSubject)/`from_graph_row` (graph_nodes)/`from_provider_symbol` (namespace id `provider:id` — scip/CBM id không bao giờ cross-join) + `dedup_by_identity` (gộp chỉ khi key trùng, short-name collision sống sót). Path normalize POSIX repo-relative. `tests/test_p4_identity.py` (16 test).
- [x] Alias/import/re-export resolution per language (Python resolver hiện hành là chuẩn tham chiếu); bổ sung TS/JS module resolution, Go package/receiver, Rust module/impl, Java package/type.
  — Receipt: Python `modutil` (chuẩn, `tests/test_import_resolution.py`); P3.3b đã bổ sung: TS relative absolutize theo dir-module + alias import `{x as y}` retarget, Go slash-package → dotted + receiver/value param typing, Rust `impl T` container + `let r = T{}` + `r: &T` params, TS constructor edge + `this.m()`. Locked bởi `tests/test_p3_builtin_recall.py` (12 test) + oracle corpus (Go 100/TS 99.5/Rust 98.5 recall). Java dotted import là native module-form (generic branch).
- [x] Ranking theo exact identity + scope + path proximity + provider evidence + freshness; top-k luôn kèm reason/provenance.
  — Receipt: `cmd_search` sort key mới verdict → exact-identity grade (exact/qualified/prefix/text) → provider-evidence rows (batch 1 query, `db.provider_evidence_counts` — không N+1) → coverage; mỗi row `reasons: [verdict=…, identity grade, freshness, evidence count, scope]`, hiện trên JSON + text (`🧾 Rank:`). Internal keys không leak envelope. `tests/test_p4_ranking.py` (12 test).
- [x] Query parser chống FTS injection + wildcard/path ambiguity.
  — Receipt: MATCH string chỉ gồm quoted prefix phrases (spy-test chứng minh mọi term match `"…"*`); operators `*^"(){}:` NEAR/column-filter không bao giờ thành operator; scope LIKE escape `%`/`_`/`\` với ESCAPE clause (scope `%` match 0 row, không mở rộng). `tests/test_p4_search_safety.py` (20 test, 13 injection vectors).
- [x] Quality gate (release floor, không phải global claim): top-k recall ≥90% (hit@10=1.0, unique hit@5=1.0), direct-call precision ≥95% per Tier-A (py 0.997/java 1.0/ts 0.995/go 1.0/rust 1.0), project-local recall ≥80% (min rust 0.970) — khóa trong `tests/test_p4_quality_gate.py` đọc baseline committed; gate fail loud khi thiếu section. **Pending P6**: false-verified-edge=0 và union-không-giảm-verified-precision cần evidence ledger để đo — không claim trước khi đo được.
## P5 — Coverage & multilingual verification (R5)

- [x] Coverage model path/range/language/relation; trạng thái indexed/parsed/partial/skipped/excluded/stale/unknown; phân biệt `queried` vs coverage thật (S5).
  — Receipt: `assurance/coverage.py` — `repo_coverage(db, root, paths)` đo từ file_journal (schema v8: cột `parser_outcome`/`parser_error` persist qua reconciler) + disk hash/mtime (tolerance ±2s như publication gate); states: INDEXED/PARSED/PARTIAL/SKIPPED/EXCLUDED (node_modules/.venv/vendor/_pb2/.min)/STALE/UNKNOWN; journal abs-path normalize về repo-relative; scope path chưa scan → UNKNOWN honestly. `tests/test_p5_coverage_verification.py` (14 test).
- [x] Propagate parser error ranges + generated/vendor paths; coverage API lỗi → downgrade completeness.
  — Receipt: ParseResult mang `parser_outcome/parser_error` → journal (commit_file_batch); coverage API exception → `basis="unknown"`, `completeness()=None` — không bao giờ fabricate số; generated/vendor paths → state EXCLUDED + gap `generated`.
- [x] Source-span verifier language-aware cho Python, TS/JS, Go, Rust, Java, C/C++ (S6 — bỏ Python-regex cho symbol khác ngôn ngữ); verify declaration span và call-site span riêng.
  — Receipt: `providers/verification.py::verify_subject` DEFINING branch dispatch: Python → real `ast`; grammar có sẵn (TS/TSX/JS/Go/Rust/Java/Kotlin/Swift/PHP/C#/C/C++) → tree-sitter `_tree_sitter_defines` (node name + kind + span khớp); ngôn ngữ không grammar → `NOT_APPLICABLE` + gap "S6" — Python-regex không bao giờ confirm definition ngôn ngữ khác. Declaration vs call-site: `verify_subject` (declaration span, unique-def) tách khỏi `verify_edge` (originating-subject span) như cũ. Tests: python ast ok/mismatch, TS class, Go method `W.Do`, no-grammar abstain.
- [x] Gap taxonomy đầy đủ (dynamic dispatch, reflection, DI, framework routing, macros, fn pointers, generated, cross-repo) — khai báo trong receipt, không cắt qua scope assurance.
  — Receipt: `GAP_TAXONOMY` 11 mã ổn định (thêm parser-partial/parser-failed/unresolved-edge từ đo lường thật: PARTIAL_AST/PARSE_ERROR/pending UNRESOLVED|AMBIGUOUS); gap families hiện trong `coverage_note` mọi search reply.
- [x] Completeness engine: coverage + capability + pagination + gaps, không đếm số kết quả.
  — Receipt: `completeness(report, capability)` — covered_fraction trừ gap penalty THEO capability (symbols/search bỏ behavioural gaps; callgraph/trace/impact chịu dynamic-dispatch/reflection/DI/...); unmeasurable → None. MCP `search` + CLI search rỗng đều gắn `coverage` note (basis/completeness/gaps) — pagination đã có (`_fits_response` cắt theo limits, `returned` field).
- [x] Exit gate: zero-result không thành negative claim khi coverage thiếu; verifier non-Python không phát exact verdict bằng Python-regex (S6 fix verify bằng test).
  — Receipt: `TestZeroResultIsNotNegativeClaim` (CLI in "absence is only claimed within covered scope" + MCP `coverage.basis=measured`); `test_no_grammar_language_abstains_not_confirms` (NOT_APPLICABLE + gap S6).
## P6 — Evidence ledger & conflict (R6)

- [ ] Truyền active `Database` vào provider qua orchestrator (W1 — `cli.py:350,825`, `providers_registry.py:119`); persist run/binding/evidence trên production CLI+MCP path (kích hoạt write sites `codebase_memory.py:518,532`).
- [ ] Commit run + evidence atomically sau parse/verify; lưu version/capability/command digest/duration/status/snapshot.
- [ ] Union theo canonical identity + relation + target + snapshot; giữ provenance support/contradict từng provider; không trộn historic stale run vào active; conflict adjudication ưu tiên current source/compiler, chưa đủ → giữ `CONFLICT`.
- [ ] Purge một run không mất evidence run khác; ledger failure không corrupt builtin graph (sidecar isolation).
- Exit gate: 1 query CLI + 1 query MCP thật tạo ledger rows có snapshot (P0.f test); tái tạo receipt từ ledger không cần log console; không winner-takes-all âm thầm.

## P7 — Impact engine & receipts (R7)

- [ ] Scope receipt trước thay đổi: request identity + resolved target, snapshot ID/digest, source anchors, direct callers/callees, imports/implementations/inheritance, transitive bounded impact, affected files/modules, candidate tests, providers/runs/versions, coverage/exclusions, conflicts/truncation/gaps, assurance status, OMP confirmations còn lại.
- [ ] Diff-impact receipt sau thay đổi: diff identity (base/head/index/worktree), changed files/symbols, added/removed/changed edges, upstream/downstream, invalidated pre-change evidence, tests cần chạy + test receipts, reconcile result + post-change snapshot, remaining gaps, closure decision.
- [ ] Assurance rules theo rủi ro (bảng roadmap §R7.3): local body → `verify`; public API/rename/delete → `audit`; auth/tenant → `audit` + security reviewer; dynamic-heavy → không absence assurance.
- [ ] Receipt JSON có schema version + deterministic digest; pre-change receipt không dùng làm proof post-change.
- Exit gate: public rename bị block khi caller coverage chưa đủ; `0 callers` chỉ xuất hiện trong bounded assured scope; đối chiếu được với ledger P6.

## P8 — OMP integration (R8)

- [ ] MCP input hỗ trợ `assurance`, `provider_policy`, `scope`, `budget`; OMP config chỉ cần SOT MCP.
- [ ] OMP rule bắt buộc scope receipt trước sửa core/public symbol; todo nodes tham chiếu receipt items; stop-time rule chặn đóng khi receipt còn pending.
- [ ] Reviewer đối chiếu diff với pre/post receipts; planner được đọc source anchors + known gaps.
- [ ] Xóa 12 claim "100%" agent-facing (mục 1.2 blocker #11) — thay bằng capability/coverage-scoped wording; đồng thời sửa docs "Schema v5" → thực tế đang chạy.
- Exit gate: E2E fixture `scope receipt → plan → edit → targeted tests → diff-impact receipt → reconcile → reviewer` xanh; provider vắng mặt vẫn hoàn thành workflow builtin-only với assurance hạ trung thực.

## P9 — Hardening & release qualification (R9)

- [ ] Ruff + type checker (mypy/pyright) cho core modules (`assurance/`, `providers/`, `diff_impact.py`, `db.py`); coverage threshold tổng + riêng orchestrator/receipt/snapshot; dependency + secret scan (pip-audit/bandit).
- [ ] Real-provider E2E job tối thiểu Linux (CBM 0.10.8 thật); chaos tests: timeout/crash/partial write/corrupt DB/schema drift/huge output; monorepo benchmark latency p50/p95 + memory + index time; migration/rollback tests ledger schema.
- [ ] Provider lifecycle manifest (roadmap §8.1) + update process 8 bước (§8.2).
- Final gates (roadmap §9): full CI 3.10–3.12 × 3 OS; 100 lifecycle integrity runs; context reduction ≥60%; per-language quality floor P4; stale→SUPPORTED = 0; negative claim không bounded = 0; receipt schema compat tests xanh; 0 absolute-completeness wording.

## 5. CI additions theo phase

| Phase | Thêm job/step |
|---|---|
| P0 | ✅ Job `accuracy-oracle`: selfcheck + full corpus run + guard corpus digest khớp baseline đã commit + upload artifact |
| P1 | Giữ matrix; thêm test streaming cap + dirty lifecycle vào suite thường |
| P2 | Job CLI/MCP parity digest |
| P3 | Golden contract từ clean clone; optional real-CBM job (Linux, non-blocking → blocking từ P9) |
| P4 | Job quality-gate per language (fail khi dưới floor) |
| P5 | Coverage API test thường |
| P6 | Ledger migration test |
| P9 | Ruff + type + coverage threshold + security scan + real-provider blocking |

## 6. Stop conditions (kế thừa roadmap §12, bổ sung)

Dừng phase, báo blocker khi: oracle không phân biệt đúng/sai target; không xác định common snapshot hoặc diff identity; provider thiếu direction/source/target cho relation đang map; coverage không chứng minh scope negative claim; structured output mâu thuẫn golden capture; fix chỉ làm metric xanh bằng cách sửa oracle; provider update làm giảm precision/recall dưới floor; thay đổi đòi hỏi fork/vendor chưa có benchmark + ADR; receipt đạt assured dù truncation/conflict/gap tồn tại; **CI matrix đỏ 2 lần liền cùng nguyên nhân gốc chưa xử lý được**.

## 7. Milestone

| Milestone | Deliverable | Phase |
|---|---|---|
| M1 | Exact oracle + dirty snapshot fix + baseline thật commit | P0+P1 |
| M2 | Shared CLI/MCP assurance orchestrator | P2 |
| M3 | Structured CBM + normalized SCIP/builtin | P3 |
| M4 | Canonical search đạt per-language floor | P4 |
| M5 | Real coverage + multilingual verification | P5 |
| M6 | Snapshot-scoped ledger + conflict engine | P6 |
| M7 | Scope/diff/reconcile receipts | P7 |
| M8 | OMP E2E assurance workflow | P8 |
| M9 | Qualified impact-assurance release | P9 |
