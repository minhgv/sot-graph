# cbm_sample_repo

Small Python fixture repo with **hand-verified ground truth** used to capture
golden outputs from the `codebase-memory-mcp` CLI binary (see
`tests/fixtures/cbm_golden/`).

## Ground truth scenarios

| Scenario | Location | Expectation |
|---|---|---|
| Direct call | `app/main.py::build_invoice` → `core/service.py::compute_total` | Edge MUST be reported |
| Same-name symbol | `format_label` in `core/service.py` AND `core/labels.py` | Indexer must keep both definitions distinct |
| Alias import | `app/main.py` imports `core.labels.format_label as code_label`; call via alias in `build_code_label` | Edge resolves through the alias to `core/labels.py::format_label` |
| Dynamic / reflection gap | `app/main.py::dispatch` uses `getattr(service, handler_name)` | Static edge to `getattr` target is NOT resolvable; must not fabricate a direct-call edge |
| Generated / excluded file | `generated/models_pb2.py` | Typically excluded by indexer ignore rules; absence of its symbols in results is acceptable |
| Caller outside target dirs | `scripts/run_report.py::run_report` → `core/service.py::compute_total` | Cross-directory caller attribution |

## Usage (golden capture)

```sh
codebase-memory-mcp cli --json index_repository --repo_path <abs-path-to-this-dir>
codebase-memory-mcp cli --json search_graph --project <slug> --query "compute_total"
```

Golden responses are captured verbatim into `tests/fixtures/cbm_golden/`.
The CBM database itself is NOT committed to this repository.
