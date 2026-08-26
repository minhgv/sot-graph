"""sot_graph.providers.codebase_memory — one-shot FEDERATED_CLI adapter.

Wire contract (verified against Codebase Memory source @010569f, v0.10.8):
- invocation: ``<command> cli --json <tool> [--flag value | --args-file path]``
  executed as a pure argv list (never a shell), ``cwd`` = canonical repo root.
- stdout carries EXACTLY ONE MCP envelope JSON document:
  ``{"content":[{"type":"text","text":"..."}],"isError":bool,"structuredContent":{}}``
- logs/progress go to stderr and are never part of the payload.
- exit codes: 0 = ok, 1 = error / ``isError`` envelope, 2 = bad arguments.
- bootstrap failures surface as a JSON-RPC error envelope on stdout.
- ``--version`` prints ``codebase-memory-mcp <version>``.

P1 boundaries (honest abstention):
- The adapter NEVER invokes ``index_repository``. A missing/stale index is
  reported as a failed outcome with ``next_action="run sot providers sync
  codebase-memory"`` so the caller can fall back truthfully.
- Evidence normalization/trust ceilings live in ``normalization`` and are
  applied by callers; this module extracts payloads verbatim.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from sot_graph.proc import RunResult, run_command
from sot_graph.snapshot import get_head_sha

from .base import (
    ArchitectureRequest,
    CoverageRequest,
    ImpactRequest,
    IndexRequest,
    ProviderRunRecord,
    ProviderStatus,
    QueryOutcome,
    SymbolRequest,
    TraceRequest,
)
from .normalization import (
    TESTED_CBM_VERSION,
    VERSION_COMPATIBLE,
    VERSION_INCOMPATIBLE,
    VERSION_UNTESTED,
    VERSION_UNKNOWN,
)

__all__ = [
    "CodebaseMemoryProvider",
    "PROVIDER_NAME",
    "NEXT_ACTION_SYNC",
    "NEXT_ACTION_VERSION_PIN",
    "SnapshotBinding",
    "SnapshotMatch",
    "snapshot_flags",
]

logger = logging.getLogger(__name__)

PROVIDER_NAME = "codebase-memory"

#: Actionable fix attached to every index-missing/stale abstention (P1).
NEXT_ACTION_SYNC = "run sot providers sync codebase-memory"

#: Actionable fix attached to every wire-incompatible fail-close (G1.5).
NEXT_ACTION_VERSION_PIN = (
    f"pin codebase-memory-mcp=={TESTED_CBM_VERSION} (golden-verified wire) "
    "or re-capture tests/fixtures/cbm_golden for the new release"
)

#: ``codebase-memory-mcp <semver>`` — anchored at start of first stdout line.
_VERSION_PATTERN = re.compile(r"^codebase-memory-mcp\s+(\S+)")

DEFAULT_QUERY_TIMEOUT_SECONDS = 30.0
DEFAULT_INDEX_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_OUTPUT_BYTES = 8 * 1024 * 1024

#: argv flag substrings whose VALUE is considered sensitive in any log/ledger.
_SENSITIVE_FLAGS = (
    "token", "secret", "password", "api-key", "apikey", "authorization",
    "credential",
)


@dataclass(frozen=True)
class _InvokeOutcome:
    """Raw result of one CLI invocation plus its ledger-ready run record."""

    ok: bool
    status: str
    payload: Any = None
    error: str | None = None
    run: ProviderRunRecord | None = None
    match: "SnapshotMatch | None" = None

@dataclass(frozen=True)
class SnapshotBinding:
    """CBM index state captured from one ``index_status`` call (P2).

    Exactly what the wire reported — nothing is fabricated when a field is
    missing; unknown values stay ``None``.
    """

    project: str | None
    head_sha: str | None
    branch: str | None
    index_status: str | None
    captured_at: int


@dataclass(frozen=True)
class SnapshotMatch:
    """Verdict of comparing a CBM index binding against the SOT worktree.

    ``bound``  — an index binding was obtained at all (else UNVERIFIABLE).
    ``fresh``  — the index provably reflects the current HEAD (and, when
                 paths were consulted, every coverage entry was fresh).
    Anything that cannot be proven fresh is ``fresh=False`` (fail-closed):
    ``detail`` distinguishes STALE (head mismatch / stale coverage) from
    UNKNOWN (SOT HEAD unavailable, tooling failure).
    """

    bound: bool
    fresh: bool
    detail: str
    project: str | None = None
    cbm_head_sha: str | None = None
    sot_head_sha: str | None = None
    branch: str | None = None
    stale_paths: tuple[str, ...] = ()

    @property
    def freshness(self) -> str:
        """FRESH | STALE | UNKNOWN | UNBOUND — the ledger vocabulary."""
        if not self.bound:
            return "UNBOUND"
        if self.fresh:
            return "FRESH"
        if self.stale_paths or (
            self.cbm_head_sha is not None and self.sot_head_sha is not None
        ):
            return "STALE"
        return "UNKNOWN"


def snapshot_flags(metadata: Mapping[str, Any]) -> tuple[bool, bool]:
    """Extract ``(snapshot_bound, source_changed)`` for trust_ceiling().

    Reads the ``freshness`` marker this adapter attaches to QueryOutcome
    metadata. Fail-closed: anything but FRESH caps at UNVERIFIABLE/STALE,
    so a candidate derived from a mismatched snapshot can NEVER be SUPPORTED.
    """
    freshness = metadata.get("freshness")
    if freshness == "FRESH":
        return True, False
    if freshness == "STALE":
        return True, True
    return False, False




def redact_argv(argv: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Mask values of sensitive flags so argv can be logged/persisted.

    Handles both ``--token abc`` (separated) and ``--token=abc`` (inline).
    """
    redacted: list[str] = []
    sensitive_next = False
    for part in argv:
        if sensitive_next:
            redacted.append("***REDACTED***")
            sensitive_next = False
            continue
        lowered = part.lower()
        if lowered.startswith("--") and any(
            marker in lowered for marker in _SENSITIVE_FLAGS
        ):
            if "=" in part:
                redacted.append(part.split("=", 1)[0] + "=***REDACTED***")
            else:
                redacted.append(part)
                sensitive_next = True
            continue
        redacted.append(part)
    return tuple(redacted)


