---
description: Trace cross-file dependencies and blast radius of a symbol
---

Run the SOT-Graph AST explorer for the target symbol:

```bash
sot explore "$ARGUMENTS"
```

- Add `--depth <n>` to widen the graph walk (default 2).
- Review both outward calls and incoming references before changing a
  signature — every incoming caller is part of the blast radius.
