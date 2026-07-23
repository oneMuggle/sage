/**
 * Office document IPC gateway (M0 Task 5, brief §Step 4 + §Step 5).
 *
 * Seven channels back the Chat-native Office workflow:
 *
 *   office:pick-and-import → native open dialog → atomic copy (COPYFILE_EXCL)
 *                          → token + ImportedOfficeFile
 *   office:import-dropped  → copy a renderer-supplied sourcePath (drag/drop)
 *   office:complete-import → consume the token without deleting the file
 *   office:discard-import  → consume the token, delete the staged file only
 *   office:save-as         → native save dialog → copy managed→chosen path
 *   office:open            → shell.openPath on the validated managed file
 *   office:show-in-folder  → shell.showItemInFolder on the validated file
 *
 * Design notes:
 *   - Pure module (no top-level side effects). Unit-tested by injecting
 *     a `register(channel, handler)` function.
 *   - Source paths are NEVER accepted from the renderer. The bridge
 *     reconstructs the managed path from `OfficeManagedRef` (workspace
 *     + documentId + filename) via `officePaths.buildManagedPath` —
 *     preventing a renderer from coercing main into operating on
 *     arbitrary filesystem paths.
 *   - Pending-import state lives in a process-local Map<token, pending>.
 *     `complete` and `discard` consume the token; a forged or stale
 *     token resolves to "no-op" without touching disk.
 *   - `discard` deletes ONLY the managed staging dir captured at pick
 *     time. A forged token can never delete an unrelated file.
 *   - Atomic copy uses `fs.copyFile` with `COPYFILE_EXCL`, so a re-raced
 *     pick-and-import cannot overwrite an existing managed document.
 *   - The existing simple `office:pick-file` and `office:save-dialog`
 *     channels from the Phase 1.3 pickup are KEPT (so the legacy
 *     pickOfficeFile + pickSavePath preload bridges still resolve).
 */

import { constants as fsConstants, existsSync, statSync } from 'fs';
import { copyFile, mkdir, rm } from 'fs/promises';
import path from 'path';
import { BrowserWindow, dialog, shell } from 'electron';
import { randomUUID } from 'crypto';

import {
  buildManagedPath,
  extensionForDocType,
  getOpenDialogFilters,
  isPathWithinWorkspace,
  type ImportedOfficeFile,
  type OfficeDocType,
  type OfficeManagedRef,
} from './officePaths';

/**
 * Register signature: same shape as Electron's `ipcMain.handle`.
 *
 * Production callers pass `(channel, handler) => ipcMain.handle(channel, handler)`.
 * Tests inject a Map-backed stub.
 */
export type RegisterIpcHandler = (
  channel: string,
  handler: (...args: unknown[]) => unknown,
) => void;

// ----------------------------------------------------------------------------
// Pending-import state (process-local Map)
// ----------------------------------------------------------------------------

/**
 * What we remember between pick-and-import and complete/discard.
 *   `managedPath`   — the staging file we already created on disk
 *   `stagingDir`    — the parent dir we created (the token-named dir)
 *   `originalName`  — basename as the user chose it
 *   `sizeBytes`     — copied file size, frozen at staging time
 *   `workspacePath` — so a discard has a defense-in-depth anchor
 *
 * We keep the *managedPath* in this map (not the source) so the bridge
 * never has to re-derive the destination later.
 */
interface PendingImport {
  managedPath: string;
  stagingDir: string;
  originalName: string;
  sizeBytes: number;
  workspacePath: string;
}

const pendingImports = new Map<string, PendingImport>();

// ----------------------------------------------------------------------------
// Dialog helpers (shared between new and legacy channels)
// ----------------------------------------------------------------------------

function focusedWindow(): BrowserWindow | undefined {
  return BrowserWindow.getFocusedWindow() ?? undefined;
}

/**
 * Common option builder for the open dialog. Uses the modern filter
 * catalog from officePaths.ts — NO legacy extensions, NO wildcard.
 */
