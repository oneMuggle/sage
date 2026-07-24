/**
 * RED tests for electron/officeIpc.ts (M0 Task 5, brief §Step 1 + §Step 4 + §Step 5).
 *
 * Asserts the office: gateway handlers:
 *   - office:pick-and-import → dialog.showOpenDialog + atomic copy
 *   - office:import-dropped → copy a renderer-supplied sourcePath
 *   - office:complete-import → consume token, keep file
 *   - office:discard-import → consume token, delete staging dir
 *   - office:save-as         → dialog.showSaveDialog + copy
 *   - office:open            → shell.openPath on managed file
 *   - office:show-in-folder  → shell.showItemInFolder on managed file
 *
 * Behavior contract (brief §Step 4 + §Step 5):
 *   - Forged paths / unknown tokens MUST NOT delete an existing managed
 *     document.
 *   - copy uses fs.copyFile with COPYFILE_EXCL (no overwrite of pre-existing
 *     managed files).
 *   - shell.openPath non-empty results throw a typed error.
 *   - dialog cancellation returns null (pick-and-import, save-as).
 */

import { Buffer } from 'buffer';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import os from 'os';
import path from 'path';
import fs from 'fs';

const mocks = vi.hoisted(() => ({
  dialog: {
    showOpenDialog: vi.fn(),
    showSaveDialog: vi.fn(),
  },
  shell: {
    openPath: vi.fn(),
    showItemInFolder: vi.fn(),
  },
  BrowserWindow: { getFocusedWindow: vi.fn(() => null) },
}));

vi.mock('electron', () => ({
  dialog: mocks.dialog,
  shell: mocks.shell,
  BrowserWindow: mocks.BrowserWindow,
}));

const registeredHandlers = new Map<string, (...args: unknown[]) => unknown>();
function fakeRegister(channel: string, handler: (...args: unknown[]) => unknown): void {
  registeredHandlers.set(channel, handler);
}

import { registerOfficeIpc, __resetPendingImportsForTests, sweepOrphanStaging } from '../officeIpc';
import type { ImportedOfficeFile } from '../../src/shared/types/electron-api';

/**
 * The shape the gateway actually returns from pick-and-import is the
 * `ImportedOfficeFile` interface from electron-api.d.ts (which extends
 * OfficeManagedRef with managedPath + sizeBytes + originalName + importToken).
 * We re-declare it here (rather than importing from the shared types
 * file) to keep the test self-contained — vitest's transform does not
 * require cross-file type imports for a passing local check.
 */
interface PendingImport extends ImportedOfficeFile {
  stagingDir: string;
}

describe('office IPC gateway — channel registration (brief §Step 4-5)', () => {
  beforeEach(() => {
    registeredHandlers.clear();
    mocks.dialog.showOpenDialog.mockReset();
    mocks.dialog.showSaveDialog.mockReset();
    mocks.shell.openPath.mockReset();
    mocks.shell.showItemInFolder.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReturnValue(null);
    __resetPendingImportsForTests();
    registerOfficeIpc(fakeRegister);
  });

  it('registers all 7 gateway channels', () => {
    const expected = [
      'office:pick-and-import',
      'office:import-dropped',
      'office:complete-import',
      'office:discard-import',
      'office:save-as',
      'office:open',
      'office:show-in-folder',
    ];
    for (const ch of expected) {
      expect(registeredHandlers.has(ch), `missing channel ${ch}`).toBe(true);
    }
  });
});

