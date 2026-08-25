"""tests/test_truthfulness.py — P0 built-in truthfulness contract.

Guarantees under test:
1. Regex token coverage alone can NEVER yield confirmed/exact evidence,
   no matter how high the coverage (verifier downgrades to heuristic).
2. A real AST span verification (Python ``ast`` module) keeps full
   EXACT_SPAN / confirmed privileges.
3. Missing tree-sitter grammars surface as ParserOutcome.PARSER_UNAVAILABLE
   instead of silently pretending an AST existed.
4. Ghost symbols living only inside comments/strings are never confirmed.
"""

from __future__ import annotations

import os

import pytest

from sot_graph import ts_extract
from sot_graph.db import Database
from sot_graph.evidence import FreshnessStatus, RelevanceType
from sot_graph.extractor import parse_file_graph
from sot_graph.parser_outcome import ParserOutcome, build_extractor_metadata
from sot_graph.reconciler import Reconciler
from sot_graph.verifier import TrustVerifier


@pytest.fixture
def workspace(tmp_path):
    db = Database(str(tmp_path / ".sot" / "sot.db"))
    yield tmp_path, db
    db.close()


def _candidate(path, symbol, line=None):
    return {
        "id": f"{path}#{symbol}",
        "path": str(path),
        "symbol": symbol,
        "kind": "function",
        "line_start": line,
    }


def test_regex_token_coverage_only_is_never_confirmed(workspace):
    """(a) Symbol matched only by regex declaration/token coverage -> heuristic."""
    tmp_path, db = workspace
    go_file = tmp_path / "scoring.go"
    go_file.write_text(
        "package scoring\n\n"
        "func CalculateScore(points int) int {\n"
        "\treturn points * 2\n"
        "}\n",
        encoding="utf-8",
    )
    Reconciler(db, str(tmp_path)).reconcile(paths=[str(go_file)], workers=1)

    ev = TrustVerifier.verify_evidence(
        _candidate(go_file, "CalculateScore", line=3),
        {"CalculateScore"},
        str(tmp_path),
        db=db,
    )

    assert ev.freshness == FreshnessStatus.FRESH
    # No tree-sitter involved in the verifier: regex evidence must stay heuristic.
    assert ev.relevance not in (RelevanceType.EXACT_SPAN, RelevanceType.EXACT_SYMBOL)
    assert ev.provenance.startswith("regex_decl:")
    assert ev.details["confirmed"] is False
    assert ev.details["source_span_verified"] is False
    assert ev.confidence < 0.5
    assert ev.to_legacy_verdict() != "STRONG"


def test_high_regex_coverage_still_not_confirmed(workspace):
    """(a-cont) Even 100% lexical coverage without a declaration stays heuristic."""
    tmp_path, db = workspace
    txt = tmp_path / "notes.js"
    txt.write_text(
        "// CalculateScore is mentioned here and there.\n"
        "const payload = { name: 'CalculateScore' };\n",
        encoding="utf-8",
    )
    Reconciler(db, str(tmp_path)).reconcile(paths=[str(txt)], workers=1)

    ev = TrustVerifier.verify_evidence(
        _candidate(txt, "CalculateScore", line=2),
        {"calculatescore"},
        str(tmp_path),
        db=db,
    )
    assert ev.coverage == 1.0
    assert ev.relevance not in (RelevanceType.EXACT_SPAN, RelevanceType.EXACT_SYMBOL)
    assert ev.details["confirmed"] is False
    assert ev.confidence < 0.5


