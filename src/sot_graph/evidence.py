"""
sot_graph.evidence — Multi-dimensional Trust Evidence Model (Trust Model v2).

Provides fine-grained, independent dimensions for trust evaluation:
- Freshness: Physical disk synchronization state.
- Relevance: Level of AST symbol / span / token alignment.
- Resolution: Graph edge linkage certainty.
- Completeness: Discovery boundary and presence of unresolved edges.
- Confidence: Calibrated floating score (0.0 .. 1.0).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class FreshnessStatus(str, Enum):
    """Physical file status on disk relative to database index."""
    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


class RelevanceType(str, Enum):
    """Semantic relevance level between query / node and physical disk contents."""
    EXACT_SYMBOL = "EXACT_SYMBOL"
    EXACT_SPAN = "EXACT_SPAN"
    FILE_TOKEN = "FILE_TOKEN"
    NAME_ONLY = "NAME_ONLY"
    UNKNOWN = "UNKNOWN"


class ResolutionStatus(str, Enum):
    """AST / Call graph resolution certainty."""
    EXACT = "EXACT"
    INFERRED = "INFERRED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


class CompletenessStatus(str, Enum):
    """Discovery completeness of usages, implementations, or graph neighborhood."""
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TrustEvidence:
    """Comprehensive multi-dimensional trust evidence for search hits and graph nodes."""
    freshness: FreshnessStatus
    relevance: RelevanceType
    resolution: ResolutionStatus
    completeness: CompletenessStatus
    confidence: float
    provenance: str = "trust_verifier:v2"
    file_path: str = ""
    file_hash: Optional[str] = None
    coverage: Optional[float] = None
    resolved_count: int = 0
    unresolved_count: int = 0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_legacy_verdict(self) -> str:
        """Convert multi-dimensional evidence to legacy verdict string for backward compatibility."""
        if self.details.get("nopath"):
            return "NOPATH"
        if self.details.get("removed"):
            return "REMOVED"
        if self.details.get("rehomed"):
            return "REBUILT"
        if self.freshness in (FreshnessStatus.MISSING, FreshnessStatus.STALE):
            return "STALE"
        if self.freshness == FreshnessStatus.UNKNOWN:
            return "WEAK"
        if self.freshness == FreshnessStatus.FRESH:
            if self.relevance in (RelevanceType.EXACT_SYMBOL, RelevanceType.EXACT_SPAN):
                return "STRONG"
            if self.confidence >= 0.5:
                return "STRONG"
            return "WEAK"
        return "WEAK"
    @property
    def is_grounded(self) -> bool:
        """Returns True if the evidence reflects a fresh, resolved, and verified physical asset."""
        return (
            self.freshness == FreshnessStatus.FRESH
            and self.confidence >= 0.5
            and self.resolution in (ResolutionStatus.EXACT, ResolutionStatus.INFERRED)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize evidence to dictionary."""
        d = asdict(self)
        d["legacy_verdict"] = self.to_legacy_verdict()
        return d