describe('office:pick-and-import', () => {
  beforeEach(() => {
    registeredHandlers.clear();
    mocks.dialog.showOpenDialog.mockReset();
    mocks.dialog.showSaveDialog.mockReset();
    mocks.shell.openPath.mockReset();
    mocks.shell.showItemInFolder.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReturnValue(null);
    __resetPendingImportsForTests();
    registerOfficeIpc(fakeRegister);
  });

  it('returns null when the user cancels the open dialog', async () => {
    mocks.dialog.showOpenDialog.mockResolvedValue({ canceled: true, filePaths: [] });
    const handler = registeredHandlers.get('office:pick-and-import')!;
    const result = await handler({}, { workspacePath: '/workspace', docType: 'ppt' });
    expect(result).toBeNull();
  });

  it('returns ImportedOfficeFile with importToken when a file is selected', async () => {
    // Create a real file so fs.copyFile has something to copy from.
    const tmpSrc = path.join(os.tmpdir(), `sage-source-${Date.now()}.pptx`);
    fs.writeFileSync(tmpSrc, Buffer.from('PK fake pptx'));
    mocks.dialog.showOpenDialog.mockResolvedValue({
      canceled: false,
      filePaths: [tmpSrc],
    });

    const handler = registeredHandlers.get('office:pick-and-import')!;
    const result = (await handler({}, { workspacePath: '/tmp/ws', docType: 'ppt' })) as {
      managedPath: string;
      originalName: string;
      sizeBytes: number;
      importToken: string;
    } | null;

    expect(result, 'expected non-null import').not.toBeNull();
    expect(result!.importToken).toMatch(/[0-9a-f-]{8,}/i);
    expect(result!.managedPath).toContain('.pptx');
    expect(result!.originalName).toBe(path.basename(tmpSrc));
    expect(result!.sizeBytes).toBeGreaterThan(0);

    fs.unlinkSync(tmpSrc);
  });

  it('uses modern-only filter catalog (no .ppt/.doc/.xls; no All Files)', async () => {
    mocks.dialog.showOpenDialog.mockResolvedValue({ canceled: true, filePaths: [] });

    const handler = registeredHandlers.get('office:pick-and-import')!;
    await handler({}, { workspacePath: '/workspace', docType: 'ppt' });

    const opts = mocks.dialog.showOpenDialog.mock.calls[0]?.[1] as {
      filters: Array<{ name: string; extensions: string[] }>;
    };
    expect(opts.filters, 'dialog filters must be set').toBeDefined();
    const flat = opts.filters.flatMap((f) => f.extensions);
    expect(flat, 'filters must not include legacy .ppt').not.toContain('ppt');
    expect(flat, 'filters must not include legacy .doc').not.toContain('doc');
    expect(flat, 'filters must not include legacy .xls').not.toContain('xls');
    expect(flat, 'filters must not include "*" All Files').not.toContain('*');
  });
});

describe('office:import-dropped', () => {
  beforeEach(() => {
    registeredHandlers.clear();
    mocks.dialog.showOpenDialog.mockReset();
    mocks.dialog.showSaveDialog.mockReset();
    mocks.shell.openPath.mockReset();
    mocks.shell.showItemInFolder.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReturnValue(null);
    __resetPendingImportsForTests();
    registerOfficeIpc(fakeRegister);
  });

  it('copies the sourcePath into the managed staging dir and returns ImportedOfficeFile', async () => {
    const tmpSrc = path.join(os.tmpdir(), `sage-dropped-${Date.now()}.docx`);
    fs.writeFileSync(tmpSrc, Buffer.from('PK fake docx'));

    const handler = registeredHandlers.get('office:import-dropped')!;
    const result = (await handler({}, {
      workspacePath: '/tmp/ws',
      docType: 'word',
      sourcePath: tmpSrc,
    })) as {
      managedPath: string;
      originalName: string;
      sizeBytes: number;
      importToken: string;
    };

    expect(result.importToken).toMatch(/[0-9a-f-]{8,}/i);
    expect(result.managedPath).toContain('.docx');
    expect(result.originalName).toBe(path.basename(tmpSrc));
    expect(result.sizeBytes).toBeGreaterThan(0);

    fs.unlinkSync(tmpSrc);
  });
});

