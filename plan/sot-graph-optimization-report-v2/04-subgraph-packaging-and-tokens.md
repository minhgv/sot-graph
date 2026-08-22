# 04. Agent Subgraph Packaging & Token Economics

> **Document Status**: Harmonized & Authoritative (Aligned with Final Audit P0 Contracts)  
> **Topic**: $k$-Hop Folded Signature Stubs Protocol, Prompt Injection Defense & Token ROI  
> **Audited By**: OMP Systems Architect (`gpt-5.6-sol`)

---

## 1. The Context Explosion Challenge

When AI Coding Agents (such as OMP, OpenCode, or Claude Code) refactor code, dumping full files or entire AST graphs into prompt contexts introduces 3 fatal failure modes:
1. **Context Window Blowout**: Exceeding 40k+ prompt tokens per step.
2. **Attention Dilution (Lost-in-the-Middle)**: Models lose track of the core function contract amid thousands of lines of unrelated helper code.
3. **Severe Cost / Quota Drainage**: Rapidly depleting rate-limited quota pools (e.g. Z.AI Legacy V2 or Claude Opus budgets).

---

## 2. The $k$-Hop Folded Signature Stubs Protocol (`ContextBundle`)

> ⚠️ **Nhất thể hóa (theo File 06 - Final Deep Audit)**: Bắt buộc tuân thủ nguyên tắc cách ly dữ liệu không tin cậy (`content_is_untrusted: true`), sử dụng giới hạn cứng byte/node (Hard Caps), và cơ chế gắn nhãn `AMBIGUOUS_TARGET` khi có nhiều ứng viên trùng tên.

```
       Global SOT-Graph Codebase                Hardened ContextBundle Artifact
┌──────────────────────────────────────┐        ┌────────────────────────────────────┐
│ [Node A] ──> [Target Function]       │        │ Target Function (Level 0)          │
│    │               │                 │ Slicing│  ├── Full AST Source Body          │
│    v               v                 │───────>│  ├── Exact Char Span [L45:1-L89:22]│
│ [Node C] ──> [Direct Callee B]       │        │ 1-Hop Neighbors (Level 1)          │
│    │                                 │        │  ├── Inbound Caller Contracts      │
│    v (k-hop bloat)                   │        │  └── Outbound Callee Signatures    │
│ [Transitive Node D]                  │        │ 2-Hop Transitive Stubs (Level >=2) │
│                                      │        │  └── Folded Single-Line Interfaces │
└──────────────────────────────────────┘        └────────────────────────────────────┘
```

### Hardened `ContextBundle.yaml` Standard Schema (v2):

```yaml
schema_version: "2.0.0"
bundle_id: "bundle:a7f920c4e18b"
base_generation: 48
generated_at: 1787386000

# Security Gate: Prevents downstream LLM from interpreting source comments as instructions
content_is_untrusted: true

target:
  node_id: "sym:0029c560e905:PaymentService.process_order"
  fqn: "sot_graph.services.payment.PaymentService.process_order"
  relative_path: "src/services/payment.py"
  language: "python"
  trust_verdict: "STRONG"
  indexed_sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  span:
    start_line: 45
    start_column: 5
    end_line: 89
    end_column: 22
  full_source: |
    def process_order(self, order_id: str, amount: int) -> bool:
        """Process order through active payment gateways."""
        conn = self.db.acquire_connection()
        return self.gateway.charge(amount, token=order_id)

inbound_callers: # 1-Hop Inbound
  - node_id: "sym:11a0bc39e120:CheckoutController.submit"
    fqn: "sot_graph.controllers.checkout.CheckoutController.submit"
    relative_path: "src/controllers/checkout.py"
    callsite_line: 112
    contract: "def submit(self, req: Request) -> HttpResponse"

outbound_callees: # 1-Hop Outbound
  - node_id: "sym:44ef8910a221:DatabasePool.acquire_connection"
    fqn: "sot_graph.db.pool.DatabasePool.acquire_connection"
    relative_path: "src/db/pool.py"
    signature: "def acquire_connection(self) -> Connection"
  - node_id: "sym:88cc1290bb34:StripeGateway.charge"
    fqn: "sot_graph.gateways.stripe.StripeGateway.charge"
    relative_path: "src/gateways/stripe.py"
    signature: "def charge(self, amount: int, token: str) -> ChargeResult"

transitive_stubs: # Level >= 2 Folded Interfaces
  - fqn: "sot_graph.gateways.base.BaseGateway.verify_credentials"
    signature: "def verify_credentials(self) -> bool"

limits:
  max_hops: 2
  max_nodes: 50
  max_bytes: 65536
  discovered_nodes: 18
  returned_nodes: 18
  truncated: false
  warnings: []
```

---

## 3. Security Defense & Prompt Injection Immunity

1. **Untrusted Data Isolation**: Source code, docstrings, and comments are treated as **pure data payload**, never concatenated into system instructions.
2. **Strict Root Containment**: SOT-Graph ignores paths outside the project root (`..`) or matching `.gitignore` / `.env` credentials during graph slicing.
3. **Hard Byte Caps**: If a target function exceeds 64KB, SOT-Graph fails closed with `TARGET_TOO_LARGE` or emits an explicit partial bundle with `complete: false` rather than silently truncating code.

---

## 4. Quantified Token Economy & ROI Analysis — ⚠️ HYPOTHESIS (chưa verify)

> **Điều chỉnh sau verification**: bảng dưới đây từ "empirical benchmarks on 100 typical agentic refactoring tasks" **không kèm methodology** — coi là hypothesis cần benchmark qua `benchmarks/` sau khi ContextBundle shipped. Các con số giữ lại làm mục tiêu thiết kế (design targets), không phải kết quả đo.

Design targets trên 100 agentic refactoring tasks điển hình:

| Metric | Traditional Agent (Raw Grep/Cat) | SOT-Graph v2 (ContextBundle) | Net Improvement |
| :--- | :---: | :---: | :---: |
| **Average Prompt Tokens / Turn** | 48,500 tokens | 12,900 tokens | **-73.4% Tokens** |
| **Dead Path / File Not Found Errors** | 18% of tool turns | 0% (Trust Verdict Gate) | **100% Eliminated** |
| **Refactor Completion Speed** | 8.4 iterations | 2.6 iterations | **3.2x Faster** |
| **Estimated Cost per 100 Tasks** | $38.50 | $9.80 | **74.5% Cost Reduction** |
| **Context Window Drift / Hallucination** | 24% of sessions | < 1% of sessions | **Near-Zero Hallucination** |
