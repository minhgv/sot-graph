from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler
from sot_graph.verifier import RelevanceType, TrustVerifier


@dataclass
class StrictEvaluationResult:
    corpus_hash: str
    manifest_hash: str
    commit_sha: str
    total_expected_edges: int
    total_predicted_edges: int
    true_positives: int
    false_positives: int
    false_negatives: int
    strict_edge_precision: float
    strict_edge_recall: float
    strict_edge_f1: float
    forbidden_edge_rejection_rate: float
    false_exact_span_count: int
    false_exact_span_rate: float
    passed: bool
    failures: List[str] = field(default_factory=list)


def compute_dir_hash(directory: Path) -> str:
    hasher = hashlib.sha256()
    for root, _, files in sorted(os.walk(directory)):
        for f in sorted(files):
            p = Path(root) / f
            hasher.update(p.relative_to(directory).as_posix().encode("utf-8"))
            try:
                hasher.update(p.read_bytes())
            except Exception:
                pass
    return hasher.hexdigest()


class Evaluator:
    def __init__(self, fixtures_dir: Path, manifest_path: Path):
        self.fixtures_dir = fixtures_dir
        self.manifest_path = manifest_path
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.corpus_hash = compute_dir_hash(fixtures_dir)
        self.manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    def evaluate(self, commit_sha: str = "HEAD") -> StrictEvaluationResult:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "sot.db"
            db = Database(str(db_path))
            rec = Reconciler(db, str(self.fixtures_dir))
            rec.reconcile(workers=1)

            # Query all confirmed graph_edges (filtering out AST structural defines edges)
            rows = db.conn.execute("""
                SELECT s.path, s.symbol, e.relation, t.path, t.symbol
                FROM graph_edges e
                JOIN graph_nodes s ON e.src = s.id
                JOIN graph_nodes t ON e.dst = t.id
                WHERE e.relation = 'calls'
            """).fetchall()
            predicted_edges: Set[str] = set()
            for r in rows:
                src_path = Path(r[0]).as_posix()
                try:
                    src_rel = Path(src_path).relative_to(self.fixtures_dir.parent.parent).as_posix()
                except Exception:
                    src_rel = src_path
                src_sym = r[1] or ""
                if "." in src_sym and not src_sym.startswith("def "):
                    src_sym = src_sym.split(".")[-1]
                rel = r[2] or "calls"
                dst_path = Path(r[3]).as_posix()
                try:
                    dst_rel = Path(dst_path).relative_to(self.fixtures_dir.parent.parent).as_posix()
                except Exception:
                    dst_rel = dst_path
                dst_sym = r[4] or ""
                if "." in dst_sym and not dst_sym.startswith("def "):
                    dst_sym = dst_sym.split(".")[-1]
                predicted_edges.add(f"{src_rel}::{src_sym}::{rel}::{dst_rel}::{dst_sym}")

            expected_edges: Set[str] = set()
            for e in self.manifest.get("expected_confirmed_edges", []):
                expected_edges.add(f"{e['source_file']}::{e['source_symbol']}::{e['relation']}::{e['target_file']}::{e['target_symbol']}")

            forbidden_edges: Set[str] = set()
            for f_edge in self.manifest.get("forbidden_edges", []):
                forbidden_edges.add(f"{f_edge['source_file']}::{f_edge['source_symbol']}::{f_edge['relation']}::{f_edge['target_file']}::{f_edge['target_symbol']}")

            tp_set = predicted_edges & expected_edges
            fp_set = predicted_edges - expected_edges
            fn_set = expected_edges - predicted_edges

            tp = len(tp_set)
            fp = len(fp_set)
            fn = len(fn_set)

            precision = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
            recall = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0
            f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

            # Forbidden edges evaluation
            forbidden_hit = predicted_edges & forbidden_edges
            forbidden_rate = (1.0 - (len(forbidden_hit) / len(forbidden_edges))) if forbidden_edges else 1.0

            # Exact span checks
            false_exact_spans = 0
            for check in self.manifest.get("exact_span_expectations", []):
                fpath = Path(check["file_path"])
                full_fpath = self.fixtures_dir.parent.parent / fpath
                cand = {
                    "path": str(full_fpath),
                    "symbol": check["symbol"],
                    "line_start": check["query_line"],
                    "line": check["query_line"],
                }
                ev = TrustVerifier.verify_evidence(cand, {check["symbol"]}, str(self.fixtures_dir.parent.parent))
                if ev.relevance == RelevanceType.EXACT_SPAN and not check["expected_exact_span"]:
                    false_exact_spans += 1

            false_exact_span_rate = (false_exact_spans / len(self.manifest.get("exact_span_expectations", []))) if self.manifest.get("exact_span_expectations") else 0.0

            failures: List[str] = []
            if fp > 0:
                failures.append(f"False Positives detected ({fp}): {sorted(list(fp_set))}")
            if fn > 0:
                failures.append(f"False Negatives detected ({fn}): {sorted(list(fn_set))}")
            if forbidden_hit:
                failures.append(f"Forbidden edges confirmed ({len(forbidden_hit)}): {sorted(list(forbidden_hit))}")
            if false_exact_spans > 0:
                failures.append(f"False EXACT_SPAN granted on {false_exact_spans} non-declaration sites")

            passed = (fp == 0) and (fn == 0) and (len(forbidden_hit) == 0) and (false_exact_spans == 0)

            return StrictEvaluationResult(
                corpus_hash=self.corpus_hash,
                manifest_hash=self.manifest_hash,
                commit_sha=commit_sha,
                total_expected_edges=len(expected_edges),
                total_predicted_edges=len(predicted_edges),
                true_positives=tp,
                false_positives=fp,
                false_negatives=fn,
                strict_edge_precision=precision,
                strict_edge_recall=recall,
                strict_edge_f1=f1,
                forbidden_edge_rejection_rate=forbidden_rate,
                false_exact_span_count=false_exact_spans,
                false_exact_span_rate=false_exact_span_rate,
                passed=passed,
                failures=failures,
            )


