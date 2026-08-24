"""
tests/fault/test_fault_injection.py - Comprehensive Fault-Injection Test Suite for sot-graph.

Covers 6 critical fault scenarios:
1. Process Hard Kill / WAL Recovery
2. SQLite Connection Drop
3. Disk Exhaustion (ENOSPC / I/O error)
4. Lock Acquisition Timeout (LockTimeoutError / LockBusy)
5. Concurrent Publication CAS Collision
6. Post-Crash Self-Healing & Note Preservation
"""
from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from typing import Any
import unittest
from sot_graph.db import Database
from sot_graph.locking import LockBusy, LockTimeoutError, WriteLock
from sot_graph.reconciler import ParseResult, Reconciler

def _crash_worker(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA cache_size = 5;")
    # Insert initial committed rows
    conn.execute("BEGIN IMMEDIATE;")
    for i in range(20):
        conn.execute(
            "INSERT INTO graph_nodes (id, path, kind, symbol, label, body, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                f"committed:node:{i}",
                f"core/committed_{i}.py",
                "function",
                f"committed_func_{i}",
                f"committed_func_{i}",
                "def committed_func(): pass",
                int(time.time()),
            ),
        )
    conn.execute("COMMIT;")

    # Start one uncommitted transaction with BEGIN IMMEDIATE, insert large payload (>50 pages) to force page cache spill to WAL
    conn.execute("BEGIN IMMEDIATE;")
    heavy_payload = "X" * 4096  # 4KB per row
    for i in range(60):
        conn.execute(
            "INSERT INTO graph_nodes (id, path, kind, symbol, label, body, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                f"uncommitted:node:{i}",
                f"core/uncommitted_{i}.py",
                "function",
                f"uncommitted_func_{i}",
                f"uncommitted_func_{i}",
                heavy_payload,
                int(time.time()),
            ),
        )
    wal_file = Path(db_path + "-wal")
    assert wal_file.exists() and wal_file.stat().st_size > 0, "WAL file must exist with bytes > 0"
    # Abrupt crash simulation: exit directly with dirty uncommitted WAL state
    os._exit(42)
class _FailingConnProxy:
    def __init__(self, conn: Any, fail_pattern: str, exc: Exception, close_on_fail: bool = False) -> None:
        self._conn = conn
        self._fail_pattern = fail_pattern
        self._exc = exc
        self._close_on_fail = close_on_fail

    def executemany(self, sql: str, seq: Any) -> Any:
        if self._fail_pattern in sql:
            if self._close_on_fail:
                try:
                    self._conn.close()
                except Exception:
                    pass
            raise self._exc
        return self._conn.executemany(sql, seq)

    def execute(self, sql: str, *args: Any) -> Any:
        if self._fail_pattern in sql:
            if self._close_on_fail:
                try:
                    self._conn.close()
                except Exception:
                    pass
            raise self._exc
        return self._conn.execute(sql, *args)

    def __enter__(self) -> Any:
        return self._conn.__enter__()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        try:
            return self._conn.__exit__(exc_type, exc_val, exc_tb)
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            return None
    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)



