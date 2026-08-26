"""P4.1 — canonical symbol identity tuple (assurance.identity).

Locks the identity contract: the FULL tuple (repo, normalized path,
language, kind, qualified name, span, provider symbol id) is the join
key — short names never dedup, unknown stays unknown, provider ids are
namespaced so they never cross-join.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sot_graph.assurance.identity import (  # noqa: E402
    Span,
    SymbolIdentity,
    dedup_by_identity,
    from_graph_row,
    from_provider_symbol,
    from_subject,
    identity_hash,
    identity_key,
    normalize_repo_path,
)
def _ident(**kw) -> SymbolIdentity:
    base: dict[str, object] = dict(
        repo_id="repo",
        path="src/app.py",
        language="python",
        kind="function",
        qualified_name="run",
        span=Span(10, 12),
    )
    base.update(kw)
    return SymbolIdentity(**base)  # type: ignore[arg-type]


class TestIdentityKey:
    def test_same_tuple_same_key_and_hash(self):
        a, b = _ident(), _ident()
        assert identity_key(a) == identity_key(b)
        assert identity_hash(a) == identity_hash(b)

    def test_different_path_is_different_identity(self):
        # THE rule: same short name, different file -> two identities.
        assert identity_key(_ident()) != identity_key(_ident(path="src/other.py"))

    def test_different_span_is_different_identity(self):
        assert identity_key(_ident()) != identity_key(_ident(span=Span(11, 12)))

    def test_unknown_span_never_equals_known(self):
        assert identity_key(_ident(span=None)) != identity_key(_ident())

    def test_different_repo_is_different_identity(self):
        assert identity_key(_ident()) != identity_key(_ident(repo_id="repo2"))

    def test_different_language_or_kind_is_different(self):
        assert identity_key(_ident()) != identity_key(_ident(language="unknown"))
        assert identity_key(_ident()) != identity_key(_ident(kind="class"))

    def test_provider_symbol_id_participates(self):
        assert identity_key(_ident()) != identity_key(_ident(provider_symbol_id="scip:x"))


class TestDedup:
    def test_short_name_collision_survives(self):
        a = _ident()
        b = _ident(path="src/other.py")
        c = _ident()  # exact duplicate of a
        result = dedup_by_identity([a, b, c])
        assert len(result) == 2
        assert {r.path for r in result} == {"src/app.py", "src/other.py"}

    def test_order_preserving_first_wins(self):
        a = _ident(provider_symbol_id=None)
        b = _ident(provider_symbol_id="scip:x")  # different key -> kept
        assert dedup_by_identity([a, b]) == [a, b]


class TestAdapters:
    def test_normalize_repo_path(self):
        assert normalize_repo_path("./src/app.py") == "src/app.py"
        assert normalize_repo_path("src\\app.py") == "src/app.py"
        assert normalize_repo_path("") is None
        assert normalize_repo_path(None) is None
        assert normalize_repo_path("a/./b/../c.py") == "a/c.py"

    def test_from_subject_maps_canonical_subject(self):
        from sot_graph.providers.normalization import CanonicalSubject

        subject = CanonicalSubject(
            kind="function", qualified_name="mod.run", path="./pkg/app.py",
            start_line=3, end_line=5, content_hash=None,
            repo_id="repo", language="python", start_column=1, end_column=9,
        )
        ident = from_subject(subject)
        assert ident.path == "pkg/app.py"
        assert ident.language == "python"
        assert ident.repo_id == "repo"
        assert ident.span == Span(3, 5, 1, 9)
        assert identity_key(ident) == identity_key(_ident(
            repo_id="repo", path="pkg/app.py", qualified_name="mod.run",
            span=Span(3, 5, 1, 9),
        ))

    def test_from_graph_row(self):
        row = {
            "path": "src/app.py", "kind": "function", "symbol": "run",
            "fqn": "src.app.run", "line_start": 1, "line_end": 2,
            "col_start": 0, "col_end": 5,
        }
        ident = from_graph_row(row, repo_id="repo")
        assert ident.language == "python"
        assert ident.qualified_name == "run"
        assert ident.span == Span(1, 2, 0, 5)

    def test_from_provider_symbol_namespaces_ids(self):
        a = from_provider_symbol(
            repo_id="r", path="a.py", language="python", kind="function",
            qualified_name="run", span=Span(1, 1), provider="scip",
            provider_symbol_id="abc",
        )
        b = from_provider_symbol(
            repo_id="r", path="a.py", language="python", kind="function",
            qualified_name="run", span=Span(1, 1), provider="codebase-memory",
            provider_symbol_id="abc",
        )
        # same wire id from two providers must NOT join
        assert a.provider_symbol_id == "scip:abc"
        assert b.provider_symbol_id == "codebase-memory:abc"
        assert identity_key(a) != identity_key(b)


class TestPublicApi:
    def test_assurance_reexports_identity(self):
        import sot_graph.assurance as assurance

        for name in ("SymbolIdentity", "Span", "identity_key", "identity_hash",
                     "dedup_by_identity", "from_subject", "from_graph_row",
                     "from_provider_symbol"):
            assert hasattr(assurance, name), name
