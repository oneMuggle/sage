/**
 * useOfficeDocuments — Task 6 fix tests (2026-07-24).
 *
 * Focus: the import-token lifecycle owned by the hook.
 *   - success  → `completeOfficeImport(importToken)`
 *   - read fail → `discardOfficeImport(importToken)` (the `safeDiscard` path)
 *   - cancel   → returns `null`, no complete/discard
 *
 * The I1 review finding: `safeDiscard` had no vitest coverage. The core
 * case here resolves the pick, rejects the read, and asserts the staged
 * import is discarded with the token.
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockListDocuments = vi.fn();
const mockReadPpt = vi.fn();
const mockArchiveDocument = vi.fn();
const mockRestoreDocument = vi.fn();
vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    listDocuments: (...args: unknown[]) => mockListDocuments(...args),
    readPpt: (...args: unknown[]) => mockReadPpt(...args),
    readWord: vi.fn(),
    readExcel: vi.fn(),
    readPdf: vi.fn(),
    archiveDocument: (...args: unknown[]) => mockArchiveDocument(...args),
    restoreDocument: (...args: unknown[]) => mockRestoreDocument(...args),
    listSnapshots: vi.fn(),
    restoreSnapshot: vi.fn(),
  },
}));

import { useOfficeDocuments } from '../useOfficeDocuments';

const mockPickAndImport = vi.fn();
const mockCompleteImport = vi.fn();
const mockDiscardImport = vi.fn();
const mockSweepOrphanStaging = vi.fn();

interface FakeWindow {
  electronAPI?: {
    office: {
      pickAndImportOfficeFile: typeof mockPickAndImport;
      completeOfficeImport: typeof mockCompleteImport;
      discardOfficeImport: typeof mockDiscardImport;
      sweepOrphanStaging: typeof mockSweepOrphanStaging;
    };
  };
}

const IMPORT_PAYLOAD = {
  workspacePath: '/tmp/ws',
  docType: 'ppt' as const,
  documentId: 'tok-1',
  filename: 'deck.pptx',
  managedPath: '/tmp/ws/office/ppt/tok-1/deck.pptx',
  originalName: 'deck.pptx',
  sizeBytes: 1024,
  importToken: 'tok-1',
};

beforeEach(() => {
  mockListDocuments.mockReset();
  mockReadPpt.mockReset();
  mockArchiveDocument.mockReset();
  mockRestoreDocument.mockReset();
  mockPickAndImport.mockReset();
  mockCompleteImport.mockReset();
  mockDiscardImport.mockReset();
  mockSweepOrphanStaging.mockReset();
  mockListDocuments.mockResolvedValue({ documents: [] });
  mockArchiveDocument.mockResolvedValue({ ok: true, summary: {} });
  mockRestoreDocument.mockResolvedValue({ ok: true, summary: {} });
  mockCompleteImport.mockResolvedValue(undefined);
  mockDiscardImport.mockResolvedValue(undefined);
  mockSweepOrphanStaging.mockResolvedValue({ swept: 0 });
  (window as unknown as FakeWindow).electronAPI = {
    office: {
      pickAndImportOfficeFile: mockPickAndImport,
      completeOfficeImport: mockCompleteImport,
      discardOfficeImport: mockDiscardImport,
      sweepOrphanStaging: mockSweepOrphanStaging,
    },
  };
});

afterEach(() => {
  delete (window as unknown as FakeWindow).electronAPI;
});

describe('useOfficeDocuments — importAndRead token lifecycle', () => {
  it('discards the staged import with importToken when the read fails (safeDiscard)', async () => {
    mockPickAndImport.mockResolvedValueOnce(IMPORT_PAYLOAD);
    mockReadPpt.mockRejectedValueOnce(new Error('parse failed'));

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    await act(async () => {
      await expect(result.current.importAndRead('ppt')).rejects.toThrow('parse failed');
    });

    expect(mockDiscardImport).toHaveBeenCalledWith('tok-1');
    expect(mockCompleteImport).not.toHaveBeenCalled();
  });

  it('swallows a discard failure so the read error still surfaces', async () => {
    mockPickAndImport.mockResolvedValueOnce(IMPORT_PAYLOAD);
    mockReadPpt.mockRejectedValueOnce(new Error('parse failed'));
    mockDiscardImport.mockRejectedValueOnce(new Error('discard blew up'));

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    await act(async () => {
      // The read error — not the discard error — is what propagates.
      await expect(result.current.importAndRead('ppt')).rejects.toThrow('parse failed');
    });

    expect(mockDiscardImport).toHaveBeenCalledWith('tok-1');
  });

  it('completes the import (not discard) when the read succeeds', async () => {
    mockPickAndImport.mockResolvedValueOnce(IMPORT_PAYLOAD);
    mockReadPpt.mockResolvedValueOnce({ slides: [], summary: 'ok' });

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    let read: unknown;
    await act(async () => {
      read = await result.current.importAndRead('ppt');
    });

    expect(read).toEqual({ slides: [], summary: 'ok' });
    expect(mockCompleteImport).toHaveBeenCalledWith('tok-1');
    expect(mockDiscardImport).not.toHaveBeenCalled();
  });

  it('returns null and touches neither complete nor discard on user cancel', async () => {
    mockPickAndImport.mockResolvedValueOnce(undefined); // dialog cancelled

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    let read: unknown = 'sentinel';
    await act(async () => {
      read = await result.current.importAndRead('ppt');
    });

    expect(read).toBeNull();
    expect(mockReadPpt).not.toHaveBeenCalled();
    expect(mockCompleteImport).not.toHaveBeenCalled();
    expect(mockDiscardImport).not.toHaveBeenCalled();
  });
});

describe('useOfficeDocuments — workspace entry sweep', () => {
  it('calls listDocuments then sweepOrphanStaging with the same workspace and known ids', async () => {
    mockListDocuments.mockResolvedValue({
      documents: [
        {
          id: 'doc-a',
          workspace_path: '/tmp/ws',
          doc_type: 'ppt',
          original_filename: 'a.pptx',
          generated_filename: 'a.pptx',
          status: 'parsed',
          created_at: 0,
          updated_at: 0,
          metadata: { file_size_bytes: 1 },
        },
        {
          id: 'doc-b',
          workspace_path: '/tmp/ws',
          doc_type: 'word',
          original_filename: 'b.docx',
          generated_filename: 'b.docx',
          status: 'parsed',
          created_at: 0,
          updated_at: 0,
          metadata: { file_size_bytes: 1 },
        },
      ],
    });
    mockSweepOrphanStaging.mockResolvedValue({ swept: 0 });

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));

    await waitFor(() => {
      expect(result.current.documents).toHaveLength(2);
    });
    // Item 1.7: listDocuments now carries the include_archived flag
    // (false on the default live view).
    expect(mockListDocuments).toHaveBeenCalledWith('/tmp/ws', { includeArchived: false });
    expect(mockSweepOrphanStaging).toHaveBeenCalledWith({
      workspacePath: '/tmp/ws',
      knownDocIds: ['doc-a', 'doc-b'],
    });
  });

  it('archived view fetches with includeArchived and keeps only archived rows (item 1.7)', async () => {
    const liveDoc = {
      id: 'doc-live',
      workspace_path: '/tmp/ws',
      doc_type: 'word',
      original_filename: null,
      generated_filename: 'live.docx',
      status: 'parsed',
      created_at: 0,
      updated_at: 0,
      metadata: { file_size_bytes: 1 },
      archived_at: null,
    };
    const archivedDoc = {
      id: 'doc-arch',
      workspace_path: '/tmp/ws',
      doc_type: 'pdf',
      original_filename: 'old.pdf',
      generated_filename: 'old.pdf',
      status: 'parsed',
      created_at: 0,
      updated_at: 0,
      metadata: { file_size_bytes: 1 },
      archived_at: 1700000000,
    };
    mockListDocuments.mockResolvedValue({ documents: [liveDoc, archivedDoc] });

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(result.current.view).toBe('live'));
    await waitFor(() => {
      expect(result.current.documents).toHaveLength(2);
    });

    await act(async () => {
      result.current.setView('archived');
    });
    await waitFor(() => {
      expect(mockListDocuments).toHaveBeenCalledWith('/tmp/ws', { includeArchived: true });
    });
    await waitFor(() => {
      expect(result.current.documents.map((d) => d.id)).toEqual(['doc-arch']);
    });
  });

  it('archiveDocument calls officeApi then re-fetches the current view', async () => {
    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    const callsBefore = mockListDocuments.mock.calls.length;
    await act(async () => {
      await result.current.archiveDocument('doc-a');
    });
    expect(mockArchiveDocument).toHaveBeenCalledWith('doc-a');
    await waitFor(() => {
      expect(mockListDocuments.mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  it('restoreDocument calls officeApi then re-fetches the current view', async () => {
    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    const callsBefore = mockListDocuments.mock.calls.length;
    await act(async () => {
      await result.current.restoreDocument('doc-arch');
    });
    expect(mockRestoreDocument).toHaveBeenCalledWith('doc-arch');
    await waitFor(() => {
      expect(mockListDocuments.mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  it('skips sweep when listDocuments rejects (no known ids to gate on)', async () => {
    mockListDocuments.mockRejectedValue(new Error('backend down'));

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));

    await waitFor(() => {
      expect(result.current.error).toMatch(/backend down/);
    });
    expect(mockSweepOrphanStaging).not.toHaveBeenCalled();
  });

  it('surfaces sweep failure without losing the documents list', async () => {
    mockListDocuments.mockResolvedValue({
      documents: [
        {
          id: 'doc-x',
          workspace_path: '/tmp/ws',
          doc_type: 'ppt',
          original_filename: 'x.pptx',
          generated_filename: 'x.pptx',
          status: 'parsed',
          created_at: 0,
          updated_at: 0,
          metadata: { file_size_bytes: 1 },
        },
      ],
    });
    mockSweepOrphanStaging.mockRejectedValue(new Error('rm failed'));

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));

    await waitFor(() => {
      expect(result.current.documents).toHaveLength(1);
    });
    await waitFor(() => {
      expect(result.current.error).toMatch(/rm failed/);
    });
  });

  it('does not setDocuments on an unmounted hook when workspace changes mid-flight', async () => {
    let resolveFirstList: ((v: { documents: unknown[] }) => void) | null = null;
    mockListDocuments
      .mockImplementationOnce(
        () =>
          new Promise((res) => {
            resolveFirstList = res;
          }),
      )
      .mockImplementationOnce(() => new Promise(() => undefined));
    mockSweepOrphanStaging.mockResolvedValue({ swept: 0 });

    const { result, rerender } = renderHook(({ ws }) => useOfficeDocuments(ws), {
      initialProps: { ws: '/tmp/first' },
    });
    rerender({ ws: '/tmp/second' });
    resolveFirstList!({ documents: [] });
    await waitFor(() => {
      expect(result.current.documents).toEqual([]);
    });
    expect(mockSweepOrphanStaging).not.toHaveBeenCalled();
  });
});

describe('useOfficeDocuments — batch archive/restore (round-3 N5)', () => {
  it('loops restoreDocument once per id, refetches once and reports per-item outcomes', async () => {
    mockRestoreDocument.mockImplementation(async (id: string) => {
      if (id === 'doc-b') throw new Error('restore blew up');
      return { ok: true };
    });

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalledTimes(1));

    let out: { succeeded: string[]; failed: string[] } | undefined;
    await act(async () => {
      out = await result.current.batchRestore(['doc-a', 'doc-b', 'doc-c']);
    });

    // Restore called N times — once per selected doc, sequentially.
    expect(mockRestoreDocument).toHaveBeenCalledTimes(3);
    expect(mockRestoreDocument).toHaveBeenNthCalledWith(1, 'doc-a');
    expect(mockRestoreDocument).toHaveBeenNthCalledWith(2, 'doc-b');
    expect(mockRestoreDocument).toHaveBeenNthCalledWith(3, 'doc-c');
    // Failed ids are counted, not thrown.
    expect(out).toEqual({ succeeded: ['doc-a', 'doc-c'], failed: ['doc-b'] });
    // ONE refetch for the whole batch (initial list + post-batch refresh).
    expect(mockListDocuments).toHaveBeenCalledTimes(2);
  });

  it('batchArchive follows the same loop contract when every item succeeds', async () => {
    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalledTimes(1));

    let out: { succeeded: string[]; failed: string[] } | undefined;
    await act(async () => {
      out = await result.current.batchArchive(['doc-a', 'doc-b']);
    });

    expect(mockArchiveDocument).toHaveBeenCalledTimes(2);
    expect(out).toEqual({ succeeded: ['doc-a', 'doc-b'], failed: [] });
    expect(mockListDocuments).toHaveBeenCalledTimes(2);
  });
});
