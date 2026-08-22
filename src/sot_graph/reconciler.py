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
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

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


def _parse_worker(job: ParseJob) -> ParseResult:
    """Picklable process-pool boundary; no coordinator state crosses it."""
    try:
        try:
            os.stat(job.path)
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
        self.root_dir = os.path.abspath(root_dir)
        self.ignore_matcher = GitIgnoreMatcher(self.root_dir, extra_ignored_dirs=extra_ignored_dirs)
    def _normalise_path(self, path: str) -> Optional[str]:
        """Return an absolute root-contained path, or ``None`` if unsafe."""
        raw = os.fspath(path)
        candidate = raw if os.path.isabs(raw) else os.path.join(self.root_dir, raw)
        absolute = os.path.abspath(candidate)
        try:
            if os.path.commonpath((self.root_dir, absolute)) != self.root_dir:
                return None
        except ValueError:
            return None
        return absolute

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
                path = os.path.abspath(os.path.join(root, name))
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
            normalised = self._normalise_path(path)
            result.add(normalised if normalised is not None else os.path.abspath(path))
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
            if normalised is not None:
                requested.append(normalised)
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
        self, paths: Optional[Sequence[str]]
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
            if prior and prior.get("size") == size and prior.get("mtime_ms") == mtime_ms:
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
        for record in records:
            disk_sha = self._hash(record.path) if record.error is None else None
            if disk_sha is not None and disk_sha == (record.sha256 or ""):
                fresh.append(record)
            else:
                conflicts.append(record.path)
        if fresh:
            expected = {record.path: record.base_generation for record in fresh}
            batch = getattr(self.db, "commit_file_batch", None)
            with self._publication_gate():
                if callable(batch):
                    outcome = batch(fresh, expected_generations=expected)
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

    def _publication_gate(self):
        """Serialize mutations behind the stable `.sot/write.lock`."""
        from contextlib import contextmanager

        lock_factory = getattr(self.db, "write_lock", None)
        if callable(lock_factory):
            return lock_factory()

        @contextmanager
        def _unlocked():
            yield

        return _unlocked()

    def reconcile_path(self, path: str) -> str:
        """Reconcile one path using the original v1 action vocabulary."""
        absolute = self._normalise_path(path)
        if absolute is None:
            return "error"
        rel_path = _relative_path(absolute, self.root_dir)
        prior = self.db.get_file_journal(absolute)
        base_generation = int(prior.get("generation") or 0) if prior else 0
        if not os.path.exists(absolute) or not os.path.isfile(absolute):
            with self._publication_gate():
                self.db.delete_path(rel_path)
                self.db.delete_path(absolute)
            return "deleted"
        try:
            stat = os.stat(absolute)
        except OSError:
            with self._publication_gate():
                self.db.delete_path(rel_path)
                self.db.delete_path(absolute)
            return "deleted"
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
                    self.db.delete_path(absolute)
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
        resolver = getattr(self.db, "resolve_all_pending_edges", None)
        if callable(resolver):
            with self._publication_gate():
                resolver()
        janitor = getattr(self.db, "cleanup_orphan_edges", None)
        if callable(janitor):
            with self._publication_gate():
                janitor()
        return "indexed"

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
    ) -> ReconcileSummary:
        """Scan and reconcile with deterministic, bounded parallel extraction."""
        if workers is None:
            workers = min(8, max(1, os.cpu_count() or 1))
        if workers < 1:
            raise ValueError("workers must be >= 1")
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        started = time.monotonic()

        jobs, current_paths, scan_failures = self._jobs_for_scan(paths)
        known_paths = self._known_abs_paths()
        unchanged = len(current_paths) - len(jobs) - scan_failures
        updated = 0
        failed = scan_failures
        conflicts_total = 0
        deleted_during_parse: Set[str] = set()
        interrupted = False
        pool_broken = False
        executor: Optional[ProcessPoolExecutor] = None

        old_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, signal.default_int_handler)
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
                    self.db.delete_path(dead_path)
                deleted = len(dead_paths) + len(deleted_during_parse)
                resolver = getattr(self.db, "resolve_all_pending_edges", None)
                if callable(resolver):
                    resolver()
                janitor = getattr(self.db, "cleanup_orphan_edges", None)
                if callable(janitor):
                    janitor()
        except KeyboardInterrupt:
            interrupted = True
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            signal.signal(signal.SIGINT, old_sigint)
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
