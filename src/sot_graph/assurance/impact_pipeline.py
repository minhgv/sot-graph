"""sot_graph.assurance.impact_pipeline — canonical impact-claim flow (SG-105).

ONE pipeline from a validated request to a digest-stable post-change
receipt. CLI/MCP surfaces migrate onto this module in a later part; it
stays presentation-free (no stdout, no argparse).

Flow:

    :class:`ImpactClaimRequest`.normalize()
      → pre-change worktree snapshot, content-bound to the diff's files
        (same capture the CLI diff-impact command performs before any
        auto-reconcile mutates the index)
      → optional auto-reconcile (same ``Reconciler`` call, failure
        recorded on the receipt instead of printed)
      → :func:`sot_graph.assurance.receipts.diff_impact_receipt` with the
        captured pre-snapshot (the receipt constructs/invokes the
        diff-impact engine exactly as the receipts path always has, so
        there is exactly ONE engine per claim)
      → ``request`` + ``projection`` augmentation (SG-104 projection
        vocabulary) and digest recompute over the augmented payload

:class:`ReceiptStore` persists the content-addressed canonical form of a
receipt under ``<repo_root>/.sot/receipts/``. No retention/GC in this
phase: the store grows monotonically and cleanup policy belongs to a
later part.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List

__all__ = [
    "IMPACT_REQUEST_SCHEMA_VERSION",
    "PROJECTION_COLLECTION_KEYS",
    "ImpactClaimRequest",
    "CollectionError",
    "ReceiptIntegrityError",
    "ReceiptStore",
    "engine_view",
    "run_impact_claim",
]

IMPACT_REQUEST_SCHEMA_VERSION = "impact-request/1"

#: Payload collections the projection block enumerates. Same vocabulary
#: as the SG-104 transport_truncation entries: one record per collection
#: with ``{key, enumerated_count, returned_count, truncated}`` plus a
#: ``next_cursor`` (always null at receipt depth — receipts are whole).
PROJECTION_COLLECTION_KEYS = (
    "changed_files",
    "direct_nodes",
    "caller_impacts",
    "test_impacts",
    "api_impacts",
    "tests_to_run",
)

_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


class CollectionError(Exception):
    """A swallowed evidence-collection failure — recorded, never raised.

    Receipts must not crash on storage faults, but silently treating a
    failed query as "empty evidence" would be fail-open. Each swallow
    site constructs one of these and records ``str(error)`` (machine
    readable: ``collection_error:<source>:<detail>``) in the receipt's
    warnings; the canonical state machine then degrades the verdict to
    UNVERIFIABLE via ``AssuranceFacts.collection_error``.
    """

    def __init__(self, source: str, detail: str) -> None:
        super().__init__(f"collection_error:{source}:{detail}")
        self.source = source
        self.detail = detail


class ReceiptIntegrityError(Exception):
    """Stored receipt bytes no longer match their content address."""


@dataclass(frozen=True)
class ImpactClaimRequest:
    """Validated input for :func:`run_impact_claim`.

    ``normalize()`` enforces the engine's contract BEFORE any git/db
    work: non-empty target, depth 1..5, and the diff-scope precedence the
    engine applies today — ``GitDeltaExtractor.extract_diff`` checks
    ``--staged`` first, so when both scopes are requested the staged diff
    wins and ``working_tree`` is coerced to False (mirrored, not invented).
    """

    schema_version: str = IMPACT_REQUEST_SCHEMA_VERSION
    target: str = "HEAD"
    depth: int = 2
    staged: bool = False
    working_tree: bool = False
    auto_reconcile: bool = False

    def normalize(self) -> "ImpactClaimRequest":
        """Validate and canonicalize; pure (no I/O)."""
        target = str(self.target or "").strip()
        if not target:
            raise ValueError("ImpactClaimRequest.target must not be empty")
        try:
            depth = int(self.depth)
        except (TypeError, ValueError):
            raise ValueError(
                f"ImpactClaimRequest.depth must be an int, got {self.depth!r}"
            )
        if not 1 <= depth <= 5:
            raise ValueError(
                f"ImpactClaimRequest.depth must be within 1..5, got {depth}"
            )
        staged = bool(self.staged)
        working_tree = bool(self.working_tree)
        if staged and working_tree:
            # Engine parity: extract_diff appends --staged first and only
            # falls through to the working-tree diff when staged is unset.
            working_tree = False
        return replace(
            self,
            target=target,
            depth=depth,
            staged=staged,
            working_tree=working_tree,
        )


def run_impact_claim(
    request: ImpactClaimRequest,
    db: Any,
    repo_root: str,
) -> Dict[str, Any]:
    """The single canonical impact-claim flow (SG-105).

    Validate → capture the pre-change snapshot → optionally auto-reconcile
    → post-change receipt (engine + snapshot + ledger + decision) →
    augment with ``request``/``projection`` blocks → recompute the digest
    so it covers the augmented payload.
    """
    from sot_graph.assurance.receipts import diff_impact_receipt, receipt_digest
    from sot_graph.diff_impact import GitDeltaExtractor
    from sot_graph.reconciler import Reconciler
    from sot_graph.snapshot import capture_worktree_snapshot

    if not isinstance(request, ImpactClaimRequest):
        raise TypeError("run_impact_claim expects an ImpactClaimRequest")
    request = request.normalize()

    # P1.g parity (cli cmd_diff_impact): cite the diff's changed files so
    # the PRE-change snapshot binds their content, and capture it BEFORE
    # any auto-reconcile mutates the index.
    try:
        delta_files = list(
            GitDeltaExtractor(repo_root)
            .extract_diff(
                request.target,
                staged=request.staged,
                working_tree=request.working_tree,
            )[0]
            .keys()
        )
    except Exception:  # pragma: no cover - best-effort content binding
        delta_files = []
    pre_snapshot = capture_worktree_snapshot(
        repo_root,
        role="pre_change",
        cited_paths=delta_files[:200] or None,
    )

    reconcile_warnings: List[str] = []
    if request.auto_reconcile:
        try:
            Reconciler(db, repo_root).reconcile()
        except Exception as exc:  # noqa: BLE001 - degrade like the CLI
            reconcile_warnings.append(
                f"auto_reconcile_failed:{type(exc).__name__}: {exc}"
            )

    # Exactly ONE engine per claim: the receipt constructs/invokes the
    # diff-impact engine (repo_root, db) exactly as the receipts path
    # always has; the pipeline never builds a second one.
    receipt = diff_impact_receipt(
        db,
        repo_root,
        target=request.target,
        depth=request.depth,
        staged=request.staged,
        working_tree=request.working_tree,
        pre_snapshot=pre_snapshot.as_dict(),
    )

    receipt["request"] = {
        "schema_version": request.schema_version,
        "target": request.target,
        "staged": request.staged,
        "working_tree": request.working_tree,
        "depth": request.depth,
        "auto_reconcile": request.auto_reconcile,
    }
    receipt["projection"] = build_projection(receipt)
    if reconcile_warnings:
        receipt["warnings"] = list(receipt.get("warnings") or []) + reconcile_warnings
    # The digest must cover the augmented payload, not just the base
    # receipt: one content address per evidenced state + request.
    receipt["digest"] = receipt_digest(
        {k: v for k, v in receipt.items() if k != "digest"}
    )
    return receipt


def build_projection(receipt: Dict[str, Any]) -> Dict[str, Any]:
    """SG-104 projection vocabulary over the receipt's own collections."""
    collections: List[Dict[str, Any]] = []
    for key in PROJECTION_COLLECTION_KEYS:
        items = receipt.get(key)
        enumerated = len(items) if isinstance(items, (list, tuple)) else 0
        collections.append(
            {
                "key": key,
                "enumerated_count": enumerated,
                "returned_count": enumerated,
                "truncated": False,
            }
        )
    return {"collections": collections, "next_cursor": None}


