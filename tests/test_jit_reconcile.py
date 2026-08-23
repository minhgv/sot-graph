import argparse
import os
import tempfile
import time
from sot_graph.cli import cmd_search
from sot_graph.db import Database
from sot_graph.evidence import FreshnessStatus, RelevanceType
from sot_graph.mcp_service import McpService
from sot_graph.reconciler import Reconciler
from sot_graph.verifier import TrustVerifier, tokenize


def test_trust_verifier_detects_stale_file_when_modified():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, ".sot", "sot.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        db = Database(db_path)

        src_file = os.path.join(tmpdir, "service.py")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write("def calculate_tax(amount):\n    return amount * 0.1\n")

        rec = Reconciler(db, tmpdir)
        summary = rec.reconcile()
        assert summary.updated == 1

        cand = db.search_fts("calculate_tax")[0]

        # Initial hit: FRESH & STRONG
        res = TrustVerifier.verify_hit(db, cand, tokenize("calculate_tax"), tmpdir, jit_reconcile=False)
        assert res.evidence.freshness == FreshnessStatus.FRESH
        assert res.evidence.relevance in (RelevanceType.EXACT_SPAN, RelevanceType.EXACT_SYMBOL)
        assert res[0] == "STRONG"

        # Modify file on disk (simulate user edit in IDE without manual reconcile)
        time.sleep(0.05)
        with open(src_file, "w", encoding="utf-8") as f:
            f.write("def calculate_tax_v2(amount, rate=0.15):\n    return amount * rate\n")

        # Query with jit_reconcile=False -> Detected as STALE
        res_stale = TrustVerifier.verify_hit(db, cand, tokenize("calculate_tax"), tmpdir, jit_reconcile=False)
        assert res_stale.evidence.freshness == FreshnessStatus.STALE
        assert res_stale.evidence.details["stale"] is True

        # Query with jit_reconcile=True -> JIT Micro-Reconcile triggers and refreshes to FRESH
        res_fresh = TrustVerifier.verify_hit(db, cand, tokenize("calculate_tax_v2"), tmpdir, jit_reconcile=True)
        assert res_fresh.evidence.freshness == FreshnessStatus.FRESH
        assert res_fresh.evidence.details["stale"] is False

        # Verify DB journal was updated
        journal = db.get_file_journal(src_file) or db.get_file_journal("service.py")
        assert journal is not None
        assert journal["generation"] >= 1


def test_cli_cmd_search_jit_reconcile():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, ".sot", "sot.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        db = Database(db_path)

        src_file = os.path.join(tmpdir, "order.py")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write("class OrderProcessor:\n    def process(self):\n        pass\n")

        Reconciler(db, tmpdir).reconcile()

        # Modify file
        time.sleep(0.05)
        with open(src_file, "w", encoding="utf-8") as f:
            f.write("class OrderProcessor:\n    def process_order_v2(self):\n        pass\n")

        args = argparse.Namespace(
            query="OrderProcessor",
            limit=5,
            scope=None,
            threshold=0.5,
            hybrid=False,
            jit=True,
            json=True,
        )
        code = cmd_search(args, db, tmpdir)
        assert code == 0


def test_mcp_service_stale_detection_via_conn_view():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, ".sot", "sot.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        db = Database(db_path)

        src_file = os.path.join(tmpdir, "auth.py")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write("def login_user(username, password):\n    return True\n")

        Reconciler(db, tmpdir).reconcile()

        # Modify file on disk
        time.sleep(0.05)
        with open(src_file, "w", encoding="utf-8") as f:
            f.write("def login_user_v2(email, token):\n    return True\n")

        svc = McpService(db_path, tmpdir)
        res = svc.search("login_user")
        assert res["returned"] >= 1
        assert res["stale"] >= 1 or res["results"][0]["evidence"]["freshness"] == "STALE"
