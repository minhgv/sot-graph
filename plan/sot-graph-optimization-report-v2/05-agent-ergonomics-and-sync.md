# 05. Agent Ergonomics & Real-Time Sync

> **Document Status**: Harmonized & Authoritative (Aligned with Final Audit P0 Contracts)  
> **Topic**: Harness Adapters, Real-time Inotify Watcher & Read-Only MCP Protocol  
> **Audited By**: OMP Systems Architect (`gpt-5.6-sol`)

---

## 1. Multi-Harness Auto-Provisioning (`sot setup`)

The `src/sot_graph/adapters/` architecture supports 4 major AI Coding Agent harnesses out of the box:

```bash
# Provision all supported harnesses at once
sot setup --harness all

# Or selectively target a specific environment
sot setup --harness omp
sot setup --harness opencode
sot setup --harness claude
sot setup --harness antigravity
```

### Harness Provisioning Manifest:

| Harness | Configuration Files Created / Patched | Exported Tools / Skills |
| :--- | :--- | :--- |
| **Antigravity CLI (`agy`)** | `.gemini/skills/sot-graph/SKILL.md`<br>`.gemini/settings.json`<br>`.gemini/GEMINI.md` | Skill `sot-graph`, automatic verification gate in prompt rules. |
| **Claude Code (`claude`)** | `.claude/CLAUDE.md`<br>`.mcp.json`<br>`.cursor/mcp.json`<br>`AGENTS.md` | Native MCP Server connection (`sot mcp`), PostToolUse sync hints. |
| **Oh My Pi (`omp`)** | `.omp/extensions/sot-graph.ts`<br>`.omp/skills/sot-graph/SKILL.md`<br>`.omp/RULES.md` | 4 Native Tools: `sot_search`, `sot_explore`, `sot_reconcile`, `sot_insert`. |
| **OpenCode (`opencode`)** | `.opencode/skills/sot-graph/SKILL.md`<br>`.opencode/opencode.json` | Plugin tools with JSON stdio interface. |

---

## 2. Real-Time Inotify / Watchdog Daemon (`sot watch`)

### Current On-Demand Limitation
Currently, `sot reconcile` must be invoked manually or via CLI hooks. In long-running autonomous sessions, intermediate file writes can cause minor temporal drift before the next explicit sync.

### Hardened Architecture: Bounded Reactive Watcher

> ⚠️ **Nhất thể hóa (theo File 06 - Final Deep Audit)**: Cơ chế `sot watch` bắt buộc phải sử dụng chung lockfile `.sot/write.lock` với các tiến trình CLI khác và áp dụng **Debounced Event Folding (200ms)** để chống bão sự kiện (event storms).
>
> **Điều chỉnh sau verification**: giữ tinh thần zero-dependency của core — `watchfiles` đặt trong **optional dependency group `[watch]`** (`pip install sot-graph[watch]`); khi không có, watcher dùng **stdlib polling fallback** (quét mtime theo chu kỳ). Cả hai backend cùng đi qua publication gate CAS.

```python
# src/sot_graph/watcher.py — backend: watchfiles nếu import được, polling fallback nếu không
def run_watch_daemon(reconciler: Reconciler, root: str, debounce_ms: int = 200,
                     backend: str = "auto"):
    """
    Reactive watcher daemon (watchfiles/inotify/kqueue hoặc polling).
    Folds multiple rapid save events into a single 2-Phase CAS commit.
    """
    ...

* **Event Folding**: If a build tool or linter edits 50 files in 50ms, the watcher batches them into a single SQLite transaction.
* **Lock Coordination**: The watcher acquires `.sot/write.lock` with a short timeout; if a heavy CLI migration holds the lock, the watcher backs off gracefully without crashing.

---

## 3. Read-Only MCP Protocol Defense

The `src/sot_graph/mcp_server.py` implementation enforces strict read-only constraints:
- **Zero Mutation Surface**: No write, clean, or delete tools exposed via MCP.
- **Bounded Payloads**: 256KB hard cap prevents downstream MCP client buffer overflow.
- **Timeout Isolation**: 2,000ms deadline per query ensures subagent loops never hang indefinitely on locked tables.
- **Path Confinement**: All query parameters are strictly confined to the project root directory.
