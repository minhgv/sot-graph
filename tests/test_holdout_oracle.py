"""test_holdout_oracle.py — SG-204 holdout oracle guard.

Three contracts under test:

1. Independence — ``sot_graph.holdout.evaluator`` is stdlib-only and
   never imports the code under evaluation; enforced by parsing the
   module's own import statements, not by trusting the docstring.
2. Manifest shape — ``benchmarks/holdout/manifest.json`` pins 10–20
   repos with full 40-hex SHAs, licenses, seeds and rename-aware
   ``diff_task`` pairs.
3. Oracle behavior on a planted corpus — overloads skipped, only
   function-level callers attributed, from-import resolution unique,
   ambiguous stems unresolved, top-level deltas exact, abstention
   probes prefix-safe against every real token, sampling deterministic.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from sot_graph.holdout import evaluator  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Independence — the oracle must not import the system under test
# ---------------------------------------------------------------------------


def test_evaluator_imports_stdlib_only():
    source = (_REPO / "src" / "sot_graph" / "holdout" / "evaluator.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    stdlib = set(sys.stdlib_module_names)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in ("sot_graph", "src"), (
                    f"oracle imports the system under test: {alias.name}"
                )
                assert root in stdlib, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root != "sot_graph", "oracle imports the system under test"
            assert root in stdlib, f"non-stdlib import-from: {node.module}"


# ---------------------------------------------------------------------------
# 2. Manifest shape
# ---------------------------------------------------------------------------


def test_manifest_pins_measurable_holdout():
    manifest = json.loads(
        (_REPO / "benchmarks" / "holdout" / "manifest.json").read_text(encoding="utf-8")
    )
    repos = manifest["repos"]
    assert 10 <= len(repos) <= 20
    hex40 = re.compile(r"^[0-9a-f]{40}$")
    for repo in repos:
        for key in ("name", "url", "commit", "license", "language", "seed"):
            assert repo.get(key), f"{repo.get('name')} missing {key}"
        assert hex40.match(repo["commit"])
        assert repo["language"] == "python"
        assert isinstance(repo["seed"], int)
        task = repo["diff_task"]
        assert hex40.match(task["base"]) and hex40.match(task["head"])
        assert task["base"] != task["head"]
        assert task.get("subject") and task.get("date")
        assert task.get("changed_files"), "diff task must touch files"
        assert any(f.endswith(".py") for f in task["changed_files"]), (
            "diff task must touch python sources or the suite is vacuous"
        )
    names = [r["name"] for r in repos]
    assert len(set(names)) == len(names)


# ---------------------------------------------------------------------------
# 3. Oracle behavior on a planted corpus
# ---------------------------------------------------------------------------

CORE = """\
from typing import overload


def util(value):
    return value


@overload
def parse(raw: str) -> int: ...


@overload
def parse(raw: bytes) -> bytes: ...


def parse(raw):
    return raw


class Engine:
    attr = util(1)          # class-body call: no function caller

    def run(self):
        return util(2)      # method caller: edge


def outer():
    def inner():
        return util(9)      # nested function: caller is OUTER

    return inner


util(3)                     # module-level call: no function caller

if t.TYPE_CHECKING:
    class Phantom: ...      # typing-only: outside the engine's model
"""

EXTRA = """\
from .core import util


def caller():
    return util(4)          # from-import resolved, unique module stem
