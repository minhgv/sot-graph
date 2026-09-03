"""R4: read-only provider cross-check diagnostic.

Seeds graph_edges + provider_runs + provider_evidence via a real Database
and asserts agreements / builtin-only / external-only classification,
relation normalization across vocabularies, invalidation exclusion, and
provider filtering.
"""

import os
import shutil
import tempfile
import unittest

from sot_graph.db import Database
from sot_graph.providers.cross_check import canonical_relation, cross_check

NOW = 1_700_000_000


class CrossCheckTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, ".sot", "crosscheck.db")
        self.db = Database(self.db_path)
        conn = self.db.conn
        # Builtin AST evidence (graph_edges).
        conn.executemany(
            "INSERT INTO graph_edges (path, src, dst, relation, line) VALUES (?,?,?,?,?)",
            [
                ("src/a.py", "func:a", "func:b", "calls", 1),   # matches E1 (call)
                ("src/b.py", "func:c", "func:d", "calls", 2),   # external has imports -> split
                ("src/a.py", "mod:a", "mod:b", "imports", 3),   # matches E3 (import)
            ],
        )
        # External provider runs + evidence.
        conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, capability, "
            "status, created_at) VALUES (?,?,?,?,?,?)",
            ("run-1", "codebase-memory", "0.10.8", "CALLGRAPH", "ok", NOW),
        )
        conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, capability, "
            "status, created_at) VALUES (?,?,?,?,?,?)",
            ("run-2", "scip-index", "1.0", "SYMBOLS", "ok", NOW),
        )
        self._evidence("ev-1", "run-1", "codebase-memory", "func:a", "func:b", "call")
        self._evidence("ev-2", "run-1", "codebase-memory", "func:c", "func:d", "imports")
        self._evidence("ev-3", "run-1", "codebase-memory", "mod:a", "mod:b", "import")
        # External-only claim: provider says a calls zzz but AST never found it.
        self._evidence("ev-4", "run-1", "codebase-memory", "func:a", "func:zzz", "call")
        # Invalidated claim: must be excluded entirely.
        self._evidence(
            "ev-5", "run-1", "codebase-memory", "func:a", "func:ghost", "call",
            invalidated_at=NOW + 5,
        )
        # Different provider, external-only, to exercise --provider filtering.
        self._evidence("ev-6", "run-2", "scip-index", "func:x", "func:y", "references")
        conn.commit()

    def _evidence(self, ev_id, run_id, provider, src, dst, relation, invalidated_at=None):
        self.db.conn.execute(
            "INSERT INTO provider_evidence (id, run_id, provider_name, path, src_symbol, "
            "dst_symbol, relation, invalidated_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (ev_id, run_id, provider, "src/x.py", src, dst, relation, invalidated_at, NOW),
        )

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_canonical_relation_normalizes_both_vocabularies(self):
        # Provider "call" and builtin "calls" must fold onto the same term.
        self.assertEqual(canonical_relation("call"), canonical_relation("calls"))
        self.assertEqual(canonical_relation("call"), "CALLS")
        self.assertEqual(canonical_relation("inherits"), "INHERITS")
        self.assertEqual(canonical_relation("extends"), "INHERITS")
        # Unknown relations fall back to a stable upper-case form.
        self.assertEqual(canonical_relation("transmutes"), "TRANSMUTES")
        self.assertEqual(canonical_relation(None), "")
        self.assertEqual(canonical_relation("  "), "")

    def test_buckets_classify_with_normalized_relations(self):
        report = cross_check(self.db)
        totals = report["totals"]
        self.assertEqual(totals["agreements"], 2)
        self.assertEqual(totals["builtin_only"], 1)
        self.assertEqual(totals["external_only"], 3)

        agreement_pairs = {(a["src"], a["dst"], a["relation"]) for a in report["agreements"]}
        self.assertEqual(
            agreement_pairs,
            {("func:a", "func:b", "CALLS"), ("mod:a", "mod:b", "IMPORTS")},
        )
        builtin_only = {(b["src"], b["dst"], b["relation"]) for b in report["builtin_only"]}
        self.assertEqual(builtin_only, {("func:c", "func:d", "CALLS")})
        external_only = {(e["src"], e["dst"], e["relation"]) for e in report["external_only"]}
        # The c->d pair appears on BOTH sides but with different relations:
        # builtin CALLS vs external IMPORTS — so it lands in both mismatch
        # buckets as distinct (src, dst, relation) pairs.
        self.assertEqual(
            external_only,
            {
                ("func:c", "func:d", "IMPORTS"),
                ("func:a", "func:zzz", "CALLS"),
                ("func:x", "func:y", "CALLS"),
            },
        )
        # references -> CALLS via the normalization table.
        self.assertEqual(totals["unmapped_external_relations"], 0)

    def test_invalidated_evidence_excluded(self):
        report = cross_check(self.db)
        every = (
            [a for a in report["agreements"]]
            + report["builtin_only"] + report["external_only"]
        )
        self.assertNotIn("func:ghost", {e["dst"] for e in every})

    def test_provider_filter_restricts_external_side(self):
        report = cross_check(self.db, provider="scip-index")
        self.assertEqual(report["totals"]["agreements"], 0)
        # Only the scip claim survives on the external side.
        self.assertEqual(
            {(e["src"], e["dst"]) for e in report["external_only"]},
            {("func:x", "func:y")},
        )
        self.assertEqual(report["provider_counts"], {"scip-index": 1})

    def test_counts_and_sample_limit(self):
        report = cross_check(self.db, sample_limit=1)
        self.assertEqual(report["totals"]["agreements"], 2)
        self.assertLessEqual(len(report["agreements"]), 1)
        self.assertEqual(report["totals"]["sample_limit"], 1)
        self.assertEqual(report["provider_counts"]["codebase-memory"], 4)

    def test_cli_subcommand_wiring(self):
        from sot_graph.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["providers", "cross-check", "--json", "--provider", "scip-index"]
        )
        self.assertEqual(args.providers_subcommand, "cross-check")
        self.assertEqual(args.provider, "scip-index")
        self.assertTrue(args.json)
        default_args = parser.parse_args(["providers", "cross-check"])
        self.assertIsNone(default_args.provider)
        self.assertFalse(default_args.json)

    def test_read_only_no_mutation(self):
        before = self.db.conn.execute(
            "SELECT COUNT(*) FROM provider_evidence"
        ).fetchone()[0]
        cross_check(self.db)
        after = self.db.conn.execute(
            "SELECT COUNT(*) FROM provider_evidence"
        ).fetchone()[0]
        self.assertEqual(before, after)
        self.assertTrue(cross_check(self.db)["read_only"])


if __name__ == "__main__":
    unittest.main()