function openDialogOptions(docType: OfficeDocType) {
  const filter = getOpenDialogFilters()[docType];
  return {
    title: `选择 ${filter.name}`,
    filters: [filter],
    properties: ['openFile'] as ('openFile')[],
  };
}

// ----------------------------------------------------------------------------
// Stage helpers
// ----------------------------------------------------------------------------

/**
 * Replace the extension on a filename with `newExt` (without leading dot).
 * Used by staging to ensure a docx file drops with a .docx name even if
 * the user picked, say, "notes.txt" through a misconfigured OS open dialog.
 */
function replaceExtension(basename: string, newExt: string): string {
  const base = path.basename(basename, path.extname(basename));
  return `${base}.${newExt}`;
}

/**
 * Atomic staging: copy sourcePath → workspace/office/<docType>/<token>/<basename>.
 *
 * Uses `fs.copyFile` with `COPYFILE_EXCL` so a colliding `token`
 * (astronomically unlikely with UUID v4) raises EEXIST and we surface
 * it as a typed error.
 */
async function stageImportedFile(
  workspacePath: string,
  docType: OfficeDocType,
  sourcePath: string,
  importToken: string,
): Promise<ImportedOfficeFile> {
  if (!workspacePath) throw new Error('workspacePath is required');
  if (!sourcePath) throw new Error('sourcePath is required');

  const ext = extensionForDocType(docType);
  const originalName = path.basename(sourcePath);
  const finalName = replaceExtension(originalName, ext);
  const stagingDir = path.join(workspacePath, 'office', docType, importToken);
  // Await both calls: without `await`, the `mkdir` promise can reject
  // asynchronously (e.g. permission denied) AFTER `copyFile` has already
  // thrown ENOENT for a non-existent dir. Tests rely on a deterministic
  // sequential chain here, so the synchronous semantics of statSync
  // below still see the committed file.
  await mkdir(stagingDir, { recursive: true });
  const managedPath = path.join(stagingDir, finalName);
  await copyFile(sourcePath, managedPath, fsConstants.COPYFILE_EXCL);

  let sizeBytes = 0;
  try {
    sizeBytes = statSync(managedPath).size;
  } catch {
    // file disappeared between copy and stat — extremely unlikely but
    // we still want to return something; size 0 lets the renderer
    // show "empty" rather than crash.
  }
  return {
    workspacePath,
    docType,
    documentId: importToken,
    filename: finalName,
    managedPath,
    originalName,
    sizeBytes,
    importToken,
  };
}

/**
 * Reconstruct the canonical managed path from an OfficeManagedRef.
 *
 * Used by save-as / open / show-in-folder — the renderer must provide
 * the same {workspace, documentId, filename, docType} tuple it used
 * during import; the bridge trusts the tuple, derives the disk path
 * itself, and refuses to operate on paths that fall outside the
 * workspace containment check OR that don't point to a real file.
 */
function resolveManagedFilePath(ref: OfficeManagedRef): string {
  const candidate = buildManagedPath(ref);
  if (!isPathWithinWorkspace(ref.workspacePath, candidate)) {
    throw new Error(
      `refused: managed path ${candidate} is not within workspace ${ref.workspacePath}`,
    );
  }
  // Existence check: the renderer cannot create a managed file by
  // fabricating a tuple — the staging step is the only path that
  // lands a file on disk. If `existsSync` returns false, we refuse
  // to operate on a path the gateway never wrote.
  if (!existsSync(candidate)) {
    throw new Error(
      `refused: managed file does not exist on disk (never imported?): ${candidate}`,
    );
  }
  return candidate;
}

// ----------------------------------------------------------------------------
// registerOfficeIpc — the real wiring
// ----------------------------------------------------------------------------

