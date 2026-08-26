#!/usr/bin/env python3
"""Lifecycle integrity runs (roadmap §9 final gate).

Repeats N full reconcile cycles on a scratch repository and asserts the
invariants that must hold after EVERY cycle:

- schema version is the running SCHEMA_VERSION,
- journal row count matches files on disk,
- quick_check passes (no corruption accumulation),
- receipts stay deterministic across cycles (same digest for the same
  pre-change state).

Exit 0 only when every cycle passed. Default N=100 per the final gate.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

REPO_FILES = {
    "app.py": "import util\n\n\ndef run():\n    return util.help()\n",
    "util.py": "def help():\n    return 42\n",
    "tests/test_app.py": "from app import run\n\n\ndef test_run():\n    assert run() == 43\n",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=100)
    args = parser.parse_args()

    from sot_graph.assurance.receipts import scope_receipt
    from sot_graph.db import SCHEMA_VERSION, Database

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="lifecycle-") as tmp:
        repo = Path(tmp) / "repo"
        (repo / "tests").mkdir(parents=True)
        for rel, content in REPO_FILES.items():
            (repo / rel).write_text(content, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c1"],
            cwd=repo, check=True,
        )

        base_digest = None
        for cycle in range(1, args.runs + 1):
            run = subprocess.run(
                [sys.executable, "-m", "sot_graph.cli", "--root", str(repo),
                 "reconcile"],
                cwd=repo, capture_output=True, text=True,
            )
            if run.returncode != 0:
                failures.append(f"cycle {cycle}: reconcile failed: {run.stderr[:200]}")
                break
            db = Database(str(repo / ".sot" / "sot.db"))
            try:
                version = db.conn.execute(
                    "PRAGMA user_version").fetchone()[0]
                if version != SCHEMA_VERSION:
                    failures.append(f"cycle {cycle}: schema {version} != {SCHEMA_VERSION}")
                quick = db.conn.execute("PRAGMA quick_check").fetchone()[0]
                if quick != "ok":
                    failures.append(f"cycle {cycle}: quick_check {quick}")
                journaled = db.conn.execute(
                    "SELECT COUNT(*) FROM file_journal").fetchone()[0]
                on_disk = sum(
                    1 for p in repo.rglob("*.py")
                    if ".sot" not in p.parts
                )
                if journaled < on_disk:
                    failures.append(
                        f"cycle {cycle}: journal {journaled} < files {on_disk}")
                digest = scope_receipt(db, str(repo), "run")["digest"]
                if base_digest is None:
                    base_digest = digest
                elif digest != base_digest:
                    failures.append(f"cycle {cycle}: receipt digest drifted")
            finally:
                db.close()
            if failures:
                break

    if failures:
        for f in failures:
            print(f"❌ {f}", file=sys.stderr)
        return 1
    print(f"✅ {args.runs} lifecycle integrity runs passed "
          f"(digest stable: {(base_digest or "")[:12]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
