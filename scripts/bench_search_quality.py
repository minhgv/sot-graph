#!/usr/bin/env python3
"""bench_search_quality.py — ranked-retrieval search-quality benchmark (R3).

The reassessment (plan/sot-graph-reassessment-vs-roadmap-2026-08-28.md §4.2)
flagged that search quality was measured with ~20 probes and ambiguous Hit@5
of 44.4%. This benchmark closes that gap with a planted, offline corpus where
every probe has EXACTLY ONE known-correct node (ground truth by construction),
runs the REAL end-to-end search path (Database.search_fts -> TrustVerifier
per-hit verification -> P4 ranking, identical to `sot search`), and scores
per-class Hit@1/5/10 plus MRR at top-k=10.

Probe classes (12 probes each, 48 total):
  exact          — bare symbol / fqn queries with a unique target
  semantic       — natural-language phrases answered only by the target's body
  ambiguous      — bare names planted in several modules; the query adds the
                   intended module context (targets the 44.4% weakness)
  path_qualified — path-fragment token + symbol name

Deterministic: fixed corpus (no RNG), seeded filler fixtures, no network.
Writes benchmarks/search-quality.json with the corpus digest, gate block and
the per-probe record. `--gate` exits 1 when any threshold fails.

Usage:
  python3 scripts/bench_search_quality.py [--json benchmarks/search-quality.json]
  python3 scripts/bench_search_quality.py --gate
  python3 scripts/bench_search_quality.py --selfcheck
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO = Path(__file__).resolve().parents[1]
for _path in (_REPO, _REPO / "src", _REPO / "vendor"):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from benchmarks.fixtures import environment_fingerprint, generate_fixture  # noqa: E402
from sot_graph.db import Database  # noqa: E402
from sot_graph.reconciler import Reconciler  # noqa: E402
from sot_graph.verifier import TrustVerifier, tokenize  # noqa: E402

SCHEMA_VERSION = 1
BENCHMARK = "search-quality"
TOP_K = 10
FILLER_FILES = 150
FILLER_SEED = 20250219

# ---------------------------------------------------------------------------
# Planted corpus. Every intended answer is unique by construction.
# ---------------------------------------------------------------------------

FILES: Dict[str, str] = {}


def _add(rel: str, body: str) -> None:
    FILES[rel] = body


_add("app/pricing.py", '''"""Order pricing pipeline."""


def calc_order_total(lines, tax_rate):
    """Sum extended line amounts and apply tax to the order total."""
    subtotal = sum(line.quantity * line.unit_price for line in lines)
    return subtotal * (1.0 + tax_rate)


def apply_seasonal_discount(total, pct):
    """Reduce a quoted total by the seasonal percentage."""
    return total * (1.0 - pct / 100.0)
''')

_add("app/auth.py", '''"""Authentication helpers."""


def validate_session_token(token, now):
    """Check the signature and expiry window of a session token."""
    return token is not None and token.expires_at > now


def hash_credentials(password, salt):
    """Derive a salted credential hash for storage."""
    return f"{salt}:{len(password)}"
''')

_add("app/inventory.py", '''"""Warehouse inventory sync."""


def sync_stock_levels(warehouse):
    """Push counted stock levels back into the ledger."""
    for sku, counted in warehouse.counts.items():
        warehouse.ledger[sku] = counted


def reserve_batch(sku, quantity):
    """Hold a batch of units before allocation."""
    return (sku, quantity, "reserved")
''')

_add("app/shipping.py", '''"""Outbound shipping math."""


def estimate_freight_cost(weight, zone):
    """Quote freight cost from weight and destination zone."""
    return weight * zone.base_rate


def track_shipment(tracking_id):
    """Return the latest carrier scan for a shipment."""
    return {"id": tracking_id, "scan": "origin"}
''')

_add("app/reporting.py", '''"""Finance reporting jobs."""


def aggregate_daily_revenue(orders):
    """Fold order totals into a daily revenue rollup."""
    return sum(order.total for order in orders)


def render_sales_csv(rows):
    """Emit the sales table as CSV text."""
    return "\\n".join(",".join(map(str, row)) for row in rows)
''')

_add("app/notifications.py", '''"""User notification scheduling."""


def schedule_digest_email(user, window):
    """Queue the digest email for the user's quiet window."""
    return (user.id, window.start)


