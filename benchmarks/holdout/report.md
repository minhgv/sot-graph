# SG-204 holdout benchmark report

- repos measured: **11** (pinned, licenses declared)
- presence precision (macro / min): **1.0** / 1.0
- false absence total: **0**
- impact recall (macro, supported static scope): **0.9609**
- test-selection recall (macro, 10 repos): **1.0**
- retrieval Hit@1 / Hit@5 / MRR (reported, not gated): 0.7879 / 0.9515 / 0.8555
- abstention accuracy: 1.0

| repo | presence | false-abs | impact | test-sel |
|---|---|---|---|---|
| itsdangerous | 1.0 | 0 | 1.0 | 1.0 |
| click | 1.0 | 0 | 0.992 | 1.0 |
| structlog | 1.0 | 0 | 1.0 | 1.0 |
| tenacity | 1.0 | 0 | 0.88 | 1.0 |
| python-slugify | 1.0 | 0 | 0.838 | 1.0 |
| freezegun | 1.0 | 0 | 1.0 | 1.0 |
| schedule | 1.0 | 0 | 1.0 | 1.0 |
| pexpect | 1.0 | 0 | 0.96 | 1.0 |
| requests | 1.0 | 0 | 1.0 | 1.0 |
| jsonschema | 1.0 | 0 | 0.9 | None |
| markdown-it-py | 1.0 | 0 | 1.0 | 1.0 |

gates: **ALL PASS**
