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
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

RRF_K = 60  # standard reciprocal-rank-fusion constant
DEFAULT_DIM = 256
_TABLE = "graph_vec"
#: Bookkeeping for incremental embedding (R5): the hash of the text each
#: node was embedded from. Owned by vector.py, created lazily next to the
#: vec0 table and only ever touched when the extension is active.
_STATE_TABLE = "vector_index_state"
#: Embedding subset cap. Applied to the NEWEST nodes by ``updated_at``
#: (reconcile rewrites touched nodes with a fresh timestamp), never
#: silently: exceeding it sets ``truncated`` in the stats and warns.
DEFAULT_EMBED_CAP = 5000

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
    if not SQLITE_VEC_AVAILABLE or sqlite_vec is None:
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        return True
    except Exception:
        return False


def ensure_table(conn, dim: int = DEFAULT_DIM) -> bool:
    """Create the vec0 virtual table if the extension is usable.

    Also creates the ``vector_index_state`` bookkeeping table (R5) in the
    same gate: it is only ever written when the vec extension is active,
    so a sqlite-vec-free install never grows schema baggage.
    """
    if not load_extension(conn):
        return False
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {_TABLE} USING vec0("
        f"node_id TEXT PRIMARY KEY, embedding float[{dim}])"
    )
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {_STATE_TABLE} ("
        "node_id TEXT PRIMARY KEY, embedded_hash TEXT NOT NULL, "
        "embedded_at INTEGER NOT NULL)"
    )
    conn.commit()
    return True


def _embedding_text(row: Sequence[Any]) -> str:
    """The exact text a node is embedded from (hash input, R5)."""
    label, symbol, keywords, body = row[1], row[2], row[3], row[4]
    return f"{label} {symbol or ''} {keywords or ''} {body[:512]}"


def _chunked(seq: List[Any], size: int = 500) -> "List[List[Any]]":
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def index_nodes(conn, embedder: Optional[HashEmbedder] = None, *,
                cap: Optional[int] = None) -> Dict[str, Any]:
    """Incrementally (re)embed graph nodes into the vector table (R5).

    Returns a stats dict: ``embedded`` (nodes embedded by this call),
    ``unchanged`` (skipped — vector + bookkeeping hash already current),
    ``pruned`` (vectors dropped for vanished/rotated-out nodes),
    ``total_nodes`` (all embeddable non-file nodes), ``cap``,
    ``truncated``.

    Incremental contract: a node is re-embedded only when the hash of its
    embedding text changed (or its vector/bookkeeping row is missing);
    nodes that vanished — or fell out of the capped selection — have their
    vector and bookkeeping rows dropped. The cap selects the NEWEST nodes
    by ``updated_at`` (``id`` as deterministic tiebreak), replacing the old
    ``ORDER BY id`` subset that silently rotated for repos bigger than the
    cap. Exceeding the cap is never silent: ``truncated`` is set in the
    returned stats and a warning goes to stderr.

    Staleness contract: reconcile only prunes orphaned vector rows (see
    :func:`prune_orphans`); it deliberately does NOT re-embed, because
    auto-embedding on every reconcile would balloon reconcile latency.
    Embedding refresh stays explicit via ``sot embed`` — which this
    incremental path makes cheap: after a small change, re-running embed
    costs O(changed) embedder calls instead of a full DELETE+INSERT
    rebuild.
    """
    embedder = embedder or HashEmbedder()
    empty_stats = {"embedded": 0, "unchanged": 0, "pruned": 0,
                   "total_nodes": 0, "cap": 0, "truncated": False}
    if not ensure_table(conn, embedder.dim):
        return empty_stats
    effective_cap = int(cap) if cap is not None else DEFAULT_EMBED_CAP
    total_nodes = int(conn.execute(
        "SELECT COUNT(*) FROM graph_nodes WHERE kind != 'file'"
    ).fetchone()[0])
    rows = conn.execute(
        "SELECT id, label, symbol, keywords, COALESCE(body, '') FROM graph_nodes "
        "WHERE kind != 'file' ORDER BY updated_at DESC, id LIMIT ?",
        (effective_cap,),
    ).fetchall()
    truncated = total_nodes > len(rows)
    desired = {
        row[0]: hashlib.sha256(_embedding_text(row).encode("utf-8")).hexdigest()
        for row in rows
    }
    state = {
        str(r[0]): str(r[1]) for r in conn.execute(
            f"SELECT node_id, embedded_hash FROM {_STATE_TABLE}"
        ).fetchall()
    }
    embedded_ids = {
        str(r[0]) for r in conn.execute(f"SELECT node_id FROM {_TABLE}").fetchall()
    }
    # Vanished nodes plus nodes rotated out of the capped selection.
    stale_ids = sorted((set(state) | embedded_ids) - set(desired))
    # Re-embed only changed content or rows missing their vector.
    to_embed = [
        row for row in rows
        if desired[row[0]] != state.get(row[0]) or row[0] not in embedded_ids
    ]
    vectors = embedder.embed([_embedding_text(row) for row in to_embed])
    now = int(time.time())
    with conn:
        for chunk in _chunked(stale_ids):
            marks = ",".join("?" * len(chunk))
            conn.execute(f"DELETE FROM {_TABLE} WHERE node_id IN ({marks})", chunk)
            conn.execute(
                f"DELETE FROM {_STATE_TABLE} WHERE node_id IN ({marks})", chunk
            )
        if to_embed:
            # vec0 virtual tables reject INSERT OR REPLACE on an existing
            # primary key, so changed nodes are deleted before re-insert.
            reembed_ids = [row[0] for row in to_embed]
            for chunk in _chunked(reembed_ids):
                marks = ",".join("?" * len(chunk))
                conn.execute(f"DELETE FROM {_TABLE} WHERE node_id IN ({marks})", chunk)
            conn.executemany(
                f"INSERT INTO {_TABLE}(node_id, embedding) VALUES (?, ?)",
                [(row[0], _vec_blob(vectors[i])) for i, row in enumerate(to_embed)],
            )
            conn.executemany(
                f"INSERT OR REPLACE INTO {_STATE_TABLE}"
                "(node_id, embedded_hash, embedded_at) VALUES (?, ?, ?)",
                [(row[0], desired[row[0]], now) for row in to_embed],
            )
    if truncated:
        print(
            f"sot embed: vector index truncated to {len(rows)} of "
            f"{total_nodes} nodes (newest kept by updated_at); raise the "
            "cap to cover the rest",
            file=sys.stderr,
        )
    return {
        "embedded": len(to_embed),
        "unchanged": len(rows) - len(to_embed),
        "pruned": len(stale_ids),
        "total_nodes": total_nodes,
        "cap": effective_cap,
        "truncated": truncated,
    }


