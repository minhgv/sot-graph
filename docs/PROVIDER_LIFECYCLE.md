# Provider Lifecycle (roadmap §8.1 / §8.2)

Mọi evidence provider đều có **lifecycle manifest** sống — sinh trực tiếp từ registry probe (`sot providers lifecycle`), không bao giờ hand-maintained — khai báo: health, version, capability, contract version của adapter, tình trạng tương thích wire, chính sách upgrade/rollback.

## §8.1 Manifest

```bash
sot providers lifecycle --format json
```

Mỗi entry:

| Trường | Ý nghĩa |
| :--- | :--- |
| `name` / `mode` | tên provider + kiểu tích hợp (embedded / import / cli / mcp) |
| `installed` / `healthy` | kết quả probe read-only hiện tại |
| `version` | version thật của binary/package |
| `capabilities` | capability đã khai báo (symbols, callgraph, impact, …) |
| `adapter_contract_version` | version của plugin contract adapter này build theo |
| `wire_compatible` | phiên bản wire nằm trong range adapter đã verify; `false` → adapter ABSTAIN, không đoán |
| `upgrade` / `rollback` |policy tham chiếu quy trình dưới |

Bất biến:

- Manifest là **read-only**: chỉ probe, không index, không mạng.
- `wire_compatible=false` không bao giờ chặn builtin path; federation đơn giản abstain và receipt ghi rõ.
- Ledger append-only: evidence của version cũ vẫn audit được sau upgrade.

## §8.2 Quy trình update 8 bước

1. **Freeze evidence** — chuyển `provider_policy` sang `builtin_only` cho query mới; ledger giữ nguyên rows cũ.
2. **Record pre-state** — `sot providers detect --format json > pre.json`.
3. **Upgrade binary** — cài version mới ngoài sot-graph; không có auto-update.
4. **Re-probe** — `sot providers detect`: installed + healthy + version mới.
5. **Contract check** — adapter so version với `contract_version`; lệch → abstain.
6. **Shadow one query** — chạy đúng MỘT federated query qua CLI; soát `schema_drift`/`abstain` trước khi mở rộng.
7. **Re-index explicitly** — `sot providers sync --provider <name>` dưới write lock; ledger ghi run + snapshot binding.
8. **Restore policy + audit ledger** — bật lại policy; `receipt_from_ledger` để audit runs/evidence và xử conflict.

**Rollback** = lặp bước 4–7 với version cũ (ledger append-only giữ evidence pre-upgrade; `purge_provider_run` là đường xóa duy nhất).

Quy trình này cũng là hằng số trong code (`sot_graph.providers.lifecycle.UPDATE_PROCESS`) để CI đối chiếu tài liệu không lệch.
