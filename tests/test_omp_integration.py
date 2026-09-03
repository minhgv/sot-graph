"""
test_omp_integration.py — End-to-End Test Scenarios for SOT-Graph and OMP Harness Integration.

Validates all 10 core operational scenarios:
1. Reconcile & full codebase synchronization
2. Verified Search with [STRONG] / [WEAK] trust verdicts
3. AST Cross-file Graph Exploration
4. Real-time disk verification & drift detection
5. Self-healing & auto-purging on file deletion
6. Knowledge note insertion and semantic retrieval
7. Community detection & Modularity Q calculation
8. Database diagnostics (doctor), clean plan, and vacuum
9. Interactive HTML viz and multi-format exporters (GraphRAG, Obsidian, GraphML)
10. OMP Extension TypeScript interface and compilation
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN_SOT = REPO_ROOT / "bin" / "sot"


class TestOMPIntegrationScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = os.environ.copy()
        cls.env["PYTHONPATH"] = str(REPO_ROOT / "src")
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp_dir.name) / "sot.db"

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def run_sot(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        has_db = any(a == "--db" or a.startswith("--db=") for a in args)
        extra_args = [] if has_db else ["--db", str(self.db_path)]
        if sys.platform == "win32":
            # bin/sot is a bash launcher; on Windows drive the CLI module
            # directly with the same PYTHONPATH the launcher exports.
            cmd = [sys.executable, "-m", "sot_graph.cli"] + extra_args + args
        else:
            cmd = [str(BIN_SOT)] + extra_args + args
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            env=self.env,
            capture_output=True,
            encoding="utf-8",  # the CLI reconfigures its streams to UTF-8
            errors="replace",  # on every platform; never locale-decode them
        )
        if check and proc.returncode != 0:
            self.fail(f"sot command failed: {' '.join(cmd)}\nStdout: {proc.stdout}\nStderr: {proc.stderr}")
        return proc

    def test_scenario_01_reconcile_sync(self):
        """Scenario 1: Codebase Indexing & Synchronization."""
        res = self.run_sot(["reconcile", "--workers", "2"])
        self.assertIn("Reconcile complete", res.stdout)
        self.assertIn("failed", res.stdout)
        self.assertTrue(self.db_path.exists())

    def test_scenario_02_verified_search_trust_verdicts(self):
        """Scenario 2: Search with Trust Verdicts and Content Coverage."""
        res = self.run_sot(["search", "Database", "-n", "5"])
        self.assertIn("[STRONG", res.stdout)
        self.assertIn("Database", res.stdout)
        self.assertIn("cov:", res.stdout)

    def test_scenario_03_ast_explore(self):
        """Scenario 3: AST Cross-file Graph Exploration."""
        res = self.run_sot(["explore", "Database", "--depth", "2"])
        self.assertIn("Graph Walk:", res.stdout)
        self.assertTrue("Outward Calls" in res.stdout or "Incoming References" in res.stdout or "Defines" in res.stdout)

    def test_scenario_04_verify_drift(self):
        """Scenario 4: Drift Detection against Disk Reality.

        Runs against an isolated fixture repo. Asserting ZERO DRIFT on the
        live repository is inherently flaky: any repo file that changes
        between this class's reconcile (scenario 01) and this verify
        (another test's artifacts, a parallel process, an editor) is GENUINE
        drift and fails the assertion. Here drift is created deliberately
        (positive control), detected, then reconciled back to zero.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = root / "app.py"
            app.write_text("def alpha():\n    return 1\n", encoding="utf-8")
            base = ["--db", str(root / "sot.db"), "--root", str(root)]

            res_add = self.run_sot(base + ["reconcile"])
            self.assertIn("Reconcile complete", res_add.stdout)

            # Positive control: journaled content changed on disk — deep
            # verify must report the file as drifted, never bless it with
            # a ZERO DRIFT verdict.
            app.write_text("def alpha():\n    return 2\n", encoding="utf-8")
            res_drift = self.run_sot(base + ["verify", "--deep"], check=False)
            self.assertEqual(res_drift.returncode, 1)
            self.assertIn("DRIFT DETECTED", res_drift.stdout)
            self.assertIn("hash_mismatch", res_drift.stdout)
            self.assertIn("app.py", res_drift.stdout)

            # Recovery: reconcile converges the graph; verify is zero again.
            res_fix = self.run_sot(base + ["reconcile"])
            self.assertIn("Reconcile complete", res_fix.stdout)
            res_ok = self.run_sot(base + ["verify", "--deep"])
            self.assertIn("ZERO DRIFT", res_ok.stdout)

    def test_scenario_05_self_healing_and_dead_path_autopurge(self):
        """Scenario 5: Self-Healing & Auto-Purging on File Deletion."""
        dummy_file = REPO_ROOT / "src" / "sot_graph" / "_dummy_omp_test.py"
        try:
            # Step A: Create temporary source file
            dummy_file.write_text("class DummyOMPTest:\n    def execute(self):\n        return True\n")
            
            # Step B: Reconcile -> file should be indexed
            res_add = self.run_sot(["reconcile"])
            self.assertIn("indexed/updated", res_add.stdout)

            # Step C: Search for temporary symbol
            res_search = self.run_sot(["search", "DummyOMPTest"])
            self.assertIn("[STRONG", res_search.stdout)
            self.assertIn("_dummy_omp_test.py", res_search.stdout)

            # Step D: Delete temporary file
            dummy_file.unlink()

            # Step E: Reconcile -> file should be automatically purged
            res_del = self.run_sot(["reconcile"])
            self.assertIn("purged", res_del.stdout)

            # Step F: Search again -> should not return active STRONG hit for deleted file
            res_search_after = self.run_sot(["search", "DummyOMPTest"])
            self.assertNotIn("_dummy_omp_test.py", res_search_after.stdout)
        finally:
            if dummy_file.exists():
                dummy_file.unlink()

    def test_scenario_06_knowledge_note_insertion_and_search(self):
        """Scenario 6: Knowledge Note Anchoring and Semantic Retrieval."""
        note_title = "OMP Native Tool Integration Guide"
        note_body = "Exposes sot_search and sot_explore as first-class native tools for Pi coding harness."
        note_keywords = "omp,pi,native,extension,tool"

        # Insert note
        res_insert = self.run_sot([
            "insert",
            "--title", note_title,
            "--body", note_body,
            "--keywords", note_keywords,
        ])
        self.assertIn("Stored knowledge node", res_insert.stdout)

        # Search note
        res_search = self.run_sot(["search", "OMP Native Tool Integration Guide"])
        self.assertIn("[STRONG", res_search.stdout)
        self.assertIn("OMP Native Tool Integration Guide", res_search.stdout)

    def test_scenario_07_community_detection_and_modularity(self):
        """Scenario 7: Graph Analytics & Louvain Clustering."""
        res_cluster = self.run_sot(["cluster"])
        self.assertIn("Detected", res_cluster.stdout)
        self.assertIn("Architectural Communities", res_cluster.stdout)

        res_report = self.run_sot(["report"])
        self.assertIn("Architectural report saved to", res_report.stdout)

    def test_scenario_08_doctor_and_database_maintenance(self):
        """Scenario 8: Database Diagnostics (Doctor) and Vacuum."""
        res_doc = self.run_sot(["doctor"])
        self.assertIn("SOT-Graph Doctor Report:", res_doc.stdout)
        self.assertIn("Graph Nodes", res_doc.stdout)
        self.assertIn("SQLite Database", res_doc.stdout)

        res_clean = self.run_sot(["clean", "--dry-run"])
        self.assertIn("Clean (stale):", res_clean.stdout)

        res_vac = self.run_sot(["vacuum", "--dry-run"])
        self.assertIn("Vacuum", res_vac.stdout)
    def test_scenario_09_viz_and_multi_format_exporters(self):
        """Scenario 9: Interactive HTML Visualizer & Multi-Format Exporters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # HTML Visualizer
            html_out = tmppath / "test_graph.html"
            self.run_sot(["viz", "-o", str(html_out)])
            self.assertTrue(html_out.exists())
            self.assertGreater(html_out.stat().st_size, 1000)
            self.assertIn("<!DOCTYPE html>", html_out.read_text())

            # GraphRAG JSON Export
            graphrag_out = tmppath / "graphrag.json"
            self.run_sot(["export", "--format", "graphrag", "-o", str(graphrag_out)])
            self.assertTrue(graphrag_out.exists())
            data = json.loads(graphrag_out.read_text())
            self.assertIn("entities", data)
            self.assertIn("relationships", data)
            self.assertIn("communities", data)

            # Obsidian Vault Export
            obsidian_out = tmppath / "obsidian_vault"
            self.run_sot(["export", "--format", "obsidian", "-o", str(obsidian_out)])
            self.assertTrue(obsidian_out.exists())
            md_files = list(obsidian_out.glob("*.md"))
            self.assertGreater(len(md_files), 0)

            # GraphML Export
            graphml_out = tmppath / "graph.graphml"
            self.run_sot(["export", "--format", "graphml", "-o", str(graphml_out)])
            self.assertTrue(graphml_out.exists())
            self.assertIn("<graphml", graphml_out.read_text())
    def test_adapter_security_and_maintenance_contracts(self):
        """OMP/OpenCode adapters use trusted PATH commands and safe tool flags."""
        if sys.platform == "win32":
            self.skipTest("The executable PATH harness is POSIX-specific")
        bun = shutil.which("bun")
        if not bun:
            self.skipTest("bun is required for TypeScript adapter behavior tests")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            workspace = tmp_root / "workspace"
            local_bin = workspace / "bin"
            node_bin = workspace / "node_modules" / ".bin"
            nested_bin = workspace / "tools"
            trusted_bin = tmp_root / "trusted-bin"
            alias_bin = tmp_root / "alias-bin"
            windows_trusted_bin = tmp_root / "windows-trusted-bin"
            windows_alias_bin = tmp_root / "windows-alias-bin"
            workspace_alias_bin = workspace / "workspace-path-alias"
            workspace.mkdir()
            local_bin.mkdir(parents=True)
            node_bin.mkdir(parents=True)
            nested_bin.mkdir()
            trusted_bin.mkdir()
            alias_bin.mkdir()
            windows_trusted_bin.mkdir()
            windows_alias_bin.mkdir()
            (workspace / ".sot").mkdir()
            log_path = tmp_root / "trusted.log"
            marker_path = tmp_root / "malicious.log"

            trusted_bin.joinpath("sot").write_text(
                f"#!{sys.executable}\n"
                "import os, sys\n"
                f"with open({json.dumps(str(log_path))}, 'a', encoding='utf-8') as handle:\n"
                "    path_keys = sorted(key for key in os.environ if key.lower() == 'path')\n"
                "    python_path_keys = sorted(key for key in os.environ if key.lower() == 'pythonpath')\n"
                "    handle.write(' '.join(sys.argv[1:]) + '|' + os.environ.get('PYTHONPATH', '<unset>') + '|' + ','.join(path_keys) + '|' + ','.join(python_path_keys) + '|' + os.environ.get('PATH', '<missing>') + '\\n')\n"
                "print('trusted')\n",
                encoding="utf-8",
            )
            trusted_bin.joinpath("sot").chmod(0o755)
            windows_trusted_bin.joinpath("sot.EXE").write_text(
                trusted_bin.joinpath("sot").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            windows_trusted_bin.joinpath("sot.EXE").chmod(0o755)
            malicious = (
                f"#!{sys.executable}\n"
                f"with open({json.dumps(str(marker_path))}, 'a', encoding='utf-8') as handle:\n"
                "    handle.write('malicious\\n')\n"
            )
            for malicious_bin in (
                workspace / "sot",
                workspace / "sot.exe",
                local_bin / "sot",
                node_bin / "sot",
                nested_bin / "sot",
            ):
                malicious_bin.write_text(malicious, encoding="utf-8")
                malicious_bin.chmod(0o755)
            alias_bin.joinpath("sot").symlink_to(node_bin / "sot")
            windows_alias_bin.joinpath("sot.EXE").symlink_to(workspace / "sot.exe")
            workspace_alias_bin.symlink_to(trusted_bin, target_is_directory=True)

            harness = """
import ompExtension, { resolveSotBinary } from __OMP_EXTENSION__;
import openCodePlugin from __OPENCODE_PLUGIN__;

const workspace = __WORKSPACE__;
const logPath = __LOG_PATH__;
const localBin = `${workspace}/bin`;
const nodeBin = `${workspace}/node_modules/.bin`;
const nestedBin = `${workspace}/tools`;
const workspaceAliasBin = `${workspace}/workspace-path-alias`;
const trustedBin = __TRUSTED_BIN__;
const aliasBin = __ALIAS_BIN__;
const windowsTrustedBin = __WINDOWS_TRUSTED_BIN__;
const windowsAliasBin = __WINDOWS_ALIAS_BIN__;
const pathSeparator = process.platform === "win32" ? ";" : ":";
const originalPath = process.env.PATH || "";
const windowsPath = [
  workspace,
  localBin,
  nodeBin,
  nestedBin,
  workspaceAliasBin,
  aliasBin,
  windowsAliasBin,
  trustedBin,
  windowsTrustedBin,
  originalPath,
].join(pathSeparator);
process.env.PATH = windowsPath;
process.env.Path = windowsPath;
process.env.PYTHONPATH = `${workspace}/src`;
process.env.PythonPath = `${workspace}/src`;

process.chdir(workspace);

const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};

