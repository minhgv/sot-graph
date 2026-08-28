/**
 * opencode_plugin.ts - Native OpenCode Plugin for SOT-Graph.
 * 
 * Provides:
 * 1. Automatic background reconciliation on session initialization.
 * 2. Custom tool registrations matching OpenCode plugin specification.
 * 3. Event subscriptions to invalidate or refresh stale cache.
 */

import { execFile } from "node:child_process";
import { accessSync, constants, existsSync, realpathSync, statSync } from "node:fs";
import { delimiter, isAbsolute, join, relative, resolve, sep } from "node:path";

const DEFAULT_WINDOWS_PATHEXT = [".COM", ".EXE", ".BAT", ".CMD"];

const environmentValue = (env: NodeJS.ProcessEnv, name: string): string | undefined => {
  const directValue = env[name];
  if (directValue !== undefined) return directValue;
  const normalizedName = name.toLowerCase();
  return Object.entries(env).find(([key]) => key.toLowerCase() === normalizedName)?.[1];
};

const pathDelimiter = (platform: NodeJS.Platform): string => (platform === "win32" ? ";" : delimiter);

const canonicalPath = (path: string): string => {
  try {
    return realpathSync(path);
  } catch {
    return path;
  }
};

const canonicalExistingPath = (path: string): string | undefined => {
  try {
    return realpathSync(path);
  } catch {
    return undefined;
  }
};

const isWithin = (root: string, candidate: string, platform: NodeJS.Platform = process.platform): boolean => {
  const comparisonRoot = platform === "win32" ? root.toLowerCase() : root;
  const comparisonCandidate = platform === "win32" ? candidate.toLowerCase() : candidate;
  const relativePath = relative(comparisonRoot, comparisonCandidate);
  return relativePath === "" || (!relativePath.startsWith(`..${sep}`) && relativePath !== ".." && !isAbsolute(relativePath));
};

const commandEnvironment = (cwd: string, platform: NodeJS.Platform = process.platform): NodeJS.ProcessEnv => {
  const env: NodeJS.ProcessEnv = { ...process.env };
  const pathValue = environmentValue(env, "PATH");

  // Environment variable names are case-insensitive on Windows. Remove every
  // variant before publishing the filtered canonical PATH.
  for (const key of Object.keys(env)) {
    const normalizedKey = key.toLowerCase();
    if (normalizedKey === "pythonpath" || normalizedKey === "path") delete env[key];
  }

  if (pathValue !== undefined) {
    const workspaceRoot = canonicalPath(resolve(cwd));
    env.PATH = pathValue
      .split(pathDelimiter(platform))
      .flatMap((entry) => {
        const originalEntryPath = resolve(cwd, entry || ".");
        const canonicalEntryPath = canonicalPath(originalEntryPath);
        const originalSotPath = join(originalEntryPath, "sot");
        const canonicalSotPath = canonicalPath(originalSotPath);
        const pathsToCheck = [
          originalEntryPath,
          canonicalEntryPath,
          originalSotPath,
          canonicalSotPath,
        ];
        if (pathsToCheck.some((candidate) => isWithin(workspaceRoot, candidate, platform))) {
          return [];
        }
        return [canonicalEntryPath];
      })
      .join(pathDelimiter(platform));
  }
  return env;
};

const windowsPathSuffixes = (env: NodeJS.ProcessEnv): string[] => {
  const configuredPathext = environmentValue(env, "PATHEXT");
  const configuredSuffixes = (configuredPathext ?? DEFAULT_WINDOWS_PATHEXT.join(";"))
    .split(";")
    .map((suffix) => suffix.trim())
    .filter((suffix) => /^\.[^./\\]+$/.test(suffix));
  return configuredSuffixes.length > 0 ? configuredSuffixes : DEFAULT_WINDOWS_PATHEXT;
};

const isExecutableFile = (path: string, platform: NodeJS.Platform): boolean => {
  try {
    if (!statSync(path).isFile()) return false;
    if (platform !== "win32") accessSync(path, constants.X_OK);
    return true;
  } catch {
    return false;
  }
};

export interface PluginContext {
  client?: Record<string, unknown>;
  event?: {
    on: (eventName: string, handler: (event: Record<string, unknown>) => Promise<void> | void) => () => void;
  };
  directory?: string;
}

const runSot = (args: string[], cwd: string = process.cwd()): Promise<{ ok: boolean; output: string }> => {
  const commandCwd = cwd || process.cwd();
  const bin = resolveSotBinary(commandCwd);
  if (bin === undefined || !isAbsolute(bin)) {
    return Promise.resolve({ ok: false, output: "Error: sot executable not found on trusted PATH" });
  }

  const { promise, resolve: resolvePromise } = Promise.withResolvers<{ ok: boolean; output: string }>();
  execFile(
    bin,
    args,
    {
      cwd: commandCwd,
      timeout: 120_000,
      maxBuffer: 16_000_000,
      env: commandEnvironment(commandCwd),
    },
    (err, stdout, stderr) => {
      if (err) {
        resolvePromise({ ok: false, output: `Error: ${err.message}\n${stderr || ""}\n${stdout || ""}` });
      } else {
        resolvePromise({ ok: true, output: stdout || stderr });
      }
    }
  );

  return promise;
};

export function resolveSotBinary(cwd: string = process.cwd(), platform: NodeJS.Platform = process.platform): string | undefined {
  const commandCwd = cwd || process.cwd();
  const env = commandEnvironment(commandCwd, platform);
  const pathValue = env.PATH;
  if (pathValue === undefined) return undefined;

  const workspaceRoot = canonicalPath(resolve(commandCwd));
  const candidateNames =
    platform === "win32" ? windowsPathSuffixes(env).map((suffix) => `sot${suffix}`) : ["sot"];
  for (const pathEntry of pathValue.split(pathDelimiter(platform))) {
    if (!pathEntry) continue;
    const canonicalDirectory = canonicalExistingPath(pathEntry);
    if (
      canonicalDirectory === undefined ||
      !isAbsolute(canonicalDirectory) ||
      isWithin(workspaceRoot, pathEntry, platform) ||
      isWithin(workspaceRoot, canonicalDirectory, platform)
    ) {
      continue;
    }

    for (const candidateName of candidateNames) {
      const candidatePath = join(canonicalDirectory, candidateName);
      if (!isAbsolute(candidatePath) || isWithin(workspaceRoot, candidatePath, platform)) continue;

      const canonicalCandidate = canonicalExistingPath(candidatePath);
      if (
        canonicalCandidate === undefined ||
        !isAbsolute(canonicalCandidate) ||
        isWithin(workspaceRoot, canonicalCandidate, platform) ||
        !isExecutableFile(canonicalCandidate, platform)
      ) {
        continue;
      }
      return canonicalCandidate;
    }
  }
  return undefined;
}

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