def engine_view(receipt: Dict[str, Any]) -> Any:
    """Duck-typed ``DiffImpactResult`` stand-in built from receipt fields.

    The markdown/github renderers read engine attributes off the result
    (getattr-guarded); CLI and MCP both project the canonical receipt
    through this view so one executor renders identically on every
    surface. Presentation-free: pure dict → namespace mapping.
    """
    from types import SimpleNamespace

    def _ns(value: Any) -> Any:
        if isinstance(value, dict):
            return SimpleNamespace(**{k: _ns(v) for k, v in value.items()})
        if isinstance(value, list):
            return [_ns(v) for v in value]
        return value

    identity = receipt.get("diff_identity") or {}
    return SimpleNamespace(
        summary=receipt.get("summary") or {},
        target=identity.get("target") or "",
        changed_files=receipt.get("changed_files") or [],
        direct_nodes=_ns(receipt.get("direct_nodes") or []),
        caller_impacts=_ns(receipt.get("caller_impacts") or []),
        api_impacts=_ns(receipt.get("api_impacts") or []),
        test_impacts=_ns(receipt.get("test_impacts") or []),
        assurance=receipt.get("assurance"),
        assurance_facts=receipt.get("assurance_facts"),
        changed_files_truncated=bool(receipt.get("changed_files_truncated", False)),
        changed_files_total=receipt.get("changed_files_total"),
        post_change_snapshot=receipt.get("post_change_snapshot"),
    )


