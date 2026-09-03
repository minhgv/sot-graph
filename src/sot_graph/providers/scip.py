"""sot_graph.providers.scip - SCIP EvidenceProvider adapter (Federated SCIP Provider).

P3.4: integrates SCIP index as a first-class EvidenceProvider in the federation
orchestration pipeline with honest status, query routing, and snapshot binding.
Honest relation mapping: SCIP definitions map to 'defines', occurrences to 'references'.
No fake callgraph/trace advertising without verified call edges.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from sot_graph.importer.scip import (
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
SCIP_DEFAULT_ARTIFACTS = (
    "index.scip",
    "index.scip.json",
    "scip.json",
    os.path.join(".scip", "index.scip"),
    os.path.join(".scip", "index.scip.json"),
)

SCIP_KIND_MAP: Dict[int, str] = {
    0: "unknown", 1: "file", 2: "module", 3: "namespace", 4: "package",
    5: "class", 6: "method", 7: "property", 8: "field", 9: "constructor",
    10: "enum", 11: "interface", 12: "function", 13: "variable", 14: "constant",
    15: "string", 16: "number", 17: "boolean", 18: "array", 19: "object",
    20: "key", 21: "null", 22: "enum_member", 23: "struct", 24: "event",
    25: "operator", 26: "type_parameter", 27: "type_alias", 28: "macro",
    29: "trait",
}


def _normalize_scip_kind(raw_kind: Any) -> str:
    if isinstance(raw_kind, int):
        return SCIP_KIND_MAP.get(raw_kind, "symbol")
    if isinstance(raw_kind, str) and raw_kind:
        return raw_kind.lower()
    return "symbol"


class ScipProvider:
    """EvidenceProvider backed by pre-generated SCIP index files."""

    name: str = PROVIDER_NAME
    provider_version: str = "1.0.0"
    capabilities: Tuple[str, ...] = ("symbols", "usages", "references", "source-verification")

    def __init__(self, index_path: Optional[str] = None, db: Optional[Any] = None):
        self.index_path = index_path
        self.db = db

    def _persist_outcome(
        self,
        capability: str,
        status: str,
        exit_code: int,
        duration_ms: int,
        repo_root: str,
        results: List[Dict[str, Any]],
        error: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> ProviderRunRecord:
        run_id = f"scip_{capability}_{uuid.uuid4().hex[:8]}"
        record = ProviderRunRecord(
            run_id=run_id,
            provider_name=self.name,
            provider_version=self.provider_version,
            capability=capability,
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            detail=error or "",
        )
        if self.db is not None:
            cmd_payload = json.dumps(arguments or {"capability": capability}, sort_keys=True)
            cmd_digest = hashlib.sha256(f"{self.name}:{capability}:{cmd_payload}".encode("utf-8")).hexdigest()
            run_kwargs = {
                "run_id": run_id,
                "provider_name": self.name,
                "provider_version": self.provider_version,
                "capability": capability,
                "status": status,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "project_root": repo_root,
                "position_encoding": "UTF-8",
                "arguments_json": cmd_payload,
                "command_digest": cmd_digest,
            }
            evidence_items = []
            if status == "ok":
                for sym in results:
                    span = sym.get("span") or {}
                    evidence_items.append({
                        "path": sym.get("path") or "",
                        "symbol": sym.get("qualified_name") or sym.get("name") or "",
                        "target_symbol": None,
                        "relation": "definition" if sym.get("is_definition") else "reference",
                        "start_line": span.get("start_line"),
                        "line_start": span.get("start_line"),
                        "start_column": span.get("start_column"),
                        "col_start": span.get("start_column"),
                        "end_line": span.get("end_line"),
                        "line_end": span.get("end_line"),
                        "end_column": span.get("end_column"),
                        "col_end": span.get("end_column"),
                        "confidence": 1.0,
                        "metadata_json": {
                            "kind": sym.get("kind"),
                            "symbol": sym.get("symbol"),
                        },
                    })
            atomic = getattr(self.db, "record_provider_outcome", None)
            try:
                if atomic is not None:
                    atomic(run_kwargs, None, evidence_items)
                else:
                    if hasattr(self.db, "record_provider_run"):
                        self.db.record_provider_run(**run_kwargs)
                    if hasattr(self.db, "record_provider_evidence") and evidence_items:
                        self.db.record_provider_evidence(run_id, evidence_items)
            except Exception:
                pass
        return record
    def _find_index_file(self, repo_root: str) -> Optional[str]:
        canonical_root = os.path.realpath(repo_root)
        if self.index_path:
            p = os.path.join(repo_root, self.index_path) if not os.path.isabs(self.index_path) else self.index_path
            if os.path.isfile(p):
                real_p = os.path.realpath(p)
                try:
                    is_inside = os.path.commonpath([canonical_root, real_p]) == canonical_root
                except ValueError:
                    is_inside = False
                if is_inside:
                    return real_p
            return None
        for candidate in SCIP_DEFAULT_ARTIFACTS:
            p = os.path.join(repo_root, candidate)
            if os.path.isfile(p):
                real_p = os.path.realpath(p)
                try:
                    is_inside = os.path.commonpath([canonical_root, real_p]) == canonical_root
                except ValueError:
                    is_inside = False
                if is_inside:
                    return real_p
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
                            "kind": _normalize_scip_kind(sym.get("kind")),
                            "is_definition": True,
                            "documentation": sym.get("documentation", []),
                        })
                        if request.limit and len(results) > request.limit:
                            break
                if request.limit and len(results) > request.limit:
                    break

            if request.limit and len(results) > request.limit:
                truncated = True
                results = results[:request.limit]
            else:
                truncated = False
            duration_ms = int((time.monotonic() - start_t) * 1000)
            run = self._persist_outcome(
                capability="symbols",
                status="ok",
                exit_code=0,
                duration_ms=duration_ms,
                repo_root=request.repo_root,
                results=results,
                arguments={"query": request.query, "limit": request.limit},
            )
            return QueryOutcome(
                ok=True,
                run=run,
                payload={
                    "symbols": results,
                    "count": len(results),
                    "truncated": truncated,
                    "has_more": truncated,
                },
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_t) * 1000)
            run = self._persist_outcome(
                capability="symbols",
                status="error",
                exit_code=1,
                duration_ms=duration_ms,
                repo_root=request.repo_root,
                results=[],
                error=str(exc),
                arguments={"query": request.query, "limit": request.limit},
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
            truncated = False

            for doc in documents:
                rel_path = doc.get("relative_path", "")
                for occ in doc.get("occurrences", []):
                    raw_sym = occ.get("symbol", "")
                    parsed = parse_scip_symbol(raw_sym)
                    bare_name = parsed.get("bare_name") or raw_sym
                    fqn = parsed.get("fqn") or bare_name
                    if query_lower in bare_name.lower() or query_lower in fqn.lower() or query_lower in raw_sym.lower():
                        roles = occ.get("symbol_roles", 0)
                        # SCIP symbol_roles bit 0 (0x1) is Definition
                        is_def = bool(roles & 1)
                        span = None
                        r = occ.get("range", [])
                        if len(r) == 3:
                            span = {
                                "start_line": r[0] + 1,
                                "start_column": r[1] + 1,
                                "end_line": r[0] + 1,
                                "end_column": r[2] + 1,
                            }
                        elif len(r) >= 4:
                            span = {
                                "start_line": r[0] + 1,
                                "start_column": r[1] + 1,
                                "end_line": r[2] + 1,
                                "end_column": r[3] + 1,
                            }
                        results.append({
                            "name": bare_name,
                            "qualified_name": fqn,
                            "symbol": raw_sym,
                            "path": rel_path,
                            "kind": "definition" if is_def else "reference",
                            "is_definition": is_def,
                            "span": span,
                        })
                        if request.limit and len(results) > request.limit:
                            break
                if request.limit and len(results) > request.limit:
                    break

            if request.limit and len(results) > request.limit:
                truncated = True
                results = results[:request.limit]
            else:
                truncated = False

            duration_ms = int((time.monotonic() - start_t) * 1000)
            run = self._persist_outcome(
                capability="usages",
                status="ok",
                exit_code=0,
                duration_ms=duration_ms,
                repo_root=request.repo_root,
                results=results,
                arguments={"query": request.query, "limit": request.limit},
            )
            return QueryOutcome(
                ok=True,
                run=run,
                payload={
                    "symbols": results,
                    "count": len(results),
                    "truncated": truncated,
                    "has_more": truncated,
                },
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_t) * 1000)
            run = self._persist_outcome(
                capability="usages",
                status="error",
                exit_code=1,
                duration_ms=duration_ms,
                repo_root=request.repo_root,
                results=[],
                error=str(exc),
                arguments={"query": request.query, "limit": request.limit},
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
