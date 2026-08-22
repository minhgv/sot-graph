# 01. Executive Summary & Strategic Evolution Roadmap

> **Document Status**: Harmonized & Authoritative (Aligned with Final Audit P0 Contracts)  
> **Target System**: SOT-Graph (`https://github.com/minhgv/sot-graph`)  
> **Author**: Hermes Agent & Deli Deep Research Protocol  
> **Audited By**: OMP Systems Architect (`gpt-5.6-sol`)

---

## 1. Executive Overview

`sot-graph` establishes a verified, self-healing knowledge layer for AI coding agents based on the architectural principle: **"The Filesystem is the Single Source of Truth — The Knowledge Graph is an Authoritative Projection."**

Traditional agentic memory systems and vector RAG pipelines suffer from fatal failure modes: **Phantom Anchors, Stale Context, and Dead Path Hallucinations**. When an agent deletes, moves, or refactors a file, traditional indexes continue serving outdated paths. The agent acts on hallucinated lines of code, burns prompt quota, and generates corrupted patches.

`sot-graph` eliminates this problem by verifying every query candidate against physical disk reality before presenting it to the agent, providing deterministic **Trust Verdicts** (`[STRONG]`, `[WEAK]`, `[REBUILT]`, `[REMOVED]`, `[NOPATH]`).

Following 4 iterations of deep autonomous research and a rigorous architectural audit by `gpt-5.6-sol`, this document suite synthesizes all discovered bottlenecks and establishes a hardened 4-phase production roadmap.

---

## 2. Core Architectural Gaps & Audit Refinements

```
┌────────────────────────────────────────────────────────────────────────┐
│                   SOT-GRAPH ARCHITECTURAL EVOLUTION                    │
└────────────────────────────────────────────────────────────────────────┘
  1. CONCURRENCY:     2-Phase Publication with Generation CAS + Cross-platform FileLock.
  2. STORAGE:         Binding-Aware Resolver eliminating 34:1 Pending Edges Bloat.
  3. MEMORY SAFETY:   Writer/Reader Connection Profiles preventing 3.2GB VPS OOM.
  4. ALGORITHMS:      Deterministic Community Detection (Seed=42) + AST LRU Cache.
  5. AGENT INTERFACE: Versioned ContextBundle (1-hop full + 2-hop Folded Signature Stubs).
```

### Key Refinements from the Deep Reasoning Audit:
1. **No Naive String Pruning**: Functions named `get`, `execute`, `join` must **never** be pruned by string matching alone; the resolver must check lexical scope, caller FQN, and receiver expressions to prevent deleting custom calls like `requests.get()` or `db.execute()`.
2. **CAS Concurrency over POSIX-only Locks**: `fcntl.flock` alone cannot prevent logical stale writes. SOT-Graph requires a single stable lockfile (`.sot/write.lock`) combined with a **Compare-And-Swap (CAS)** generation check upon commit.
3. **VPS Memory Safety**: Dedicated connection profiles (8MB Writer, 4MB Reader) ensure 50 concurrent agents consume $\le 200\text{MB}$ RAM instead of blowing past 3.2GB on constrained 4GB VPS environments.
4. **Untrusted Data Isolation**: All code snippets delivered to LLM prompt registers are flagged `content_is_untrusted: true` to immunize downstream subagents against prompt injection attacks embedded in source comments.

---

## 3. Four-Phase Strategic Upgrade Roadmap (v2.1 — Verified Edition)

```
  Phase 1: Zero-Bloat Resolution & Memory-Safe Concurrency (Weeks 1-2)
  ├── Implement Binding-Aware Builtin Resolver (FQN + Call Kind + Receiver).
  │   └── Tiered fidelity: Python full AST binding analysis; regex-languages heuristic (no pruning).
  ├── Deploy Cross-Platform `.sot/write.lock` (fcntl/msvcrt, stdlib-only) + 2-Phase Publication
  │   └── Per-path CAS trên cột `generation` SẴN CÓ trong file_journal (db.py:21,244) — không cần global counter.
  └── Enforce Connection Profiles (Writer 8MB / Reader 4MB) — preventive hardening.
      └── LƯU Ý: code hiện tại KHÔNG set cache_size 64MB (Defect 3 không áp dụng cho bản shipped).

  Phase 2: Storage Schema v2 & Determinism Lock (Weeks 3-4)  [thu hẹp so với bản đầu]
  ├── graph_nodes v2: fqn, signature, line_end, col_start, col_end → ĐIỀU KIỆN TIÊN QUYẾT cho Phase 3.
  ├── Multilingual FTS5 Tokenizer (`unicode61 remove_diacritics 0 tokenchars "_-.:$@"`) + index cột fqn.
  ├── Migration: index là disposable → bump user_version + auto full re-reconcile (không cần migration phức tạp).
  ├── Regression test lock cho deterministic Label Propagation (seed=42) — ĐÃ CÀI ĐẶT SẴN tại graph.py:300-338.
  └── [Hạ ưu tiên] AST LRU cache — reconciler đã skip unchanged files qua SHA-256 journal.

  Phase 3: ContextBundle Protocol & Subgraph Packaging (Weeks 5-6)
  ├── Implement `sot pack <target_symbol>` command for AI Agent Prompt Registers.
  ├── 1-hop full contract (direct callers/callees) + 2-hop folded interface stubs.
  ├── Standardize `ContextBundle.yaml` schema with `content_is_untrusted: true` security gate.
  └── Zero-dependency: YAML emitter tự viết cho schema cố định (không thêm PyYAML).

  Phase 4: Real-Time Sync & Enterprise Ergonomics (Weeks 7-8)
  ├── Background `sot watch` daemon: `watchfiles` qua optional group `[watch]`, stdlib polling fallback.
  ├── Seamless integration with `.sot/write.lock` to prevent lock contention.
  └── Multi-repo federated graph projection for large enterprise monorepos.
```

---

## 4. Traceability & Impact Matrix

| Subsystem | Root Problem (verified) | Hardened Solution | Expected Impact |
| :--- | :--- | :--- | :--- |
| **Pending Edges** | 2,206 pending records trên 39 paths do builtins/external calls (verified trong `.sot/sot.db`). | Binding-Aware Resolver: prune unshadowed bare builtins + external imports; giữ attribute calls với context. | Giảm mạnh (BUILTIN+EXTERNAL classes); **đo thực tế sau implement** — attribute calls với receiver unknown được GIỮ lại (audit-compliant) nên không cam kết 92%. |
| **Concurrency** | Không có lock; commit không re-verify disk hash (verified). | Stable `.sot/write.lock` + 2-Phase Publication với per-path generation CAS. | 100% elimination of stale overwrites; deterministic `CONFLICT` on drift. |
| **Memory / VPS** | *(Preventive — code shipped không có 64MB cache)* | Bounded Connection Profiles: 8MB Writer, 4MB Reader. | RAM predictably bounded khi scale số connection. |
| **Context Packaging** | 40k+ tokens dumped vào agent context; schema thiếu FQN/spans (verified). | $k$-hop Folded Signature Stubs Protocol (`ContextBundle`). | Hypothesis: tiết kiệm token lớn — benchmark qua `benchmarks/` sau implement. |
| **Community Detection** | ~~Random dict ordering~~ **ĐÃ FIXED sẵn trong code** (graph.py:300-338, seed=42, sorted ties). | Regression test lock tính deterministic. | 100% reproducible architecture reports (cần test để không regress). |