const fs = await import("node:fs");
const canonicalTrustedBinary = fs.realpathSync(`${trustedBin}/sot`);
assert(resolveSotBinary(workspace) === canonicalTrustedBinary, "POSIX resolver must return the canonical PATH executable");

const mockedWindowsPath = [
  workspace,
  localBin,
  nodeBin,
  nestedBin,
  windowsAliasBin,
  aliasBin,
  windowsTrustedBin,
].join(";");
process.env.PATH = mockedWindowsPath;
process.env.Path = mockedWindowsPath;
process.env.PATHEXT = ".EXE;.CMD";
const canonicalWindowsBinary = fs.realpathSync(`${windowsTrustedBin}/sot.EXE`);
assert(
  resolveSotBinary(workspace, "win32") === canonicalWindowsBinary,
  "Windows resolver must honor PATHEXT and return an absolute canonical executable",
);
process.env.PATH = [workspace, windowsAliasBin].join(";");
process.env.Path = process.env.PATH;
assert(
  resolveSotBinary(workspace, "win32") === undefined,
  "Windows resolver must reject current-directory and symlinked workspace candidates",
);
process.env.PATH = windowsPath;
process.env.Path = windowsPath;
delete process.env.PATHEXT;
const tools = new Map();
const ompEvents = new Map();
ompExtension({
  registerTool(tool) {
    tools.set(tool.name, tool);
  },
  on(name, handler) {
    ompEvents.set(name, handler);
  },
});
assert(tools.get("sot_clean").parameters.properties.confirm.type === "boolean", "clean schema must expose confirmation");
assert(tools.get("sot_pack").parameters.properties.tokens.type === "number", "pack schema must expose token budget");

