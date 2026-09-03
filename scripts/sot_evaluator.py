#!/usr/bin/env python3
"""
sot_evaluator.py — Exact 6-tuple accuracy oracle for SOT-Graph (v2).

Contract (P0, impact-assurance execution plan):
  An edge counts as a true positive ONLY when the exact tuple matches:
      (repo, path, source identity, relation, target identity, span)
  - path           : repo-relative posix path of the edge's source file
  - source identity: language-canonical file-local qualified symbol
                     (e.g. "Pipeline.process", "Worker1.Check", "Validator.isValid")
  - relation       : "calls" | "extends" | "implements"
  - target identity: file-local qualified symbol in its DEFINING file
  - span           : the call-site line (graph_edges.line). graph_edges is
                     keyed (path, src, dst, relation), so several call sites
                     of one src->dst pair collapse to one row; a group is a
                     TP iff the stored line is one of the true call lines.
  A bare name appearing on a DIFFERENT edge is never a true positive; it is
  recorded as an explicit confusion reason instead.

Corpus polarities:
  static_positive  : edge MUST exist exactly (drives recall)
  static_negative  : edge MUST NOT exist at any line (drives precision)
  dynamic_positive : true at runtime, statically unresolvable in closed form
                     (reflection, DI tables, fn pointers, virtual dispatch on
                     an unprovable receiver). Claiming is optional; claiming a
                     WRONG target with the same bare name is counted as
                     "dynamic misresolution". Never merged into static P/R.

Diagnostics (never counted as TP):
  identity_only_recall          — tuple without span (shows span-only misses)
  legacy_loose_recall_diagnostic— replicates the pre-v2 3-tier matcher that
                                  inflated recall via bare-name fallbacks.

Self-check subcommand proves the matcher discriminates wrong-target edges.

Usage:
  python3 scripts/sot_evaluator.py --output benchmarks/oracle/builtin-baseline.json
  python3 scripts/sot_evaluator.py --selfcheck
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sot_graph.db import Database  # noqa: E402
from sot_graph.modutil import dotted_module  # noqa: E402
from sot_graph.reconciler import Reconciler  # noqa: E402

ORACLE_VERSION = "2.0.0"
CORPUS_REPO_ID = "oracle-corpus-v1"
RELATIONS_MEASURED = ("calls", "extends", "implements")


# ---------------------------------------------------------------------------
# Ground-truth model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EdgeTruth:
    """One asserted edge in the exact 6-tuple contract."""

    repo: str
    path: str                # repo-relative posix path of the SOURCE file
    src: str                 # file-local qualified source symbol
    relation: str            # calls | extends | implements
    dst: str                 # file-local qualified target symbol
    dst_path: str            # repo-relative posix path DEFINING the target
    line: Optional[int]      # call-site line; None for negatives
    language: str
    polarity: str            # static_positive | static_negative | dynamic_positive
    category: str
    description: str = ""

    @property
    def key(self) -> Tuple[str, str, str, str, str]:
        return (self.path, self.src, self.relation, self.dst, self.dst_path)

    def anchor(self, line: Optional[int] = None) -> str:
        ln = line if line is not None else self.line
        where = f"{self.path}:{ln}" if ln is not None else f"{self.path}:?"
        return f"{where} {self.src} -> {self.dst} ({self.relation})"


@dataclass(frozen=True)
class DbEdge:
    """One resolved edge read from graph_edges (already repo-relative)."""

    path: str
    src: str                 # source node symbol
    relation: str
    dst: str                 # target node symbol
    dst_path: str
    line: Optional[int]

    @property
    def key(self) -> Tuple[str, str, str, str, str]:
        return (self.path, self.src, self.relation, self.dst, self.dst_path)


@dataclass(frozen=True)
class PendingEdge:
    path: str
    src: str                 # source node symbol (resolved from node id)
    relation: str
    dst_symbol: str

    def bare(self) -> str:
        return self.dst_symbol.split(".")[-1]


@dataclass
class SearchProbe:
    query: str
    gold: List[Tuple[str, str]]   # list of (path, symbol) acceptable answers
    ambiguous: bool
    language: str


@dataclass
class CorpusResult:
    builder: "CorpusBuilder"
    edges: List[EdgeTruth]
    probes: List[SearchProbe]


# ---------------------------------------------------------------------------
# Corpus builder
# ---------------------------------------------------------------------------

class CorpusBuilder:
    """Writes corpus files and derives exact line numbers for ground truth."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.files: Dict[str, str] = {}

    def add_file(self, rel_path: str, content: str) -> None:
        p = self.root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self.files[rel_path.replace("\\", "/")] = content

    def line_of(self, rel_path: str, needle: str, occurrence: int = 1) -> int:
        content = self.files[rel_path]
        seen = 0
        for idx, line in enumerate(content.splitlines(), start=1):
            if needle in line:
                seen += 1
                if seen == occurrence:
                    return idx
        raise AssertionError(
            f"needle {needle!r} (occurrence {occurrence}) not found in {rel_path}"
        )

    def edge(
        self,
        path: str,
        src: str,
        relation: str,
        dst: str,
        dst_path: str,
        line: Optional[int],
        language: str,
        polarity: str = "static_positive",
        category: str = "call",
        description: str = "",
    ) -> EdgeTruth:
        if polarity == "static_positive" and line is None:
            raise AssertionError(f"static_positive edge needs a line: {path} {src}->{dst}")
        if polarity == "static_negative" and line is not None:
            raise AssertionError(f"static_negative edge must not pin a line: {path} {src}->{dst}")
        return EdgeTruth(
            repo=CORPUS_REPO_ID,
            path=path,
            src=src,
            relation=relation,
            dst=dst,
            dst_path=dst_path,
            line=line,
            language=language,
            polarity=polarity,
            category=category,
            description=description,
        )

    def digest(self) -> str:
        payload = json.dumps(
            {p: self.files[p] for p in sorted(self.files)}, ensure_ascii=False
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Pure matcher — no production code involved; unit-testable on synthetic data
# ---------------------------------------------------------------------------

def _bare(symbol: str) -> str:
    return symbol.split(".")[-1]


@dataclass
class ItemOutcome:
    truth: EdgeTruth
    matched: bool
    reason: str              # tp | false_positive | span_mismatch |
                             # identity_unqualified | wrong_target_same_bare_name |
                             # wrong_relation | pending_unresolved | edge_absent
    detail: str = ""


@dataclass
class OracleReport:
    counts: Dict[str, float] = field(default_factory=dict)
    per_language: Dict[str, Dict[str, Dict[str, float]]] = field(default_factory=dict)
    confusion: List[str] = field(default_factory=list)
    false_positive_details: List[Dict[str, object]] = field(default_factory=list)
    dynamic: Dict[str, int] = field(default_factory=dict)
    diagnostics: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return {
            "counts": self.counts,
            "per_language": self.per_language,
            "confusion": self.confusion,
            "false_positive_details": self.false_positive_details,
            "dynamic": self.dynamic,
            "diagnostics": self.diagnostics,
        }


def evaluate_edges(
    truths: List[EdgeTruth],
    db_edges: List[DbEdge],
    pending: Optional[List[PendingEdge]] = None,
) -> OracleReport:
    """Exact 6-tuple evaluation. Pure function over plain data."""
    pending = pending or []
    report = OracleReport()

    db_index: Dict[Tuple[str, str, str, str, str], DbEdge] = {}
    by_src_file: Dict[Tuple[str, str, str], List[DbEdge]] = {}
    for e in db_edges:
        db_index[e.key] = e
        by_src_file.setdefault((e.path, e.src, e.relation), []).append(e)

    static_pos = [t for t in truths if t.polarity == "static_positive"]
    static_neg = [t for t in truths if t.polarity == "static_negative"]
    dynamic = [t for t in truths if t.polarity == "dynamic_positive"]

    tp = fn = fp = tn = 0
    fp_negative = fp_unexpected = 0
    per_lang: Dict[str, Dict[str, Dict[str, int]]] = {}

    def _lang_slot(lang: str, relation: str) -> Dict[str, int]:
        lang_rel = per_lang.setdefault(lang, {})
        return lang_rel.setdefault(
            relation, {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        )

    # --- static positives: group by identity, span = set of true call lines ---
    groups: Dict[Tuple[str, str, str, str, str], List[EdgeTruth]] = {}
    for t in static_pos:
        groups.setdefault(t.key, []).append(t)

    explained_keys: Set[Tuple[str, str, str, str, str]] = set()

    for key, members in groups.items():
        t0 = members[0]
        slot = _lang_slot(t0.language, t0.relation)
        row = db_index.get(key)
        true_lines = {t.line for t in members}
        if row is not None and row.line is not None and row.line in true_lines:
            for t in members:
                tp += 1
                slot["tp"] += 1
        else:
            reason = "edge_absent"
            detail = ""
            if row is not None:
                reason = "span_mismatch"
                detail = f"db_line={row.line} expected_lines={sorted(x for x in true_lines if x is not None)}"
            else:
                collisions = [
                    c for c in by_src_file.get((t0.path, t0.src, t0.relation), [])
                    if _bare(c.dst) == _bare(t0.dst)
                ]
                if collisions:
                    same_file = [c for c in collisions if c.dst_path == t0.dst_path]
                    if same_file:
                        reason = "identity_unqualified"
                        explained_keys.update(c.key for c in same_file)
                    else:
                        reason = "wrong_target_same_bare_name"
                        detail = "; ".join(
                            f"db edge -> {c.dst} @ {c.dst_path}:{c.line}" for c in collisions[:3]
                        )
                else:
                    other_rel = [
                        c for c in db_edges
                        if c.path == t0.path and c.src == t0.src
                        and c.dst == t0.dst and c.dst_path == t0.dst_path
                        and c.relation != t0.relation
                    ]
                    if other_rel:
                        reason = "wrong_relation"
                        detail = f"db has relation {other_rel[0].relation!r} at line {other_rel[0].line}"
                    else:
                        pend = [
                            p for p in pending
                            if p.path == t0.path and p.src == t0.src
                            and _bare(p.dst_symbol) == _bare(t0.dst)
                        ]
                        if pend:
                            reason = "pending_unresolved"
                            detail = f"pending dst_symbol={pend[0].dst_symbol!r}"
            for t in members:
                fn += 1
                slot["fn"] += 1
                report.confusion.append(
                    f"{t.anchor()} [{reason}] {t.category}: {detail or t.description}".rstrip()
                )

    # --- static negatives: identity tuple at ANY line is a false positive ---
    matched_negative_keys: Set[Tuple[str, str, str, str, str]] = set()
    for t in static_neg:
        slot = _lang_slot(t.language, t.relation)
        row = db_index.get(t.key)
        if row is not None:
            fp += 1
            fp_negative += 1
            slot["fp"] += 1
            matched_negative_keys.add(t.key)
            report.confusion.append(
                f"{t.anchor(row.line)} [false_positive] {t.category}: {t.description}".rstrip()
            )
            report.false_positive_details.append({
                "anchor": t.anchor(row.line),
                "category": t.category,
                "db_line": row.line,
                "description": t.description,
            })
        else:
            tn += 1
            slot["tn"] += 1

    # --- unexpected resolved 'calls' edges from GT-covered source functions ---
    covered_srcs = {(t.path, t.src) for t in static_pos}
    gt_positive_keys = set(groups.keys())
    dynamic_keys = {t.key for t in dynamic}
    for e in db_edges:
        if e.relation != "calls":
            continue
        if (e.path, e.src) not in covered_srcs:
            continue
        if e.key in gt_positive_keys or e.key in matched_negative_keys:
            continue
        if e.key in dynamic_keys:
            continue
        # Edges already consumed as the under-qualified form of a true edge are
        # reported once as identity_unqualified FN — do not double-punish here.
        if e.key in explained_keys:
            continue
        fp += 1
        fp_unexpected += 1
        lang = _language_of_path(e.path)
        _lang_slot(lang, "calls")["fp"] += 1
        report.confusion.append(
            f"{e.path}:{e.line} {e.src} -> {e.dst} (calls) [unexpected_edge]"
        )
        report.false_positive_details.append({
            "anchor": f"{e.path}:{e.line} {e.src} -> {e.dst} (calls)",
            "category": "unexpected_edge",
            "db_line": e.line,
            "description": "resolved calls edge from a GT-covered source, absent from ground truth",
        })

    # --- dynamic positives: claims are optional; wrong-target claims tracked ---
    dyn_counts = {"total": len(dynamic), "claimed_exact": 0,
                  "claimed_same_bare_other": 0, "unclaimed": 0}
    for t in dynamic:
        if db_index.get(t.key) is not None:
            dyn_counts["claimed_exact"] += 1
            continue
        collisions = [
            c for c in by_src_file.get((t.path, t.src, t.relation), [])
            if _bare(c.dst) == _bare(t.dst) and c.key != t.key
        ]
        if collisions:
            dyn_counts["claimed_same_bare_other"] += 1
            report.confusion.append(
                f"{t.anchor(collisions[0].line)} [dynamic_misresolution] {t.category}: "
                f"claimed {collisions[0].dst} @ {collisions[0].dst_path} instead of {t.dst} @ {t.dst_path}"
            )
        else:
            dyn_counts["unclaimed"] += 1
    report.dynamic = dyn_counts

    # --- diagnostics ---
    identity_tp = sum(1 for key in groups if db_index.get(key) is not None)
    total_members = sum(len(m) for m in groups.values())
    report.diagnostics["identity_only_recall"] = round(
        identity_tp / max(1, len(groups)), 4
    )
    report.diagnostics["legacy_loose_recall_diagnostic"] = round(
        _legacy_loose_match(static_pos, db_edges) / max(1, total_members), 4
    )

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / max(1, len(static_pos))
    report.counts = {
        "static_positive": len(static_pos),
        "static_negative": len(static_neg),
        "dynamic_positive": len(dynamic),
        "true_positives": tp,
        "false_negatives": fn,
        "false_positives": fp,
        "false_positive_negative_matches": fp_negative,
        "false_positive_unexpected_edges": fp_unexpected,
        "true_negatives": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(
            2 * precision * recall / (precision + recall) if (precision + recall) else 0.0, 4
        ),
    }

    breakdown: Dict[str, Dict[str, Dict[str, float]]] = {}
    for lang, rels in per_lang.items():
        out: Dict[str, Dict[str, float]] = {}
        agg = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        for rel, s in sorted(rels.items()):
            prec = s["tp"] / (s["tp"] + s["fp"]) if (s["tp"] + s["fp"]) else 0.0
            rec = s["tp"] / (s["tp"] + s["fn"]) if (s["tp"] + s["fn"]) else 0.0
            out[rel] = {
                "tp": s["tp"], "fp": s["fp"], "fn": s["fn"], "tn": s["tn"],
                "precision": round(prec, 4), "recall": round(rec, 4),
                "f1": round(2 * prec * rec / (prec + rec) if (prec + rec) else 0.0, 4),
            }
            for k in agg:
                agg[k] += s[k]
        prec = agg["tp"] / (agg["tp"] + agg["fp"]) if (agg["tp"] + agg["fp"]) else 0.0
        rec = agg["tp"] / (agg["tp"] + agg["fn"]) if (agg["tp"] + agg["fn"]) else 0.0
        out["overall"] = {
            "tp": agg["tp"], "fp": agg["fp"], "fn": agg["fn"], "tn": agg["tn"],
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(2 * prec * rec / (prec + rec) if (prec + rec) else 0.0, 4),
        }
        breakdown[lang] = out
    report.per_language = breakdown
    return report


def _language_of_path(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".py": "python", ".ts": "typescript", ".js": "javascript",
        ".go": "go", ".rs": "rust", ".java": "java",
    }.get(ext, "unknown")


def _legacy_loose_match(static_pos: List[EdgeTruth], db_edges: List[DbEdge]) -> int:
    """Replicates the pre-v2 3-tier matcher (full/full, full/bare, bare/bare).

    Diagnostic ONLY — quantifies how the old metric inflated recall.
    """
    confirmed: Set[Tuple[str, str, str, str]] = set()
    for e in db_edges:
        confirmed.add((e.path, e.src, e.dst, e.relation))
    hits = 0
    for t in static_pos:
        if (t.path, t.src, t.dst, t.relation) in confirmed:
            hits += 1
        elif (t.path, t.src, _bare(t.dst), t.relation) in confirmed:
            hits += 1
        elif (t.path, _bare(t.src), _bare(t.dst), t.relation) in confirmed:
            hits += 1
    return hits


# ---------------------------------------------------------------------------
# Corpus — 5 Tier-A languages, mandatory adversarial cases (P0.c/P0.d)
# ---------------------------------------------------------------------------

GENERATED_MARKERS = ("Code generated", "DO NOT EDIT", "@generated", "Generated by")


def _python_corpus(b: CorpusBuilder) -> Tuple[List[EdgeTruth], List[SearchProbe]]:
    edges: List[EdgeTruth] = []
    lang = "python"

    # -- core: plain closed-world calls --------------------------------------
    b.add_file("py_pkg/core/math_ops.py", '''
def add(a: int, b: int) -> int:
    return a + b

def multiply(a: int, b: int) -> int:
    return a * b

def compute_tax(amount: float, rate: float) -> float:
    base = multiply(int(amount), 1)
    return base * rate

def discount(price: float, percentage: float) -> float:
    tax = compute_tax(price, 0.1)
    return price - (tax * percentage)
''')
    f = "py_pkg/core/math_ops.py"
    edges.append(b.edge(f, "compute_tax", "calls", "multiply", f, b.line_of(f, "base = multiply"), lang))
    edges.append(b.edge(f, "discount", "calls", "compute_tax", f, b.line_of(f, "tax = compute_tax"), lang))

    b.add_file("py_pkg/core/security.py", '''
import hashlib

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def verify_token(token: str, expected_hash: str) -> bool:
    h = hash_token(token)
    return h == expected_hash
''')
    f = "py_pkg/core/security.py"
    edges.append(b.edge(f, "verify_token", "calls", "hash_token", f, b.line_of(f, "h = hash_token"), lang))

    # -- shadowing negatives + alias-import positive ---------------------------
    b.add_file("py_pkg/shadowed/shadowing.py", '''
from ..core.math_ops import add as run_add, multiply as run_mul
from ..core.security import hash_token

def process_with_param_shadow(run_add, val: int):
    # run_add is a parameter here, NOT the imported function.
    return run_add(val)

def process_with_local_assign(val: int):
    run_mul = lambda x: x * 2
    return run_mul(val)

def process_with_for_target(items):
    for hash_token in items:
        pass
    return hash_token

class Worker:
    def method_with_param_shadow(self, run_add, data):
        return run_add(data)

    def legit_call(self, val: int):
        return run_mul(val, 2)
''')
    f = "py_pkg/shadowed/shadowing.py"
    core = "py_pkg/core/math_ops.py"
    sec = "py_pkg/core/security.py"
    edges.append(b.edge(f, "process_with_param_shadow", "calls", "add", core, None, lang,
                        "static_negative", "shadowed_param",
                        "Parameter shadows imported alias run_add -> add"))
    edges.append(b.edge(f, "process_with_local_assign", "calls", "multiply", core, None, lang,
                        "static_negative", "shadowed_local",
                        "Local lambda shadows imported alias run_mul -> multiply"))
    edges.append(b.edge(f, "Worker.method_with_param_shadow", "calls", "add", core, None, lang,
                        "static_negative", "shadowed_param",
                        "Method parameter shadows imported alias run_add -> add"))
    edges.append(b.edge(f, "process_with_for_target", "calls", "hash_token", sec, None, lang,
                        "static_negative", "shadowed_for_target",
                        "Loop target shadows imported hash_token"))
    edges.append(b.edge(f, "Worker.legit_call", "calls", "multiply", core,
                        b.line_of(f, "return run_mul(val, 2)"), lang,
                        "static_positive", "alias_import",
                        "Real call through imported alias run_mul -> multiply"))

    # -- scopes: same bare name in two scopes + nested scope ------------------
    b.add_file("py_pkg/scopes/scopes.py", '''
def process(data):
    return normalize(data)

def normalize(data):
    return data * 2

class Pipeline:
    def process(self, data):
        return self.normalize_stage(data)

    def normalize_stage(self, data):
        def inner(value):
            return normalize(value)
        return inner(data)

def run_pipeline(data):
    p = Pipeline()
    return p.process(data)
''')
    f = "py_pkg/scopes/scopes.py"
    edges.append(b.edge(f, "process", "calls", "normalize", f, b.line_of(f, "return normalize(data)"), lang))
    edges.append(b.edge(f, "Pipeline.process", "calls", "Pipeline.normalize_stage", f,
                        b.line_of(f, "return self.normalize_stage"), lang, "static_positive", "call"))
    edges.append(b.edge(f, "Pipeline.normalize_stage.inner", "calls", "normalize", f,
                        b.line_of(f, "return normalize(value)"), lang, "static_positive", "nested_scope"))
    edges.append(b.edge(f, "run_pipeline", "calls", "Pipeline", f,
                        b.line_of(f, "p = Pipeline()"), lang, "static_positive", "constructor_call",
                        "p = Pipeline() invokes the class constructor"))
    edges.append(b.edge(f, "run_pipeline", "calls", "Pipeline.process", f,
                        b.line_of(f, "return p.process(data)"), lang, "static_positive",
                        "same_name_two_scopes",
                        "Must resolve to Pipeline.process, never module-level process"))
    edges.append(b.edge(f, "run_pipeline", "calls", "process", f, None, lang,
                        "static_negative", "same_name_two_scopes",
                        "Module-level process must not be the target of p.process()"))

    # -- alias imports ---------------------------------------------------------
    b.add_file("py_pkg/alias/aliases.py", '''
from ..core.math_ops import add as plus
from ..core.security import verify_token as check_token

def compute(x: int, y: int) -> int:
    return plus(x, y)

def guarded(x: int, y: int, tok: str) -> int:
    if check_token(tok, "h"):
        return plus(x, y)
    return 0
''')
    f = "py_pkg/alias/aliases.py"
    edges.append(b.edge(f, "compute", "calls", "add", core, b.line_of(f, "return plus(x, y)"), lang,
                        "static_positive", "alias_import"))
    edges.append(b.edge(f, "guarded", "calls", "verify_token", sec,
                        b.line_of(f, "if check_token(tok"), lang, "static_positive", "alias_import"))
    edges.append(b.edge(f, "guarded", "calls", "add", core,
                        b.line_of(f, "return plus(x, y)", occurrence=2), lang,
                        "static_positive", "alias_import"))

    # -- inheritance (extends) -------------------------------------------------
    b.add_file("py_pkg/dyn/inheritance.py", '''
class Notifier:
    def send(self, msg: str) -> str:
        return "base:" + msg

class LoudNotifier(Notifier):
    def send(self, msg: str) -> str:
        return "loud:" + msg

def notify_straight(msg: str) -> str:
    n = LoudNotifier()
    return n.send(msg)
''')
    f = "py_pkg/dyn/inheritance.py"
    edges.append(b.edge(f, "LoudNotifier", "extends", "Notifier", f, b.line_of(f, "class LoudNotifier(Notifier)"), lang,
                        "static_positive", "extends"))
    edges.append(b.edge(f, "notify_straight", "calls", "LoudNotifier", f,
                        b.line_of(f, "n = LoudNotifier()"), lang, "static_positive", "constructor_call"))
    edges.append(b.edge(f, "notify_straight", "calls", "LoudNotifier.send", f,
                        b.line_of(f, "return n.send(msg)"), lang, "static_positive", "call"))

    # -- dynamic / unsupported --------------------------------------------------
    b.add_file("py_pkg/dyn/dispatch.py", '''
class Notifier:
    def send(self, msg: str) -> str:
        return "base:" + msg

class LoudNotifier(Notifier):
    def send(self, msg: str) -> str:
        return "loud:" + msg

def notify_dynamic(base: Notifier, msg: str) -> str:
    return base.send(msg)

def reflective_call(module, name: str):
    fn = getattr(module, name)
    return fn()

OPS = {}

def invoke(name: str):
    fn = OPS.get(name)
    if fn is None:
        return None
    return fn()

def apply_func(fn, value):
    return fn(value)
''')
    f = "py_pkg/dyn/dispatch.py"
    edges.append(b.edge(f, "notify_dynamic", "calls", "LoudNotifier.send", f,
                        b.line_of(f, "return base.send(msg)"), lang, "dynamic_positive",
                        "virtual_dispatch", "Runtime target for harness call; claim optional"))
    edges.append(b.edge(f, "reflective_call", "calls", "Notifier.send", f, None, lang,
                        "dynamic_positive", "reflection", "getattr-resolved target"))
    edges.append(b.edge(f, "invoke", "calls", "Notifier.send", f, None, lang,
                        "dynamic_positive", "di", "Registry-table dispatch"))
    edges.append(b.edge(f, "apply_func", "calls", "Notifier.send", f, None, lang,
                        "dynamic_positive", "function_pointer", "First-class function value"))

    # -- generated file (claim optional) ---------------------------------------
    b.add_file("py_pkg/generated/gen_models.py", '''# Code generated by corpus-tool. DO NOT EDIT.
from ..core.math_ops import compute_tax

def generated_entry(amount: float) -> float:
    return compute_tax(amount, 0.3)
''')
    f = "py_pkg/generated/gen_models.py"
    edges.append(b.edge(f, "generated_entry", "calls", "compute_tax", core,
                        b.line_of(f, "return compute_tax(amount, 0.3)"), lang,
                        "dynamic_positive", "generated_file",
                        "Generated file; indexing optional"))

    # -- caller outside the package ---------------------------------------------
    b.add_file("scripts/run_all.py", '''
from py_pkg.core.math_ops import compute_tax, discount
from py_pkg.scopes.scopes import run_pipeline

def main(amount: float):
    t = compute_tax(amount, 0.2)
    d = discount(t, 0.1)
    r = run_pipeline(t)
    return d, r
''')
    f = "scripts/run_all.py"
    edges.append(b.edge(f, "main", "calls", "compute_tax", "py_pkg/core/math_ops.py",
                        b.line_of(f, "t = compute_tax(amount, 0.2)"), lang,
                        "static_positive", "caller_outside_module"))
    edges.append(b.edge(f, "main", "calls", "discount", "py_pkg/core/math_ops.py",
                        b.line_of(f, "d = discount(t, 0.1)"), lang,
                        "static_positive", "caller_outside_module"))
    edges.append(b.edge(f, "main", "calls", "run_pipeline", "py_pkg/scopes/scopes.py",
                        b.line_of(f, "r = run_pipeline(t)"), lang,
                        "static_positive", "caller_outside_module"))

    # -- scalable services -------------------------------------------------------
    for i in range(1, 61):
        rel = f"py_pkg/services/service_{i}.py"
        b.add_file(rel, f'''
from ..core.math_ops import compute_tax, discount
from ..core.security import verify_token

class Service{i}:
    def __init__(self, svc_id: int):
        self.svc_id = svc_id

    def execute_calc(self, amount: float) -> float:
        t = compute_tax(amount, 0.05)
        return discount(t, 0.02)

    def auth_and_run(self, token: str, amount: float) -> float:
        if verify_token(token, "secret"):
            return self.execute_calc(amount)
        return 0.0

def run_service_{i}(token: str, amount: float) -> float:
    s = Service{i}({i})
    return s.auth_and_run(token, amount)
''')
        edges.append(b.edge(rel, f"Service{i}.execute_calc", "calls", "compute_tax", core,
                            b.line_of(rel, "t = compute_tax(amount, 0.05)"), lang))
        edges.append(b.edge(rel, f"Service{i}.execute_calc", "calls", "discount", core,
                            b.line_of(rel, "return discount(t, 0.02)"), lang))
        edges.append(b.edge(rel, f"Service{i}.auth_and_run", "calls", "verify_token", sec,
                            b.line_of(rel, 'if verify_token(token, "secret")'), lang))
        edges.append(b.edge(rel, f"Service{i}.auth_and_run", "calls", f"Service{i}.execute_calc", rel,
                            b.line_of(rel, "return self.execute_calc(amount)"), lang))
        edges.append(b.edge(rel, f"run_service_{i}", "calls", f"Service{i}.auth_and_run", rel,
                            b.line_of(rel, "return s.auth_and_run(token, amount)"), lang))
        edges.append(b.edge(rel, f"run_service_{i}", "calls", f"Service{i}", rel,
                            b.line_of(rel, f"s = Service{i}({i})"), lang,
                            "static_positive", "constructor_call"))
        if i <= 20:
            edges.append(b.edge(rel, f"Service{i}.execute_calc", "calls", "non_existent_function",
                                "py_pkg/nowhere.py", None, lang, "static_negative", "negative_target",
                                "Target does not exist"))
            edges.append(b.edge(rel, f"Service{i}.execute_calc", "calls", "ValidateKey",
                                "go_pkg/storage/db.go", None, lang, "static_negative", "cross_lang_negative",
                                "Cross-language invalid target"))

    probes = [
        SearchProbe("compute_tax", [("py_pkg/core/math_ops.py", "compute_tax")], False, lang),
        SearchProbe("verify_token", [("py_pkg/core/security.py", "verify_token")], False, lang),
        SearchProbe("process", [("py_pkg/scopes/scopes.py", "process"),
                                ("py_pkg/scopes/scopes.py", "Pipeline.process")], True, lang),
        SearchProbe("normalize", [("py_pkg/scopes/scopes.py", "normalize"),
                                  ("py_pkg/scopes/scopes.py", "Pipeline.normalize_stage")], True, lang),
    ]
    return edges, probes


def _typescript_corpus(b: CorpusBuilder) -> Tuple[List[EdgeTruth], List[SearchProbe]]:
    edges: List[EdgeTruth] = []
    lang = "typescript"

    b.add_file("ts_pkg/models/order.ts", '''
export interface Order {
    id: string;
    amount: number;
}

export function validateOrder(order: Order): boolean {
    return order.amount > 0 && order.id.length > 0;
}

export function formatOrder(order: Order): string {
    if (!validateOrder(order)) {
        return "Invalid";
    }
    return `Order ${order.id}: ${order.amount}`;
}
''')
    f = "ts_pkg/models/order.ts"
    edges.append(b.edge(f, "formatOrder", "calls", "validateOrder", f,
                        b.line_of(f, "if (!validateOrder(order))"), lang))

    # -- interface implements + dynamic dispatch --------------------------------
    b.add_file("ts_pkg/models/shapes.ts", '''
export interface Shape {
    area(): number;
}

export class Circle implements Shape {
    constructor(private r: number) {}

    area(): number {
        return this.r * this.r * 3;
    }

    describe(): string {
        return "area=" + this.area();
    }
}

export function render(shape: Shape): string {
    return "render:" + shape.area();
}
''')
    f = "ts_pkg/models/shapes.ts"
    edges.append(b.edge(f, "Circle", "implements", "Shape", f, b.line_of(f, "class Circle implements Shape"), lang,
                        "static_positive", "implements"))
    edges.append(b.edge(f, "Circle.describe", "calls", "Circle.area", f,
                        b.line_of(f, 'return "area=" + this.area()'), lang))
    edges.append(b.edge(f, "render", "calls", "Circle.area", f,
                        b.line_of(f, 'return "render:" + shape.area()'), lang,
                        "dynamic_positive", "interface_dispatch",
                        "Interface-typed receiver; runtime target Circle.area"))

    # -- comment / string literal traps ------------------------------------------
    b.add_file("ts_pkg/comments/comment_trap.ts", '''
// function validateOrder(fake: any) { return false; }
/*
export function compute_tax() { return 0; }
*/
export function realAction(): string {
    const message = "function discount() is deprecated";
    return message;
}
''')
    f = "ts_pkg/comments/comment_trap.ts"
    edges.append(b.edge(f, "realAction", "calls", "discount", "ts_pkg/models/order.ts", None, lang,
                        "static_negative", "string_literal", "String literal must not become a call edge"))
    edges.append(b.edge(f, "realAction", "calls", "validateOrder", "ts_pkg/models/order.ts", None, lang,
                        "static_negative", "comment_span", "Commented-out declaration must not be called"))

    # -- scopes -------------------------------------------------------------------
    b.add_file("ts_pkg/scopes/scopes.ts", '''
export function process(input: string): string {
    return normalize(input);
}

export function normalize(input: string): string {
    return input.trim();
}

export class Stage {
    process(input: string): string {
        return this.normalizeStage(input);
    }

    normalizeStage(input: string): string {
        const inner = (value: string) => normalize(value);
        return inner(input);
    }
}

export function runStage(input: string): string {
    const s = new Stage();
    return s.process(input);
}
''')
    f = "ts_pkg/scopes/scopes.ts"
    edges.append(b.edge(f, "process", "calls", "normalize", f, b.line_of(f, "return normalize(input);"), lang))
    edges.append(b.edge(f, "Stage.process", "calls", "Stage.normalizeStage", f,
                        b.line_of(f, "return this.normalizeStage(input);"), lang))
    edges.append(b.edge(f, "Stage.normalizeStage", "calls", "normalize", f,
                        b.line_of(f, "return inner(input);"), lang, "static_positive", "nested_scope"))
    edges.append(b.edge(f, "runStage", "calls", "Stage", f,
                        b.line_of(f, "const s = new Stage();"), lang, "static_positive", "constructor_call"))
    edges.append(b.edge(f, "runStage", "calls", "Stage.process", f,
                        b.line_of(f, "return s.process(input);"), lang, "static_positive",
                        "same_name_two_scopes"))
    edges.append(b.edge(f, "runStage", "calls", "process", f, None, lang,
                        "static_negative", "same_name_two_scopes",
                        "s.process() must resolve to Stage.process, not module process"))

    # -- alias import ----------------------------------------------------------------
    b.add_file("ts_pkg/alias/aliases.ts", '''
import { validateOrder as checkOrder } from "../models/order";

export function verify(order: Order2): boolean {
    return checkOrder(order as any);
}

interface Order2 { id: string; amount: number; }
''')
    f = "ts_pkg/alias/aliases.ts"
    edges.append(b.edge(f, "verify", "calls", "validateOrder", "ts_pkg/models/order.ts",
                        b.line_of(f, "return checkOrder(order as any);"), lang,
                        "static_positive", "alias_import"))

    # -- overload + call-site collapse --------------------------------------------------
    b.add_file("ts_pkg/overload/poly.ts", '''
export function fmt(x: string): string;
export function fmt(x: number): string;
export function fmt(x: any): string {
    return pad(String(x));
}

export function pad(s: string): string {
    return " " + s + " ";
}

export function callBoth(a: string, b: number): string {
    return fmt(a) + fmt(b);
}
''')
    f = "ts_pkg/overload/poly.ts"
    edges.append(b.edge(f, "fmt", "calls", "pad", f, b.line_of(f, 'return pad(String(x));'), lang,
                        "static_positive", "overload"))
    edges.append(b.edge(f, "callBoth", "calls", "fmt", f, b.line_of(f, "return fmt(a)"), lang,
                        "static_positive", "overload", "first call site"))
    edges.append(b.edge(f, "callBoth", "calls", "fmt", f, b.line_of(f, "+ fmt(b);"), lang,
                        "static_positive", "overload", "second call site — collapses to same edge row"))

    # -- dynamic -------------------------------------------------------------------------
    b.add_file("ts_pkg/dyn/dispatch.ts", '''
import { Shape } from "../models/shapes";

export class Renderer {
    constructor(private shape: Shape) {}

    draw(): string {
        return "draw:" + this.shape.area();
    }
}

export function indirect(x: string): string {
    const f = fmtRef;
    return f(x);
}

declare function fmtRef(x: string): string;

export function dynamicMethod(shape: Shape, name: string): number {
    return (shape as any)[name]();
}
''')
    f = "ts_pkg/dyn/dispatch.ts"
    edges.append(b.edge(f, "Renderer.draw", "calls", "Circle.area", "ts_pkg/models/shapes.ts", None, lang,
                        "dynamic_positive", "di", "Constructor-injected interface field"))
    edges.append(b.edge(f, "indirect", "calls", "fmtRef", f, None, lang,
                        "dynamic_positive", "function_pointer", "Local alias of function value"))
    edges.append(b.edge(f, "dynamicMethod", "calls", "Circle.area", "ts_pkg/models/shapes.ts", None, lang,
                        "dynamic_positive", "reflection", "Computed member access"))

    # -- generated file ---------------------------------------------------------------------
    b.add_file("ts_pkg/generated/gen_api.generated.ts", '''// Code generated by corpus-tool. DO NOT EDIT.
import { validateOrder } from "../models/order";

export function generatedCheck(order: any): boolean {
    return validateOrder(order);
}
''')
    f = "ts_pkg/generated/gen_api.generated.ts"
    edges.append(b.edge(f, "generatedCheck", "calls", "validateOrder", "ts_pkg/models/order.ts", None, lang,
                        "dynamic_positive", "generated_file"))

    # -- caller outside module -----------------------------------------------------------------
    b.add_file("scripts/main.ts", '''
import { computeTaxAmount } from "../ts_pkg/generated/gen_api.generated";

declare function computeTaxAmount(x: number): number;
''')
    f = "scripts/main.ts"
    edges.append(b.edge(f, "scripts/main.ts", "calls", "generatedCheck",
                        "ts_pkg/generated/gen_api.generated.ts", None, lang,
                        "dynamic_positive", "caller_outside_module",
                        "Script-level import of generated module"))

    # -- scalable services -----------------------------------------------------------------------
    for i in range(1, 41):
        rel = f"ts_pkg/services/order_svc_{i}.ts"
        b.add_file(rel, f'''
import {{ Order, validateOrder, formatOrder }} from "../models/order";

export class OrderService{i} {{
    private svcId: number = {i};

    public check(order: Order): boolean {{
        return validateOrder(order);
    }}

    public process(order: Order): string {{
        if (this.check(order)) {{
            return formatOrder(order);
        }}
        return "Failed";
    }}
}}

export function handleOrder{i}(order: Order): string {{
    const svc = new OrderService{i}();
    return svc.process(order);
}}
''')
        edges.append(b.edge(rel, f"OrderService{i}.check", "calls", "validateOrder",
                            "ts_pkg/models/order.ts", b.line_of(rel, "return validateOrder(order);"), lang))
        edges.append(b.edge(rel, f"OrderService{i}.process", "calls", f"OrderService{i}.check", rel,
                            b.line_of(rel, "if (this.check(order)) {"), lang))
        edges.append(b.edge(rel, f"OrderService{i}.process", "calls", "formatOrder",
                            "ts_pkg/models/order.ts", b.line_of(rel, "return formatOrder(order);"), lang))
        edges.append(b.edge(rel, f"handleOrder{i}", "calls", f"OrderService{i}.process", rel,
                            b.line_of(rel, "return svc.process(order);"), lang))
        edges.append(b.edge(rel, f"handleOrder{i}", "calls", f"OrderService{i}", rel,
                            b.line_of(rel, f"const svc = new OrderService{i}();"), lang,
                            "static_positive", "constructor_call"))
        if i <= 15:
            edges.append(b.edge(rel, f"OrderService{i}.check", "calls", "hash_token",
                                "py_pkg/core/security.py", None, lang, "static_negative", "cross_lang_negative"))
            edges.append(b.edge(rel, f"OrderService{i}.check", "calls", "unknownMethod",
                                "ts_pkg/models/order.ts", None, lang, "static_negative", "negative_target"))

    probes = [
        SearchProbe("formatOrder", [("ts_pkg/models/order.ts", "formatOrder")], False, lang),
        SearchProbe("validateOrder", [("ts_pkg/models/order.ts", "validateOrder")], False, lang),
        SearchProbe("process", [("ts_pkg/scopes/scopes.ts", "process"),
                                ("ts_pkg/scopes/scopes.ts", "Stage.process")], True, lang),
        SearchProbe("normalizeStage", [("ts_pkg/scopes/scopes.ts", "Stage.normalizeStage")], False, lang),
    ]
    return edges, probes


def _go_corpus(b: CorpusBuilder) -> Tuple[List[EdgeTruth], List[SearchProbe]]:
    edges: List[EdgeTruth] = []
    lang = "go"
    storage = "go_pkg/storage/db.go"

    b.add_file(storage, '''
package storage

type Record struct {
    Key string
    Val string
}

func ValidateKey(k string) bool {
    return len(k) > 0
}

func FormatRecord(r Record) string {
    if !ValidateKey(r.Key) {
        return ""
    }
    return r.Key + "=" + r.Val
}
''')
    edges.append(b.edge(storage, "FormatRecord", "calls", "ValidateKey", storage,
                        b.line_of(storage, "if !ValidateKey(r.Key)"), lang))

    # -- scopes: free func + method with the same bare name --------------------------
    b.add_file("go_pkg/scopes/scopes.go", '''
package scopes

func process(s string) string {
    return normalize(s)
}

func normalize(s string) string {
    return s + "!"
}

type Stage struct{}

func (st *Stage) Process(s string) string {
    return st.normalizeStage(s)
}

func (st *Stage) normalizeStage(s string) string {
    return process(s)
}

func RunStage(s string) string {
    st := &Stage{}
    return st.Process(s)
}
''')
    f = "go_pkg/scopes/scopes.go"
    edges.append(b.edge(f, "process", "calls", "normalize", f, b.line_of(f, "return normalize(s)"), lang))
    edges.append(b.edge(f, "Stage.Process", "calls", "Stage.normalizeStage", f,
                        b.line_of(f, "return st.normalizeStage(s)"), lang))
    edges.append(b.edge(f, "Stage.normalizeStage", "calls", "process", f,
                        b.line_of(f, "return process(s)"), lang))
    edges.append(b.edge(f, "RunStage", "calls", "Stage.Process", f,
                        b.line_of(f, "return st.Process(s)"), lang, "static_positive",
                        "same_name_two_scopes"))
    edges.append(b.edge(f, "RunStage", "calls", "process", f, None, lang,
                        "static_negative", "same_name_two_scopes",
                        "st.Process() is the method, never the free function process"))

    # -- alias import (package alias) --------------------------------------------------
    b.add_file("go_pkg/alias/alias.go", '''
package alias

import stor "go_pkg/storage"

func Check(k string) bool {
    return stor.ValidateKey(k)
}
''')
    f = "go_pkg/alias/alias.go"
    edges.append(b.edge(f, "Check", "calls", "ValidateKey", storage,
                        b.line_of(f, "return stor.ValidateKey(k)"), lang,
                        "static_positive", "alias_import"))

    # -- same method name on two receiver types ------------------------------------------
    b.add_file("go_pkg/samename/samename.go", '''
package samename

type Doc struct{ ID int }
type Blob struct{ ID int }

func (d *Doc) Save() bool  { return d.ID > 0 }
func (b *Blob) Save() bool { return b.ID > 0 }

func SaveAll(d *Doc, bl *Blob) bool {
    return d.Save() && bl.Save()
}
''')
    f = "go_pkg/samename/samename.go"
    edges.append(b.edge(f, "SaveAll", "calls", "Doc.Save", f, b.line_of(f, "return d.Save()"), lang,
                        "static_positive", "same_name_two_scopes"))
    edges.append(b.edge(f, "SaveAll", "calls", "Blob.Save", f, b.line_of(f, "&& bl.Save()"), lang,
                        "static_positive", "same_name_two_scopes"))

    # -- interface dispatch (dynamic) ------------------------------------------------------
    b.add_file("go_pkg/shapes/shapes.go", '''
package shapes

type Shape interface {
    Area() float64
}

type Circle struct{ R float64 }

func (c Circle) Area() float64 { return c.R * c.R * 3 }

func Render(s Shape) string {
    return "area:" + string(rune(int(s.Area())))
}
''')
    f = "go_pkg/shapes/shapes.go"
    edges.append(b.edge(f, "Render", "calls", "Circle.Area", f,
                        b.line_of(f, "s.Area()"), lang, "dynamic_positive", "interface_dispatch",
                        "Interface receiver; runtime target Circle.Area"))

    # -- dynamic: fn value, reflection, DI ----------------------------------------------------
    b.add_file("go_pkg/dyn/dispatch.go", '''
package dyn

import (
    "reflect"
)

type StringFn func(string) string

func Apply(f StringFn, s string) string {
    return f(s)
}

func InvokeReflect(x interface{}) []reflect.Value {
    m := reflect.ValueOf(x).MethodByName("Save")
    return m.Call(nil)
}

type Saver interface{ Save() bool }

type Service struct {
    Store Saver
}

func (s *Service) Flush() bool {
    return s.Store.Save()
}
''')
    f = "go_pkg/dyn/dispatch.go"
    edges.append(b.edge(f, "Apply", "calls", "Doc.Save", "go_pkg/samename/samename.go", None, lang,
                        "dynamic_positive", "function_pointer", "Function value parameter"))
    edges.append(b.edge(f, "InvokeReflect", "calls", "Doc.Save", "go_pkg/samename/samename.go", None, lang,
                        "dynamic_positive", "reflection", "MethodByName resolution"))
    edges.append(b.edge(f, "Service.Flush", "calls", "Doc.Save", "go_pkg/samename/samename.go", None, lang,
                        "dynamic_positive", "di", "Injected interface field"))

    # -- generated file -------------------------------------------------------------------------
    b.add_file("go_pkg/generated/gen.go", '''// Code generated by corpus-tool. DO NOT EDIT.
package generated

import "go_pkg/storage"

func CheckGenerated(k string) bool {
    return storage.ValidateKey(k)
}
''')
    f = "go_pkg/generated/gen.go"
    edges.append(b.edge(f, "CheckGenerated", "calls", "ValidateKey", storage, None, lang,
                        "dynamic_positive", "generated_file"))

    # -- caller outside module --------------------------------------------------------------------
    b.add_file("cmd/main.go", '''package main

import (
    "fmt"
    "go_pkg/storage"
)

func main() {
    ok := storage.ValidateKey("k")
    fmt.Println(ok)
}
''')
    f = "cmd/main.go"
    edges.append(b.edge(f, "main", "calls", "ValidateKey", storage,
                        b.line_of(f, 'ok := storage.ValidateKey("k")'), lang,
                        "static_positive", "caller_outside_module"))

    # -- scalable workers ---------------------------------------------------------------------------
    for i in range(1, 31):
        rel = f"go_pkg/workers/worker_{i}.go"
        b.add_file(rel, f'''
package workers

import "go_pkg/storage"

type Worker{i} struct {{
    ID int
}}

func (w *Worker{i}) Check(k string) bool {{
    return storage.ValidateKey(k)
}}

func (w *Worker{i}) Process(r storage.Record) string {{
    if w.Check(r.Key) {{
        return storage.FormatRecord(r)
    }}
    return ""
}}

func (w *Worker{i}) Run(r storage.Record) string {{
    return w.Process(r)
}}

func ExecuteWorker{i}(r storage.Record) string {{
    w := &Worker{i}{{ID: {i}}}
    return w.Run(r)
}}
''')
        edges.append(b.edge(rel, f"Worker{i}.Check", "calls", "ValidateKey", storage,
                            b.line_of(rel, "return storage.ValidateKey(k)"), lang))
        edges.append(b.edge(rel, f"Worker{i}.Process", "calls", f"Worker{i}.Check", rel,
                            b.line_of(rel, "if w.Check(r.Key) {"), lang))
        edges.append(b.edge(rel, f"Worker{i}.Process", "calls", "FormatRecord", storage,
                            b.line_of(rel, "return storage.FormatRecord(r)"), lang))
        edges.append(b.edge(rel, f"Worker{i}.Run", "calls", f"Worker{i}.Process", rel,
                            b.line_of(rel, "return w.Process(r)"), lang))
        edges.append(b.edge(rel, f"ExecuteWorker{i}", "calls", f"Worker{i}.Run", rel,
                            b.line_of(rel, "return w.Run(r)"), lang))
        if i <= 10:
            edges.append(b.edge(rel, f"Worker{i}.Check", "calls", "compute_tax",
                                "py_pkg/core/math_ops.py", None, lang, "static_negative", "cross_lang_negative"))

    probes = [
        SearchProbe("ValidateKey", [(storage, "ValidateKey")], False, lang),
        SearchProbe("FormatRecord", [(storage, "FormatRecord")], False, lang),
        SearchProbe("Process", [("go_pkg/scopes/scopes.go", "Stage.Process")], True, lang),
        SearchProbe("Save", [("go_pkg/samename/samename.go", "Doc.Save"),
                             ("go_pkg/samename/samename.go", "Blob.Save")], True, lang),
    ]
    return edges, probes


def _rust_corpus(b: CorpusBuilder) -> Tuple[List[EdgeTruth], List[SearchProbe]]:
    edges: List[EdgeTruth] = []
    lang = "rust"

    b.add_file("rust_pkg/src/crypto.rs", '''
pub fn hash_data(input: &str) -> String {
    format!("hash_{}", input)
}

pub fn verify_data(input: &str, expected: &str) -> bool {
    let h = hash_data(input);
    h == expected
}
''')
    f = "rust_pkg/src/crypto.rs"
    edges.append(b.edge(f, "verify_data", "calls", "hash_data", f,
                        b.line_of(f, "let h = hash_data(input);"), lang))

    # -- scopes: free fn + impl method same bare name --------------------------------------
    b.add_file("rust_pkg/src/scopes.rs", '''
pub fn process(s: &str) -> String {
    normalize(s)
}

pub fn normalize(s: &str) -> String {
    format!("{}!", s)
}

pub struct Stage;

impl Stage {
    pub fn process(&self, s: &str) -> String {
        self.normalize_stage(s)
    }

    pub fn normalize_stage(&self, s: &str) -> String {
        process(s)
    }
}

pub fn run_stage(s: &str) -> String {
    let st = Stage;
    st.process(s)
}
''')
    f = "rust_pkg/src/scopes.rs"
    edges.append(b.edge(f, "process", "calls", "normalize", f, b.line_of(f, "normalize(s)"), lang))
    edges.append(b.edge(f, "Stage.process", "calls", "Stage.normalize_stage", f,
                        b.line_of(f, "self.normalize_stage(s)"), lang))
    edges.append(b.edge(f, "Stage.normalize_stage", "calls", "process", f,
                        b.line_of(f, "process(s)"), lang))
    edges.append(b.edge(f, "run_stage", "calls", "Stage.process", f,
                        b.line_of(f, "st.process(s)"), lang, "static_positive", "same_name_two_scopes"))
    edges.append(b.edge(f, "run_stage", "calls", "process", f, None, lang,
                        "static_negative", "same_name_two_scopes",
                        "st.process() is the impl method, not the free fn"))

    # -- alias use ------------------------------------------------------------------------
    b.add_file("rust_pkg/src/alias.rs", '''
use crate::crypto::hash_data as hd;

pub fn digest(s: &str) -> String {
    hd(s)
}
''')
    f = "rust_pkg/src/alias.rs"
    edges.append(b.edge(f, "digest", "calls", "hash_data", "rust_pkg/src/crypto.rs",
                        b.line_of(f, "hd(s)"), lang, "static_positive", "alias_import"))

    # -- same method name on two types ----------------------------------------------------------
    b.add_file("rust_pkg/src/samename.rs", '''
pub struct Doc { pub id: u32 }
pub struct Blob { pub id: u32 }

impl Doc {
    pub fn save(&self) -> bool { self.id > 0 }
}

impl Blob {
    pub fn save(&self) -> bool { self.id > 0 }
}

pub fn save_all(d: &Doc, b: &Blob) -> bool {
    d.save() && b.save()
}
''')
    f = "rust_pkg/src/samename.rs"
    edges.append(b.edge(f, "save_all", "calls", "Doc.save", f, b.line_of(f, "d.save() &&"), lang,
                        "static_positive", "same_name_two_scopes"))
    edges.append(b.edge(f, "save_all", "calls", "Blob.save", f, b.line_of(f, "b.save()"), lang,
                        "static_positive", "same_name_two_scopes"))

    # -- trait dispatch (dynamic) + implements ----------------------------------------------------
    b.add_file("rust_pkg/src/shape.rs", '''
pub trait Shape {
    fn area(&self) -> f64;
}

pub struct Circle { pub r: f64 }

impl Shape for Circle {
    fn area(&self) -> f64 { self.r * self.r * 3.0 }
}

impl Circle {
    pub fn describe(&self) -> String { format!("area={}", self.area()) }
}

pub fn render(s: &dyn Shape) -> String {
    format!("{}", s.area())
}
''')
    f = "rust_pkg/src/shape.rs"
    edges.append(b.edge(f, "Circle", "implements", "Shape", f, b.line_of(f, "impl Shape for Circle"), lang,
                        "static_positive", "implements"))
    edges.append(b.edge(f, "Circle.describe", "calls", "Circle.area", f,
                        b.line_of(f, 'format!("area={}", self.area())'), lang))
    edges.append(b.edge(f, "render", "calls", "Circle.area", f,
                        b.line_of(f, "s.area()"), lang, "dynamic_positive", "virtual_dispatch",
                        "dyn trait receiver; runtime target Circle.area"))

    # -- dynamic: fn pointer, DI, macros ------------------------------------------------------------
    b.add_file("rust_pkg/src/dyn_dispatch.rs", '''
pub type StrFn = fn(&str) -> String;

pub fn apply(f: StrFn, s: &str) -> String {
    f(s)
}

pub struct Runner {
    pub hasher: StrFn,
}

impl Runner {
    pub fn run(&self, s: &str) -> String {
        (self.hasher)(s)
    }
}

macro_rules! shout {
    ($e:expr) => {
        format!("{}!", $e)
    };
}

pub fn announce(s: &str) -> String {
    shout!(s)
}
''')
    f = "rust_pkg/src/dyn_dispatch.rs"
    edges.append(b.edge(f, "apply", "calls", "hash_data", "rust_pkg/src/crypto.rs", None, lang,
                        "dynamic_positive", "function_pointer"))
    edges.append(b.edge(f, "Runner.run", "calls", "hash_data", "rust_pkg/src/crypto.rs", None, lang,
                        "dynamic_positive", "di"))
    edges.append(b.edge(f, "announce", "calls", "hash_data", "rust_pkg/src/crypto.rs", None, lang,
                        "dynamic_positive", "macros"))

    # -- generated file -------------------------------------------------------------------------------
    b.add_file("rust_pkg/src/generated.rs", '''// @generated by corpus-tool. DO NOT EDIT.
use crate::crypto::hash_data;

pub fn generated_hash(s: &str) -> String {
    hash_data(s)
}
''')
    f = "rust_pkg/src/generated.rs"
    edges.append(b.edge(f, "generated_hash", "calls", "hash_data", "rust_pkg/src/crypto.rs", None, lang,
                        "dynamic_positive", "generated_file"))

    # -- caller outside module: binary crate root ---------------------------------------------------------
    b.add_file("rust_pkg/src/main.rs", '''
mod crypto;
mod scopes;

fn main() {
    let h = crypto::hash_data("x");
    let p = scopes::process("y");
    let _ = (h, p);
}
''')
    f = "rust_pkg/src/main.rs"
    edges.append(b.edge(f, "main", "calls", "hash_data", "rust_pkg/src/crypto.rs",
                        b.line_of(f, 'crypto::hash_data("x")'), lang,
                        "static_positive", "caller_outside_module"))
    edges.append(b.edge(f, "main", "calls", "process", "rust_pkg/src/scopes.rs",
                        b.line_of(f, 'scopes::process("y")'), lang,
                        "static_positive", "caller_outside_module"))

    # -- scalable modules -----------------------------------------------------------------------------------
    for i in range(1, 31):
        rel = f"rust_pkg/src/mod_{i}.rs"
        b.add_file(rel, f'''
use crate::crypto::{{hash_data, verify_data}};

pub struct Engine{i} {{
    pub id: u32,
}}

impl Engine{i} {{
    pub fn check(&self, data: &str) -> bool {{
        verify_data(data, "expected")
    }}

    pub fn process(&self, data: &str) -> String {{
        if self.check(data) {{
            return hash_data(data);
        }}
        String::new()
    }}
}}

pub fn run_engine_{i}(data: &str) -> String {{
    let e = Engine{i} {{ id: {i} }};
    e.process(data)
}}
''')
        edges.append(b.edge(rel, f"Engine{i}.check", "calls", "verify_data", "rust_pkg/src/crypto.rs",
                            b.line_of(rel, 'verify_data(data, "expected")'), lang))
        edges.append(b.edge(rel, f"Engine{i}.process", "calls", f"Engine{i}.check", rel,
                            b.line_of(rel, "if self.check(data) {"), lang))
        edges.append(b.edge(rel, f"Engine{i}.process", "calls", "hash_data", "rust_pkg/src/crypto.rs",
                            b.line_of(rel, "return hash_data(data);"), lang))
        edges.append(b.edge(rel, f"run_engine_{i}", "calls", f"Engine{i}.process", rel,
                            b.line_of(rel, "e.process(data)"), lang))
        if i <= 10:
            edges.append(b.edge(rel, f"Engine{i}.check", "calls", "ValidateKey",
                                "go_pkg/storage/db.go", None, lang, "static_negative", "cross_lang_negative"))

    # -- implements/extends NEGATIVES (Rust) -------------------------------------------------------
    # Cases that must NOT resolve as implements/extends: inherent impl blocks,
    # generic/where bounds, commented-out impls, similarly-named lookalikes,
    # and forward references to undefined bases.
    b.add_file("rust_pkg/src/negatives.rs", '''
pub trait Persist {
    fn flush(&self) -> bool;
}

pub trait NotificationHandler {
    fn handle(&self, raw: &str) -> bool;
}

pub struct Store;

pub struct Cache<T> {
    pub backend: T,
}

// impl Persist for Cache<Store> {
//     fn flush(&self) -> bool { true }
// }

impl<T> Cache<T>
where
    T: Sized,
{
    pub fn get(&self, _key: &str) -> Option<String> {
        None
    }
}

pub struct NotificationService;

impl NotificationService {
    pub fn dispatch(&self, raw: &str) -> bool {
        raw.len() > 0
    }
}

pub struct PhantomJob;

// impl Persist for PhantomJob {
//     fn flush(&self) -> bool { false }
// }

pub fn adopt(job: PhantomJob) -> PhantomJob {
    job
}
''')
    f = "rust_pkg/src/negatives.rs"
    edges.append(b.edge(f, "Cache", "implements", "Persist", f, None, lang,
                        "static_negative", "implements_negative",
                        "trait-bound-free generic struct; trait impl only in a comment"))
    edges.append(b.edge(f, "Cache", "implements", "NotificationHandler", f, None, lang,
                        "static_negative", "implements_negative",
                        "where-clause bound must not imply trait implementation"))
    edges.append(b.edge(f, "NotificationService", "implements", "NotificationHandler", f, None, lang,
                        "static_negative", "implements_negative",
                        "similarly-named lookalike; only an inherent impl exists"))
    edges.append(b.edge(f, "PhantomJob", "implements", "Persist", f, None, lang,
                        "static_negative", "implements_negative",
                        "forward reference: only commented impl mentions the pair"))
    edges.append(b.edge("rust_pkg/src/mod_1.rs", "Engine1", "implements", "Shape",
                        "rust_pkg/src/shape.rs", None, lang,
                        "static_negative", "implements_negative",
                        "inherent impl Engine1 must not resolve as implementing Shape"))
    edges.append(b.edge(f, "PhantomJob", "extends", "Persist", f, None, lang,
                        "static_negative", "extends_negative",
                        "Rust has no extends relation; inheritance-style claim must not exist"))

    probes = [
        SearchProbe("hash_data", [("rust_pkg/src/crypto.rs", "hash_data")], False, lang),
        SearchProbe("verify_data", [("rust_pkg/src/crypto.rs", "verify_data")], False, lang),
        SearchProbe("process", [("rust_pkg/src/scopes.rs", "process"),
                                ("rust_pkg/src/scopes.rs", "Stage.process")], True, lang),
        SearchProbe("save", [("rust_pkg/src/samename.rs", "Doc.save"),
                             ("rust_pkg/src/samename.rs", "Blob.save")], True, lang),
    ]
    return edges, probes


def _java_corpus(b: CorpusBuilder) -> Tuple[List[EdgeTruth], List[SearchProbe]]:
    edges: List[EdgeTruth] = []
    lang = "java"

    b.add_file("java_pkg/core/Validator.java", '''
package java_pkg.core;

public class Validator {
    public static boolean isValid(String token) {
        return token != null && !token.isEmpty();
    }

    public static String sanitize(String token) {
        if (!isValid(token)) {
            return "";
        }
        return token.trim();
    }
}
''')
    f = "java_pkg/core/Validator.java"
    edges.append(b.edge(f, "Validator.sanitize", "calls", "Validator.isValid", f,
                        b.line_of(f, "if (!isValid(token))"), lang))

    # -- interface + dynamic dispatch ---------------------------------------------------
    b.add_file("java_pkg/shapes/Shape.java", '''
package java_pkg.shapes;

public interface Shape {
    double area();
}
''')
    b.add_file("java_pkg/shapes/Circle.java", '''
package java_pkg.shapes;

public class Circle implements Shape {
    private final double r;

    public Circle(double r) { this.r = r; }

    public double area() { return r * r * 3; }

    public String describe() { return "area=" + area(); }
}
''')
    b.add_file("java_pkg/shapes/Render.java", '''
package java_pkg.shapes;

public class Render {
    public String render(Shape s) {
        return "render:" + s.area();
    }
}
''')
    edges.append(b.edge("java_pkg/shapes/Circle.java", "Circle", "implements", "Shape",
                        "java_pkg/shapes/Shape.java",
                        b.line_of("java_pkg/shapes/Circle.java", "class Circle implements Shape"),
                        lang, "static_positive", "implements"))
    edges.append(b.edge("java_pkg/shapes/Circle.java", "Circle.describe", "calls", "Circle.area",
                        "java_pkg/shapes/Circle.java",
                        b.line_of("java_pkg/shapes/Circle.java", 'return "area=" + area();'), lang))
    edges.append(b.edge("java_pkg/shapes/Render.java", "Render.render", "calls", "Circle.area",
                        "java_pkg/shapes/Circle.java", None, lang,
                        "dynamic_positive", "interface_dispatch",
                        "Interface-typed parameter; runtime target Circle.area"))

    # -- scopes: static vs instance method with the same bare name ----------------------------
    b.add_file("java_pkg/scopes/Scopes.java", '''
package java_pkg.scopes;

public class Scopes {
    public static String process(String s) {
        return normalize(s);
    }

    public static String normalize(String s) {
        return s + "!";
    }

    public String process(String s, int repeat) {
        return process(s) + repeat;
    }

    public String run(String s) {
        return process(s, 1);
    }
}
''')
    f = "java_pkg/scopes/Scopes.java"
    edges.append(b.edge(f, "Scopes.process", "calls", "Scopes.normalize", f,
                        b.line_of(f, "return normalize(s);"), lang))
    edges.append(b.edge(f, "Scopes.run", "calls", "Scopes.process", f,
                        b.line_of(f, "return process(s, 1);"), lang, "static_positive",
                        "same_name_two_scopes", "Overload arity disambiguates the instance method"))
    edges.append(b.edge(f, "Scopes.process", "calls", "Scopes.process", f,
                        b.line_of(f, "return process(s) + repeat;"), lang, "static_positive",
                        "overload", "Instance overload calls the static one-arg overload"))

    # -- static import binding (alias) ------------------------------------------------------------
    b.add_file("java_pkg/alias/UseStatic.java", '''
package java_pkg.alias;

import static java_pkg.core.Validator.isValid;

public class UseStatic {
    public boolean check(String token) {
        return isValid(token);
    }
}
''')
    f = "java_pkg/alias/UseStatic.java"
    edges.append(b.edge(f, "UseStatic.check", "calls", "Validator.isValid",
                        "java_pkg/core/Validator.java",
                        b.line_of(f, "return isValid(token);"), lang,
                        "static_positive", "alias_import"))

    # -- overload collapse -----------------------------------------------------------------------
    b.add_file("java_pkg/overload/Overload.java", '''
package java_pkg.overload;

public class Overload {
    public boolean isValid(String token) { return token != null; }
    public boolean isValid(int code) { return code > 0; }

    public boolean checkBoth(String token, int code) {
        return isValid(token) && isValid(code);
    }
}
''')
    f = "java_pkg/overload/Overload.java"
    edges.append(b.edge(f, "Overload.checkBoth", "calls", "Overload.isValid", f,
                        b.line_of(f, "return isValid(token)"), lang, "static_positive", "overload"))
    edges.append(b.edge(f, "Overload.checkBoth", "calls", "Overload.isValid", f,
                        b.line_of(f, "&& isValid(code);"), lang, "static_positive", "overload",
                        "second call site collapses into the same edge row"))

    # -- dynamic: reflection, method ref, DI ------------------------------------------------------------
    b.add_file("java_pkg/dyn/Dyn.java", '''
package java_pkg.dyn;

import java_pkg.core.Validator;

public class Dyn {
    private final Validator validator = new Validator();

    public boolean viaInjection(String token) {
        return validator.isValid(token);
    }

    public Runnable makeTask() {
        return this::heartbeat;
    }

    public void heartbeat() { }

    public Object viaReflection(String cls) throws Exception {
        return Class.forName(cls).getMethod("heartbeat").invoke(this);
    }
}
''')
    f = "java_pkg/dyn/Dyn.java"
    edges.append(b.edge(f, "Dyn.viaInjection", "calls", "Validator.isValid",
                        "java_pkg/core/Validator.java", None, lang,
                        "dynamic_positive", "di", "Instance field of concrete type; claim optional"))
    edges.append(b.edge(f, "Dyn.makeTask", "calls", "Dyn.heartbeat", f, None, lang,
                        "dynamic_positive", "function_pointer", "Method reference — invocation deferred"))
    edges.append(b.edge(f, "Dyn.viaReflection", "calls", "Dyn.heartbeat", f, None, lang,
                        "dynamic_positive", "reflection"))

    # -- generated file -----------------------------------------------------------------------------------
    b.add_file("java_pkg/generated/GeneratedRepo.java", '''// Generated by corpus-tool. DO NOT EDIT.
package java_pkg.generated;

import java_pkg.core.Validator;

public class GeneratedRepo {
    public boolean check(String token) {
        return Validator.isValid(token);
    }
}
''')
    f = "java_pkg/generated/GeneratedRepo.java"
    edges.append(b.edge(f, "GeneratedRepo.check", "calls", "Validator.isValid",
                        "java_pkg/core/Validator.java", None, lang,
                        "dynamic_positive", "generated_file"))

    # -- caller outside module ------------------------------------------------------------------------------
    b.add_file("java_pkg/Main.java", '''
package java_pkg;

import java_pkg.core.Validator;

public class Main {
    public String run(String token) {
        if (Validator.isValid(token)) {
            return Validator.sanitize(token);
        }
        return "";
    }
}
''')
    f = "java_pkg/Main.java"
    edges.append(b.edge(f, "Main.run", "calls", "Validator.isValid", "java_pkg/core/Validator.java",
                        b.line_of(f, "if (Validator.isValid(token))"), lang,
                        "static_positive", "caller_outside_module"))
    edges.append(b.edge(f, "Main.run", "calls", "Validator.sanitize", "java_pkg/core/Validator.java",
                        b.line_of(f, "return Validator.sanitize(token);"), lang,
                        "static_positive", "caller_outside_module"))

    # -- scalable handlers -----------------------------------------------------------------------------------
    for i in range(1, 31):
        rel = f"java_pkg/handlers/Handler{i}.java"
        b.add_file(rel, f'''
package java_pkg.handlers;

import java_pkg.core.Validator;

public class Handler{i} {{
    private int id = {i};

    public boolean check(String token) {{
        return Validator.isValid(token);
    }}

    public String handle(String token) {{
        if (check(token)) {{
            return Validator.sanitize(token);
        }}
        return "";
    }}

    public String execute(String token) {{
        return handle(token);
    }}
}}
''')
        edges.append(b.edge(rel, f"Handler{i}.check", "calls", "Validator.isValid",
                            "java_pkg/core/Validator.java",
                            b.line_of(rel, "return Validator.isValid(token);"), lang))
        edges.append(b.edge(rel, f"Handler{i}.handle", "calls", f"Handler{i}.check", rel,
                            b.line_of(rel, "if (check(token)) {"), lang))
        edges.append(b.edge(rel, f"Handler{i}.handle", "calls", "Validator.sanitize",
                            "java_pkg/core/Validator.java",
                            b.line_of(rel, "return Validator.sanitize(token);"), lang))
        edges.append(b.edge(rel, f"Handler{i}.execute", "calls", f"Handler{i}.handle", rel,
                            b.line_of(rel, "return handle(token);"), lang))
        if i <= 10:
            edges.append(b.edge(rel, f"Handler{i}.check", "calls", "nonExistentMethod",
                                "java_pkg/core/Validator.java", None, lang,
                                "static_negative", "negative_target"))

    # -- implements/extends NEGATIVES (Java) ---------------------------------------------------------
    # Cases that must NOT resolve as implements/extends: interface-typed fields,
    # type-parameter bounds, "Impl"-suffixed lookalikes, commented declarations,
    # and forward references to undefined bases.
    b.add_file("java_pkg/negatives/JavaNegatives.java", '''
package java_pkg.negatives;

import java_pkg.core.Validator;
import java_pkg.shapes.Shape;
import java.util.concurrent.Callable;

public class CacheClient {
    private Callable<String> fetcher;

    public String run() throws Exception {
        return fetcher.call();
    }
}

public class Repo<T extends Comparable<T>> {
    private final T id;

    public Repo(T id) {
        this.id = id;
    }
}

public class NotifierImpl {
    public boolean send(String token) {
        return Validator.isValid(token);
    }
}

public class Orphan extends MissingBase {
    public String describe() {
        return "orphan:" + Shape.class.getName();
    }
}

// public class Ghost implements Shape { }
''')
    f = "java_pkg/negatives/JavaNegatives.java"
    neg_dst = "java_pkg/shapes/Shape.java"
    edges.append(b.edge(f, "CacheClient", "implements", "Callable", f, None, lang,
                        "static_negative", "implements_negative",
                        "external-dependency interface used as a field type only"))
    edges.append(b.edge(f, "Repo", "extends", "Comparable", f, None, lang,
                        "static_negative", "extends_negative",
                        "type-parameter bound <T extends Comparable<T>> is not class inheritance"))
    edges.append(b.edge(f, "Repo", "implements", "Comparable", f, None, lang,
                        "static_negative", "implements_negative",
                        "type-parameter bound must not imply implements either"))
    edges.append(b.edge(f, "NotifierImpl", "implements", "Shape", neg_dst, None, lang,
                        "static_negative", "implements_negative",
                        "'Impl' suffix lookalike; no implements declaration exists"))
    edges.append(b.edge(f, "Orphan", "extends", "MissingBase", f, None, lang,
                        "static_negative", "extends_negative",
                        "forward reference: base type is undefined in the corpus"))
    edges.append(b.edge(f, "Orphan", "implements", "Shape", neg_dst, None, lang,
                        "static_negative", "implements_negative",
                        "name-only mention of Shape must not become a claimed edge"))
    edges.append(b.edge(f, "CacheClient", "extends", "Validator",
                        "java_pkg/core/Validator.java", None, lang,
                        "static_negative", "extends_negative",
                        "import + method usage must not imply inheritance"))
    edges.append(b.edge(f, "Ghost", "implements", "Shape", neg_dst, None, lang,
                        "static_negative", "implements_negative",
                        "commented-out declaration must stay a comment"))

    probes = [
        SearchProbe("sanitize", [("java_pkg/core/Validator.java", "Validator.sanitize")], False, lang),
        SearchProbe("isValid", [("java_pkg/core/Validator.java", "Validator.isValid")], True, lang),
        SearchProbe("area", [("java_pkg/shapes/Circle.java", "Circle.area")], False, lang),
        SearchProbe("process", [("java_pkg/scopes/Scopes.java", "Scopes.process")], True, lang),
    ]
    return edges, probes


def build_corpus(root: Path) -> CorpusResult:
    b = CorpusBuilder(root)
    edges: List[EdgeTruth] = []
    probes: List[SearchProbe] = []
    for fn in (_python_corpus, _typescript_corpus, _go_corpus, _rust_corpus, _java_corpus):
        lang_edges, lang_probes = fn(b)
        edges.extend(lang_edges)
        probes.extend(lang_probes)
    return CorpusResult(builder=b, edges=edges, probes=probes)


# ---------------------------------------------------------------------------
# DB adapters
# ---------------------------------------------------------------------------

def load_db_state(db: Database, root: Path) -> Tuple[List[DbEdge], List[PendingEdge]]:
    root_abs = str(root)
    edges: List[DbEdge] = []

    def rel(p: str) -> str:
        try:
            out = os.path.relpath(p, root_abs)
        except ValueError:
            out = p
        return out.replace("\\", "/")

    rows = db.conn.execute(
        """
        SELECT e.path, e.relation, e.line, s.symbol, s.path, d.symbol, d.path
        FROM graph_edges e
        JOIN graph_nodes s ON e.src = s.id
        JOIN graph_nodes d ON e.dst = d.id
        """
    ).fetchall()
    for e_path, rel_, line, s_sym, _s_path, d_sym, d_path in rows:
        edges.append(DbEdge(
            path=rel(e_path),
            src=s_sym or "",
            relation=rel_,
            dst=d_sym or "",
            dst_path=rel(d_path),
            line=line,
        ))

    pending: List[PendingEdge] = []
    node_sym: Dict[str, str] = {
        r[0]: (r[1] or "") for r in db.conn.execute("SELECT id, symbol FROM graph_nodes").fetchall()
    }
    for p_path, p_src, p_dst, p_rel in db.conn.execute(
        "SELECT path, src, dst_symbol, relation FROM pending_edges"
    ).fetchall():
        pending.append(PendingEdge(
            path=rel(p_path),
            src=node_sym.get(p_src, p_src or ""),
            relation=p_rel,
            dst_symbol=p_dst or "",
        ))
    return edges, pending


def gold_fqn(path: str, symbol: str) -> str:
    module = dotted_module(path)
    return f"{module}.{symbol}" if module else symbol


def run_search_probes(db: Database, probes: List[SearchProbe]) -> Dict[str, object]:
    per_k = {1: 0, 5: 0, 10: 0}
    unique_hits = {1: 0, 5: 0, 10: 0}
    unique_total = 0
    ambiguous_hits = {1: 0, 5: 0, 10: 0}
    ambiguous_total = 0
    details: List[Dict[str, object]] = []

    for probe in probes:
        gold_fqns = {gold_fqn(p, s) for p, s in probe.gold}
        results = db.search_fts(probe.query, limit=10)
        hit_at: Dict[int, bool] = {}
        for k in (1, 5, 10):
            top = results[:k]
            hit_at[k] = any(
                (r.get("fqn") in gold_fqns) or (r.get("symbol") in {s for _, s in probe.gold}
                                                 and r.get("path", "").replace("\\", "/") in {p for p, _ in probe.gold})
                for r in top
            )
        bucket = unique_hits if not probe.ambiguous else ambiguous_hits
        for k in (1, 5, 10):
            per_k[k] += 1 if hit_at[k] else 0
            bucket[k] += 1 if hit_at[k] else 0
        if probe.ambiguous:
            ambiguous_total += 1
        else:
            unique_total += 1
        details.append({
            "query": probe.query,
            "language": probe.language,
            "ambiguous": probe.ambiguous,
            "gold": sorted(gold_fqns),
            "hit_at_1": hit_at[1], "hit_at_5": hit_at[5], "hit_at_10": hit_at[10],
            "top3": [
                {"fqn": r.get("fqn"), "path": r.get("path"), "symbol": r.get("symbol")}
                for r in results[:3]
            ],
        })

    def _rate(num: int, den: int) -> float:
        return round(num / den, 4) if den else 0.0

    return {
        "queries": len(probes),
        "unique_queries": unique_total,
        "ambiguous_queries": ambiguous_total,
        "hit_at_1": _rate(per_k[1], len(probes)),
        "hit_at_5": _rate(per_k[5], len(probes)),
        "hit_at_10": _rate(per_k[10], len(probes)),
        "unique_hit_at_1": _rate(unique_hits[1], unique_total),
        "unique_hit_at_5": _rate(unique_hits[5], unique_total),
        "unique_hit_at_10": _rate(unique_hits[10], unique_total),
        "ambiguous_hit_at_1": _rate(ambiguous_hits[1], ambiguous_total),
        "ambiguous_hit_at_5": _rate(ambiguous_hits[5], ambiguous_total),
        "ambiguous_hit_at_10": _rate(ambiguous_hits[10], ambiguous_total),
        "details": details,
    }


# ---------------------------------------------------------------------------
# Self-check: the oracle must discriminate wrong-target / bare-name / span
# ---------------------------------------------------------------------------

def run_selfcheck() -> List[str]:
    """Synthetic discrimination checks. Returns list of failures (empty = pass)."""
    failures: List[str] = []
    path = "pkg/a.py"
    tgt = "pkg/b.py"

    # 1. Wrong target with the same bare name must NOT be a true positive.
    truths = [EdgeTruth(CORPUS_REPO_ID, path, "caller", "calls", "Worker.Check", tgt, 10,
                        "go", "static_positive", "same_name_two_scopes")]
    db = [DbEdge(path, "caller", "calls", "process", "pkg/c.py", 10)]
    report = evaluate_edges(truths, db, [])
    if report.counts["true_positives"] != 0:
        failures.append("wrong-target edge counted as TP")
    reasons = {c for c in report.confusion}
    if not any("wrong_target_same_bare_name" in c or "edge_absent" in c for c in reasons):
        failures.append(f"wrong-target confusion missing: {reasons}")

    # 2. A bare name appearing on a DIFFERENT edge must not inflate recall.
    truths = [EdgeTruth(CORPUS_REPO_ID, path, "run_stage", "calls", "Stage.process", path, 12,
                        "rust", "static_positive", "same_name_two_scopes")]
    db = [DbEdge(path, "run_stage", "calls", "process", path, 12)]
    report = evaluate_edges(truths, db, [])
    if report.counts["true_positives"] != 0:
        failures.append("bare-name-only edge counted as TP under exact matching")
    if report.diagnostics["legacy_loose_recall_diagnostic"] <= 0.0:
        failures.append("legacy loose diagnostic failed to match bare-name edge (must differ)")

    # 3. Exact positive must be a TP.
    truths = [EdgeTruth(CORPUS_REPO_ID, path, "caller", "calls", "Worker.Check", tgt, 10,
                        "go", "static_positive", "call")]
    db = [DbEdge(path, "caller", "calls", "Worker.Check", tgt, 10)]
    report = evaluate_edges(truths, db, [])
    if report.counts["true_positives"] != 1:
        failures.append("exact edge not counted as TP")

    # 4. Span mismatch must be flagged, not silently accepted.
    db = [DbEdge(path, "caller", "calls", "Worker.Check", tgt, 42)]
    report = evaluate_edges(truths, db, [])
    if report.counts["true_positives"] != 0 or not any("span_mismatch" in c for c in report.confusion):
        failures.append("span mismatch not flagged")

    # 5. Call-site collapse: DB stores one of the true lines -> one TP per item.
    truths = [
        EdgeTruth(CORPUS_REPO_ID, path, "callBoth", "calls", "fmt", path, 7, "typescript",
                  "static_positive", "overload"),
        EdgeTruth(CORPUS_REPO_ID, path, "callBoth", "calls", "fmt", path, 7, "typescript",
                  "static_positive", "overload"),
    ]
    db = [DbEdge(path, "callBoth", "calls", "fmt", path, 7)]
    report = evaluate_edges(truths, db, [])
    if report.counts["true_positives"] != 2:
        failures.append("call-site collapse handling broken")

    # 6. A negative edge present in the DB must be a false positive.
    truths = [EdgeTruth(CORPUS_REPO_ID, path, "shadower", "calls", "add", tgt, None,
                        "python", "static_negative", "shadowed_param")]
    db = [DbEdge(path, "shadower", "calls", "add", tgt, 3)]
    report = evaluate_edges(truths, db, [])
    if report.counts["false_positives"] != 1:
        failures.append("negative edge not detected as FP")

    # 7. identity_unqualified vs wrong_target disambiguation.
    truths = [EdgeTruth(CORPUS_REPO_ID, path, "run_stage", "calls", "Stage.process", tgt, 9,
                        "rust", "static_positive", "same_name_two_scopes")]
    db = [DbEdge(path, "run_stage", "calls", "process", tgt, 9)]
    report = evaluate_edges(truths, db, [])
    if not any("identity_unqualified" in c for c in report.confusion):
        failures.append("under-qualified identity in the right file not reported as identity_unqualified")

    return failures


# ---------------------------------------------------------------------------
# Suite entry
# ---------------------------------------------------------------------------

def _cbm_invoke(binary: str, tool: str, args: Dict[str, object], cwd: str) -> Dict[str, object]:
    """One one-shot CBM CLI call via --args-file (no shell, no quoting)."""
    from sot_graph.proc import run_command

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", prefix="cbm-probe-",
                                     delete=False, encoding="utf-8") as handle:
        json.dump(args, handle, ensure_ascii=False)
        args_file = handle.name
    try:
        result = run_command(
            [binary, "cli", "--json", tool, "--args-file", args_file],
            cwd=cwd, timeout_seconds=120.0,
        )
    finally:
        os.unlink(args_file)
    if result.returncode != 0 or result.timed_out:
        return {"error": f"exit={result.returncode} timed_out={result.timed_out}",
                "stderr": result.stderr[-400:]}
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "unparseable stdout", "stdout_head": result.stdout[:200]}
    if isinstance(parsed.get("structuredContent"), dict):
        merged = dict(parsed["structuredContent"])
        content = parsed.get("content")
        if isinstance(content, list) and content:
            merged.setdefault("raw_text", content[0].get("text"))
        return merged
    return parsed