def test_ast_span_verified_keeps_confirmed(workspace):
    """(b) Python AST span verification retains EXACT_SPAN + confirmed."""
    tmp_path, db = workspace
    py_file = tmp_path / "auth.py"
    py_file.write_text(
        "# sample\n\ndef calculate_metric(a: int) -> int:\n    return a * 3\n",
        encoding="utf-8",
    )
    Reconciler(db, str(tmp_path)).reconcile(paths=[str(py_file)], workers=1)

    res = TrustVerifier.verify_hit(
        db,
        _candidate(py_file, "calculate_metric", line=3),
        {"calculate_metric"},
        str(tmp_path),
    )
    ev = res.evidence
    assert res[0] == "STRONG"
    assert ev.freshness == FreshnessStatus.FRESH
    assert ev.relevance == RelevanceType.EXACT_SPAN
    assert ev.provenance == "ast_visitor:exact_span"
    assert ev.details["source_span_verified"] is True
    assert ev.details["confirmed"] is True
    assert ev.details["parser_outcome"] == ParserOutcome.COMPLETE.value
    assert ev.confidence >= 0.95


def test_missing_tree_sitter_grammar_reports_unavailable(tmp_path, monkeypatch):
    """(c) Grammar import failure -> ParserOutcome.PARSER_UNAVAILABLE, not silence."""
    target = tmp_path / "ghost_lang.txt"
    target.write_text("nothing\n", encoding="utf-8")

    monkeypatch.setitem(
        ts_extract.CONFIGS,
        "ghostlang",
        {"module": "sot_graph._definitely_not_installed_grammar"},
    )
    res = ts_extract.extract_ts(target, "ghostlang")
    assert res["parser_outcome"] == ParserOutcome.PARSER_UNAVAILABLE.value
    assert res["error"]
    assert "definitely_not_installed_grammar" in res["fallback_reason"]

    # Unsupported languages must be equally honest.
    res2 = ts_extract.extract_ts(target, "neverheardof")
    assert res2["parser_outcome"] == ParserOutcome.PARSER_UNAVAILABLE.value


def test_ghost_symbol_in_comment_or_string_never_confirmed(workspace):
    """(d) Ghost symbols living only in comments/strings cannot be confirmed."""
    tmp_path, db = workspace

    comment_only = tmp_path / "legacy.py"
    comment_only.write_text(
        "# def processPayment(amount): ...\n"
        "def other():\n    return 1\n",
        encoding="utf-8",
    )
    Reconciler(db, str(tmp_path)).reconcile(paths=[str(comment_only)], workers=1)
    ev_c = TrustVerifier.verify_evidence(
        _candidate(comment_only, "processPayment", line=1),
        {"processPayment"},
        str(tmp_path),
        db=db,
    )
    assert ev_c.relevance not in (RelevanceType.EXACT_SPAN, RelevanceType.EXACT_SYMBOL)
    assert ev_c.details["confirmed"] is False
    assert ev_c.to_legacy_verdict() != "STRONG"

    string_only = tmp_path / "messages.py"
    string_only.write_text(
        'TEMPLATE = "call processPayment(amount) now"\n'
        "def other():\n    return 2\n",
        encoding="utf-8",
    )
    Reconciler(db, str(tmp_path)).reconcile(paths=[str(string_only)], workers=1)
    ev_s = TrustVerifier.verify_evidence(
        _candidate(string_only, "processPayment", line=1),
        {"processPayment"},
        str(tmp_path),
        db=db,
    )
    assert ev_s.relevance not in (RelevanceType.EXACT_SPAN, RelevanceType.EXACT_SYMBOL)
    assert ev_s.details["confirmed"] is False
    assert ev_s.to_legacy_verdict() != "STRONG"


def test_python_syntax_error_reports_parse_error(workspace):
    """A real parse failure is surfaced as PARSE_ERROR, never as exact."""
    tmp_path, _ = workspace
    broken = tmp_path / "broken.py"
    broken.write_text("def oops(:\n", encoding="utf-8")
    relevance, prov, ast_verified, outcome = TrustVerifier._verify_ast_declaration(
        str(broken), "oops", 1, broken.read_text(encoding="utf-8"), None, 0.5
    )
    assert outcome == ParserOutcome.PARSE_ERROR.value
    assert ast_verified is False
    assert relevance not in (RelevanceType.EXACT_SPAN, RelevanceType.EXACT_SYMBOL)