await ompEvents.get("session_start")();
const packResult = await tools.get("sot_pack").execute("test", {
  target: "Example",
  depth: 3,
  tokens: 777,
});
assert(packResult.details.ok === true, "pack command should succeed");

const blockedClean = await tools.get("sot_clean").execute("test", { all: true });
assert(blockedClean.details.ok === false && blockedClean.details.blocked === true, "clean-all must require confirmation");
const linesAfterBlockedClean = (await Bun.file(logPath).text()).trim().split("\\n").filter(Boolean);
assert(!linesAfterBlockedClean.some((line) => line.startsWith("clean ")), "blocked clean must not execute a command");

const confirmedClean = await tools.get("sot_clean").execute("test", { all: true, confirm: true });
assert(confirmedClean.details.ok === true, "confirmed clean command should succeed");
const blockedDiffLineCount = (await Bun.file(logPath).text()).trim().split("\\n").filter(Boolean).length;
const blockedDiff = await tools.get("sot_diff_impact").execute("test", { target: "--staged" });
assert(blockedDiff.details.ok === false && blockedDiff.details.blocked === true, "option-like diff target must be rejected");
const linesAfterBlockedDiff = (await Bun.file(logPath).text()).trim().split("\\n").filter(Boolean);
assert(linesAfterBlockedDiff.length === blockedDiffLineCount, "rejected diff target must not execute a command");

