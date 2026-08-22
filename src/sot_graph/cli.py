"""
sot_graph.cli — CLI Dispatcher for sot-graph commands.
Commands: search, insert, reconcile, explore, verify, doctor.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from typing import List

import sqlite3

from sot_graph.db import CleanPlan, Database
from sot_graph.reconciler import Reconciler
from sot_graph.verifier import TrustVerifier, tokenize


def _maintenance_json(payload: dict) -> None:
    """Emit machine-readable maintenance output without terminal decoration."""
    print(json.dumps(payload, sort_keys=True))
def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed




def cmd_clean(args: argparse.Namespace, db: Database, root: str) -> int:
    started = time.monotonic()
    try:
        plan = db.plan_clean(root, reset=args.reset, include_notes=args.include_notes)
    except (OSError, ValueError, sqlite3.Error) as exc:
        if args.json:
            _maintenance_json({"mode": "reset" if args.reset else "stale",
                               "dry_run": bool(args.dry_run), "deleted": {},
                               "errors": [str(exc)], "duration_ms": 0})
        else:
            print(f"clean failed: {exc}", file=sys.stderr)
        return 1
    if plan.errors:
        if args.json:
            _maintenance_json({"mode": plan.mode, "dry_run": bool(args.dry_run),
                               "deleted": dict(plan.counts), "errors": list(plan.errors),
                               "duration_ms": int((time.monotonic() - started) * 1000)})
        else:
            for error in plan.errors:
                print(f"clean: {error}", file=sys.stderr)
        return 1

    if args.reset and not args.dry_run and not args.yes:
        if not sys.stdin.isatty():
            print("clean --all requires --yes when stdin is non-interactive", file=sys.stderr)
            return 1
        try:
            confirmation = input("Type RESET to delete all graph data: ")
        except (EOFError, KeyboardInterrupt):
            return 130 if isinstance(sys.exc_info()[1], KeyboardInterrupt) else 1
        if confirmation != "RESET":
            print("clean cancelled; exact confirmation RESET was not provided", file=sys.stderr)
            return 1

    try:
        deleted = dict(plan.counts) if args.dry_run else db.apply_clean(plan)
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        if args.json:
            _maintenance_json({"mode": plan.mode, "dry_run": bool(args.dry_run),
                               "deleted": {}, "errors": [str(exc)],
                               "duration_ms": int((time.monotonic() - started) * 1000)})
        else:
            print(f"clean failed: {exc}", file=sys.stderr)
        return 1
    payload = {
        "mode": plan.mode,
        "dry_run": bool(args.dry_run),
        "deleted": deleted,
        "errors": [],
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    if args.json:
        _maintenance_json(payload)
    else:
        action = "would delete" if args.dry_run else "deleted"
        print(f"Clean ({plan.mode}): {action} "
              f"{deleted.get('paths', 0)} paths, {deleted.get('nodes', 0)} nodes, "
              f"{deleted.get('edges', 0)} edges, {deleted.get('pending', 0)} pending edges, "
              f"{deleted.get('notes', 0)} notes.")
    return 0


def cmd_vacuum(args: argparse.Namespace, db: Database) -> int:
    try:
        result = db.vacuum(optimize=args.analyze, dry_run=args.dry_run)
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        if args.json:
            _maintenance_json({"error": str(exc), "dry_run": bool(args.dry_run)})
        else:
            print(f"vacuum failed: {exc}", file=sys.stderr)
        return 1
    payload = {
        "dry_run": result.dry_run,
        "before_bytes": result.before_bytes,
        "after_bytes": result.after_bytes,
        "reclaimed_bytes": result.reclaimed_bytes,
        "before_wal_bytes": result.before_wal_bytes,
        "after_wal_bytes": result.after_wal_bytes,
        "page_size": result.page_size,
        "before_page_count": result.before_page_count,
        "after_page_count": result.after_page_count,
        "before_freelist_pages": result.before_freelist_pages,
        "after_freelist_pages": result.after_freelist_pages,
        "estimated_reclaimable_bytes": result.estimated_reclaimable_bytes,
        "checkpoint_status": result.checkpoint_status,
        "elapsed_ms": result.elapsed_ms,
        "optimized": result.optimized,
    }
    if args.json:
        _maintenance_json(payload)
    else:
        if args.dry_run:
            print(f"Vacuum dry-run: estimated reclaimable {result.estimated_reclaimable_bytes} bytes.")
        else:
            print(f"Vacuum complete: reclaimed {result.reclaimed_bytes} bytes "
                  f"({result.before_bytes} -> {result.after_bytes}).")
    return 0


def default_db_path(root: str) -> str:
    return os.path.join(os.path.abspath(root), ".sot", "sot.db")


def cmd_search(args: argparse.Namespace, db: Database, root: str) -> int:
    q_toks = tokenize(args.query)
    candidates = db.search_fts(args.query, limit=args.limit, scope=args.scope)

    verified = []
    for cand in candidates:
        verdict, cov, real_path = TrustVerifier.verify_hit(
            db, cand, q_toks, root, threshold=args.threshold
        )
        if verdict == "REMOVED":
            continue  # Auto-purged dead path

        verified.append({
            "verdict": verdict,
            "coverage": f"{int((cov or 0) * 100)}%",
            "label": cand["label"],
            "path": real_path or cand.get("path") or "",
            "kind": cand["kind"],
            "line": cand.get("line_start"),
            "body": cand["body"],
            "score": round(cand["score"], 3),
        })

    # Sort priority: STRONG / REBUILT -> WEAK -> NOPATH, then highest coverage
    rank_order = {"STRONG": 0, "REBUILT": 0, "WEAK": 1, "NOPATH": 2}
    verified.sort(
        key=lambda x: (
            rank_order.get(x["verdict"], 9),
            -float(x["coverage"].replace("%", "")),
        )
    )
    final_list = verified[:args.limit]

    if args.json:
        print(json.dumps({"query": args.query, "results": final_list}, indent=2))
        return 0

    print(f"\n🔍 Knowledge Search: \"{args.query}\" (Found: {len(final_list)} verified hits)")
    print("=" * 80)
    if not final_list:
        print("  (No verified matching knowledge found in graph)")
        return 0

    for i, r in enumerate(final_list, 1):
        cov_str = f"cov:{r['coverage']}" if r['coverage'] != "0%" else ""
        loc = f"{r['path']}:{r['line']}" if r.get('line') else r['path']
        print(f"  {i:2d}. [{r['verdict']:^7}] {cov_str:^8} {r['label']}")
        if loc:
            print(f"      📍 File: {loc}")
        first_line = r['body'].splitlines()[0][:110]
        print(f"      💡 Content: {first_line}...")
        print()

    return 0


def cmd_explore(args: argparse.Namespace, db: Database) -> int:
    query = args.target.strip()
    cur = db.conn.execute(
        "SELECT id, label, kind, path, line_start FROM graph_nodes WHERE symbol = ? OR label LIKE ? LIMIT 1",
        (query, f"%{query}%")
    )
    row = cur.fetchone()
    if not row:
        print(f"❌ No symbol or node matching '{query}' found in graph.")
        return 1

    node_id, label, kind, path, line = row
    print(f"\n🌐 Graph Walk: [{label}] ({kind}) @ {path}:{line or 1}")
    print("=" * 80)

    relations = db.explore_node(node_id, depth=args.depth)
    if not relations:
        print("  (No inbound or outbound connections found)")
        return 0

    outward = [r for r in relations if r["direction"] == "outward"]
    inward = [r for r in relations if r["direction"] == "inward"]

    if outward:
        print("  ▶ Outward Calls / Uses:")
        for r in outward:
            print(f"    └── [{r['relation']}] ➔ {r['label']} ({r['path']}:{r['line'] or 1})")

    if inward:
        print("\n  ◀ Inward References (Used by):")
        for r in inward:
            print(f"    └── [{r['relation']}] ➔ {r['label']} ({r['path']}:{r['line'] or 1})")

    print()
    return 0


def cmd_insert(args: argparse.Namespace, db: Database) -> int:
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    content = f"{args.title}\n{args.body}"
    node_id = f"note:{hashlib.sha256(content.encode()).hexdigest()[:12]}"
    now = int(time.time())
    kw_str = " ".join(keywords)

    with db.conn:
        db.conn.execute("""
            INSERT INTO graph_nodes (id, path, kind, symbol, label, body, keywords, line_start, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                path=excluded.path, label=excluded.label, body=excluded.body,
                keywords=excluded.keywords, updated_at=excluded.updated_at
        """, (
            node_id, args.path or "", "note", None, args.title,
            args.body, kw_str, 1, now
        ))

    print(f"✅ Stored knowledge node [{node_id}] '{args.title}'")
    return 0


def cmd_reconcile(args: argparse.Namespace, reconciler: Reconciler) -> int:
    start_t = time.time()
    try:
        summary = reconciler.reconcile(
            paths=args.paths,
            workers=args.workers,
            batch_size=args.batch_size,
        )
    except KeyboardInterrupt:
        return 130
    elapsed = time.time() - start_t
    if args.json:
        print(json.dumps(summary.as_dict(), sort_keys=True))
    else:
        print(
            f"✅ Reconcile complete in {elapsed:.2f}s: "
            f"{summary.updated} indexed/updated, "
            f"{summary.unchanged} unchanged, "
            f"{summary.deleted} purged, "
            f"{summary.failed} failed."
        )
    return 1 if summary.failed else 0




def cmd_verify(args: argparse.Namespace, reconciler: Reconciler) -> int:
    drift = reconciler.audit_drift(deep=args.deep)
    if drift:
        print(f"⚠️  DRIFT DETECTED: {len(drift)} files out of sync with disk:")
        for d in drift:
            print(f"   [{d['why']}] {d['path']}")
        print("\nRun 'sot reconcile' to synchronize graph.")
        return 1

    print("✅ ZERO DRIFT: All recorded nodes and files match disk state exactly.")
    return 0


def cmd_doctor(db: Database) -> int:
    st = db.stats()
    print("\n🩺 SOT-Graph Doctor Report:")
    print("=" * 40)
    print(f"  • SQLite Database : {db.db_path} (WAL Mode: OK)")
    print(f"  • Tracked Files   : {st['paths']}")
    print(f"  • Graph Nodes     : {st['nodes']}")
    print(f"  • Confirmed Edges : {st['edges']}")
    print(f"  • Pending Edges   : {st['pending']}")
    print("=" * 40)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sot",
        description="sot-graph: Verified, self-healing knowledge graph for AI coding agents."
    )
    parser.add_argument("--root", default=".", help="Project root directory (default: current dir)")
    parser.add_argument("--db", default=None, help="Custom SQLite DB path (default: .sot/sot.db)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = subparsers.add_parser("search", help="Ranked search with Trust Verdicts")
    p_search.add_argument("query", help="Query string")
    p_search.add_argument("-n", "--limit", type=int, default=6, help="Maximum results (default: 6)")
    p_search.add_argument("--scope", default=None, help="Filter by path or keyword substring")
    p_search.add_argument("--threshold", type=float, default=0.5, help="Coverage threshold for STRONG verdict")
    p_search.add_argument("--json", action="store_true", help="Output JSON format")

    # explore
    p_exp = subparsers.add_parser("explore", help="Explore AST relations and cross-file edges")
    p_exp.add_argument("target", help="Symbol, function name, or class to explore")
    p_exp.add_argument("--depth", type=int, default=2, help="Graph walk depth (default: 2)")

    # insert
    p_ins = subparsers.add_parser("insert", help="Insert a reusable piece of knowledge or decision")
    p_ins.add_argument("--title", required=True, help="Title of the knowledge item")
    p_ins.add_argument("--body", required=True, help="Detailed explanation, fix, or gotcha")
    p_ins.add_argument("--path", default="", help="Associated file path if applicable")
    p_ins.add_argument("--keywords", default="", help="Comma-separated keywords")

    # reconcile
    p_rec = subparsers.add_parser("reconcile", help="Idempotently sync graph with filesystem")
    p_rec.add_argument("paths", nargs="*", help="Files or directories relative to --root")
    p_rec.add_argument(
        "--workers",
        type=_positive_int,
        default=min(8, max(1, os.cpu_count() or 1)),
        help="Extraction worker processes (default: auto, max 8)",
    )
    p_rec.add_argument(
        "--batch-size",
        type=_positive_int,
        default=64,
        help="Files per deterministic transaction window (default: 64)",
    )
    p_rec.add_argument("--json", action="store_true", help="Output summary as JSON")
    # verify
    p_ver = subparsers.add_parser("verify", help="Check for drift between graph and filesystem (CI-safe)")
    p_ver.add_argument("--deep", action="store_true", help="Perform full SHA-256 content re-hashing")

    # doctor
    subparsers.add_parser("doctor", help="Check database and graph health statistics")

    # clean
    p_clean = subparsers.add_parser("clean", help="Remove stale or reset graph data safely")
    p_clean.add_argument("--dry-run", action="store_true", help="Classify without changing the database")
    p_clean.add_argument("--all", dest="reset", action="store_true", help="Reset generated graph data")
    p_clean.add_argument("--include-notes", action="store_true", help="Include notes in --all reset")
    p_clean.add_argument("--yes", action="store_true", help="Skip reset confirmation")
    p_clean.add_argument("--json", action="store_true", help="Output JSON format")

    # vacuum
    p_vac = subparsers.add_parser("vacuum", help="Compact the SQLite database")
    p_vac.add_argument("--analyze", action="store_true", help="Run PRAGMA optimize after vacuum")
    p_vac.add_argument("--dry-run", action="store_true", help="Report reclaimable space without mutation")
    p_vac.add_argument("--json", action="store_true", help="Output JSON format")

    # mcp (optional dependency is imported only when this command is selected)
    subparsers.add_parser("mcp", help="Run the optional MCP stdio server")

    return parser
def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    db_path = args.db or default_db_path(root)
    if args.command == "mcp":
        # Keep the optional SDK out of normal CLI startup/import paths.
        from sot_graph.mcp_server import main as mcp_main
        return mcp_main(["--root", root, "--db", db_path])

    db = Database(db_path)
    reconciler = Reconciler(db, root)

    try:
        if args.command == "search":
            return cmd_search(args, db, root)
        elif args.command == "explore":
            return cmd_explore(args, db)
        elif args.command == "insert":
            return cmd_insert(args, db)
        elif args.command == "reconcile":
            return cmd_reconcile(args, reconciler)
        elif args.command == "clean":
            return cmd_clean(args, db, root)
        elif args.command == "vacuum":
            return cmd_vacuum(args, db)
        elif args.command == "verify":
            return cmd_verify(args, reconciler)
        elif args.command == "doctor":
            return cmd_doctor(db)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
