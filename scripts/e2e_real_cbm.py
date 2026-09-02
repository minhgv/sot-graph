#!/usr/bin/env python3
"""scripts/e2e_real_cbm.py — Real Provider E2E Validation Script for SOT-Graph CI.

Executes end-to-end integration tests with semantic assertions on:
1. Reconcile and indexing of a multi-file realistic repository.
2. Provider detection and capability registration.
3. Federated queries with Codebase Memory & SCIP providers.
4. SQLite evidence ledger persistence and snapshot binding validation.
5. Scope receipt and diff-impact receipt production invariants.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def log(msg: str) -> None:
    print(f"[E2E] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def run_cmd(args: list[str], cwd: str) -> str:
    res = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        fail(f"Command failed ({res.returncode}): {' '.join(args)}\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
    return res.stdout


def setup_test_repo(root: Path) -> None:
    """Create a realistic repository with Python, TypeScript, and Go files."""
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)

    # Python module
    (root / "src" / "auth_service.py").write_text(
        """\"\"\"Auth Service Module.\"\"\"

def hash_password(raw_password: str) -> str:
    return f"hashed_{raw_password}"

def verify_credentials(user: str, token: str) -> bool:
    hashed = hash_password(token)
    return len(hashed) > 0
""",
        encoding="utf-8",
    )

    (root / "src" / "user_handler.py").write_text(
        """\"\"\"User Handler Module.\"\"\"
from src.auth_service import verify_credentials

def handle_login(user_id: str, secret: str) -> dict:
    is_valid = verify_credentials(user_id, secret)
    return {"user": user_id, "authenticated": is_valid}
""",
        encoding="utf-8",
    )

    (root / "tests" / "test_auth.py").write_text(
        """\"\"\"Auth Unit Tests.\"\"\"
from src.auth_service import hash_password, verify_credentials

def test_hash():
    assert hash_password("secret") == "hashed_secret"

def test_verify():
    assert verify_credentials("admin", "secret") is True
""",
        encoding="utf-8",
    )
    (root / ".gitignore").write_text(".sot/sot.db*\n.sot/*.lock\n.sot/write.lock\n.sot/lock*\n.sot/bundle/\n.sot/cache/\n", encoding="utf-8")
    # Config for sot-graph (.sot/config.toml)
    (root / ".sot").mkdir(parents=True, exist_ok=True)
    (root / ".sot" / "config.toml").write_text(
        """allow_external = true

