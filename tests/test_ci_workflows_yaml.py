"""Phase 0 SG-101/SG-102: CI YAML files stay parseable.

The diff-impact workflow and its composite action were reworked (explicit
`base...head` PR ranges, tool-source dogfood install, gate mode); these
tests pin their YAML validity and the load-bearing input contract so a
typo cannot silently break the CI bot.
"""

import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "diff-impact.yml"
ACTION = REPO_ROOT / ".github" / "actions" / "diff-impact" / "action.yml"


class CiYamlValidityTests(unittest.TestCase):
    def test_both_changed_yaml_files_safe_load(self):
        for path in (WORKFLOW, ACTION):
            with self.subTest(file=str(path.relative_to(REPO_ROOT))):
                self.assertTrue(path.exists(), f"missing: {path}")
                with open(path, encoding="utf-8") as fp:
                    parsed = yaml.safe_load(fp)
                self.assertIsInstance(parsed, dict)

    def test_workflow_passes_explicit_pr_range(self):
        """SG-101: PRs must diff base...head, not a single base revision."""
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        steps = doc["jobs"]["diff-impact"]["steps"]
        target_step = next(s for s in steps if s.get("name") == "SOT-Graph Diff Impact")
        self.assertEqual(target_step["with"]["target"], "${{ env.SOT_DIFF_TARGET }}")
        resolve_step = next(
            s for s in steps
            if isinstance(s.get("run"), str) and "SOT_DIFF_TARGET" in s["run"]
        )
        self.assertIn("github.event.pull_request.base.sha", resolve_step["run"])
        self.assertIn("github.event.pull_request.head.sha", resolve_step["run"])
        self.assertIn("...", resolve_step["run"])

    def test_action_contract_inputs_and_no_consumer_repo_fallback(self):
        """SG-102: dogfood inputs exist; the git+consumer-repo fallback is gone."""
        doc = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
        inputs = doc["inputs"]
        self.assertEqual(inputs["tool-source"]["default"], "auto")
        self.assertIn("checkout", inputs["tool-source"]["description"])
        self.assertIn("pypi", inputs["tool-source"]["description"])
        self.assertEqual(inputs["mode"]["default"], "advisory")
        self.assertIn("gate", inputs["mode"]["description"])
        self.assertEqual(inputs["target"]["default"], "")
        # The harmful fallback installed the CONSUMER's repo as sot-graph.
        raw = ACTION.read_text(encoding="utf-8")
        self.assertNotIn("github.server_url", raw)
        self.assertNotIn("install-extra", raw)
        self.assertIn("install.outputs.source", raw)
        self.assertIn("tool-source-args", raw)


if __name__ == "__main__":
    unittest.main()
