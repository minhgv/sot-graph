"""Unit tests for reconcile_receipt and audit_receipt (receipts.py)."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from sot_graph.assurance.receipts import reconcile_receipt, audit_receipt
from sot_graph.db import Database


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture(scope="module")
def sample_repo(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("receipt_repo")
    (repo / "app.py").write_text("def run(): return 1\n", encoding="utf-8")
    (repo / "util.py").write_text("def helper(): return 2\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c1")
    subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo), "reconcile"],
        check=True, cwd=repo, capture_output=True,
    )
    return repo


class TestReconcileAndAuditReceipts:
    def test_reconcile_receipt_success(self, sample_repo):
        db = Database(str(sample_repo / ".sot" / "sot.db"))
        receipt = reconcile_receipt(db, str(sample_repo), reconcile_result={"reconciled": 2})

        assert receipt["kind"] == "reconcile"
        assert receipt["proof_scope"] == "post_reconcile"
        assert receipt["reconcile_summary"]["reconciled"] == 2
        assert len(receipt["digest"]) == 64
        assert "assurance" in receipt
        assert receipt["collection_errors"] == []

    def test_reconcile_receipt_collection_error_fails_closed(self, tmp_path):
        db = MagicMock()
        db.conn.execute.side_effect = RuntimeError("DB locked")

        receipt = reconcile_receipt(db, str(tmp_path))

        assert receipt["kind"] == "reconcile"
        assert len(receipt["collection_errors"]) > 0
        assert receipt["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"

    def test_audit_receipt_success(self, sample_repo):
        db = Database(str(sample_repo / ".sot" / "sot.db"))
        receipt = audit_receipt(db, str(sample_repo), doctor_report={"healthy": True})

        assert receipt["kind"] == "audit"
        assert receipt["proof_scope"] == "system_integrity"
        assert receipt["doctor_summary"]["healthy"] is True
        assert len(receipt["digest"]) == 64
        assert "assurance" in receipt
        assert receipt["collection_errors"] == []
        assert "stale_files" in receipt
        assert isinstance(receipt["stale_files"], list)
        assert "coverage" in receipt
        assert "gaps" in receipt["coverage"]
        assert isinstance(receipt["coverage"]["gaps"], list)
        assert "scope_manifest" in receipt
        assert "snapshot" in receipt
        assert "assurance_facts" in receipt
        assert receipt["assurance"]["status"] == "ASSURED_WITHIN_SCOPE"

    def test_audit_receipt_collection_error_fails_closed(self, tmp_path):
        db = MagicMock()
        db.conn.execute.side_effect = RuntimeError("DB corruption")

        receipt = audit_receipt(db, str(tmp_path))

        assert receipt["kind"] == "audit"
        assert len(receipt["collection_errors"]) > 0
        assert receipt["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
    def test_reconcile_result_failed_count_fails_closed(self, sample_repo):
        db = Database(str(sample_repo / ".sot" / "sot.db"))
        receipt = reconcile_receipt(
            db, str(sample_repo),
            reconcile_result={"reconciled": 2, "failed": 2, "ok": False}
        )
        assert receipt["kind"] == "reconcile"
        assert receipt["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
        assert any("reconcile_failed" in err for err in receipt["collection_errors"])

    def test_audit_receipt_doctor_not_ok_fails_closed(self, sample_repo):
        db = Database(str(sample_repo / ".sot" / "sot.db"))
        receipt = audit_receipt(
            db, str(sample_repo),
            doctor_report={"ok": False, "errors": ["Foreign key integrity check failed"]}
        )
        assert receipt["kind"] == "audit"
        assert receipt["assurance"]["status"] != "ASSURED_WITHIN_SCOPE"
        assert any("doctor_integrity_failed" in err for err in receipt["collection_errors"])
