"""Tests for SQLite Storage Integrity, PRAGMA checks, and sot doctor diagnostics."""
import json
import threading
import time
from pathlib import Path
import pytest

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler
from sot_graph.cli import main as cli_main


@pytest.fixture
def temp_project(tmp_path):
    proj = tmp_path / "test_proj"
    proj.mkdir()
    (proj / "main.py").write_text("def hello():\n    print('hello world')\n", encoding="utf-8")
    (proj / "utils.py").write_text("from main import hello\ndef run():\n    hello()\n", encoding="utf-8")
    return proj


def test_integrity_check_clean_and_populated(temp_project):
    db_path = temp_project / ".sot" / "sot.db"
    db = Database(db_path)
    
    # 1. Clean DB integrity
    diag = db.integrity_check()
    assert diag["ok"] is True
    assert diag["quick_check"] == "ok"
    assert diag["journal_mode"] == "WAL"
    assert diag["schema_version"] == 4
    assert diag["stats"]["paths"] == 0
    assert diag["stats"]["nodes"] == 0
    assert diag["errors"] == []

    # 2. Populated DB
    reconciler = Reconciler(db, str(temp_project))
    summary = reconciler.reconcile()
    assert summary.updated == 2

    diag_pop = db.integrity_check()
    assert diag_pop["ok"] is True
    assert diag_pop["quick_check"] == "ok"
    assert diag_pop["stats"]["paths"] == 2
    assert diag_pop["stats"]["nodes"] >= 2
    assert diag_pop["stats"]["orphaned_nodes"] == 0
    assert diag_pop["stats"]["fts_count"] == diag_pop["stats"]["nodes"]
    assert diag_pop["errors"] == []
    
    db.close()


def test_doctor_cli_text_and_json(temp_project, capsys):
    db_path = temp_project / ".sot" / "sot.db"
    db = Database(db_path)
    reconciler = Reconciler(db, str(temp_project))
    reconciler.reconcile()
    db.close()

    # 1. Test CLI text doctor
    ret = cli_main(["--root", str(temp_project), "doctor"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "SOT-Graph Doctor Report" in captured.out
    assert "quick_check: ok" in captured.out
    assert "WAL" in captured.out

    # 2. Test CLI --json doctor
    ret_json = cli_main(["--root", str(temp_project), "doctor", "--json"])
    assert ret_json == 0
    captured_json = capsys.readouterr()
    data = json.loads(captured_json.out)
    assert data["ok"] is True
    assert data["quick_check"] == "ok"
    assert data["stats"]["paths"] == 2
    assert data["journal_mode"] == "WAL"


def test_stress_storage_integrity_100_rounds(tmp_path):
    """Stress test: 100 rounds of incremental mutations & reconciles with quick_check assertions."""
    proj = tmp_path / "stress_proj"
    proj.mkdir()
    db_path = proj / ".sot" / "sot.db"
    
    db = Database(db_path)
    reconciler = Reconciler(db, str(proj))

    for i in range(100):
        # Create or update a file
        file_idx = i % 10
        fpath = proj / f"mod_{file_idx}.py"
        fpath.write_text(f"def func_{i}():\n    return {i} * 2\n", encoding="utf-8")
        
        # Every 10 iterations, delete an old file
        if i % 10 == 9 and i > 10:
            del_path = proj / f"mod_{(file_idx + 1) % 10}.py"
            if del_path.exists():
                del_path.unlink()

        summary = reconciler.reconcile()
        assert summary.failed == 0

        # Run integrity check every 10 rounds to avoid excessive overhead
        if i % 10 == 0 or i == 99:
            diag = db.integrity_check()
            assert diag["ok"] is True, f"Integrity check failed on round {i}: {diag['errors']}"
            assert diag["quick_check"] == "ok"
            assert diag["stats"]["orphaned_nodes"] == 0

    db.close()


def test_concurrent_readers_with_writer(temp_project):
    """Verify WAL mode allows concurrent readers while writer commits batches."""
    db_path = temp_project / ".sot" / "sot.db"
    db_writer = Database(db_path)
    reconciler = Reconciler(db_writer, str(temp_project))
    reconciler.reconcile()

    reader_errors = []
    stop_event = threading.Event()

    def reader_loop():
        try:
            db_reader = Database(db_path)
            while not stop_event.is_set():
                st = db_reader.stats()
                assert st["paths"] >= 2
                time.sleep(0.005)
            db_reader.close()
        except Exception as exc:
            reader_errors.append(exc)

    threads = [threading.Thread(target=reader_loop) for _ in range(4)]
    for t in threads:
        t.start()

    # Writer performs updates
    for i in range(20):
        (temp_project / f"dynamic_{i}.py").write_text(f"def dyn_{i}(): pass\n", encoding="utf-8")
        reconciler.reconcile()
        time.sleep(0.01)

    stop_event.set()
    for t in threads:
        t.join(timeout=5)

    assert len(reader_errors) == 0, f"Reader thread errors: {reader_errors}"

    diag = db_writer.integrity_check()
    assert diag["ok"] is True
    assert diag["quick_check"] == "ok"
    db_writer.close()
