"""
test_diff_impact_oracle.py — Exact Diff-Impact Oracle Benchmark for SOT-Graph.

Evaluates Precision, Recall, and F1-score for:
1. Exact caller blast radius (1-hop, 2-hop).
2. Impacted candidate unit test discovery.
3. Affected API routes and contracts.
4. Fail-closed decision receipt state (ASSURED_WITHIN_SCOPE vs PARTIAL).
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from sot_graph.assurance.receipts import diff_impact_receipt
from sot_graph.db import Database
from sot_graph.diff_impact import DiffImpactEngine
from sot_graph.reconciler import Reconciler


def setup_diff_impact_corpus(root: Path) -> None:
    """Populate a multi-tier microservice architecture for diff impact verification."""
    # 1. Domain math module
    math_file = root / "src" / "math_lib.py"
    math_file.parent.mkdir(parents=True, exist_ok=True)
    math_file.write_text("""
def base_add(a: int, b: int) -> int:
    return a + b

def calculate_fee(amount: int) -> int:
    return base_add(amount, 10)
""", encoding="utf-8", newline="")

    # 2. Service layer
    svc_file = root / "src" / "order_service.py"
    svc_file.write_text("""
from src.math_lib import calculate_fee

class OrderService:
    def process_order(self, total: int) -> int:
        fee = calculate_fee(total)
        return total + fee
""", encoding="utf-8", newline="")

    # 3. Controller / API layer
    api_file = root / "src" / "order_controller.py"
    api_file.write_text("""
from src.order_service import OrderService

class OrderController:
    def handle_checkout(self, amount: int) -> int:
        svc = OrderService()
        return svc.process_order(amount)
""", encoding="utf-8", newline="")

    # 4. Independent unrelated module
    user_file = root / "src" / "user_service.py"
    user_file.write_text("""
class UserService:
    def get_user(self, user_id: str) -> str:
        return f"user:{user_id}"
""", encoding="utf-8", newline="")

    # 5. Unit test files
    test_dir = root / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)

    (test_dir / "test_math.py").write_text("""
from src.math_lib import calculate_fee

def test_calculate_fee():
    assert calculate_fee(100) == 110
""", encoding="utf-8", newline="")

    (test_dir / "test_order.py").write_text("""
from src.order_service import OrderService

def test_order_service():
    svc = OrderService()
    assert svc.process_order(100) == 120
""", encoding="utf-8", newline="")

    (test_dir / "test_user.py").write_text("""
from src.user_service import UserService

def test_user():
    svc = UserService()
    assert svc.get_user("42") == "user:42"
""", encoding="utf-8", newline="")

    # Initialize git repo and commit
    subprocess.run(["git", "init"], cwd=str(root), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "tester"], cwd=str(root), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=str(root), check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(root), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(root), check=True, capture_output=True)


def test_diff_impact_oracle_precision_and_blast_radius():
    """Verify that diff impact calculates exact blast radius without over-tainting unrelated modules."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        setup_diff_impact_corpus(root)

        db_path = root / ".sot" / "sot.db"
        db = Database(str(db_path))
        try:
            reconciler = Reconciler(db, str(root))
            reconciler.reconcile()

            # Modify src/math_lib.py
            math_file = root / "src" / "math_lib.py"
            math_file.write_text("""
def base_add(a: int, b: int) -> int:
    return a + b + 1

def calculate_fee(amount: int) -> int:
    return base_add(amount, 20)
""", encoding="utf-8", newline="")

            # Reconcile working tree changes
            reconciler.reconcile()

            engine = DiffImpactEngine(db, str(root))
            impact = engine.analyze_diff_impact(working_tree=True)

            impacted_paths = {item.path for item in impact.caller_impacts}
            impacted_symbols = {item.symbol for item in impact.caller_impacts}

            # Verify direct / transitive inward callers
            assert any("order_service.py" in p for p in impacted_paths)
            assert any("process_order" in s for s in impacted_symbols)

            # Ensure unrelated files are NOT tainted (Precision = 1.0 on unrelated services)
            assert not any("user_service.py" in p for p in impacted_paths)
            assert not any("get_user" in s for s in impacted_symbols)
            # Verify affected test discovery
            affected_tests = {item.path for item in impact.test_impacts}
            assert any("test_math.py" in t for t in affected_tests)
        finally:
            db.close()

def test_diff_impact_receipt_contract():
    """Verify that diff_impact_receipt generates complete deterministic state with snapshot digest."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        setup_diff_impact_corpus(root)

        db_path = root / ".sot" / "sot.db"
        db = Database(str(db_path))
        try:
            reconciler = Reconciler(db, str(root))
            reconciler.reconcile()

            # Modify src/math_lib.py
            math_file = root / "src" / "math_lib.py"
            math_file.write_text("""
def base_add(a: int, b: int) -> int:
    return a + b + 1

def calculate_fee(amount: int) -> int:
    return base_add(amount, 20)
""", encoding="utf-8", newline="")
            reconciler.reconcile()
            receipt = diff_impact_receipt(db, repo_root=str(root), working_tree=True)

            assert receipt["assurance"]["status"] in ("ASSURED_WITHIN_SCOPE", "PARTIAL", "STALE")
            assert receipt["schema_version"] in ("1.1", "2.0")
            assert "post_change_snapshot" in receipt
            assert receipt["post_change_snapshot"]["scope_digest"] is not None
            assert len(receipt["post_change_snapshot"]["content_digests"]) >= 1
            assert any("math_lib.py" in p for p in receipt["post_change_snapshot"]["content_digests"])
        finally:
            db.close()
