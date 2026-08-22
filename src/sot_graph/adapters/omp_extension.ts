/**
 * sot_omp_extension.ts — OMP (Oh My Pi) Native Extension for SOT-Graph.
 * 
 * Exposes SOT-Graph capabilities as native agent tools:
 * - sot_search: Verified Knowledge & AST Symbol Search with Trust Verdicts
 * - sot_explore: Cross-file AST Call Graph & Dependency Exploration
 * - sot_reconcile: Idempotent Single-Writer Knowledge Graph Synchronization
 * - sot_verify: Real-time Disk Verification & Drift Detection
 * - sot_doctor: Database Diagnostics & Graph Health Statistics
 * - sot_insert: Persistent Knowledge Anchors & Note Recording
 * - sot_cluster: Louvain / Label Propagation Community Detection
 * - sot_report: Architecture Assessment & God Node Blast Radius
 * - sot_viz: Interactive D3.js Knowledge Graph Visualizer Generation
 * - sot_export: Multi-format Graph Export (GraphRAG JSON, Obsidian, GraphML)
 * - sot_bundle: Architecture Fact Bundler for LLM Report Synthesis
 */
import { execFile } from "node:child_process";
import { join } from "node:path";
import { existsSync } from "node:fs";

interface ToolResult {
  content: Array<{ type: string; text: string }>;
  details?: Record<string, unknown>;
}

interface ExtensionAPI {
  on?: (event: string, handler: (event: Record<string, unknown>, ctx: Record<string, unknown>) => Promise<void> | void) => void;
  registerTool: (toolDef: {
    name: string;
    label?: string;
    description: string;
    promptSnippet?: string;
    parameters: Record<string, unknown>;
    execute: (id: string, params: Record<string, unknown>) => Promise<ToolResult>;
  }) => void;
}

const runCmd = (bin: string, args: string[], cwd?: string): Promise<{ ok: boolean; output: string }> => {
  const { promise, resolve } = Promise.withResolvers<{ ok: boolean; output: string }>();
  execFile(
    bin,
    args,
    {
      cwd: cwd || process.cwd(),
      timeout: 120_000,
      maxBuffer: 16_000_000,
      env: { ...process.env, PYTHONPATH: join(process.cwd(), "src") },
    },
    (err, stdout, stderr) => {
      if (err) {
        resolve({ ok: false, output: `Error: ${err.message}\n${stderr || ""}\n${stdout || ""}` });
      } else {
        resolve({ ok: true, output: stdout || stderr });
      }
    }
  );
  return promise;
};

export function resolveSotBinary(cwd: string = process.cwd()): string {
  const localBin = join(cwd, "bin", "sot");
  if (existsSync(localBin)) return localBin;
  return "sot";
}