const opencodeEvents = new Map();
await openCodePlugin({
  directory: workspace,
  event: {
    on(name, handler) {
      opencodeEvents.set(name, handler);
      return () => {};
    },
  },
});
await opencodeEvents.get("session.created")();

// A successful result from each mutating OMP tool schedules one debounced reconcile.
await Bun.write(`${workspace}/.sot/sot.db`, "present");
const toolResult = ompEvents.get("tool_result");
assert(typeof toolResult === "function", "OMP mutation result hook must be registered");
await toolResult({ tool: "write", success: true, path: "src/write.py" });
await toolResult({ toolName: "edit", result: { ok: true }, input: { path: "src/edit.py" } });
await toolResult({ name: "ast_edit", result: { details: { ok: true } }, args: { path: "src/ast.py" } });
await toolResult({ tool: "patch", result: { isError: false }, path: "src/patch.py" });
await toolResult({ tool: "write", success: false, path: "src/failed.py" });
await new Promise((resolve) => setTimeout(resolve, 450));

const lines = (await Bun.file(logPath).text()).trim().split("\\n").filter(Boolean);
assert(lines.some((line) => line.startsWith("reconcile|")), "session startup must reconcile through PATH");
assert(lines.some((line) => line.startsWith("pack Example --max-hops 3 --max-tokens 777|")), "pack depth and tokens must map to CLI flags");
assert(lines.some((line) => line.startsWith("clean --all --yes|")), "explicit clean confirmation must pass --yes");
const mutationLine = lines.find((line) => line.startsWith("reconcile src/write.py"));
assert(mutationLine && ["src/edit.py", "src/ast.py", "src/patch.py"].every((path) => mutationLine.includes(path)), "successful mutations must trigger one debounced reconcile");
assert(!lines.some((line) => line.includes("src/failed.py")), "failed mutation results must not reconcile");
assert(lines.every((line) => line.split("|")[1] === "<unset>"), "adapters must not inject any PYTHONPATH variant");
assert(lines.every((line) => line.split("|")[2] === "PATH"), "adapters must publish one canonical PATH key");
assert(lines.every((line) => line.split("|")[3] === ""), "adapters must remove all PythonPath variants");
const childPaths = lines.map((line) => line.split("|")[4].split(pathSeparator));
assert(childPaths.every((entries) => !entries.includes(workspaceAliasBin)), "workspace symlink PATH entries must not be republished");
assert(childPaths.every((entries) => !entries.includes(aliasBin)), "external aliases to workspace tools must not be republished");
assert(childPaths.every((entries) => !entries.includes(nodeBin)), "canonical workspace paths must not be published");
const canonicalTrustedBin = (await import("node:fs")).realpathSync(trustedBin);
assert(childPaths.every((entries) => entries.includes(canonicalTrustedBin)), "external trusted PATH commands must remain available");