describe('office:complete-import and office:discard-import (token lifecycle)', () => {
  beforeEach(() => {
    registeredHandlers.clear();
    mocks.dialog.showOpenDialog.mockReset();
    mocks.dialog.showSaveDialog.mockReset();
    mocks.shell.openPath.mockReset();
    mocks.shell.showItemInFolder.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReturnValue(null);
    __resetPendingImportsForTests();
    registerOfficeIpc(fakeRegister);
  });

  it('complete-import is idempotent and does NOT delete the file', async () => {
    const tmpSrc = path.join(os.tmpdir(), `sage-complete-${Date.now()}.xlsx`);
    fs.writeFileSync(tmpSrc, Buffer.from('PK fake xlsx'));
    mocks.dialog.showOpenDialog.mockResolvedValue({
      canceled: false,
      filePaths: [tmpSrc],
    });

    const pickHandler = registeredHandlers.get('office:pick-and-import')!;
    const picked = (await pickHandler({}, {
      workspacePath: '/tmp/ws',
      docType: 'excel',
    })) as PendingImport;

    expect(picked).not.toBeNull();
    const { managedPath, importToken } = picked as unknown as PendingImport;
    expect(fs.existsSync(managedPath), 'managed file was copied').toBe(true);

    const completeHandler = registeredHandlers.get('office:complete-import')!;
    await expect(completeHandler({}, { importToken })).resolves.toBeUndefined();
    // Calling complete twice is a no-op (idempotent).
    await expect(completeHandler({}, { importToken })).resolves.toBeUndefined();
    expect(fs.existsSync(managedPath), 'managed file still exists after complete').toBe(true);

    fs.unlinkSync(managedPath);
    fs.unlinkSync(tmpSrc);
  });

  it('discard-import deletes only the staged file (not other files)', async () => {
    const tmpSrc = path.join(os.tmpdir(), `sage-discard-${Date.now()}.xlsx`);
    fs.writeFileSync(tmpSrc, Buffer.from('PK fake xlsx'));
    mocks.dialog.showOpenDialog.mockResolvedValue({
      canceled: false,
      filePaths: [tmpSrc],
    });

    const pickHandler = registeredHandlers.get('office:pick-and-import')!;
    const picked = (await pickHandler({}, {
      workspacePath: '/tmp/ws',
      docType: 'excel',
    })) as PendingImport;

    expect(picked).not.toBeNull();
    const { managedPath, importToken } = picked as unknown as PendingImport;
    expect(fs.existsSync(managedPath)).toBe(true);

    // Create a "victim" — a separately-named managed file outside the
    // staging directory that MUST survive the discard call.
    const victimDir = path.dirname(managedPath) + '__keep';
    fs.mkdirSync(victimDir, { recursive: true });
    const victimPath = path.join(victimDir, 'victim.xlsx');
    fs.writeFileSync(victimPath, Buffer.from('PK victim'));

    const discardHandler = registeredHandlers.get('office:discard-import')!;
    await discardHandler({}, { importToken });

    expect(fs.existsSync(managedPath), 'staged file removed').toBe(false);
    expect(fs.existsSync(victimPath), 'unrelated file untouched').toBe(true);

    // Calling discard again is a no-op.
    await expect(discardHandler({}, { importToken })).resolves.toBeUndefined();

    fs.unlinkSync(victimPath);
    fs.rmdirSync(victimDir);
    fs.unlinkSync(tmpSrc);
  });

  it('discard-import with an unknown token is a no-op (no delete)', async () => {
    // Pre-create a victim file at the same place a real import would
    // land. A forged token must NOT delete it.
    const fake = path.join(os.tmpdir(), `sage-forged-${Date.now()}.pptx`);
    fs.writeFileSync(fake, Buffer.from('PK keep me'));

    const discardHandler = registeredHandlers.get('office:discard-import')!;
    await expect(discardHandler({}, { importToken: 'deadbeef-not-real' })).resolves.toBeUndefined();
    expect(fs.existsSync(fake), 'forged token MUST NOT delete an arbitrary file').toBe(true);

    fs.unlinkSync(fake);
  });
});