def run_cbm_probe(binary: str, output_path: Optional[str] = None,
                  corpus_dir: Optional[str] = None) -> Dict[str, object]:
    """P0.g — optional provider-side probe against the same corpus truth.

    EXPLORATORY SAMPLE, not the exact 6-tuple baseline contract: CBM
    trace_path reports hop-level callee names without call-site spans, so a
    hit here means "claimed the edge at qualified-name level" or "claimed a
    same-name callee without file-level proof". Reported separately; never
    merged into the builtin baseline.
    """
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(corpus_dir) if corpus_dir else Path(tmpdir) / CORPUS_REPO_ID
        root.mkdir(parents=True, exist_ok=True)
        corpus = build_corpus(root)

        subprocess.run(["git", "init", "-q", "."], cwd=str(root), check=True,
                       capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=str(root), check=True,
                       capture_output=True)
        subprocess.run(
            ["git", "-c", "user.email=oracle@probe", "-c", "user.name=oracle",
             "commit", "-q", "-m", "cbm probe corpus"],
            cwd=str(root), check=True, capture_output=True,
        )

        version_out = subprocess.run([binary, "--version"], capture_output=True,
                                     text=True, timeout=30)
        cbm_version = version_out.stdout.strip()

        index = _cbm_invoke(binary, "index_repository", {"repo_path": str(root)}, str(root))
        project = index.get("project")
        if not project:
            raise RuntimeError(f"index_repository failed: {json.dumps(index)[:400]}")

        # Sample: every mandatory-case edge, plus the first two scalable
        # service edges per language, plus every non-calls relation edge.
        sample: List[EdgeTruth] = []
        scalable_seen: Dict[str, int] = {}
        for t in corpus.edges:
            if t.polarity != "static_positive" or t.relation != "calls":
                if t.polarity == "static_positive":
                    sample.append(t)
                continue
            if t.category != "call":
                sample.append(t)
            else:
                n = scalable_seen.get(t.language, 0)
                if n < 2:
                    scalable_seen[t.language] = n + 1
                    sample.append(t)

        per_lang: Dict[str, Dict[str, int]] = {}
        details: List[Dict[str, object]] = []
        for t in sample:
            slot = per_lang.setdefault(
                t.language, {"sampled": 0, "qualified_claim": 0,
                             "name_only_claim": 0, "unclaimed": 0})
            slot["sampled"] += 1
            bare_src = t.src.split(".")[-1]
            trace_args: Dict[str, object] = {
                "function_name": bare_src, "project": project, "format": "json",
            }
            out = _cbm_invoke(binary, "trace_path", trace_args, str(root))
            if out.get("status") == "ambiguous":
                pick = None
                for sug in out.get("suggestions", []):
                    fp = str(sug.get("file_path", "")).replace("\\", "/")
                    qn = str(sug.get("qualified_name", ""))
                    if fp.endswith(t.path) and (qn.endswith(t.src) or qn.endswith(bare_src)):
                        pick = qn
                        break
                if pick is None:
                    slot["unclaimed"] += 1
                    details.append({"anchor": t.anchor(), "reason": "src_ambiguous_unresolved"})
                    continue
                trace_args["function_name"] = pick
                out = _cbm_invoke(binary, "trace_path", trace_args, str(root))

            callees = out.get("callees") if isinstance(out.get("callees"), dict) else None
            rows: List[Tuple[str, str]] = []
            if callees:
                for group in callees.get("groups", []):
                    prefix = str(group.get("qn_prefix", ""))
                    for row in group.get("rows", []):
                        if len(row) >= 2 and row[1] == 1:  # hop 1 only
                            rows.append((prefix, str(row[0])))
            gt_module_tail = dotted_module(t.dst_path)
            gt_qualified = f"{gt_module_tail}.{t.dst}" if gt_module_tail else t.dst
            n_seg = len(gt_qualified.split("."))
            qualified = any(
                ".".join(f"{prefix}.{name}".split(".")[-n_seg:]) == gt_qualified
                for prefix, name in rows
            )
            name_only = any(name == t.dst.split(".")[-1] for _p, name in rows)
            if qualified:
                slot["qualified_claim"] += 1
                details.append({"anchor": t.anchor(), "reason": "qualified_claim"})
            elif name_only:
                slot["name_only_claim"] += 1
                details.append({"anchor": t.anchor(), "reason": "name_only_claim"})
            else:
                slot["unclaimed"] += 1
                details.append({"anchor": t.anchor(), "reason": "unclaimed"})

        payload: Dict[str, object] = {
            "oracle_version": ORACLE_VERSION,
            "kind": "cbm-exploratory-probe",
            "binary": binary,
            "cbm_version": cbm_version,
            "corpus": {"repo": CORPUS_REPO_ID, "digest": corpus.builder.digest(),
                       "files": len(corpus.builder.files)},
            "sample_rule": ("all mandatory-case static positives + non-calls relations "
                            "+ first 2 scalable 'call' edges per language; hop-1 callees only; "
                            "qualified-name level, span not checkable via trace_path"),
            "per_language": per_lang,
            "details": details,
        }
        total = {k: sum(v[k] for v in per_lang.values())
                 for k in ("sampled", "qualified_claim", "name_only_claim", "unclaimed")}
        payload["totals"] = total
        print(f"CBM probe ({cbm_version}): sampled {total['sampled']} — "
              f"qualified {total['qualified_claim']}  name-only {total['name_only_claim']}  "
              f"unclaimed {total['unclaimed']}")
        for lang in sorted(per_lang):
            s = per_lang[lang]
            print(f"  [{lang:10s}] qualified {s['qualified_claim']:3d}/{s['sampled']:<3d}  "
                  f"name-only {s['name_only_claim']:3d}  unclaimed {s['unclaimed']:3d}")
        if output_path:
            out_file = Path(output_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                encoding="utf-8")
            print(f"Probe JSON written to: {out_file}")
        return payload


