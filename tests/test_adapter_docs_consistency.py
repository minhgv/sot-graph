"""Adapter docs must stay consistent with build_parser() and the MCP registry.

Regression fence for audit finding P2 surfaces-20: the hand-maintained
quick-reference tables drifted from reality (unregistered MCP tools like
``sot_reconcile``, nonexistent flags like ``--purge-missing``). The check
logic lives in scripts/adapter_docs_check.py so CI and docs authors run
the exact same gate.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "adapter_docs_check", REPO_ROOT / "scripts" / "adapter_docs_check.py"
)
assert _spec is not None and _spec.loader is not None
adapter_docs_check = importlib.util.module_from_spec(_spec)
sys.modules["adapter_docs_check"] = adapter_docs_check
_spec.loader.exec_module(adapter_docs_check)


class AdapterDocsConsistencyTests(unittest.TestCase):
    def test_docs_match_cli_parser_and_mcp_registry(self):
        violations = adapter_docs_check.check()
        self.assertEqual(
            violations, [],
            "Adapter docs drifted from CLI/MCP reality:\n  - "
            + "\n  - ".join(violations),
        )

    def test_emit_table_covers_all_top_level_subcommands(self):
        table = adapter_docs_check.emit_table()
        truth = adapter_docs_check.CliTruth()
        names = sorted(adapter_docs_check._subparser_choices(truth.main))
        self.assertTrue(names, "build_parser() exposed no subcommands")
        # Leaf commands render as `sot <name>`; parents of nested
        # subcommands (solution, providers) render as `solution inventory`.
        missing = [
            n for n in names
            if f"`sot {n}`" not in table and f"`{n} " not in table
        ]
        self.assertEqual(missing, [])
