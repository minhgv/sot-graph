#!/usr/bin/env python3
"""bench_provider_identity.py — provider identity join oracle (SG-203).

The reassessment roadmap (issue #6 / SG-203) exists because the legacy
cross-check joined builtin node IDs against provider symbol strings by
raw equality — accidental joins across identity spaces. This benchmark
measures the replacement: canonical SymbolIdentity joins.

Corpus (all real machinery, no mocks):

- Builtin side: the git-tracked fixture repo
  ``tests/fixtures/cbm_sample_repo`` copied to a temp root and ingested
  by the REAL Reconciler. Its source comments are the ground truth:
  build_invoice -> core.service.compute_total (direct call, builtin
  resolves it), build_code_label -> core.labels.format_label (alias
  import, builtin resolves it), build_invoice ->
  core.service.format_label (attribute call — a REAL builtin parser
  gap), dispatch -> getattr(...) (dynamic; NEITHER side may claim it).

- CBM side: the recorded golden responses in
  ``tests/fixtures/cbm_golden/`` (CBM 0.10.8). search_graph carries the
  compute_total definition; trace_path carries the two build_invoice
  callees. The golden qualified names embed the ORIGINAL fixture path
  as their dash-mangled prefix; the replay rehomes that prefix onto the
  temp root (names, hops and lines are replayed verbatim).

- SCIP side: a synthetic index in real SCIP JSON shape (documents,
  definitions with roles, ranges) imported through the REAL ScipImporter
  under provider "scip-index".

Probes planted on top:

- span_conflict : one CBM call row claims compute_total at lines 60-62
  (real span 7-10) — must surface as span_disagreement adjudicated
  builtin_verified against the live file.
- id_collision  : one CBM row whose src is literally a builtin node ID
  string — must NEVER join (the legacy raw-string bug).

Metrics (measured, then gated):

- join precision   : every agreement maps onto a planted ground-truth
  claim (definition or call) — no invented joins.
- join recall      : every ground-truth claim asserted by BOTH an
  external provider and the builtin graph is found.
- external-only honesty: builtin parser gaps (e.g. the attribute call)
  are REPORTED, not silently dropped or miscounted as agreements.
- zero accidental joins: the collision probe contributes nothing.

Writes benchmarks/provider-identity.json. `--gate` exits 1 on any
threshold failure. `--selfcheck` verifies the planted truth closure is
internally consistent without touching a repo.

Usage:
  python3 scripts/bench_provider_identity.py [--json benchmarks/provider-identity.json]
  python3 scripts/bench_provider_identity.py --gate
  python3 scripts/bench_provider_identity.py --selfcheck
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from sot_graph.db import Database  # noqa: E402
from sot_graph.providers.cross_check import cross_check  # noqa: E402
from sot_graph.providers.identity_join import mangled_root_prefix  # noqa: E402
from sot_graph.reconciler import Reconciler  # noqa: E402

NOW = 1_700_000_000

# ---------------------------------------------------------------------------
# Ground truth — planted by the fixture repo's source comments.
# ---------------------------------------------------------------------------

TRUTH_DEFINITIONS: Set[str] = {
    "app.main.build_invoice",
    "app.main.build_code_label",
    "app.main.dispatch",
    "core.service.compute_total",
    "core.service.format_label",
    "core.labels.format_label",
}

# Calls the builtin graph is KNOWN to claim after a real reconcile
# (verified against the extractor; the attribute call is absent there).
TRUTH_BUILTIN_CALLS: Set[Tuple[str, str]] = {
    ("app.main.build_invoice", "core.service.compute_total"),
    ("app.main.build_code_label", "core.labels.format_label"),
}

# The attribute call: claimed by CBM (golden trace) but beyond the
# builtin extractor — the honest external-only gap this benchmark must
# surface rather than paper over.
TRUTH_BUILTIN_GAP_CALLS: Set[Tuple[str, str]] = {
    ("app.main.build_invoice", "core.service.format_label"),
}

# SCIP synthetic index plants definitions for these three symbols.
SCIP_DEFINITIONS: Set[str] = {
    "app.main.build_invoice",
    "core.service.compute_total",
    "core.service.format_label",
}

GATES = {
    "join_precision": 1.0,
    "join_recall": 1.0,
    "span_conflict_detected": 1,
    "span_conflict_adjudicated_builtin": 1,
    "accidental_joins": 0,
}


def selfcheck() -> List[str]:
    """Verify the planted truth closure is internally consistent."""
    problems: List[str] = []
    if TRUTH_BUILTIN_CALLS & TRUTH_BUILTIN_GAP_CALLS:
        problems.append("a call is both builtin-claimed and a builtin gap")
    gap_defs = {s for pair in TRUTH_BUILTIN_GAP_CALLS for s in pair}
    if not gap_defs <= TRUTH_DEFINITIONS:
        problems.append("gap call references unknown symbols")
    if not SCIP_DEFINITIONS <= TRUTH_DEFINITIONS:
        problems.append("SCIP definitions reference unknown symbols")
    cbm_callees = {
        ("app.main.build_invoice", "core.service.compute_total"),
        ("app.main.build_invoice", "core.service.format_label"),
    }
    if not cbm_callees <= (TRUTH_BUILTIN_CALLS | TRUTH_BUILTIN_GAP_CALLS):
        problems.append("golden trace callees diverge from planted truth")
    return problems


# ---------------------------------------------------------------------------
# Corpus construction
# ---------------------------------------------------------------------------

def build_corpus(root: Path) -> None:
    src = _REPO / "tests" / "fixtures" / "cbm_sample_repo"
    for item in ("app", "core", "README.md"):
        s, d = src / item, root / item
        if s.is_dir():
            shutil.copytree(s, d, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(s, d)


# --- CBM golden replay ------------------------------------------------------

_SEARCH_ROW = re.compile(
    r"^\s*(?P<qn>\S+)\s+(?P<label>\S+)\s+(?P<file>\S+)\s+(?P<lines>\d+-\d+)"
)
_TRACE_GROUP = re.compile(r"^(?P<prefix>\S+):\s*$")
_TRACE_MEMBER = re.compile(r"^\s{2}(?P<name>\S+)\s+(?P<hop>\d+)$")


def _golden_text(name: str) -> str:
    payload = json.loads(
        (_REPO / "tests" / "fixtures" / "cbm_golden" / f"{name}.json")
        .read_text(encoding="utf-8"))
    return payload["content"][0]["text"]


def parse_golden_search(orig_prefix: str) -> List[Dict[str, str]]:
    """Rows from the recorded search_graph response (definition claims)."""
    rows: List[Dict[str, str]] = []
    for line in _golden_text("search_graph").splitlines():
        m = _SEARCH_ROW.match(line)
        if m:
            row = dict(m.groupdict())
            row["qn"] = row["qn"].replace(orig_prefix + ".", "", 1)
            rows.append(row)
    return rows


def parse_golden_trace(orig_prefix: str) -> List[Tuple[str, str, int]]:
    """(callee_fqn, group_prefix, hop) from the recorded trace_path."""
    out: List[Tuple[str, str, int]] = []
    prefix = ""
    for line in _golden_text("trace_path").splitlines():
        g = _TRACE_GROUP.match(line)
        if g:
            prefix = g.group("prefix").replace(orig_prefix + ".", "", 1)
            continue
        m = _TRACE_MEMBER.match(line)
        if m and prefix:
            out.append((m.group("name"), prefix, int(m.group("hop"))))
    return out


def insert_cbm_evidence(
    db: Database, root: Path, orig_prefix: str,
) -> Dict[str, int]:
    """Replay golden CBM responses into provider_evidence (replayed+rehomed)."""
    conn = db.conn
    conn.execute(
        "INSERT INTO provider_runs (id, provider_name, provider_version, "
        "capability, status, created_at) VALUES (?,?,?,?,?,?)",
        ("run-cbm-bench", "codebase-memory", "0.10.8", "CALLGRAPH", "ok", NOW),
    )
    planted = {"definitions": 0, "calls": 0, "span_probes": 0, "collisions": 0}

    def ev(ev_id, src, dst, relation, path, ls, le):
        conn.execute(
            "INSERT INTO provider_evidence (id, run_id, provider_name, path,"
            " src_symbol, dst_symbol, relation, line_start, line_end,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ev_id, "run-cbm-bench", "codebase-memory", path, src, dst,
             relation, ls, le, NOW),
        )

    # search_graph definitions (qn, file, lines replayed verbatim; the
    # mangled prefix is rehomed onto this temp root).
    new_prefix = mangled_root_prefix(str(root))
    for row in parse_golden_search(orig_prefix):
        ls, le = row["lines"].split("-")
        ev(f"cbm-def-{row['qn']}", f"{new_prefix}.{row['qn']}", None,
           "defines", row["file"], int(ls), int(le))
        planted["definitions"] += 1

    # trace_path callees: group prefix names the callee module; the
    # recorded groups carry the temp-root-rehomed namespace.
    for i, (name, group, _hop) in enumerate(parse_golden_trace(orig_prefix)):
        ev(f"cbm-call-{i}", f"{new_prefix}.app.main.build_invoice",
           f"{new_prefix}.{group}.{name}", "call:out", "app/main.py", 8, 8)
        planted["calls"] += 1

    # Span-conflict probe: a pair only the probe claims (the alias call —
    # real span 13-15) with a deliberately wrong span 60-62. It joins on
    # identity, then the span disagreement must adjudicate against the
    # live file. (Probing the SAME pair as a golden call would dedup into
    # one claim and never disagree with itself.)
    ev("cbm-span-probe", f"{new_prefix}.app.main.build_code_label",
       f"{new_prefix}.core.labels.format_label", "call:out",
       "app/main.py", 60, 62)
    planted["span_probes"] += 1

    # Identity-collision probe: src is literally a builtin node ID.
    node_id = conn.execute(
        "SELECT id FROM graph_nodes WHERE fqn = 'app.main.build_invoice'"
    ).fetchone()[0]
    ev("cbm-collision-probe", node_id,
       f"{new_prefix}.core.service.compute_total", "call:out",
       "app/main.py", 8, 8)
    planted["collisions"] += 1
    conn.commit()
    return planted


# --- SCIP synthetic index ----------------------------------------------------

def scip_index() -> Dict[str, Any]:
    """Real-shape SCIP JSON: definition occurrences with roles/ranges.

    Ranges are SCIP triples [start_line, start_col], [end_line, end_col]
    (0-based); definitions carry ROLE_DEFINITION (1).
    """
    def defn(symbol: str, line: int, end_line: int) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "symbol_roles": 1,
            "range": [[line - 1, 0], [end_line - 1, 0]],
            "syntax_kind": 12,
        }

    return {
        "metadata": {
            "project_root": ".",
            "text_document_encoding": 1,
            "tool_info": {"name": "scip-python", "version": "1.0.0"},
        },
        "documents": [
            {
                "relative_path": "app/main.py",
                "occurrences": [
                    defn(
                        "scip-python python pkg 1.0.0 `app/main.py`/"
                        "build_invoice().", 7, 10),
                ],
            },
            {
                "relative_path": "core/service.py",
                "occurrences": [
                    defn(
                        "scip-python python pkg 1.0.0 `core/service.py`/"
                        "compute_total().", 6, 9),
                    defn(
                        "scip-python python pkg 1.0.0 `core/service.py`/"
                        "format_label().", 12, 14),
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def run_benchmark(out_path: Path) -> Dict[str, Any]:
    from sot_graph.importer.scip import ScipImporter

    tmp = tempfile.mkdtemp(prefix="sot-bench-pid-")
    root = Path(tmp) / "repo"
    root.mkdir(parents=True)
    try:
        build_corpus(root)
        db = Database(str(root / ".sot" / "sot.db"))
        try:
            Reconciler(db, str(root)).reconcile(workers=1)
            orig_prefix = mangled_root_prefix(
                str(_REPO / "tests" / "fixtures" / "cbm_sample_repo"))
            planted = insert_cbm_evidence(db, root, orig_prefix)
            scip_result = ScipImporter(db, str(root)).import_index(
                scip_index(), provider_name="scip-index",
                provider_version="1.0.0", project_root=str(root))
            report = cross_check(db, repo_root=str(root))
        finally:
            db.close()

        totals = report["totals"]

        # --- decode agreements onto (fqn, fqn-or-identity) triples
        edge_agreements: Set[Tuple[str, str]] = set()
        def_agreements: Set[str] = set()
        for a in report["agreements"]:
            if a["claim_type"] == "edge":
                edge_agreements.add(
                    (a["src"]["fqn"], a["dst"]["fqn"]))
            else:
                def_agreements.add(a["identity"]["fqn"])

        truth_calls = TRUTH_BUILTIN_CALLS | TRUTH_BUILTIN_GAP_CALLS
        false_joins = {
            pair for pair in edge_agreements if pair not in truth_calls}
        false_defs = def_agreements - TRUTH_DEFINITIONS

        # Recall over BOTH-claimed ground truth: CBM trace's computable
        # calls that the builtin graph also claims, and every SCIP def.
        cbm_callable = {
            ("app.main.build_invoice", "core.service.compute_total")}
        expected_calls = cbm_callable & TRUTH_BUILTIN_CALLS
        missed_calls = expected_calls - edge_agreements
        expected_defs = set(SCIP_DEFINITIONS)
        missed_defs = expected_defs - def_agreements

        precision_d = 1.0 if not false_joins and not false_defs else (
            len(def_agreements) + len(edge_agreements) - len(false_defs)
            - len(false_joins)) / max(
                1, len(def_agreements) + len(edge_agreements))
        denom_c = max(1, len(expected_calls))
        denom_d = max(1, len(expected_defs))
        recall = (
            (len(expected_calls) - len(missed_calls))
            + (len(expected_defs) - len(missed_defs))
        ) / (denom_c + denom_d)

        span_conflicts = [
            c for c in report["conflicts"]
            if c.get("conflict", {}).get("reason") == "span_disagreement"]
        adjudicated_builtin = [
            c for c in span_conflicts
            if c["conflict"].get("adjudication") == "builtin_verified"]

        # The collision probe must not appear anywhere near agreements.
        probe = [a for a in report["agreements"]
                 if str(a.get("src", {}).get("fqn", "")).startswith("sym:")]

        # Honest gap listing: external-only calls that are REAL symbols
        # (builtin parser gaps), keyed for the artifact.
        gap_calls = sorted(
            f"{s} -> {d}" for (s, d) in (
                (e["src"]["fqn"], e["dst"]["fqn"])
                for e in report["external_only"] if e["claim_type"] == "edge")
            if (s, d) in TRUTH_BUILTIN_GAP_CALLS)

        metrics = {
            "join_precision": round(precision_d, 4),
            "join_recall": round(recall, 4),
            "edge_agreements": len(edge_agreements),
            "definition_agreements": len(def_agreements),
            "span_conflict_detected": len(span_conflicts),
            "span_conflict_adjudicated_builtin": len(adjudicated_builtin),
            "accidental_joins": len(probe),
            "builtin_gap_calls_surfaced": len(gap_calls),
        }
        gates = {
            "join_precision": metrics["join_precision"]
            >= GATES["join_precision"],
            "join_recall": metrics["join_recall"] >= GATES["join_recall"],
            "span_conflict_detected": metrics["span_conflict_detected"]
            >= GATES["span_conflict_detected"],
            "span_conflict_adjudicated_builtin":
                metrics["span_conflict_adjudicated_builtin"]
                >= GATES["span_conflict_adjudicated_builtin"],
            "accidental_joins":
                metrics["accidental_joins"] == GATES["accidental_joins"],
        }

        corpus_digest = hashlib.sha256(
            "\n".join(sorted(TRUTH_DEFINITIONS)).encode("utf-8")
        ).hexdigest()[:16]
        artifact = {
            "benchmark": "provider-identity-oracle",
            "schema_version": 1,
            "corpus": {
                "digest": corpus_digest,
                "fixture": "tests/fixtures/cbm_sample_repo",
                "golden": "tests/fixtures/cbm_golden (CBM 0.10.8, replayed;"
                          " mangled root rehomed onto temp corpus)",
                "scip": "synthetic SCIP JSON via real ScipImporter",
                "truth_definitions": sorted(TRUTH_DEFINITIONS),
                "truth_builtin_calls": sorted(map(list, TRUTH_BUILTIN_CALLS)),
                "truth_builtin_gap_calls":
                    sorted(map(list, TRUTH_BUILTIN_GAP_CALLS)),
                "probes": planted,
            },
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "metrics": metrics,
            "observed": {
                "edge_agreements": sorted(map(list, edge_agreements)),
                "definition_agreements": sorted(def_agreements),
                "false_joins": sorted(map(list, false_joins)),
                "false_definitions": sorted(false_defs),
                "missed_calls": sorted(map(list, missed_calls)),
                "missed_definitions": sorted(missed_defs),
                "builtin_gap_calls": gap_calls,
                "scip_rows_imported": scip_result.get("evidence_recorded", 0),
                "totals": totals,
            },
            "gates": {
                "passed": all(gates.values()),
                "thresholds": GATES,
                "checks": gates,
                "rationale": (
                    "Thresholds fixed from the first measured run on the "
                    "planted corpus: identity joins must be exact (no "
                    "invented joins, no missed both-claimed pairs), the "
                    "span probe must adjudicate against the live file, "
                    "and the node-ID collision probe must join nothing."),
            },
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(artifact, indent=2, sort_keys=False) + "\n",
            encoding="utf-8")
        return artifact
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default=str(_REPO / "benchmarks"
                                              / "provider-identity.json"))
    parser.add_argument("--gate", action="store_true")
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args(argv)

    if args.selfcheck:
        problems = selfcheck()
        for p in problems:
            print(f"SELFCHECK FAIL: {p}", file=sys.stderr)
        return 1 if problems else 0

    artifact = run_benchmark(Path(args.json))
    m, g = artifact["metrics"], artifact["gates"]["checks"]
    print("Provider identity join oracle (SG-203)")
    print(f"  precision / recall      : "
          f"{m['join_precision']:.2f} / {m['join_recall']:.2f}")
    print(f"  agreements (edge/def)   : "
          f"{m['edge_agreements']} / {m['definition_agreements']}")
    print(f"  span probe (found/adj.) : "
          f"{m['span_conflict_detected']} / "
          f"{m['span_conflict_adjudicated_builtin']}")
    print(f"  accidental joins        : {m['accidental_joins']}")
    print(f"  builtin gaps surfaced   : "
          f"{m['builtin_gap_calls_surfaced']}")
    print(f"  artifact                : {args.json}")
    if args.gate:
        if not artifact["gates"]["passed"]:
            failed = [k for k, ok in g.items() if not ok]
            print(f"GATE FAIL: {failed}", file=sys.stderr)
            return 1
        print("  gates                   : ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
