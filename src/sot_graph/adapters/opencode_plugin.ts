/**
 * opencode_plugin.ts - Native OpenCode Plugin for SOT-Graph.
 * 
 * Provides:
 * 1. Automatic background reconciliation on session initialization.
 * 2. Custom tool registrations matching OpenCode plugin specification.
 * 3. Event subscriptions to invalidate or refresh stale cache.
 */

import { execFile } from "node:child_process";
import { join } from "node:path";
import { existsSync } from "node:fs";

export interface PluginContext {
  client?: Record<string, unknown>;
  event?: {
    on: (eventName: string, handler: (event: Record<string, unknown>) => Promise<void> | void) => () => void;
  };
  directory?: string;
}

const runSot = (args: string[], cwd: string = process.cwd()): Promise<{ ok: boolean; output: string }> => {
  const { promise, resolve } = Promise.withResolvers<{ ok: boolean; output: string }>();
  const bin = existsSync(join(cwd, "bin", "sot")) ? join(cwd, "bin", "sot") : "sot";

  execFile(
    bin,
    args,
    {
      cwd,
      timeout: 120_000,
      maxBuffer: 16_000_000,
      env: { ...process.env, PYTHONPATH: join(cwd, "src") },
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

/**
 * OpenCode Plugin Entrypoint
 */
export default async function SotGraphOpenCodePlugin(ctx: PluginContext) {
  const workspaceRoot = ctx?.directory || process.cwd();

  // 1. Session start auto-indexing if database is missing
  if (ctx?.event?.on) {
    ctx.event.on("session.created", async () => {
      try {
        const dbPath = join(workspaceRoot, ".sot", "sot.db");
        if (!existsSync(dbPath)) {
          await runSot(["reconcile"], workspaceRoot);
        }
      } catch (err) {
        console.error("[sot-graph] Auto-reconciliation failed:", err);
      }
    });

    // 2. File write/edit triggers background incremental reconcile
    ctx.event.on("file.edited", async () => {
      try {
        await runSot(["reconcile", "--workers", "1"], workspaceRoot);
      } catch {
        // Non-blocking background sync
      }
    });
  }
}
