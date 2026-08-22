"""Optional hybrid retrieval: FTS5 BM25 fused with sqlite-vec vectors.

Installed via the ``[vector]`` extra (``pip install 'sot-graph[vector]'``).
The zero-dependency core keeps FTS5 BM25 as the always-available floor;
when the extension and an embedder are present, :func:`hybrid_search` fuses
both rankings with Reciprocal Rank Fusion. Trust verdicts remain orthogonal
to score fusion — verification is never diluted by similarity.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

RRF_K = 60  # standard reciprocal-rank-fusion constant
DEFAULT_DIM = 256
_TABLE = "graph_vec"

try:  # pragma: no cover - depends on optional extra
    import sqlite_vec  # type: ignore

    SQLITE_VEC_AVAILABLE = True
except ImportError:  # pragma: no cover
    sqlite_vec = None
    SQLITE_VEC_AVAILABLE = False


def available() -> bool:
    """True when the sqlite-vec extension can be loaded."""
    return SQLITE_VEC_AVAILABLE


class HashEmbedder:
    """Deterministic dependency-free embedder (hashing trick, L2-normalized).

    Bag-of-words semantics only: it makes the hybrid pipeline runnable and
    testable offline, but real semantic recall requires plugging a neural
    embedder with the same interface.
    """

    def __init__(self, dim: int = DEFAULT_DIM):
        self.dim = dim

    def _tokens(self, text: str) -> List[str]:
        import re

        return re.findall(r"[a-z0-9]+", text.lower())

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for tok in self._tokens(text):
                if not tok:
                    continue
                digest = hashlib.sha256(tok.encode("utf-8")).digest()
                idx = int.from_bytes(digest[:4], "big") % self.dim
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vec[idx] += sign
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            out.append(vec)
        return out

    def embed_query(self, text: str) -> List[float]:
        return self.embed([text])[0]


def load_extension(conn) -> bool:
    """Load sqlite-vec into a connection; returns success."""
    if not SQLITE_VEC_AVAILABLE:
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        return True
    except Exception:
        return False


def ensure_table(conn, dim: int = DEFAULT_DIM) -> bool:
    """Create the vec0 virtual table if the extension is usable."""
    if not load_extension(conn):
        return False
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {_TABLE} USING vec0("
        f"node_id TEXT PRIMARY KEY, embedding float[{dim}])"
    )
    conn.commit()
    return True


def index_nodes(conn, embedder: Optional[HashEmbedder] = None, *, limit: int = 5000) -> int:
    """(Re)embed graph nodes into the vector table; returns embedded count."""
    embedder = embedder or HashEmbedder()
    if not ensure_table(conn, embedder.dim):
        return 0
    rows = conn.execute(
        "SELECT id, label, symbol, keywords, COALESCE(body, '') FROM graph_nodes "
        "WHERE kind != 'file' LIMIT ?", (limit,)
    ).fetchall()
    if not rows:
        return 0
    texts = [f"{label} {symbol or ''} {keywords or ''} {body[:512]}"
             for _, label, symbol, keywords, body in rows]
    vectors = embedder.embed(texts)
    with conn:
        conn.execute(f"DELETE FROM {_TABLE}")
        conn.executemany(
            f"INSERT INTO {_TABLE}(node_id, embedding) VALUES (?, ?)",
            [(rows[i][0], _vec_blob(vectors[i])) for i in range(len(rows))],
        )
    return len(rows)


def _vec_blob(vector: Sequence[float]) -> bytes:
    import struct

    return struct.pack(f"<{len(vector)}f", *vector)


def vector_search(conn, query: str, embedder: Optional[HashEmbedder] = None,
                  *, limit: int = 10) -> List[Tuple[str, float]]:
    """Top-k node ids by cosine distance; empty when unavailable."""
    embedder = embedder or HashEmbedder()
    if not load_extension(conn):
        return []
    try:
        rows = conn.execute(
            f"SELECT node_id, distance FROM {_TABLE} "
            f"WHERE embedding MATCH ? AND k = ?",
            (_vec_blob(embedder.embed_query(query)), limit),
        ).fetchall()
    except Exception:
        return []
    return [(r[0], float(r[1])) for r in rows]


def reciprocal_rank_fusion(*rankings: Sequence[str], k: int = RRF_K) -> Dict[str, float]:
    """Fuse ranked id lists into RRF scores (higher is better)."""
    scores: Dict[str, float] = {}
    for ranking in rankings:
        for position, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + position + 1)
    return scores


def hybrid_search(db, query: str, *, limit: int = 10,
                  embedder: Optional[HashEmbedder] = None) -> Dict[str, Any]:
    """Fuse BM25 (always) with vector similarity (when available).

    Returns hits with ``fused_score``, ``sources`` provenance, and the
    original search_fts payloads for verdict computation upstream.
    """
    fts_hits = db.search_fts(query, limit=limit * 2)
    fts_order = [h["id"] for h in fts_hits]
    vec_hits = vector_search(db.conn, query, embedder, limit=limit * 2)
    vec_order = [node_id for node_id, _ in vec_hits]

    if not vec_order:
        fused = {nid: 1.0 / (RRF_K + i + 1) for i, nid in enumerate(fts_order)}
        sources = {nid: ["bm25"] for nid in fts_order}
    else:
        fused = reciprocal_rank_fusion(fts_order, vec_order)
        sources = {}
        for nid in fts_order:
            sources.setdefault(nid, []).append("bm25")
        for nid in vec_order:
            sources.setdefault(nid, []).append("vector")

    by_id = {h["id"]: h for h in fts_hits}
    ordered = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    hits: List[Dict[str, Any]] = []
    for node_id, score in ordered:
        payload = by_id.get(node_id)
        if payload is None:
            # Vector-only hit: fetch minimal payload for display/verdicts.
            row = db.conn.execute(
                "SELECT id, path, kind, symbol, fqn, label, body, keywords, line_start "
                "FROM graph_nodes WHERE id = ?", (node_id,)
            ).fetchone()
            if row is None:
                continue
            payload = {"id": row[0], "path": row[1], "kind": row[2], "symbol": row[3],
                       "fqn": row[4], "label": row[5], "body": row[6], "keywords": row[7],
                       "line_start": row[8], "score": 0.0}
        entry = dict(payload)
        entry["fused_score"] = round(score, 6)
        entry["sources"] = sources.get(node_id, [])
        hits.append(entry)
    return {
        "query": query,
        "mode": "hybrid" if vec_order else "bm25",
        "results": hits,
        "returned": len(hits),
    }
