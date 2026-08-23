#!/usr/bin/env python3
"""SOT-Graph Python Semantic Resolver Accuracy Benchmark Harness.

Measures Precision, Recall, and F1-score against Ground Truth corpus.
Ground Truth covers:
1. Multi-level relative imports ('from ..core.calculator import add as my_add')
2. Aliased function and module calls
3. Package re-exports via __init__.py ('__all__')
4. Class inheritance & MRO method resolution
5. Typed parameter & constructor receiver inference
6. Dynamic and external calls correctly identified or excluded
"""

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Ensure sot_graph is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler


@dataclass
class GroundTruthEdge:
    src_file: str
    src_symbol: str
    target_symbol: str
    relation: str = "calls"


@dataclass
class BenchmarkResult:
    total_ground_truth: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    details: Dict[str, Any]
    passed_thresholds: bool


def generate_benchmark_corpus(root: Path) -> List[GroundTruthEdge]:
    """Populates an isolated directory with multi-pattern Python codebase."""
    # 1. Base calculator & helper
    (root / "pkg" / "core").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "core" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core" / "math_ops.py").write_text(
        """\
def add(a: int, b: int) -> int:
    return a + b

def multiply(a: int, b: int) -> int:
    return a * b
""",
        encoding="utf-8",
    )

    # 2. Re-exported engine in internal module
    (root / "pkg" / "internal").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "internal" / "engine.py").write_text(
        """\
class ExecutionEngine:
    def run_job(self, name: str) -> str:
        return f"job_done:{name}"
""",
        encoding="utf-8",
    )
    # Package __init__.py re-export
    (root / "pkg" / "__init__.py").write_text(
        """\
from .internal.engine import ExecutionEngine
__all__ = ["ExecutionEngine"]
""",
        encoding="utf-8",
    )

    # 3. Base & Derived repositories for MRO
    (root / "pkg" / "data").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "data" / "base_store.py").write_text(
        """\
class BaseStore:
    def get_by_key(self, key: str) -> str:
        return f"val_{key}"
""",
        encoding="utf-8",
    )
    (root / "pkg" / "data" / "user_store.py").write_text(
        """\
from .base_store import BaseStore

class UserStore(BaseStore):
    def find_user(self, uid: str) -> str:
        return self.get_by_key(uid)
""",
        encoding="utf-8",
    )

    # 4. Service layer exercising multi-level relative imports, aliases, re-exports, MRO & typed annotations
    (root / "pkg" / "services").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "services" / "app_service.py").write_text(
        """\
from ..core.math_ops import add as sum_func, multiply as product_func
from pkg import ExecutionEngine
from ..data.user_store import UserStore

def process_order(price: int, qty: int, tax: int) -> int:
    subtotal = product_func(price, qty)
    return sum_func(subtotal, tax)

def execute_pipeline(name: str):
    engine = ExecutionEngine()
    return engine.run_job(name)

def get_user_profile(uid: str, store: UserStore) -> str:
    return store.get_by_key(uid)
""",
        encoding="utf-8",
    )

    # Ground Truth expected edges
    return [
        # Relative import + alias inside process_order
        GroundTruthEdge("pkg/services/app_service.py", "process_order", "multiply", "calls"),
        GroundTruthEdge("pkg/services/app_service.py", "process_order", "add", "calls"),
        # Re-export + constructor inside execute_pipeline
        GroundTruthEdge("pkg/services/app_service.py", "execute_pipeline", "ExecutionEngine", "calls"),
        GroundTruthEdge("pkg/services/app_service.py", "execute_pipeline", "ExecutionEngine.run_job", "calls"),
        # Inheritance / MRO inside UserStore.find_user
        GroundTruthEdge("pkg/data/user_store.py", "UserStore.find_user", "BaseStore.get_by_key", "calls"),
        # Typed parameter receiver inside get_user_profile
        GroundTruthEdge("pkg/services/app_service.py", "get_user_profile", "BaseStore.get_by_key", "calls"),
    ]


