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
    # Current SCIP `Kind` enum (scip.proto) — non-sequential by design;
    # the old sequential 0..29 table matched neither this enum nor the
    # deprecated SymbolKind one, mislabelling nearly every numeric kind.
    0: "unspecifiedkind", 1: "array", 2: "assertion", 3: "associatedtype", 4: "attribute", 5: "axiom", 6: "boolean", 7: "class", 8: "constant", 9: "constructor", 10: "datafamily", 11: "enum", 12: "enummember", 13: "event", 14: "fact", 15: "field", 16: "file", 17: "function", 18: "getter", 19: "grammar", 20: "instance", 21: "interface", 22: "key", 23: "lang", 24: "lemma", 25: "macro", 26: "method", 27: "methodreceiver", 28: "message", 29: "module", 30: "namespace", 31: "null", 32: "number", 33: "object", 34: "operator", 35: "package", 36: "packageobject", 37: "parameter", 38: "parameterlabel", 39: "pattern", 40: "predicate", 41: "property", 42: "protocol", 43: "quasiquoter", 44: "selfparameter", 45: "setter", 46: "signature", 47: "subscript", 48: "string", 49: "struct", 50: "tactic", 51: "theorem", 52: "thisparameter", 53: "trait", 54: "type", 55: "typealias", 56: "typeclass", 57: "typefamily", 58: "typeparameter", 59: "union", 60: "value", 61: "variable", 62: "contract", 63: "error", 64: "library", 65: "modifier", 66: "abstractmethod", 67: "methodspecification", 68: "protocolmethod", 69: "purevirtualmethod", 70: "traitmethod", 71: "typeclassmethod", 72: "accessor", 73: "delegate", 74: "methodalias", 75: "singletonclass", 76: "singletonmethod", 77: "staticdatamember", 78: "staticevent", 79: "staticfield", 80: "staticmethod", 81: "staticproperty", 82: "staticvariable", 84: "extension", 85: "mixin", 86: "concept", 87: "next",
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
        # Single-entry parse cache keyed by (realpath, mtime_ns, size): one
        # provider run probes and then queries the same multi-hundred-MB
        # index several times — only the first call should pay for parsing.
        self._parse_cache: Optional[
            Tuple[str, int, int, Dict[str, Any], List[Dict[str, Any]]]
        ] = None

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
        cache_key: Optional[Tuple[str, int, int]] = None
        try:
            real = os.path.realpath(file_path)
            st = os.stat(real)
            cache_key = (real, st.st_mtime_ns, st.st_size)
        except OSError:
            cache_key = None
        if cache_key is not None and self._parse_cache is not None:
            c_real, c_mtime, c_size, c_meta, c_docs = self._parse_cache
            if (c_real, c_mtime, c_size) == cache_key:
                # List copy keeps callers from mutating the cached documents.
                return dict(c_meta), list(c_docs)
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
        if cache_key is not None:
            self._parse_cache = (
                cache_key[0], cache_key[1], cache_key[2],
                dict(metadata), list(documents),
            )
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
