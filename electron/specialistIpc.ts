/**
 * Specialist (.sage 专家包) IPC handlers — M1-E.
 *
 * Two channels back the /specialists gallery import/export buttons:
 *
 *   specialists:import → dialog.showOpenDialog (.sage/.zip) → multipart
 *                        POST /api/v1/specialists/import → { id, name } | null
 *   specialists:export → GET /api/v1/specialists/{id}/export (binary zip)
 *                        → save dialog → writeFileSync → { ok, path } | null
 *
 * Why not the generic command-route invoke path? `invokeBackend()`
 * (electron/invoke.ts) always calls `res.json()`, so the zip download
 * cannot ride it. Import is multipart and needs a native file dialog.
 * Same rationale as electron/skillsIpc.ts, whose structure this module
 * mirrors.
 *
 * Design notes:
 *   - Pure module (no top-level side effects) so unit tests can inject a
 *     register(channel, handler) function.
 *   - Node 16-compatible multipart: explicit boundary, no global FormData.
 *   - Backend error `detail.type` / `detail.message` are surfaced in the
 *     thrown Error message so the renderer can map reason codes to toasts.
 */
import { lstatSync, readFileSync, realpathSync, writeFileSync } from 'fs';
import { basename, join, resolve } from 'path';
import { randomBytes } from 'crypto';
import { BrowserWindow, dialog } from 'electron';
import { fetchCompat } from './fetchCompat';

/** Default backend base URL; PYTHON_BACKEND_URL overrides (used in CI). */
const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8765';

/** Matches backend `is_agent_id_safe()` — defense in depth before URL build. */
const AGENT_ID_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$/u;

/** Zip packages are capped well above the backend per-file (10 MB) and
 *  knowledge-total (50 MB) limits to leave room for zip overhead. */
const MAX_PACKAGE_BYTES = 64 * 1024 * 1024;

function getBackendBaseUrl(): string {
  return process.env.PYTHON_BACKEND_URL || DEFAULT_BACKEND_URL;
}

/**
 * Register signature: same shape as Electron's `ipcMain.handle`.
 * Loose typing lets test fakes swap it in without ceremony.
 */
export type RegisterSpecialistIpcHandler = (
  channel: string,
  handler: (...args: unknown[]) => unknown,
) => void;

export type SpecialistAuthToken = string | (() => string | undefined);

function resolveAuthToken(authToken?: SpecialistAuthToken): string | undefined {
  return typeof authToken === 'function' ? authToken() : authToken;
}

function parseBackendError(errBody: { detail?: { type?: string; message?: string } }): Error {
  return new Error(`${errBody.detail?.type ?? 'request_failed'}: ${errBody.detail?.message ?? ''}`);
}

function buildPackageMultipart(packagePath: string): {
  body: Buffer;
  contentType: string;
} {
  if (typeof packagePath !== 'string' || !packagePath) throw new Error('invalid package path');
  const stat = lstatSync(packagePath);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error('package must be a regular file');
  }
  if (stat.size > MAX_PACKAGE_BYTES) throw new Error('package too large');
  const filename = basename(realpathSync(resolve(packagePath)));
  if (/[\r\n"]/u.test(filename)) throw new Error('invalid multipart filename');

  const boundary = `----sage-${randomBytes(16).toString('hex')}`;
  const content = readFileSync(packagePath);
  const body = Buffer.concat([
    Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: application/zip\r\n\r\n`,
      'utf8',
    ),
    content,
    Buffer.from(`\r\n--${boundary}--\r\n`, 'utf8'),
  ]);
  return { body, contentType: `multipart/form-data; boundary=${boundary}` };
}

export function registerSpecialistIpc(
  register: RegisterSpecialistIpcHandler,
  authToken?: SpecialistAuthToken,
): void {
  // ── specialists:import ────────────────────────────────────────────────
  // Native picker → upload → return the created specialist's { id, name }.
  // Returns null when the user cancels the dialog.
  register('specialists:import', (async () => {
    const focusedWindow = BrowserWindow.getFocusedWindow();
    const picked = await dialog.showOpenDialog(focusedWindow ?? undefined!, {
      title: '导入专家包',
      filters: [{ name: 'Sage 专家包', extensions: ['sage', 'zip'] }],
      properties: ['openFile'],
    });
    if (picked.canceled || picked.filePaths.length === 0) return null;

    const multipart = buildPackageMultipart(picked.filePaths[0]);
    const token = resolveAuthToken(authToken);
    const headers: Record<string, string> = { 'Content-Type': multipart.contentType };
    if (token) headers.Authorization = `Bearer ${token}`;

    const resp = await fetchCompat(`${getBackendBaseUrl()}/api/v1/specialists/import`, {
      method: 'POST',
      headers,
      body: multipart.body,
    });
    if (!resp.ok) {
      const errBody = (await resp.json().catch(() => ({
        detail: { message: 'unknown' },
      }))) as { detail?: { type?: string; message?: string } };
      throw parseBackendError(errBody);
    }
    return resp.json();
  }) as (...args: unknown[]) => unknown);

  // ── specialists:export ────────────────────────────────────────────────
  // agentId → save dialog → binary GET → writeFileSync. Returns
  // { ok: true, path } or null when the user cancels the save dialog.
  register('specialists:export', (async (_event: unknown, agentId: unknown) => {
    if (typeof agentId !== 'string' || !AGENT_ID_PATTERN.test(agentId)) {
      throw new Error(`invalid_agent_id: ${String(agentId)}`);
    }

    const token = resolveAuthToken(authToken);
    const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
    const resp = await fetchCompat(
      `${getBackendBaseUrl()}/api/v1/specialists/${encodeURIComponent(agentId)}/export`,
      { method: 'GET', headers },
    );
    if (!resp.ok) {
      const errBody = (await resp.json().catch(() => ({
        detail: { message: 'unknown' },
      }))) as { detail?: { type?: string; message?: string } };
      throw parseBackendError(errBody);
    }

    const focusedWindow = BrowserWindow.getFocusedWindow();
    const save = await dialog.showSaveDialog(focusedWindow ?? undefined!, {
      title: '导出专家包',
      defaultPath: join(process.env.HOME ?? './', `${agentId}.sage`),
      filters: [{ name: 'Sage 专家包', extensions: ['sage'] }],
    });
    if (save.canceled || !save.filePath) return null;

    const bytes = Buffer.from(await resp.arrayBuffer());
    writeFileSync(save.filePath, bytes);
    return { ok: true, path: save.filePath };
  }) as (...args: unknown[]) => unknown);
}

/** Exported for unit tests: package size ceiling (bytes). */
export const SPECIALIST_MAX_PACKAGE_BYTES = MAX_PACKAGE_BYTES;

/** Exported for unit tests: agent-id pattern used before URL construction. */
export const SPECIALIST_AGENT_ID_PATTERN = AGENT_ID_PATTERN;
