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
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

import sqlite3

from sot_graph.db import Database
from sot_graph.locking import LockBusy
from sot_graph.reconciler import Reconciler
from sot_graph.envelope import wrap_envelope
from sot_graph.verifier import TrustVerifier, tokenize
from sot_graph.assurance import (
    assured_query_context,
    envelope_fed_kwargs,
    federated_extras,
    resolve_federated_spec,
    resolve_symbol,
    stale_files_warning,
)
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
        if args.dry_run:
            deleted = dict(plan.counts)
        else:
            with db.write_lock():
                deleted = db.apply_clean(plan)
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
        with db.write_lock():
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
    """Return the default DB path without following an outside symlink."""
    canonical_root = os.path.realpath(os.path.abspath(root))

    def inside(candidate: str) -> bool:
        try:
            return os.path.commonpath((canonical_root, candidate)) == canonical_root
        except ValueError:
            return False

    sot_dir = os.path.join(canonical_root, ".sot")
    if os.path.lexists(sot_dir) and not inside(os.path.realpath(sot_dir)):
        raise ValueError("default .sot directory resolves outside the project root")

    db_path = os.path.join(sot_dir, "sot.db")
    if os.path.islink(db_path) and not inside(os.path.realpath(db_path)):
        raise ValueError("default .sot/sot.db symlink resolves outside the project root")
    return db_path

# P4 ranking: exact identity + scope + path proximity + provider
# evidence + freshness, each factor surfaced as a human-readable reason
# so every top-k row carries its provenance.
_RANK_ORDER = {"STRONG": 0, "REBUILT": 0, "WEAK": 1, "NOPATH": 2, "STALE": 3, "REMOVED": 4}


def _identity_grade(row: Dict[str, Any], query: str) -> Tuple[int, str]:
    """0 exact symbol, 1 exact label/fqn, 2 name-prefix, 3 body-only."""
    q = query.strip().strip('"\'' )
    symbol = (row.get("label") or "").strip()
    if q and symbol == q:
        return 0, "exact symbol name match"
    fqn = (row.get("fqn") or "").strip()
    if q and (fqn == q or fqn.endswith("." + q) or fqn.endswith("::" + q)):
        return 1, "qualified-name match"
    if q and symbol.lower().startswith(q.lower()):
        return 2, "symbol name prefix match"
    return 3, "text match only"


def _rank_reasons(row: Dict[str, Any], grade_reason: str, evidence_count: int,
                  scope: Optional[str]) -> List[str]:
    reasons = [f"verdict={row['verdict']}", grade_reason]
    ev = (row.get("evidence") or {}).get("freshness", "")
    if ev:
        reasons.append(f"freshness={ev}")
    if evidence_count:
        reasons.append(f"provider evidence rows: {evidence_count}")
    if scope:
        reasons.append(f"scope filter: {scope}")
    return reasons


def _p4_sort_key(row: Dict[str, Any]) -> Tuple[int, Any, Any, float]:
    return (
        _RANK_ORDER.get(row["verdict"], 9),
        row["_identity_grade"],
        -row.get("_evidence_count", 0),
        -float(str(row["coverage"]).replace("%", "") or 0),
    )


def cmd_search(args: argparse.Namespace, db: Database, root: str) -> int:
    q_toks = tokenize(args.query)
    hybrid = bool(getattr(args, "hybrid", False))
    if hybrid:
        from sot_graph.vector import available as vec_available, hybrid_search
        if not vec_available():
            print("⚠ sqlite-vec not installed — install with `pip install 'sot-graph[vector]'`; "
                  "falling back to BM25.")
        res = hybrid_search(db, args.query, limit=args.limit * 2,
                            scope=getattr(args, "scope", None))
        candidates = res["results"]
        mode = res["mode"]
    else:
        candidates = db.search_fts(args.query, limit=args.limit, scope=getattr(args, "scope", None))
        mode = "bm25"
    verified = []
    has_stale = False
    jit_enabled = getattr(args, "jit", True)
    for cand in candidates:
        res = TrustVerifier.verify_hit(
            db, cand, q_toks, root, threshold=args.threshold, auto_heal=False, jit_reconcile=jit_enabled
        )
        verdict, cov, real_path = res
        evidence = res.evidence
        if evidence.freshness.value in ("STALE", "MISSING"):
            has_stale = True
        verified.append({
            "verdict": verdict,
            "coverage": f"{int((cov or 0) * 100)}%",
            "label": cand["label"],
            "fqn": cand.get("fqn"),
            "path": real_path or cand.get("path") or "",
            "kind": cand["kind"],
            "line": cand.get("line_start"),
            "body": cand["body"],
            "score": round(cand.get("fused_score", cand["score"]), 6),
            "sources": cand.get("sources"),
            "evidence": evidence.to_dict(),
        })

    # P4 ranking: verdict -> exact-identity grade -> provider evidence ->
    # coverage; every row carries its ranking provenance as reasons.
    scope = getattr(args, "scope", None)
    evidence_counts = db.provider_evidence_counts(
        [v["path"] for v in verified]
    )
    for v in verified:
        grade, grade_reason = _identity_grade(v, args.query)
        v["_identity_grade"] = grade
        v["_evidence_count"] = evidence_counts.get(
            (v["path"], (v.get("label") or "")), 0
        )
        v["reasons"] = _rank_reasons(
            v, grade_reason, v["_evidence_count"], scope
        )
    verified.sort(key=_p4_sort_key)
    final_list = verified[:args.limit]
    for v in final_list:
        v.pop("_identity_grade", None)
        v.pop("_evidence_count", None)

    if args.json:
        envelope = wrap_envelope({"query": args.query, "results": final_list}, db=db, project_root=root)
        print(json.dumps(envelope, indent=2))
        return 0
    mode_note = " [hybrid: bm25+vector]" if hybrid and mode == "hybrid" else ""
    print(f"\n🔍 Knowledge Search: \"{args.query}\" (Found: {len(final_list)} verified hits){mode_note}")
    print("=" * 80)
    if not final_list:
        print("  (No verified matching knowledge found in graph)")
        try:
            from types import SimpleNamespace

            from sot_graph.assurance.coverage import coverage_note, repo_coverage

            report = repo_coverage(SimpleNamespace(conn=db.conn), root)
            print(f"  ⚠️  {coverage_note(report)} — absence is only claimed "
                  "within covered scope")
        except Exception:
            pass
        return 0

    for i, r in enumerate(final_list, 1):
        cov_str = f"cov:{r['coverage']}" if r['coverage'] != "0%" else ""
        loc = f"{r['path']}:{r['line']}" if r.get('line') else r['path']
        print(f"  {i:2d}. [{r['verdict']:^7}] {cov_str:^8} {r['label']}")
        if loc:
            print(f"      📍 File: {loc}")
        first_line = r['body'].splitlines()[0][:110]
        print(f"      💡 Content: {first_line}...")
        if r.get("reasons"):
            print(f"      🧾 Rank: {'; '.join(r['reasons'])}")
        print()

    if has_stale:
        print("  💡 Tip: Some files have changed on disk. Run 'sot reconcile' to synchronize the graph.")

    return 0


# -----------------------------------------------------------------------
# Federated provider orchestration moved to sot_graph.assurance (P2):
# spec parsing + capability routing (.routing), federation plan, typed
# query outcomes, candidate normalization, conflict adjudication
# (.orchestrator), symbol resolution + assurance context (.engine).
# This file keeps only argument parsing and output rendering.
# -----------------------------------------------------------------------
def _print_fed_warnings(fed: Optional[dict]) -> None:
    """Emit federation fallback warnings on stderr (both output modes)."""
    if fed is None:
        return
    for warning in fed["warnings"]:
        print(f"⚠️  {warning}", file=sys.stderr)


def _print_federation_notes(fed: Optional[dict]) -> None:
    """Emit federation warnings/notes for non-JSON output modes."""
    _print_fed_warnings(fed)
    if fed is None:
        return
    if fed["candidates"]:
        conflicts = len(fed["conflicts"])
        verdicts = {cand["verdict"] for cand in fed["candidates"]}
        cap = "SUPPORTED" if "SUPPORTED" in verdicts else (
            "/".join(sorted(verdicts)) if verdicts else "UNVERIFIABLE"
        )
        print(
            f"\n🔗 Federation: {len(fed['candidates'])} external candidate(s) "
            f"(max {cap}), {conflicts} conflict(s) recorded"
        )
        for cand in fed["candidates"][:10]:
            subj = cand["subject"]
            loc = f"{subj.get('path') or ''}:{subj.get('start_line') or '?'}"
            print(f"    └── [{cand['verdict']}] {subj.get('qualified_name')} @ {loc}")