def throttle_push_alerts(device, budget):
    """Cap device push alerts to the daily budget."""
    return budget - device.sent_today
''')

# -- semantic class: the phrase is answerable only from the body -------------

_add("app/resilience.py", '''"""Fault-tolerance primitives."""


def attempt_with_jitter(op, attempts):
    """Exponential retry backoff policy for flaky upstream calls, with per-attempt jitter."""
    for n in range(attempts):
        try:
            return op()
        except TransientError:
            delay = 2 ** n
    return None
''')

_add("app/queue_health.py", '''"""Queue janitors."""


def quarantine_poison_message(msg, deliveries):
    """After the maximum delivery attempts, route the message to the dead letter queue."""
    if deliveries >= 5:
        return ("dead-letter", msg.id)
    return ("retry", msg.id)
''')

_add("app/cache_maintenance.py", '''"""Cache hygiene jobs."""


def sweep_eviction_hourly(store):
    """Hourly sweep to purge expired cache entries and evict stale lines."""
    return [key for key, entry in store.items() if entry.expired]
''')

_add("app/compliance.py", '''"""Compliance storage."""


def roll_compliance_files(prefix, keep):
    """Rotate audit log segments nightly and compress the archived files."""
    return sorted(p for p in prefix if p.endswith(".log"))[:keep]
''')

_add("app/webhooks.py", '''"""Inbound webhook gateway."""


def authenticate_delivery_event(request):
    """HMAC webhook signature verification gate before accepting delivery events."""
    return request.header == expected_hmac(request.body)
''')

_add("app/ingest.py", '''"""Event ingestion path."""


def drop_duplicate_fingerprints(events):
    """Idempotency filter to dedupe incoming events by content fingerprint."""
    seen = set()
    return [e for e in events if not (e.fingerprint in seen or seen.add(e.fingerprint))]
''')

_add("app/paging.py", '''"""Incident paging."""


def bump_severity_rotation(page, minutes):
    """Escalate an unacknowledged severity page to the oncall rotation after fifteen minutes."""
    if minutes >= 15:
        page.level += 1
    return page
''')

_add("app/metrics_backfill.py", '''"""Metrics warehouse tools."""


def rebuild_missing_series(series, snapshots):
    """Backfill missing historical metrics from warehouse snapshots."""
    return [snap for snap in snapshots if snap.key not in series]
''')

_add("app/streaming.py", '''"""Consumer streaming runtime."""


def persist_consumer_progress(partition, offset):
    """Persist the consumer stream offset checkpoint after every processed batch."""
    return ("checkpoint", partition, offset)
''')

_add("app/forms.py", '''"""Form rendering guards."""


def strip_control_chars(raw):
    """Strip control characters to sanitize user input before template rendering."""
    return "".join(ch for ch in raw if ch.isprintable())
''')

_add("app/oauth.py", '''"""OAuth client runtime."""


def rotate_oauth_grant(session):
    """Refresh the OAuth access token using the stored refresh grant."""
    return ("POST", "/token", session.refresh_grant)
''')

_add("app/session_store.py", '''"""Login session hygiene."""


def reap_idle_logins(store, idle_window):
    """Vacuum stale sessions that exceeded the configured idle timeout window."""
    return [s for s in store if s.idle > idle_window]
''')

# -- ambiguous class: same bare name in three modules ------------------------

_add("app/cache.py", '''"""Local cache front-end."""


def resolve(key):
    """Resolve a cache key against the local eviction table."""
    return TABLE.get(key)
''')

_add("app/dns.py", '''"""Hostname resolution."""


def resolve(host):
    """Resolve a hostname to an address via the recursive resolver."""
    return QUERY(host)
''')

_add("app/config.py", '''"""Runtime configuration."""


def resolve(placeholder):
    """Resolve a config placeholder from environment overlays."""
    return OVERLAYS[placeholder]
''')

_add("app/payments.py", '''"""Charge settlement."""


def process(charge):
    """Process a settled charge through the refund window."""
    return charge.amount
''')

_add("app/images.py", '''"""Image pipeline."""


