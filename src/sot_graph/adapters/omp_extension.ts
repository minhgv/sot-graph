/**
 * sot_omp_extension.ts — OMP (Oh My Pi) Native Extension for SOT-Graph.
 * 
 * Exposes SOT-Graph capabilities as native agent tools:
 * - sot_search: Verified Knowledge & AST Symbol Search with Trust Verdicts
 * - sot_map: Token-budgeted PageRank Architectural Repository Mapping
 * - sot_explore: Cross-file AST Call Graph & Dependency Exploration
 * - sot_usages: Exact Call-site and Reference Site Inspection
 * - sot_implementations: Interface and Subclass Implementation Traversal
 * - sot_rename: Safe Structural Symbol Rename Planning
 * - sot_pack: k-Hop Subgraph ContextBundle Packaging for Prompt Compression
 * - sot_reconcile: Idempotent Single-Writer Knowledge Graph Synchronization
 * - sot_verify: Real-time Disk Verification & Drift Detection
 * - sot_doctor: Database Diagnostics & Graph Health Statistics
 * - sot_clean: Stale Data & Deleted File Purging
 * - sot_vacuum: SQLite Freelist Compaction & Storage Optimization
 * - sot_insert: Persistent Knowledge Anchors & Note Recording
 * - sot_cluster: Louvain / Label Propagation Community Detection
 * - sot_report: Architecture Assessment & God Node Blast Radius
 * - sot_viz: Interactive D3.js Knowledge Graph Visualizer Generation
 * - sot_export: Multi-format Graph Export (GraphRAG JSON, Obsidian, GraphML, SCIP)
 * - sot_bundle: Architecture Fact Bundler for LLM Report Synthesis
 * - sot_diff_impact: Git Diff Blast Radius & API Impact Analysis
 * - sot_git_history: Git Commit History Risk Scoring & Symbol Detection
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
        hybrid: { type: "boolean", description: "Enable hybrid vector + FTS5 search (if vector extra installed)" },
      },
      required: ["query"],
    },
    async execute(_id, params) {
      const query = String(params.query || "");
      const limit = Number(params.limit ?? 6);
      const args = ["search", query, "-n", String(limit)];
      if (params.scope) args.push("--scope", String(params.scope));
      if (params.threshold !== undefined) args.push("--threshold", String(params.threshold));
      if (params.hybrid) args.push("--hybrid");

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 2. sot_map: Token-budgeted PageRank Repository Mapping
  pi.registerTool({
    name: "sot_map",
    label: "SOT Repository Map",
    description:
      "Generate a token-budgeted architectural repository map ranked by personalized PageRank. Use for top-down orientation across unfamiliar codebases.",
    promptSnippet: "Generate PageRank-ranked repository architecture map",
    parameters: {
      type: "object",
      properties: {
        focus: { type: "string", description: "Comma-separated symbols or topics to personalize ranking" },
        tokens: { type: "number", description: "Approximate token budget (default: 1024)" },
      },
    },
    async execute(_id, params) {
      const args = ["map"];
      if (params.focus) args.push("--focus", String(params.focus));
      if (params.tokens) args.push("--tokens", String(params.tokens));

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 3. sot_explore: AST Cross-file Graph Traversal
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

  // 4. sot_usages: Inspect Exact Call-Sites & References
  pi.registerTool({
    name: "sot_usages",
    label: "SOT Symbol Usages",
    description:
      "List every physical reference site and invocation of a symbol across the codebase, grouped by caller. Essential before changing signatures.",
    promptSnippet: "List all call-sites and reference locations of a symbol",
    parameters: {
      type: "object",
      properties: {
        target: { type: "string", description: "Symbol, function name, or class to inspect" },
      },
      required: ["target"],
    },
    async execute(_id, params) {
      const target = String(params.target || "");
      const args = ["usages", target];

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 5. sot_implementations: Interface and Inheritance Discovery
  pi.registerTool({
    name: "sot_implementations",
    label: "SOT Implementations",
    description:
      "Discover all concrete classes implementing an interface/trait or extending a base class across modules.",
    promptSnippet: "List concrete classes implementing an interface or base class",
    parameters: {
      type: "object",
      properties: {
        target: { type: "string", description: "Base class, interface, or trait name to inspect" },
      },
      required: ["target"],
    },
    async execute(_id, params) {
      const target = String(params.target || "");
      const args = ["implementations", target];

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 6. sot_rename: Safe Structural Symbol Rename Planning
  pi.registerTool({
    name: "sot_rename",
    label: "SOT Rename Impact",
    description:
      "Generate an impact plan and preview call-site updates for renaming a symbol across the codebase.",
    promptSnippet: "Plan and inspect symbol rename impact across codebase",
    parameters: {
      type: "object",
      properties: {
        target: { type: "string", description: "Current symbol name to rename" },
        to: { type: "string", description: "Proposed new symbol name" },
      },
      required: ["target"],
    },
    async execute(_id, params) {
      const target = String(params.target || "");
      const args = ["rename", target];
      if (params.to) args.push("--to", String(params.to));

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 7. sot_pack: k-Hop Subgraph ContextBundle Packaging
  pi.registerTool({
    name: "sot_pack",
    label: "SOT Pack ContextBundle",
    description:
      "Package a k-hop Subgraph ContextBundle (YAML/Markdown) for AI agent prompt registers. Reduces context token consumption by ~70% compared to reading raw files.",
    promptSnippet: "Package k-hop subgraph context bundle for token efficiency",
    parameters: {
      type: "object",
      properties: {
        target: { type: "string", description: "Target root symbol or fully-qualified name" },
        depth: { type: "number", description: "Graph traversal depth (default: 2)" },
        output: { type: "string", description: "Optional output file path" },
      },
      required: ["target"],
    },
    async execute(_id, params) {
      const target = String(params.target || "");
      const args = ["pack", target];
      if (params.depth) args.push("--depth", String(params.depth));
      if (params.output) args.push("-o", String(params.output));

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 8. sot_reconcile: Sync Knowledge Graph with Filesystem
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

  // 9. sot_verify: Real-time Disk Verification & Drift Detection
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

  // 10. sot_doctor: Database Diagnostics & Statistics
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

  // 11. sot_clean: Stale Data & Deleted File Purging
  pi.registerTool({
    name: "sot_clean",
    label: "SOT Clean Stale Data",
    description:
      "Safely purge stale nodes, dangling edges, or reset generated graph data.",
    promptSnippet: "Clean stale nodes or reset graph data safely",
    parameters: {
      type: "object",
      properties: {
        all: { type: "boolean", description: "Reset all generated graph data" },
        include_notes: { type: "boolean", description: "Include persistent notes in reset" },
        dry_run: { type: "boolean", description: "Preview clean plan without modifying database" },
      },
    },
    async execute(_id, params) {
      const args = ["clean"];
      if (params.all) args.push("--all");
      if (params.include_notes) args.push("--include-notes");
      if (params.dry_run) args.push("--dry-run");

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 12. sot_vacuum: SQLite Storage Compaction
  pi.registerTool({
    name: "sot_vacuum",
    label: "SOT Vacuum Database",
    description:
      "Compact SQLite database file and reclaim unallocated freelist pages.",
    promptSnippet: "Compact SQLite database and optimize freelist pages",
    parameters: {
      type: "object",
      properties: {
        analyze: { type: "boolean", description: "Run PRAGMA optimize after vacuum" },
        dry_run: { type: "boolean", description: "Report reclaimable space without mutating" },
      },
    },
    async execute(_id, params) {
      const args = ["vacuum"];
      if (params.analyze) args.push("--analyze");
      if (params.dry_run) args.push("--dry-run");

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 13. sot_insert: Record Knowledge Node / Architectural Anchor
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

  // 14. sot_cluster: Community Detection & Modularity Q
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
        min_size: { type: "number", description: "Minimum community size (default: 1)" },
      },
    },
    async execute(_id, params) {
      const args = ["cluster"];
      if (params.scope) args.push("--scope", String(params.scope));
      if (params.min_size) args.push("--min-size", String(params.min_size));

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 15. sot_report: Architecture Health & God Node Blast Radius
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

  // 16. sot_viz: Interactive D3.js Visualizer
  pi.registerTool({
    name: "sot_viz",
    label: "SOT Generate HTML Visualizer",
    description:
      "Generate an interactive, standalone HTML knowledge graph visualizer with force-directed physics, search filtering, and node pinning.",
    promptSnippet: "Generate interactive HTML knowledge graph visualizer",
    parameters: {
      type: "object",
      properties: {
        output: { type: "string", description: "Output HTML file path (default: graph.html)" },
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

  // 17. sot_export: Multi-Format Knowledge Graph Exporter
  pi.registerTool({
    name: "sot_export",
    label: "SOT Export Graph",
    description:
      "Export the knowledge graph in standard open formats: 'graphrag' (hierarchical JSON dataset), 'obsidian' (Markdown vault), 'graphml' (Gephi / Cytoscape XML), or 'scip'.",
    promptSnippet: "Export knowledge graph to GraphRAG JSON, Obsidian Vault, GraphML, or SCIP",
    parameters: {
      type: "object",
      properties: {
        format: {
          type: "string",
          enum: ["graphrag", "obsidian", "graphml", "scip"],
          description: "Target export format (graphrag | obsidian | graphml | scip)",
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

  // 18. sot_bundle: Fact Bundle Extractor for LLM Architecture Reports
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

  // 19. sot_trace: Full-Stack Execution & Visual Interaction Trace
  pi.registerTool({
    name: "sot_trace",
    label: "SOT Full-Stack Trace",
    description:
      "Extract Full-Stack execution path, UI decision branches, API contracts, and deterministic Mermaid diagrams (flowchart and sequence) for a ticket, keyword, or endpoint.",
    promptSnippet: "Extract full-stack trace and render Mermaid interaction diagrams",
    parameters: {
      type: "object",
      properties: {
        target: { type: "string", description: "Ticket ID, symbol name, endpoint, or feature keyword" },
        depth: { type: "number", description: "Exploration depth (default: 2)" },
        output: { type: "string", description: "Write trace report to file" },
        json: { type: "boolean", description: "Output raw structured JSON" },
      },
      required: ["target"],
    },
    async execute(_id, params) {
      const args = ["trace", String(params.target || "")];
      if (params.depth) args.push("--depth", String(params.depth));
      if (params.output) args.push("-o", String(params.output));
      if (params.json) args.push("--json");

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 20. sot_ui_tree: Frontend UI Decision Tree & Modals
  pi.registerTool({
    name: "sot_ui_tree",
    label: "SOT UI Decision Tree",
    description:
      "Extract Frontend UI decision tree, validation rules, button triggers, and modal transitions.",
    promptSnippet: "Extract local UI decision tree and modal branches",
    parameters: {
      type: "object",
      properties: {
        component: { type: "string", description: "Component name or file path" },
        json: { type: "boolean", description: "Output raw JSON" },
      },
      required: ["component"],
    },
    async execute(_id, params) {
      const args = ["ui-tree", String(params.component || "")];
      if (params.json) args.push("--json");

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 21. sot_backend_flow: Backend Micro-steps & Datasources
  pi.registerTool({
    name: "sot_backend_flow",
    label: "SOT Backend Flow",
    description:
      "Extract Backend service micro-steps, multi-datasources, and exception handling branches.",
    promptSnippet: "Extract backend processing steps and multi-datasource connections",
    parameters: {
      type: "object",
      properties: {
        service: { type: "string", description: "Service or controller symbol name" },
        json: { type: "boolean", description: "Output raw JSON" },
      },
      required: ["service"],
    },
    async execute(_id, params) {
      const args = ["be-flow", String(params.service || "")];
      if (params.json) args.push("--json");

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 22. sot_solution_inventory: Stage 1 Feature Inventory by Role
  pi.registerTool({
    name: "sot_solution_inventory",
    label: "SOT Solution Feature Inventory",
    description:
      "Discover all features by user role and 10 related feature categories for Stage 1 Solution documentation.",
    promptSnippet: "Scan module and generate Stage 1 Feature Inventory",
    parameters: {
      type: "object",
      properties: {
        module: { type: "string", description: "Module or subsystem name (default: all)" },
        output: { type: "string", description: "Output markdown file path" },
        json: { type: "boolean", description: "Output JSON format" },
      },
    },
    async execute(_id, params) {
      const args = ["solution", "inventory"];
      if (params.module) args.push(String(params.module));
      if (params.output) args.push("-o", String(params.output));
      if (params.json) args.push("--json");

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 23. sot_solution_steps: Stage 2 Micro-step Decomposition (4-Column Table)
  pi.registerTool({
    name: "sot_solution_steps",
    label: "SOT Solution Micro-Steps",
    description:
      "Extract Stage 2 micro-step decomposition (4-column table: TT, Name, Code Statement, Logic) with verified AST execution code for Manpower NVJ1/NVJ2/NVJ3 estimation.",
    promptSnippet: "Decompose method into 4-column execution table for manpower estimation",
    parameters: {
      type: "object",
      properties: {
        method: { type: "string", description: "Service or method symbol to decompose" },
        format: { type: "string", description: "Output format: 'table' or 'json' (default: table)" },
        output: { type: "string", description: "Output file path" },
      },
      required: ["method"],
    },
    async execute(_id, params) {
      const args = ["solution", "steps", String(params.method || "")];
      if (params.format) args.push("--format", String(params.format));
      if (params.output) args.push("-o", String(params.output));

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 24. sot_solution_bundle: Stage 2 Full Solution Context Bundle
  pi.registerTool({
    name: "sot_solution_bundle",
    label: "SOT Solution Context Bundle",
    description:
      "Synthesize complete Context Bundle (UI forms, DataTable schemas, API specs, diagrams) for Solution.md and downstream agents without raw source re-reading.",
    promptSnippet: "Generate complete Solution Context Bundle for downstream docs",
    parameters: {
      type: "object",
      properties: {
        module: { type: "string", description: "Module name (default: all)" },
        output: { type: "string", description: "Output file path (default: .sot/bundle/ContextBundle.md)" },
        json: { type: "boolean", description: "Output JSON format" },
      },
    },
    async execute(_id, params) {
      const args = ["solution", "bundle"];
      if (params.module) args.push(String(params.module));
      if (params.output) args.push("-o", String(params.output));
      if (params.json) args.push("--json");

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 25. sot_diff_impact: Git Diff Blast Radius & Impact Analysis
  pi.registerTool({
    name: "sot_diff_impact",
    label: "SOT Diff Impact Analysis",
    description:
      "Analyze git diff blast radius, upstream inward callers, API contract impacts, and affected tests.",
    promptSnippet: "Analyze blast radius and upstream caller impact for git diff/revisions",
    parameters: {
      type: "object",
      properties: {
        target: { type: "string", description: "Git revision target (e.g. 'HEAD~1', 'main...HEAD', commit hash; default: 'HEAD~1')" },
        depth: { type: "number", description: "Reverse call graph traversal depth (default: 2)" },
        staged: { type: "boolean", description: "Analyze staged changes (--cached)" },
        workingTree: { type: "boolean", description: "Analyze unstaged working tree changes" },
        autoReconcile: { type: "boolean", description: "Reconcile knowledge graph before analyzing impact" },
        format: { type: "string", description: "Output format: 'markdown' or 'json'" },
        json: { type: "boolean", description: "Output raw JSON" },
      },
    },
    async execute(_id, params) {
      const args = ["diff-impact"];
      if (params.target) args.push(String(params.target));
      if (params.depth) args.push("--depth", String(params.depth));
      if (params.staged) args.push("--staged");
      if (params.workingTree) args.push("--working-tree");
      if (params.autoReconcile) args.push("--auto-reconcile");
      if (params.json || params.format === "json") args.push("--json");

      const { ok, output } = await runCmd(getSotBin(), args);
      return { content: [{ type: "text", text: output.trim() }], details: { ok } };
    },
  });

  // 26. sot_git_history: Git Commit History Risk Scoring & Impacted Symbols
  pi.registerTool({
    name: "sot_git_history",
    label: "SOT Git History & Risk Scoring",
    description:
      "Inspect git commit history with automated risk scoring and impacted symbol detection.",
    promptSnippet: "Inspect git commit history with risk scoring and symbol impact",
    parameters: {
      type: "object",
      properties: {
        limit: { type: "number", description: "Maximum commits to evaluate (default: 10)" },
        author: { type: "string", description: "Filter commits by author" },
        since: { type: "string", description: "Filter commits since date/time (e.g. '2026-01-01' or '2.weeks')" },
        impact: { type: "boolean", description: "Enable or disable knowledge graph symbol impact analysis (default: true)" },
        json: { type: "boolean", description: "Output raw JSON format" },
      },
    },
    async execute(_id, params) {
      const args = ["log"];
      if (params.limit) args.push("-n", String(params.limit));
      if (params.author) args.push("--author", String(params.author));
      if (params.since) args.push("--since", String(params.since));
      if (params.impact === false) args.push("--no-impact");
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
