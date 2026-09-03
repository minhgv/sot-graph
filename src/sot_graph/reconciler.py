"""
sot_graph.reconciler — Level-triggered Single-Writer Reconciler.

The coordinator is deliberately the only process that touches ``Database``.
Extraction workers receive only the small, frozen ``ParseJob`` record and
return the equally explicit ``ParseResult`` record.
"""

from __future__ import annotations

import hashlib
import os
import signal
import sqlite3
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, cast

from sot_graph.db import Database
from sot_graph.extractor import EXT_DISPATCH, parse_file_graph
from sot_graph.ignore import DEFAULT_IGNORED_DIRS, GitIgnoreMatcher


IGNORED_DIRS: Set[str] = set(DEFAULT_IGNORED_DIRS)
TEXT_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".sh", ".sql", ".arb"}


@dataclass(frozen=True)
class ParseJob:
    path: str
    root_dir: str
    size: int
    mtime_ms: int
    base_generation: int = 0


@dataclass(frozen=True)
class ParseResult:
    path: str
    sha256: Optional[str]
    size: int
    mtime_ms: int
    nodes: Tuple[dict, ...]
    edges: Tuple[dict, ...]
    pending: Tuple[dict, ...]
    error: Optional[str] = None
    base_generation: int = 0
    # P5.2: parser outcome persisted to the file journal so coverage can
    # distinguish parsed/partial/failed files from merely-scanned ones.
    parser_outcome: Optional[str] = None
    parser_error: Optional[str] = None

@dataclass(frozen=True)
class ReconcileSummary:
    scanned: int
    unchanged: int
    updated: int
    deleted: int
    failed: int
    duration_ms: int
    conflicts: int = 0

    def as_dict(self) -> Dict[str, int]:
        return asdict(self)

    def to_legacy(self) -> Dict[str, int]:
        # Keep the v1 return shape of scan_and_reconcile().
        return {
            "indexed": self.updated,
            "unchanged": self.unchanged,
            "deleted": self.deleted,
            "error": self.failed,
        }


