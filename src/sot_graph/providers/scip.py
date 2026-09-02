"""sot_graph.providers.scip - SCIP EvidenceProvider adapter (Federated SCIP Provider).

P3.4: integrates SCIP index as a first-class EvidenceProvider in the federation
orchestration pipeline with honest status, query routing, and snapshot binding.
Honest relation mapping: SCIP definitions map to 'defines', occurrences to 'references'.
No fake callgraph/trace advertising without verified call edges.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sot_graph.importer.scip import (
    ROLE_DEFINITION,
    parse_scip_json,
    parse_scip_protobuf,
    parse_scip_symbol,
)
from sot_graph.providers.base import (
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

PROVIDER_NAME = "scip"
SCIP_DEFAULT_ARTIFACTS = ("index.scip", os.path.join(".scip", "index.scip"))


class ScipProvider:
    """EvidenceProvider backed by pre-generated SCIP index files."""

    name: str = PROVIDER_NAME
    provider_version: str = "1.0.0"
    # Explicit honest capabilities: NO trace/callgraph without verified call graph
    capabilities: Tuple[str, ...] = ("symbols", "usages", "references", "source-verification")

    def __init__(self, index_path: Optional[str] = None):
        self.index_path = index_path

    def _find_index_file(self, repo_root: str) -> Optional[str]:
        if self.index_path:
            p = os.path.join(repo_root, self.index_path) if not os.path.isabs(self.index_path) else self.index_path
            return p if os.path.isfile(p) else None
        for candidate in SCIP_DEFAULT_ARTIFACTS:
            p = os.path.join(repo_root, candidate)
            if os.path.isfile(p):
                return p
        return None

    def _parse_index(self, file_path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        with open(file_path, "rb") as f:
            data = f.read()
        if not data:
            return {}, []
        # Auto-detect JSON vs Protobuf binary
        stripped = data.strip()
        if file_path.endswith(".json") or stripped.startswith(b"{") or stripped.startswith(b"["):
            parsed = parse_scip_json(data.decode("utf-8", errors="replace"))
        else:
            parsed = parse_scip_protobuf(data)
        metadata = parsed.get("metadata", {})
        documents = parsed.get("documents", [])
        return metadata, documents

    def probe(self, repo_root: str) -> ProviderStatus:
        index_file = self._find_index_file(repo_root)
        if not index_file:
            return ProviderStatus(
                name=self.name,
                installed=False,
                healthy=False,
                version=self.provider_version,
                detail=f"no SCIP index file found in {repo_root} (expected index.scip)",
                capabilities=self.capabilities,
            )
        try:
            metadata, docs = self._parse_index(index_file)
            doc_count = len(docs)
            ver = metadata.get("version", self.provider_version)
            return ProviderStatus(
                name=self.name,
                installed=True,
                healthy=True,
                version=str(ver),
                detail=f"SCIP index loaded ({doc_count} documents)",
                capabilities=self.capabilities,
            )
        except Exception as exc:
            return ProviderStatus(
                name=self.name,
                installed=True,
                healthy=False,
                version=self.provider_version,
                detail=f"error reading SCIP index: {exc}",
                capabilities=self.capabilities,
            )

    def ensure_index(self, request: IndexRequest) -> ProviderRunRecord:
        index_file = self._find_index_file(request.repo_root)
        return ProviderRunRecord(
            run_id=f"scip_ensure_{uuid.uuid4().hex[:8]}",
            provider_name=self.name,
            provider_version=self.provider_version,
            capability="ensure_index",
            status="ok" if index_file else "abstained",
            exit_code=0 if index_file else 1,
            duration_ms=0,
            detail=f"index file: {index_file}" if index_file else "missing index file",
        )

    def search_symbols(self, request: SymbolRequest) -> QueryOutcome:
        start_t = time.monotonic()
        index_file = self._find_index_file(request.repo_root)
        if not index_file:
            run = ProviderRunRecord(
                run_id=f"scip_search_{uuid.uuid4().hex[:8]}",
                provider_name=self.name,
                provider_version=self.provider_version,
                capability="symbols",
                status="abstained",
                exit_code=1,
                duration_ms=0,
                next_action="generate index.scip using scip-python/scip-typescript/scip-java",
            )
            return QueryOutcome(ok=False, run=run, error="SCIP index file not found")

        try:
            _metadata, documents = self._parse_index(index_file)
            results: List[Dict[str, Any]] = []
            query_lower = request.query.lower()

            for doc in documents:
                rel_path = doc.get("relative_path", "")
                for sym in doc.get("symbols", []):
                    raw_sym = sym.get("symbol", "")
                    parsed = parse_scip_symbol(raw_sym)
                    bare_name = parsed.get("bare_name") or raw_sym
                    fqn = parsed.get("fqn") or bare_name
                    if query_lower in bare_name.lower() or query_lower in fqn.lower() or query_lower in raw_sym.lower():
                        results.append({
                            "name": bare_name,
                            "qualified_name": fqn,
                            "symbol": raw_sym,
                            "path": rel_path,
                            "kind": sym.get("kind", "symbol"),
                            "is_definition": True,
                            "documentation": sym.get("documentation", []),
                        })
                        if len(results) >= request.limit:
                            break
                if len(results) >= request.limit:
                    break

            duration_ms = int((time.monotonic() - start_t) * 1000)
            run = ProviderRunRecord(
                run_id=f"scip_search_{uuid.uuid4().hex[:8]}",
                provider_name=self.name,
                provider_version=self.provider_version,
                capability="symbols",
                status="ok",
                exit_code=0,
                duration_ms=duration_ms,
            )
            return QueryOutcome(ok=True, run=run, payload={"symbols": results, "count": len(results)})
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_t) * 1000)
            run = ProviderRunRecord(
                run_id=f"scip_search_{uuid.uuid4().hex[:8]}",
                provider_name=self.name,
                provider_version=self.provider_version,
                capability="symbols",
                status="error",
                exit_code=1,
                duration_ms=duration_ms,
                detail=str(exc),
            )
            return QueryOutcome(ok=False, run=run, error=str(exc))

    def usages(self, request: SymbolRequest) -> QueryOutcome:
        """Find occurrences/references of a symbol in SCIP documents."""
        start_t = time.monotonic()
        index_file = self._find_index_file(request.repo_root)
        if not index_file:
            run = ProviderRunRecord(
                run_id=f"scip_usages_{uuid.uuid4().hex[:8]}",
                provider_name=self.name,
                provider_version=self.provider_version,
                capability="usages",
                status="abstained",
                exit_code=1,
                duration_ms=0,
                next_action="generate index.scip",
            )
            return QueryOutcome(ok=False, run=run, error="SCIP index file not found")

        try:
            _, documents = self._parse_index(index_file)
            results: List[Dict[str, Any]] = []
            query_lower = request.query.lower()

            for doc in documents:
                rel_path = doc.get("relative_path", "")
                for occ in doc.get("occurrences", []):
                    raw_sym = occ.get("symbol", "")
                    parsed = parse_scip_symbol(raw_sym)
                    bare_name = parsed.get("bare_name") or raw_sym
                    fqn = parsed.get("fqn") or bare_name
                    if query_lower in bare_name.lower() or query_lower in fqn.lower() or query_lower in raw_sym.lower():
                        roles = occ.get("symbol_roles", 0)
                        is_def = bool(roles & ROLE_DEFINITION)
                        rng = occ.get("range", [])
                        span = None
                        if rng and len(rng) >= 3:
                            # [start_line, start_col, end_line, end_col] or [start_line, start_col, end_col]
                            if len(rng) == 4:
                                span = {"start_line": rng[0] + 1, "end_line": rng[2] + 1}
                            else:
                                span = {"start_line": rng[0] + 1, "end_line": rng[0] + 1}
                        elif rng and len(rng) >= 1:
                            span = {"start_line": rng[0] + 1, "end_line": rng[0] + 1}

                        results.append({
                            "name": bare_name,
                            "qualified_name": fqn,
                            "symbol": raw_sym,
                            "path": rel_path,
                            "span": span,
                            "is_definition": is_def,
                            "relation": "defines" if is_def else "references",
                            "syntax_kind": occ.get("syntax_kind", 0),
                        })
                        if len(results) >= request.limit:
                            break
                if len(results) >= request.limit:
                    break

            duration_ms = int((time.monotonic() - start_t) * 1000)
            run = ProviderRunRecord(
                run_id=f"scip_usages_{uuid.uuid4().hex[:8]}",
                provider_name=self.name,
                provider_version=self.provider_version,
                capability="usages",
                status="ok",
                exit_code=0,
                duration_ms=duration_ms,
            )
            return QueryOutcome(ok=True, run=run, payload={"symbols": results, "count": len(results)})
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_t) * 1000)
            run = ProviderRunRecord(
                run_id=f"scip_usages_{uuid.uuid4().hex[:8]}",
                provider_name=self.name,
                provider_version=self.provider_version,
                capability="usages",
                status="error",
                exit_code=1,
                duration_ms=duration_ms,
                detail=str(exc),
            )
            return QueryOutcome(ok=False, run=run, error=str(exc))

    def trace(self, _request: TraceRequest) -> QueryOutcome:
        run = ProviderRunRecord(
            run_id=f"scip_trace_{uuid.uuid4().hex[:8]}",
            provider_name=self.name,
            provider_version=self.provider_version,
            capability="trace",
            status="abstained",
            exit_code=0,
            duration_ms=0,
            detail="scip does not calculate dynamic trace/call graph natively",
        )
        return QueryOutcome(ok=False, run=run, error="unsupported capability")

    def impact(self, _request: ImpactRequest) -> QueryOutcome:
        run = ProviderRunRecord(
            run_id=f"scip_impact_{uuid.uuid4().hex[:8]}",
            provider_name=self.name,
            provider_version=self.provider_version,
            capability="impact",
            status="abstained",
            exit_code=0,
            duration_ms=0,
            detail="scip does not calculate dynamic impact natively",
        )
        return QueryOutcome(ok=False, run=run, error="unsupported capability")

    def architecture(self, _request: ArchitectureRequest) -> QueryOutcome:
        run = ProviderRunRecord(
            run_id=f"scip_arch_{uuid.uuid4().hex[:8]}",
            provider_name=self.name,
            provider_version=self.provider_version,
            capability="architecture",
            status="abstained",
            exit_code=0,
            duration_ms=0,
            detail="scip does not calculate architecture clusters natively",
        )
        return QueryOutcome(ok=False, run=run, error="unsupported capability")

    def coverage(self, _request: CoverageRequest) -> QueryOutcome:
        start_t = time.monotonic()
        index_file = self._find_index_file(_request.repo_root)
        if not index_file:
            run = ProviderRunRecord(
                run_id=f"scip_cov_{uuid.uuid4().hex[:8]}",
                provider_name=self.name,
                provider_version=self.provider_version,
                capability="coverage",
                status="abstained",
                exit_code=1,
                duration_ms=0,
            )
            return QueryOutcome(ok=False, run=run, error="SCIP index file not found")
        try:
            _, documents = self._parse_index(index_file)
            doc_paths = [doc.get("relative_path", "") for doc in documents]
            duration_ms = int((time.monotonic() - start_t) * 1000)
            run = ProviderRunRecord(
                run_id=f"scip_cov_{uuid.uuid4().hex[:8]}",
                provider_name=self.name,
                provider_version=self.provider_version,
                capability="coverage",
                status="ok",
                exit_code=0,
                duration_ms=duration_ms,
            )
            return QueryOutcome(ok=True, run=run, payload={"covered_paths": doc_paths, "count": len(doc_paths)})
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_t) * 1000)
            run = ProviderRunRecord(
                run_id=f"scip_cov_{uuid.uuid4().hex[:8]}",
                provider_name=self.name,
                provider_version=self.provider_version,
                capability="coverage",
                status="error",
                exit_code=1,
                duration_ms=duration_ms,
                detail=str(exc),
            )
            return QueryOutcome(ok=False, run=run, error=str(exc))
