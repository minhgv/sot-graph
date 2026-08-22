"""Regression tests for the PHP extractor state machine.

The regex-only extractor captured bare class/function names only: no
interfaces, traits or enums, no inheritance edges, no imports, no call
sites, and same-named methods of different classes collapsed into one node.
These tests pin the structural contract of the rewritten extractor.
"""

import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from sot_graph._vendor.graphify.extract import extract_php
from sot_graph.db import Database
from sot_graph.reconciler import Reconciler


PHP_FIXTURE = textwrap.dedent("""\
    <?php

    namespace App\\Foo;

    use App\\Contracts\\BarInterface;
    use App\\Traits\\LogTrait;

    interface PaymentGatewayInterface {
        public function charge($amount): bool;
    }

    trait LogTrait {
        public function log($msg) { echo $msg; }
    }

    enum Status: string {
        case Active = 'active';
    }

    class PaymentGateway implements PaymentGatewayInterface {
        use LogTrait;

        public function charge($amount): bool {
            $this->log("charging");
            return true;
        }
    }
""")


def node_map(result):
    return {n["id"]: n for n in result["nodes"] if n["id"] != "file"}


class PhpExtractorUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sot_php_unit_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = Path(self.tmp) / "edge.php"
        self.path.write_text(PHP_FIXTURE, encoding="utf-8")

    def test_symbols_and_kinds(self):
        nodes = node_map(extract_php(self.path))
        self.assertEqual(nodes["PaymentGatewayInterface"]["kind"], "interface")
        self.assertEqual(nodes["LogTrait"]["kind"], "trait")
        self.assertEqual(nodes["Status"]["kind"], "enum")
        self.assertEqual(nodes["PaymentGateway"]["kind"], "class")
        self.assertEqual(nodes["PaymentGateway.charge"]["kind"], "method")

    def test_implements_and_trait_use_edges(self):
        edges = extract_php(self.path)["edges"]
        rel = {(e["source"], e["relation"], e["target"]) for e in edges}
        self.assertIn(
            ("PaymentGateway", "implements", "PaymentGatewayInterface"), rel)
        self.assertIn(("PaymentGateway", "uses", "LogTrait"), rel)

    def test_use_imports_emit_short_symbol_targets(self):
        edges = extract_php(self.path)["edges"]
        imports = {e["target"] for e in edges if e["relation"] == "imports"}
        self.assertEqual(imports, {"BarInterface", "LogTrait"})

    def test_this_call_edge_has_self_receiver(self):
        edges = extract_php(self.path)["edges"]
        calls = [e for e in edges
                 if e["relation"] == "calls" and e["target"] == "log"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["source"], "PaymentGateway.charge")
        self.assertEqual(calls[0]["receiver"], "self")

    def test_same_named_methods_do_not_collide(self):
        self.path.write_text(textwrap.dedent("""\
            <?php
            class A { public function handle() { return 1; } }
            class B { public function handle() { return 2; } }
        """), encoding="utf-8")
        nodes = node_map(extract_php(self.path))
        self.assertIn("A.handle", nodes)
        self.assertIn("B.handle", nodes)

    def test_static_and_new_calls(self):
        self.path.write_text(textwrap.dedent("""\
            <?php
            class Svc {
                public function go() {
                    $r = Registry::find('x');
                    return new PaymentGateway();
                }
            }
        """), encoding="utf-8")
        edges = extract_php(self.path)["edges"]
        rel = {(e["source"], e["relation"], e["target"], e.get("receiver")) for e in edges}
        self.assertIn(("Svc.go", "calls", "Registry.find", "Registry"), rel)
        self.assertIn(("Svc.go", "calls", "PaymentGateway", None), rel)

    def test_extends_and_multiline_header(self):
        self.path.write_text(textwrap.dedent("""\
            <?php
            abstract class BaseRepo
                implements Arrayable, Jsonable
            {
                public function all() { return []; }
            }
        """), encoding="utf-8")
        edges = extract_php(self.path)["edges"]
        rel = {(e["source"], e["relation"], e["target"]) for e in edges}
        self.assertIn(("BaseRepo", "implements", "Arrayable"), rel)
        self.assertIn(("BaseRepo", "implements", "Jsonable"), rel)

    def test_comments_do_not_produce_symbols(self):
        self.path.write_text(textwrap.dedent("""\
            <?php
            // class Ghost { }
            /* function phantom() {} */
            class Real { public function ok() { return 1; } }
        """), encoding="utf-8")
        nodes = node_map(extract_php(self.path))
        self.assertNotIn("Ghost", nodes)
        self.assertNotIn("phantom", nodes)
        self.assertIn("Real.ok", nodes)

    def test_closures_and_callables_are_ignored(self):
        self.path.write_text(textwrap.dedent("""\
            <?php
            class W {
                public function run($arr) {
                    usort($arr, function ($a, $b) { return 0; });
                    $f = strlen(...);
                    return $arr;
                }
            }
        """), encoding="utf-8")
        nodes = node_map(extract_php(self.path))
        self.assertEqual(
            [k for k in nodes if k.startswith("W.")], ["W.run"])

    def test_laravel_command_shape_stays_in_scope(self):
        # Multi-line class header ('{' on its own line), string braces in a
        # property, and parent::__construct() delegation: the constructor
        # must stay a qualified method and the parent call must not resolve
        # into a self-loop against a bare '__construct' node.
        self.path.write_text(textwrap.dedent("""\
            <?php
            namespace Modules\\Admin\\Console;

            class DailyReport extends Command
            {
                protected $signature = 'report:daily {year?} {month?}';

                public function __construct()
                {
                    parent::__construct();
                }

                public function handle()
                {
                    $this->info('done');
                }
            }
        """), encoding="utf-8")
        result = extract_php(self.path)
        nodes = node_map(result)
        self.assertIn("DailyReport.__construct", nodes)
        self.assertIn("DailyReport.handle", nodes)
        self.assertNotIn("__construct", nodes)

        self_loops = [
            e for e in result["edges"]
            if e["relation"] == "calls" and e["source"] == e["target"]
        ]
        self.assertEqual(self_loops, [], "parent::__construct must not self-loop")
        parent_calls = [
            e for e in result["edges"]
            if e["relation"] == "calls" and e["target"] == "__construct"
        ]
        self.assertEqual(len(parent_calls), 1)
        self.assertEqual(parent_calls[0]["source"], "DailyReport.__construct")
        self.assertEqual(parent_calls[0]["receiver"], "super")
        this_calls = [
            e for e in result["edges"]
            if e["relation"] == "calls" and e["target"] == "info"
        ]
        self.assertEqual(this_calls[0]["source"], "DailyReport.handle")


class PhpEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sot_php_e2e_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.db = Database(str(self.root / ".sot" / "sot.db"))
        self.addCleanup(self.db.close)

    def write(self, rel_path, content):
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)

    def test_implementations_and_usages_surface_php_relations(self):
        gateway = self.write("app/Gateway.php", PHP_FIXTURE)
        controller = self.write(
            "app/Controller.php",
            textwrap.dedent("""\
                <?php
                namespace App;

                use App\\Foo\\PaymentGateway;

                class Controller {
                    public function pay() {
                        $gw = new PaymentGateway();
                        return $gw->charge(100);
                    }
                }
            """),
        )
        Reconciler(self.db, str(self.root)).reconcile()

        # implements edge resolved within the same file
        iface_row = self.db.conn.execute(
            "SELECT id FROM graph_nodes WHERE symbol = 'PaymentGatewayInterface'"
        ).fetchone()
        self.assertIsNotNone(iface_row, "interface node must exist")
        impl = self.db.inheritance_edges(iface_row[0], "PaymentGatewayInterface")
        self.assertTrue(
            any(e["label"].startswith("class PaymentGateway") for e in impl["derived"]),
            f"PaymentGateway must implement the interface: {impl}")

        # new PaymentGateway() resolves across files via the import's short name
        callers = self.db.conn.execute(
            "SELECT n1.path FROM graph_edges e "
            "JOIN graph_nodes n1 ON e.src = n1.id "
            "JOIN graph_nodes n2 ON e.dst = n2.id "
            "WHERE e.relation = 'calls' AND n2.symbol = 'PaymentGateway'"
        ).fetchall()
        self.assertEqual([c[0] for c in callers], [controller])

        # $this->log() stays a pending risk (trait indirection), never a
        # wrongly confirmed edge
        wrong = self.db.conn.execute(
            "SELECT COUNT(*) FROM graph_edges e "
            "JOIN graph_nodes n2 ON e.dst = n2.id "
            "WHERE e.relation = 'calls' AND n2.symbol = 'LogTrait.log' "
            "AND n2.path = ?", (gateway,)).fetchone()[0]
        self.assertEqual(wrong, 0)


if __name__ == "__main__":
    unittest.main()