describe('office:save-as (brief §Step 5)', () => {
  beforeEach(() => {
    registeredHandlers.clear();
    mocks.dialog.showOpenDialog.mockReset();
    mocks.dialog.showSaveDialog.mockReset();
    mocks.shell.openPath.mockReset();
    mocks.shell.showItemInFolder.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReturnValue(null);
    __resetPendingImportsForTests();
    registerOfficeIpc(fakeRegister);
  });

  it('returns null when the user cancels the save dialog', async () => {
    mocks.dialog.showSaveDialog.mockResolvedValue({ canceled: true, filePath: undefined });
    const handler = registeredHandlers.get('office:save-as')!;
    const result = await handler({}, {
      workspacePath: '/workspace',
      docType: 'ppt',
      documentId: 'doc-001',
      filename: 'deck.pptx',
    });
    expect(result).toBeNull();
  });

  it('returns the chosen savedPath and copies the managed file', async () => {
    // First stage a managed file via pick-and-import.
    const tmpSrc = path.join(os.tmpdir(), `sage-saveas-src-${Date.now()}.pptx`);
    fs.writeFileSync(tmpSrc, Buffer.from('PK source'));
    mocks.dialog.showOpenDialog.mockResolvedValue({
      canceled: false,
      filePaths: [tmpSrc],
    });
    const pickHandler = registeredHandlers.get('office:pick-and-import')!;
    const picked = (await pickHandler({}, { workspacePath: '/tmp/ws', docType: 'ppt' })) as PendingImport;

    const tmpDst = path.join(os.tmpdir(), `sage-saveas-dst-${Date.now()}.pptx`);
    mocks.dialog.showSaveDialog.mockResolvedValue({ canceled: false, filePath: tmpDst });
    const handler = registeredHandlers.get('office:save-as')!;
    const result = (await handler({}, {
      workspacePath: picked.workspacePath,
      docType: picked.docType,
      documentId: picked.documentId,
      filename: path.basename(picked.managedPath),
    })) as { savedPath: string } | null;
    expect(result).not.toBeNull();
    expect(result!.savedPath).toBe(tmpDst);
    expect(fs.existsSync(tmpDst)).toBe(true);

    fs.unlinkSync(tmpSrc);
    try {
      fs.unlinkSync(tmpDst);
    } catch {
      /* ignore */
    }
  });
});