def _command_digest(redacted: tuple[str, ...]) -> str:
    """Stable sha256 over the REDACTED argv (ledger ``command_digest``)."""
    return hashlib.sha256("\0".join(redacted).encode("utf-8")).hexdigest()


def _count_json_documents(text: str) -> int:
    """Count whitespace-separated top-level JSON documents in ``text``.

    Returns -1 when the text is not parseable as JSON at some offset.
    """
    decoder = json.JSONDecoder()
    idx = 0
    count = 0
    stripped = text.strip()
    while idx < len(stripped):
        while idx < len(stripped) and stripped[idx] in " \t\r\n":
            idx += 1
        if idx >= len(stripped):
            break
        try:
            _, end = decoder.raw_decode(stripped, idx)
        except json.JSONDecodeError:
            return -1
        count += 1
        idx = end
    return count


def _extract_message(envelope: Mapping[str, Any]) -> str:
    """Best-effort human-readable message from an MCP error envelope."""
    content = envelope.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, Mapping) and isinstance(first.get("text"), str):
            return first["text"]
    structured = envelope.get("structuredContent")
    if isinstance(structured, Mapping):
        message = structured.get("message") or structured.get("error")
        if isinstance(message, str):
            return message
    return "provider returned an error without a message"


def _extract_payload(envelope: Mapping[str, Any]) -> tuple[Any, str | None]:
    """Extract the tool payload from an MCP success envelope.

    Prefers a non-empty ``structuredContent``; otherwise parses the JSON text
    of ``content[0]``. Returns ``(payload, problem)`` — problem None on success.
    """
    structured = envelope.get("structuredContent")
    if isinstance(structured, Mapping) and structured:
        return dict(structured), None

    content = envelope.get("content")
    if not isinstance(content, list) or not content:
        return None, "schema drift: envelope has no content array"
    first = content[0]
    if not isinstance(first, Mapping):
        return None, "schema drift: content[0] is not an object"
    if first.get("type") != "text":
        return None, f"schema drift: unsupported content type {first.get('type')!r}"
    text = first.get("text")
    if not isinstance(text, str):
        return None, "schema drift: content[0].text missing or not a string"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Text-report tools (search_graph, trace_path, get_architecture)
        # emit a human-readable report instead of JSON (ADR-0001 §6);
        # surface the report verbatim so callers parse documented columns.
        return text, None
    return payload, None


