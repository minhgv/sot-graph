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

- [ ] P1.a Wire dirty state vào external snapshot match: `codebase_memory.py:829-843` — khi `is_dirty()` (dùng sẵn `snapshot.py` dirty fingerprint), freshness tối đa là `STALE`/`UNVERIFIABLE` kể cả khi `head_sha` khớp; khi `paths=()` vẫn phải check dirty.
- [ ] P1.b Snapshot chung trước mọi assured query: HEAD SHA + dirty flag + content-based dirty fingerprint + manifest digest + graph generation + snapshot ID (tái dùng `snapshots` table hiện có); gắn snapshot ID vào builtin và external runs.
- [ ] P1.c Builtin path: `explore`/`usages`/`diff-impact` check journal hash/mtime của cited files trước khi trả kết quả (mở rộng JIT micro-reconcile hiện có của `search`).
- [ ] P1.d TOCTOU guard trong `verify_subject` (`providers/verification.py:146-150`): capture (hash, mtime) khi query, so lại khi verify; lệch → abstain "snapshot race", không phát verdict mạnh.
- [ ] P1.e Invalidation: edit/rename/delete làm invalidate evidence liên quan đến file đó (đánh dấu, không xóa — phục vụ P6 ledger phân biệt pre/post-change snapshot).
- [ ] P1.f Streaming hard cap trong `proc.py`: reader drain 2 pipe theo chunk với byte cap; vượt cap → kill process group ngay (tái dùng `_kill_process_group` `proc.py:55-63`); giữ contract `RunResult` + `truncated=True`.
- [ ] P1.g Phân biệt pre-change và post-change snapshot ID trong mọi receipt (nền cho P7).

### Test bắt buộc (từ roadmap R1)