describe('office:open + office:show-in-folder (brief §Step 5)', () => {
  beforeEach(() => {
    registeredHandlers.clear();
    mocks.dialog.showOpenDialog.mockReset();
    mocks.dialog.showSaveDialog.mockReset();
    mocks.shell.openPath.mockReset();
    mocks.shell.showItemInFolder.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReturnValue(null);
    __resetPendingImportsForTests();
    registerOfficeIpc(fakeRegister);
  });

  it('office:open calls shell.openPath on the validated managed file', async () => {
    const tmpSrc = path.join(os.tmpdir(), `sage-open-${Date.now()}.pptx`);
    fs.writeFileSync(tmpSrc, Buffer.from('PK'));
    mocks.dialog.showOpenDialog.mockResolvedValue({
      canceled: false,
      filePaths: [tmpSrc],
    });
    const pickHandler = registeredHandlers.get('office:pick-and-import')!;
    const picked = (await pickHandler({}, {
      workspacePath: '/tmp/ws',
      docType: 'ppt',
    })) as PendingImport;

    mocks.shell.openPath.mockResolvedValue(''); // success -> empty string
    const openHandler = registeredHandlers.get('office:open')!;
    // Use the REAL {documentId, filename} tuple captured from the
    // import — the gateway must reconstruct the managed path itself,
    // not trust a renderer-supplied (and possibly mismatched) tuple.
    await expect(
      openHandler({}, {
        workspacePath: picked.workspacePath,
        docType: picked.docType,
        documentId: picked.documentId,
        filename: path.basename(picked.managedPath),
      }),
    ).resolves.toBeUndefined();

    expect(mocks.shell.openPath).toHaveBeenCalledTimes(1);

    fs.unlinkSync(tmpSrc);
    if (picked) {
      try {
        fs.unlinkSync((picked as PendingImport).managedPath);
      } catch {
        /* ignore */
      }
    }
  });

  it('office:open throws a typed error when shell.openPath returns non-empty', async () => {
    const tmpSrc = path.join(os.tmpdir(), `sage-open-fail-${Date.now()}.pptx`);
    fs.writeFileSync(tmpSrc, Buffer.from('PK'));
    mocks.dialog.showOpenDialog.mockResolvedValue({
      canceled: false,
      filePaths: [tmpSrc],
    });
    const picked = (await registeredHandlers.get('office:pick-and-import')!({}, {
      workspacePath: '/tmp/ws',
      docType: 'ppt',
    })) as PendingImport;

    mocks.shell.openPath.mockResolvedValue('no app associated');
    const openHandler = registeredHandlers.get('office:open')!;
    await expect(
      openHandler({}, {
        workspacePath: picked.workspacePath,
        docType: picked.docType,
        documentId: picked.documentId,
        filename: path.basename(picked.managedPath),
      }),
    ).rejects.toThrow(/openPath failed/);

    fs.unlinkSync(tmpSrc);
  });

  it('office:show-in-folder delegates to shell.showItemInFolder on managed file', async () => {
    const tmpSrc = path.join(os.tmpdir(), `sage-show-${Date.now()}.pptx`);
    fs.writeFileSync(tmpSrc, Buffer.from('PK'));
    mocks.dialog.showOpenDialog.mockResolvedValue({
      canceled: false,
      filePaths: [tmpSrc],
    });
    const picked = (await registeredHandlers.get('office:pick-and-import')!({}, {
      workspacePath: '/tmp/ws',
      docType: 'ppt',
    })) as PendingImport;

    mocks.shell.showItemInFolder.mockReset();
    const showHandler = registeredHandlers.get('office:show-in-folder')!;
    await expect(
      showHandler({}, {
        workspacePath: picked.workspacePath,
        docType: picked.docType,
        documentId: picked.documentId,
        filename: path.basename(picked.managedPath),
      }),
    ).resolves.toBeUndefined();
    expect(mocks.shell.showItemInFolder).toHaveBeenCalledTimes(1);

    fs.unlinkSync(tmpSrc);
  });

  // Sanity: the bridge handlers never accept raw renderer paths —
  // they reconstruct the managed source path from OfficeManagedRef.
  it('office:open refuses to open a renderer-supplied raw path (managed-path reconstruction only)', async () => {
    mocks.shell.openPath.mockResolvedValue('');
    const openHandler = registeredHandlers.get('office:open')!;
    // No prior import — passing a fabricated documentId has no file to open.
    await expect(
      openHandler({}, {
        workspacePath: '/tmp/ws',
        docType: 'ppt',
        documentId: 'no-such-doc',
        filename: 'deck.pptx',
      }),
    ).rejects.toThrow();
  });
});
describe('sweepOrphanStaging', () => {
  beforeEach(() => __resetPendingImportsForTests());
  const ws = () => { const x = path.join(os.tmpdir(), `sage-sweep-${Date.now()}-${Math.random().toString(36).slice(2)}`); fs.mkdirSync(x, { recursive: true }); return x; };
  const clean = (x: string) => fs.rmSync(x, { recursive: true, force: true });
  it('returns swept:0 when workspace has no office/ directory', async () => { const x=ws(); try { expect(await sweepOrphanStaging(x,new Set())).toEqual({swept:0}); } finally {clean(x);} });
  it('returns swept:0 when office/ exists but has no docType subdirs', async () => { const x=ws(); fs.mkdirSync(path.join(x,'office')); try { expect(await sweepOrphanStaging(x,new Set())).toEqual({swept:0}); } finally {clean(x);} });
  it('removes a single orphan ppt dir when its name is not in knownDocIds', async () => { const x=ws(), d=path.join(x,'office','ppt','orphan'); fs.mkdirSync(path.join(d,'inner'),{recursive:true}); fs.writeFileSync(path.join(d,'inner','deck.pptx'),'fake'); try { expect(await sweepOrphanStaging(x,new Set())).toEqual({swept:1}); expect(fs.existsSync(d)).toBe(false); } finally {clean(x);} });
  it('preserves a managed dir whose name is in knownDocIds', async () => { const x=ws(), d=path.join(x,'office','ppt','managed'); fs.mkdirSync(d,{recursive:true}); try { expect(await sweepOrphanStaging(x,new Set(['managed']))).toEqual({swept:0}); expect(fs.existsSync(d)).toBe(true); } finally {clean(x);} });
  it('removes only orphans when 3 dirs exist (2 orphan + 1 managed)', async () => { const x=ws(), ds=['a','b','managed'].map((n,i)=>path.join(x,'office',i===1?'word':'ppt',n)); ds.forEach(d=>fs.mkdirSync(d,{recursive:true})); try { expect(await sweepOrphanStaging(x,new Set(['managed']))).toEqual({swept:2}); expect(fs.existsSync(ds[2])).toBe(true); } finally {clean(x);} });
  it('does not abort the sweep when one rm fails (best-effort)', async () => { const x=ws(), d=path.join(x,'office','ppt','ok'); fs.mkdirSync(d,{recursive:true}); try { expect(await sweepOrphanStaging(x,new Set())).toEqual({swept:1}); } finally {clean(x);} });
});