def process(bitmap):
    """Process a raw bitmap through the resize pipeline."""
    return bitmap.width // 2
''')

_add("app/jobs.py", '''"""Background job runner."""


def process(item):
    """Process one background job item from the queue."""
    return item.payload
''')

_add("app/git_sync.py", '''"""Repository mirroring."""


def fetch(remote):
    """Fetch refs from the upstream remote into the mirror."""
    return remote.refs
''')

_add("app/weather.py", '''"""Station telemetry."""


def fetch(station):
    """Fetch the latest forecast observation for a station."""
    return station.reading
''')

_add("app/mail.py", '''"""Inbox access."""


def fetch(folder):
    """Fetch unread messages from an IMAP folder."""
    return folder.unread
''')

_add("app/schema_registry.py", '''"""Schema registry client."""


def validate(record):
    """Validate a record against the registered schema version."""
    return record.version in REGISTRY
''')

_add("app/licensing.py", '''"""License checks."""


def validate(key):
    """Validate a license key signature and expiry."""
    return key.signed and not key.expired
''')

_add("app/addressbook.py", '''"""Contact storage."""


def validate(entry):
    """Validate an address book entry's required fields."""
    return bool(entry.name and entry.mail)
''')

# -- interference: shared vocabulary without the qualified context -----------

_add("app/glossary.py", '''"""Internal glossary.

Words such as tokenize, rank, export, quote, adjust, translate, template and
process appear across the codebase; qualified lookups must disambiguate them.
"""


def lookup_glossary_term(term):
    """Return the glossary entry for a term."""
    return TERMS.get(term)
''')

_add("app/search_index.py", '''"""Prototype index."""


def build_index(hits):
    """Crude rank over tokenize-d hits until the real ranker lands."""
    return sorted(hits)
''')

# -- path_qualified class: subpackage path fragment + symbol -----------------

_add("app/auth/tokenizer.py", '''"""Auth request tokenization."""


def tokenize(text):
    """Split raw text into normalized tokens."""
    return text.split()
''')

_add("app/billing/totals.py", '''"""Billing totals."""


def compute_total(cart):
    """Total a cart for invoicing."""
    return sum(cart.lines)
''')

_add("app/inventory/adjustments.py", '''"""Stock adjustments."""


def adjust(sku, delta):
    """Apply a stock adjustment delta to a sku."""
    return delta
''')

_add("app/shipping/quotes.py", '''"""Shipping quotes."""


def quote(zipcode, weight):
    """Price a shipment quote for a zipcode."""
    return (zipcode, weight)
''')

_add("app/reporting/exports.py", '''"""Report exports."""


def export(rows, fmt):
    """Export report rows in the requested format."""
    return fmt.join(map(str, rows))
''')

_add("app/notifications/templates.py", '''"""Notification templates."""


def template(name, ctx):
    """Render a notification template with context."""
    return name.format(**ctx)
''')

_add("app/search/ranking.py", '''"""Search ranking."""


def rank(query, hits):
    """Score and rank hits for a query."""
    return hits[:10]
''')

_add("app/media/transcoder.py", '''"""Media transcode workers."""


def transcode(blob):
    """Transcode a media blob to the delivery preset."""
    return blob
''')

_add("app/audit/trail.py", '''"""Audit trail."""


def append_trail(actor, action):
    """Append an entry to the audit trail."""
    return (actor, action)
''')

_add("app/graphql/resolvers.py", '''"""GraphQL field wiring."""


def field_resolver(parent, info):
    """Resolve a single graphql field value."""
    return getattr(parent, info.field_name, None)
''')

_add("app/i18n/translate.py", '''"""Translation runtime."""


def translate(msgid, locale):
    """Translate a message id into the locale."""
    return CATALOG[locale].get(msgid, msgid)
''')

_add("app/cli/arguments.py", '''"""CLI argument parsing."""


def parse_args(argv):
    """Parse CLI arguments into options."""
    return {"argv": list(argv)}
