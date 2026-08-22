/**
 * sot_omp_extension.ts — OMP (Oh My Pi) Native Extension for SOT-Graph.
 * Exposes sot_search, sot_explore, sot_reconcile, and sot_insert as agent tools.
 */
import { execFile } from "node:child_process";
import { join } from "node:path";
import { existsSync } from "node:fs";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { Type } from "typebox";

const runCmd = (bin: string, args: string[]): Promise<{ ok: boolean; output: string }> =>
  new Promise((resolve) => {
    execFile(bin, args, { timeout: 60_000, maxBuffer: 4_000_000 }, (err, stdout, stderr) => {
      if (err) {
        resolve({ ok: false, output: `Error: ${err.message}\n${stderr}` });
      } else {
        resolve({ ok: true, output: stdout });
      }
    });
  });

export default function sotGraphExtension(pi: ExtensionAPI): void {
  const getSotBin = (): string => {
    const localBin = join(process.cwd(), "bin", "sot");
    return existsSync(localBin) ? localBin : "sot";
  };

  // 1. sot_search: Verified Knowledge Search
  pi.registerTool({
    name: "sot_search",
    label: "SOT Knowledge Search",
    description:
      "Search the verified Source-of-Truth knowledge graph with Trust Verdicts ([STRONG], [WEAK], [REBUILT]). Use BEFORE implementing features or refactoring to locate existing code and avoid rebuilding prior work.",
    promptSnippet: "Search verified codebase knowledge and AST symbols",
    parameters: Type.Object({
      query: Type.String({ description: "Search query, symbol, or topic" }),
      limit: Type.Optional(Type.Number({ description: "Max results (default 6)" })),
      scope: Type.Optional(Type.String({ description: "Filter by directory or file path" })),
    }),
    async execute(_id, params) {
      const args = ["search", params.query, "-n", String(params.limit ?? 6)];
      if (params.scope) args.push("--scope", params.scope);
      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output }], details: { ok } };
    },
  });

  // 2. sot_explore: AST Cross-file Graph Walk
  pi.registerTool({
    name: "sot_explore",
    label: "SOT Graph Explore",
    description:
      "Explore inbound and outbound relations for an AST symbol/class/function. Shows what calls this symbol and what this symbol calls across files.",
    promptSnippet: "Explore cross-file dependencies and calls",
    parameters: Type.Object({
      target: Type.String({ description: "Symbol or class name to trace" }),
      depth: Type.Optional(Type.Number({ description: "Graph traversal depth (default 2)" })),
    }),
    async execute(_id, params) {
      const args = ["explore", params.target, "--depth", String(params.depth ?? 2)];
      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output }], details: { ok } };
    },
  });

  // 3. sot_reconcile: Sync Knowledge Graph
  pi.registerTool({
    name: "sot_reconcile",
    label: "SOT Reconcile",
    description:
      "Idempotently synchronize the knowledge graph with disk files. Re-indexes modified files and cleans dead paths.",
    promptSnippet: "Sync knowledge graph with filesystem",
    parameters: Type.Object({}),
    async execute() {
      const { ok, output } = await runCmd(getSotBin(), ["reconcile"]);
      return { content: [{ type: "text", text: output }], details: { ok } };
    },
  });

  // 4. sot_insert: Record Knowledge Node
  pi.registerTool({
    name: "sot_insert",
    label: "SOT Insert Note",
    description:
      "Record an architectural decision, pattern, or gotcha into persistent knowledge graph for future sessions.",
    promptSnippet: "Insert reusable knowledge into machine memory",
    parameters: Type.Object({
      title: Type.String({ description: "Short title of the knowledge node" }),
      body: Type.String({ description: "Explanation, fix, or solution details" }),
      path: Type.Optional(Type.String({ description: "Associated file path" })),
      keywords: Type.Optional(Type.String({ description: "Comma-separated keywords" })),
    }),
    async execute(_id, params) {
      const args = ["insert", "--title", params.title, "--body", params.body];
      if (params.path) args.push("--path", params.path);
      if (params.keywords) args.push("--keywords", params.keywords);
      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output }], details: { ok } };
    },
  });
}
