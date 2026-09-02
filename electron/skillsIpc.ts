/**
 * Skills "load-new" IPC handlers (PR-C).
 *
 * Three channels back the Skills page buttons added in this phase:
 *
 *   skills:pick-files → dialog.showOpenDialog (.md filter, multiSelections)
 *   skills:rescan     → POST /api/v1/skills/rescan
 *   skills:import     → POST /api/v1/skills/import (multipart bytes)
 *
 * Design notes:
 *   - This is a *pure module* (no top-level side effects) so it can be
 *     unit-tested by injecting a register(channel, handler) function.
 *     Production callers pass `(c, h) => ipcMain.handle(c, h)`.
 *   - The pick-files handler uses dialog.showOpenDialog with a focused
 *     window if available so the dialog attaches to the Sage window
 *     (modal behavior on Windows/Linux).
 *   - import reads each file from disk and builds a Node 16-compatible multipart
 *     byte payload with an explicit boundary; it does not use global FormData/Blob.
 *     Backend expects field name "files" (multipart list).
 *   - On HTTP error, we surface backend `detail.type` (and `detail.message`)
 *     as the Error message so the renderer can show a friendly toast
 *     that maps 1:1 to backend reason codes.
 */
import { lstatSync, readFileSync, realpathSync } from 'fs';
import { basename, resolve } from 'path';
import { randomBytes } from 'crypto';
import fetch from 'node-fetch';
import { BrowserWindow, dialog } from 'electron';

/** Default backend base URL; PYTHON_BACKEND_URL overrides (used in CI). */
const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8765';
const MAX_IMPORT_FILE_SIZE_BYTES = 1024 * 1024;
const MAX_IMPORT_FILES = 100;
const MAX_IMPORT_TOTAL_SIZE_BYTES = 10 * 1024 * 1024;

function getBackendBaseUrl(): string {
  return process.env.PYTHON_BACKEND_URL || DEFAULT_BACKEND_URL;
}

/**
 * Register signature: same shape as Electron's `ipcMain.handle`.
 *
 * We accept any `(channel, handler)` pair — the production wiring
 * passes `ipcMain.handle.bind(ipcMain)`. The handler parameter is
 * loosely typed so test fakes can swap it in without ceremony.
 */
export type RegisterIpcHandler = (
  channel: string,
  handler: (...args: unknown[]) => unknown,
) => void;

export type SkillsAuthToken = string | (() => string | undefined);

function resolveAuthToken(authToken?: SkillsAuthToken): string | undefined {
  return typeof authToken === 'function' ? authToken() : authToken;
}

function requestFetch(...args: Parameters<typeof fetch>): ReturnType<typeof fetch> {
  const runtimeFetch = (globalThis as unknown as { fetch?: typeof fetch }).fetch ?? fetch;
  return runtimeFetch(...args);
}

function buildMultipart(paths: string[]): { body: Buffer; contentType: string } {
  if (!Array.isArray(paths) || paths.length === 0) throw new Error('no files selected');
  if (paths.length > MAX_IMPORT_FILES) throw new Error('too many files selected');
  const boundary = `----sage-${randomBytes(16).toString('hex')}`;
  const chunks: Buffer[] = [];
  const seen = new Set<string>();
  let totalSize = 0;
  for (const p of paths) {
    if (typeof p !== 'string' || !p) throw new Error('invalid file path');
    const canonical = realpathSync(resolve(p));
    if (seen.has(canonical)) throw new Error('duplicate file');
    seen.add(canonical);
    const stat = lstatSync(p);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('file must be a regular file');
    if (!/\.(?:md|markdown)$/iu.test(basename(p))) throw new Error('file must be Markdown');
    if (stat.size > MAX_IMPORT_FILE_SIZE_BYTES) throw new Error('file too large');
    totalSize += stat.size;
    if (totalSize > MAX_IMPORT_TOTAL_SIZE_BYTES) throw new Error('batch too large');
    const filename = basename(canonical);
    if (/[\r\n"]/u.test(filename)) throw new Error('invalid multipart filename');
    const content = readFileSync(canonical);
    chunks.push(
      Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="files"; filename="${filename}"\r\nContent-Type: text/markdown\r\n\r\n`,
        'utf8',
      ),
      content,
      Buffer.from(`\r\n`, 'utf8'),
    );
  }
  chunks.push(Buffer.from(`--${boundary}--\r\n`, 'utf8'));
  return { body: Buffer.concat(chunks), contentType: `multipart/form-data; boundary=${boundary}` };
}

export function registerSkillsIpc(register: RegisterIpcHandler, authToken?: SkillsAuthToken): void {
  let recentPickedFiles = new Set<string>();
  // ── skills:pick-files ─────────────────────────────────────────────────
  // Returns `string[] | null` — selected absolute paths, or null on cancel.
  register('skills:pick-files', async () => {
    const focusedWindow = BrowserWindow.getFocusedWindow();
    const result = await dialog.showOpenDialog(focusedWindow ?? undefined!, {
      title: '导入 SKILL.md',
      filters: [{ name: 'SKILL.md', extensions: ['md', 'markdown'] }],
      properties: ['openFile', 'multiSelections'],
    });
    if (result.canceled || result.filePaths.length === 0) {
      recentPickedFiles = new Set();
      return null;
    }
    const canonical = new Set<string>();
    for (const filePath of result.filePaths) {
      const stat = lstatSync(filePath);
      if (!stat.isFile() || stat.isSymbolicLink()) continue;
      canonical.add(realpathSync(resolve(filePath)));
    }
    recentPickedFiles = canonical;
    return [...canonical];
  });

  // ── skills:rescan ─────────────────────────────────────────────────────
  // Forwards to POST /api/v1/skills/rescan (no body). Returns the raw JSON
  // payload: { loaded, skipped, total_loaded }.
  register('skills:rescan', async () => {
    const baseUrl = getBackendBaseUrl();
    const token = resolveAuthToken(authToken);
    const resp = await requestFetch(`${baseUrl}/api/v1/skills/rescan`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!resp.ok) {
      throw new Error(`rescan failed: HTTP ${resp.status}`);
    }
    return resp.json();
  });

  // ── skills:import ─────────────────────────────────────────────────────
  // Reads each file from disk, builds a Node 16-compatible multipart payload, and
  // POSTs to /api/v1/skills/import. Backend field name is "files".
  // On error, throws an Error whose message starts with backend
  // detail.type so renderer can show reason-specific toast.
  register('skills:import', (async () => {
    const paths = [...recentPickedFiles];
    if (paths.length === 0) throw new Error('no files selected');
    const multipart = buildMultipart(paths);
    const token = resolveAuthToken(authToken);
    const headers: Record<string, string> = {
      'Content-Type': multipart.contentType,
    };
    if (token) headers.Authorization = `Bearer ${token}`;
    const baseUrl = getBackendBaseUrl();
    const resp = await requestFetch(`${baseUrl}/api/v1/skills/import`, {
      method: 'POST',
      headers,
      body: multipart.body,
    });
    if (!resp.ok) {
      const errBody = (await resp.json().catch(() => ({
        detail: { message: 'unknown' },
      }))) as { detail?: { type?: string; message?: string } };
      throw new Error(
        `${errBody.detail?.type ?? 'import_failed'}: ${errBody.detail?.message ?? ''}`,
      );
    }
    return resp.json();
  }) as (...args: unknown[]) => unknown);
}
