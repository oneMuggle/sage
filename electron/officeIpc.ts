/**
 * Office document IPC handlers (Phase 1.3, plan §4.1.3 step 13).
 *
 * Two channels back the Office page:
 *
 *   office:pick-file  → dialog.showOpenDialog (per .pptx/.docx/.xlsx)
 *   office:save-dialog → dialog.showSaveDialog (default filename + extension)
 *
 * The 8 read/list/delete IPC routes (office_ppt_read etc.) are routed
 * through the standard invoke→HTTP path in commands.ts and don't need
 * dedicated ipcMain handlers — Electron main process auto-forwards them
 * via the COMMAND_ROUTES map.
 *
 * Design notes (mirrors skillsIpc.ts):
 * - Pure module (no top-level side effects) so it can be unit-tested by
 *   injecting a register(channel, handler) function.
 * - The pick-file handler uses dialog.showOpenDialog with a focused
 *   window if available so the dialog attaches to the Sage window.
 * - Returns are JSON-serializable: { path, name, sizeBytes } | null
 *   (or string | null for save-dialog).
 */
import { statSync } from 'fs';
import { BrowserWindow, dialog } from 'electron';

/** Extension filter for each Office doc type (passed to dialog.showOpenDialog). */
const FILE_FILTERS: Record<string, { name: string; extensions: string[] }> = {
  ppt: { name: 'PowerPoint Presentation', extensions: ['pptx', 'ppt'] },
  word: { name: 'Word Document', extensions: ['docx', 'doc'] },
  excel: { name: 'Excel Workbook', extensions: ['xlsx', 'xls'] },
};

export interface PickedFile {
  path: string;
  name: string;
  sizeBytes: number;
}

export type RegisterIpcHandler = (
  channel: string,
  handler: (...args: unknown[]) => unknown,
) => void;

export function registerOfficeIpc(register: RegisterIpcHandler): void {
  // ── office:pick-file ──────────────────────────────────────────────────
  // Opens a native open dialog filtered to the requested doc type.
  // Returns the picked file metadata, or null if user cancelled.
  register('office:pick-file', (async (_event: unknown, opts: { docType: string }) => {
    const focusedWindow = BrowserWindow.getFocusedWindow();
    const filter = FILE_FILTERS[opts.docType] ?? {
      name: 'Office Document',
      extensions: ['pptx', 'docx', 'xlsx'],
    };
    const result = await dialog.showOpenDialog(focusedWindow ?? undefined!, {
      title: `选择 ${filter.name}`,
      filters: [filter, { name: 'All Files', extensions: ['*'] }],
      properties: ['openFile'],
    });
    if (result.canceled || result.filePaths.length === 0) return null;
    const path = result.filePaths[0]!;
    const name = path.split(/[\\/]/).pop() ?? path;
    let sizeBytes = 0;
    try {
      sizeBytes = statSync(path).size;
    } catch {
      // file disappeared between dialog and stat — return 0 and let backend 404
    }
    return { path, name, sizeBytes } satisfies PickedFile;
  }) as (...args: unknown[]) => unknown);

  // ── office:save-dialog ────────────────────────────────────────────────
  // Opens a native save dialog with a suggested default filename.
  // Returns the chosen absolute path, or null if user cancelled.
  register('office:save-dialog', (async (_event: unknown, opts: { defaultName: string }) => {
    const focusedWindow = BrowserWindow.getFocusedWindow();
    const result = await dialog.showSaveDialog(focusedWindow ?? undefined!, {
      title: '保存 Office 文档',
      defaultPath: opts.defaultName,
    });
    if (result.canceled || !result.filePath) return null;
    return result.filePath;
  }) as (...args: unknown[]) => unknown);
}
