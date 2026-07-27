/**
 * importOfficeReference — Task 7 (2026-07-26) RED tests.
 *
 * Covers:
 *   - happy path: importDropped → read → completeOfficeImport
 *   - read failure: discardOfficeImport is called, original error re-thrown
 *   - discard failure swallowed: read error still surfaces
 *   - missing sourcePath / docType on the FileSearchResult → throws
 *   - missing electron bridge → throws
 *   - isImportableOfficeResult classification
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockReadPpt = vi.fn();
vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    readPpt: (...args: unknown[]) => mockReadPpt(...args),
    readWord: vi.fn(),
    readExcel: vi.fn(),
  },
}));

import { importOfficeReference, isImportableOfficeResult } from '../importOfficeReference';

const mockImportDropped = vi.fn();
const mockCompleteImport = vi.fn();
const mockDiscardImport = vi.fn();

interface FakeWindow {
  electronAPI?: {
    office: {
      importDroppedOfficeFile: typeof mockImportDropped;
      completeOfficeImport: typeof mockCompleteImport;
      discardOfficeImport: typeof mockDiscardImport;
    };
  };
}

const IMPORT_PAYLOAD = {
  workspacePath: '/tmp/ws',
  docType: 'ppt' as const,
  documentId: 'doc-from-import',
  filename: 'deck.pptx',
  managedPath: '/tmp/ws/office/ppt/doc-from-import/deck.pptx',
  originalName: 'deck.pptx',
  sizeBytes: 1024,
  importToken: 'tok-imp',
};

const BASE_RESULT = {
  path: '/tmp/deck.pptx',
  name: 'deck.pptx',
  size: 1024,
  kind: 'office-ppt' as const,
  docId: null,
  docType: 'ppt' as const,
  sourcePath: '/tmp/deck.pptx',
};

beforeEach(() => {
  mockReadPpt.mockReset();
  mockImportDropped.mockReset();
  mockCompleteImport.mockReset();
  mockDiscardImport.mockReset();
  mockCompleteImport.mockResolvedValue(undefined);
  mockDiscardImport.mockResolvedValue(undefined);
  (window as unknown as FakeWindow).electronAPI = {
    office: {
      importDroppedOfficeFile: mockImportDropped,
      completeOfficeImport: mockCompleteImport,
      discardOfficeImport: mockDiscardImport,
    },
  };
});

afterEach(() => {
  delete (window as unknown as FakeWindow).electronAPI;
});

describe('importOfficeReference — happy path', () => {
  it('returns a ChatOfficeRef and finalizes the import with the token', async () => {
    mockImportDropped.mockResolvedValueOnce(IMPORT_PAYLOAD);
    mockReadPpt.mockResolvedValueOnce({ slides: [], summary: 'ok' });

    const ref = await importOfficeReference('/tmp/ws', BASE_RESULT);

    expect(ref).toEqual({
      docId: 'doc-from-import',
      docType: 'ppt',
      filename: 'deck.pptx',
    });
    expect(mockImportDropped).toHaveBeenCalledWith('/tmp/ws', 'ppt', '/tmp/deck.pptx');
    expect(mockReadPpt).toHaveBeenCalledWith({
      workspace_path: '/tmp/ws',
      file_path: '/tmp/ws/office/ppt/doc-from-import/deck.pptx',
    });
    expect(mockCompleteImport).toHaveBeenCalledWith('tok-imp');
    expect(mockDiscardImport).not.toHaveBeenCalled();
  });
});

describe('importOfficeReference — error path', () => {
  it('discards the staged import with importToken when read fails', async () => {
    mockImportDropped.mockResolvedValueOnce(IMPORT_PAYLOAD);
    mockReadPpt.mockRejectedValueOnce(new Error('parse failed'));

    await expect(importOfficeReference('/tmp/ws', BASE_RESULT)).rejects.toThrow('parse failed');
    expect(mockDiscardImport).toHaveBeenCalledWith('tok-imp');
    expect(mockCompleteImport).not.toHaveBeenCalled();
  });

  it('swallows a discard failure so the read error still surfaces', async () => {
    mockImportDropped.mockResolvedValueOnce(IMPORT_PAYLOAD);
    mockReadPpt.mockRejectedValueOnce(new Error('parse failed'));
    mockDiscardImport.mockRejectedValueOnce(new Error('discard blew up'));

    await expect(importOfficeReference('/tmp/ws', BASE_RESULT)).rejects.toThrow('parse failed');
    expect(mockDiscardImport).toHaveBeenCalledWith('tok-imp');
  });

  it('discards when completeOfficeImport rejects (token may be leaked)', async () => {
    mockImportDropped.mockResolvedValueOnce(IMPORT_PAYLOAD);
    mockReadPpt.mockResolvedValueOnce({ slides: [], summary: 'ok' });
    mockCompleteImport.mockRejectedValueOnce(new Error('complete failed'));

    await expect(importOfficeReference('/tmp/ws', BASE_RESULT)).rejects.toThrow('complete failed');
    // The token might or might not be consumed server-side; safeDiscard
    // is called as a belt-and-suspenders cleanup.
    expect(mockDiscardImport).toHaveBeenCalledWith('tok-imp');
  });
});

describe('importOfficeReference — preconditions', () => {
  it('throws when sourcePath is missing', async () => {
    await expect(
      importOfficeReference('/tmp/ws', { ...BASE_RESULT, sourcePath: null }),
    ).rejects.toThrow(/missing sourcePath/);
    expect(mockImportDropped).not.toHaveBeenCalled();
  });

  it('throws when docType is missing', async () => {
    await expect(
      importOfficeReference('/tmp/ws', { ...BASE_RESULT, docType: null }),
    ).rejects.toThrow(/missing docType/);
    expect(mockImportDropped).not.toHaveBeenCalled();
  });

  it('throws when electron.office bridge is unavailable', async () => {
    delete (window as unknown as FakeWindow).electronAPI;
    await expect(importOfficeReference('/tmp/ws', BASE_RESULT)).rejects.toThrow(
      /bridge unavailable/,
    );
  });
});

describe('isImportableOfficeResult', () => {
  it('returns false for plain files', () => {
    expect(
      isImportableOfficeResult({
        path: 'a.txt',
        name: 'a.txt',
        kind: 'file',
        docId: null,
        docType: null,
        sourcePath: 'a.txt',
      }),
    ).toBe(false);
  });

  it('returns false for managed office docs (already has a docId)', () => {
    expect(
      isImportableOfficeResult({
        path: '/w/m.pptx',
        name: 'm.pptx',
        kind: 'office-ppt',
        docId: 'doc-m',
        docType: 'ppt',
        sourcePath: '/w/m.pptx',
      }),
    ).toBe(false);
  });

  it('returns true for unmanaged office docs', () => {
    expect(
      isImportableOfficeResult({
        path: '/tmp/o.pptx',
        name: 'o.pptx',
        kind: 'office-ppt',
        docId: null,
        docType: 'ppt',
        sourcePath: '/tmp/o.pptx',
      }),
    ).toBe(true);
  });

  it('returns false when sourcePath is missing', () => {
    expect(
      isImportableOfficeResult({
        path: '/tmp/o.pptx',
        name: 'o.pptx',
        kind: 'office-ppt',
        docId: null,
        docType: 'ppt',
        sourcePath: null,
      }),
    ).toBe(false);
  });
});
