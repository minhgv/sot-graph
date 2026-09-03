"""
test_dynamic_gap_corpus.py — Benchmark evaluating Dynamic Gap Handling & Containment in SOT-Graph.

Tests:
1. Python dynamic dispatch (getattr, eval, reflection).
2. TypeScript dynamic imports & loose callbacks.
3. Java interface dispatch / reflection.
4. Go interface dispatch / type switches.
5. Rust trait object dynamic dispatch (dyn Trait).
6. Fail-closed decision state (PARTIAL with dynamic_dispatch_unresolved vs ASSURED_WITHIN_SCOPE when contained).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sot_graph.assurance.coverage import build_scope_manifest
from sot_graph.assurance.receipts import scope_receipt
from sot_graph.assurance.state import AssuranceFacts, decide
from sot_graph.db import Database
from sot_graph.reconciler import Reconciler


def test_dynamic_gap_python():
    """Verify Python dynamic reflection downgrades to PARTIAL with dynamic_dispatch_unresolved."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        py_file = root / "dynamic_service.py"
        py_file.write_text("""
import importlib

def run_handler(name: str, payload: dict):
    mod = importlib.import_module(f"handlers.{name}")
    fn = getattr(mod, "handle")
    return fn(payload)
""", encoding="utf-8")

        db_path = root / ".sot" / "sot.db"
        db = Database(str(db_path))
        try:
            reconciler = Reconciler(db, str(root))
            reconciler.reconcile()

            manifest = build_scope_manifest(db, str(root), ["dynamic_service.py"])
            assert "dynamic_service.py" in manifest.included_files
            assert any("dynamic_reflection" in c for c in manifest.unsupported_constructs)

            receipt = scope_receipt(db, target="run_handler", repo_root=str(root))
            assert receipt["assurance"]["status"] == "PARTIAL"
            assert "dynamic_dispatch_unresolved" in receipt["assurance"]["reason_codes"]
        finally:
            db.close()

def test_dynamic_gap_typescript():
    """Verify TypeScript dynamic import/eval detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        ts_file = root / "dynamic_loader.ts"
        ts_file.write_text("""
export async function loadModule(name: string) {
    const mod = await import(`./plugins/${name}`);
    const res = eval("mod.run()");
    return res;
}
""", encoding="utf-8")

        db_path = root / ".sot" / "sot.db"
        db = Database(str(db_path))
        try:
            reconciler = Reconciler(db, str(root))
            reconciler.reconcile()

            manifest = build_scope_manifest(db, str(root), ["dynamic_loader.ts"])
            assert "dynamic_loader.ts" in manifest.included_files
            assert any("dynamic_eval" in c or "dynamic_import" in c for c in manifest.unsupported_constructs)

            receipt = scope_receipt(db, target="loadModule", repo_root=str(root))
            assert receipt["assurance"]["status"] == "PARTIAL"
            assert "dynamic_dispatch_unresolved" in receipt["assurance"]["reason_codes"]
        finally:
            db.close()

def test_dynamic_gap_java():
    """Verify Java Class.forName / reflection detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        java_file = root / "PluginManager.java"
        java_file.write_text("""
public class PluginManager {
    public static Object loadPlugin(String className) throws Exception {
        Class<?> clazz = Class.forName(className);
        return clazz.getDeclaredMethod("init").invoke(null);
    }
}
""", encoding="utf-8")

        db_path = root / ".sot" / "sot.db"
        db = Database(str(db_path))
        try:
            reconciler = Reconciler(db, str(root))
            reconciler.reconcile()

            manifest = build_scope_manifest(db, str(root), ["PluginManager.java"])
            assert "PluginManager.java" in manifest.included_files
            assert any("dynamic_class_loading" in c or "dynamic_reflection" in c for c in manifest.unsupported_constructs)

            receipt = scope_receipt(db, target="PluginManager.loadPlugin", repo_root=str(root))
            assert receipt["assurance"]["status"] == "PARTIAL"
            assert "dynamic_dispatch_unresolved" in receipt["assurance"]["reason_codes"]
        finally:
            db.close()