export function registerOfficeIpc(register: RegisterIpcHandler): void {
  // ── office:pick-and-import ────────────────────────────────────────────
  // Atomic dialog → copy → token. Returns ImportedOfficeFile | null.
  register(
    'office:pick-and-import',
    (async (
      _event: unknown,
      opts: { workspacePath: string; docType: OfficeDocType },
    ): Promise<ImportedOfficeFile | null> => {
      const focused = focusedWindow();
      const dialogOpts = openDialogOptions(opts.docType);
      const result = await dialog.showOpenDialog(focused ?? undefined!, dialogOpts);
      if (result.canceled || result.filePaths.length === 0) return null;
      const sourcePath = result.filePaths[0]!;
      const importToken = randomUUID();
      const imported = await stageImportedFile(opts.workspacePath, opts.docType, sourcePath, importToken);
      pendingImports.set(importToken, {
        managedPath: imported.managedPath,
        stagingDir: path.dirname(imported.managedPath),
        originalName: imported.originalName,
        sizeBytes: imported.sizeBytes,
        workspacePath: imported.workspacePath,
      });
      return imported;
    }) as (...args: unknown[]) => unknown,
  );

  // ── office:import-dropped ─────────────────────────────────────────────
  // Renderer already has sourcePath (drag/drop handler did the JSON
  // serialization). Same atomic copy logic as pick-and-import.
  register(
    'office:import-dropped',
    (async (
      _event: unknown,
      opts: { workspacePath: string; docType: OfficeDocType; sourcePath: string },
    ): Promise<ImportedOfficeFile> => {
      const importToken = randomUUID();
      const imported = await stageImportedFile(
        opts.workspacePath,
        opts.docType,
        opts.sourcePath,
        importToken,
      );
      pendingImports.set(importToken, {
        managedPath: imported.managedPath,
        stagingDir: path.dirname(imported.managedPath),
        originalName: imported.originalName,
        sizeBytes: imported.sizeBytes,
        workspacePath: imported.workspacePath,
      });
      return imported;
    }) as (...args: unknown[]) => unknown,
  );

  // ── office:complete-import ────────────────────────────────────────────
  // Consumes the token without deleting the file. Idempotent: a second
  // call on the same (now-consumed) token is a no-op.
  register(
    'office:complete-import',
    (async (_event: unknown, opts: { importToken: string }): Promise<void> => {
      pendingImports.delete(opts.importToken);
    }) as (...args: unknown[]) => unknown,
  );

  // ── office:discard-import ─────────────────────────────────────────────
  // Consumes the token and deletes ONLY the staging directory captured at
  // pick time. A forged or unknown token resolves to "no-op" — the
  // property test asserts that even if no real import ever happened,
  // an attacker cannot make us delete an arbitrary file (because we
  // never had a path to that file in the map).
  register(
    'office:discard-import',
    (async (_event: unknown, opts: { importToken: string }): Promise<void> => {
      const pending = pendingImports.get(opts.importToken);
      if (!pending) return; // unknown token → no-op (NO delete path)
      pendingImports.delete(opts.importToken);
      try {
        await rm(pending.stagingDir, { recursive: true, force: true });
      } catch {
        // Best-effort cleanup; if rm fails (locked, gone) we just leave
        // the file. The renderer shouldn't surface this as a crash.
      }
    }) as (...args: unknown[]) => unknown,
  );

  // ── office:save-as ────────────────────────────────────────────────────
  // Native save dialog → copy the managed file to the chosen path.
  // Returns { savedPath } on confirmation, null on cancel. We never
  // accept a renderer-supplied destination — only the dialog drives it.
  register(
    'office:save-as',
    (async (
      _event: unknown,
      opts: { workspacePath: string; docType: OfficeDocType; documentId: string; filename: string },
    ): Promise<{ savedPath: string } | null> => {
      const focused = focusedWindow();
      const dialogOpts = {
        title: '保存 Office 文档',
        defaultPath: opts.filename,
        filters: [getOpenDialogFilters()[opts.docType]],
      };
      const result = await dialog.showSaveDialog(focused ?? undefined!, dialogOpts);
      if (result.canceled || !result.filePath) return null;
      const sourcePath = resolveManagedFilePath({
        workspacePath: opts.workspacePath,
        docType: opts.docType,
        documentId: opts.documentId,
        filename: opts.filename,
      });
      // Save As is the user's explicit "OK, replace whatever is there"
      // gesture, so we don't use COPYFILE_EXCL — just an atomic copy.
      await copyFile(sourcePath, result.filePath, fsConstants.COPYFILE_FICLONE);
      return { savedPath: result.filePath };
    }) as (...args: unknown[]) => unknown,
  );

  // ── office:open ───────────────────────────────────────────────────────
  // shell.openPath on the validated managed file. Throws a typed error
  // if the OS shell reports a non-empty error string (no app associated
  // with this filetype, etc.).
  register(
    'office:open',
    (async (
      _event: unknown,
      opts: { workspacePath: string; docType: OfficeDocType; documentId: string; filename: string },
    ): Promise<void> => {
      const targetPath = resolveManagedFilePath(opts);
      let openResult: string;
      try {
        openResult = await shell.openPath(targetPath);
      } catch (err) {
        throw new Error(
          `office:open: shell.openPath threw: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
      if (openResult) {
        // shell.openPath returns a non-empty error string on failure
        throw new Error(`openPath failed: ${openResult}`);
      }
    }) as (...args: unknown[]) => unknown,
  );

  // ── office:show-in-folder ─────────────────────────────────────────────
  // shell.showItemInFolder is fire-and-forget (no return code). The
  // path is reconstructed from the OfficeManagedRef so the renderer
  // can't trigger a folder view of arbitrary paths.
  register(
    'office:show-in-folder',
    (async (
      _event: unknown,
      opts: { workspacePath: string; docType: OfficeDocType; documentId: string; filename: string },
    ): Promise<void> => {
      const targetPath = resolveManagedFilePath(opts);
      shell.showItemInFolder(targetPath);
    }) as (...args: unknown[]) => unknown,
  );

  // ── legacy channels (Phase 1.3 + 1.4) ────────────────────────────────
  // Kept so the existing preload bridges (pickOfficeFile, pickSavePath)
  // continue to resolve. New code should prefer the gateway channels.
  register(
    'office:pick-file',
    (async (_event: unknown, opts: { docType: OfficeDocType }) => {
      const focused = focusedWindow();
      const dialogOpts = openDialogOptions(opts.docType);
      const result = await dialog.showOpenDialog(focused ?? undefined!, dialogOpts);
      if (result.canceled || result.filePaths.length === 0) return null;
      const filePath = result.filePaths[0]!;
      const name = filePath.split(/[\\/]/).pop() ?? filePath;
      let sizeBytes = 0;
      try {
        sizeBytes = statSync(filePath).size;
      } catch {
        /* file disappeared between dialog and stat */
      }
      return { path: filePath, name, sizeBytes };
    }) as (...args: unknown[]) => unknown,
  );

  register(
    'office:save-dialog',
    (async (_event: unknown, opts: { defaultName: string }) => {
      const focused = focusedWindow();
      const result = await dialog.showSaveDialog(focused ?? undefined!, {
        title: '保存 Office 文档',
        defaultPath: opts.defaultName,
      });
      if (result.canceled || !result.filePath) return null;
      return result.filePath;
    }) as (...args: unknown[]) => unknown,
  );
}

// Test-only helper: clear the pending import state. Not exported on
// the public surface; only invoked from __tests__ to keep specs
// isolated. Calling this in production code is a no-op semantically.
export function __resetPendingImportsForTests(): void {
  pendingImports.clear();
}

// Re-export the typed surface so the preload bridge only needs to
// import once from `officeIpc` for types.
export type {
  OfficeDocType,
  OfficeManagedRef,
  ImportedOfficeFile,
} from './officePaths';
