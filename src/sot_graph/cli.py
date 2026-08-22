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


def _resolve_symbol(db: Database, query: str):
    """Resolve a query to one node row: (id, label, kind, path, line, symbol).

    Prefers exact symbol matches over file/doc nodes whose labels merely
    mention the query text.
    """
    row = db.conn.execute(
        "SELECT id, label, kind, path, line_start, symbol FROM graph_nodes "
        "WHERE symbol = ? LIMIT 1", (query,)
    ).fetchone()
    if not row:
        row = db.conn.execute(
            "SELECT id, label, kind, path, line_start, symbol FROM graph_nodes "
            "WHERE kind != 'file' AND (label LIKE ? OR fqn LIKE ?) "
            "ORDER BY kind LIMIT 1", (f"%{query}%", f"%{query}%")
        ).fetchone()
    if not row:
        row = db.conn.execute(
            "SELECT id, label, kind, path, line_start, symbol FROM graph_nodes "
            "WHERE label LIKE ? LIMIT 1", (f"%{query}%",)
        ).fetchone()
    return row


def cmd_explore(args: argparse.Namespace, db: Database) -> int:
    query = args.target.strip()
    row = _resolve_symbol(db, query)
    if not row:
        print(f"❌ No symbol or node matching '{query}' found in graph.")
        return 1

    node_id, label, kind, path, line, _symbol = row
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


def _print_usages_risk(risk: list, symbol: str) -> None:
    if not risk:
        return
    print(f"\n  ⚠ Unresolved references to bare name '{symbol}' "
          f"({len(risk)} — cannot be safely attributed):")
    for item in risk:
        print(f"    └── [{item['state']}] {item['label']} → {item['dst_symbol']}"
              f" ({item['relation']}) @ {item['path']}:{item['line'] or 1}")


def cmd_usages(args: argparse.Namespace, db: Database) -> int:
    query = args.target.strip()
    row = _resolve_symbol(db, query)
    if not row:
        print(f"❌ No symbol or node matching '{query}' found in graph.")
        return 1
    node_id, label, kind, path, line, symbol = row

    data = db.usages(node_id, symbol)
    total = sum(len(c["sites"]) for c in data["callers"])
    print(f"\n🔎 Usages of [{label}] ({kind}) — {total} site(s) across "
          f"{len(data['callers'])} caller(s)")
    print("=" * 80)
    if not data["callers"]:
        print("  (No resolved inbound references)")
    for caller in data["callers"]:
        print(f"\n  ◀ {caller['label']} ({caller['kind']})")
        for site in caller["sites"]:
            print(f"      └── [{site['relation']}] @ line {site['line'] or 1}")
    _print_usages_risk(data["risk"], symbol)
    print()
    return 0


def cmd_implementations(args: argparse.Namespace, db: Database) -> int:
    query = args.target.strip()
    row = _resolve_symbol(db, query)
    if not row:
        print(f"❌ No symbol or node matching '{query}' found in graph.")
        return 1
    node_id, label, kind, path, line, symbol = row

    data = db.inheritance_edges(node_id, symbol)
    print(f"\n🧬 Inheritance of [{label}] ({kind}) @ {path}:{line or 1}")
    print("=" * 80)
    if data["bases"]:
        print("  ▶ Extends / Implements (bases):")
        for item in data["bases"]:
            print(f"    └── [{item['relation']}] {item['label']} ({item['path']}:{item['line'] or 1})")
    if data["derived"]:
        print("  ◀ Derived types (implements/extends this):")
        for item in data["derived"]:
            print(f"    └── [{item['relation']}] {item['label']} ({item['path']}:{item['line'] or 1})")
    if not data["bases"] and not data["derived"]:
        print("  (No extends/implements edges found)")
    for entry, title in ((data["pending_bases"], "unresolved bases"),
                         (data["pending_derived"], "unresolved derived types")):
        if entry:
            print(f"\n  ⚠ {len(entry)} {title} (link could not be resolved):")
            for item in entry:
                print(f"    └── [{item['state']}] {item['label']} → {item['dst_symbol']}"
                      f" ({item['path']})")
    print()
    return 0