"""

TWIN = "def twin():\n    return 1\n"
AMBIG = "from twin import twin\n\n\ndef go():\n    return twin()\n"

TEST_SRC = "from pkg.core import Engine\n\n\ndef test_engine():\n    assert Engine().run() is not None\n"


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(CORE, encoding="utf-8")
    (pkg / "extra.py").write_text(EXTRA, encoding="utf-8")
    # two modules share the stem "twin" -> from twin import ... stays
    # unresolved (the engine's module-stem keying cannot disambiguate)
    (tmp_path / "twin.py").write_text(TWIN, encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "twin.py").write_text(TWIN, encoding="utf-8")
    (tmp_path / "ambig.py").write_text(AMBIG, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_core.py").write_text(TEST_SRC, encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.py").write_text("def hidden():\n    return 0\n", encoding="utf-8")
    (tmp_path / "setup.py").write_text(
        "def also_hidden():\n    return 0\n", encoding="utf-8"
    )
    return tmp_path


def _names(defs):
    return sorted(d.name for d in defs)


def test_extract_definitions_scope_and_overloads(corpus):
    defs, failures = evaluator.extract_definitions(corpus, evaluator.OracleConfig())
    assert failures == []
    names = _names(defs)
    assert names.count("parse") == 1, "overload stubs must not be counted"
    assert "util" in names and "Engine" in names and "run" in names
    assert "hidden" not in names, "docs/ prefix must be excluded"
    assert "also_hidden" not in names, "setup.py must be excluded"
    assert "Phantom" not in names, "TYPE_CHECKING classes are out of model"
    assert "inner" not in names, "function-local defs are out of model"
    assert "outer" in names
    core_lines = sorted(
        d.line for d in defs if d.path == "pkg/core.py" and d.name == "parse"
    )
    assert core_lines == [16], "the real implementation line is kept"


def test_resolve_direct_calls_attributes_innermost_caller(corpus):
    defs, _ = evaluator.extract_definitions(corpus, evaluator.OracleConfig())
    edges, unresolved = evaluator.resolve_direct_calls(
        corpus, defs, evaluator.OracleConfig()
    )
    callers = {(e.caller_path, e.caller_name) for e in edges if e.callee_name == "util"}
    assert ("pkg/extra.py", "caller") in callers, "from-import edge"
    assert ("pkg/core.py", "Engine.run") in callers, "method caller edge"
    assert ("pkg/core.py", "outer.inner") in callers, (
        "a call inside a nested function attributes to the nested def — "
        "the engine indexes nested defs as qualified nodes"
    )
    assert ("pkg/core.py", "outer") not in callers
    assert not any(name == "" for _, name in callers), "no bare module caller"
    assert ("pkg/core.py", "Engine") not in callers, "class-body call excluded"
    assert unresolved >= 1, "ambiguous twin stem must stay unresolved"
    twin_edges = [e for e in edges if e.callee_name == "twin"]
    assert twin_edges == [], "ambiguous callee must produce no edge"


def test_all_definition_names_is_the_full_validation_universe(corpus):
    names = evaluator.all_definition_names(corpus, evaluator.OracleConfig())
    assert ("pkg/core.py", "Phantom") in names, "TYPE_CHECKING counted"
    assert ("pkg/core.py", "inner") in names, "function-local counted"
    assert ("pkg/core.py", "parse") in names, "overload stubs counted"
    assert ("pkg/core.py", "util") in names
    assert ("docs/guide.py", "hidden") not in names, "excluded prefixes"
    assert ("setup.py", "also_hidden") not in names, "excluded names"


def test_top_level_delta_detects_add_remove_rename():
    base = "def alpha():\n    return 1\n\n\nclass Beta:\n    pass\n"
    added = base + "\n\ndef gamma():\n    return 3\n"
    assert evaluator.top_level_delta(added, base) == {"gamma"}
    assert evaluator.top_level_delta(base, added) == {"gamma"}, "symmetric"
    renamed = base.replace("alpha", "alpha2")
    assert evaluator.top_level_delta(renamed, base) == {"alpha", "alpha2"}
    assert evaluator.top_level_delta(base, base) == set()


def test_referenced_names_bare_only_and_is_test_path():
    names = evaluator.referenced_names("obj.method(Engine())")
    assert "Engine" in names and "obj" in names
    assert "method" not in names, "attribute names are not bare references"
    assert evaluator.referenced_names("\x00def broken(")  # regex fallback
    assert evaluator.is_test_path("tests/test_core.py")
    assert evaluator.is_test_path("tests/core_test.py")
    assert not evaluator.is_test_path("src/sot_graph/core.py")


def test_mutated_queries_are_prefix_safe(corpus):
    defs, _ = evaluator.extract_definitions(corpus, evaluator.OracleConfig())
    probes = evaluator.mutated_queries(defs, seed=7, limit=8)
    assert len(probes) == 8
    real_tokens: set[str] = set()
    for d in defs:
        real_tokens.update(t for t in re.split(r"[^A-Za-z0-9]+", d.name) if t)
    for probe in probes:
        assert probe not in real_tokens
        assert not any(t.startswith(probe) for t in real_tokens), (
            f"probe {probe!r} would prefix-match a real token"
        )


def test_sampling_is_deterministic(corpus):
    defs, _ = evaluator.extract_definitions(corpus, evaluator.OracleConfig())
    a = evaluator.sample_definitions(defs, seed=204001, limit=3)
    b = evaluator.sample_definitions(defs, seed=204001, limit=3)
    assert [(d.path, d.name, d.line) for d in a] == [
        (d.path, d.name, d.line) for d in b
    ]
    assert len(a) == 3
