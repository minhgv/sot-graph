"""R4/SG-203: read-only provider cross-check diagnostic — identity joins.

Seeds a real Database with builtin graph_nodes/graph_edges in their TRUE
shapes (node IDs ``sym:hash:name`` referencing node rows) plus provider
evidence in CBM/SCIP shapes (mangled-root qualified names, raw SCIP
symbol strings) and asserts:

- agreements only ever come from canonical identity joins;
- a string that merely looks equal across identity spaces (the legacy
  raw-string join) resolves to NOTHING — the zero-accidental-joins gate;
- relation mismatches and span disagreements surface as conflicts, with
  span conflicts adjudicated against the live filesystem;
- invalidated evidence is excluded; provider filtering, exact totals
  under sample caps, and read-only behavior all hold.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from sot_graph.assurance.receipts import RECEIPT_SCHEMA_VERSION, cross_check_receipt
from sot_graph.db import Database
from sot_graph.providers.cross_check import canonical_relation, cross_check
from sot_graph.providers.identity_join import mangled_root_prefix

NOW = 1_700_000_000


class CrossCheckTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, ".sot", "crosscheck.db")
        self.db = Database(self.db_path)
        # A real source tree so span adjudication can verify against disk.
        src = os.path.join(self.test_dir, "core")
        app = os.path.join(self.test_dir, "app")
        os.makedirs(src, exist_ok=True)
        os.makedirs(app, exist_ok=True)
        with open(os.path.join(app, "main.py"), "w", encoding="utf-8") as fh:
            fh.write(
                "from core.service import compute_total\n"   # line 1
                "\n"
                "\n"
                "\n"
                "def build_invoice(price, quantity):\n"        # line 5
                "    return compute_total(price, quantity)\n"
                "    \n"
            )
        with open(os.path.join(src, "service.py"), "w", encoding="utf-8") as fh:
            fh.write(
                "TAX_RATE = 0.1\n"
                "\n"
                "\n"
                "def compute_total(price, quantity):\n"     # line 4
                "    subtotal = price * quantity\n"
                "    return round(subtotal * (1 + TAX_RATE), 2)\n"
                "\n"
                "\n"
                "def format_label(name, total):\n"          # line 9
                "    return f'{name}: {total:.2f} USD'\n"
            )
        # CBM mangles the absolute repo root into every qualified name
        # (realpath: macOS /var is a symlink to /private/var — the same
        # aliasing the SG-108 scope normalizer had to absorb). The shared
        # mangling keeps this symmetric with cbm_identity stripping on
        # Windows roots too.
        self.mangled = mangled_root_prefix(self.test_dir)
        conn = self.db.conn
        # Builtin nodes: symbol nodes carry dotted FQNs + paths, and edges
        # reference them by node ID — the real storage shapes.
        conn.executemany(
            "INSERT INTO graph_nodes (id, path, kind, symbol, fqn, label, body,"
            " line_start, line_end, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                ("sym:aaaaaa:build_invoice", "app/main.py", "function",
                 "build_invoice", "app.main.build_invoice", "l", "b", 5, 7, NOW),
                ("sym:aaaaaa:compute_total", "core/service.py", "function",
                 "compute_total", "core.service.compute_total", "l", "b", 4, 6, NOW),
                ("sym:aaaaaa:format_label", "core/service.py", "function",
                 "format_label", "core.service.format_label", "l", "b", 9, 10, NOW),
            ],
        )
        conn.executemany(
            "INSERT INTO graph_edges (path, src, dst, relation, line) VALUES (?,?,?,?,?)",
            [
                # calls: build_invoice -> compute_total (span 4-6 verifies on disk)
                ("app/main.py", "sym:aaaaaa:build_invoice",
                 "sym:aaaaaa:compute_total", "calls", 6),
                # defines edges: the dst symbol is defined in the file
                ("core/service.py", "sym:aaaaaa:compute_total",
                 "sym:aaaaaa:compute_total", "defines", 4),
                ("core/service.py", "sym:aaaaaa:format_label",
                 "sym:aaaaaa:format_label", "defines", 9),
            ],
        )
        # External provider runs.
        conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, "
            "capability, status, created_at) VALUES (?,?,?,?,?,?)",
            ("run-1", "codebase-memory", "0.10.8", "CALLGRAPH", "ok", NOW),
        )
        conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, "
            "capability, status, created_at) VALUES (?,?,?,?,?,?)",
            ("run-2", "scip-index", "1.0", "SYMBOLS", "ok", NOW),
        )
        conn.commit()

    def _evidence(self, ev_id, run_id, provider, src, dst, relation,
                  path="", line_start=None, line_end=None, invalidated_at=None):
        self.db.conn.execute(
            "INSERT INTO provider_evidence (id, run_id, provider_name, path,"
            " src_symbol, target_symbol, dst_symbol, relation, line_start,"
            " line_end, snapshot_hash, recorded_at, created_at,"
            " invalidated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ev_id, run_id, provider, path, src, dst, dst, relation,
             line_start, line_end, "snap", NOW, NOW, invalidated_at),
        )
        self.db.conn.commit()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_canonical_relation_normalizes_both_vocabularies(self):
        self.assertEqual(canonical_relation("calls"), "CALLS")
        self.assertEqual(canonical_relation("call"), "CALLS")
        self.assertEqual(canonical_relation("call:out"), "CALLS")
        self.assertEqual(canonical_relation("call:in"), "CALLS")
        self.assertEqual(canonical_relation("extends"), "INHERITS")
        self.assertEqual(canonical_relation("inherits"), "INHERITS")
        self.assertEqual(canonical_relation("totally novel"), "TOTALLY NOVEL")
        self.assertEqual(canonical_relation(None), "")
        self.assertEqual(canonical_relation("  "), "")

    def test_identity_join_agreement(self):
        # CBM trace shape: mangled-root qualified pair, direction-suffixed
        # relation. Joins the builtin calls edge through canonical identity.
        self._evidence(
            "ev-1", "run-1", "codebase-memory",
            f"{self.mangled}.app.main.build_invoice",
            f"{self.mangled}.core.service.compute_total",
            "call:out", path="app/main.py", line_start=6, line_end=6,
        )
        report = cross_check(self.db, repo_root=self.test_dir)
        edges = [a for a in report["agreements"]
                 if a["claim_type"] == "edge"]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["relation"], "CALLS")
        self.assertEqual(edges[0]["providers"], ["codebase-memory"])
        self.assertEqual(edges[0]["src"]["fqn"], "app.main.build_invoice")
        self.assertEqual(edges[0]["dst"]["fqn"], "core.service.compute_total")
        self.assertEqual(report["totals"]["conflicts"], 0)

    def test_definitions_join_on_identity(self):
        # CBM define rows: qualified name + path + span (search_graph shape).
        self._evidence(
            "ev-d1", "run-1", "codebase-memory",
            f"{self.mangled}.core.service.compute_total", None,
            "define", path="core/service.py", line_start=4, line_end=6,
        )
        self._evidence(
            "ev-d2", "run-1", "codebase-memory",
            f"{self.mangled}.core.service.ghost_fn", None,
            "define", path="core/service.py", line_start=90, line_end=92,
        )
        report = cross_check(self.db, repo_root=self.test_dir)
        defs = [a for a in report["agreements"]
                if a["claim_type"] == "definition"]
        self.assertEqual(len(defs), 1)
        self.assertEqual(defs[0]["identity"]["fqn"],
                         "core.service.compute_total")
        # ghost_fn is claimed externally, not defined by the builtin graph.
        ext_only = [e for e in report["external_only"]
                    if e["claim_type"] == "definition"]
        self.assertEqual(len(ext_only), 1)
        self.assertIn("ghost_fn", ext_only[0]["identity"]["fqn"])

    def test_raw_string_collision_never_joins(self):
        """The zero-accidental-joins gate (acceptance criterion).

        Legacy behavior joined these by string equality: the evidence
        symbols are LITERALLY equal to the builtin edge endpoints. Under
        identity joins they resolve to different (or foreign) identities
        and must produce zero agreements.
        """
        # Case 1: a builtin node ID pasted into a provider column — a
        # foreign shape that resolves to nothing.
        self._evidence("ev-x1", "run-1", "codebase-memory",
                       "sym:aaaaaa:build_invoice",
                       "sym:aaaaaa:compute_total", "call")
        # Case 2: identical strings on both sides, but the builtin node's
        # canonical FQN is module-qualified while the provider string is
        # bare — different identities, no join.
        self._evidence("ev-x2", "run-1", "codebase-memory",
                       "build_invoice", "compute_total", "call")
        report = cross_check(self.db, repo_root=self.test_dir)
        self.assertEqual(report["totals"]["agreements"], 0)
        self.assertGreaterEqual(report["totals"]["unresolved_external"], 1)

    def test_relation_mismatch_is_a_conflict(self):
        # Same identity pair, external claims INHERITS while builtin says CALLS.
        self._evidence(
            "ev-c1", "run-1", "codebase-memory",
            f"{self.mangled}.app.main.build_invoice",
            f"{self.mangled}.core.service.compute_total",
            "inherits",
        )
        report = cross_check(self.db, repo_root=self.test_dir)
        self.assertEqual(report["totals"]["conflicts"], 1)
        conflict = report["conflicts"][0]
        self.assertEqual(conflict["conflict"]["reason"], "relation_mismatch")
        self.assertEqual(conflict["conflict"]["builtin_relation"], "CALLS")
        self.assertEqual(conflict["conflict"]["external_relation"], "INHERITS")
        # The disagreement is surfaced, never counted as agreement.
        self.assertEqual(report["totals"]["agreements"], 0)

    def test_span_disagreement_adjudicates_against_filesystem(self):
        # External claims the same call at lines 60-62 — the builtin span
        # (4-6) is what actually verifies on disk.
        self._evidence(
            "ev-s1", "run-1", "codebase-memory",
            f"{self.mangled}.app.main.build_invoice",
            f"{self.mangled}.core.service.compute_total",
            "call:out", path="core/service.py", line_start=60, line_end=62,
        )
        report = cross_check(self.db, repo_root=self.test_dir)
        self.assertEqual(report["totals"]["conflicts"], 1)
        conflict = report["conflicts"][0]
        self.assertEqual(conflict["conflict"]["reason"], "span_disagreement")
        self.assertEqual(conflict["conflict"]["adjudication"],
                         "builtin_verified")
        # Without repo_root the filesystem adjudicator cannot run — and the
        # mangled-root CBM name no longer resolves, so use plain qualified
        # names to isolate the adjudication behavior itself.
        report_no_root = cross_check(self.db)
        self.assertEqual(report_no_root["totals"]["agreements"], 0)
        self._evidence(
            "ev-s2", "run-1", "codebase-memory",
            "app.main.build_invoice", "core.service.compute_total",
            "call:out", path="app/main.py", line_start=60, line_end=62,
        )
        report_plain = cross_check(self.db)
        span_conflicts = [c for c in report_plain["conflicts"]
                          if c["conflict"]["reason"] == "span_disagreement"]
        self.assertEqual(len(span_conflicts), 1)
        self.assertEqual(span_conflicts[0]["conflict"]["adjudication"], "open")

    def test_windows_mangled_names_fail_closed_without_repo_root(self):
        # Regression (Windows CI): a Windows-mangled-root CBM name used to
        # leak raw separators/colon past mangled_root_prefix, so its path
        # chunks were dropped by canonical_fqn and the residue joined the
        # builtin FQN — a spurious agreement under no repo_root. The
        # dash-only Windows mangling must fail closed exactly like POSIX.
        win_mangled = ("C-Users-runneradmin-AppData-Local-Temp-"
                       "pytest-of-runneradmin-pytest-2-test_span0")
        self._evidence(
            "ev-win1", "run-1", "codebase-memory",
            f"{win_mangled}.app.main.build_invoice",
            f"{win_mangled}.core.service.compute_total",
            "call:out", path="core/service.py", line_start=5, line_end=7,
        )
        report = cross_check(self.db)
        self.assertEqual(report["totals"]["agreements"], 0)
        self.assertEqual(report["totals"]["unresolved_external"], 1)

    def test_unresolved_endpoints_counted_never_joined(self):
        # Builtin edge whose dst node row is gone.
        self.db.conn.execute(
            "INSERT INTO graph_edges (path, src, dst, relation, line)"
            " VALUES ('app/main.py','sym:aaaaaa:build_invoice',"
            "'sym:deadbee:vanished','calls',7)")
        self.db.conn.commit()
        # SCIP local-synthetic symbol with no descriptor chain.
        self._evidence("ev-u1", "run-2", "scip-index", "local 1", "local 2",
                       "references", path="app/main.py")
        report = cross_check(self.db, repo_root=self.test_dir)
        self.assertGreaterEqual(report["totals"]["unresolved_builtin"], 1)
        self.assertGreaterEqual(report["totals"]["unresolved_external"], 1)
        self.assertEqual(report["totals"]["agreements"], 0)

    def test_invalidated_evidence_excluded(self):
        self._evidence(
            "ev-i1", "run-1", "codebase-memory",
            f"{self.mangled}.app.main.build_invoice",
            f"{self.mangled}.core.service.compute_total",
            "call:out", invalidated_at=NOW + 5,
        )
        report = cross_check(self.db, repo_root=self.test_dir)
        self.assertEqual(report["totals"]["agreements"], 0)
        self.assertEqual(report["external_pair_count"], 0)

    def test_provider_filter_restricts_external_side(self):
        self._evidence(
            "ev-f1", "run-2", "scip-index",
            "scip-python python pkg 1.0.0 `app/main.py`/build_invoice().",
            "scip-python python pkg 1.0.0 `core/service.py`/compute_total().",
            "call", path="app/main.py", line_start=6, line_end=6,
        )
        both = cross_check(self.db, repo_root=self.test_dir)
        scip_only = cross_check(self.db, provider="scip-index",
                                repo_root=self.test_dir)
        self.assertEqual(both["totals"]["agreements"], 1)
        self.assertEqual(scip_only["totals"]["agreements"], 1)
        self.assertEqual(scip_only["provider_counts"], {"scip-index": 1})
        cbm_only = cross_check(self.db, provider="codebase-memory",
                               repo_root=self.test_dir)
        self.assertEqual(cbm_only["totals"]["agreements"], 0)
        self.assertEqual(cbm_only["provider_counts"], {})

    def test_counts_and_sample_limit(self):
        for i in range(5):
            self._evidence(
                f"ev-n{i}", "run-1", "codebase-memory",
                f"{self.mangled}.app.main.build_invoice",
                f"{self.mangled}.core.service.compute_total",
                "call:out",
            )
        report = cross_check(self.db, sample_limit=2, repo_root=self.test_dir)
        self.assertEqual(report["totals"]["agreements"], 1)
        self.assertLessEqual(len(report["agreements"]), 2)
        self.assertEqual(report["totals"]["sample_limit"], 2)

    def test_cli_subcommand_wiring(self):
        from sot_graph.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(
            ["providers", "cross-check", "--json", "--provider", "scip-index"]
        )
        self.assertEqual(args.providers_subcommand, "cross-check")
        self.assertEqual(args.provider, "scip-index")
        self.assertTrue(args.json)

    def test_read_only_no_mutation(self):
        self._evidence(
            "ev-ro", "run-1", "codebase-memory",
            f"{self.mangled}.app.main.build_invoice",
            f"{self.mangled}.core.service.compute_total", "call:out",
        )
        before = self.db.conn.total_changes
        cross_check(self.db, repo_root=self.test_dir)
        self.assertEqual(self.db.conn.total_changes, before)


class CrossCheckReceiptTests(unittest.TestCase):
    """SG-203 receipt: snapshot-bound reconciliation decisions."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, ".sot", "xc.db")
        self.db = Database(self.db_path)
        os.makedirs(os.path.join(self.test_dir, "app"), exist_ok=True)
        with open(os.path.join(self.test_dir, "app", "main.py"), "w") as fh:
            fh.write("def build_invoice(items):\n    return sum(items)\n")
        conn = self.db.conn
        conn.execute(
            "INSERT INTO provider_runs (id, provider_name, provider_version, "
            "capability, status, created_at) VALUES (?,?,?,?,?,?)",
            ("run-1", "codebase-memory", "0.10.8", "CALLGRAPH", "ok", NOW),
        )
        conn.executemany(
            "INSERT INTO graph_nodes (id, path, kind, symbol, fqn, label, body,"
            " line_start, line_end, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                ("sym:aaaa:build_invoice", "app/main.py", "function",
                 "build_invoice", "app.main.build_invoice", "l", "b", 1, 2, NOW),
                ("sym:bbbb:helper", "app/main.py", "function",
                 "helper", "app.main.helper", "l", "b", 4, 5, NOW),
            ],
        )
        conn.execute(
            "INSERT INTO graph_edges (path, src, dst, relation, line)"
            " VALUES ('app/main.py','sym:aaaa:build_invoice',"
            "'sym:bbbb:helper','calls',2)")
        conn.commit()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _evidence(self, src, dst, relation, ev_id="ev-1", line_start=None,
                  line_end=None):
        self.db.conn.execute(
            "INSERT INTO provider_evidence (id, run_id, provider_name, path,"
            " src_symbol, dst_symbol, relation, line_start, line_end,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ev_id, "run-1", "codebase-memory", "app/main.py", src, dst,
             relation, line_start, line_end, NOW),
        )
        self.db.conn.commit()

    def test_abstained_without_external_evidence(self):
        # Builtin claims exist but the ledger is empty: a clean bill would
        # overstate — the receipt must abstain with the explicit reason.
        receipt = cross_check_receipt(self.db, self.test_dir)
        self.assertEqual(receipt["kind"], "cross_check")
        self.assertEqual(receipt["schema_version"], "1.7")
        self.assertEqual(receipt["schema_version"], RECEIPT_SCHEMA_VERSION)
        self.assertEqual(receipt["assurance"]["status"], "ABSTAINED")
        self.assertIn("no_external_evidence",
                      receipt["assurance"]["reason_codes"])
        self.assertEqual(receipt["evidence_basis"]["builtin_edges_scanned"], 1)
        self.assertEqual(receipt["evidence_basis"]["external_rows_scanned"], 0)
        self.assertTrue(receipt["digest"])

    def test_conflicted_on_relation_mismatch(self):
        mangled = os.path.realpath(self.test_dir).lstrip("/").replace("/", "-")
        self._evidence(
            f"{mangled}.app.main.build_invoice",
            f"{mangled}.app.main.helper",
            "inherits",
        )
        receipt = cross_check_receipt(self.db, self.test_dir)
        self.assertEqual(receipt["assurance"]["status"], "CONFLICTED")
        self.assertIn("open_conflicts", receipt["assurance"]["reason_codes"])
        self.assertEqual(receipt["evidence_basis"]["external_rows_scanned"], 1)

    def test_agreement_passes_with_evidence_present(self):
        mangled = os.path.realpath(self.test_dir).lstrip("/").replace("/", "-")
        self._evidence(
            f"{mangled}.app.main.build_invoice",
            f"{mangled}.app.main.helper",
            "call:out", line_start=2, line_end=2,
        )
        receipt = cross_check_receipt(self.db, self.test_dir)
        self.assertEqual(receipt["assurance"]["status"],
                         "ASSURED_WITHIN_SCOPE")
        self.assertEqual(receipt["report"]["totals"]["agreements"], 1)

    def test_cli_receipt_flag_wiring(self):
        from sot_graph.cli import build_parser
        args = build_parser().parse_args(["providers", "cross-check", "--receipt"])
        self.assertTrue(args.receipt)


if __name__ == "__main__":
    unittest.main()
