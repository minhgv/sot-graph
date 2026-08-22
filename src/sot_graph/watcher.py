"""
sot_graph.watch — Reactive file watcher daemon for real-time sync.

Backends:
- ``watchfiles`` (inotify/kqueue/ReadDirectoryChangesW) when the optional
  ``[watch]`` extra is installed;
- a stdlib polling fallback otherwise, so the daemon stays zero-dependency.

Both backends fold rapid save events through the same debouncer and publish
through the reconciler's 2-Phase CAS gate (``.sot/write.lock``); if a heavy
CLI migration holds the lock, the watcher backs off instead of hanging.
"""

from __future__ import annotations

import os
import time
from typing import Callable, Optional, Set

from sot_graph.locking import LockBusy

__all__ = ["run_watch", "pick_backend"]

_WATCHFILES = None
try:  # optional [watch] extra
    import watchfiles as _WATCHFILES  # type: ignore
except ImportError:
    _WATCHFILES = None


def pick_backend(requested: str) -> str:
    if requested == "watchfiles":
        if _WATCHFILES is None:
            raise RuntimeError(
                "watchfiles backend requested but not installed; "
                "pip install sot-graph[watch] or use --backend poll"
            )
        return "watchfiles"
    if requested == "poll":
        return "poll"
    return "watchfiles" if _WATCHFILES is not None else "poll"


def _reconcile_quietly(reconciler, paths: Set[str]) -> int:
    """Reconcile changed paths; back off gracefully when the lock is busy."""
    published = 0
    for path in sorted(paths):
        try:
            outcome = reconciler.reconcile_path(path)
        except LockBusy:
            time.sleep(0.2)
            continue
        except Exception:
            continue
        if outcome not in ("error",):
            published += 1
    return published


def _run_watchfiles(reconciler, root: str, debounce_ms: int, log: Callable[[str], None]) -> None:
    assert _WATCHFILES is not None
    for changes in _WATCHFILES.watch(
        root, debounce=int(debounce_ms) / 1000.0, recursive=True, step=50
    ):
        paths = {
            path for _kind, path in changes
            if not reconciler.ignore_matcher.is_ignored(path)
        }
        if not paths:
            continue
        log(f"change: {len(paths)} file(s)")
        _reconcile_quietly(reconciler, paths)


def _run_polling(
    reconciler,
    root: str,
    debounce_ms: int,
    log: Callable[[str], None],
    interval_ms: int = 500,
) -> None:
    def snapshot() -> dict:
        state = {}
        try:
            for path in reconciler.scan(None):
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                state[path] = (stat.st_size, int(stat.st_mtime * 1000))
        except Exception:
            pass
        return state

    current = snapshot()
    while True:
        time.sleep(interval_ms / 1000.0)
        fresh = snapshot()
        changed = {
            path for path, stamp in fresh.items()
            if current.get(path) != stamp
        } | {path for path in current if path not in fresh}
        current = fresh
        if not changed:
            continue
        # Fold bursty edits: wait until quiet for debounce_ms.
        quiet_until = time.monotonic() + debounce_ms / 1000.0
        while time.monotonic() < quiet_until:
            time.sleep(min(0.05, max(0.0, quiet_until - time.monotonic())))
            fresh = snapshot()
            delta = {
                path for path, stamp in fresh.items()
                if current.get(path) != stamp
            } | {path for path in current if path not in fresh}
            current = fresh
            if delta:
                changed |= delta
                quiet_until = time.monotonic() + debounce_ms / 1000.0
        log(f"change: {len(changed)} file(s)")
        _reconcile_quietly(reconciler, changed)


def run_watch(
    reconciler,
    root: str,
    debounce_ms: int = 200,
    backend: str = "auto",
    interval_ms: int = 500,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Run the watch daemon until interrupted (KeyboardInterrupt exits)."""
    resolved = pick_backend(backend)
    log = log or (lambda message: print(f"[sot watch:{resolved}] {message}", flush=True))
    log(f"watching {root} (backend={resolved}, debounce={debounce_ms}ms)")
    if resolved == "watchfiles":
        _run_watchfiles(reconciler, root, debounce_ms, log)
    else:
        _run_polling(reconciler, root, debounce_ms, log, interval_ms=interval_ms)