def run_benchmark_suite(output_path: Optional[str] = None, corpus_dir: Optional[str] = None) -> Dict[str, object]:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(corpus_dir) if corpus_dir else Path(tmpdir) / CORPUS_REPO_ID
        if corpus_dir is None:
            root.mkdir(parents=True, exist_ok=True)
        else:
            root.mkdir(parents=True, exist_ok=True)

        corpus = build_corpus(root)
        n_pos = sum(1 for e in corpus.edges if e.polarity == "static_positive")
        n_neg = sum(1 for e in corpus.edges if e.polarity == "static_negative")
        n_dyn = sum(1 for e in corpus.edges if e.polarity == "dynamic_positive")
        print(f"Corpus: {len(corpus.builder.files)} files, {len(corpus.edges)} edges "
              f"(static+ {n_pos}, static- {n_neg}, dynamic {n_dyn}), "
              f"{len(corpus.probes)} search probes")

        db_path = str(root / ".sot" / "sot.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        db = Database(db_path)
        reconciler = Reconciler(db, str(root))
        reconciler.reconcile()

        db_edges, pending = load_db_state(db, root)
        report = evaluate_edges(corpus.edges, db_edges, pending)
        search = run_search_probes(db, corpus.probes)

        payload: Dict[str, object] = {
            "oracle_version": ORACLE_VERSION,
            "corpus": {
                "repo": CORPUS_REPO_ID,
                "digest": corpus.builder.digest(),
                "files": len(corpus.builder.files),
                "edges": len(corpus.edges),
                "languages": sorted({e.language for e in corpus.edges}),
                "counts": {"static_positive": n_pos, "static_negative": n_neg,
                           "dynamic_positive": n_dyn},
                "relations_measured": list(RELATIONS_MEASURED),
            },
            "builtin": report.as_dict(),
            "search_topk": search,
        }

        print()
        print("=" * 72)
        print("SOT-GRAPH EXACT ORACLE (6-tuple) — BUILTIN BASELINE")
        print("=" * 72)
        c = report.counts
        print(f"static+: {c['static_positive']}  static-: {c['static_negative']}  dynamic: {c['dynamic_positive']}")
        print(f"TP {c['true_positives']}  FN {c['false_negatives']}  FP {c['false_positives']}  TN {c['true_negatives']}")
        print(f"precision {c['precision']*100:.1f}%  recall {c['recall']*100:.1f}%  f1 {c['f1']*100:.1f}%")
        print(f"diag identity-only recall {report.diagnostics['identity_only_recall']*100:.1f}%  "
              f"legacy-loose recall {report.diagnostics['legacy_loose_recall_diagnostic']*100:.1f}%")
        print("-" * 72)
        for lang in sorted(report.per_language):
            s = report.per_language[lang]["overall"]
            print(f"  [{lang:10s}] P {s['precision']*100:6.1f}%  R {s['recall']*100:6.1f}%  "
                  f"F1 {s['f1']*100:6.1f}%  (FP {s['fp']}, FN {s['fn']})")
        print("-" * 72)
        print(f"dynamic: {report.dynamic}")
        h1, h5, h10 = (float(search[k]) for k in ("hit_at_1", "hit_at_5", "hit_at_10"))
        print(f"search top-k: hit@1 {h1*100:.0f}%  hit@5 {h5*100:.0f}%  hit@10 {h10*100:.0f}%")
        if report.confusion:
            print(f"\n[!] {len(report.confusion)} confusion entries "
                  f"(showing first 25):")
            for line in report.confusion[:25]:
                print(f"   - {line}")

        if output_path:
            out_file = Path(output_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            with open(out_file, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
            print(f"\nBaseline JSON written to: {out_file}")

        db.close()
        return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="SOT-Graph Exact Oracle (6-tuple)")
    parser.add_argument("--output", "-o", help="Path to save machine-readable baseline JSON")
    parser.add_argument("--corpus-dir", help="Reuse/build corpus at this path instead of a tempdir")
    parser.add_argument("--cbm-probe", metavar="BIN",
                        help="Optional P0.g: probe the real codebase-memory binary "
                             "against the same corpus (exploratory sample)")
    parser.add_argument("--selfcheck", action="store_true",
                        help="Run oracle discrimination self-checks and exit")
    args = parser.parse_args()

    if args.selfcheck:
        failures = run_selfcheck()
        if failures:
            print("SELF-CHECK FAILED:")
            for f_ in failures:
                print(f"  - {f_}")
            sys.exit(1)
        print("self-check: OK (7/7)")
        sys.exit(0)

    if args.cbm_probe:
        run_cbm_probe(args.cbm_probe, args.output, args.corpus_dir)
        sys.exit(0)
    run_benchmark_suite(args.output, args.corpus_dir)
    sys.exit(0)


if __name__ == "__main__":
    main()