def test_regex_fallback_annotates_partial_ast(tmp_path, monkeypatch):
    """Regex fallback results are stamped PARTIAL_AST with a fallback reason."""
    from sot_graph._vendor.graphify import extract as gx

    def _boom(path, language):
        raise RuntimeError("simulated grammar outage")

    monkeypatch.setattr(ts_extract, "extract_ts", _boom)
    go_file = tmp_path / "svc.go"
    go_file.write_text("package svc\n\nfunc Run() {}\n", encoding="utf-8")

    res = gx.extract_go(go_file)
    assert res["parser_outcome"] == ParserOutcome.PARTIAL_AST.value
    assert res["extractor"] == "core-ast"
    assert res["fallback_reason"]
    assert any(n.get("id") == "Run" for n in res.get("nodes", []))


def test_extract_ts_complete_and_valid_empty():
    """With a grammar installed: real code -> COMPLETE, symbol-free code -> VALID_EMPTY."""
    import tempfile

    available = ts_extract.available_languages()
    if not available.get("go"):
        pytest.skip("tree-sitter-go grammar not installed")

    with tempfile.TemporaryDirectory() as td:
        real = os.path.join(td, "real.go")
        with open(real, "w", encoding="utf-8") as f:
            f.write("package main\n\nfunc RunJob() {}\n")
        res = ts_extract.extract_ts(real, "go")
        assert res["parser_outcome"] == ParserOutcome.COMPLETE.value
        assert res["fallback_reason"] is None
        assert res["nodes"]

        empty = os.path.join(td, "empty.go")
        with open(empty, "w", encoding="utf-8") as f:
            f.write("package main\n")
        res_empty = ts_extract.extract_ts(empty, "go")
        assert res_empty["parser_outcome"] == ParserOutcome.VALID_EMPTY.value
        assert res_empty["nodes"] == [] and res_empty["edges"] == []
        assert res_empty["error"] is None


def test_parse_file_graph_carries_extractor_metadata(tmp_path):
    """parse_file_graph propagates truthful provenance for downstream storage."""
    go_file = tmp_path / "app.go"
    go_file.write_text("package app\n\nfunc Boot() {}\n", encoding="utf-8")
    res = parse_file_graph(str(go_file), str(tmp_path))

    assert res["parser_outcome"] in (
        ParserOutcome.COMPLETE.value,
        ParserOutcome.PARTIAL_AST.value,
    )
    meta = res["extractor_metadata"]
    assert meta["parser_outcome"] == res["parser_outcome"]
    assert meta["extractor"] in ("tree-sitter-ast", "core-ast")
    assert isinstance(meta["extractor_version"], str) and meta["extractor_version"]
    if res["parser_outcome"] == ParserOutcome.PARTIAL_AST.value:
        assert meta["fallback_reason"]

    # Non-code file: extraction error branch stamps PARSE_ERROR provenance.
    bad = tmp_path / "broken.py"
    bad.write_text("def oops(:\n", encoding="utf-8")
    res_bad = parse_file_graph(str(bad), str(tmp_path))
    assert res_bad["parser_outcome"] == ParserOutcome.PARSE_ERROR.value
    assert res_bad["extractor_metadata"]["parser_outcome"] == "PARSE_ERROR"


def test_build_extractor_metadata_shape():
    meta = build_extractor_metadata(
        "tree-sitter-ast", ParserOutcome.PARTIAL_AST, fallback_reason="no grammar"
    )
    assert meta == {
        "extractor": "tree-sitter-ast",
        "extractor_version": build_extractor_metadata(
            "x", ParserOutcome.COMPLETE
        )["extractor_version"],
        "parser_outcome": "PARTIAL_AST",
        "fallback_reason": "no grammar",
    }
