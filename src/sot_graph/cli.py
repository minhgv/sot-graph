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

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler
from sot_graph.verifier import TrustVerifier, tokenize


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
    stats = reconciler.scan_and_reconcile()
    elapsed = time.time() - start_t
    print(
        f"✅ Reconcile complete in {elapsed:.2f}s: "
        f"{stats['indexed']} indexed/updated, "
        f"{stats['unchanged']} unchanged, "
        f"{stats['deleted']} purged."
    )
    return 0


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
    subparsers.add_parser("reconcile", help="Idempotently sync graph with filesystem")

    # verify
    p_ver = subparsers.add_parser("verify", help="Check for drift between graph and filesystem (CI-safe)")
    p_ver.add_argument("--deep", action="store_true", help="Perform full SHA-256 content re-hashing")

    # doctor
    subparsers.add_parser("doctor", help="Check database and graph health statistics")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    db_path = args.db or default_db_path(root)
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
        elif args.command == "verify":
            return cmd_verify(args, reconciler)
        elif args.command == "doctor":
            return cmd_doctor(db)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
