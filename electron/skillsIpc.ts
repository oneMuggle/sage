/**
 * Skills "load-new" IPC handlers (PR-C).
 *
 * Three channels back the Skills page buttons added in this phase:
 *
 *   skills:pick-files → dialog.showOpenDialog (.md filter, multiSelections)
 *   skills:rescan     → POST /api/v1/skills/rescan
 *   skills:import     → POST /api/v1/skills/import (multipart FormData)
 *
 * Design notes:
 *   - This is a *pure module* (no top-level side effects) so it can be
 *     unit-tested by injecting a register(channel, handler) function.
 *     Production callers pass `(c, h) => ipcMain.handle(c, h)`.
 *   - The pick-files handler uses dialog.showOpenDialog with a focused
 *     window if available so the dialog attaches to the Sage window
 *     (modal behavior on Windows/Linux).
 *   - import reads each file from disk and ships it as a Blob inside
 *     a FormData payload (Node 18+ has FormData + Blob as globals).
 *     Backend expects field name "files" (multipart list).
 *   - On HTTP error, we surface backend `detail.type` (and `detail.message`)
 *     as the Error message so the renderer can show a friendly toast
 *     that maps 1:1 to backend reason codes.
 */
import { readFileSync } from 'fs';
import { basename } from 'path';
import { BrowserWindow, dialog } from 'electron';

/** Default backend base URL; PYTHON_BACKEND_URL overrides (used in CI). */
const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8765';

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

export function registerSkillsIpc(register: RegisterIpcHandler): void {
  // ── skills:pick-files ─────────────────────────────────────────────────
  // Returns `string[] | null` — selected absolute paths, or null on cancel.
  register('skills:pick-files', async () => {
    const focusedWindow = BrowserWindow.getFocusedWindow();
    const result = await dialog.showOpenDialog(focusedWindow ?? undefined!, {
      title: '导入 SKILL.md',
      filters: [{ name: 'SKILL.md', extensions: ['md', 'markdown'] }],
      properties: ['openFile', 'multiSelections'],
    });
    if (result.canceled || result.filePaths.length === 0) return null;
    return result.filePaths;
  });

  // ── skills:rescan ─────────────────────────────────────────────────────
  // Forwards to POST /api/v1/skills/rescan (no body). Returns the raw JSON
  // payload: { loaded, skipped, total_loaded }.
  register('skills:rescan', async () => {
    const baseUrl = getBackendBaseUrl();
    const resp = await fetch(`${baseUrl}/api/v1/skills/rescan`, { method: 'POST' });
    if (!resp.ok) {
      throw new Error(`rescan failed: HTTP ${resp.status}`);
    }
    return resp.json();
  });

  // ── skills:import ─────────────────────────────────────────────────────
  // Reads each file from disk, builds a multipart FormData payload, and
  // POSTs to /api/v1/skills/import. Backend field name is "files".
  // On error, throws an Error whose message starts with backend
  // detail.type so renderer can show reason-specific toast.
  register('skills:import', (async (_event: unknown, paths: string[]) => {
    const baseUrl = getBackendBaseUrl();
    const form = new FormData();
    for (const p of paths) {
      const filename = basename(p);
      const buffer = readFileSync(p);
      form.append('files', new Blob([buffer], { type: 'text/markdown' }), filename);
    }
    const resp = await fetch(`${baseUrl}/api/v1/skills/import`, {
      method: 'POST',
      body: form,
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