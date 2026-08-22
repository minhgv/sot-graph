# 03. AST Extraction & Graph Algorithms Optimization

> **Document Status**: Harmonized & Authoritative (Aligned with Final Audit P0 Contracts)  
> **Topic**: Deterministic Clustering, High-Fidelity AST Spans & Memory-Safe Parsers  
> **Audited By**: OMP Systems Architect (`gpt-5.6-sol`)

---

## 1. Deterministic Community Detection (Seed=42 & Sorted Traversal)

### ✅ TRẠNG THÁI: ĐÃ CÀI ĐẶT SẴN TRONG CODE (verified 2026-08-22)

**Bản report v2 gốc mô tả đây là defect — không còn chính xác.** Kiểm tra trực tiếp cho thấy `src/sot_graph/analytics/graph.py:300-338` (_label_propagation_community) đã triển khai đúng bản "Hardened": `seed: int = 42`, `rng = random.Random(seed)`, `rng.shuffle(nodes_list)`, tie-breaking bằng `sorted(best_labels)[0]`, output sorted theo `(-len, min)`; thậm chí NetworkX Louvain cũng gọi với `seed=42` (line 291).

**Việc còn lại duy nhất**: thêm regression test khóa tính deterministic (chạy cluster 2 lần trên cùng graph → output byte-identical) để chống regress trong tương lai. Không cần sửa algorithm.

```python
# Tham chiếu: code hiện tại (graph.py:300-338) đã có sẵn — KHÔNG cần implement lại
def _label_propagation_community(self, seed: int = 42, max_iterations: int = 30):
    import random
    rng = random.Random(seed)   # ✅ đã có
    ...
    new_label = sorted(best_labels)[0]   # ✅ deterministic tie-breaking đã có
```

---

## 2. High-Fidelity AST Schema Extension — ⬆️ THĂNG HẠNG P0 (điều kiện tiên quyết cho `sot pack`)

### Schema Limitations Identified in Audit (verified)
The v1 `graph_nodes` table only recorded `line_start` and a generic `label` (`db.py:23-27`). It lacked exact character spans, end lines, and fully qualified names (FQNs), making it impossible to slice exact function bodies without re-reading the entire file. **Không có schema v2 thì ContextBundle (Phase 3) không thể triển khai trung thực.**

### Hardened `graph_nodes` Schema (v2):

```sql
CREATE TABLE IF NOT EXISTS graph_nodes (
    id            TEXT PRIMARY KEY,       -- Namespaced ID: 'sym:<path_hash>:<symbol_id>'
    path          TEXT NOT NULL,          -- Project-relative file path
    kind          TEXT NOT NULL,          -- 'file' | 'class' | 'function' | 'method' | 'interface'
    symbol        TEXT NOT NULL,          -- Raw short name
    fqn           TEXT NOT NULL,          -- Fully Qualified Name (e.g. 'sot_graph.db.Database.commit_file')
    label         TEXT NOT NULL,          -- Formatted display label
    body          TEXT NOT NULL,          -- Short docstring / signature preview
    keywords      TEXT,                   -- Space-separated keywords for FTS5
    start_line    INTEGER NOT NULL,
    start_column  INTEGER NOT NULL,
    end_line      INTEGER NOT NULL,
    end_column    INTEGER NOT NULL,
    signature     TEXT,                   -- Structured signature contract: '(self, path: str) -> bool'
    updated_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_path ON graph_nodes(path);
CREATE INDEX IF NOT EXISTS idx_nodes_fqn ON graph_nodes(fqn);
CREATE INDEX IF NOT EXISTS idx_nodes_symbol ON graph_nodes(symbol);
```

---

## 3. In-Memory AST Extraction LRU Cache — [HẠ ƯU TIÊN: giá trị thấp hơn claim ban đầu]

**Điều chỉnh sau verification**: reconciler **đã skip unchanged files** bằng so sánh SHA-256 journal (`reconciler.py:272-281`) trước khi parse — nên LRU không tiết kiệm cho reconcile flow chính. Lợi ích thực tế chỉ nằm ở parse lặp trong cùng process (MCP session dài, watcher). Chỉ implement nếu benchmark cho thấy cần.

### Thiết kế (nếu triển khai):
```python
import functools

@functools.lru_cache(maxsize=1024)
def _cached_parse_ast(content_sha256: str, file_path: str, language: str) -> Dict[str, Any]:
    """
    Pure-function AST extraction.
    Cache key relies strictly on (content_sha256, file_path, language).
    If file content changes, SHA-256 changes -> automatic cache invalidation.
    """
    ...
```

---

## 4. Multilingual & Unicode Tokenizer for FTS5

Configure SQLite FTS5 table with the Unicode61 tokenizer to properly index Vietnamese accents, CJK characters, and code symbols (`::`, `->`, `$`):

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS graph_fts USING fts5(
    label,
    fqn,
    body,
    keywords,
    content='graph_nodes',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 0 tokenchars "_-.:$@"'
);
```
