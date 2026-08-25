"""Provider contract for the Verified Code Evidence & Change-Safety Layer.

Defines the normalized assertion/evidence vocabulary shared by every extractor
provider (sot-builtin, scip importer, federated CLI adapters). Purely additive:
no existing module imports this yet; adapters in later phases consume it.

Field rules (contract):
- Unknown values MUST be ``None`` or ``"unknown"`` — never fabricated defaults.
- Every evidence envelope binds to exactly one snapshot id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

ENVELOPE_SCHEMA_VERSION = 1


class Capability(str, Enum):
    """Capability advertised by a provider."""

    SYMBOLS = "symbols"
    CALLGRAPH = "callgraph"
    IMPACT = "impact"
    TRACE = "trace"
    PDG = "pdg"
    TAINT = "taint"
    ARCHITECTURE = "architecture"
    BROAD_LANGUAGE_DISCOVERY = "broad-language-discovery"
    REPO_MAP = "repo-map"
    SOURCE_VERIFICATION = "source-verification"


class IntegrationMode(str, Enum):
    """How SOT-Graph talks to the provider (priority order for rollout)."""

    EMBEDDED = "embedded"
    IMPORT = "import"
    FEDERATED_CLI = "federated-cli"
    FEDERATED_MCP = "federated-mcp"


@dataclass(frozen=True)
class ProviderIdentity:
    """Who produced an assertion."""

    name: str
    version: str | None
    mode: IntegrationMode
    capability: Capability


@dataclass(frozen=True)
class SnapshotBinding:
    """Which source snapshot an assertion was captured against.

    Mirrors the ``snapshots`` table (schema v6). ``snapshot_id=None`` means
    UNBOUND: the assertion may not participate in PROVEN decisions.
    """

    repository_root: str
    commit_sha: str | None
    worktree_fingerprint: str | None
    manifest_digest: str | None
    dirty: bool
    snapshot_id: str | None


@dataclass(frozen=True)
class Subject:
    """The code entity an assertion is about."""

    kind: str
    qualified_name: str
    path: str
    start_line: int | None
    end_line: int | None
    content_hash: str | None


@dataclass(frozen=True)
class Assertion:
    """A single provider claim about a relation between subjects."""

    relation: str
    target: str
    provider_confidence: float | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationResult:
    """SOT-Graph verification outcome for one assertion."""

    status: str  # SUPPORTED | HEURISTIC | AMBIGUOUS | STALE | UNVERIFIABLE
    source_span_verified: bool
    snapshot_verified: bool
    conflicts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Normalized evidence record every adapter must emit (guide §5)."""

    provider: ProviderIdentity
    snapshot: SnapshotBinding
    subject: Subject
    assertion: Assertion
    verification: VerificationResult
    schema_version: int = ENVELOPE_SCHEMA_VERSION

    def validate(self) -> list[str]:
        """Return contract violations; empty list means valid."""
        problems: list[str] = []
        if self.snapshot.snapshot_id is None and self.verification.status == "SUPPORTED":
            problems.append("UNBOUND snapshot cannot yield SUPPORTED")
        if self.provider.mode is IntegrationMode.FEDERATED_CLI and self.provider.version is None:
            problems.append("federated-cli provider must report detected version or 'unknown'")
        if self.assertion.provider_confidence is not None and not (
            0.0 <= self.assertion.provider_confidence <= 1.0
        ):
            problems.append("provider_confidence outside [0,1]")
        if self.subject.path.startswith("/"):
            problems.append("subject.path must be repo-relative, not absolute")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider": {
                "name": self.provider.name,
                "version": self.provider.version,
                "mode": self.provider.mode.value,
                "capability": self.provider.capability.value,
            },
            "snapshot": {
                "repository_root": self.snapshot.repository_root,
                "commit": self.snapshot.commit_sha,
                "worktree_fingerprint": self.snapshot.worktree_fingerprint,
                "manifest_digest": self.snapshot.manifest_digest,
                "dirty": self.snapshot.dirty,
                "snapshot_id": self.snapshot.snapshot_id,
            },
            "subject": {
                "kind": self.subject.kind,
                "qualified_name": self.subject.qualified_name,
                "path": self.subject.path,
                "start_line": self.subject.start_line,
                "end_line": self.subject.end_line,
                "content_hash": self.subject.content_hash,
            },
            "assertion": {
                "relation": self.assertion.relation,
                "target": self.assertion.target,
                "provider_confidence": self.assertion.provider_confidence,
                "metadata": self.assertion.metadata,
            },
            "verification": {
                "status": self.verification.status,
                "source_span_verified": self.verification.source_span_verified,
                "snapshot_verified": self.verification.snapshot_verified,
                "conflicts": self.verification.conflicts,
            },
        }