''')

# Corpus sources above are DATA (parsed by the reconciler, never executed);
# unresolved names inside them simply land in pending_edges.

PROBE_SPEC: Sequence[Tuple[str, str, str]] = [
    # (query, class, expected fqn)
    # -- exact ----------------------------------------------------------------
    ("calc_order_total", "exact", "app.pricing.calc_order_total"),
    ("validate_session_token", "exact", "app.auth.validate_session_token"),
    ("sync_stock_levels", "exact", "app.inventory.sync_stock_levels"),
    ("estimate_freight_cost", "exact", "app.shipping.estimate_freight_cost"),
    ("aggregate_daily_revenue", "exact", "app.reporting.aggregate_daily_revenue"),
    ("schedule_digest_email", "exact", "app.notifications.schedule_digest_email"),
    ("apply_seasonal_discount", "exact", "app.pricing.apply_seasonal_discount"),
    ("hash_credentials", "exact", "app.auth.hash_credentials"),
    ("reserve_batch", "exact", "app.inventory.reserve_batch"),
    ("track_shipment", "exact", "app.shipping.track_shipment"),
    ("render_sales_csv", "exact", "app.reporting.render_sales_csv"),
    ("throttle_push_alerts", "exact", "app.notifications.throttle_push_alerts"),
    # -- semantic ---------------------------------------------------------------
    ("retry backoff policy", "semantic", "app.resilience.attempt_with_jitter"),
    ("dead letter queue", "semantic", "app.queue_health.quarantine_poison_message"),
    ("purge expired cache", "semantic", "app.cache_maintenance.sweep_eviction_hourly"),
    ("rotate audit log", "semantic", "app.compliance.roll_compliance_files"),
    ("verify webhook signature", "semantic", "app.webhooks.authenticate_delivery_event"),
    ("dedupe incoming events", "semantic", "app.ingest.drop_duplicate_fingerprints"),
    ("escalate oncall page", "semantic", "app.paging.bump_severity_rotation"),
    ("backfill historical metrics", "semantic", "app.metrics_backfill.rebuild_missing_series"),
    ("checkpoint stream offset", "semantic", "app.streaming.persist_consumer_progress"),
    ("sanitize user input", "semantic", "app.forms.strip_control_chars"),
    ("refresh access token", "semantic", "app.oauth.rotate_oauth_grant"),
    ("vacuum stale sessions", "semantic", "app.session_store.reap_idle_logins"),
    # -- ambiguous --------------------------------------------------------------
    ("cache resolve", "ambiguous", "app.cache.resolve"),
    ("dns resolve", "ambiguous", "app.dns.resolve"),
    ("config resolve", "ambiguous", "app.config.resolve"),
    ("payments process", "ambiguous", "app.payments.process"),
    ("images process", "ambiguous", "app.images.process"),
    ("jobs process", "ambiguous", "app.jobs.process"),
    ("git fetch", "ambiguous", "app.git_sync.fetch"),
    ("weather fetch", "ambiguous", "app.weather.fetch"),
    ("mail fetch", "ambiguous", "app.mail.fetch"),
    ("schema validate", "ambiguous", "app.schema_registry.validate"),
    ("license validate", "ambiguous", "app.licensing.validate"),
    ("address validate", "ambiguous", "app.addressbook.validate"),
    # -- path_qualified ----------------------------------------------------------
    ("auth tokenize", "path_qualified", "app.auth.tokenizer.tokenize"),
    ("billing compute_total", "path_qualified", "app.billing.totals.compute_total"),
    ("inventory adjust", "path_qualified", "app.inventory.adjustments.adjust"),
    ("shipping quote", "path_qualified", "app.shipping.quotes.quote"),
    ("reporting export", "path_qualified", "app.reporting.exports.export"),
    ("notifications template", "path_qualified", "app.notifications.templates.template"),
    ("search rank", "path_qualified", "app.search.ranking.rank"),
    ("media transcode", "path_qualified", "app.media.transcoder.transcode"),
    ("audit append_trail", "path_qualified", "app.audit.trail.append_trail"),
    ("graphql field_resolver", "path_qualified", "app.graphql.resolvers.field_resolver"),
    ("i18n translate", "path_qualified", "app.i18n.translate.translate"),
    ("cli parse_args", "path_qualified", "app.cli.arguments.parse_args"),
]

CLASSES = ("exact", "semantic", "ambiguous", "path_qualified")

# Initial thresholds sit just below the first measured values (see
# benchmarks/search-quality.json "gates.rationale"): strict enough to catch
# ranking regressions, loose enough to stay stable across SQLite point releases.
GATES: Dict[str, float] = {
    "exact_hit_at_1": 0.85,
    "semantic_hit_at_5": 0.90,
    "ambiguous_hit_at_5": 0.75,
    "path_qualified_hit_at_1": 0.90,
    "overall_mrr": 0.85,
}
GATE_RATIONALE = (
    "Thresholds were fixed ONCE, a step below the first measured run on the "
    "planted corpus (exact Hit@1 1.00, semantic Hit@5 1.00 with Hit@1 0.75, "
    "ambiguous Hit@5 1.00, path_qualified Hit@1 1.00, overall MRR 0.969); the "
    "corpus was never tuned to move the numbers. Margins absorb cross-platform "
    "BM25 rank jitter (a few probe flips) while still failing on real ranking "
    "regressions. The ambiguous margin is the widest because the class is "
    "intentionally hostile (one bare name planted in three modules) and "
    "targets the 44.4% Hit@5 weakness recorded in the 2026-08-28 "
    "reassessment; a fall back below 0.75 trips the gate."
)


# ---------------------------------------------------------------------------
# Metrics (pure, selfcheck-able)
# ---------------------------------------------------------------------------

def hit_at_k(ranks: Sequence[Optional[int]], k: int) -> float:
    """Fraction of probes whose single correct node ranks <= k (None = miss)."""
    if not ranks:
        return 0.0
    return round(sum(1 for r in ranks if r is not None and r <= k) / len(ranks), 4)


def mrr(ranks: Sequence[Optional[int]]) -> float:
    """Mean reciprocal rank; a miss contributes 0."""
    if not ranks:
        return 0.0
    return round(sum(1.0 / r for r in ranks if r is not None) / len(ranks), 4)


def class_metrics(ranks: Sequence[Optional[int]]) -> Dict[str, float]:
    return {
        "probes": len(ranks),
        "hit_at_1": hit_at_k(ranks, 1),
        "hit_at_5": hit_at_k(ranks, 5),
        "hit_at_10": hit_at_k(ranks, 10),
        "mrr": mrr(ranks),
    }


# ---------------------------------------------------------------------------
# Real search path (mirrors sot_graph.cli.cmd_search, BM25 branch)
# ---------------------------------------------------------------------------

def _relativize(path: str, root: str) -> str:
    """Make probe records reproducible across machines (temp roots differ)."""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return path


def real_search(db: Database, root: str, query: str, top_k: int) -> Dict[str, Any]:
    """Run the production search pipeline: FTS retrieval, per-hit trust
    verification and P4 re-ranking. Returns the ordered final list plus the
    pre-verification candidate identities for diagnostics."""
    from sot_graph.cli import _identity_grade, _p4_sort_key

    candidates = db.search_fts(query, limit=top_k)
    candidate_ids = [c.get("fqn") for c in candidates]
    q_toks = tokenize(query)
    verified: List[Dict[str, Any]] = []
    for cand in candidates:
        res = TrustVerifier.verify_hit(
            db, cand, q_toks, root, threshold=0.5, auto_heal=False, jit_reconcile=False
        )
        verdict, _coverage, real_path = res
        verified.append({
            "verdict": verdict,
            "coverage": f"{int((_coverage or 0) * 100)}%",
            "label": cand["label"],
            "fqn": cand.get("fqn"),
            "path": _relativize(real_path or cand.get("path") or "", root),
            "kind": cand["kind"],
            "line": cand.get("line_start"),
            "body": cand["body"],
            "score": round(cand.get("fused_score", cand["score"]), 6),
        })
    evidence_counts = db.provider_evidence_counts([v["path"] for v in verified])
    for v in verified:
        grade, _reason = _identity_grade(v, query)
        v["_identity_grade"] = grade
        v["_evidence_count"] = evidence_counts.get((v["path"], (v.get("label") or "")), 0)
    verified.sort(key=_p4_sort_key)
    final = verified[:top_k]
    for v in final:
        v.pop("_identity_grade", None)
        v.pop("_evidence_count", None)
    return {"final": final, "candidate_fqns": candidate_ids}


# ---------------------------------------------------------------------------
# Benchmark driver
# ---------------------------------------------------------------------------

def corpus_digest() -> str:
    payload = json.dumps({p: FILES[p] for p in sorted(FILES)}, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_corpus(root: Path) -> int:
    """Write the planted corpus plus deterministic filler files."""
    for rel, body in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    generate_fixture(root, files=FILLER_FILES, seed=FILLER_SEED)
    return len(FILES) + FILLER_FILES


def evaluate(db: Database, root_str: str, top_k: int) -> Dict[str, Any]:
    probe_records: List[Dict[str, Any]] = []
    ranks_by_class: Dict[str, List[Optional[int]]] = {c: [] for c in CLASSES}
    for query, klass, expected in PROBE_SPEC:
        out = real_search(db, root_str, query, top_k)
        final = out["final"]
        rank: Optional[int] = None
        for idx, row in enumerate(final, start=1):
            if row.get("fqn") == expected:
                rank = idx
                break
        ranks_by_class[klass].append(rank)
        probe_records.append({
            "query": query,
            "class": klass,
            "expected_fqn": expected,
            "rank": rank,
            "hit_at_1": rank == 1,
            "hit_at_5": rank is not None and rank <= 5,
            "hit_at_10": rank is not None and rank <= 10,
            "reciprocal_rank": (1.0 / rank) if rank else 0.0,
            "in_fts_candidates": expected in out["candidate_fqns"],
            "top3": [{"fqn": r.get("fqn"), "path": r.get("path")} for r in final[:3]],
        })

    by_class = {klass: class_metrics(ranks_by_class[klass]) for klass in CLASSES}
    overall_ranks = [r for klass in CLASSES for r in ranks_by_class[klass]]
    metrics: Dict[str, Any] = {
        "top_k": top_k,
        "probes": len(PROBE_SPEC),
        "by_class": by_class,
        "overall": class_metrics(overall_ranks),
    }

    measured = {
        "exact_hit_at_1": by_class["exact"]["hit_at_1"],
        "semantic_hit_at_5": by_class["semantic"]["hit_at_5"],
        "ambiguous_hit_at_5": by_class["ambiguous"]["hit_at_5"],
        "path_qualified_hit_at_1": by_class["path_qualified"]["hit_at_1"],
        "overall_mrr": metrics["overall"]["mrr"],
    }
    gate_results = {
        name: {"threshold": GATES[name], "measured": measured[name],
               "passed": measured[name] + 1e-9 >= GATES[name]}
        for name in GATES
    }
    return {
        "metrics": metrics,
        "gates": {
            "thresholds": dict(GATES),
            "results": gate_results,
            "passed": all(g["passed"] for g in gate_results.values()),
            "rationale": GATE_RATIONALE,
        },
        "probes": probe_records,
    }


def run_benchmark(top_k: int) -> Dict[str, Any]:
    runtime_parent = _REPO / ".sot"
    runtime_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bench-search-quality-", dir=runtime_parent) as directory:
        root = Path(directory)
        file_count = build_corpus(root)
        db_path = root / ".sot" / "sot.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = Database(str(db_path))
        try:
            Reconciler(db, str(root)).reconcile(workers=1)
            node_count = int(db.conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0])
            result = evaluate(db, str(root), top_k)
        finally:
            db.close()
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": BENCHMARK,
        "corpus": {
            "digest": corpus_digest(),
            "files": file_count,
            "nodes": node_count,
            "probes": len(PROBE_SPEC),
            "classes": {c: sum(1 for _, k, _ in PROBE_SPEC if k == c) for c in CLASSES},
            "filler": {"generator": "benchmarks.fixtures.generate_fixture",
                       "files": FILLER_FILES, "seed": FILLER_SEED},
        },
        "config": {"top_k": top_k, "search_path": "search_fts -> TrustVerifier -> P4 rank"},
        "environment": environment_fingerprint(top_k=top_k, filler_files=FILLER_FILES),
        **result,
    }


def print_summary(payload: Dict[str, Any]) -> None:
    m = payload["metrics"]
    print("=" * 72)
    print(f"SEARCH QUALITY — {payload['corpus']['probes']} probes, "
          f"top_k={m['top_k']}, corpus {payload['corpus']['digest'][:16]}")
    print("=" * 72)
    for klass in CLASSES:
        s = m["by_class"][klass]
        print(f"  [{klass:14s}] H@1 {s['hit_at_1']*100:5.1f}%  H@5 {s['hit_at_5']*100:5.1f}%  "
              f"H@10 {s['hit_at_10']*100:5.1f}%  MRR {s['mrr']*100:5.1f}%")
    o = m["overall"]
    print(f"  [{'overall':14s}] H@1 {o['hit_at_1']*100:5.1f}%  H@5 {o['hit_at_5']*100:5.1f}%  "
          f"H@10 {o['hit_at_10']*100:5.1f}%  MRR {o['mrr']*100:5.1f}%")
    gate_block = payload["gates"]
    status = "PASS" if gate_block["passed"] else "FAIL"
    print("-" * 72)
    for name, g in gate_block["results"].items():
        print(f"  gate {name:26s} measured {g['measured']:.2f} >= {g['threshold']:.2f} "
              f"-> {'ok' if g['passed'] else 'FAIL'}")
    print(f"  gates: {status}")
    misses = [p for p in payload["probes"] if p["rank"] is None]
    if misses:
        print(f"  misses ({len(misses)}): "
              + "; ".join(f"[{p['class']}] {p['query']!r}" for p in misses[:8]))


def run_selfcheck() -> List[str]:
    """Fast offline checks: metric math + one end-to-end mini corpus."""
    failures: List[str] = []
    if hit_at_k([1, 3, None, 5], 5) != 0.75:
        failures.append("hit_at_k math wrong")
    if hit_at_k([2, 2], 1) != 0.0:
        failures.append("hit_at_k must respect k")
    if mrr([1, 3, None]) != round((1 + 1 / 3) / 3, 4):
        failures.append("mrr math wrong")
    if mrr([None, None]) != 0.0:
        failures.append("mrr must treat misses as 0")
    if len(PROBE_SPEC) < 40:
        failures.append("probe corpus must have >= 40 probes")
    expected_classes = {c: sum(1 for _, k, _ in PROBE_SPEC if k == c) for c in CLASSES}
    if any(v < 10 for v in expected_classes.values()):
        failures.append(f"each class needs >= 10 probes: {expected_classes}")

    # End-to-end mini run through the real pipeline.
    with tempfile.TemporaryDirectory(prefix="bench-sq-selfcheck-") as directory:
        root = Path(directory)
        (root / "app").mkdir()
        (root / "app" / "alpha.py").write_text(
            'def unique_widget_marker():\n    """Widget assembly line for gizmos."""\n'
            '    return "widget"\n', encoding="utf-8")
        (root / "app" / "beta.py").write_text(
            'def assemble_gizmo():\n    """Assemble a gizmo from parts."""\n'
            '    return "gizmo"\n', encoding="utf-8")
        db = Database(str(root / ".sot" / "sot.db"))
        try:
            Reconciler(db, str(root)).reconcile(workers=1)
            out = real_search(db, str(root), "unique_widget_marker", 5)
            if not out["final"] or out["final"][0].get("fqn") != "app.alpha.unique_widget_marker":
                failures.append(f"exact selfcheck probe misranked: {out['final'][:2]}")
            out = real_search(db, str(root), "assemble gizmo from parts", 5)
            if not out["final"]:
                failures.append("semantic selfcheck probe returned no verified hits")
        finally:
            db.close()
    return failures


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=_REPO / "benchmarks" / "search-quality.json",
                        help="output JSON path (default benchmarks/search-quality.json)")
    parser.add_argument("--gate", action="store_true",
                        help="exit 1 when any quality gate threshold fails")
    parser.add_argument("--selfcheck", action="store_true",
                        help="run offline self-checks and exit")
    parser.add_argument("--top-k", type=int, default=TOP_K)
    args = parser.parse_args(argv)

    if args.selfcheck:
        failures = run_selfcheck()
        if failures:
            print("SELF-CHECK FAILED:")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("self-check: OK (metric math, probe corpus shape, real-pipeline probes)")
        return 0

    payload = run_benchmark(args.top_k)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print_summary(payload)
    print(f"\nWritten to: {args.json}")
    return 0 if payload["gates"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
