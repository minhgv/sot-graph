---
description: Package a bounded k-hop ContextBundle (YAML) for the current task
---

Run the SOT-Graph context packer, then read the generated bundle file:

```bash
sot pack "$ARGUMENTS" -o .sot/bundle.yaml
```

- After the command finishes, read `.sot/bundle.yaml` and use it as the working
  context for the task.
- Useful flags: `--depth <n>` (default 2), `--format <yaml|md>`.