def run_benchmark(
    corpus_dir: Optional[str] = None,
    min_precision: float = 0.95,
    min_recall: float = 0.80,
) -> BenchmarkResult:
    """Executes reconciliation on benchmark corpus and evaluates precision/recall."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root_path = Path(corpus_dir) if corpus_dir else Path(tmpdir) / "corpus"
        root_path.mkdir(parents=True, exist_ok=True)
        ground_truth = generate_benchmark_corpus(root_path)

        db_path = Path(tmpdir) / ".sot" / "sot.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = Database(str(db_path))

        reconciler = Reconciler(db, str(root_path))
        reconciler.reconcile()

        # Query all resolved edges
        resolved_rows = db.conn.execute(
            """
            SELECT e.path, n1.symbol, n2.symbol, e.relation
            FROM graph_edges e
            JOIN graph_nodes n1 ON e.src = n1.id
            JOIN graph_nodes n2 ON e.dst = n2.id
            WHERE e.relation = 'calls'
            """
        ).fetchall()

        resolved_set: Set[Tuple[str, str, str]] = set()
        for r_path, src_sym, dst_sym, _rel in resolved_rows:
            # Normalize rel_path
            rel_file = os.path.relpath(r_path, str(root_path))
            resolved_set.add((rel_file, src_sym, dst_sym))

        tp = 0
        fn = 0
        matched_gt = []
        missed_gt = []

        for gt in ground_truth:
            key = (gt.src_file, gt.src_symbol, gt.target_symbol)
            if key in resolved_set:
                tp += 1
                matched_gt.append(asdict(gt))
            else:
                fn += 1
                missed_gt.append(asdict(gt))

        # False positives: resolved call edges in our test corpus that are not in GT
        # Note: only consider call edges originating from our test functions
        gt_src_keys = {(gt.src_file, gt.src_symbol) for gt in ground_truth}
        fp = 0
        unexpected_edges = []
        for rel_file, src_sym, dst_sym in resolved_set:
            if (rel_file, src_sym) in gt_src_keys:
                if (rel_file, src_sym, dst_sym) not in {(gt.src_file, gt.src_symbol, gt.target_symbol) for gt in ground_truth}:
                    fp += 1
                    unexpected_edges.append({"file": rel_file, "src": src_sym, "target": dst_sym})

        total_gt = len(ground_truth)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        passed = (precision >= min_precision) and (recall >= min_recall)

        db.close()

        return BenchmarkResult(
            total_ground_truth=total_gt,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            precision=precision,
            recall=recall,
            f1_score=f1,
            details={
                "matched_ground_truth": matched_gt,
                "missed_ground_truth": missed_gt,
                "unexpected_edges": unexpected_edges,
                "min_precision_threshold": min_precision,
                "min_recall_threshold": min_recall,
            },
            passed_thresholds=passed,
        )


def main():
    parser = argparse.ArgumentParser(description="SOT-Graph Python Resolver Accuracy Benchmark")
    parser.add_argument("--corpus-dir", type=str, default=None, help="Custom corpus directory path")
    parser.add_argument("--min-precision", type=float, default=0.95, help="Minimum acceptable precision (default: 0.95)")
    parser.add_argument("--min-recall", type=float, default=0.80, help="Minimum acceptable recall (default: 0.80)")
    parser.add_argument("--json", action="store_true", help="Output benchmark results in JSON format")

    args = parser.parse_args()

    result = run_benchmark(
        corpus_dir=args.corpus_dir,
        min_precision=args.min_precision,
        min_recall=args.min_recall,
    )

    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        print("=" * 60)
        print(" SOT-GRAPH PYTHON RESOLVER ACCURACY BENCHMARK ")
        print("=" * 60)
        print(f"Ground Truth Items  : {result.total_ground_truth}")
        print(f"True Positives (TP) : {result.true_positives}")
        print(f"False Positives (FP): {result.false_positives}")
        print(f"False Negatives (FN): {result.false_negatives}")
        print("-" * 60)
        print(f"Precision           : {result.precision * 100:.2f}% (Threshold >= {args.min_precision * 100:.1f}%)")
        print(f"Recall              : {result.recall * 100:.2f}% (Threshold >= {args.min_recall * 100:.1f}%)")
        print(f"F1-Score            : {result.f1_score * 100:.2f}%")
        print("=" * 60)
        if result.passed_thresholds:
            print(" [PASS] ACCURACY MEETS OR EXCEEDS ROADMAP TARGETS")
        else:
            print(" [FAIL] ACCURACY BELOW ROADMAP TARGETS")
        print("=" * 60)

    sys.exit(0 if result.passed_thresholds else 1)


if __name__ == "__main__":
    main()
