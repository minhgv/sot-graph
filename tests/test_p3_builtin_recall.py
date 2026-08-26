"""P3.3b — builtin recall mechanisms (AST-anchored receiver typing).

Locks the mechanisms that lifted the oracle scorecard from F1 81.6 to
99.5 (Go 40.9->100 recall, TS 60.4->99.5, Rust 2.3->97.0):

- module_form_of_import: Go slash packages + TS relative imports become
  the dotted project-module form the pending resolver compares against
  (previously Go imports were pruned as "external").
- Receiver typing: TS `const v = new C()`, TS typed params, Go receiver/
  value params + `r := &T{}`, Rust `let r = T{...}`/unit + `r: &T` params
  qualify `v.m()` to the class-scoped 'C.m' of the CONSTRUCTED type —
  before the bare-name match, so a module-level same-name function can
  never win.
- Canonical method identity: Rust `impl T { fn m }` -> 'T.m'.
- TS constructor edges + `this.m()` + alias imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from sot_graph.extractor import parse_file_graph  # noqa: E402
from sot_graph.ts_extract import module_form_of_import  # noqa: E402


def _parse(tmp_path: Path, rel: str) -> dict:
    return parse_file_graph(str(tmp_path / rel), str(tmp_path))


def _calls_of(result: dict) -> set:
    return {
        (e["src"].rsplit(":", 1)[-1], e["dst"].rsplit(":", 1)[-1])
        for e in result["edges"]
        if e["relation"] == "calls"
    }


def _write(tmp_path: Path, rel: str, content: str) -> Path:
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


class TestModuleFormOfImport:
    def test_go_slash_package_becomes_dotted(self):
        assert module_form_of_import("go_pkg/storage", "go", "") == "go_pkg.storage"

    def test_ts_relative_up_one_level(self):
        got = module_form_of_import("../models/order", "typescript", "ts_pkg.services")
        assert got == "ts_pkg.models.order"

    def test_ts_relative_same_dir(self):
        assert module_form_of_import("./util", "typescript", "ts_pkg.services") == "ts_pkg.services.util"

    def test_empty_returns_none(self):
        assert module_form_of_import("", "go", "x") is None


class TestTsReceiverTyping:
    def test_new_inference_beats_module_level_same_name(self, tmp_path):
        f = _write(tmp_path, "svc.ts", """\
export function process(o: unknown): string { return ""; }
export class Stage {
    process(o: unknown): string { return "stage"; }
}
export function runStage(o: unknown): string {
    const s = new Stage();
    return s.process(o);
}
""")
        calls = _calls_of(_parse(tmp_path, "svc.ts"))
        assert ("runStage", "Stage.process") in calls
        # the module-level same-name function must NOT be the target
        assert ("runStage", "process") not in calls

    def test_this_call_targets_own_class_method(self, tmp_path):
        _write(tmp_path, "inner.ts", """\
export class Svc {
    check(x: number): boolean { return x > 0; }
    run(x: number): boolean { return this.check(x); }
}
""")
        calls = _calls_of(_parse(tmp_path, "inner.ts"))
        assert ("Svc.run", "Svc.check") in calls

    def test_constructor_edge_to_class(self, tmp_path):
        _write(tmp_path, "ctor.ts", """\
export class Box {}
export function make(): Box { return new Box(); }
""")
        calls = _calls_of(_parse(tmp_path, "ctor.ts"))
        assert ("make", "Box") in calls

    def test_alias_import_retargets_to_original_name(self, tmp_path):
        _write(tmp_path, "alias.ts", """\
import { validateOrder as verify } from "../models/order";
export function check(o: unknown): boolean { return verify(o); }
""")
        got = _parse(tmp_path, "alias.ts")
        aliased = [
            p for p in got["pending"]
            if p.get("alias_of") == "verify"
        ]
        assert aliased and all(p["dst_symbol"] == "validateOrder" for p in aliased)


class TestGoReceiverTyping:
    def test_package_qualified_and_typed_receivers(self, tmp_path):
        _write(tmp_path, "go_pkg/storage/storage.go", """\
package storage

func ValidateKey(k string) bool { return len(k) > 0 }
""")
        _write(tmp_path, "go_pkg/workers/worker.go", """\
package workers

import "go_pkg/storage"

type Worker struct{ ID int }

func (w *Worker) Check(k string) bool { return storage.ValidateKey(k) }

func Run(r string) string {
    w := &Worker{ID: 1}
    if w.Check(r) {
        return "ok"
    }
    return ""
}
""")
        result = _parse(tmp_path, "go_pkg/workers/worker.go")
        calls = {
            (e["src"].rsplit(":", 1)[-1], e["dst"].rsplit(":", 1)[-1])
            for e in result["edges"] if e["relation"] == "calls"
        }
        assert ("Run", "Worker.Check") in calls  # typed receiver resolves intra-file
        pending = {
            (p["src"].rsplit(":", 1)[-1], p["dst_symbol"], p.get("import_source"))
            for p in result["pending"]
        }
        # cross-file package call rides as pending with DOTTED import source
        assert ("Worker.Check", "ValidateKey", "go_pkg.storage") in pending

    def test_same_name_methods_disambiguated_by_param_types(self, tmp_path):
        _write(tmp_path, "samename.go", """\
package samename

type Doc struct{ ID int }
type Blob struct{ ID int }

func (d *Doc) Save() bool  { return d.ID > 0 }
func (b *Blob) Save() bool { return b.ID > 0 }

func SaveAll(d *Doc, bl *Blob) bool { return d.Save() && bl.Save() }
""")
        calls = _calls_of(_parse(tmp_path, "samename.go"))
        assert ("SaveAll", "Doc.Save") in calls
        assert ("SaveAll", "Blob.Save") in calls
        assert ("SaveAll", "Save") not in calls


class TestRustImplIdentity:
    def test_impl_methods_are_type_qualified(self, tmp_path):
        _write(tmp_path, "samename.rs", """\
pub struct Doc;
pub struct Blob;

impl Doc { pub fn save(&self) -> bool { true } }
impl Blob { pub fn save(&self) -> bool { true } }

pub fn save_all(d: &Doc, b: &Blob) -> bool {
    let local = Doc;
    d.save() && b.save() && local.save()
}
""")
        calls = _calls_of(_parse(tmp_path, "samename.rs"))
        assert ("save_all", "Doc.save") in calls
        assert ("save_all", "Blob.save") in calls
        assert ("save_all", "save") not in calls

    def test_let_struct_literal_typing(self, tmp_path):
        _write(tmp_path, "engine.rs", """\
pub struct Engine;

impl Engine { pub fn process(&self) -> u32 { 1 } }

pub fn run() -> u32 {
    let e = Engine { marker: 0 };
    e.process()
}
""")
        calls = _calls_of(_parse(tmp_path, "engine.rs"))
        assert ("run", "Engine.process") in calls