class CodebaseMemoryProvider:
    """Adapter for the Codebase Memory one-shot CLI (FEDERATED_CLI)."""

    capabilities: tuple[str, ...]

    def __init__(
        self,
        config: Any = None,
        *,
        db: _RunsLedger | None = None,
        command: list[str] | tuple[str, ...] | None = None,
        query_timeout_seconds: float = DEFAULT_QUERY_TIMEOUT_SECONDS,
        index_timeout_seconds: float = DEFAULT_INDEX_TIMEOUT_SECONDS,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        provider_version: str | None = None,
    ) -> None:
        cfg_command: list[str] | None = getattr(config, "command", None)
        cfg_caps = tuple(getattr(config, "capabilities", ()) or ())
        self.command: tuple[str, ...] = tuple(
            command if command is not None else (cfg_command or ["codebase-memory-mcp"])
        )
        self.capabilities = cfg_caps
        self._db = db
        self._query_timeout = float(query_timeout_seconds)
        self._index_timeout = float(index_timeout_seconds)
        self._max_output_bytes = int(max_output_bytes)
        #: repo_root(realpath) -> (resolved_project, problem, next_action);
        #: avoids one ``list_projects`` round-trip per query on the same root.
        self._project_cache: dict[str, tuple[str | None, str | None, str | None]] = {}
        self._version: str | None = provider_version

    def version_compatibility(self) -> str:
        """Classify the probed binary release against the golden-tested one.

        COMPATIBLE   — exact match; the golden fixtures prove this wire.
        UNTESTED     — same major.minor, different patch; queries still run
                       but downstream verdicts cap at UNVERIFIABLE.
        INCOMPATIBLE — different major.minor; queries fail closed.
        UNKNOWN      — probe has not produced a parsable version yet.
        """
        if self._version is None:
            return VERSION_UNKNOWN
        if self._version == TESTED_CBM_VERSION:
            return VERSION_COMPATIBLE
        if self._version.split(".")[:2] == TESTED_CBM_VERSION.split(".")[:2]:
            return VERSION_UNTESTED
        return VERSION_INCOMPATIBLE

    def probe(self, repo_root: str) -> ProviderStatus:
        """Probe ``<command> --version``; never raises."""
        started = time.monotonic()
        result = run_command(
            [*self.command, "--version"],
            cwd=os.path.realpath(repo_root),
            timeout_seconds=min(self._query_timeout, 15.0),
            max_output_bytes=self._max_output_bytes,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        self._persist_run(
            capability="probe", result=result, duration_ms=duration_ms,
            status=self._probe_status(result), repo_root=repo_root,
        )

        if result.error is not None:
            return ProviderStatus(
                name=PROVIDER_NAME,
                installed=False,
                healthy=False,
                version=None,
                detail=f"not installed: {result.error}",
                capabilities=self.capabilities,
            )
        match = _VERSION_PATTERN.match(result.stdout.strip())
        if result.returncode != 0 or match is None:
            detail = "unhealthy: " + (
                f"exit={result.returncode}" if result.returncode != 0
                else f"unparseable version output: {result.stdout.strip()[:120]!r}"
            )
            return ProviderStatus(
                name=PROVIDER_NAME,
                installed=True,
                healthy=False,
                version=None,
                detail=detail,
                capabilities=self.capabilities,
            )
        self._version = match.group(1)
        return ProviderStatus(
            name=PROVIDER_NAME,
            installed=True,
            healthy=True,
            version=self._version,
            detail=f"ok; wire-compat={self.version_compatibility()}",
            capabilities=self.capabilities,
        )

    def _probe_status(self, result: RunResult) -> str:
        if result.error is not None:
            return "spawn_failed"
        if result.timed_out:
            return "timeout"
        if result.returncode == 0 and _VERSION_PATTERN.match(result.stdout.strip()):
            return "ok"
        return "error"

    # ----------------------------------------------------------------- invoke

    def _invoke(
        self,
        tool: str,
        args: Mapping[str, Any],
        *,
        repo_root: str,
        timeout_seconds: float,
        project: str | None = None,
        snapshot_bind: bool = False,
    ) -> _InvokeOutcome:
        """Run one one-shot CLI tool call; never raises.

        The request travels as a JSON ``--args-file`` so no user-controlled
        string ever touches a shell or argv quoting rules. With
        ``snapshot_bind=True`` a successful call additionally fetches
        ``index_status`` (P2) and records the snapshot match with the run.
        """
        if self.version_compatibility() == VERSION_INCOMPATIBLE:
            detail = (
                f"probed version {self._version!r} is wire-incompatible "
                f"with golden-tested {TESTED_CBM_VERSION!r}; refusing to query"
            )
            record = ProviderRunRecord(
                run_id=f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}",
                provider_name=PROVIDER_NAME,
                provider_version=self._version,
                capability=tool,
                status="version_incompatible",
                exit_code=None,
                duration_ms=0,
                arguments_redacted=(tool, repo_root),
                next_action=NEXT_ACTION_VERSION_PIN,
                detail=detail,
            )
            logger.info("cbm %s refused: %s", tool, detail)
            return _InvokeOutcome(
                ok=False, status="version_incompatible",
                error=detail, run=record,
            )
        cwd = os.path.realpath(repo_root)
        args_file: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", prefix="cbm-req-", delete=False,
                encoding="utf-8",
            ) as handle:
                json.dump(dict(args), handle, ensure_ascii=False)
                args_file = handle.name

            argv = [*self.command, "cli", "--json", tool, "--args-file", args_file]
            started = time.monotonic()
            result = run_command(
                argv,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                max_output_bytes=self._max_output_bytes,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
        finally:
            if args_file is not None:
                try:
                    os.unlink(args_file)
                except OSError:  # pragma: no cover - best-effort cleanup
                    pass

        redacted = redact_argv(result.argv)
        outcome = self._shape_outcome(tool, result)
        logger.debug(
            "cbm cli tool=%s exit=%s timed_out=%s truncated=%s duration_ms=%d "
            "status=%s argv=%s",
            tool, result.returncode, result.timed_out, result.truncated,
            duration_ms, outcome.status, list(redacted),
        )
        match: SnapshotMatch | None = None
        if snapshot_bind and outcome.ok and not result.timed_out:
            match = self.snapshot_match(repo_root, project=project)
        run = self._persist_run(
            capability=tool, result=result, duration_ms=duration_ms,
            status=outcome.status, repo_root=cwd, redacted=redacted,
            match=match,
        )
        return _InvokeOutcome(
            ok=outcome.ok, status=outcome.status, payload=outcome.payload,
            error=outcome.error, run=run, match=match,
        )

    def _shape_outcome(self, tool: str, result: RunResult) -> _InvokeOutcome:
        """Classify one completed invocation against the wire contract."""
        if result.error is not None:
            return _InvokeOutcome(False, "spawn_failed", error=result.error)
        if result.timed_out:
            return _InvokeOutcome(
                False, "timeout",
                error=f"{tool} exceeded its time budget and was killed",
            )
        if result.truncated:
            return _InvokeOutcome(
                False, "truncated",
                error=(f"{tool} output exceeded the byte cap; refusing "
                       "partial evidence"),
            )
        # Contract: exit != 0 means failure regardless of stdout content
        # (1 = tool error / isError, 2 = bad arguments).
        if result.returncode not in (0, None):
            status = (
                "bad_arguments" if result.returncode == 2 else "provider_error"
            )
            return _InvokeOutcome(
                False, status,
                error=(f"{tool} exited {result.returncode}; "
                       f"stderr={result.stderr.strip()[:200]!r}"),
            )
        if not result.stdout.strip():
            return _InvokeOutcome(
                False, "empty_stdout",
                error=(f"{tool} produced no stdout "
                       f"(stderr={result.stderr.strip()[:200]!r})"),
            )

        doc_count = _count_json_documents(result.stdout)
        if doc_count < 0:
            return _InvokeOutcome(
                False, "invalid_json",
                error=(f"{tool} stdout is not valid JSON: "
                       f"{result.stdout.strip()[:200]!r}"),
            )
        if doc_count > 1:
            return _InvokeOutcome(
                False, "multiple_json",
                error=(f"{tool} stdout carried {doc_count} JSON documents; "
                       "the wire contract allows exactly one"),
            )

        envelope: Any = json.loads(result.stdout.strip())
        # JSON-RPC bootstrap failure: {"jsonrpc":..,"error":{..}} without content.
        if isinstance(envelope, dict) and "error" in envelope and "content" not in envelope:
            err = envelope.get("error")
            message = (
                err.get("message") if isinstance(err, Mapping) else str(err)
            ) or "JSON-RPC error envelope"
            return _InvokeOutcome(False, "jsonrpc_error", error=str(message))
        if not isinstance(envelope, dict):
            return _InvokeOutcome(
                False, "schema_drift",
                error=(f"{tool} envelope is {type(envelope).__name__}, "
                       "expected object"),
            )

        if envelope.get("isError"):
            return _InvokeOutcome(
                False, "provider_error", error=_extract_message(envelope),
            )

        payload, problem = _extract_payload(envelope)
        if problem is not None:
            return _InvokeOutcome(False, "schema_drift", error=problem)
        return _InvokeOutcome(True, "ok", payload=payload)

    # ------------------------------------------------------------- persistence

    def _persist_run(
        self,
        *,
        capability: str,
        result: RunResult,
        duration_ms: int,
        status: str,
        repo_root: str,
        redacted: tuple[str, ...] | None = None,
        match: SnapshotMatch | None = None,
    ) -> ProviderRunRecord:
        """Build the run record; persist through the ledger when available.

        Without a ledger the record is returned so the caller can persist it.
        Ledger failures are swallowed (logged) — a broken ledger must never
        corrupt or abort an otherwise successful query.
        """
        record = ProviderRunRecord(
            run_id=f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}",
            provider_name=PROVIDER_NAME,
            provider_version=self._version,
            capability=capability,
            status=status,
            exit_code=result.returncode,
            duration_ms=duration_ms,
            arguments_redacted=(
                redacted if redacted is not None else redact_argv(result.argv)
            ),
        )
        if self._db is not None:
            snapshot_hash = (
                match.cbm_head_sha if match is not None and match.bound else None
            )
            try:
                self._db.record_provider_run(
                    PROVIDER_NAME,
                    provider_version=self._version,
                    capability=capability,
                    snapshot_hash=snapshot_hash,
                    project_root=repo_root,
                    position_encoding="UTF-8",
                    arguments_json=json.dumps(list(record.arguments_redacted)),
                    run_id=record.run_id,
                    status=status,
                    exit_code=result.returncode,
                    duration_ms=duration_ms,
                    command_digest=_command_digest(record.arguments_redacted),
                )
                binding_api = getattr(self._db, "record_provider_binding", None)
                if (
                    binding_api is not None and match is not None
                    and match.bound and match.project
                ):
                    binding_api(
                        repo_root,
                        PROVIDER_NAME,
                        match.project,
                        head_sha=match.cbm_head_sha,
                        branch=match.branch,
                    )
            except Exception as exc:  # pragma: no cover - defensive ledger guard
                logger.warning(
                    "cbm ledger persistence failed for run %s: %s",
                    record.run_id, exc,
                )
        return record

    @staticmethod
    def _match_metadata(match: SnapshotMatch | None) -> dict[str, Any]:
        """Metadata block attached to every bound QueryOutcome."""
        if match is None:
            return {"freshness": "UNBOUND", "snapshot_bound": False}
        meta: dict[str, Any] = {
            "freshness": match.freshness,
            "snapshot_bound": match.bound,
            "snapshot": {
                "cbm_head_sha": match.cbm_head_sha,
                "sot_head_sha": match.sot_head_sha,
                "branch": match.branch,
                "detail": match.detail,
                "stale_paths": list(match.stale_paths),
            },
        }
        # Convenience flags for trust_ceiling(): (snapshot_bound, source_changed)
        bound, changed = snapshot_flags(meta)
        meta["source_changed"] = changed
        return meta

    def _query_outcome(self, outcome: _InvokeOutcome) -> QueryOutcome:
        """Shape a raw invoke outcome into an honest public QueryOutcome.

        Provider-side failures (a missing/stale index surfaces as
        provider_error) carry ``next_action`` pointing at the explicit sync
        command; the caller falls back truthfully instead of serving partial
        evidence. When the invocation carried a snapshot binding (P2), the
        freshness verdict travels in ``metadata`` so downstream trust
        ceilings can downgrade stale evidence without re-querying.
        """
        index_related = outcome.status in (
            "provider_error", "jsonrpc_error", "spawn_failed", "bad_arguments",
        )
        metadata = {
            "wire_status": outcome.status,
            "version_compatibility": self.version_compatibility(),
        }
        # Fail-closed: every outcome carries an explicit freshness marker;
        # unbound/unknown defaults cap downstream trust at UNVERIFIABLE.
        metadata.update(self._match_metadata(outcome.match))
        if outcome.status == "version_incompatible":
            next_action = NEXT_ACTION_VERSION_PIN
        elif index_related:
            next_action = NEXT_ACTION_SYNC
        else:
            next_action = None
        return QueryOutcome(
            ok=outcome.ok,
            run=outcome.run,  # type: ignore[arg-type]
            payload=outcome.payload,
            error=outcome.error,
            next_action=next_action,
            metadata=metadata,
        )

    # ------------------------------------------------------------ P1 surface

    # ------------------------------------------------- project resolution

    def _abstained_outcome(
        self,
        capability: str,
        repo_root: str,
        detail: str,
        next_action: str | None,
    ) -> QueryOutcome:
        """Honest no-spawn outcome when a query cannot even be addressed."""
        record = ProviderRunRecord(
            run_id=f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}",
            provider_name=PROVIDER_NAME,
            provider_version=self._version,
            capability=capability,
            status="abstained",
            exit_code=None,
            duration_ms=0,
            arguments_redacted=(capability, repo_root),
            next_action=next_action,
            detail=detail,
        )
        return QueryOutcome(
            ok=False, run=record, payload=None, error=detail,  # type: ignore[arg-type]
            next_action=next_action,
            metadata={"wire_status": "abstained", "freshness": "UNBOUND",
                      "snapshot_bound": False},
        )

    def resolve_project(
        self, repo_root: str
    ) -> tuple[str | None, str | None, str | None]:
        """Resolve the CBM project name covering ``repo_root``.

        Never guesses: exactly one ``list_projects`` entry whose canonicalized
        ``root_path`` equals ``realpath(repo_root)`` wins; zero matches or two
        or more matches abstain with an explicit ``next_action``. Results are
        cached per repo root for the lifetime of this instance.
        """
        target = os.path.realpath(repo_root)
        cached = self._project_cache.get(target)
        if cached is not None:
            return cached
        outcome = self._invoke(
            "list_projects", {},
            repo_root=repo_root,
            timeout_seconds=self._query_timeout,
        )
        if not outcome.ok or not isinstance(outcome.payload, Mapping):
            resolved: tuple[str | None, str | None, str | None] = (
                None,
                f"list_projects failed: {outcome.error}",
                NEXT_ACTION_SYNC,
            )
        else:
            projects = outcome.payload.get("projects")
            projects = projects if isinstance(projects, list) else []
            matches = [
                p["name"] for p in projects
                if isinstance(p, Mapping)
                and isinstance(p.get("name"), str)
                and isinstance(p.get("root_path"), str)
                and os.path.realpath(p["root_path"]) == target
            ]
            if len(matches) == 1:
                resolved = (matches[0], None, None)
            elif len(matches) == 0 and bool(outcome.payload.get("has_more")):
                resolved = (
                    None,
                    "no match in the first list_projects page (has_more=true); "
                    "refusing to guess across pagination",
                    NEXT_ACTION_SYNC,
                )
            elif len(matches) == 0:
                resolved = (
                    None,
                    f"no indexed CBM project covers {target}",
                    NEXT_ACTION_SYNC,
                )
            else:
                resolved = (
                    None,
                    "ambiguous: %d indexed projects share %s (%s); pass project "
                    "explicitly or delete duplicates"
                    % (len(matches), target, ", ".join(sorted(matches))),
                    "disambiguate with `codebase-memory-mcp cli list_projects` "
                    "and pass the project explicitly",
                )
        self._project_cache[target] = resolved
        return resolved

    def _project_for(
        self, repo_root: str, explicit: str | None
    ) -> tuple[str | None, str | None, str | None]:
        """Explicit caller project wins; otherwise resolve via list_projects."""
        if explicit is not None:
            return explicit, None, None
        return self.resolve_project(repo_root)

    # ------------------------------------------------- P2 snapshot binding

    def _index_binding(
        self, repo_root: str, project: str | None
    ) -> SnapshotBinding | None:
        """Fetch one ``index_status`` binding for ``project``; None on failure.

        Deliberately NOT snapshot-bound itself (no recursion) and never
        raises: a failed probe degrades to an unbound match downstream.
        """
        args: dict[str, Any] = {}
        if project is not None:
            args["project"] = project
        try:
            outcome = self._invoke(
                "index_status", args,
                repo_root=repo_root,
                timeout_seconds=self._query_timeout,
            )
        except Exception:  # pragma: no cover - _invoke already never raises
            return None
        if not outcome.ok or not isinstance(outcome.payload, Mapping):
            return None
        payload = outcome.payload
        head = payload.get("head_sha")
        branch = payload.get("branch")
        status = payload.get("status")
        return SnapshotBinding(
            project=project,
            head_sha=head if isinstance(head, str) else None,
            branch=branch if isinstance(branch, str) else None,
            index_status=status if isinstance(status, str) else None,
            captured_at=int(time.time()),
        )

    def snapshot_match(
        self,
        repo_root: str,
        paths: tuple[str, ...] | list[str] = (),
        *,
        project: str | None = None,
    ) -> SnapshotMatch:
        """Compare the CBM index state against the SOT worktree (P2).

        (a) CBM ``head_sha`` (via index_status) vs SOT HEAD SHA; (b) when
        ``paths`` are given, every ``check_index_coverage`` entry must report
        ``hash_status == "fresh"``. Fail-closed: any unprovable step yields
        ``fresh=False`` with a distinguishing ``detail``.
        """
        resolved, problem, _next_action = self._project_for(repo_root, project)
        if resolved is None:
            return SnapshotMatch(
                bound=False, fresh=False,
                detail=f"unbound: {problem}",
            )
        binding = self._index_binding(repo_root, resolved)
        if binding is None or not binding.head_sha:
            return SnapshotMatch(
                bound=False, fresh=False, project=resolved,
                detail="unbound: index_status failed or reported no head_sha",
            )
        sot_head = get_head_sha(os.path.realpath(repo_root))
        if sot_head is None:
            return SnapshotMatch(
                bound=True, fresh=False, project=resolved,
                detail="unknown: SOT HEAD unavailable (not a git repo or no commits)",
                cbm_head_sha=binding.head_sha, branch=binding.branch,
            )
        fresh = binding.head_sha == sot_head
        detail = (
            "head_sha matches"
            if fresh
            else f"stale: cbm head_sha {binding.head_sha[:12]} != "
                 f"sot HEAD {sot_head[:12]}"
        )
        stale_paths: list[str] = []
        if paths:
            cov = self._invoke(
                "check_index_coverage", {"paths": list(paths)},
                repo_root=repo_root,
                timeout_seconds=self._query_timeout,
            )
            entries = (
                cov.payload.get("entries")
                if cov.ok and isinstance(cov.payload, Mapping) else None
            )
            if not isinstance(entries, list):
                fresh = False
                detail += "; unknown: coverage check unavailable"
            else:
                bad = [
                    e.get("path", "?")
                    for e in entries
                    if isinstance(e, Mapping) and e.get("hash_status") != "fresh"
                ]
                if bad:
                    fresh = False
                    stale_paths = [str(p) for p in bad]
                    detail += "; stale coverage: " + ", ".join(stale_paths[:5])
        return SnapshotMatch(
            bound=True, fresh=fresh, detail=detail, project=resolved,
            cbm_head_sha=binding.head_sha, sot_head_sha=sot_head,
            branch=binding.branch, stale_paths=tuple(stale_paths),
        )

    def ensure_index(self, request: IndexRequest) -> ProviderRunRecord:
        """P1 abstention: indexing is NEVER triggered implicitly."""
        record = ProviderRunRecord(
            run_id=f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}",
            provider_name=PROVIDER_NAME,
            provider_version=self._version,
            capability="ensure_index",
            status="abstained",
            exit_code=None,
            duration_ms=0,
            arguments_redacted=(
                "ensure_index", request.repo_root, f"force={request.force}",
            ),
            next_action=NEXT_ACTION_SYNC,
            detail="P1 adapter does not invoke index_repository; sync explicitly.",
        )
        logger.info("cbm ensure_index abstained: %s", NEXT_ACTION_SYNC)
        return record

    def search_symbols(self, request: SymbolRequest) -> QueryOutcome:
        """Free-text symbol search via the ``search_graph`` tool."""
        project, problem, next_action = self._project_for(
            request.repo_root, getattr(request, "project", None)
        )
        if project is None:
            return self._abstained_outcome(
                "search_graph", request.repo_root, problem, next_action
            )
        args: dict[str, Any] = {
            "query": request.query, "limit": request.limit, "project": project,
        }
        if request.language is not None:
            args["language"] = request.language
        outcome = self._invoke(
            "search_graph", args,
            repo_root=request.repo_root,
            timeout_seconds=request.timeout_seconds or self._query_timeout,
            project=project, snapshot_bind=True,
        )
        return self._query_outcome(outcome)

    def trace(self, request: TraceRequest) -> QueryOutcome:
        """Call-path trace via the ``trace_path`` tool."""
        project, problem, next_action = self._project_for(
            request.repo_root, getattr(request, "project", None)
        )
        if project is None:
            return self._abstained_outcome(
                "trace_path", request.repo_root, problem, next_action
            )
        outcome = self._invoke(
            "trace_path",
            {
                # The real wire expects ``function_name`` (ADR-0001 §6).
                "function_name": request.symbol,
                "direction": request.direction,
                "max_depth": request.max_depth,
                "project": project,
            },
            repo_root=request.repo_root,
            timeout_seconds=request.timeout_seconds or self._query_timeout,
            project=project, snapshot_bind=True,
        )
        return self._query_outcome(outcome)

    def _refine_coverage_freshness(self, shaped: QueryOutcome) -> QueryOutcome:
        """Downgrade a bound coverage outcome whose entries are not fresh.

        The check_index_coverage payload is authoritative for path-level
        staleness: any entry without ``hash_status == "fresh"`` marks the
        run STALE even when head_sha still matches (content hashes lag the
        commit pointer after uncommitted edits).
        """
        entries = (
            shaped.payload.get("entries")
            if isinstance(shaped.payload, Mapping) else None
        )
        if not isinstance(entries, list):
            return shaped  # schema drift elsewhere; do not invent staleness
        stale_paths = [
            str(e.get("path", "?"))
            for e in entries
            if isinstance(e, Mapping) and e.get("hash_status") != "fresh"
        ]
        if not stale_paths:
            return shaped
        metadata = dict(shaped.metadata)
        snapshot = dict(metadata.get("snapshot") or {})
        snapshot["stale_paths"] = stale_paths
        snapshot["detail"] = (
            str(snapshot.get("detail", "")) + "; stale coverage: "
            + ", ".join(stale_paths[:5])
        ).strip()
        metadata["snapshot"] = snapshot
        metadata["freshness"] = "STALE"
        metadata["source_changed"] = True
        return QueryOutcome(
            ok=shaped.ok, run=shaped.run, payload=shaped.payload,
            error=shaped.error, next_action=shaped.next_action,
            metadata=metadata,
        )

    def impact(self, request: ImpactRequest) -> QueryOutcome:
        """Blast-radius query via the ``detect_changes`` tool."""
        project, problem, next_action = self._project_for(
            request.repo_root, getattr(request, "project", None)
        )
        if project is None:
            return self._abstained_outcome(
                "detect_changes", request.repo_root, problem, next_action
            )
        outcome = self._invoke(
            "detect_changes", {"path": request.path, "project": project},
            repo_root=request.repo_root,
            timeout_seconds=request.timeout_seconds or self._query_timeout,
            project=project, snapshot_bind=True,
        )
        return self._query_outcome(outcome)

    def architecture(self, request: ArchitectureRequest) -> QueryOutcome:
        """Module structure via the ``get_architecture`` tool."""
        project, problem, next_action = self._project_for(
            request.repo_root, getattr(request, "project", None)
        )
        if project is None:
            return self._abstained_outcome(
                "get_architecture", request.repo_root, problem, next_action
            )
        outcome = self._invoke(
            "get_architecture", {"project": project},
            repo_root=request.repo_root,
            timeout_seconds=request.timeout_seconds or self._query_timeout,
            project=project, snapshot_bind=True,
        )
        return self._query_outcome(outcome)

    def coverage(self, request: CoverageRequest) -> QueryOutcome:
        """Index-coverage check via the ``check_index_coverage`` tool.

        Coverage is itself an index probe: a failure here is exactly the
        missing/stale-index signal, so ``next_action`` is always attached.
        The query payload doubles as the coverage half of the snapshot
        match: any entry not ``hash_status == "fresh"`` downgrades the run
        to STALE (fail-closed).
        """
        args: dict[str, Any] = {"paths": list(request.paths)}
        outcome = self._invoke(
            "check_index_coverage", args,
            repo_root=request.repo_root,
            timeout_seconds=request.timeout_seconds or self._query_timeout,
            snapshot_bind=True,
        )
        shaped = self._query_outcome(outcome)
        if not shaped.ok:
            return QueryOutcome(
                ok=False, run=shaped.run, payload=None, error=shaped.error,
                next_action=NEXT_ACTION_SYNC, metadata=shaped.metadata,
            )
        return self._refine_coverage_freshness(shaped)
