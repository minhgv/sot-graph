"""
tests.test_adapters - Comprehensive Unit Tests for AI Coding Harness Adapters.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sot_graph.adapters.installer import install_harnesses, list_supported_harnesses
from sot_graph.adapters.omp import setup_omp
from sot_graph.adapters.opencode import setup_opencode
from sot_graph.adapters.antigravity import setup_antigravity
from sot_graph.adapters.claude import setup_claude
from sot_graph.adapters.zcode import setup_zcode
from sot_graph.cli import build_parser, cmd_setup


class TestHarnessAdapters(unittest.TestCase):
    """Test suite for multi-harness adapters and unified installer."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.root = Path(self.temp_dir)
        self.mock_home = self.root / "fake_home"
        self.mock_home.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_list_supported_harnesses(self):
        harnesses = list_supported_harnesses()
        self.assertIn("omp", harnesses)
        self.assertIn("opencode", harnesses)
        self.assertIn("antigravity", harnesses)
        self.assertIn("claude", harnesses)
        self.assertIn("zcode", harnesses)

    def test_omp_adapter_workspace_and_global(self):
        with patch.object(Path, "home", return_value=self.mock_home):
            installed = setup_omp(self.root, global_install=True, workspace_install=True)
            self.assertTrue(len(installed) >= 4)

            # Workspace assertions
            ws_ext = self.root / ".omp" / "extensions" / "sot-graph.ts"
            ws_skill = self.root / ".omp" / "skills" / "sot-graph" / "SKILL.md"
            ws_rules = self.root / ".omp" / "RULES.md"
            self.assertTrue(ws_ext.exists())
            self.assertTrue(ws_skill.exists())
            self.assertTrue(ws_rules.exists())
            self.assertIn("Knowledge Reuse Protocol", ws_rules.read_text())

            # Global assertions
            global_ext = self.mock_home / ".omp" / "agent" / "extensions" / "sot-graph.ts"
            self.assertTrue(global_ext.exists())

    def test_opencode_adapter_json_merge_and_skills(self):
        with patch.object(Path, "home", return_value=self.mock_home):
            # Pre-seed existing opencode.json with dummy provider
            global_cfg = self.mock_home / ".config" / "opencode" / "opencode.json"
            global_cfg.parent.mkdir(parents=True, exist_ok=True)
            global_cfg.write_text(json.dumps({"provider": {"test": {"name": "TestProvider"}}}))

            installed = setup_opencode(self.root, global_install=True, workspace_install=True)
            self.assertTrue(len(installed) >= 4)

            # Check JSON merge preserves existing provider and adds MCP
            merged = json.loads(global_cfg.read_text())
            self.assertIn("test", merged["provider"])
            self.assertIn("sot-graph", merged["mcp"])
            self.assertEqual(merged["permission"]["skill"], "allow")

            # Check workspace files
            ws_skill = self.root / ".opencode" / "skills" / "sot-graph" / "SKILL.md"
            self.assertTrue(ws_skill.exists())

    def test_antigravity_adapter_setup(self):
        with patch.object(Path, "home", return_value=self.mock_home):
            installed = setup_antigravity(self.root, global_install=True, workspace_install=True)
            self.assertTrue(len(installed) >= 5)

            # Workspace settings and skills
            ws_settings = self.root / ".gemini" / "settings.json"
            ws_gemini_md = self.root / ".gemini" / "GEMINI.md"
            self.assertTrue(ws_settings.exists())
            self.assertTrue(ws_gemini_md.exists())

            settings_data = json.loads(ws_settings.read_text())
            self.assertIn("sot-graph", settings_data["mcpServers"])
            self.assertIn("SOT-Graph Knowledge Reuse Protocol", ws_gemini_md.read_text())

    def test_claude_adapter_setup(self):
        with patch.object(Path, "home", return_value=self.mock_home):
            installed = setup_claude(self.root, global_install=True, workspace_install=True)
            self.assertTrue(len(installed) >= 4)

            ws_mcp = self.root / ".mcp.json"
            cursor_mcp = self.root / ".cursor" / "mcp.json"
            self.assertTrue(ws_mcp.exists())
            self.assertTrue(cursor_mcp.exists())

            mcp_data = json.loads(ws_mcp.read_text())
            self.assertIn("sot-graph", mcp_data["mcpServers"])

    def test_zcode_adapter_setup(self):
        with patch.object(Path, "home", return_value=self.mock_home):
            installed = setup_zcode(self.root, global_install=True, workspace_install=True)
            self.assertTrue(len(installed) >= 4)

            # Workspace artifacts: nested MCP config, skill, slash commands
            ws_cfg = self.root / ".zcode" / "config.json"
            ws_skill = self.root / ".zcode" / "skills" / "sot-graph" / "SKILL.md"
            self.assertTrue(ws_cfg.exists())
            self.assertTrue(ws_skill.exists())
            for cmd in ("sot-search.md", "sot-map.md", "sot-explore.md", "sot-usages.md", "sot-rename.md", "sot-pack.md", "sot-bundle.md", "sot-diff-impact.md", "sot-log.md"):
                self.assertTrue((self.root / ".zcode" / "commands" / cmd).exists())

            cfg = json.loads(ws_cfg.read_text())
            server = cfg["mcp"]["servers"]["sot-graph"]
            self.assertEqual(server["args"], ["-m", "sot_graph.cli", "mcp"])
            self.assertEqual(server["env"]["PYTHONPATH"], str(self.root / "src"))
            self.assertEqual(server["cwd"], str(self.root))
            self.assertIn("name: sot-graph", ws_skill.read_text())

            # Global assertions
            self.assertTrue((self.mock_home / ".zcode" / "config.json").exists())
            self.assertTrue((self.mock_home / ".zcode" / "skills" / "sot-graph" / "SKILL.md").exists())

    def test_zcode_config_merge_preserves_foreign_keys(self):
        with patch.object(Path, "home", return_value=self.mock_home):
            # Pre-seed existing .zcode/config.json with foreign keys
            ws_cfg = self.root / ".zcode" / "config.json"
            ws_cfg.parent.mkdir(parents=True, exist_ok=True)
            ws_cfg.write_text(json.dumps({
                "mcp": {"servers": {"other": {"command": "foo"}}, "transport": "stdio"},
                "theme": "dark",
            }))

            setup_zcode(self.root, global_install=False, workspace_install=True)

            merged = json.loads(ws_cfg.read_text())
            self.assertEqual(merged["theme"], "dark")
            self.assertEqual(merged["mcp"]["transport"], "stdio")
            self.assertEqual(merged["mcp"]["servers"]["other"]["command"], "foo")
            self.assertIn("sot-graph", merged["mcp"]["servers"])

    def test_zcode_setup_idempotent(self):
        with patch.object(Path, "home", return_value=self.mock_home):
            setup_zcode(self.root, global_install=False, workspace_install=True)
            first_cfg = (self.root / ".zcode" / "config.json").read_text()
            first_skill = (self.root / ".zcode" / "skills" / "sot-graph" / "SKILL.md").read_text()

            setup_zcode(self.root, global_install=False, workspace_install=True)

            self.assertEqual(first_cfg, (self.root / ".zcode" / "config.json").read_text())
            self.assertEqual(first_skill, (self.root / ".zcode" / "skills" / "sot-graph" / "SKILL.md").read_text())

    def test_unified_installer_all(self):
        with patch.object(Path, "home", return_value=self.mock_home):
            results = install_harnesses(["all"], root=self.root, global_install=True, workspace_install=True)
            self.assertEqual(len(results), 5)
            self.assertIn("omp", results)
            self.assertIn("opencode", results)
            self.assertIn("antigravity", results)
            self.assertIn("claude", results)
            self.assertIn("zcode", results)

    def test_unified_installer_pi_alias(self):
        with patch.object(Path, "home", return_value=self.mock_home):
            results = install_harnesses(["pi"], root=self.root, global_install=True, workspace_install=True)
            self.assertIn("omp", results)
            ws_ext = self.root / ".omp" / "extensions" / "sot-graph.ts"
            self.assertTrue(ws_ext.exists())

    def test_cli_setup_pi_alias(self):
        with patch.object(Path, "home", return_value=self.mock_home):
            parser = build_parser()
            args = parser.parse_args(["setup", "--harness", "pi", "--workspace-only"])
            ret = cmd_setup(args, root=str(self.root))
            self.assertEqual(ret, 0)
            self.assertTrue((self.root / ".omp" / "extensions" / "sot-graph.ts").exists())
            self.assertTrue((self.root / ".omp" / "RULES.md").exists())

    def test_cli_setup_command(self):
        with patch.object(Path, "home", return_value=self.mock_home):
            parser = build_parser()
            args = parser.parse_args(["setup", "--harness", "all", "--workspace-only"])
            ret = cmd_setup(args, root=str(self.root))
            self.assertEqual(ret, 0)

            # Verify workspace was configured
            self.assertTrue((self.root / ".omp" / "RULES.md").exists())
            self.assertTrue((self.root / ".opencode" / "skills" / "sot-graph" / "SKILL.md").exists())
            self.assertTrue((self.root / ".gemini" / "settings.json").exists())
            self.assertTrue((self.root / ".mcp.json").exists())
            self.assertTrue((self.root / ".zcode" / "config.json").exists())


if __name__ == "__main__":
    unittest.main()