def test_dynamic_gap_go():
    """Verify Go type switch / reflect detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        go_file = root / "dispatcher.go"
        go_file.write_text("""
package main

import "fmt"

func dispatch(x interface{}) string {
	switch v := x.(type) {
	case string:
		return fmt.Sprintf("str: %s", v)
	case int:
		return fmt.Sprintf("num: %d", v)
	default:
		return "unknown"
	}
}
""", encoding="utf-8")
        db_path = root / ".sot" / "sot.db"
        db = Database(str(db_path))
        try:
            reconciler = Reconciler(db, str(root))
            reconciler.reconcile()

            manifest = build_scope_manifest(db, str(root), ["dispatcher.go"])
            assert "dispatcher.go" in manifest.included_files
            assert any("dynamic_type_switch" in c for c in manifest.unsupported_constructs)

            receipt = scope_receipt(db, target="dispatch", repo_root=str(root))
            assert receipt["assurance"]["status"] == "PARTIAL"
            assert "dynamic_dispatch_unresolved" in receipt["assurance"]["reason_codes"]
        finally:
            db.close()

def test_dynamic_gap_rust():
    """Verify Rust dynamic trait object (&dyn Trait, Box<dyn Trait>) detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        rs_file = root / "plugin.rs"
        rs_file.write_text("""
pub trait Plugin {
    fn name(&self) -> &str;
}

pub struct PluginRunner {
    pub plugins: Vec<Box<dyn Plugin>>,
}

impl PluginRunner {
    pub fn execute(&self, plugin: &dyn Plugin) {
        println!("{}", plugin.name());
    }
}
""", encoding="utf-8")
        db_path = root / ".sot" / "sot.db"
        db = Database(str(db_path))
        try:
            reconciler = Reconciler(db, str(root))
            reconciler.reconcile()

            manifest = build_scope_manifest(db, str(root), ["plugin.rs"])
            assert "plugin.rs" in manifest.included_files
            assert any("dynamic_trait_object" in c for c in manifest.unsupported_constructs)

            receipt = scope_receipt(db, target="PluginRunner.execute", repo_root=str(root))
            assert receipt["assurance"]["status"] == "PARTIAL"
            assert "dynamic_dispatch_unresolved" in receipt["assurance"]["reason_codes"]
        finally:
            db.close()
def test_static_negative_control_assured():
    """Verify pure static code without dynamic gaps or parser errors is ASSURED_WITHIN_SCOPE."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        py_file = root / "calculator.py"
        py_file.write_text("""
def add(a: int, b: int) -> int:
    return a + b

def multiply(a: int, b: int) -> int:
    return a * b
""", encoding="utf-8")

        db_path = root / ".sot" / "sot.db"
        db = Database(str(db_path))
        try:
            reconciler = Reconciler(db, str(root))
            reconciler.reconcile()

            manifest = build_scope_manifest(db, str(root), ["calculator.py"])
            assert manifest.unsupported_constructs == []
            assert manifest.parser_error_files == []

            receipt = scope_receipt(db, target="add", repo_root=str(root))
            assert receipt["assurance"]["status"] == "ASSURED_WITHIN_SCOPE"
            assert receipt["assurance"]["reason_codes"] == []
        finally:
            db.close()

def test_state_decision_with_dynamic_dispatch_unresolved():
    """Verify pure state decision downgrades to PARTIAL with dynamic_dispatch_unresolved reason."""
    facts = AssuranceFacts(
        identity_status="UNIQUE",
        snapshot_bound=True,
        dynamic_dispatch_unresolved=True,
    )
    outcome = decide(facts)
    assert outcome["status"] == "PARTIAL"
    assert "dynamic_dispatch_unresolved" in outcome["reason_codes"]