def cmd_providers_sync(args: argparse.Namespace, root: str,
                       db_path: Optional[str] = None) -> int:
    """Explicit index sync with its own budget, lock, progress, and receipt.

    Wraps the provider's ``index_repository`` (P3.1): never triggered from a
    read path, guarded by the project write lock so concurrent sot writes
    cannot interleave with an external reindex, and always emits a receipt
    (JSON or text) recording what ran and how it ended.
    """
    from dataclasses import asdict

    from sot_graph.config import load_config
    from sot_graph.db import Database
    from sot_graph.locking import LockBusy, WriteLock
    from sot_graph.providers.base import IndexRequest
    from sot_graph.providers.codebase_memory import CodebaseMemoryProvider
    from sot_graph.providers_registry import ADAPTER_PROBED_PROVIDERS

    name = getattr(args, "provider_name", "")
    pcfg = load_config(root).providers.get(name)
    if pcfg is None or pcfg.name not in ADAPTER_PROBED_PROVIDERS:
        print(
            f"❌ sync is not available for provider '{name}'; "
            f"supported: {', '.join(sorted(ADAPTER_PROBED_PROVIDERS))}"
        )
        return 1

    timeout = float(getattr(args, "timeout", 0) or 0) or None
    progress = bool(getattr(args, "progress", False))
    lock_path = os.path.join(root, ".sot", "write.lock")
    pruned: Optional[Dict[str, int]] = None
    try:
        with WriteLock(lock_path, timeout_ms=60_000):
            # The ledger connection is opened only for the sync itself, so
            # the provider records the index run it just executed.
            db = Database(db_path or os.path.join(root, ".sot", "sot.db"))
            try:
                provider = CodebaseMemoryProvider(config=pcfg, db=db)
                record = provider.index(
                    IndexRequest(repo_root=root, timeout_seconds=timeout),
                    progress=progress,
                )
                # A successful sync just appended run + evidence rows, so
                # prune older ledger history now while the write lock is
                # held. Feature-detected so stub Databases without
                # retention support keep working.
                if record.status == "ok":
                    purge_history = getattr(db, "purge_history", None)
                    if callable(purge_history):
                        pruned = cast(Dict[str, int], purge_history())
            finally:
                db.close()
    except LockBusy:
        print(
            "❌ another sot writer holds the project lock; "
            "retry 'sot providers sync' once it finishes"
        )
        return 1

    receipt = asdict(record)
    if getattr(args, "json", False):
        print(json.dumps({"providers_sync": receipt}, indent=2))
    else:
        status_icon = "✅" if record.status == "ok" else "⚠️ "
        print(f"{status_icon} sot providers sync {name}: {record.status}")
        print(f"   capability   : {record.capability}")
        print(f"   exit_code    : {record.exit_code}")
        print(f"   duration_ms  : {record.duration_ms}")
        print(f"   detail       : {record.detail}")
        if record.next_action:
            print(f"   next_action  : {record.next_action}")
        if pruned and any(pruned.values()):
            print(
                f"   history      : pruned {pruned['provider_runs']} run(s), "
                f"{pruned['provider_evidence']} evidence row(s), "
                f"{pruned['snapshots']} snapshot(s)"
            )
    return 0 if record.status == "ok" else 1


def cmd_explore(args: argparse.Namespace, db: Database, root: str = ".") -> int:
    query = args.target.strip()
    row = resolve_symbol(db, query)
    if not row:
        print(f"❌ No symbol or node matching '{query}' found in graph.")
        return 1

    node_id, label, kind, path, line, _symbol = row
    fed = federated_extras(
        resolve_federated_spec(getattr(args, "provider", None), root),
        root, "explore", query, builtin_target=(_symbol, path, line),
        db=db,
    )
    if fed is not None and fed["fail_message"]:
        print(f"❌ {fed['fail_message']}", file=sys.stderr)
        return 2
    relations = db.explore_node(node_id, depth=args.depth)
    snapshot_dict, stale = assured_query_context(
        db, root, [path] + [r.get("path") for r in relations]
    )

    if getattr(args, "json", False):
        import json
        hop_summary = {
            "1_hop_direct": sum(1 for r in relations if r.get("hop") == 1),
            "2_hop_transitive": sum(1 for r in relations if r.get("hop") == 2),
        }
        payload = {
            "target": {
                "id": node_id,
                "label": label,
                "kind": kind,
                "path": path,
                "line": line or 1,
            },
            "depth": args.depth,
            "relations_count": len(relations),
            "hop_summary": hop_summary,
            "relations": relations,
            "snapshot": snapshot_dict,
            "stale_files": stale,
        }
        if fed is not None:
            _print_fed_warnings(fed)
            payload["external_candidates"] = fed["candidates"]
            envelope = wrap_envelope(payload, db=db, **envelope_fed_kwargs(db, fed))
        else:
            envelope = wrap_envelope(payload, db=db)
        print(json.dumps(envelope, indent=2))
        return 0

    print(f"\n🌐 Graph Walk: [{label}] ({kind}) @ {path}:{line or 1}")
    print("=" * 80)
    warning = stale_files_warning(stale)
    if warning:
        print(f"  ⚠ {warning}")

    if not relations:
        print("  (No inbound or outbound connections found)")
        return 0

    show_all = getattr(args, "show_all", False)
    hub_threshold = 15
    def _render_section(title: str, items: list, is_transitive: bool = False):
        if not items:
            return
        print(f"\n{title} ({len(items)}):")
        displayed = items if show_all or len(items) <= hub_threshold else items[:hub_threshold]
        for r in displayed:
            via_info = ""
            if is_transitive and r.get("via_label"):
                via_info = f" [via {r['via_label']} @ {r.get('via_path', '')}]"
            arrow = "➔" if r["direction"] == "outward" else "◀"
            print(f"    └── [{r['relation']}] {arrow} {r['label']} ({r['path']}:{r['line'] or 1}){via_info}")
        if len(items) > len(displayed):
            collapsed = len(items) - len(displayed)
            print(f"    └── ... +{collapsed} more references collapsed (use --all to show full list)")

    outward_direct = [r for r in relations if r["direction"] == "outward" and r.get("hop", 1) == 1]
    outward_trans = [r for r in relations if r["direction"] == "outward" and r.get("hop", 1) > 1]
    inward_direct = [r for r in relations if r["direction"] == "inward" and r.get("hop", 1) == 1]
    inward_trans = [r for r in relations if r["direction"] == "inward" and r.get("hop", 1) > 1]

    _render_section("▶ 1-Hop Direct Outward Calls", outward_direct, is_transitive=False)
    _render_section("▶ 2-Hop Transitive Outward Calls", outward_trans, is_transitive=True)
    _render_section("◀ 1-Hop Direct Inward References (Used by)", inward_direct, is_transitive=False)
    _render_section("◀ 2-Hop Transitive Inward References", inward_trans, is_transitive=True)

    _print_federation_notes(fed)
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


def cmd_usages(args: argparse.Namespace, db: Database, root: str = ".") -> int:
    query = args.target.strip()
    row = resolve_symbol(db, query)
    if not row:
        print(f"❌ No symbol or node matching '{query}' found in graph.")
        return 1
    node_id, label, kind, path, line, symbol = row
    fed = federated_extras(
        resolve_federated_spec(getattr(args, "provider", None), root),
        root, "usages", query, builtin_target=(symbol, path, line),
        db=db,
    )
    if fed is not None and fed["fail_message"]:
        print(f"❌ {fed['fail_message']}", file=sys.stderr)
        return 2

    data = db.usages(node_id, symbol)
    snapshot_dict, stale = assured_query_context(
        db, root,
        [path] + [c.get("path") for c in data["callers"]]
        + [r.get("path") for r in data.get("risk", [])],
    )
    total = sum(len(c["sites"]) for c in data["callers"])
    unresolved_count = data.get("unresolved_count", len(data.get("risk", [])))
    data["snapshot"] = snapshot_dict
    data["stale_files"] = stale

    if getattr(args, "json", False):
        if fed is not None:
            _print_fed_warnings(fed)
            data["external_candidates"] = fed["candidates"]
            envelope = wrap_envelope(data, db=db, **envelope_fed_kwargs(db, fed))
        else:
            envelope = wrap_envelope(data, db=db)
        print(json.dumps(envelope, indent=2))
        return 0

    print(f"\n🔎 Usages of [{label}] ({kind}) — {total} site(s) across "
          f"{len(data['callers'])} caller(s)")
    print("=" * 80)
    warning = stale_files_warning(stale)
    if warning:
        print(f"  ⚠ {warning}")
    if not data["callers"]:
        if unresolved_count > 0:
            print(f"  ⚠ 0 confirmed usages, but {unresolved_count} UNRESOLVED/AMBIGUOUS candidate(s) exist in graph.")
        else:
            print("  (No confirmed inbound references or pending candidates)")
    for caller in data["callers"]:
        print(f"\n  ◀ {caller['label']} ({caller['kind']})")
        for site in caller["sites"]:
            print(f"      └── [{site['relation']}] @ line {site['line'] or 1}")
    _print_usages_risk(data["risk"], symbol)
    if data.get("next_steps"):
        print("\n  👉 Next Steps:")
        for step in data["next_steps"]:
            print(f"     • {step}")
    _print_federation_notes(fed)
    print()
    return 0


