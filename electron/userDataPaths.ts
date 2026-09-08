// electron/userDataPaths.ts

/**
 * Resolve SAGE_DB_PATH and SAGE_USER_DATA_DIR with a single, consistent
 * rule so the backend supervisor and the doctor supervisor never disagree.
 *
 * Why a dedicated module (2026-09-08):
 *   Pre-fix, ``electron/main.ts`` had the resolver inlined twice with
 *   subtly different fallbacks:
 *     - backend spawn (line 278-285): ``app.isPackaged ? userData : cwd/data``
 *     - doctor spawn  (line 1642-1643): ``cwd/data`` unconditionally
 *   On a packaged Win7 install where ``process.cwd()`` resolves to the
 *   install dir (e.g. ``C:\Program Files\Sage``), the doctor subprocess
 *   probed Program Files instead of ``%APPDATA%\Sage``, producing three
 *   false-positive CRITICAL verdicts (``conda_env``,
 *   ``sqlite_writable``, ``runtime_env``). Both call sites now go
 *   through ``resolveSageDbPath`` / ``resolveSageUserDataDir`` so the
 *   bug cannot recur without breaking both helpers' tests.
 *
 * Priority (matches the legacy backend-spawn behaviour, which the doctor
 * path was meant to mirror):
 *   1. Explicit env override (``SAGE_DB_PATH`` / ``SAGE_USER_DATA_DIR``)
 *      wins for CI fixtures and operator overrides.
 *   2. ``app.isPackaged`` true → ``app.getPath('userData')`` — the
 *      per-user writable location. Critical for Win installs to
 *      ``C:\Program Files\Sage`` which is system-protected.
 *   3. Dev mode → ``<cwd>/data`` — project-local so developers see their
 *      existing session history during ``npm run electron:dev``.
 */

import { join } from 'node:path';
import { app } from 'electron';

export function resolveSageDbPath(env: NodeJS.ProcessEnv = process.env): string {
  if (env.SAGE_DB_PATH) return env.SAGE_DB_PATH;
  if (app.isPackaged) return join(app.getPath('userData'), 'sage.db');
  return join(process.cwd(), 'data', 'sage.db');
}

export function resolveSageUserDataDir(env: NodeJS.ProcessEnv = process.env): string {
  if (env.SAGE_USER_DATA_DIR) return env.SAGE_USER_DATA_DIR;
  if (app.isPackaged) return app.getPath('userData');
  return join(process.cwd(), 'data');
}