def main():
    parser = argparse.ArgumentParser(description="Strict Ground-Truth Evaluator for SOT-Graph")
    parser.add_argument("--output", "-o", help="Output JSON path")
    parser.add_argument("--mode", choices=["strict", "relaxed"], default="strict")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parent.parent
    evaluation_dir = Path(__file__).resolve().parent
    fixtures_dir = evaluation_dir / "fixtures"
    manifest_path = evaluation_dir / "manifests" / "closed_world_manifest.json"
    evaluator = Evaluator(fixtures_dir, manifest_path)
    result = evaluator.evaluate()

    print("=" * 65)
    print("STRICT SOT-GRAPH EVALUATION RESULT")
    print("=" * 65)
    print(f"Corpus Hash    : {result.corpus_hash[:16]}...")
    print(f"Manifest Hash  : {result.manifest_hash[:16]}...")
    print(f"Commit SHA     : {result.commit_sha}")
    print(f"Strict Prec    : {result.strict_edge_precision * 100:.2f}%")
    print(f"Strict Rec     : {result.strict_edge_recall * 100:.2f}%")
    print(f"Strict F1      : {result.strict_edge_f1 * 100:.2f}%")
    print(f"Forbidden Rej  : {result.forbidden_edge_rejection_rate * 100:.2f}%")
    print(f"False Spans    : {result.false_exact_span_count}")
    print(f"Status         : {'PASS' if result.passed else 'FAIL'}")
    print("=" * 65)

    if result.failures:
        print("FAILURES / DISCREPANCIES:")
        for f in result.failures:
            print(f" - {f}")

    if args.output:
        Path(args.output).write_text(json.dumps(asdict(result), indent=2))
        print(f"\nWritten to: {args.output}")

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