def prune_orphans(conn) -> int:
    """Drop vector rows whose node no longer exists; returns pruned count.

    Reconcile deletes and renames nodes without knowing about the optional
    vector table, so deleted ids keep answering vector queries until the
    next full re-embed. Read paths filter unresolvable ids, but the rows
    should not rot between embeds either. The incremental-embedding
    bookkeeping table (R5) is pruned by the same pass so stale hashes
    cannot outlive their nodes.
    """
    try:
        pruned = 0
        with conn:
            cur = conn.execute(
                f"DELETE FROM {_TABLE} WHERE node_id NOT IN (SELECT id FROM graph_nodes)"
            )
            pruned += cur.rowcount or 0
            conn.execute(
                f"DELETE FROM {_STATE_TABLE} WHERE node_id NOT IN "
                "(SELECT id FROM graph_nodes)"
            )
        return pruned
    except Exception:
        # sqlite-vec not installed / table absent / read-only DB: nothing to do.
        return 0


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


def hybrid_search(db, query: str, *, limit: int = 10, scope: Optional[str] = None,
                  embedder: Optional[HashEmbedder] = None) -> Dict[str, Any]:
    """Fuse BM25 (always) with vector similarity (when available).

    ``scope`` narrows both retrieval legs to a path subtree, matching
    ``db.search_fts`` semantics so hybrid results respect the same filter
    as plain search. Returns hits with ``fused_score``, ``sources``
    provenance, and the original search_fts payloads for verdict
    computation upstream.
    """
    fts_hits = db.search_fts(query, limit=limit * 2, scope=scope)
    vec_hits = vector_search(db.conn, query, embedder, limit=limit * 2)
    if scope:
        # Vector leg: keep only nodes inside the scope subtree.
        prefix = scope.replace("\\", "/").rstrip("/") + "/"
        def _in_scope(node_id: str) -> bool:
            row = db.conn.execute(
                "SELECT path FROM graph_nodes WHERE id = ?", (node_id,)
            ).fetchone()
            if row is None:
                return False
            p = str(row[0]).replace("\\", "/")
            return p == scope.rstrip("/") or p.startswith(prefix)
        vec_hits = [(nid, s) for nid, s in vec_hits if _in_scope(nid)]
    fts_order = [h["id"] for h in fts_hits]
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
        "scope": scope or None,
        "results": hits,
        "returned": len(hits),
    }
