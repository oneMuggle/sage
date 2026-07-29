/**
 * Orphan backend killer — pure function.
 *
 * On Windows, a previous Electron main process may have crashed without
 * running `shutdownBackend()`, leaving a Python backend still listening
 * on port 8765. When a new main process spawns its own backend, both
 * compete for the same port (Windows SO_REUSEADDR allows it), and HTTP
 * requests from the frontend may be routed to the stale process whose
 * DB state is inconsistent — causing 500 errors and a white screen.
 *
 * This module detects and kills any *other* process listening on the
 * backend port before the new backend is spawned. It is a no-op on
 * non-Windows platforms (where the OS cleans up child processes more
 * reliably and `lsof`-style cleanup is more disruptive than helpful).
 *
 * Design: pure function with injectable `execSyncFn` so unit tests can
 * stage netstat/taskkill output without spawning real processes.
 */

import { execSync as defaultExecSync } from 'node:child_process';

export interface KillOrphanOpts {
  /** TCP port to reclaim (default backend port 8765). */
  port: number;
  /** `process.platform` snapshot — only `'win32'` triggers cleanup. */
  platform: NodeJS.Platform;
  /** `process.pid` — never kill ourselves. */
  selfPid: number;
  /** Injected `execSync` for testing. Defaults to `node:child_process`. */
  execSyncFn?: (cmd: string, opts?: { encoding: string }) => string;
}

export type KillOrphanResult =
  | { kind: 'skipped'; reason: 'non-windows' }
  | { kind: 'none-found' }
  | { kind: 'killed'; pids: string[] }
  | { kind: 'error'; error: string };

/**
 * Find and kill processes listening on `port` (Windows only).
 *
 * Safe guards:
 * - No-op on non-Windows platforms.
 * - Never kills the current process (`selfPid`).
 * - Never kills PID 0 / PID 1 / empty PIDs.
 * - Catches all exec errors and returns them as `KillOrphanResult`
 *   rather than throwing — startup must not crash on cleanup failure.
 */
export function killOrphanedBackendOnPort(opts: KillOrphanOpts): KillOrphanResult {
  if (opts.platform !== 'win32') {
    return { kind: 'skipped', reason: 'non-windows' };
  }

  const execSyncFn =
    opts.execSyncFn ?? ((cmd: string) => defaultExecSync(cmd, { encoding: 'utf8' }));

  // Step 1: Find PIDs listening on the port via netstat.
  //
  // Example netstat output (Windows):
  //   TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    12345
  //   TCP    [::]:8765       [::]:0       LISTENING    12345
  //
  // We filter for `:<port>` in the local address column and `LISTENING`
  // state, then extract the PID (last column).
  let netstatOutput: string;
  try {
    netstatOutput = execSyncFn(`netstat -ano | findstr :${opts.port} | findstr LISTENING`, {
      encoding: 'utf8',
    });
  } catch {
    // `findstr` exits with code 1 when no lines match — that's the
    // happy "no orphan" case, not an error.
    return { kind: 'none-found' };
  }

  // Step 2: Extract unique PIDs from netstat output.
  const pids = extractPidsFromNetstat(netstatOutput, opts.selfPid);
  if (pids.length === 0) {
    return { kind: 'none-found' };
  }

  // Step 3: Kill each orphaned PID.
  const killedPids: string[] = [];
  for (const pid of pids) {
    try {
      execSyncFn(`taskkill /PID ${pid} /F`, { encoding: 'utf8' });
      killedPids.push(pid);
    } catch {
      // Process may have exited between netstat and taskkill — that's
      // fine, the port is freed either way. Log and continue.
    }
  }

  return killedPids.length > 0
    ? { kind: 'killed', pids: killedPids }
    : { kind: 'none-found' };
}

/**
 * Parse netstat output and return unique PIDs, filtering out unsafe values.
 *
 * Exported for unit testing.
 */
export function extractPidsFromNetstat(netstatOutput: string, selfPid: number): string[] {
  const seen = new Set<string>();
  const result: string[] = [];

  for (const rawLine of netstatOutput.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;

    // netstat columns: Proto | LocalAddr | ForeignAddr | State | PID
    // Split on whitespace; PID is the last non-empty token.
    const tokens = line.split(/\s+/).filter(Boolean);
    if (tokens.length < 5) continue;

    const pid = tokens[tokens.length - 1];

    // Safety: skip non-numeric, zero, init, or self PIDs.
    if (!/^\d+$/.test(pid)) continue;
    if (pid === '0' || pid === '1') continue;
    if (Number(pid) === selfPid) continue;

    if (!seen.has(pid)) {
      seen.add(pid);
      result.push(pid);
    }
  }

  return result;
}
