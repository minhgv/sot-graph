from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class NodeExpectation:
    id: str
    kind: str
    label: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None


@dataclass
class EdgeExpectation:
    source_file: str
    source_symbol: str
    target_file: str
    target_symbol: str
    relation: str = "calls"
    target_kind: Optional[str] = None
    is_forbidden: bool = False
    is_allowed_pending: bool = False
    reason: Optional[str] = None

    @property
    def canonical_id(self) -> str:
        return f"{self.source_file}::{self.source_symbol}::{self.relation}::{self.target_file}::{self.target_symbol}"


@dataclass
class ExactSpanExpectation:
    file_path: str
    symbol: str
    query_line: int
    expected_exact_span: bool
    description: str


@dataclass
class ScipAttributionExpectation:
    symbol: str
    file_path: str
    occurrence_line: int
    expected_enclosing_symbol: Optional[str]
    allowed_providers: List[str]
    forbidden_providers: List[str] = field(default_factory=list)


@dataclass
class DiffImpactExpectation:
    revision_target: str
    expected_changed_files: List[str]
    expected_impacted_symbols: List[str]
    forbidden_files: List[str] = field(default_factory=list)
    forbidden_symbols: List[str] = field(default_factory=list)


@dataclass
class Manifest:
    manifest_version: str = "1.0.0"
    corpus_id: str = "sot-graph-evaluation-corpus-v1"
    expected_nodes: List[NodeExpectation] = field(default_factory=list)
    expected_confirmed_edges: List[EdgeExpectation] = field(default_factory=list)
    allowed_pending_edges: List[EdgeExpectation] = field(default_factory=list)
    forbidden_edges: List[EdgeExpectation] = field(default_factory=list)
    exact_span_expectations: List[ExactSpanExpectation] = field(default_factory=list)
    scip_expectations: List[ScipAttributionExpectation] = field(default_factory=list)
    diff_expectations: List[DiffImpactExpectation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
