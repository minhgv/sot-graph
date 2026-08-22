#!/usr/bin/env python3
"""Field-test metrics for a sot-graph database.

Prints node/edge/pending breakdowns plus self-loop and dangling-edge counts
so before/after comparisons of extractor or resolver changes are a one-liner:

    python3 scripts/field_metrics.py /tmp/sot-test/php-crm.db [db2 ...]
"""

import json
import sqlite3
import sys


def metrics(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        out = {"db": db_path}
        out["nodes_by_kind"] = dict(conn.execute(
            "SELECT kind, COUNT(*) FROM graph_nodes GROUP BY kind ORDER BY 2 DESC"))
        out["edges_by_relation"] = dict(conn.execute(
            "SELECT relation, COUNT(*) FROM graph_edges GROUP BY relation ORDER BY 2 DESC"))
        out["pending_by_state"] = dict(conn.execute(
            "SELECT resolution_state, COUNT(*) FROM pending_edges GROUP BY 1"))
        out["pending_by_relation"] = dict(conn.execute(
            "SELECT relation, COUNT(*) FROM pending_edges GROUP BY 1"))
        out["self_loops"] = conn.execute(
            "SELECT COUNT(*) FROM graph_edges WHERE src = dst").fetchone()[0]
        out["dangling_edges"] = conn.execute(
            "SELECT COUNT(*) FROM graph_edges e WHERE NOT EXISTS "
            "(SELECT 1 FROM graph_nodes n WHERE n.id = e.src) OR NOT EXISTS "
            "(SELECT 1 FROM graph_nodes n WHERE n.id = e.dst)").fetchone()[0]
        out["ambiguous_imports"] = conn.execute(
            "SELECT COUNT(*) FROM pending_edges WHERE relation = 'imports' "
            "AND resolution_state = 'AMBIGUOUS'").fetchone()[0]
        return out
    finally:
        conn.close()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    print(json.dumps([metrics(p) for p in sys.argv[1:]], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