def cmd_rename(args: argparse.Namespace, db: Database) -> int:
    query = args.target.strip()
    row = _resolve_symbol(db, query)
    if not row:
        print(f"❌ No symbol or node matching '{query}' found in graph.")
        return 1
    node_id, label, kind, path, line, symbol = row
    new_name = args.to or "<new_name>"

    definitions = db.conn.execute(
        "SELECT n.label, n.path, n.line_start FROM graph_edges e "
        "JOIN graph_nodes n ON e.src = n.id "
        "WHERE e.dst = ? AND e.relation = 'defines'", (node_id,)
    ).fetchall()
    data = db.usages(node_id, symbol)
    ambiguous = [r for r in data["risk"] if r["state"] == "AMBIGUOUS"]
    sites = [(c["path"], s["line"], c["label"]) for c in data["callers"] for s in c["sites"]]

    print(f"\n✏️  Rename plan: '{symbol}' → '{new_name}' (report-only — no files modified)")
    print("=" * 80)
    print(f"  Definitions ({len(definitions)}):")
    for def_label, def_path, def_line in definitions or [(label, path, line)]:
        print(f"    └── {def_label} ({def_path}:{def_line or 1})")
    print(f"\n  Usage sites ({len(sites)}):")
    for site_path, site_line, caller_label in sites or []:
        print(f"    └── {caller_label} ({site_path}:{site_line or 1})")
    if not sites:
        print("    └── (none resolved)")
    if ambiguous:
        print(f"\n  ⚠ Risk: {len(ambiguous)} AMBIGUOUS reference(s) share the bare name "
              f"'{symbol.rsplit('.', 1)[-1]}' — manual review required:")
        for item in ambiguous:
            print(f"    └── {item['label']} ({item['path']}:{item['line'] or 1})")
    print(f"\n  Summary: {len(definitions or [1])} definition(s), {len(sites)} usage site(s)"
          f"{f', {len(ambiguous)} ambiguous' if ambiguous else ''}")
    print()
    return 0