export default function sotGraphExtension(pi: ExtensionAPI): void {
  const getSotBin = (): string => resolveSotBinary(process.cwd());

  // 1. sot_search: Verified Knowledge Search with Trust Verdicts
  pi.registerTool({
    name: "sot_search",
    label: "SOT Knowledge Search",
    description:
      "Search the verified Source-of-Truth knowledge graph with Trust Verdicts ([STRONG], [WEAK], [REBUILT]). Use BEFORE implementing features or refactoring to locate existing code and avoid hallucinating dead paths.",
    promptSnippet: "Search verified codebase knowledge, AST symbols, and functions",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Search query, symbol name, or technical topic" },
        limit: { type: "number", description: "Maximum number of results to return (default: 6)" },
        scope: { type: "string", description: "Optional directory or path prefix filter (e.g. 'src/sot_graph/')" },
        threshold: { type: "number", description: "Minimum content coverage score (0.0 - 1.0, default: 0.1)" },
      },
      required: ["query"],
    },
    async execute(_id, params) {
      const query = String(params.query || "");
      const limit = Number(params.limit ?? 6);
      const args = ["search", query, "-n", String(limit)];
      if (params.scope) args.push("--scope", String(params.scope));
      if (params.threshold !== undefined) args.push("--threshold", String(params.threshold));

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 2. sot_explore: AST Cross-file Graph Traversal
  pi.registerTool({
    name: "sot_explore",
    label: "SOT Graph Explore",
    description:
      "Explore inbound and outbound dependency relations for an AST symbol, class, or function. Reveals what calls this symbol and what this symbol calls across files.",
    promptSnippet: "Explore cross-file dependencies, callers, and callees",
    parameters: {
      type: "object",
      properties: {
        target: { type: "string", description: "Target symbol, function, or class name to trace" },
        depth: { type: "number", description: "Graph traversal depth (1 to 4, default: 2)" },
      },
      required: ["target"],
    },
    async execute(_id, params) {
      const target = String(params.target || "");
      const depth = Number(params.depth ?? 2);
      const args = ["explore", target, "--depth", String(depth)];

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 3. sot_reconcile: Sync Knowledge Graph with Filesystem
  pi.registerTool({
    name: "sot_reconcile",
    label: "SOT Reconcile",
    description:
      "Idempotently synchronize the knowledge graph with physical files on disk. Incrementally parses modified files and auto-purges deleted paths.",
    promptSnippet: "Sync knowledge graph with filesystem reality",
    parameters: {
      type: "object",
      properties: {
        paths: {
          type: "array",
          items: { type: "string" },
          description: "Optional specific files or directories to reconcile (default: whole project)",
        },
        workers: { type: "number", description: "Number of parallel worker processes (default: auto)" },
        batch_size: { type: "number", description: "Transaction batch size (default: 64)" },
      },
    },
    async execute(_id, params) {
      const args = ["reconcile"];
      if (params.workers) args.push("--workers", String(params.workers));
      if (params.batch_size) args.push("--batch-size", String(params.batch_size));
      if (Array.isArray(params.paths) && params.paths.length > 0) {
        args.push(...params.paths.map(String));
      }

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 4. sot_verify: Real-time Disk Verification & Drift Detection
  pi.registerTool({
    name: "sot_verify",
    label: "SOT Verify Drift",
    description:
      "Audit drift between the database index and actual disk reality without modifying the database.",
    promptSnippet: "Verify index freshness and detect drift against disk",
    parameters: {
      type: "object",
      properties: {
        deep: { type: "boolean", description: "Perform full SHA-256 content verification (default: false)" },
      },
    },
    async execute(_id, params) {
      const args = ["verify"];
      if (params.deep) args.push("--deep");

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 5. sot_doctor: Database Diagnostics & Statistics
  pi.registerTool({
    name: "sot_doctor",
    label: "SOT Doctor",
    description:
      "Inspect knowledge graph health: total nodes, resolved edges, pending relations, file journals, and SQLite page usage.",
    promptSnippet: "Inspect knowledge graph statistics and health",
    parameters: {
      type: "object",
      properties: {},
    },
    async execute() {
      const { ok, output } = await runCmd(getSotBin(), ["doctor"]);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 6. sot_insert: Record Knowledge Node / Architectural Anchor
  pi.registerTool({
    name: "sot_insert",
    label: "SOT Insert Note",
    description:
      "Record an architectural decision, pattern, or tricky fix into the persistent knowledge graph for future sessions.",
    promptSnippet: "Record reusable architectural knowledge or solution pattern",
    parameters: {
      type: "object",
      properties: {
        title: { type: "string", description: "Short title of the architectural note or pattern" },
        body: { type: "string", description: "Detailed explanation, trade-offs, or solution steps" },
        path: { type: "string", description: "Optional associated file path" },
        keywords: { type: "string", description: "Optional comma-separated tags/keywords" },
      },
      required: ["title", "body"],
    },
    async execute(_id, params) {
      const args = ["insert", "--title", String(params.title || ""), "--body", String(params.body || "")];
      if (params.path) args.push("--path", String(params.path));
      if (params.keywords) args.push("--keywords", String(params.keywords));

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 7. sot_cluster: Community Detection & Modularity Q
  pi.registerTool({
    name: "sot_cluster",
    label: "SOT Cluster Graph",
    description:
      "Run Louvain / Label Propagation community detection to discover architectural clusters, Modularity (Q), and module Cohesion scores.",
    promptSnippet: "Run graph clustering to discover functional communities and modularity",
    parameters: {
      type: "object",
      properties: {
        scope: { type: "string", description: "Optional directory prefix to restrict clustering scope" },
      },
    },
    async execute(_id, params) {
      const args = ["cluster"];
      if (params.scope) args.push("--scope", String(params.scope));

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 8. sot_report: Architecture Health & God Node Blast Radius
  pi.registerTool({
    name: "sot_report",
    label: "SOT Architecture Report",
    description:
      "Generate comprehensive architectural diagnostics: God Nodes with 2-hop Blast Radius, Surprising Cross-Cutting Connections, and Modularity score.",
    promptSnippet: "Generate architecture report and identify God Node blast radius",
    parameters: {
      type: "object",
      properties: {
        scope: { type: "string", description: "Optional directory scope" },
        output: { type: "string", description: "File path to save Markdown report (default: print to stdout)" },
      },
    },
    async execute(_id, params) {
      const args = ["report"];
      if (params.scope) args.push("--scope", String(params.scope));
      if (params.output) args.push("-o", String(params.output));

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 9. sot_viz: Interactive D3.js Visualizer
  pi.registerTool({
    name: "sot_viz",
    label: "SOT Generate HTML Visualizer",
    description:
      "Generate an interactive, standalone HTML knowledge graph visualizer with force-directed physics, search filtering, and node pinning.",
    promptSnippet: "Generate interactive HTML knowledge graph visualizer",
    parameters: {
      type: "object",
      properties: {
        output: { type: "string", description: "Output HTML file path (default: sot_graph.html)" },
        open: { type: "boolean", description: "Automatically open in default web browser" },
      },
    },
    async execute(_id, params) {
      const args = ["viz"];
      if (params.output) args.push("-o", String(params.output));
      if (params.open) args.push("--open");

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 10. sot_export: Multi-Format Knowledge Graph Exporter
  pi.registerTool({
    name: "sot_export",
    label: "SOT Export Graph",
    description:
      "Export the knowledge graph in standard open formats: 'graphrag' (hierarchical JSON dataset), 'obsidian' (Markdown vault), or 'graphml' (Gephi / Cytoscape XML).",
    promptSnippet: "Export knowledge graph to GraphRAG JSON, Obsidian Vault, or GraphML",
    parameters: {
      type: "object",
      properties: {
        format: {
          type: "string",
          enum: ["graphrag", "obsidian", "graphml"],
          description: "Target export format (graphrag | obsidian | graphml)",
        },
        output: { type: "string", description: "Destination file or directory path" },
        scope: { type: "string", description: "Optional directory prefix filter" },
      },
      required: ["format"],
    },
    async execute(_id, params) {
      const args = ["export", "--format", String(params.format)];
      if (params.output) args.push("-o", String(params.output));
      if (params.scope) args.push("--scope", String(params.scope));

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 11. sot_bundle: Fact Bundle Extractor for LLM Architecture Reports
  pi.registerTool({
    name: "sot_bundle",
    label: "SOT Architecture Fact Bundler",
    description:
      "Extract 5 high-density architecture fact bundle markdown/json files (01_module_inventory.md, 02_routing_endpoints.md, 03_workflows_states.md, 04_dependencies_violations.md, 05_system_metrics.json) into .sot/bundle/ for LLM synthesis of comprehensive architecture reports.",
    promptSnippet: "Extract 5 architecture fact bundle files for LLM report synthesis",
    parameters: {
      type: "object",
      properties: {
        output: { type: "string", description: "Target directory path (default: .sot/bundle/)" },
        json: { type: "boolean", description: "Output in JSON format" },
      },
    },
    async execute(_id, params) {
      const args = ["bundle"];
      if (params.output) args.push("-o", String(params.output));
      if (params.json) args.push("--json");

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // Optional Hook: check graph status on session start
  if (typeof pi.on === "function") {
    pi.on("session_start", async () => {
      try {
        const cwd = process.cwd();
        const dbPath = join(cwd, ".sot", "sot.db");
        if (!existsSync(dbPath)) {
          // Trigger initial silent reconcile if database doesn't exist
          const bin = resolveSotBinary(cwd);
          if (existsSync(bin)) {
            await runCmd(bin, ["reconcile"], cwd);
          }
        }
      } catch {
        // Non-blocking fallback
      }
    });
  }
}