def cmd_implementations(args: argparse.Namespace, db: Database) -> int:
    query = args.target.strip()
    row = resolve_symbol(db, query)
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
    row = resolve_symbol(db, query)
    if not row:
        print(f"❌ No symbol or node matching '{query}' found in graph.")
        return 1
    node_id, label, kind, path, line, symbol = row
    new_name = args.to or "<new_name>"

    definers = db.conn.execute(
        "SELECT n.label, n.path, n.line_start FROM graph_edges e "
        "JOIN graph_nodes n ON e.src = n.id "
        "WHERE e.dst = ? AND e.relation = 'defines'", (node_id,)
    ).fetchall()
    data = db.usages(node_id, symbol)
    ambiguous = [r for r in data["risk"] if r["state"] == "AMBIGUOUS"]
    sites = [(c["path"], s["line"], c["label"]) for c in data["callers"] for s in c["sites"]]

    print(f"\n✏️  Rename plan: '{symbol}' → '{new_name}' (report-only — no files modified)")
    print("=" * 80)
    # The definition site is the resolved symbol itself; 'defines' edges point
    # at the enclosing scope (file or class), which is context, not the site.
    print("  Definitions (1):")
    print(f"    └── {label} ({path}:{line or 1})")
    for def_label, def_path, def_line in definers:
        print(f"    └── declared inside: {def_label} ({def_path}:{def_line or 1})")
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
    print(f"\n  Summary: 1 definition, {len(sites)} usage site(s)"
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


def cmd_embed(args: argparse.Namespace, db: Database) -> int:
    from sot_graph.vector import available as vec_available, index_nodes
    from sot_graph.locking import LockBusy

    if not vec_available():
        print("❌ sqlite-vec is not installed. Install with: pip install 'sot-graph[vector]'")
        return 2
    try:
        with db.write_lock():
            stats = index_nodes(db.conn, cap=getattr(args, "limit", 5000))
    except (LockBusy, RuntimeError) as exc:
        print(f"❌ embed failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"✅ Embedded {stats['embedded']} graph nodes into the vector index "
        f"({stats['unchanged']} unchanged, {stats['pruned']} pruned; "
        "dim=256, HashEmbedder)."
    )
    if stats["truncated"]:
        print(
            f"   ⚠️  truncated: {stats['total_nodes']} embeddable nodes exceed "
            f"the cap ({stats['cap']}); the newest nodes are covered first."
        )
    print("   Plug a neural embedder via sot_graph.vector for semantic recall.")
    return 0


def cmd_insert(args: argparse.Namespace, db: Database) -> int:
    from sot_graph.locking import LockBusy

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    content = f"{args.title}\n{args.body}"
    node_id = f"note:{hashlib.sha256(content.encode()).hexdigest()[:12]}"
    now = int(time.time())
    kw_str = " ".join(keywords)

    try:
        with db.write_lock():
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
    except (LockBusy, RuntimeError) as exc:
        print(f"❌ insert failed: {exc}", file=sys.stderr)
        return 1
    print(f"✅ Stored knowledge node [{node_id}] '{args.title}'")
    return 0

def cmd_reconcile(args: argparse.Namespace, reconciler: Reconciler) -> int:
    start_t = time.time()
    try:
        summary = reconciler.reconcile(
            paths=args.paths,
            workers=args.workers,
            batch_size=args.batch_size,
            force=getattr(args, "force", False),
        )
    except KeyboardInterrupt:
        return 130
    elapsed = time.time() - start_t
    if getattr(args, "receipt", False):
        from sot_graph.assurance.receipts import reconcile_receipt
        receipt = reconcile_receipt(reconciler.db, reconciler.root_dir, reconcile_result=summary.as_dict())
        print(json.dumps(receipt, indent=2))
    elif args.json:
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
def _reconcile_single_repo(repo_dir: str, force: bool = False, workers: int = 1) -> dict:
    """Worker function executed for a single repository in batch reconcile."""
    start_t = time.monotonic()
    abs_repo = os.path.abspath(repo_dir)
    db_path = default_db_path(abs_repo)
    try:
        db = Database(db_path)
        try:
            reconciler = Reconciler(db, abs_repo)
            summary = reconciler.reconcile(force=force, workers=workers)
            st = db.stats()
            duration_ms = int((time.monotonic() - start_t) * 1000)
            return {
                "repo": abs_repo,
                "name": os.path.basename(abs_repo),
                "status": "ok",
                "scanned": summary.scanned,
                "updated": summary.updated,
                "unchanged": summary.unchanged,
                "deleted": summary.deleted,
                "failed": summary.failed,
                "nodes": st.get("nodes", 0),
                "edges": st.get("edges", 0),
                "duration_ms": duration_ms,
            }
        finally:
            db.close()
    except Exception as exc:
        duration_ms = int((time.monotonic() - start_t) * 1000)
        return {
            "repo": abs_repo,
            "name": os.path.basename(abs_repo),
            "status": "error",
            "error": str(exc),
            "scanned": 0,
            "updated": 0,
            "unchanged": 0,
            "deleted": 0,
            "failed": 1,
            "nodes": 0,
            "edges": 0,
            "duration_ms": duration_ms,
        }


def _discover_repos(target_dir: str) -> List[str]:
    """Find all repository roots inside target_dir."""
    abs_target = os.path.abspath(target_dir)
    if not os.path.isdir(abs_target):
        return []

    repo_markers = {".git", ".sot", "package.json", "pyproject.toml", "Cargo.toml", "go.mod", "pom.xml", "pubspec.yaml"}
    try:
        entries = sorted(os.listdir(abs_target))
    except OSError:
        return [abs_target]

    candidates = []
    for entry in entries:
        if entry.startswith("."):
            continue
        child_path = os.path.join(abs_target, entry)
        if os.path.isdir(child_path):
            try:
                child_entries = set(os.listdir(child_path))
                if child_entries & repo_markers or any(os.path.isdir(os.path.join(child_path, m)) for m in [".git", ".sot"]):
                    candidates.append(child_path)
            except OSError:
                pass

    if candidates:
        return candidates
    return [abs_target]


def cmd_batch_reconcile(args: argparse.Namespace, target_dir: str) -> int:
    """Reconcile multiple repositories concurrently with per-repo SQLite DB isolation."""
    from concurrent.futures import ProcessPoolExecutor, as_completed

    repos = _discover_repos(target_dir)
    if not repos:
        print(f"No repositories discovered in: {target_dir}", file=sys.stderr)
        return 1

    max_workers = getattr(args, "workers", None) or min(len(repos), min(8, max(1, os.cpu_count() or 1)))
    force = getattr(args, "force", False)

    start_total = time.monotonic()
    results = []

    if not getattr(args, "json", False):
        print(f"📦 Batch Reconciling {len(repos)} repositories (workers: {max_workers})...\n")

    if max_workers == 1 or len(repos) == 1:
        for r in repos:
            res = _reconcile_single_repo(r, force=force, workers=1)
            results.append(res)
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_repo = {
                executor.submit(_reconcile_single_repo, r, force, 1): r
                for r in repos
            }
            for future in as_completed(future_to_repo):
                results.append(future.result())

    total_duration_ms = int((time.monotonic() - start_total) * 1000)
    results.sort(key=lambda x: x["name"])

    if getattr(args, "json", False):
        print(json.dumps({
            "total_repos": len(repos),
            "duration_ms": total_duration_ms,
            "results": results,
        }, indent=2))
    else:
        print(f"{'Repository':<28} | {'Status':<7} | {'Scanned':<8} | {'Updated':<8} | {'Nodes':<7} | {'Edges':<7} | {'Time'}")
        print("-" * 88)
        tot_scanned = tot_updated = tot_nodes = tot_edges = tot_failed = 0
        for r in results:
            stat_icon = "✅ OK" if r["status"] == "ok" and r["failed"] == 0 else "❌ ERR"
            tot_scanned += r["scanned"]
            tot_updated += r["updated"]
            tot_nodes += r["nodes"]
            tot_edges += r["edges"]
            tot_failed += r["failed"]
            sec = r["duration_ms"] / 1000.0
            print(f"{r['name']:<28} | {stat_icon:<7} | {r['scanned']:<8} | {r['updated']:<8} | {r['nodes']:<7} | {r['edges']:<7} | {sec:.2f}s")
            if r["status"] == "error":
                print(f"  └─ Error: {r.get('error')}")

        print("-" * 88)
        print(f"{'TOTAL (' + str(len(repos)) + ' repos)':<28} | {'':<7} | {tot_scanned:<8} | {tot_updated:<8} | {tot_nodes:<7} | {tot_edges:<7} | {total_duration_ms/1000.0:.2f}s\n")

    return 1 if any(r["status"] == "error" or r["failed"] > 0 for r in results) else 0


def cmd_pack(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.pack import PackError, build_bundle, render_yaml

    try:
        bundle = build_bundle(
            db, root, args.target,
            max_hops=args.max_hops,
            max_nodes=args.max_nodes,
            max_bytes=args.max_bytes,
            max_tokens=getattr(args, "max_tokens", None),
        )
    except PackError as exc:
        detail = f" candidates: {', '.join(exc.candidates)}" if exc.candidates else ""
        print(f"❌ pack failed [{exc.code}]: {exc}{detail}")
        return 2
    if getattr(args, "json", False):
        envelope = wrap_envelope(bundle, db=db, project_root=root)
        payload_json = json.dumps(envelope, indent=2)
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(payload_json)
        else:
            print(payload_json)
        return 0

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
    from sot_graph.watcher import (
        run_watch, run_watch_multi, discover_sot_projects,
        start_daemon, stop_daemon, status_daemon,
        install_service, uninstall_service
    )

    is_all = getattr(args, "all", False)
    base_dir = getattr(args, "dir", None) or root

    # 1. Handle background service install / uninstall
    if getattr(args, "service", None) == "install":
        msg = install_service(base_dir=base_dir, python_bin=sys.executable)
        print(msg)
        return 0
    elif getattr(args, "service", None) == "uninstall":
        msg = uninstall_service()
        print(msg)
        return 0

    # 2. Handle daemon stop
    if getattr(args, "stop", False):
        ok, msg = stop_daemon(root, is_all=is_all)
        print(msg)
        return 0 if ok else 1

    # 3. Handle daemon status
    if getattr(args, "status", False):
        st = status_daemon(root, is_all=is_all)
        print(f"📊 SOT Watcher Daemon Status ({'Global Multi-Project' if is_all else 'Local Project'}):")
        print(f"   Status:   {'🟢 ACTIVE' if st['running'] else '⚪ STOPPED'}")
        if st['pid']:
            print(f"   PID:      {st['pid']}")
        print(f"   Logs:     {st['log_path']}")
        print(f"   Message:  {st['message']}")
        return 0 if st['running'] else 1

    # 4. Handle daemon start
    if getattr(args, "daemon", False):
        ok, msg = start_daemon(
            root=root,
            is_all=is_all,
            base_dir=base_dir,
            debounce_ms=args.debounce_ms,
            interval_ms=args.interval_ms,
            backend=args.backend,
        )
        print(msg)
        return 0 if ok else 1

    # 5. Handle multi-project watch in foreground
    if is_all:
        roots = discover_sot_projects(base_dir)
        if not roots:
            print(f"⚠️ No initialized SOT projects found under {base_dir}")
            return 1
        try:
            run_watch_multi(
                roots=roots,
                debounce_ms=args.debounce_ms,
                backend=args.backend,
                interval_ms=args.interval_ms,
            )
        except KeyboardInterrupt:
            print("\n👋 sot watch --all stopped.")
            return 0
        except RuntimeError as exc:
            print(f"❌ {exc}")
            return 2
        return 0

    # 6. Default foreground single-project watch
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


def cmd_doctor(args: argparse.Namespace, db: Database, root: Optional[str] = None) -> int:
    diag = db.integrity_check()
    if getattr(args, "receipt", False):
        from sot_graph.assurance.receipts import audit_receipt
        repo_root = root or os.path.dirname(os.path.dirname(os.path.abspath(db.db_path)))
        receipt = audit_receipt(db, repo_root, doctor_report=diag)
        print(json.dumps(receipt, indent=2))
        return 0 if diag.get("ok", False) else 1
    if getattr(args, "json", False):
        print(json.dumps(diag, indent=2))
        return 0 if diag.get("ok", False) else 1
    st = diag["stats"]
    print("\n🩺 SOT-Graph Doctor Report:")
    print("=" * 55)
    status_icon = "✅ OK" if diag["quick_check"] == "ok" else "❌ CORRUPTED"
    print(f"  • SQLite Database   : {db.db_path}")
    print(f"  • Integrity Check   : {status_icon} (quick_check: {diag['quick_check']})")
    print(f"  • Journal Mode      : {diag['journal_mode']} (schema v{diag['schema_version']})")
    print(f"  • DB Storage Size   : {diag['db_size_bytes']:,} bytes ({diag['page_count']} pages @ {diag['page_size']}B)")
    print("-" * 55)
    print(f"  • Tracked Files     : {st['paths']}")
    print(f"  • Graph Nodes       : {st['nodes']}")
    print(f"  • FTS5 Sync Records : {st.get('fts_count', 0)}")
    print(f"  • Confirmed Edges   : {st['edges']}")
    print(f"  • Pending Edges     : {st['pending']} (Unresolved: {st['pending_unresolved']}, Ambiguous: {st['pending_ambiguous']})")
    if st.get("orphaned_nodes", 0) > 0:
        print(f"  ⚠️  Orphaned Nodes  : {st['orphaned_nodes']}")
    
    pb = diag.get("pending_breakdown", {})
    if pb.get("by_relation"):
        rel_str = ", ".join(f"{k}: {v}" for k, v in sorted(pb["by_relation"].items()))
        print(f"  • Pending Relations : {rel_str}")

    if diag.get("warnings"):
        print("\n⚠️  Diagnostic Warnings:")
        for warn in diag["warnings"]:
            print(f"   - {warn}")

    if diag["errors"]:
        print("\n❌  Critical Corruption Issues:")
        for err in diag["errors"]:
            print(f"   - {err}")
        print("=" * 55)
        return 1

    print("=" * 55)
    return 0

def _print_provider_rows(rows: list[dict], title: str) -> None:
    """Render provider rows as a short aligned text table."""
    print(f"\n🧩 {title}")
    header = f"  {'NAME':<18} {'MODE':<10} {'STATUS':<14} {'VERSION':<16} DETAIL"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in rows:
        if not row["installed"]:
            icon = "❌ missing "
        elif not row["healthy"]:
            icon = "⚠️  unhealthy"
        else:
            icon = "✅ healthy "
        version = row.get("version") or "-"
        print(f"  {row['name']:<18} {row['mode']:<10} {icon:<14} {version:<16} {row['detail']}")


def cmd_providers(args: argparse.Namespace, root: str,
                  db_path: Optional[str] = None) -> int:
    """Read-only provider registry commands: detect, list, doctor, resolve."""
    from dataclasses import asdict

    from sot_graph.config import load_config
    from sot_graph.providers_registry import (
        detect_providers,
        providers_doctor,
        resolve_capability,
    )

    fmt = getattr(args, "format", "text")
    sub = args.providers_subcommand

    if sub == "sync":
        return cmd_providers_sync(args, root, db_path=db_path)

    if sub == "cross-check":
        # Read-only evidence reconciliation: unlike the registry reads above
        # this DOES touch the database (graph_edges vs provider_evidence),
        # so it opens the resolved --db target read-only.
        from sot_graph.db import Database
        from sot_graph.providers.cross_check import cross_check

        if not db_path:
            print("❌ No --db target resolved for cross-check.", file=sys.stderr)
            return 1
        try:
            xc_db = Database(db_path, read_only=True)
        except FileNotFoundError:
            print(f"❌ No index database at {db_path}; run `sot reconcile` first.", file=sys.stderr)
            return 1
        try:
            report = cross_check(xc_db, provider=getattr(args, "provider", None))
            if getattr(args, "json", False):
                print(json.dumps(wrap_envelope(report, db=xc_db), indent=2, default=str))
                return 0
            totals = report["totals"]
            print("\n🔍 Provider cross-check (builtin AST vs external evidence):")
            print(f"  builtin pairs (graph_edges)     : {report['builtin_pair_count']}")
            print(f"  external pairs (provider_evidence): {report['external_pair_count']}")
            print(f"  agreements (both claim)         : {totals['agreements']}")
            print(f"  builtin-only (AST found)        : {totals['builtin_only']}")
            print(f"  external-only (review these)    : {totals['external_only']}")
            if totals["unmapped_external_relations"]:
                print(f"  unmapped external relation rows : {totals['unmapped_external_relations']}")
            if report["provider_counts"]:
                print("  external evidence rows per provider:")
                for name, count in report["provider_counts"].items():
                    print(f"    • {name}: {count}")
            print("\n  external-only pairs are candidate hallucinations OR builtin parser gaps — verify each before acting.")
            return 0
        finally:
            xc_db.close()


    if sub == "lifecycle":
        from sot_graph.providers.lifecycle import lifecycle_manifest

        manifest = lifecycle_manifest(root)
        if fmt == "json":
            print(json.dumps(manifest, indent=2))
            return 0
        print(f"Provider lifecycle manifest (schema v{manifest['schema_version']})")
        for entry in manifest["providers"]:
            state = "healthy" if entry["healthy"] else "unhealthy"
            print(f"  {entry['name']}: {state} v{entry['version'] or '?'} "
                  f"[{entry['mode']}] wire_compatible={entry['wire_compatible']}")
        print(f"  update process: {len(manifest['update_process'])} steps "
              "(docs/PROVIDER_LIFECYCLE.md); "
              f"rollback: {manifest['providers'][0]['rollback'][:60]}…"
              if manifest["providers"] else "  no providers configured")
        return 0
    if sub == "detect":
        rows = [asdict(st) for st in detect_providers(root)]
        if fmt == "json":
            print(json.dumps(rows, indent=2))
        else:
            _print_provider_rows(rows, f"Providers detected under {root}")
        return 0

    if sub == "list":
        cfg = load_config(root)
        rows = [
            {
                "name": pcfg.name,
                "enabled": pcfg.enabled,
                "command": list(pcfg.command) if pcfg.command else [],
                "integration": pcfg.integration,
                "index_policy": pcfg.index_policy,
                "timeout_seconds": pcfg.timeout_seconds,
                "capabilities": list(pcfg.capabilities),
            }
            for pcfg in cfg.providers.values()
        ]
        if fmt == "json":
            print(json.dumps(rows, indent=2))
        else:
            print(f"\n🧩 Configured providers under {root} (providers_mode={cfg.providers_mode}, allow_external={cfg.allow_external})")
            for row in rows:
                enabled = {True: "enabled", False: "disabled", None: "auto"}[row["enabled"]]
                caps = ", ".join(row["capabilities"]) or "(none)"
                cmd = " ".join(row["command"]) or "(embedded)"
                print(f"  • {row['name']}: {enabled}, integration={row['integration']}, index_policy={row['index_policy']}, timeout={row['timeout_seconds']:g}s")
                print(f"      command : {cmd}")
                print(f"      caps    : {caps}")
        return 0

    if sub == "doctor":
        report = providers_doctor(root)
        if fmt == "json":
            print(json.dumps(report, indent=2))
        else:
            print(f"\n🩺 Provider Doctor ({report['root']}):")
            print(f"  providers_mode={report['providers_mode']} allow_external={report['allow_external']} conflict_policy={report['conflict_policy']} verification_provider={report['verification_provider']}")
            _print_provider_rows(report["providers"], "Health")
            if report["next_actions"]:
                print("\n⚠️  Recommended next actions:")
                for action in report["next_actions"]:
                    print(f"   - {action}")
            else:
                print("\n✅ All providers healthy.")
        return 0 if report["ok"] else 1

    # resolve
    ranked = [asdict(st) for st in resolve_capability(root, args.capability)]
    if fmt == "json":
        print(json.dumps(ranked, indent=2))
    else:
        print(f"\n🧩 Providers ranked for capability '{args.capability}' under {root}:")
        if not ranked:
            print("  (no available provider)")
        for i, row in enumerate(ranked, start=1):
            version = row.get("version") or "-"
            print(f"  {i}. {row['name']} ({row['mode']}, {version}) — {row['detail']}")
    return 0

def cmd_bundle(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.analytics.bundle import ArchitectureBundler

    include_tests = getattr(args, "include_tests", False)
    bundler = ArchitectureBundler(db, root, include_tests=include_tests)
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

def cmd_trace(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.trace import trace_fullstack, render_trace_markdown

    res = trace_fullstack(db, args.target, depth=getattr(args, "depth", 2))

    # P1.b shared pre-query assurance: bind cited file content beside the
    # result and surface journal staleness (same contract as explore/usages).
    cited_paths: list[str] = []
    for key, path_keys in (
        ("nodes", ("path",)),
        ("ui_navigation", ("file",)),
        ("ui_decisions", ("file",)),
        ("backend_steps", ("file",)),
    ):
        for item in res.get(key, []):
            if isinstance(item, dict):
                for pk in path_keys:
                    p = item.get(pk)
                    if p:
                        cited_paths.append(str(p))
    snapshot_dict, stale = assured_query_context(db, root, cited_paths)
    res["snapshot"] = snapshot_dict
    res["stale_files"] = stale

    if args.json:
        payload = json.dumps(res, indent=2)
        if args.output:
            out_path = os.path.abspath(os.path.join(root, args.output)) if not os.path.isabs(args.output) else args.output
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as fp:
                fp.write(payload)
            print(f"📊 Trace JSON written to: {out_path}")
        else:
            print(payload)
        return 0

    md = render_trace_markdown(res)
    warning = stale_files_warning(stale)
    if warning:
        md = f"⚠ {warning}\n\n{md}"
    if args.output:
        out_path = os.path.abspath(os.path.join(root, args.output)) if not os.path.isabs(args.output) else args.output
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(md)
        print(f"📊 Trace report written to: {out_path}")
    else:
        print(md)
    return 0


def cmd_ui_tree(args: argparse.Namespace, db: Database) -> int:
    from sot_graph.trace import extract_ui_tree

    res = extract_ui_tree(db, args.component)
    if args.json:
        print(json.dumps(res, indent=2))
        return 0

    print(f"🌿 UI Decision Tree: {args.component}")
    print(f"Summary: {res.get('summary', '')}\n")
    branches = res.get("decision_branches", [])
    if not branches:
        print("  (No UI decision branches detected)")
        return 0
    for idx, b in enumerate(branches, 1):
        print(f"  [{idx}] {b.get('type')}: {b.get('target')} (Trigger: {b.get('trigger')}, Condition: {b.get('condition')})")
    return 0


def cmd_be_flow(args: argparse.Namespace, db: Database) -> int:
    from sot_graph.trace import extract_backend_flow

    res = extract_backend_flow(db, args.service)
    if args.json:
        print(json.dumps(res, indent=2))
        return 0

    print(f"⚙️  Backend Processing Flow: {args.service}")
    print(f"Summary: {res.get('summary', '')}\n")
    steps = res.get("execution_steps", [])
    if not steps:
        print("  (No backend execution steps detected)")
        return 0
    for s in steps:
        print(f"  Step {s.get('step_order', 1)} [{s.get('step_category')}]: {s.get('step_name')}")
        print(f"    Code: {s.get('code_statement')}")
        print(f"    Desc: {s.get('step_description')}\n")
    return 0


def cmd_solution(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.solution import generate_feature_inventory, extract_execution_steps, generate_solution_bundle

    sub = getattr(args, "solution_subcommand", "")
    if sub == "inventory":
        out_file = args.output
        if out_file and not os.path.isabs(out_file):
            out_file = os.path.abspath(os.path.join(root, out_file))
        res = generate_feature_inventory(db, args.module or "", out_file=out_file)
        if args.json:
            print(json.dumps(res, indent=2))
        elif out_file:
            print(f"📋 Feature Inventory written to: {out_file} ({res.get('total_features', 0)} features detected)")
        else:
            print(res.get("markdown", ""))
        return 0

    elif sub == "steps":
        res = extract_execution_steps(db, args.method)
        if args.format == "json" or getattr(args, "json", False):
            payload_str = json.dumps(res, indent=2)
            if args.output:
                out_file = os.path.abspath(os.path.join(root, args.output)) if not os.path.isabs(args.output) else args.output
                os.makedirs(os.path.dirname(out_file), exist_ok=True)
                with open(out_file, "w", encoding="utf-8") as fp:
                    fp.write(payload_str)
                print(f"📝 Micro-steps JSON written to: {out_file} (Rank: {res.get('manpower_rank')})")
            else:
                print(payload_str)
        elif args.output:
            out_file = os.path.abspath(os.path.join(root, args.output)) if not os.path.isabs(args.output) else args.output
            os.makedirs(os.path.dirname(out_file), exist_ok=True)
            with open(out_file, "w", encoding="utf-8") as fp:
                fp.write(res.get("markdown_table", ""))
            print(f"📝 Micro-steps table written to: {out_file} (Rank: {res.get('manpower_rank')})")
        else:
            print(res.get("markdown_table", ""))
        return 0

    elif sub == "bundle":
        out_file = args.output or os.path.join(root, ".sot", "bundle", "ContextBundle.md")
        if not os.path.isabs(out_file):
            out_file = os.path.abspath(os.path.join(root, out_file))
        res = generate_solution_bundle(db, args.module or "", out_file=out_file)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"📦 Solution Context Bundle generated at: {out_file}")
            print(f"   • Module: {res.get('module') or 'All'}")
            print(f"   • Features in Scope: {res.get('inventory', {}).get('total_features', 0)}")
            print(f"   • Manpower Effort Rank: {res.get('steps', {}).get('manpower_rank', '-')}")
        return 0

    print(f"Unknown solution subcommand: {sub}")
    return 1

def cmd_scope_receipt(args: argparse.Namespace, db: Database, root: str) -> int:
    """PRE-change scope receipt (P7): bounded evidence before an edit."""
    import json

    from sot_graph.assurance.receipts import scope_receipt

    target = (args.target or "").strip()
    payload = scope_receipt(
        db, root, target,
        depth=int(getattr(args, "depth", 2) or 2),
        kind_of_change=getattr(args, "change_kind", "local-body"),
        touches_auth=bool(getattr(args, "auth", False)),
        dynamic_heavy=bool(getattr(args, "dynamic", False)),
    )
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    ass = payload["assurance"]
    print(f"📋 Scope receipt — {payload['request']['target']} "
          f"(schema v{payload['schema_version']}, digest {payload['digest'][:12]}…)")
    print(f"   proof scope: {payload['proof_scope']} (never post-change proof)")
    print(f"   snapshot: {(payload['snapshot'].get('commit_sha') or '?')[:12]} "
          f"dirty={payload['snapshot'].get('dirty')} "
          f"digest={str(payload['snapshot'].get('descriptor_digest'))[:12]}…")
    print(f"   callers: {len(payload['direct_callers'])}  "
          f"callees: {len(payload['direct_callees'])}  "
          f"transitive(depth {payload['transitive_impact']['depth']}): "
          f"{len(payload['transitive_impact']['nodes'])}")
    print(f"   affected files: {len(payload['affected_files'])}  "
          f"candidate tests: {len(payload['candidate_tests'])}")
    print(f"   {payload['coverage']['note']}")
    print(f"   assurance: {ass['status']} — {ass['risk']['rule']}")
    for rc in ass.get("reason_codes", []):
        print(f"   reason: {rc}")
    if ass["rename_gate"].get("blocked"):
        print(f"   🚫 rename gate BLOCKED: {ass['rename_gate']['reason']}")
    for item in ass["omp_confirmations"]:
        print(f"   ☐ {item}")
    # P0 vocabulary: hard stop only on ABSTAINED/UNVERIFIABLE (no bounded
    # evidence at all); gate-blocked renames still stop the loop via exit 2.
    blocked_statuses = ("ABSTAINED", "UNVERIFIABLE")
    gate_blocked = bool(ass.get("rename_gate", {}).get("blocked"))
    return 2 if (ass["status"] in blocked_statuses or gate_blocked) else 0


def cmd_diff_impact(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.diff_impact import (
        GitDeltaExtractor,
        format_diff_impact_github,
        format_diff_impact_markdown,
    )

    from sot_graph.assurance.receipts import diff_impact_receipt
    from sot_graph.snapshot import capture_worktree_snapshot
    from types import SimpleNamespace

    target = getattr(args, "target", "HEAD~1") or "HEAD~1"
    depth = int(getattr(args, "depth", 2) or 2)
    staged = bool(getattr(args, "staged", False))
    working_tree = bool(getattr(args, "working_tree", False))

    # P1.g: capture PRE-change snapshot before any auto-reconcile mutates the
    # index — the receipt binds it (volatile-stripped) beside the post state.
    # P0 Contract 2: cite the diff's changed files so the pre-snapshot binds
    # their content, mirroring the post-change snapshot in receipts.py.
    try:
        delta_files = list(
            GitDeltaExtractor(root)
            .extract_diff(target, staged=staged, working_tree=working_tree)[0]
            .keys()
        )
    except Exception:  # pragma: no cover - best-effort content binding
        delta_files = []
    pre_snapshot = capture_worktree_snapshot(
        root, role="pre_change", cited_paths=delta_files[:200] or None
    )
    if getattr(args, "auto_reconcile", False):
        try:
            reconciler = Reconciler(db, root)
            reconciler.reconcile()
        except Exception as exc:
            print(f"⚠️  Auto-reconcile failed: {exc}", file=sys.stderr)

    receipt = diff_impact_receipt(
        db, root, target=target, depth=depth, staged=staged,
        working_tree=working_tree,
        pre_snapshot=pre_snapshot.as_dict(),
    )
    post_snapshot = receipt["post_change_snapshot"]
    if not isinstance(post_snapshot, dict):
        post_snapshot = post_snapshot.as_dict()

    # P1.c: every graph-derived citation must still match the journal; a
    # file that changed since the last reconcile caps evidence trust.
    cited = (
        list(receipt["changed_files"])
        + [n["path"] for n in receipt["direct_nodes"] if "path" in n]
        + [c["path"] for c in receipt["caller_impacts"] if "path" in c]
    )
    stale = db.stale_journal_files(sorted({p for p in cited if p}), root=root)
    if stale:
        try:
            db.mark_evidence_stale(
                stale, reason="journal mismatch: file changed since last reconcile"
            )
        except Exception:  # pragma: no cover - best-effort ledger marking
            pass

    fed = federated_extras(
        resolve_federated_spec(getattr(args, "provider", None), root),
        root, "diff-impact", target,
        staged=staged,
        working_tree=working_tree,
        depth=depth,
        db=db,
    )
    if fed is not None and fed["fail_message"]:
        print(f"❌ {fed['fail_message']}", file=sys.stderr)
        return 2

    payload = dict(receipt)
    payload["stale_files"] = stale
    if fed is not None:
        payload["external_candidates"] = fed["candidates"]

    # --format (R4): github = PR-safe renderer; text = legacy CLI output;
    # markdown = pure report body; json = envelope. Default (None) keeps the
    # historical behavior: --json wins, otherwise text.
    fmt = getattr(args, "format", None) or ("json" if getattr(args, "json", False) else "text")
    fmt = str(fmt).lower()

    if fmt == "json":
        if fed is not None:
            _print_fed_warnings(fed)
        envelope = wrap_envelope(payload, db=db)
        payload_str = json.dumps(envelope, indent=2, default=str)
        if getattr(args, "output", None):
            out_path = os.path.abspath(os.path.join(root, args.output)) if not os.path.isabs(args.output) else args.output
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as fp:
                fp.write(payload_str)
            print(f"📊 Diff impact JSON written to: {out_path}")
        else:
            print(payload_str)
        if fed is not None:
            _print_federation_notes(fed)
        return 0

    if fmt == "text":
        print(
            f"_Snapshot: pre {pre_snapshot.descriptor_digest[:19]} "
            f"(dirty={pre_snapshot.dirty}) → post {post_snapshot['descriptor_digest'][:19]} "
            f"(dirty={post_snapshot['dirty']})_"
        )
        # R5: bounded measurement must never be silent — surface receipt
        # warnings (e.g. partial closure over >RECEIPT_CITED_FILE_CAP diffs)
        # on stderr so text/CI output cannot bless partial evidence as whole.
        for warning in receipt.get("warnings") or []:
            print(f"⚠️  {warning}", file=sys.stderr)

    def _ns(value: Any) -> Any:
        if isinstance(value, dict):
            return SimpleNamespace(**{k: _ns(v) for k, v in value.items()})
        if isinstance(value, list):
            return [_ns(v) for v in value]
        return value

    # Duck-typed stand-in carrying the receipt fields the markdown formatter
    # reads off a DiffImpactResult.
    engine: Any = SimpleNamespace(
        summary=receipt["summary"],
        target=target,
        changed_files=receipt["changed_files"],
        direct_nodes=_ns(receipt["direct_nodes"]),
        caller_impacts=_ns(receipt["caller_impacts"]),
        api_impacts=_ns(receipt["api_impacts"]),
        test_impacts=_ns(receipt["test_impacts"]),
    )
    if fmt == "github":
        md = format_diff_impact_github(engine, repo_root=root)
    else:
        md = format_diff_impact_markdown(engine)
    if getattr(args, "output", None):
        out_path = os.path.abspath(os.path.join(root, args.output)) if not os.path.isabs(args.output) else args.output
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(md)
        print(f"📊 Diff impact report written to: {out_path}")
    else:
        print(md)
    # Notes print to stdout in text mode only; markdown/github output must
    # stay redirect-safe for CI piping (warnings already go to stderr).
    if fmt == "text":
        _print_federation_notes(fed)
    return 0


def cmd_log(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.diff_impact import (
        analyze_commit_history,
        format_commit_history_markdown,
        format_commit_history_json,
    )

    limit = getattr(args, "limit", 10)
    author = getattr(args, "author", None)
    since = getattr(args, "since", None)
    impact = getattr(args, "impact", True)

    res = analyze_commit_history(
        repo_path=root,
        count=limit,
        author=author,
        since=since,
        db=db if impact else None,
        with_impact=impact,
    )

    if getattr(args, "json", False):
        print(format_commit_history_json(res))
        return 0

    md = format_commit_history_markdown(res)
    if getattr(args, "output", None):
        out_path = os.path.abspath(os.path.join(root, args.output)) if not os.path.isabs(args.output) else args.output
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(md)
        print(f"📜 Commit history report written to: {out_path}")
    else:
        print(md)
    return 0

def cmd_report(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.analytics.graph import AnalyticsGraph
    from sot_graph.analytics.diagnostics import analyze_graph
    from sot_graph.analytics.report import generate_markdown_report, save_markdown_report
    from sot_graph.locking import LockBusy

    try:
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
            with db.write_lock():
                db.save_communities(comm_list)
    except (LockBusy, RuntimeError) as exc:
        print(f"❌ report failed: {exc}", file=sys.stderr)
        return 1

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
    from sot_graph.locking import LockBusy

    try:
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
            with db.write_lock():
                db.save_communities(comm_list)
    except (LockBusy, RuntimeError) as exc:
        print(f"❌ cluster failed: {exc}", file=sys.stderr)
        return 1

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


def cmd_export(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.analytics.graph import AnalyticsGraph
    from sot_graph.export.exporter import (
        export_graphrag_json,
        export_obsidian_vault,
        export_graphml,
    )

    fmt = args.format.lower()

    if fmt == "scip":
        from sot_graph.export.scip import export_scip

        out_file = args.output or os.path.join(root, ".sot", "index.scip")
        size = export_scip(db, root, out_file)
        print(f"🧭 SCIP index exported to: {out_file} ({size} bytes)")
        return 0

    graph = AnalyticsGraph.from_database(db, scope=args.scope)

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
        print(f"❌ Unknown export format: {fmt}. Supported: graphrag, obsidian, graphml, scip")
        return 1
    return 0

def cmd_import_scip(args: argparse.Namespace, db: Database, root: str) -> int:
    from sot_graph.importer.scip import ScipImporter
    index_path = args.index_file
    if not os.path.isabs(index_path):
        index_path = os.path.join(root, index_path)
    if not os.path.isfile(index_path):
        print(f"❌ SCIP index file not found: {index_path}", file=sys.stderr)
        return 1
    importer = ScipImporter(db, project_root=root)
    try:
        p_name = getattr(args, "provider", None) or getattr(args, "provider_name", None)
        p_ver = getattr(args, "provider_version", None)
        summary = importer.import_file(
            index_path,
            provider_name=p_name,
            provider_version=p_ver,
        )
    except Exception as exc:
        print(f"❌ Failed to import SCIP index: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        envelope = wrap_envelope(summary, db=db, project_root=root)
        print(json.dumps(envelope, indent=2))
    else:
        print("🧭 SCIP index imported successfully:")
        print(f"   Provider: {summary['provider_name']} (v{summary['provider_version']})")
        print(f"   Run ID: {summary['run_id']}")
        print(f"   Documents: {summary['documents_count']}")
        print(f"   Occurrences: {summary['occurrences_count']} ({summary['definitions_count']} defs, {summary['references_count']} refs)")
        print(f"   Relationships: {summary['relationships_count']}")
        print(f"   Evidence Recorded: {summary['evidence_recorded']} in {summary['duration_ms']}ms")
    return 0
def cmd_setup(args: argparse.Namespace, root: str) -> int:
    from pathlib import Path
    from sot_graph.adapters.installer import install_harnesses, list_supported_harnesses

    if args.list:
        print("Supported AI Coding Harnesses:")
        for key, desc in list_supported_harnesses().items():
            print(f"  - {key:<12} : {desc}")
        print(f"  - {'pi':<12} : Alias for 'omp' (Oh My Pi / Pi harness)")
        return 0

    if getattr(args, "hooks", False):
        from sot_graph.adapters.hooks import install_git_hooks

        installed = install_git_hooks(Path(root))
        if not installed:
            print("⚠ No .git directory found — git hooks not installed.")
            return 1
        print(f"🪝 Installed git hooks ({', '.join(h.name for h in installed)}):")
        for hook in installed:
            print(f"  ✓ {hook}")
        print("   The graph now reconciles automatically after merge/checkout.")
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
    try:
        import importlib.metadata
        __version__ = importlib.metadata.version("sot-graph")
    except Exception:
        __version__ = "0.3.0"
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--root", default=".", help="Project root directory (default: current dir)")
    parser.add_argument("--db", default=None, help="Custom SQLite DB path (default: .sot/sot.db)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = subparsers.add_parser("search", help="Ranked search with Trust Verdicts")
    p_search.add_argument("query", help="Query string")
    p_search.add_argument("-n", "--limit", type=int, default=6, help="Maximum results (default: 6)")
    p_search.add_argument("--scope", default=None, help="Filter by path or keyword substring")
    p_search.add_argument("--threshold", type=float, default=0.5, help="Coverage threshold for STRONG verdict")
    p_search.add_argument("--hybrid", action="store_true", help="Fuse BM25 with vector similarity (needs [vector] extra + `sot embed`)")
    p_search.add_argument("--jit", dest="jit", action="store_true", default=True, help="Enable JIT Micro-Reconciliation for modified files (default: True)")
    p_search.add_argument("--no-jit", dest="jit", action="store_false", help="Disable JIT Micro-Reconciliation")
    p_search.add_argument("--json", action="store_true", help="Output JSON format")
    # embed
    p_emb = subparsers.add_parser("embed", help="Build/refresh the optional vector index ([vector] extra)")
    p_emb.add_argument("--limit", type=int, default=5000, help="Maximum nodes to embed (default: 5000)")

    # explore
    p_exp = subparsers.add_parser("explore", help="Explore AST relations and cross-file edges")
    p_exp.add_argument("target", help="Symbol, function name, or class to explore")
    p_exp.add_argument("--depth", type=int, default=2, help="Graph walk depth (default: 2)")
    p_exp.add_argument("--all", dest="show_all", action="store_true", help="Show all references without collapsing large hubs (default: collapse if > 15 items)")
    p_exp.add_argument("--json", action="store_true", help="Output explore graph in JSON format")
    p_exp.add_argument("--provider", default="builtin",
                       help="External evidence providers: builtin | auto | prefer:<name> | require:<name> | all (default: builtin)")
    # usages
    p_usg = subparsers.add_parser("usages", help="List every reference site of a symbol, grouped by caller")
    p_usg.add_argument("target", help="Symbol, function name, or class to inspect")
    p_usg.add_argument("--json", action="store_true", help="Output raw JSON format")

    p_usg.add_argument("--provider", default="builtin",
                       help="External evidence providers: builtin | auto | prefer:<name> | require:<name> | all (default: builtin)")
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
    p_rec.add_argument("--receipt", action="store_true", help="Emit a post-reconcile assurance receipt as JSON")
    p_rec.add_argument(
        "--force",
        action="store_true",
        help="Re-extract every file regardless of journal state (upgrade path "
             "for extractor changes; notes are preserved)",
    )
    p_rec.add_argument(
        "--all",
        dest="all_repos",
        action="store_true",
        help="Batch reconcile all repositories in root directory",
    )
    # batch-reconcile
    p_batch_rec = subparsers.add_parser("batch-reconcile", help="Batch reconcile multiple repositories concurrently")
    p_batch_rec.add_argument("directory", nargs="?", default=".", help="Parent directory containing repositories (default: current directory)")
    p_batch_rec.add_argument(
        "--workers",
        type=_positive_int,
        default=min(8, max(1, os.cpu_count() or 1)),
        help="Worker processes (default: auto, max 8)",
    )
    p_batch_rec.add_argument("--force", action="store_true", help="Re-extract every file regardless of journal state")
    p_batch_rec.add_argument("--json", action="store_true", help="Output summary in JSON format")
    p_ver = subparsers.add_parser("verify", help="Check for drift between graph and filesystem (CI-safe)")
    p_ver.add_argument("--deep", action="store_true", help="Perform full SHA-256 content re-hashing")

    # doctor
    p_doc = subparsers.add_parser("doctor", help="Check database and graph health statistics")
    p_doc.add_argument("--json", action="store_true", help="Output health diagnostic in JSON format")
    p_doc.add_argument("--receipt", action="store_true", help="Emit a system integrity audit receipt as JSON")
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
    p_expo = subparsers.add_parser("export", help="Export knowledge graph to GraphRAG JSON, Obsidian, GraphML, or SCIP")
    p_expo.add_argument("-f", "--format", default="graphrag", choices=["graphrag", "json", "obsidian", "graphml", "scip"], help="Export format (default: graphrag)")
    p_expo.add_argument("-o", "--output", default=None, help="Output file or directory path")
    p_expo.add_argument("--scope", default=None, help="Scope export to path or subdirectory")
    # bundle
    p_bun = subparsers.add_parser("bundle", help="Extract 5 high-density fact bundle markdown files for LLM architecture reports")
    p_bun.add_argument("-o", "--output", default=None, help="Output directory path (default: .sot/bundle/)")
    p_bun.add_argument("--json", action="store_true", help="Output summary in JSON format")
    p_bun.add_argument("--include-tests", action="store_true", help="Include test files and mock nodes in fact bundles")

    # setup
    p_setup = subparsers.add_parser("setup", help="Configure AI coding harnesses (OMP / Pi, OpenCode, Antigravity, Claude, ZCode)")
    p_setup.add_argument("--harness", default="all", choices=["all", "omp", "pi", "opencode", "antigravity", "claude", "zcode"], help="Target harness ('pi' is an alias for 'omp'; default: all)")
    p_setup.add_argument("--global-only", action="store_true", help="Install to user home directory only")
    p_setup.add_argument("--workspace-only", action="store_true", help="Install to current workspace only")
    p_setup.add_argument("--list", action="store_true", help="List supported harnesses")
    p_setup.add_argument("--hooks", action="store_true", help="Provision git post-merge/post-checkout hooks that reconcile the graph (no daemon)")

    p_pack = subparsers.add_parser(
        "pack", help="Package a k-hop ContextBundle (YAML) for AI agent prompt registers")
    p_pack.add_argument("target", help="Target symbol or fully-qualified name")
    p_pack.add_argument("-o", "--output", default=None,
                        help="Write YAML to file (default: print to stdout)")
    p_pack.add_argument("--max-hops", type=int, default=2, help="Hop depth (default: 2)")
    p_pack.add_argument("--max-nodes", type=int, default=50, help="Node cap (default: 50)")
    p_pack.add_argument("--max-bytes", type=int, default=65536, help="Byte cap (default: 64KB)")
    p_pack.add_argument("--tokens", "--max-tokens", dest="max_tokens", type=int, default=None, help="Hard token budget cap (default: None)")
    p_pack.add_argument("--json", action="store_true", help="Output result as JSON envelope")
    p_watch = subparsers.add_parser(
        "watch", help="Watch filesystem and reconcile in real time (daemon & multi-project support)")
    p_watch.add_argument("--debounce-ms", type=int, default=200,
                         help="Event folding window (default: 200ms)")
    p_watch.add_argument("--backend", choices=("auto", "watchfiles", "poll"), default="auto",
                         help="Watcher backend (default: auto = watchfiles if installed)")
    p_watch.add_argument("--interval-ms", type=int, default=500,
                         help="Polling interval for the poll backend (default: 500ms)")
    p_watch.add_argument("-d", "--daemon", action="store_true",
                         help="Run watcher as a detached background daemon process")
    p_watch.add_argument("--stop", action="store_true",
                         help="Stop the running background watcher daemon")
    p_watch.add_argument("--status", action="store_true",
                         help="Check status of the background watcher daemon")
    p_watch.add_argument("--all", action="store_true",
                         help="Auto-discover and watch ALL indexed SOT projects in workspace/directory")
    p_watch.add_argument("--dir", type=str, default=None,
                         help="Base directory to search for SOT projects when using --all (default: current directory)")
    p_watch.add_argument("--service", choices=("install", "uninstall"), default=None,
                         help="Install/uninstall persistent background service (macOS LaunchAgent / systemd)")
    # trace
    p_trace = subparsers.add_parser("trace", help="Extract Full-Stack execution path, UI decisions, API binding, and Mermaid diagrams")
    p_trace.add_argument("target", help="Ticket ID, keyword, symbol, or endpoint to trace")
    # import-scip
    p_scip = subparsers.add_parser("import-scip", help="Import compiler-backed SCIP index into Multi-Provider Evidence Storage")
    p_scip.add_argument("index_file", help="Path to .scip (protobuf) or .json index file")
    p_scip.add_argument("--provider", default=None, help="Provider name override (e.g. scip-typescript, scip-python)")
    p_scip.add_argument("--provider-version", default=None, help="Provider version override")
    p_scip.add_argument("--json", action="store_true", help="Output result as JSON envelope")
    p_trace.add_argument("--depth", type=int, default=2, help="Trace exploration depth (default: 2)")
    p_trace.add_argument("-o", "--output", default=None, help="Write markdown output to file")
    p_trace.add_argument("--json", action="store_true", help="Output raw structured JSON")

    # ui-tree
    p_ui = subparsers.add_parser("ui-tree", help="Extract local Frontend UI decision tree, validation rules, and modals")
    p_ui.add_argument("component", help="Component name or file path")
    p_ui.add_argument("--json", action="store_true", help="Output raw JSON")

    # be-flow
    p_be = subparsers.add_parser("be-flow", help="Extract Backend processing steps, multi-datasources, and exception branches")
    p_be.add_argument("service", help="Service name or controller endpoint")
    p_be.add_argument("--json", action="store_true", help="Output raw JSON")

    # solution
    p_sol = subparsers.add_parser("solution", help="Automated Solution Architecture and Manpower Estimation Engine")
    sol_subs = p_sol.add_subparsers(dest="solution_subcommand", required=True)

    p_sol_inv = sol_subs.add_parser("inventory", help="Stage 1 Feature Discovery by Role & Related Features")
    p_sol_inv.add_argument("module", nargs="?", default="", help="Module or subsystem name (default: all)")
    p_sol_inv.add_argument("-o", "--output", default=None, help="Output markdown file path")
    p_sol_inv.add_argument("--json", action="store_true", help="Output JSON format")

    p_sol_steps = sol_subs.add_parser("steps", help="Stage 2 Micro-step decomposition (4-column table) for manpower estimation")
    p_sol_steps.add_argument("method", help="Service or method symbol to decompose")
    p_sol_steps.add_argument("--format", default="table", choices=["table", "json"], help="Output format (default: table)")
    p_sol_steps.add_argument("-o", "--output", default=None, help="Output file path")

    p_sol_bun = sol_subs.add_parser("bundle", help="Synthesize complete Context Bundle for Solution.md & downstream agents")
    p_sol_bun.add_argument("module", nargs="?", default="", help="Module name (default: all)")
    p_sol_bun.add_argument("-o", "--output", default=None, help="Output file path (default: .sot/bundle/ContextBundle.md)")
    p_sol_bun.add_argument("--json", action="store_true", help="Output JSON format")


    # scope-receipt (P7)
    p_sr = subparsers.add_parser("scope-receipt", help="PRE-change bounded evidence receipt for one edit target")
    p_sr.add_argument("target", help="Symbol to scope (e.g. 'Pipeline.process')")
    p_sr.add_argument("--depth", type=int, default=2, help="Transitive impact walk depth (default: 2)")
    p_sr.add_argument("--change-kind", default="local-body",
                      choices=["local-body", "public-api", "rename", "delete"],
                      help="Kind of change (default: local-body)")
    p_sr.add_argument("--auth", action="store_true", help="Change touches auth/tenant logic")
    p_sr.add_argument("--dynamic", action="store_true", help="Change is dynamic-heavy (dispatch/reflection)")
    p_sr.add_argument("--json", action="store_true", help="Output raw JSON receipt")
    p_prov = subparsers.add_parser("providers", help="Detect, list, and diagnose evidence providers (read-only)")
    prov_subs = p_prov.add_subparsers(dest="providers_subcommand", required=True)

    p_prov_detect = prov_subs.add_parser("detect", help="Probe provider executables and SCIP artifacts (read-only)")
    p_prov_detect.add_argument("--format", default="text", choices=["text", "json"], help="Output format (default: text)")

    p_prov_list = prov_subs.add_parser("list", help="List configured providers, commands, and capabilities")
    p_prov_list.add_argument("--format", default="text", choices=["text", "json"], help="Output format (default: text)")

    p_prov_doc = prov_subs.add_parser("doctor", help="Provider health summary with recommended next actions")
    p_prov_doc.add_argument("--format", default="text", choices=["text", "json"], help="Output format (default: text)")

    p_prov_res = prov_subs.add_parser("resolve", help="Rank available providers for a capability")
    p_prov_res.add_argument("--capability", required=True, help="Capability to resolve (e.g. impact, symbols, callgraph)")
    p_prov_res.add_argument("--format", default="text", choices=["text", "json"], help="Output format (default: text)")

    p_prov_lifecycle = prov_subs.add_parser("lifecycle", help="Provider lifecycle manifest + 8-step update process (roadmap §8.1/§8.2)")
    p_prov_lifecycle.add_argument("--format", default="text", choices=["text", "json"], help="Output format (default: text)")

    p_prov_xc = prov_subs.add_parser(
        "cross-check",
        help="Read-only reconciliation: builtin AST evidence vs external provider evidence (R4)",
    )
    p_prov_xc.add_argument("--json", action="store_true", help="Output the read-only envelope as JSON")
    p_prov_xc.add_argument("--provider", default=None, help="Restrict the external side to one provider name (default: all)")
    p_prov_sync = prov_subs.add_parser(
        "sync",
        help="Explicit index sync for one provider (own timeout, lock, receipt)",
    )
    p_prov_sync.add_argument("provider_name", help="Provider name (e.g. codebase-memory)")
    p_prov_sync.add_argument("--json", action="store_true", help="Emit the run receipt as JSON")
    p_prov_sync.add_argument("--progress", action="store_true", help="Forward the provider's progress stream")
    p_prov_sync.add_argument("--timeout", type=float, default=0, help="Index budget in seconds (0 = adapter default)")

    # diff-impact
    p_diff = subparsers.add_parser("diff-impact", help="Git diff blast radius, upstream caller traversal, and API impact analysis")
    p_diff.add_argument("target", nargs="?", default="HEAD", help="Git revision target (e.g. 'HEAD', 'main...HEAD', commit hash; default: HEAD — a single revision diffs <rev>~1..<rev>, so the default analyzes the LATEST commit)")
    p_diff.add_argument("--depth", type=int, default=2, help="Reverse call graph walk depth (default: 2)")
    p_diff.add_argument("--staged", action="store_true", help="Analyze staged changes (--cached)")
    p_diff.add_argument("--working-tree", action="store_true", help="Analyze unstaged working tree changes")
    p_diff.add_argument("--auto-reconcile", action="store_true", help="Reconcile knowledge graph before analyzing impact")
    p_diff.add_argument("-o", "--output", default=None, help="Output markdown file path")
    p_diff.add_argument("--json", action="store_true", help="Output raw JSON format")
    p_diff.add_argument("--format", default=None,
                        choices=["text", "markdown", "json", "github"],
                        help="Output format: text (legacy CLI report), markdown (pure report body), json (envelope), github (PR-comment-safe collapsed sections; R4). Default: text, or json with --json")
    p_diff.add_argument("--provider", default="builtin",
                        help="External evidence providers: builtin | auto | prefer:<name> | require:<name> | all (default: builtin)")

    # log / commits
    p_log = subparsers.add_parser("log", aliases=["commits"], help="Inspect git commit history with automated risk scoring and impacted symbols")
    p_log.add_argument("-n", "--limit", type=int, default=10, help="Maximum commits to analyze (default: 10)")
    p_log.add_argument("--author", default=None, help="Filter commits by author")
    p_log.add_argument("--since", default=None, help="Filter commits since date/time (e.g. '2026-01-01' or '2.weeks')")
    p_log.add_argument("--impact", dest="impact", action="store_true", default=True, help="Enable knowledge graph symbol impact analysis (default: True)")
    p_log.add_argument("--no-impact", dest="impact", action="store_false", help="Disable knowledge graph symbol impact analysis")
    p_log.add_argument("-o", "--output", default=None, help="Output markdown file path")
    p_log.add_argument("--json", action="store_true", help="Output raw JSON format")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    # CLI output contains emoji; on Windows the console default (cp1252)
    # cannot encode them, so normalize the streams to UTF-8 before any
    # print() can raise UnicodeEncodeError mid-command.
    for _stream in (sys.stdout, sys.stderr):
        try:
            if _stream and _stream.encoding and _stream.encoding.lower().replace("-", "") != "utf8":
                _reconfigure = getattr(_stream, "reconfigure", None)
                if callable(_reconfigure):
                    _reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass  # non-tty or exotic stream: keep the interpreter default
    parser = build_parser()
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    try:
        db_path = args.db or default_db_path(root)
    except ValueError as exc:
        print(f"❌ Unsafe default database path: {exc}", file=sys.stderr)
        return 1
    if args.command == "setup":
        return cmd_setup(args, root)

    if args.command == "providers":
        # Registry reads never touch the database; the sync subcommand is
        # the write path and receives the resolved --db target like every
        # other database-touching command.
        return cmd_providers(args, root, db_path=db_path)

    if args.command == "batch-reconcile" or (args.command == "reconcile" and getattr(args, "all_repos", False)):
        target_dir = getattr(args, "directory", None) or root
        return cmd_batch_reconcile(args, target_dir)

    if args.command == "mcp":
        # Keep the optional SDK out of normal CLI startup/import paths.
        from sot_graph.mcp_server import main as mcp_main
        return mcp_main(["--root", root, "--db", db_path])
    try:
        db = Database(db_path)
    except (LockBusy, RuntimeError) as exc:
        print(f"❌ Database initialization failed: {exc}", file=sys.stderr)
        return 1

    try:
        reconciler = Reconciler(db, root)
        if db.schema_was_reset:
            print("⚠️  LEGACY SCHEMA RESET: this project's index used an outdated schema "
                  "and was rebuilt empty.")
            if args.command in ("reconcile", "clean"):
                # `reconcile` is about to refill the graph itself, and `clean` was
                # explicitly asked to prune/reset — auto-refilling would undo it.
                print("   Run `sot reconcile` to repopulate the graph.")
            else:
                print("   Rebuilding the index automatically (one-time)…")
                try:
                    summary = reconciler.reconcile()
                    print(f"   ✅ Auto-reconciled: {summary.updated} indexed/updated, "
                          f"{summary.failed} failed.")
                except (OSError, sqlite3.Error) as exc:
                    print(f"   ⚠ Auto-reconcile failed: {exc}; run `sot reconcile` manually.")

        if args.command == "search":
            return cmd_search(args, db, root)
        elif args.command == "explore":
            return cmd_explore(args, db, root)
        elif args.command == "usages":
            return cmd_usages(args, db, root)
        elif args.command == "implementations":
            return cmd_implementations(args, db)
        elif args.command == "rename":
            return cmd_rename(args, db)
        elif args.command == "map":
            return cmd_map(args, db, root)
        elif args.command == "embed":
            return cmd_embed(args, db)
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
            return cmd_doctor(args, db, root)
        elif args.command == "report":
            return cmd_report(args, db, root)
        elif args.command == "cluster":
            return cmd_cluster(args, db)
        elif args.command == "viz":
            return cmd_viz(args, db, root)
        elif args.command == "export":
            return cmd_export(args, db, root)
        elif args.command == "import-scip":
            return cmd_import_scip(args, db, root)
        elif args.command == "bundle":
            return cmd_bundle(args, db, root)
        elif args.command == "pack":
            return cmd_pack(args, db, root)
        elif args.command == "watch":
            return cmd_watch(args, reconciler, root)
        elif args.command == "trace":
            return cmd_trace(args, db, root)
        elif args.command == "ui-tree":
            return cmd_ui_tree(args, db)
        elif args.command == "be-flow":
            return cmd_be_flow(args, db)
        elif args.command == "solution":
            return cmd_solution(args, db, root)
        elif args.command == "scope-receipt":
            return cmd_scope_receipt(args, db, root)
        elif args.command == "diff-impact":
            return cmd_diff_impact(args, db, root)
        elif args.command in ("log", "commits"):
            return cmd_log(args, db, root)
        return 0
    except (LockBusy, RuntimeError) as exc:
        print(f"❌ {args.command} failed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