class ReceiptStore:
    """Content-addressed, immutable receipt store.

    Files hold the canonical digest form of a receipt (volatile-stripped,
    ``digest`` key excluded — byte-identical to what :func:`receipt_digest`
    hashes), named ``<digest>.json``. Writes are write-if-absent and never
    overwrite: an existing file whose bytes differ at the same address is
    a hash-collision bug and raises :class:`ReceiptIntegrityError`. Reads
    re-verify the digest over the loaded payload, so tampering is detected
    (and volatile wall-clock fields are simply absent — they are not part
    of the address).

    No retention/GC this phase: receipts accumulate; cleanup is the
    caller's policy.
    """

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _canonical_bytes(receipt: Dict[str, Any]) -> bytes:
        from sot_graph.assurance.receipts import _strip_volatile

        payload = _strip_volatile(
            {k: v for k, v in receipt.items() if k != "digest"}
        )
        # Exactly the bytes receipt_digest hashes (same dump args), so a
        # stored file's bytes can never disagree with its filename.
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8", errors="surrogateescape")

    def put(self, receipt: Dict[str, Any]) -> str:
        """Store one receipt; returns its content-address digest."""
        from sot_graph.assurance.receipts import receipt_digest

        digest = receipt_digest(
            {k: v for k, v in receipt.items() if k != "digest"}
        )
        path = self.directory / f"{digest}.json"
        canonical = self._canonical_bytes(receipt)
        if path.exists():
            if path.read_bytes() != canonical:
                raise ReceiptIntegrityError(
                    f"hash collision at {digest}: existing bytes differ; "
                    "refusing to overwrite"
                )
            return digest  # immutable: same content, no-op
        path.write_bytes(canonical)
        return digest

    def get(self, digest: str) -> Dict[str, Any]:
        """Load one receipt, re-verifying its content address."""
        from sot_graph.assurance.receipts import receipt_digest

        if not _DIGEST_RE.fullmatch(str(digest)):
            raise ReceiptIntegrityError(f"malformed receipt digest: {digest!r}")
        path = self.directory / f"{digest}.json"
        if not path.is_file():
            raise KeyError(digest)
        payload = json.loads(
            path.read_bytes().decode("utf-8", errors="surrogateescape")
        )
        recomputed = receipt_digest(
            {k: v for k, v in payload.items() if k != "digest"}
        )
        if recomputed != digest:
            raise ReceiptIntegrityError(
                f"receipt {digest} failed integrity check: "
                f"recomputed digest is {recomputed}"
            )
        return payload

    def list_digests(self) -> List[str]:
        """All content addresses currently in the store, sorted."""
        return sorted(
            p.stem
            for p in self.directory.glob("*.json")
            if _DIGEST_RE.fullmatch(p.stem)
        )