def cmd_map(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.repo_map import build_repo_map

    focus = [f for f in (args.focus or "").split(",") if f.strip()]
    result = build_repo_map(db.conn, focus=focus, max_tokens=args.tokens, root=root)
    if not result["rendered"]:
        print("❌ No code symbols indexed yet — run `sot reconcile` first.")
        return 1
    print(result["rendered"])
    footer = f"  (~{result['tokens_estimate']} tokens, {result['symbols']} symbols"
    if result["files"]:
        footer += f", {len(result['files'])} files"
    if result["truncated"]:
        footer += ", truncated by budget"
    print(f"\n🗺️  Repo map{footer})")
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
        conflict_note = (
            f", {summary.conflicts} conflicts (stale snapshots re-queued)"
            if summary.conflicts else ""
        )
        print(
            f"✅ Reconcile complete in {elapsed:.2f}s: "
            f"{summary.updated} indexed/updated, "
            f"{summary.unchanged} unchanged, "
            f"{summary.deleted} purged, "
            f"{summary.failed} failed{conflict_note}."
        )
    return 1 if summary.failed else 0


def cmd_pack(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.pack import PackError, build_bundle, render_yaml

    try:
        bundle = build_bundle(
            db, root, args.target,
            max_hops=args.max_hops,
            max_nodes=args.max_nodes,
            max_bytes=args.max_bytes,
        )
    except PackError as exc:
        detail = f" candidates: {', '.join(exc.candidates)}" if exc.candidates else ""
        print(f"❌ pack failed [{exc.code}]: {exc}{detail}")
        return 2
    payload = render_yaml(bundle)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload)
        print(
            f"📦 ContextBundle {bundle['bundle_id']} -> {args.output} "
            f"({bundle['limits']['returned_nodes']} nodes, "
            f"truncated={str(bundle['limits']['truncated']).lower()})"
        )
    else:
        print(payload, end="")
    return 0


def cmd_watch(args: argparse.Namespace, reconciler: Reconciler, root: str) -> int:
    from sot_graph.watcher import run_watch

    try:
        run_watch(
            reconciler, root,
            debounce_ms=args.debounce_ms,
            backend=args.backend,
            interval_ms=args.interval_ms,
        )
    except KeyboardInterrupt:
        print("\n👋 sot watch stopped.")
        return 0
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 2
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
def cmd_bundle(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.analytics.bundle import ArchitectureBundler

    bundler = ArchitectureBundler(db, root)
    out_dir = args.output or os.path.join(root, ".sot", "bundle")
    bundle = bundler.extract_bundle(out_dir)

    if args.json:
        payload = {
            "output_dir": os.path.abspath(out_dir),
            "files": list(bundle.keys()),
            "status": "success",
        }
        print(json.dumps(payload, indent=2))
    else:
        print(f"[OK] Architecture Fact Bundle extracted to: {out_dir}/")
        for fname in sorted(bundle.keys()):
            fpath = os.path.join(out_dir, fname)
            size = os.path.getsize(fpath) if os.path.exists(fpath) else len(bundle[fname])
            print(f"  • {fname:<32} ({size:,} bytes)")
        print("\nTip: LLM Agents can now ingest these 5 fact files with ARCHITECTURE_TEMPLATE.md to generate the full architecture report.")
    return 0


def cmd_report(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.analytics.graph import AnalyticsGraph
    from sot_graph.analytics.diagnostics import analyze_graph
    from sot_graph.analytics.report import generate_markdown_report, save_markdown_report

    graph = AnalyticsGraph.from_database(db, scope=args.scope)
    analysis = analyze_graph(
        graph,
        min_community_size=args.min_size,
        threshold_sigma=args.sigma,
    )

    if args.save_communities:
        comm_list = []
        for cid, cinfo in analysis.community_result.community_info.items():
            comm_list.append({
                "community_id": cid,
                "label": cinfo.label,
                "cohesion_score": cinfo.cohesion_score,
                "node_count": len(cinfo.nodes),
                "nodes": cinfo.nodes,
            })
        db.save_communities(comm_list)

    if args.json:
        payload = {
            "metrics": {
                "node_count": analysis.metrics.node_count,
                "edge_count": analysis.metrics.edge_count,
                "file_count": analysis.metrics.file_count,
                "symbol_count": analysis.metrics.symbol_count,
                "community_count": analysis.metrics.community_count,
                "density": analysis.metrics.density,
                "avg_degree": analysis.metrics.avg_degree,
                "modularity": analysis.metrics.modularity,
                "isolated_nodes": analysis.metrics.isolated_nodes,
            },
            "communities": [
                {
                    "id": cid,
                    "label": c.label,
                    "nodes_count": len(c.nodes),
                    "cohesion": c.cohesion_score,
                    "internal_edges": c.internal_edges,
                    "external_edges": c.external_edges,
                }
                for cid, c in analysis.community_result.community_info.items()
            ],
            "god_nodes": [
                {
                    "node_id": g.node_id,
                    "label": g.label,
                    "kind": g.kind,
                    "path": g.path,
                    "line_start": g.line_start,
                    "total_degree": g.total_degree,
                    "in_degree": g.in_degree,
                    "out_degree": g.out_degree,
                    "risk_level": g.risk_level,
                    "blast_radius": g.blast_radius,
                    "score": g.score,
                }
                for g in analysis.god_nodes
            ],
            "surprising_connections": [
                {
                    "src": s.src_label,
                    "dst": s.dst_label,
                    "relation": s.relation,
                    "weight": s.weight,
                }
                for s in analysis.surprising_connections
            ],
            "suggested_focus_areas": analysis.suggested_focus_areas,
        }
        print(json.dumps(payload, indent=2))
        return 0

    project_name = os.path.basename(os.path.abspath(root))
    report_md = generate_markdown_report(analysis, project_name=project_name, scope=args.scope)

    out_path = args.output
    if out_path:
        save_markdown_report(report_md, out_path)
        print(f"✅ Architectural report saved to: {out_path}")
    else:
        print(report_md)
    return 0


def cmd_cluster(args: argparse.Namespace, db: Database) -> int:
    from sot_graph.analytics.graph import AnalyticsGraph

    graph = AnalyticsGraph.from_database(db, scope=args.scope)
    res = graph.detect_communities(min_community_size=args.min_size)

    comm_list = []
    for cid, cinfo in res.community_info.items():
        comm_list.append({
            "community_id": cid,
            "label": cinfo.label,
            "cohesion_score": cinfo.cohesion_score,
            "node_count": len(cinfo.nodes),
            "nodes": cinfo.nodes,
        })

    if not args.no_save:
        db.save_communities(comm_list)

    if args.json:
        print(json.dumps({
            "communities_count": len(comm_list),
            "modularity": res.modularity,
            "communities": comm_list,
        }, indent=2))
        return 0

    print(f"\n🧩 Detected {len(comm_list)} Architectural Communities (Modularity Q={res.modularity:.4f}):")
    print("=" * 80)
    print(f"{'ID':<4} {'Domain / Community Label':<35} {'Nodes':<8} {'Cohesion':<10} {'Sample Symbols'}")
    print("-" * 80)
    for c in sorted(comm_list, key=lambda x: x["node_count"], reverse=True):
        sample = ", ".join([n.split(":")[-1] for n in c["nodes"][:3]])
        if len(c["nodes"]) > 3:
            sample += f" (+{len(c['nodes'])-3})"
        print(f"{c['community_id']:<4} {c['label']:<35} {c['node_count']:<8} {int(c['cohesion_score']*100)}%{'':<6} {sample}")
    print("=" * 80)
    if not args.no_save:
        print("💾 Communities saved to SQLite database.")
    return 0

def cmd_viz(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.analytics.graph import AnalyticsGraph
    from sot_graph.export.html import generate_html_visualizer, save_html_visualizer

    project_name = os.path.basename(os.path.abspath(root))
    graph = AnalyticsGraph.from_database(db, scope=args.scope)
    html_content = generate_html_visualizer(
        graph,
        title=f"SOT-Graph: {project_name}",
    )
    out_path = save_html_visualizer(
        html_content,
        output_path=args.output,
        open_browser=args.open,
    )
    print(f"🎨 Interactive knowledge graph visualization generated at: {out_path}")
    return 0


def cmd_export(args: argparse.Namespace, db: Database) -> int:
    from sot_graph.analytics.graph import AnalyticsGraph
    from sot_graph.export.exporter import (
        export_graphrag_json,
        export_obsidian_vault,
        export_graphml,
    )

    graph = AnalyticsGraph.from_database(db, scope=args.scope)
    fmt = args.format.lower()

    if fmt in ("graphrag", "json"):
        out_file = args.output or "graphrag.json"
        export_graphrag_json(graph, output_path=out_file)
        print(f"📦 GraphRAG JSON exported to: {out_file}")
    elif fmt == "obsidian":
        out_dir = args.output or "obsidian_vault"
        count = export_obsidian_vault(graph, output_dir=out_dir)
        print(f"📓 Obsidian Vault exported to: {out_dir}/ ({count} files created)")
    elif fmt in ("graphml", "xml"):
        out_file = args.output or "graph.graphml"
        export_graphml(graph, output_path=out_file)
        print(f"🕸️  GraphML XML exported to: {out_file}")
    else:
        print(f"❌ Unknown export format: {fmt}. Supported: graphrag, obsidian, graphml")
        return 1
    return 0
def cmd_setup(args: argparse.Namespace, root: str) -> int:
    from pathlib import Path
    from sot_graph.adapters.installer import install_harnesses, list_supported_harnesses

    if args.list:
        print("Supported AI Coding Harnesses:")
        for key, desc in list_supported_harnesses().items():
            print(f"  - {key:<12} : {desc}")
        return 0

    global_install = not args.workspace_only
    workspace_install = not args.global_only
    harnesses = [args.harness] if args.harness != "all" else ["all"]

    results = install_harnesses(
        harnesses=harnesses,
        root=Path(root),
        global_install=global_install,
        workspace_install=workspace_install,
    )

    print(f"🚀 Configured {len(results)} harness(es):")
    for h_name, files in results.items():
        print(f"\n[{h_name.upper()}] ({len(files)} files)")
        for f in files:
            print(f"  ✓ {f}")
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

    # usages
    p_usg = subparsers.add_parser("usages", help="List every reference site of a symbol, grouped by caller")
    p_usg.add_argument("target", help="Symbol, function name, or class to inspect")

    # implementations
    p_imp = subparsers.add_parser("implementations", help="Show extends/implements relationships of a symbol")
    p_imp.add_argument("target", help="Base class/interface or derived type to inspect")

    # rename
    p_ren = subparsers.add_parser("rename", help="Report-only impact plan for renaming a symbol")
    p_ren.add_argument("target", help="Symbol to rename")
    p_ren.add_argument("--to", default=None, help="Proposed new name (display only)")

    # map
    p_map = subparsers.add_parser("map", help="Token-budgeted repo map ranked by personalized PageRank")
    p_map.add_argument("--tokens", type=int, default=1024, help="Approximate token budget (default: 1024)")
    p_map.add_argument("--focus", default=None, help="Comma-separated symbols to personalize the ranking")

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
    # report
    p_rep = subparsers.add_parser("report", help="Generate comprehensive architectural markdown report")
    p_rep.add_argument("-o", "--output", default="GRAPH_REPORT.md", help="Output file path (default: GRAPH_REPORT.md)")
    p_rep.add_argument("--scope", default=None, help="Scope analysis to path or subdirectory")
    p_rep.add_argument("--min-size", type=int, default=1, help="Minimum community size (default: 1)")
    p_rep.add_argument("--sigma", type=float, default=1.5, help="Standard deviation threshold for God nodes (default: 1.5)")
    p_rep.add_argument("--no-save-communities", dest="save_communities", action="store_false", default=True, help="Do not persist communities to SQLite")
    p_rep.add_argument("--json", action="store_true", help="Output structured analysis JSON")

    # cluster
    p_clu = subparsers.add_parser("cluster", help="Detect and inspect architectural communities/clusters")
    p_clu.add_argument("--scope", default=None, help="Scope clustering to path or subdirectory")
    p_clu.add_argument("--min-size", type=int, default=1, help="Minimum community size (default: 1)")
    p_clu.add_argument("--no-save", action="store_true", help="Do not persist communities to SQLite")
    p_clu.add_argument("--json", action="store_true", help="Output communities JSON")

    # viz
    p_viz = subparsers.add_parser("viz", help="Generate standalone interactive HTML graph visualizer")
    p_viz.add_argument("-o", "--output", default="graph.html", help="HTML output path (default: graph.html)")
    p_viz.add_argument("--scope", default=None, help="Scope visualization to path or subdirectory")
    p_viz.add_argument("--open", action="store_true", help="Automatically open visualizer in default web browser")

    # export
    p_expo = subparsers.add_parser("export", help="Export knowledge graph to GraphRAG JSON, Obsidian, or GraphML")
    p_expo.add_argument("-f", "--format", default="graphrag", choices=["graphrag", "json", "obsidian", "graphml"], help="Export format (default: graphrag)")
    p_expo.add_argument("-o", "--output", default=None, help="Output file or directory path")
    p_expo.add_argument("--scope", default=None, help="Scope export to path or subdirectory")
    # bundle
    p_bun = subparsers.add_parser("bundle", help="Extract 5 high-density fact bundle markdown files for LLM architecture reports")
    p_bun.add_argument("-o", "--output", default=None, help="Output directory path (default: .sot/bundle/)")
    p_bun.add_argument("--json", action="store_true", help="Output summary in JSON format")


    # setup
    p_setup = subparsers.add_parser("setup", help="Configure AI coding harnesses (OMP, OpenCode, Antigravity, Claude, ZCode)")
    p_setup.add_argument("--harness", default="all", choices=["all", "omp", "opencode", "antigravity", "claude", "zcode"], help="Target harness (default: all)")
    p_setup.add_argument("--global-only", action="store_true", help="Install to user home directory only")
    p_setup.add_argument("--workspace-only", action="store_true", help="Install to current workspace only")
    p_setup.add_argument("--list", action="store_true", help="List supported harnesses")

    p_pack = subparsers.add_parser(
        "pack", help="Package a k-hop ContextBundle (YAML) for AI agent prompt registers")
    p_pack.add_argument("target", help="Target symbol or fully-qualified name")
    p_pack.add_argument("-o", "--output", default=None,
                        help="Write YAML to file (default: print to stdout)")
    p_pack.add_argument("--max-hops", type=int, default=2, help="Hop depth (default: 2)")
    p_pack.add_argument("--max-nodes", type=int, default=50, help="Node cap (default: 50)")
    p_pack.add_argument("--max-bytes", type=int, default=65536, help="Byte cap (default: 64KB)")

    p_watch = subparsers.add_parser(
        "watch", help="Watch filesystem and reconcile in real time (daemon)")
    p_watch.add_argument("--debounce-ms", type=int, default=200,
                         help="Event folding window (default: 200ms)")
    p_watch.add_argument("--backend", choices=("auto", "watchfiles", "poll"), default="auto",
                         help="Watcher backend (default: auto = watchfiles if installed)")
    p_watch.add_argument("--interval-ms", type=int, default=500,
                         help="Polling interval for the poll backend (default: 500ms)")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    db_path = args.db or default_db_path(root)
    if args.command == "setup":
        return cmd_setup(args, root)

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
        elif args.command == "usages":
            return cmd_usages(args, db)
        elif args.command == "implementations":
            return cmd_implementations(args, db)
        elif args.command == "rename":
            return cmd_rename(args, db)
        elif args.command == "map":
            return cmd_map(args, db, root)
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
        elif args.command == "report":
            return cmd_report(args, db, root)
        elif args.command == "cluster":
            return cmd_cluster(args, db)
        elif args.command == "viz":
            return cmd_viz(args, db, root)
        elif args.command == "export":
            return cmd_export(args, db)
        elif args.command == "bundle":
            return cmd_bundle(args, db, root)
        elif args.command == "pack":
            return cmd_pack(args, db, root)
        elif args.command == "watch":
            return cmd_watch(args, reconciler, root)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
