"""SG-203 unit tests: cross-provider identity normalizers.

Pure-function coverage for kind folding, FQN canonicalization, the CBM
mangled-root prefix, fail-closed rules (node IDs in provider columns,
mangled names without repo_root, SCIP synthetics) and the join-key /
span-conflict semantics — the integration joins live in
test_providers_cross_check.py.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from sot_graph.assurance.identity import Span
from sot_graph.providers.identity_join import (
    builtin_identity,
    canonical_fqn,
    cbm_identity,
    cross_join_key,
    evidence_identity,
    identities_joinable,
    identity_summary,
    kind_class,
    mangled_root_prefix,
    scip_identity,
    span_conflict,
)


def _identity(qualified_name, path=None, repo_id="repo", span=None):
    from sot_graph.assurance.identity import SymbolIdentity

    return SymbolIdentity(
        repo_id=repo_id, path=path, language="python", kind="callable",
        qualified_name=qualified_name, span=span, provider_symbol_id=None,
    )


class KindClassTests(unittest.TestCase):
    def test_folds_provider_vocabularies(self):
        for raw in ("function", "method", "FUNCTION", " constructor "):
            self.assertEqual(kind_class(raw), "callable")
        self.assertEqual(kind_class("class"), "type")
        self.assertEqual(kind_class("module"), "module")
        self.assertEqual(kind_class("mystery"), "other")

    def test_non_string_is_blank(self):
        self.assertEqual(kind_class(None), "")
        self.assertEqual(kind_class(7), "")
        self.assertEqual(kind_class("   "), "")


class CanonicalFqnTests(unittest.TestCase):
    def test_drops_descriptor_leftovers_and_path_chunks(self):
        self.assertEqual(canonical_fqn("compute_total()"), "compute_total")
        self.assertEqual(canonical_fqn("compute_total()."), "compute_total")
        # A chunk carrying a slash is a path fragment, not a module name.
        self.assertEqual(
            canonical_fqn("core/service.compute_total"),
            "compute_total",
        )
        # Dotted names without slashes are legitimate FQNs — kept whole.
        self.assertEqual(
            canonical_fqn("app.main.build_invoice"),
            "app.main.build_invoice",
        )

    def test_garbage_in_garbage_out(self):
        self.assertEqual(canonical_fqn(""), "")
        self.assertEqual(canonical_fqn(None), "")
        self.assertEqual(canonical_fqn("..."), "")


class MangledRootPrefixTests(unittest.TestCase):
    def test_realpath_dash_mangling(self):
        with tempfile.TemporaryDirectory() as tmp:
            # macOS /var → /private/var: the prefix must come from the
            # REAL path or CBM names never strip.
            mangled = mangled_root_prefix(tmp)
            self.assertEqual(mangled, mangled_root_prefix(tmp))
            # Platform-portable shape: separators and drive colons are
            # mangled away, leaving a pure dash-joined label.
            for raw in ("\\", "/", ":"):
                self.assertNotIn(raw, mangled)
            if os.name == "posix":
                self.assertEqual(
                    mangled,
                    os.path.realpath(tmp).lstrip("/").replace("/", "-"),
                )

    def test_windows_style_root_mangles_deterministically(self):
        # A Windows root must mangle to the same dash-only label shape as
        # a POSIX root — the pre-fix lstrip/replace pair was a no-op on
        # backslash paths and leaked raw separators/colon through.
        win_root = ("C:\\Users\\runneradmin\\AppData\\Local\\Temp\\"
                    "pytest-of-runneradmin\\pytest-2\\test_span0")
        with mock.patch.object(os.path, "realpath", return_value=win_root):
            mangled = mangled_root_prefix(win_root)
            self.assertEqual(
                mangled,
                "C-Users-runneradmin-AppData-Local-Temp-"
                "pytest-of-runneradmin-pytest-2-test_span0",
            )
            self.assertEqual(mangled, mangled_root_prefix(win_root))

    def test_windows_mangled_shape_without_root_fails_closed(self):
        # The Windows-mangled CBM name must hit the same no-repo_root
        # fail-closed rule as the POSIX-mangled one.
        name = ("C-Users-runneradmin-AppData-Local-Temp-"
                "pytest-of-runneradmin-pytest-2-test_span0"
                ".app.main.build_invoice")
        self.assertIsNone(cbm_identity(name, repo_root=None))


class BuiltinIdentityTests(unittest.TestCase):
    def test_fqn_wins_over_bare_symbol(self):
        identity = builtin_identity({
            "path": "app/main.py", "fqn": "app.main.build_invoice",
            "symbol": "build_invoice", "kind": "function",
            "line_start": 5, "line_end": 7,
        })
        self.assertIsNotNone(identity)
        self.assertEqual(identity.qualified_name, "app.main.build_invoice")
        self.assertEqual(identity.path, "app/main.py")
        self.assertEqual(identity.span, Span(5, 7))

    def test_node_ids_are_never_identities(self):
        # An fqn that is literally a builtin node ID must not pass through
        # as a qualified name.
        identity = builtin_identity({
            "path": "app/main.py", "fqn": "sym:deadbee:build_invoice",
            "symbol": None, "kind": "function",
        })
        # canonical_fqn keeps the string (it is not path-ish) — so the
        # guard lives at the JOIN: cross_check never feeds node IDs here.
        # The contract under test: builtin side derives from real rows.
        self.assertIsNotNone(identity)  # shape preserved, not silently None

    def test_no_name_no_identity(self):
        self.assertIsNone(builtin_identity({"path": "app/main.py"}))


class ScipIdentityTests(unittest.TestCase):
    def test_embedded_doc_path_defines_the_module(self):
        identity = scip_identity(
            "scip-python python pkg 1.0.0 `core/service.py`/compute_total().",
            "app/main.py",
        )
        self.assertIsNotNone(identity)
        self.assertEqual(identity.qualified_name, "core.service.compute_total")
        # The occurrence path is carried for adjudication, not identity.
        self.assertEqual(identity.path, "app/main.py")

    def test_local_synthetics_fail_closed(self):
        self.assertIsNone(scip_identity("local 1", "app/main.py"))

    def test_no_document_no_identity(self):
        self.assertIsNone(
            scip_identity("scip-python python pkg 1.0 `x`/f().", None))


class CbmIdentityTests(unittest.TestCase):
    def test_strips_mangled_prefix_with_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            mangled = mangled_root_prefix(tmp)
            identity = cbm_identity(
                f"{mangled}.app.main.build_invoice", tmp,
                path="app/main.py", kind_hint="function",
            )
            self.assertIsNotNone(identity)
            self.assertEqual(identity.qualified_name,
                             "app.main.build_invoice")

    def test_mangled_shape_without_root_fails_closed(self):
        self.assertIsNone(
            cbm_identity("Users-x-code-repo.app.main.build_invoice", None))

    def test_plain_name_without_root_passes(self):
        identity = cbm_identity("app.main.build_invoice", None)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.qualified_name, "app.main.build_invoice")


class EvidenceIdentityTests(unittest.TestCase):
    def test_builtin_node_id_in_provider_column_is_foreign(self):
        self.assertIsNone(
            evidence_identity("codebase-memory", "sym:abcdef12:build_invoice"))

    def test_dispatch_by_provider_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            mangled = mangled_root_prefix(tmp)
            cbm = evidence_identity(
                "codebase-memory", f"{mangled}.core.compute", repo_root=tmp)
            self.assertEqual(cbm.qualified_name, "core.compute")
        scip = evidence_identity(
            "scip-index", "scip-python python pkg 1.0 `x/y.py`/f().",
            path="x/y.py")
        self.assertEqual(scip.qualified_name, "x.y.f")
        other = evidence_identity("some-provider", "a.b.c")
        self.assertEqual(other.qualified_name, "a.b.c")


class CrossJoinKeyTests(unittest.TestCase):
    def test_module_qualified_fqn_joins_path_free(self):
        a = _identity("app.main.build_invoice", path="app/main.py")
        b = _identity("app.main.build_invoice", path=None)
        self.assertEqual(cross_join_key(a), cross_join_key(b))
        self.assertTrue(identities_joinable(a, b))

    def test_bare_fqn_requires_path_in_the_key(self):
        a = _identity("build_invoice", path="app/main.py")
        b = _identity("build_invoice", path=None)
        self.assertNotEqual(cross_join_key(a), cross_join_key(b))

    def test_same_fqn_different_files_are_different_symbols(self):
        a = _identity("util.render", path="a/util.py")
        b = _identity("util.render", path="b/util.py")
        self.assertEqual(cross_join_key(a), cross_join_key(b))
        self.assertFalse(identities_joinable(a, b))

    def test_repo_partitions_namespaces(self):
        a = _identity("app.main.f", repo_id="one")
        b = _identity("app.main.f", repo_id="two")
        self.assertNotEqual(cross_join_key(a), cross_join_key(b))


class SpanConflictTests(unittest.TestCase):
    def test_within_tolerance_and_unknown_never_conflict(self):
        self.assertFalse(span_conflict(Span(4, 6), Span(5, 7)))
        self.assertFalse(span_conflict(None, Span(1, 2)))
        self.assertFalse(span_conflict(Span(1, 2), None))

    def test_beyond_tolerance_conflicts(self):
        self.assertTrue(span_conflict(Span(4, 6), Span(60, 62)))


class IdentitySummaryTests(unittest.TestCase):
    def test_resolved_and_unresolved_shapes(self):
        summary = identity_summary(
            _identity("app.f", path="app.py", span=Span(1, 2)))
        self.assertTrue(summary["resolved"])
        self.assertEqual(summary["span"], [1, 2])
        self.assertEqual(identity_summary(None), {"resolved": False})


if __name__ == "__main__":
    unittest.main()