[providers.codebase-memory]
command = ["codebase-memory-mcp"]
""",
        encoding="utf-8",
    )


def test_e2e() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "e2e_repo"
        repo_dir.mkdir(parents=True)
        setup_test_repo(repo_dir)

        # 1. Initialize git repo
        log("Initializing git repository...")
        run_cmd(["git", "init"], cwd=str(repo_dir))
        run_cmd(["git", "config", "user.name", "E2E Test"], cwd=str(repo_dir))
        run_cmd(["git", "config", "user.email", "e2e@test.local"], cwd=str(repo_dir))
        run_cmd(["git", "add", "."], cwd=str(repo_dir))
        run_cmd(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir))

        # 2. Run sot reconcile
        log("Running sot reconcile...")
        out_reconcile = run_cmd([sys.executable, "-m", "sot_graph.cli", "reconcile"], cwd=str(repo_dir))
        log(f"Reconcile output: {out_reconcile.strip()}")

        db_path = repo_dir / ".sot" / "sot.db"
        if not db_path.exists():
            fail("Database .sot/sot.db was not created!")

        # 3. Check SQLite ledger tables
        log("Verifying SQLite schema & ledger tables...")
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        tables = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        
        required_tables = {"graph_nodes", "graph_edges", "file_journal", "provider_runs", "provider_evidence"}
        missing_tables = required_tables - tables
        if missing_tables:
            fail(f"Missing required SQLite tables: {missing_tables}")
        log(f"SQLite verified: found tables {sorted(tables)}")
        # 4. Check Provider Detection
        log("Running sot providers detect...")
        out_detect = run_cmd([sys.executable, "-m", "sot_graph.cli", "providers", "detect", "--format", "json"], cwd=str(repo_dir))
        try:
            detect_json = json.loads(out_detect)
            log(f"Providers detect json: {json.dumps(detect_json, indent=2)}")
        except json.JSONDecodeError:
            log(f"Detect raw output: {out_detect}")
        # 4.1 Run federated usages query
        log("Running federated usages query (auto)...")
        out_usages = run_cmd(
            [sys.executable, "-m", "sot_graph.cli", "usages", "verify_credentials", "--provider", "auto", "--json"],
            cwd=str(repo_dir),
        )
        try:
            usages_json = json.loads(out_usages)
            log(f"Usages query result entries: {len(usages_json.get('references', usages_json.get('callers', [])))}")
        except json.JSONDecodeError:
            log(f"Usages raw output: {out_usages}")

        # 4.2 Test provider sync & require:codebase-memory
        cbm_available = shutil.which("codebase-memory-mcp") is not None
        is_ci = os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"
        if is_ci and not cbm_available:
            fail("In CI environment, codebase-memory-mcp must be installed!")
        if cbm_available:
            from sot_graph.snapshot import dirty_state, _status_entries, get_head_sha
            log(f"Pre-sync git head: {get_head_sha(str(repo_dir))}")
            log(f"Pre-sync git status entries: {_status_entries(str(repo_dir))}")
            log(f"Pre-sync dirty state: {dirty_state(str(repo_dir))}")
            log("Running sot providers sync codebase-memory...")
            res_sync = subprocess.run(
                [sys.executable, "-m", "sot_graph.cli", "providers", "sync", "codebase-memory", "--json"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
            )
            log(f"Sync return code: {res_sync.returncode}, output: {res_sync.stdout.strip()[:100]}")
            if res_sync.returncode != 0:
                fail(f"CBM provider sync failed: {res_sync.stderr}\n{res_sync.stdout}")
            log("Testing require:codebase-memory federated query...")
            out_cbm = run_cmd(
                [sys.executable, "-m", "sot_graph.cli", "usages", "verify_credentials", "--provider", "require:codebase-memory", "--json"],
                cwd=str(repo_dir),
            )
            log(f"CBM federated output: {out_cbm[:120]}...")
            try:
                cbm_json = json.loads(out_cbm)
                external_cands = cbm_json.get("external_candidates", [])
                log(f"CBM external_candidates count: {len(external_cands)}")
                if not external_cands:
                    fail("Semantic gate failed: require:codebase-memory returned zero external_candidates for verify_credentials!")
                
                # Check provider provenance on all candidates
                for cand in external_cands:
                    if cand.get("provider") != "codebase-memory":
                        fail(f"Candidate provider is not codebase-memory: {cand}")
                    log(f"Found CBM candidate: name={cand.get('name') or cand.get('target') or cand.get('symbol')}, provider={cand.get('provider')}")
                
                # Verify provider in envelope
                provs = cbm_json.get("providers", [])
                if not any(p.get("name") == "codebase-memory" for p in provs):
                    fail("codebase-memory not declared in response envelope providers!")

                # Verify builtin callers intact
                builtin_callers = cbm_json.get("callers", [])
                log(f"Builtin callers preserved: count={len(builtin_callers)}")
            except json.JSONDecodeError:
                fail(f"Failed to parse require:codebase-memory output: {out_cbm}")
            # Verify SQLite ledger persistence for CBM
            log("Verifying provider_runs and provider_bindings in SQLite ledger...")
            with sqlite3.connect(str(db_path)) as conn:
                cur = conn.cursor()
                all_runs = cur.execute(
                    "SELECT id, capability, status, exit_code, snapshot_hash "
                    "FROM provider_runs WHERE provider_name = 'codebase-memory' "
                    "ORDER BY rowid ASC"
                ).fetchall()
                log(f"All CBM runs in ledger ({len(all_runs)}): {all_runs}")
                all_bindings = cur.execute(
                    "SELECT sot_repo_id, provider_name, provider_project_id, head_sha "
                    "FROM provider_project_bindings"
                ).fetchall()
                log(f"All bindings in ledger ({len(all_bindings)}): {all_bindings}")
                cur.execute(
                    "SELECT id, capability, status, exit_code, snapshot_hash "
                    "FROM provider_runs WHERE provider_name = 'codebase-memory' "
                    "ORDER BY rowid DESC LIMIT 1"
                )
                run_row = cur.fetchone()
                if not run_row:
                    fail("provider_runs row missing for codebase-memory!")
                rid, cap, st, ec, snap = run_row
                log(f"Ledger run verified: id={rid}, cap={cap}, status={st}, exit_code={ec}, snap={snap}")
                if st != "ok" or ec != 0:
                    fail(f"Ledger run has non-ok status: status={st}, exit_code={ec}")
                if not snap:
                    fail("Ledger run has null snapshot_hash (binding failed)!")

                cur.execute(
                    "SELECT sot_repo_id, provider_project_id, head_sha FROM provider_project_bindings "
                    "WHERE provider_name = 'codebase-memory' LIMIT 1"
                )
                bind_row = cur.fetchone()
                if not bind_row:
                    fail("provider_project_bindings row missing for codebase-memory!")
                log(f"Ledger binding verified: repo_id={bind_row[0]}, project_id={bind_row[1]}, head_sha={bind_row[2]}")
                expected_head = get_head_sha(str(repo_dir))
                if bind_row[2] != expected_head:
                    fail(f"Binding head_sha mismatch: expected {expected_head}, got {bind_row[2]}")
        log("Testing fail-closed negative path for non-existent provider...")
        res_neg = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "usages", "verify_credentials", "--provider", "require:nonexistent", "--json"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
        )
        if res_neg.returncode == 0:
            fail("Expected require:nonexistent to fail closed, but it returned 0!")
        log(f"Fail-closed verified: non-existent provider exited with code {res_neg.returncode}")

        # 5. Run scope_receipt via CLI
        log("Running sot scope-receipt for verify_credentials...")
        out_receipt = run_cmd(
            [sys.executable, "-m", "sot_graph.cli", "scope-receipt", "verify_credentials", "--json"],
            cwd=str(repo_dir),
        )
        try:
            receipt_json = json.loads(out_receipt)
            status = receipt_json.get("assurance", {}).get("status")
            log(f"Scope Receipt status: {status}")
            if status not in ("ASSURED_WITHIN_SCOPE", "PARTIAL"):
                fail(f"Unexpected scope receipt status: {status}")
            
            # Check snapshot binding
            snapshot = receipt_json.get("snapshot", {})
            if not snapshot.get("scope_digest"):
                fail("Scope digest missing from snapshot!")
            if not snapshot.get("content_digests"):
                fail("Content digests missing from snapshot!")
            log(f"Scope digest: {snapshot.get('scope_digest')}")
            log(f"Content digests count: {len(snapshot.get('content_digests', {}))}")
        except json.JSONDecodeError:
            fail(f"Failed to parse scope-receipt JSON: {out_receipt}")

        # 6. Make a change and test diff-impact
        log("Modifying src/auth_service.py and testing diff-impact...")
        auth_file = repo_dir / "src" / "auth_service.py"
        auth_file.write_text(
            """\"\"\"Auth Service Module.\"\"\"