def _worker_sigint_ignore() -> None:
    """Workers must not race the coordinator for SIGINT ownership."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def _relative_path(path: str, root_dir: str) -> str:
    return os.path.relpath(path, root_dir).replace(os.sep, "/")


def _worker_error(category: str, job: ParseJob) -> str:
    # Error strings intentionally contain no exception text or traceback.
    return f"{category}:{_relative_path(job.path, job.root_dir)}"


def _safe_path(path: str, root_dir: str) -> Optional[str]:
    """Return a canonical path only when it remains inside ``root_dir``."""
    try:
        canonical_root = os.path.realpath(os.path.abspath(root_dir))
        canonical_path = os.path.realpath(path)
        if os.path.commonpath((canonical_root, canonical_path)) != canonical_root:
            return None
        return canonical_path
    except (OSError, ValueError):
        return None

def _parse_worker(job: ParseJob) -> ParseResult:
    """Picklable process-pool boundary; no coordinator state crosses it."""
    try:
        safe_path = _safe_path(job.path, job.root_dir)
        if safe_path is None:
            return ParseResult(
                job.path, None, job.size, job.mtime_ms, (), (), (),
                _worker_error("unsafe", job),
            )
        try:
            os.stat(safe_path)
        except FileNotFoundError:
            return ParseResult(
                job.path, None, job.size, job.mtime_ms, (), (), (),
                _worker_error("missing", job),
            )
        except PermissionError:
            return ParseResult(
                job.path, None, job.size, job.mtime_ms, (), (), (),
                _worker_error("permission", job),
            )
        except OSError:
            return ParseResult(
                job.path, None, job.size, job.mtime_ms, (), (), (),
                _worker_error("stat", job),
            )

        parsed = parse_file_graph(job.path, job.root_dir)
        nodes = tuple(dict(node) for node in parsed.get("nodes", ()))
        edges = tuple(dict(edge) for edge in parsed.get("edges", ()))
        pending = tuple(dict(edge) for edge in parsed.get("pending", ()))
        # An extractor can return a useful base file node alongside a syntax
        # diagnostic.  Preserve v1 behavior and index that useful result.
        if parsed.get("error") and not nodes:
            return ParseResult(
                job.path,
                parsed.get("sha256"),
                job.size,
                job.mtime_ms,
                nodes,
                edges,
                pending,
                _worker_error("parse", job),
                parser_outcome=str(parsed.get("parser_outcome") or ""),
                parser_error=str(parsed.get("error") or "") or None,
            )
        return ParseResult(
            job.path,
            parsed.get("sha256"),
            job.size,
            job.mtime_ms,
            nodes,
            edges,
            pending,
            None,
            job.base_generation,
            parser_outcome=str(parsed.get("parser_outcome") or ""),
            parser_error=str(parsed.get("error") or "") or None,
        )
    except PermissionError:
        return ParseResult(
            job.path, None, job.size, job.mtime_ms, (), (), (),
            _worker_error("permission", job),
        )
    except FileNotFoundError:
        return ParseResult(
            job.path, None, job.size, job.mtime_ms, (), (), (),
            _worker_error("missing", job),
        )
    except Exception:
        return ParseResult(
            job.path, None, job.size, job.mtime_ms, (), (), (),
            _worker_error("parse", job),
        )

class Reconciler:
    def __init__(self, db: Database, root_dir: str, extra_ignored_dirs: Optional[Set[str]] = None):
        self.db = db
        # Keep the caller's lexical root for DB compatibility (notably
        # macOS /var -> /private/var), while using its realpath for safety.
        requested_root = os.path.abspath(root_dir)
        self._canonical_root = os.path.realpath(requested_root)
        self.root_dir = self._stored_root_alias(requested_root)
        self.ignore_matcher = GitIgnoreMatcher(self.root_dir, extra_ignored_dirs=extra_ignored_dirs)

    def _stored_root_alias(self, requested_root: str) -> str:
        """Reuse an existing DB path spelling when its parent is this root."""
        try:
            journal_paths = sorted(self.db.all_journal_paths())
        except (AttributeError, OSError, sqlite3.Error):
            return requested_root
        for stored_path in journal_paths:
            try:
                raw_path = os.fspath(stored_path)
                candidate = (
                    raw_path
                    if os.path.isabs(raw_path)
                    else os.path.join(requested_root, raw_path)
                )
                candidate = os.path.abspath(candidate)
            except (TypeError, OSError, ValueError):
                continue
            parent = os.path.dirname(candidate)
            while parent and parent != os.path.dirname(parent):
                try:
                    if os.path.realpath(parent) == self._canonical_root:
                        return parent
                except OSError:
                    break
                parent = os.path.dirname(parent)
        return requested_root

    def _lexical_path(self, path: str) -> Optional[str]:
        """Return a root-contained path without resolving its final target."""
        try:
            raw = os.fspath(path)
            if not raw:
                return None
            candidate = raw if os.path.isabs(raw) else os.path.join(self.root_dir, raw)
            absolute = os.path.abspath(candidate)
            if os.path.commonpath((self.root_dir, absolute)) == self.root_dir:
                return absolute

            # An absolute path may use the alternate /var or /private/var
            # spelling.  Resolve ancestors only, never the final symlink.
            ancestor = os.path.dirname(absolute)
            while ancestor and ancestor != os.path.dirname(ancestor):
                try:
                    if os.path.realpath(ancestor) == self._canonical_root:
                        suffix = os.path.relpath(absolute, ancestor)
                        return os.path.abspath(os.path.join(self.root_dir, suffix))
                except OSError:
                    pass
                ancestor = os.path.dirname(ancestor)
            return None
        except (TypeError, OSError, ValueError):
            return None

    def _delete_path_variants(self, path: str) -> None:
        """Delete an absolute path and its root-relative DB spelling."""
        self.db.delete_path(path)
        relative = _relative_path(path, self.root_dir)
        if relative != path:
            self.db.delete_path(relative)

    def _normalise_path(self, path: str) -> Optional[str]:
        """Return a root-contained canonical path, or ``None`` if unsafe."""
        try:
            raw = os.fspath(path)
        except TypeError:
            return None
        if not raw:
            return None
        candidate = raw if os.path.isabs(raw) else os.path.join(self.root_dir, raw)
        absolute = os.path.abspath(candidate)
        canonical = os.path.realpath(absolute)
        try:
            if os.path.commonpath((self._canonical_root, canonical)) != self._canonical_root:
                return None
            # Resolve symlinks below the project root, but preserve the
            # caller's root spelling so existing DB IDs remain stable.
            relative = os.path.relpath(canonical, self._canonical_root)
            return os.path.abspath(os.path.join(self.root_dir, relative))
        except ValueError:
            return None

    def _supported(self, path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in EXT_DISPATCH or ext in TEXT_EXTENSIONS

    def _walk(self, directory: str, explicit: bool = False) -> List[str]:
        paths: List[str] = []
        for root, dirs, files in os.walk(directory):
            dirs[:] = sorted(
                d for d in dirs
                if not self.ignore_matcher.is_ignored(os.path.join(root, d), is_dir=True)
            )
            for name in sorted(files):
                path = self._normalise_path(os.path.join(root, name))
                if path is None or not os.path.isfile(path):
                    continue
                if not explicit and self.ignore_matcher.is_ignored(path, is_dir=False):
                    continue
                if explicit or self._supported(path):
                    paths.append(path)
        return paths

    def scan(self, paths: Optional[Sequence[str]] = None) -> List[str]:
        """Return supported, existing files in deterministic repository order."""
        candidates: Set[str] = set()
        if paths is None or len(paths) == 0:
            candidates.update(self._walk(self.root_dir))
        else:
            for requested in paths:
                path = self._normalise_path(requested)
                if path is None:
                    continue
                if os.path.isdir(path):
                    candidates.update(self._walk(path))
                elif os.path.isfile(path):
                    # Explicit files retain the existing single-file semantics.
                    if self._supported(path):
                        candidates.add(path)
        return sorted(candidates, key=lambda p: _relative_path(p, self.root_dir))

    def _hash(self, path: str) -> Optional[str]:
        try:
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except (OSError, IOError):
            return None

    def _known_abs_paths(self) -> Set[str]:
        result: Set[str] = set()
        for path in self.db.all_journal_paths():
            # Keep the lexical spelling as a deletion-only candidate.  Older
            # indexes could journal an internal symlink as ``alias.py`` while
            # the canonical scan now publishes its target as ``target.py``.
            # Tracking both lets the deletion sweep remove the stale alias
            # row without ever treating the alias as parse work.
            lexical = self._lexical_path(path)
            if lexical is not None:
                result.add(lexical)
            normalised = self._normalise_path(path)
            if normalised is not None:
                result.add(normalised)
        return result

    def _deletion_scope(
        self, paths: Optional[Sequence[str]], known_paths: Set[str]
    ) -> Set[str]:
        """Limit targeted reconciles to the requested path subtree."""
        if paths is None or len(paths) == 0:
            return set(known_paths)
        requested: List[str] = []
        for value in paths:
            normalised = self._normalise_path(value)
            lexical = self._lexical_path(value)
            for candidate in (normalised, lexical):
                if candidate is not None and candidate not in requested:
                    # Keep aliases in deletion scope, but never feed them to
                    # scan() or the parser; current_paths remains canonical.
                    requested.append(candidate)
        if not requested:
            return set()
        def is_under(base: str, candidate: str) -> bool:
            try:
                return os.path.commonpath((base, candidate)) == base
            except ValueError:
                return False

        scoped: Set[str] = set()
        for known in known_paths:
            for value in requested:
                if known == value:
                    scoped.add(known)
                    break
                if is_under(value, known) and (
                    os.path.isdir(value)
                    or any(
                        is_under(value, other)
                        for other in known_paths
                        if other != value
                    )
                ):
                    scoped.add(known)
                    break
        return scoped


    def _jobs_for_scan(
        self, paths: Optional[Sequence[str]], force: bool = False
    ) -> Tuple[List[ParseJob], Set[str], int]:
        disk_paths = self.scan(paths)
        jobs: List[ParseJob] = []
        failures = 0
        journal_cache: Dict[str, Any] = self.db.get_all_file_journals() if hasattr(self.db, "get_all_file_journals") else {}
        for path in disk_paths:
            try:
                stat = os.stat(path)
            except OSError:
                failures += 1
                continue
            size = int(stat.st_size)
            mtime_ms = int(stat.st_mtime * 1000)
            prior = journal_cache.get(path) or self.db.get_file_journal(path)
            if not force and prior and prior.get("size") == size and prior.get("mtime_ms") == mtime_ms:
                # Hash verification preserves v1 behavior for edits that retain
                # both size and mtime.
                current_sha = self._hash(path)
                if current_sha is None:
                    failures += 1
                    continue
                if prior.get("sha256") == current_sha:
                    continue
            jobs.append(ParseJob(
                path, self.root_dir, size, mtime_ms,
                base_generation=int(prior.get("generation") or 0) if prior else 0,
            ))
        return jobs, set(disk_paths), failures


    def _commit_batch(self, records: Sequence[ParseResult]) -> List[str]:
        """Phase B of the 2-Phase Publication protocol.

        Under the stable project lock, every parsed record is re-hashed on
        disk; a file that changed since Phase A is a stale snapshot and is
        reported as a conflict instead of overwriting the newer publication.
        The database additionally compare-and-swaps the per-path journal
        generation captured at parse time.
        """
        fresh: List[ParseResult] = []
        conflicts: List[str] = []
        with self._publication_gate():
            for record in records:
                if record.error is not None:
                    conflicts.append(record.path)
                    continue
                safe_record_path = _safe_path(record.path, self.root_dir)
                if safe_record_path is None:
                    conflicts.append(record.path)
                    continue
                try:
                    st = os.stat(safe_record_path)
                    cur_size = int(st.st_size)
                    cur_mtime_ms = int(st.st_mtime * 1000)
                    disk_sha = self._hash(safe_record_path)
                except OSError:
                    conflicts.append(record.path)
                    continue

                if (
                    disk_sha is not None
                    and disk_sha == (record.sha256 or "")
                    and cur_size == record.size
                    and abs(cur_mtime_ms - record.mtime_ms) <= 2000
                ):
                    fresh.append(record)
                else:
                    conflicts.append(record.path)
            if fresh:
                expected = {record.path: record.base_generation for record in fresh}
                batch = getattr(self.db, "commit_file_batch", None)
                outcome: Dict[str, Any]
                if callable(batch):
                    outcome = cast(Dict[str, Any], batch(fresh, expected_generations=expected))
                else:
                    # Kept solely for databases created by v1 callers during a
                    # rolling upgrade; no CAS data is available there.
                    for record in fresh:
                        self.db.commit_file(
                            path=record.path,
                            sha256=record.sha256 or "",
                            size=record.size,
                            mtime_ms=record.mtime_ms,
                            nodes=list(record.nodes),
                            edges=list(record.edges),
                            pending=list(record.pending),
                        )
                    outcome = {"committed": len(fresh), "conflicts": []}
                conflicts.extend(outcome.get("conflicts", []))
        return conflicts

    def _publication_gate(self) -> AbstractContextManager[Any]:
        """Serialize mutations behind the stable `.sot/write.lock`."""
        from contextlib import contextmanager

        lock_factory = getattr(self.db, "write_lock", None)
        if callable(lock_factory):
            return cast(AbstractContextManager[Any], lock_factory())

        @contextmanager
        def _unlocked():
            yield

        return _unlocked()

    def reconcile_path(self, path: str, *, janitor: bool = True) -> str:
        """Reconcile one path using the original v1 action vocabulary.

        ``janitor=False`` skips only the post-commit global janitor
        passes (pending-edge resolution + orphan cleanup); batch callers
        run them once via :meth:`reconcile_paths` instead of once per
        file. All other callers keep the default full behavior.
        """
        absolute = self._normalise_path(path)
        if absolute is None:
            # Keep an escaped in-root symlink deletion-only.  Do not stat,
            # hash, or parse the external target, and still reject the path.
            lexical = self._lexical_path(path)
            if lexical is not None:
                with self._publication_gate():
                    self._delete_path_variants(lexical)
            return "error"
        prior = self.db.get_file_journal(absolute)
        base_generation = int(prior.get("generation") or 0) if prior else 0
        if not os.path.exists(absolute) or not os.path.isfile(absolute):
            with self._publication_gate():
                self._delete_path_variants(absolute)
            return "deleted"
        try:
            stat = os.stat(absolute)
        except OSError:
            with self._publication_gate():
                self._delete_path_variants(absolute)
            return "deleted"
        if not self._supported(absolute):
            # Watcher-fed events can name unsupported/binary files (logos,
            # data blobs). Indexing them would publish file nodes that the
            # next full reconcile's deletion sweep removes again —
            # add/delete churn plus binary bytes in FTS. Delete any legacy
            # rows (mirrors scan()'s supported-only semantics) and stop.
            with self._publication_gate():
                self._delete_path_variants(absolute)
            return "excluded"
        job = ParseJob(
            absolute,
            self.root_dir,
            int(stat.st_size),
            int(stat.st_mtime * 1000),
            base_generation=base_generation,
        )
        result = _parse_worker(job)
        if result.error:
            # A file can disappear after the initial stat.
            if result.error.startswith("missing:") and not os.path.exists(absolute):
                with self._publication_gate():
                    self._delete_path_variants(absolute)
                return "deleted"
            return "error"
        if prior and prior.get("sha256") == result.sha256:
            return "unchanged"
        try:
            conflicts = self._commit_batch([result])
        except Exception:
            return "error"
        if conflicts:
            return "conflict"
        if janitor:
            resolver = getattr(self.db, "resolve_all_pending_edges", None)
            if callable(resolver):
                with self._publication_gate():
                    resolver()
            cleanup = getattr(self.db, "cleanup_orphan_edges", None)
            if callable(cleanup):
                with self._publication_gate():
                    cleanup()
        return "indexed"

    def reconcile_paths(self, paths: Iterable[str]) -> Tuple[int, Set[str]]:
        """Reconcile a batch of paths with a single global janitor pass.

        Contract: per-file commits stay individual (each file still takes
        the publication gate on its own, so lock granularity is
        unchanged), but the gated global janitors — pending-edge
        resolution plus orphan cleanup — run exactly once for the whole
        batch and only when something was published. A git checkout
        touching N files therefore costs one full-graph pass instead of
        N. LockBusy paths are deferred into the returned set (never
        dropped); any other failure skips just that path. Returns
        ``(published, deferred)`` where published counts outcomes outside
        ``("error", "excluded")``, mirroring the watcher's per-file
        semantics.
        """
        from sot_graph.locking import LockBusy

        published = 0
        deferred: Set[str] = set()
        for path in sorted(paths):
            try:
                outcome = self.reconcile_path(path, janitor=False)
            except LockBusy:
                deferred.add(path)
                continue
            except Exception:
                continue
            if outcome not in ("error", "excluded"):
                published += 1
        if published:
            resolver = getattr(self.db, "resolve_all_pending_edges", None)
            if callable(resolver):
                with self._publication_gate():
                    resolver()
            cleanup = getattr(self.db, "cleanup_orphan_edges", None)
            if callable(cleanup):
                with self._publication_gate():
                    cleanup()
        return published, deferred

    def _parallel_window(
        self,
        executor: ProcessPoolExecutor,
        jobs: Sequence[ParseJob],
        outstanding_limit: int,
    ) -> Tuple[List[ParseResult], bool]:
        futures: Dict[Any, ParseJob] = {}
        results: List[ParseResult] = []
        next_job = 0
        broken = False
        def submit_one() -> None:
            nonlocal next_job, broken
            if next_job >= len(jobs):
                return
            job = jobs[next_job]
            next_job += 1
            try:
                futures[executor.submit(_parse_worker, job)] = job
            except Exception:
                broken = True
                results.append(
                    ParseResult(
                        job.path, None, job.size, job.mtime_ms, (), (), (),
                        _worker_error("worker", job),
                    )
                )
        while len(futures) < outstanding_limit and next_job < len(jobs):
            submit_one()
            if broken:
                break
        while futures:
            done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)

            for future in done:
                job = futures.pop(future)
                try:
                    results.append(future.result())
                except KeyboardInterrupt:
                    raise
                except Exception:
                    # A future exception indicates pool breakage; ordinary
                    # worker exceptions are converted into ParseResult above.
                    broken = True
                    results.append(
                        ParseResult(
                            job.path, None, job.size, job.mtime_ms, (), (), (),
                            _worker_error("worker", job),
                        )
                    )
            if broken:
                for future, pending_job in tuple(futures.items()):
                    future.cancel()
                    results.append(
                        ParseResult(
                            pending_job.path, None, pending_job.size,
                            pending_job.mtime_ms, (), (), (),
                            _worker_error("worker", pending_job),
                        )
                    )
                for pending_job in jobs[next_job:]:
                    results.append(
                        ParseResult(
                            pending_job.path, None, pending_job.size,
                            pending_job.mtime_ms, (), (), (),
                            _worker_error("worker", pending_job),
                        )
                    )
                next_job = len(jobs)
                futures.clear()
                break
            while len(futures) < outstanding_limit and next_job < len(jobs):
                submit_one()
                if broken:
                    break
        if broken and next_job < len(jobs):
            for pending_job in jobs[next_job:]:
                results.append(
                    ParseResult(
                        pending_job.path, None, pending_job.size,
                        pending_job.mtime_ms, (), (), (),
                        _worker_error("worker", pending_job),
                    )
                )
            next_job = len(jobs)
        return results, broken

    def reconcile(
        self,
        paths: Optional[Sequence[str]] = None,
        *,
        workers: Optional[int] = None,
        batch_size: int = 64,
        force: bool = False,
    ) -> ReconcileSummary:
        """Scan and reconcile with deterministic, bounded parallel extraction.

        ``force`` re-extracts every discovered file regardless of journal
        state — the upgrade path for extractor changes on existing indexes.
        """
        if workers is None:
            workers = min(8, max(1, os.cpu_count() or 1))
        if workers < 1:
            raise ValueError("workers must be >= 1")
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        started = time.monotonic()

        jobs, current_paths, scan_failures = self._jobs_for_scan(paths, force=force)
        known_paths = self._known_abs_paths()
        unchanged = len(current_paths) - len(jobs) - scan_failures
        updated = 0
        failed = scan_failures
        conflicts_total = 0
        deleted_during_parse: Set[str] = set()
        interrupted = False
        pool_broken = False
        executor: Optional[ProcessPoolExecutor] = None

        old_sigint = None
        is_main_thread = (threading.current_thread() is threading.main_thread())
        if is_main_thread:
            try:
                old_sigint = signal.getsignal(signal.SIGINT)
                signal.signal(signal.SIGINT, signal.default_int_handler)
            except (ValueError, AttributeError):
                is_main_thread = False
        try:
            windows = [
                jobs[index:index + batch_size]
                for index in range(0, len(jobs), batch_size)
            ]
            use_pool = workers > 1 and len(jobs) > 1
            if use_pool:
                executor = ProcessPoolExecutor(
                    max_workers=min(workers, len(jobs)),
                    initializer=_worker_sigint_ignore,
                )
            for window_index, window in enumerate(windows):
                if executor is None:
                    parsed = [_parse_worker(job) for job in window]
                    broken = False
                else:
                    parsed, broken = self._parallel_window(
                        executor,
                        window,
                        min(batch_size, workers * 2),
                    )
                pool_broken = pool_broken or broken
                successful = [
                    result for result in parsed
                    if result.error is None and result.sha256 is not None
                ]
                for result in parsed:
                    if result.error is not None or result.sha256 is None:
                        abs_path = os.path.join(self.root_dir, result.path) if not os.path.isabs(result.path) else result.path
                        if (
                            result.error is not None
                            and result.error.startswith("missing:")
                            and not os.path.exists(abs_path)
                        ):
                            with self._publication_gate():
                                self.db.delete_path(result.path)
                                self.db.delete_path(abs_path)
                            deleted_during_parse.add(abs_path)
                        else:
                            failed += 1
                if successful:
                    try:
                        conflicts = self._commit_batch(successful)
                        conflicts_total += len(conflicts)
                        updated += len(successful) - len(conflicts)
                    except Exception:
                        # Database transaction rollback is owned by Database;
                        # no record in this window is counted as committed.
                        failed += len(successful)
                if pool_broken:
                    # Never silently switch to sequential after partial writes.
                    failed += sum(len(item) for item in windows[window_index + 1:])
                    break

            deletion_scope = self._deletion_scope(paths, known_paths)
            dead_paths = (deletion_scope - current_paths) - deleted_during_parse
            with self._publication_gate():
                for dead_path in sorted(
                    dead_paths,
                    key=lambda p: _relative_path(p, self.root_dir),
                ):
                    self._delete_path_variants(dead_path)
                deleted = len(dead_paths) + len(deleted_during_parse)
                resolver = getattr(self.db, "resolve_all_pending_edges", None)
                if callable(resolver):
                    resolver()
                janitor = getattr(self.db, "cleanup_orphan_edges", None)
                if callable(janitor):
                    janitor()
                # The optional vector index is not maintained transactionally
                # with graph mutations — drop embeddings of nodes this pass
                # deleted so they stop answering vector queries.
                try:
                    from sot_graph.vector import prune_orphans
                    prune_orphans(self.db.conn)
                except Exception:
                    pass
        except KeyboardInterrupt:
            interrupted = True
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            if is_main_thread and old_sigint is not None:
                try:
                    signal.signal(signal.SIGINT, old_sigint)
                except (ValueError, AttributeError):
                    pass
            if executor is not None and not interrupted:
                executor.shutdown(wait=not pool_broken, cancel_futures=pool_broken)

        duration_ms = int((time.monotonic() - started) * 1000)
        # A broken pool is represented as failed work; callers can return a
        # command failure without ever attempting an unsafe sequential retry.
        return ReconcileSummary(
            scanned=len(current_paths),
            unchanged=max(0, unchanged),
            updated=updated,
            deleted=deleted,
            failed=failed,
            duration_ms=duration_ms,
            conflicts=conflicts_total,
        )

    def scan_and_reconcile(
        self,
        paths: Optional[Sequence[str]] = None,
        *,
        workers: Optional[int] = None,
        batch_size: int = 64,
    ) -> Dict[str, int]:
        """Compatibility wrapper retaining the v1 dictionary result."""
        return self.reconcile(
            paths=paths, workers=workers, batch_size=batch_size
        ).to_legacy()

    def audit_drift(self, deep: bool = False) -> List[Dict[str, str]]:
        """
        Read-only comparison of journaled records against the filesystem.
        Returns a list of drifted items: [{ 'path': ..., 'why': 'missing'|'mtime_size'|'hash' }].
        Safe to run in CI pipelines.
        """
        drift = []
        for path in self.db.all_journal_paths():
            if not os.path.exists(path) or not os.path.isfile(path):
                drift.append({"path": path, "why": "missing"})
                continue

            try:
                st = os.stat(path)
            except OSError:
                drift.append({"path": path, "why": "unreadable"})
                continue

            prior = self.db.get_file_journal(path)
            if not prior:
                drift.append({"path": path, "why": "unrecorded"})
                continue

            if deep:
                try:
                    with open(path, "rb") as handle:
                        current_sha = hashlib.sha256(handle.read()).hexdigest()
                    if current_sha != prior["sha256"]:
                        drift.append({"path": path, "why": "hash_mismatch"})
                except Exception:
                    drift.append({"path": path, "why": "unreadable"})
            elif st.st_size != prior["size"] or int(st.st_mtime * 1000) != prior["mtime_ms"]:
                drift.append({"path": path, "why": "mtime_size_mismatch"})

        return drift