// A missing installed command is a non-fatal background-sync failure.
const { unlink } = await import("node:fs/promises");
await unlink(`${workspace}/.sot/sot.db`);
process.env.PATH = localBin;
await ompEvents.get("session_start")();
await opencodeEvents.get("session.created")();
process.env.PATH = originalPath;
"""
            replacements = {
                "__OMP_EXTENSION__": json.dumps(
                    str(REPO_ROOT / "src" / "sot_graph" / "adapters" / "omp_extension.ts")
                ),
                "__OPENCODE_PLUGIN__": json.dumps(
                    str(REPO_ROOT / "src" / "sot_graph" / "adapters" / "opencode_plugin.ts")
                ),
                "__WORKSPACE__": json.dumps(str(workspace)),
                "__LOG_PATH__": json.dumps(str(log_path)),
                "__TRUSTED_BIN__": json.dumps(str(trusted_bin)),
                "__ALIAS_BIN__": json.dumps(str(alias_bin)),
                "__WINDOWS_TRUSTED_BIN__": json.dumps(str(windows_trusted_bin)),
                "__WINDOWS_ALIAS_BIN__": json.dumps(str(windows_alias_bin)),
            }
            for placeholder, value in replacements.items():
                harness = harness.replace(placeholder, value)

            harness_path = tmp_root / "adapter_harness.ts"
            harness_path.write_text(harness, encoding="utf-8")
            proc = subprocess.run(
                [bun, "run", str(harness_path)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                env=self.env,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"Adapter harness failed:\nStdout: {proc.stdout}\nStderr: {proc.stderr}",
            )
            self.assertFalse(marker_path.exists(), "workspace-controlled PATH entries must never be invoked")

    def test_scenario_10_omp_extension_compilation(self):
        """Scenario 10: OMP and OpenCode TypeScript compilation."""
        extension_paths = [
            REPO_ROOT / "src" / "sot_graph" / "adapters" / "omp_extension.ts",
            REPO_ROOT / ".omp" / "extensions" / "sot-graph.ts",
            REPO_ROOT / "src" / "sot_graph" / "adapters" / "opencode_plugin.ts",
        ]
        self.assertEqual(extension_paths[0].read_bytes(), extension_paths[1].read_bytes())
        for ext_path in extension_paths:
            self.assertTrue(ext_path.exists())

            # Check if bun or tsc is available for compilation test
            shutil_bun = shutil.which("bun")
            if shutil_bun:
                proc = subprocess.run(
                    [shutil_bun, "build", str(ext_path), "--no-bundle"],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(proc.returncode, 0, f"Bun build failed:\n{proc.stderr}")
                if ext_path.name == "omp_extension.ts":
                    self.assertIn("sotGraphExtension", proc.stdout)



if __name__ == "__main__":
    unittest.main()
