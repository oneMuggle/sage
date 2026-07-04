// electron/logPaths.ts

/**
 * Resolves and caches the log directory path for the Electron main process.
 *
 * `SAGE_LOG_DIR` is the BASE directory; sage log files always live under
 * `${SAGE_LOG_DIR}/logs/`. This matches the convention used by logger.ts
 * (electron/logger.ts) — keep them in sync if you change one.
 *
 * The directory is created lazily on first access and memoized for the
 * lifetime of the process.
 */

import { mkdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { app } from 'electron';

let cachedDir: string | null = null;

export function getLogDir(): string {
  if (cachedDir) return cachedDir;
  // SAGE_LOG_DIR is the BASE directory; sage files always go in `${SAGE_LOG_DIR}/logs/`.
  // This matches logger.ts (T4) and aligns with T3 test expectations.
  const base = process.env.SAGE_LOG_DIR ?? app.getPath('userData');
  const dir = join(base, 'logs');
  if (!existsSync(dir)) {
    try {
      mkdirSync(dir, { recursive: true });
    } catch (err) {
      console.error('[logPaths] failed to create log dir:', err);
    }
  }
  cachedDir = dir;
  return dir;
}

export function getCurrentLogFile(): string {
  const today = new Date().toISOString().slice(0, 10);
  return join(getLogDir(), `sage-${today}.ndjson`);
}