- Dirty unstaged/staged edit, untracked caller, rename, delete → không FRESH.
- HEAD giữ nguyên nhưng file content đổi → STALE/UNVERIFIABLE (reproduction blocker #1 hiện tại).
- Provider HEAD khớp nhưng cited path stale.
- Output vô hạn/oversized bị kill giữa chừng, memory giữ ổn định.
- Snapshot race: file đổi giữa query và verification → abstention.

### Exit gate

- Zero `SUPPORTED`/`ASSURED_WITHIN_SCOPE` trên stale/unbound evidence (test rà toàn bộ verdict path).
- Reproduction blocker #1 chuyển FRESH → STALE/UNVERIFIABLE.
- `test_proc_process_group.py` xanh ổn định ≥5 lần chạy liên tiếp.

## P2 — Shared assurance orchestrator (R2)

### Mục tiêu

Provider orchestration ra khỏi private CLI helpers; CLI và MCP dùng chung một engine.

### Việc

- [ ] P2.a Tạo `src/sot_graph/assurance/` package: `orchestrator.py`, `models.py`, `routing.py`, `identity.py`, `normalization.py`, `coverage.py`, `verification.py`, `conflicts.py`, `receipts.py`.
- [ ] P2.b Di chuyển (không copy): `_federation_plan` (`cli.py:295-335`), `_run_federated_query` (`cli.py:367`), `_cbm_candidates_from_outcome` (`cli.py:500-580`), `_target_conflicts` (`cli.py:606`) vào orchestrator; CLI chỉ parse args + render.
- [ ] P2.c `McpService` gọi orchestrator (thay đọc tĩnh `provider_runs` — `mcp_service.py:168-178`); không gọi private CLI function.
- [ ] P2.c' Đúng semantics `builtin/auto/prefer:/require:/all`; `providers_mode=auto` trong config có hiệu lực không cần lặp `--provider` (W5/G6.1); `all` thật sự invoke mọi provider queryable hoặc không quảng bá.
- [ ] P2.d Route theo capability + language + assurance tier; provider failure là typed outcome, không throw xuyên lớp; builtin giữ tương thích ngược.
- [ ] P2.e Canonical candidate model đúng roadmap §5.2 (field thiếu là `null`/`unknown`, không invent).

### Test bắt buộc

- CLI/MCP parity: cùng request + snapshot → cùng canonical evidence/receipt digest.
- `require` fail closed exit code ổn định; `auto/prefer` provider chết không phá builtin.

### Exit gate

- Không còn orchestration logic trong `cli.py` ngoài parse/render.
- Full suite xanh; hành vi CLI cũ không đổi (backward-compat invariant #9).

## P3 — Provider adapters hoàn thiện (R3)

### Mục tiêu

Structured parse thay text report; sync explicit; builtin capability trung thực theo oracle P0.

### P3.1 Codebase Memory (≈ G2 + G6.2)

- [ ] `search_graph`: gửi `format=json` qua `--args-file`; parse `cols`/rows/groups/`total`/`offset`/`has_more`; giữ qualified name + span + rank; không đồng nhất short name (thay `codebase_memory.py:832`, `cli.py:394-415`).
- [ ] `trace_path`: map `max_depth`→`depth`; `format=json` + `include_evidence=true`; directed edge root→callee / caller→root; giữ direction/hop/strategy/confidence/cursor/total; tách `CALLS`/`CALL_REFERENCE`/`USAGE`; thiếu span → low-resolution, không tự tạo (thay `codebase_memory.py:856-861`, `cli.py:437-440,571-576`).
- [ ] `detect_changes`: `format=json`; map SOT target→`since`/`base_branch` + `depth`; staged/working-tree không hỗ trợ → ghi scope conflict, không merge; parse `changed_files`/seeds/impacted/modules/truncated; `diff_identity` chung trước khi so builtin+CBM (thay `codebase_memory.py:935`, `cli.py:549-550`, `cli.py:383`).
- [ ] `architecture()`: expose qua orchestrator (thay `codebase_memory.py:942`); inference thiếu anchor không được source-verified.
- [ ] `check_index_coverage`: args-file + explicit project (dùng cho P5).
- [ ] `sot providers sync codebase-memory`: bọc `index_repository` explicit — có timeout riêng, progress, cancellation, lock (tái dùng WriteLock), receipt; không bắt user chạy CLI CBM tay (thay `codebase_memory.py:804-818`, `cli.py:826-833`).

### P3.2 SCIP

- [ ] Normalize definitions/references vào identity model chung; bind index metadata vào source snapshot; không suy call từ reference đơn thuần; invalidate khi commit/manifest lệch (`importer/scip.py:623-809`).

### P3.3 Builtin

- [ ] Capability theo từng language×relation (không quảng bá chung), dựa trên scorecard P0.
- [ ] Sửa Go/TS recall theo exact oracle; nâng canonical qualified identity Rust/Go/TS methods; regex fallback giữ ở heuristic ceiling.

### P3.4 Plugin contract

- [ ] Entry-point versioned; adapter mới phải qua contract tests (dùng golden capture pattern G1); không sửa orchestrator core; không auto-install trong read query.

### Exit gate

- Không production evidence parser nào phụ thuộc whitespace text report.
- Golden tests chạy từ clean clone; schema drift/unknown version/partial payload → abstain.
- Trace test chứng minh đúng source/target/direction/hop; builtin+CBM cùng `diff_identity`.

## P4 — Canonical identity & search accuracy (R4)

- [ ] Identity tuple `(repo, normalized path, language, kind, qualified name, span, provider symbol ID?)`; không dedup short name.
- [ ] Alias/import/re-export resolution per language (Python resolver hiện hành là chuẩn tham chiếu); bổ sung TS/JS module resolution, Go package/receiver, Rust module/impl, Java package/type.
- [ ] Ranking theo exact identity + scope + path proximity + provider evidence + freshness; top-k luôn kèm reason/provenance.
- [ ] Query parser chống FTS injection + wildcard/path ambiguity.
- Quality gate (release floor, không phải global claim): top-k recall ≥90%, confirmed direct-call precision ≥95%, project-local recall ≥80% — **per Tier-A language**, false verified edge = 0 trên adversarial corpus (P0), provider union không giảm verified precision.

## P5 — Coverage & multilingual verification (R5)

- [ ] Coverage model path/range/language/relation; trạng thái indexed/parsed/partial/skipped/excluded/stale/unknown; phân biệt `queried` vs coverage thật (S5 — `cli.py:703,717`).
- [ ] Propagate parser error ranges + generated/vendor paths; coverage API lỗi → downgrade completeness.
- [ ] Source-span verifier language-aware cho Python, TS/JS, Go, Rust, Java, C/C++ (S6 — bỏ Python-regex cho symbol khác ngôn ngữ); verify declaration span và call-site span riêng.
- [ ] Gap taxonomy đầy đủ (dynamic dispatch, reflection, DI, framework routing, macros, fn pointers, generated, cross-repo) — khai báo trong receipt, không cắt qua scope assurance.
- [ ] Completeness engine: coverage + capability + pagination + gaps, không đếm số kết quả.
- Exit gate: zero-result không thành negative claim khi coverage thiếu; verifier non-Python không phát exact verdict bằng Python-regex (S6 fix verify bằng test).

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