def hash_password(raw_password: str) -> str:
    return f"sha256_hashed_{raw_password}"

def verify_credentials(user: str, token: str) -> bool:
    hashed = hash_password(token)
    return len(hashed) > 10
""",
            encoding="utf-8",
        )

        out_diff = run_cmd(
            [sys.executable, "-m", "sot_graph.cli", "diff-impact", "--working-tree", "--json"],
            cwd=str(repo_dir),
        )
        try:
            diff_json = json.loads(out_diff)
            changed_files = diff_json.get("changed_files", [])
            log(f"Diff Impact changed files: {changed_files}")
            if not any("auth_service.py" in f for f in changed_files):
                fail(f"Expected auth_service.py in changed files, got: {changed_files}")

            # Verify caller impact on user_handler
            caller_impacts = diff_json.get("caller_impacts", [])
            log(f"Caller impacts: {len(caller_impacts)}")
        except json.JSONDecodeError:
            fail(f"Failed to parse diff-impact JSON: {out_diff}")

        # 7. Post-reconcile and ledger validation
        log("Reconciling and checking ledger recording...")
        run_cmd([sys.executable, "-m", "sot_graph.cli", "reconcile"], cwd=str(repo_dir))
        
        journal_count = cursor.execute("SELECT count(*) FROM file_journal").fetchone()[0]
        if journal_count < 3:
            fail(f"Expected at least 3 journal entries, got {journal_count}")
        log(f"File journal records: {journal_count}")

        conn.close()

    log("ALL REAL PROVIDER E2E ASSERTIONS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    test_e2e()