class TestFaultInjection(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp(prefix="sot_fault_test_")
        self.db_path = os.path.join(self.test_dir, ".sot", "sot.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.db = Database(self.db_path)
        self.reconciler = Reconciler(self.db, self.test_dir)

    def tearDown(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Scenario 1: Process Hard Kill / WAL Recovery
    # -------------------------------------------------------------------------
    def test_scenario_1_process_hard_kill_and_wal_recovery(self) -> None:
        """
        Simulate process hard-kill mid-transaction:
        1. Commit a valid baseline file.
        2. Spawn a subprocess/multiprocessing worker that starts an uncommitted transaction writing into WAL and calls os._exit(42).
        3. Open a fresh Database instance -> verify SQLite WAL auto-recovers,
           uncommitted dirty data is discarded, baseline committed data is intact,
           and PRAGMA integrity_check passes cleanly.
        """
        # Step 1: Baseline commit
        rec = ParseResult(
            path="core/engine.py",
            sha256="abc123sha",
            size=1024,
            mtime_ms=1000,
            nodes=[{
                "id": "core/engine.py:Engine",
                "kind": "class",
                "symbol": "Engine",
                "label": "Engine",
                "fqn": "core.engine.Engine",
                "line_start": 10,
                "line_end": 50,
            }],
            edges=[],
            pending=[],
        )
        self.db.commit_file_batch([rec])
        self.db.close()

        # Step 2: Spawn multiprocessing.Process that writes dirty rows into WAL and calls os._exit(42)
        proc = multiprocessing.Process(target=_crash_worker, args=(self.db_path,))
        proc.start()
        proc.join(timeout=5.0)
        self.assertEqual(proc.exitcode, 42, "Worker process must terminate abnormally via os._exit(42)")

        # Step 3: Reopen with fresh Database connection
        new_db = Database(self.db_path)
        try:
            # Check PRAGMA integrity
            integrity = new_db.conn.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(integrity, "ok")

            # Verify uncommitted dirty nodes were rolled back
            uncommitted = new_db.conn.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE id LIKE 'uncommitted:node:%'"
            ).fetchone()[0]
            self.assertEqual(uncommitted, 0, "Uncommitted data must be rolled back on recovery")

            # Verify baseline committed node is intact
            baseline = new_db.conn.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE id = 'core/engine.py:Engine'"
            ).fetchone()[0]
            self.assertEqual(baseline, 1, "Baseline committed data must remain intact")

            # Verify worker committed nodes are intact
            committed = new_db.conn.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE id LIKE 'committed:node:%'"
            ).fetchone()[0]
            self.assertEqual(committed, 20, "Worker committed data must remain intact")

            # Verify WAL checkpoint works cleanly
            ckpt = new_db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            self.assertEqual(ckpt[0], 0)
        finally:
            new_db.close()

    test_process_crash_wal_recovery = test_scenario_1_process_hard_kill_and_wal_recovery
    # -------------------------------------------------------------------------
    # Scenario 2: SQLite Connection Drop Mid-Operation
    # -------------------------------------------------------------------------
    def test_scenario_2_connection_drop_and_rollback(self) -> None:
        """
        Simulate connection drop / interruption mid-operation:
        1. Ensure database integrity check passes before and after.
        2. Attempt transactional mutation that fails due to connection drop during commit_file_batch.
        3. Verify safe rollback, no orphaned locks or dirty state, and subsequent queries succeed.
        """
        file_path = os.path.join(self.test_dir, "test_conn.py")
        with open(file_path, "w") as f:
            f.write("def func_conn():\n    return 42\n")
        
        self.reconciler.reconcile()
        initial_nodes = self.db.conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        self.assertGreater(initial_nodes, 0)

        rec_drop = ParseResult(
            path="service/drop.py",
            sha256="sha_drop",
            size=300,
            mtime_ms=1000,
            nodes=[{
                "id": "service/drop.py:DropFunc",
                "kind": "function",
                "symbol": "DropFunc",
                "label": "DropFunc",
            }],
            edges=[],
            pending=[],
        )

        # Wrap connection in proxy to simulate disconnect mid-batch during graph_nodes insertion
        orig_conn = self.db.conn
        proxy = _FailingConnProxy(
            orig_conn,
            "graph_nodes",
            sqlite3.OperationalError("cannot operate on a closed database / disconnect"),
            close_on_fail=True,
        )
        self.db.conn = proxy  # type: ignore[assignment]
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.db.commit_file_batch([rec_drop])
        finally:
            self.db.conn = orig_conn

        # Reopen fresh connection since proxy closed the connection during hard drop
        self.db = Database(self.db_path)
        # Verify rollback: drop.py is not in nodes or journal
        drop_nodes = self.db.conn.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE path = 'service/drop.py'"
        ).fetchone()[0]
        self.assertEqual(drop_nodes, 0)
        self.assertIsNone(self.db.get_file_journal("service/drop.py"))

        # Open fresh connection on same database and verify integrity
        nodes_count = self.db.conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        self.assertEqual(nodes_count, initial_nodes)
        check = self.db.integrity_check()
        self.assertEqual(check["quick_check"], "ok")
        self.assertEqual(len(check["errors"]), 0)
    # Scenario 3: Disk Exhaustion (ENOSPC / I/O Error)
    # -------------------------------------------------------------------------
    def test_scenario_3_disk_exhaustion_enospc_rollback(self) -> None:
        """
        Simulate ENOSPC / disk full / I/O error during transactional batch publication:
        1. Setup initial consistent database state.
        2. Execute commit_file_batch where an intermediate step encounters simulated ENOSPC (disk I/O error).
        3. Verify exception is propagated, atomic transaction rollback occurs,
           no partial records leaked, and subsequent valid commit succeeds.
        """
        rec_initial = ParseResult(
            path="service/payment.py",
            sha256="sha_init",
            size=500,
            mtime_ms=1000,
            nodes=[{
                "id": "service/payment.py:PaymentService",
                "kind": "class",
                "symbol": "PaymentService",
                "label": "PaymentService",
                "fqn": "service.payment.PaymentService",
            }],
            edges=[],
            pending=[],
        )
        self.db.commit_file_batch([rec_initial])
        
        # New batch to commit
        rec_failing = ParseResult(
            path="service/order.py",
            sha256="sha_order",
            size=600,
            mtime_ms=2000,
            nodes=[{
                "id": "service/order.py:OrderService",
                "kind": "class",
                "symbol": "OrderService",
                "label": "OrderService",
                "fqn": "service.order.OrderService",
            }],
            edges=[{
                "src": "service/order.py:OrderService",
                "dst": "service/payment.py:PaymentService",
                "relation": "calls",
                "line": 15,
            }],
            pending=[],
        )

        # Wrap connection in proxy to simulate disk I/O error: disk full during graph_edges insertion
        orig_conn = self.db.conn
        proxy = _FailingConnProxy(
            orig_conn,
            "graph_edges",
            sqlite3.OperationalError("disk I/O error: disk full"),
        )
        self.db.conn = proxy  # type: ignore[assignment]
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.db.commit_file_batch([rec_failing])
        finally:
            self.db.conn = orig_conn
        # Verify rollback: service/order.py nodes and journal must NOT exist in DB
        order_nodes = self.db.conn.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE path = 'service/order.py'"
        ).fetchone()[0]
        self.assertEqual(order_nodes, 0, "No partially written records must exist after ENOSPC rollback")

        # Verify initial records still intact
        payment_nodes = self.db.conn.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE path = 'service/payment.py'"
        ).fetchone()[0]
        self.assertEqual(payment_nodes, 1)

        # Verify journal is not corrupted
        order_journal = self.db.get_file_journal("service/order.py")
        self.assertIsNone(order_journal)

        # Verify subsequent normal commit succeeds
        outcome = self.db.commit_file_batch([rec_failing])
        self.assertEqual(outcome["committed"], 1)
        self.assertEqual(len(outcome["conflicts"]), 0)
        self.assertIsNotNone(self.db.get_file_journal("service/order.py"))
    # -------------------------------------------------------------------------
    # Scenario 4: Lock Acquisition Timeout
    # -------------------------------------------------------------------------
    def test_scenario_4_lock_acquisition_timeout(self) -> None:
        """
        Verify LockTimeoutError and LockBusy:
        1. Acquire primary WriteLock with holder A.
        2. Attempt to acquire WriteLock with holder B with short timeout.
        3. Verify LockTimeoutError (subclass of LockBusy) is explicitly caught.
        4. Verify active lock file is NOT removed or corrupted.
        5. Verify holder A can release lock cleanly and holder B can then acquire.
        """
        lock_path = os.path.join(self.test_dir, ".sot", "write.lock")
        
        lock_a = WriteLock(lock_path, timeout_ms=5000)
        lock_a.acquire()
        self.assertTrue(os.path.exists(lock_path), "Lock file must exist while held by holder A")

        # Holder B attempts acquisition with short timeout (50ms)
        lock_b = WriteLock(lock_path, timeout_ms=50)
        with self.assertRaises(LockTimeoutError) as ctx:
            lock_b.acquire()
        self.assertIsInstance(ctx.exception, LockBusy)
        self.assertIn("Could not acquire write lock", str(ctx.exception))
        
        # Verify lock file is still present and valid
        self.assertTrue(os.path.exists(lock_path), "Lock file must NOT be deleted by timed out requester")

        # Holder A releases lock
        lock_a.release()

        # Holder B can now acquire cleanly
        lock_b.acquire()
        lock_b.release()
    # -------------------------------------------------------------------------
    # Scenario 5: Concurrent Publication CAS Collision
    # -------------------------------------------------------------------------
    def test_scenario_5_concurrent_publication_cas_collision(self) -> None:
        """
        Simulate two concurrent workers publishing modifications for the same file:
        1. Baseline state: file_journal has path 'mod.py' with generation = 1.
        2. Worker 1 reads generation 1, parses, and commits -> updates generation to 2.
        3. Worker 2 was also working with expected_generation = 1.
        4. Worker 2 attempts commit_file_batch -> CAS fails, returning path in conflicts list.
        5. Worker 2 detects conflict, re-reads current generation (2), re-parses/re-packages,
           and successfully commits with expected_generation = 2 -> updates generation to 3.
        """
        target_path = "modules/auth.py"
        
        # Baseline
        rec_base = ParseResult(
            path=target_path,
            sha256="sha_v1",
            size=100,
            mtime_ms=1000,
            nodes=[{"id": "auth:v1", "kind": "function", "symbol": "login", "label": "login"}],
            edges=[],
            pending=[],
            base_generation=0,
        )
        self.db.commit_file_batch([rec_base], expected_generations={target_path: 0})
        
        j_init = self.db.get_file_journal(target_path)
        self.assertIsNotNone(j_init)
        self.assertEqual(j_init["generation"], 1)

        # Worker 1 commits change with expected_generation = 1
        rec_worker1 = ParseResult(
            path=target_path,
            sha256="sha_v2_worker1",
            size=120,
            mtime_ms=1500,
            nodes=[{"id": "auth:v2_w1", "kind": "function", "symbol": "login_v2", "label": "login_v2"}],
            edges=[],
            pending=[],
            base_generation=1,
        )
        outcome1 = self.db.commit_file_batch([rec_worker1], expected_generations={target_path: 1})
        self.assertEqual(outcome1["committed"], 1)
        self.assertEqual(outcome1["conflicts"], [])

        j_w1 = self.db.get_file_journal(target_path)
        self.assertEqual(j_w1["generation"], 2)

        # Worker 2 attempts commit with stale expected_generation = 1
        rec_worker2 = ParseResult(
            path=target_path,
            sha256="sha_v2_worker2",
            size=130,
            mtime_ms=1600,
            nodes=[{"id": "auth:v2_w2", "kind": "function", "symbol": "login_custom", "label": "login_custom"}],
            edges=[],
            pending=[],
            base_generation=1,
        )
        outcome2 = self.db.commit_file_batch([rec_worker2], expected_generations={target_path: 1})
        
        # CAS detection: conflict returned, zero records overwritten
        self.assertEqual(outcome2["committed"], 0)
        self.assertIn(target_path, outcome2["conflicts"])

        # Verify Worker 1 data is still the active data
        active_nodes = self.db.conn.execute(
            "SELECT id FROM graph_nodes WHERE path = ?", (target_path,)
        ).fetchall()
        self.assertEqual([r[0] for r in active_nodes], ["auth:v2_w1"])

        # Worker 2 re-checks current generation and retries
        j_current = self.db.get_file_journal(target_path)
        current_gen = j_current["generation"]
        self.assertEqual(current_gen, 2)

        outcome2_retry = self.db.commit_file_batch(
            [rec_worker2], expected_generations={target_path: current_gen}
        )
        self.assertEqual(outcome2_retry["committed"], 1)
        self.assertEqual(outcome2_retry["conflicts"], [])

        j_final = self.db.get_file_journal(target_path)
        self.assertEqual(j_final["generation"], 3)
        self.assertEqual(j_final["sha256"], "sha_v2_worker2")

    # -------------------------------------------------------------------------
    # Scenario 6: Post-Crash Self-Healing & Note Preservation
    # -------------------------------------------------------------------------
    def test_scenario_6_post_crash_self_healing_and_note_preservation(self) -> None:
        """
        Verify post-crash self-healing and user note preservation:
        1. Insert user notes (kind == 'note').
        2. Create and reconcile code files.
        3. Corrupt disposable index tables (inject orphaned nodes missing from journal).
        4. Run integrity check -> verify warnings detected.
        5. Run plan_clean / apply_clean and reconciler -> self-heals disposable index.
        6. Verify PRAGMA integrity_check == 'ok', and user notes preserved.
        """
        # 1. Insert user note
        note_id = "note:arch_dec_001"
        note_title = "Architectural ADR: Decoupled SQLite DAL"
        note_body = "All DAL access must be scoped and transactional."
        with self.db.write_lock():
            with self.db.conn:
                self.db.conn.execute("""
                    INSERT INTO graph_nodes (id, path, kind, symbol, label, body, keywords, line_start, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (note_id, "", "note", None, note_title, note_body, "adr dal sqlite", 1, 1000))

        # 2. Reconcile normal code file
        code_file = os.path.join(self.test_dir, "calc.py")
        with open(code_file, "w") as f:
            f.write("def calculate_total(x: int, y: int) -> int:\n    return x + y\n")
        self.reconciler.reconcile()

        # 3. Simulate index damage / inject orphaned code node
        with self.db.write_lock():
            with self.db.conn:
                self.db.conn.execute(
                    "INSERT INTO graph_nodes (id, path, kind, symbol, label, body, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("orphan:calc_old", "calc_old.py", "function", "calc_old", "calc_old", "def calc_old(): pass", 1000)
                )
        check = self.db.integrity_check()
        self.assertGreater(len(check["warnings"]), 0, "Integrity check must detect orphaned code node")

        # 5. Clean / heal and reconcile
        plan = self.db.plan_clean(self.test_dir, reset=False, include_notes=False)
        self.db.apply_clean(plan)
        summary = self.reconciler.reconcile(force=True)
        self.assertEqual(summary.failed, 0)

        # 6. Verify post-heal consistency
        healed_check = self.db.integrity_check()
        self.assertEqual(healed_check["quick_check"], "ok")
        self.assertEqual(len(healed_check["errors"]), 0)

        # Verify user notes are intact!
        note_row = self.db.conn.execute(
            "SELECT id, label, body, kind FROM graph_nodes WHERE id = ?", (note_id,)
        ).fetchone()
        self.assertIsNotNone(note_row, "User note must NEVER be lost across healing cycles")
        self.assertEqual(note_row[1], note_title)
        self.assertEqual(note_row[2], note_body)
        self.assertEqual(note_row[3], "note")

        # Verify code search works
        results = self.db.search_fts("calculate_total")
        self.assertTrue(len(results) > 0, "FTS index must be rebuilt and searchable")


if __name__ == "__main__":
    unittest.main()
