---
description: Search the SOT knowledge graph for verified code and knowledge
---

Run the SOT-Graph verified search and report the ranked results with their
Trust Verdicts:

```bash
./bin/sot search "$ARGUMENTS"
```

- Add `-n <count>` to limit results, `--scope <dir>` to narrow the search space.
- Only `[STRONG]` and `[REBUILT]` verdicts may be relied on without inspection;
  `[WEAK]` matches require reading the file first.
- Summarize what already exists before writing any new code.
