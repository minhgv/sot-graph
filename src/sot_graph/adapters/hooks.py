"""Git hook provisioning: event-driven reconcile for the no-daemon model.

`sot setup --hooks` appends a guarded reconcile invocation to post-merge
and post-checkout so the graph syncs exactly when branches change — no
polling, no resident process. Idempotent: a hook carrying our marker is
never duplicated.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

HOOK_MARKER = "# sot-graph: keep the knowledge graph in sync"
HOOK_NAMES = ("post-merge", "post-checkout")


def _hooks_dir(root: Path) -> Path | None:
    git_path = root / ".git"
    if git_path.is_dir():
        return git_path / "hooks"
    if git_path.is_file():
        # Worktree: .git holds `gitdir: /path/to/main/.git/worktrees/name`.
        text = git_path.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith("gitdir:"):
            return Path(text.split(":", 1)[1].strip()) / "hooks"
    return None


def install_git_hooks(root: Path) -> List[Path]:
    """Append the reconcile hook block; returns hook paths (idempotent)."""
    hooks_dir = _hooks_dir(root)
    if hooks_dir is None:
        return []

    src_dir = (root / "src").resolve()
    block = "\n".join([
        HOOK_MARKER,
        f'PYTHONPATH="{src_dir}" "{sys.executable}" -m sot_graph.cli reconcile >/dev/null 2>&1 || true',
        "",
    ])

    installed: List[Path] = []
    for name in HOOK_NAMES:
        hook = hooks_dir / name
        existing = ""
        if hook.exists():
            existing = hook.read_text(encoding="utf-8", errors="replace")
            if HOOK_MARKER in existing:
                installed.append(hook)
                continue
        with open(hook, "a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(block)
        hook.chmod(0o755)
        installed.append(hook)
    return installed


__all__ = ["install_git_hooks", "HOOK_MARKER", "HOOK_NAMES"]
