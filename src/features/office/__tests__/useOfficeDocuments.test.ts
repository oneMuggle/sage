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
const mockReadWord = vi.fn();
const mockCheckDuplicates = vi.fn();
const mockSetDocumentLineage = vi.fn();
const mockArchiveDocument = vi.fn();
const mockRestoreDocument = vi.fn();
vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    listDocuments: (...args: unknown[]) => mockListDocuments(...args),
    readPpt: (...args: unknown[]) => mockReadPpt(...args),
    readWord: (...args: unknown[]) => mockReadWord(...args),
    readExcel: vi.fn(),
    readPdf: vi.fn(),
    checkDuplicates: (...args: unknown[]) => mockCheckDuplicates(...args),
    setDocumentLineage: (...args: unknown[]) => mockSetDocumentLineage(...args),
    archiveDocument: (...args: unknown[]) => mockArchiveDocument(...args),
    restoreDocument: (...args: unknown[]) => mockRestoreDocument(...args),
    listSnapshots: vi.fn(),
    restoreSnapshot: vi.fn(),
  },
}));

import type { OfficeDocumentSummary } from '../../../shared/api/types';
import { useOfficeDocuments, type OfficeMultiImportResult } from '../useOfficeDocuments';

const mockPickAndImport = vi.fn();
const mockCompleteImport = vi.fn();
const mockDiscardImport = vi.fn();
const mockSweepOrphanStaging = vi.fn();
const mockImportDroppedMulti = vi.fn();

interface FakeWindow {
  electronAPI?: {
    office: {
      pickAndImportOfficeFile: typeof mockPickAndImport;
      completeOfficeImport: typeof mockCompleteImport;
      discardOfficeImport: typeof mockDiscardImport;
      sweepOrphanStaging: typeof mockSweepOrphanStaging;
      importDroppedMultiOfficeFiles: typeof mockImportDroppedMulti;
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
  mockReadWord.mockReset();
  mockCheckDuplicates.mockReset();
  mockSetDocumentLineage.mockReset();
  mockArchiveDocument.mockReset();
  mockRestoreDocument.mockReset();
  mockPickAndImport.mockReset();
  mockCompleteImport.mockReset();
  mockDiscardImport.mockReset();
  mockSweepOrphanStaging.mockReset();
  mockImportDroppedMulti.mockReset();
  mockListDocuments.mockResolvedValue({ documents: [] });
  mockArchiveDocument.mockResolvedValue({ ok: true, summary: {} });
  mockRestoreDocument.mockResolvedValue({ ok: true, summary: {} });
  mockCompleteImport.mockResolvedValue(undefined);
  mockDiscardImport.mockResolvedValue(undefined);
  mockSweepOrphanStaging.mockResolvedValue({ swept: 0 });
  // Default: no staged file is a duplicate, so batches import straight away.
  mockCheckDuplicates.mockResolvedValue({ files: [] });
  mockSetDocumentLineage.mockResolvedValue({ updated: true });
  (window as unknown as FakeWindow).electronAPI = {
    office: {
      pickAndImportOfficeFile: mockPickAndImport,
      completeOfficeImport: mockCompleteImport,
      discardOfficeImport: mockDiscardImport,
      sweepOrphanStaging: mockSweepOrphanStaging,
      importDroppedMultiOfficeFiles: mockImportDroppedMulti,
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
  it('lists documents without invoking destructive cleanup', async () => {
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
    expect(mockSweepOrphanStaging).not.toHaveBeenCalled();
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
      expect(mockSweepOrphanStaging).not.toHaveBeenCalled();
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

  it('does not invoke legacy sweep even when it would fail', async () => {
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
    expect(result.current.error).toBeNull();
    expect(mockSweepOrphanStaging).not.toHaveBeenCalled();
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

  it('formats office documents batch summary and JSON (Phase P110)', async () => {
    const { formatOfficeDocumentsBatchSummary, formatOfficeDocumentsBatchJson } = await import(
      '../useOfficeDocuments'
    );
    const res = { succeeded: ['doc-a', 'doc-c'], failed: ['doc-b'] };
    expect(formatOfficeDocumentsBatchSummary(res)).toBe('succeeded=2 · failed=1');
    const parsed = JSON.parse(formatOfficeDocumentsBatchJson(res));
    expect(parsed.total).toBe(3);
    expect(parsed.succeededCount).toBe(2);
    expect(parsed.failedCount).toBe(1);
  });
});

describe('useOfficeDocuments — import duplicate gate (AI workbench Phase 0)', () => {
  const EXISTING_DOC: OfficeDocumentSummary = {
    id: 'doc-existing',
    workspace_path: '/tmp/ws',
    doc_type: 'word',
    original_filename: 'dup.docx',
    generated_filename: 'doc-existing.docx',
    status: 'parsed',
    created_at: 1700000000,
    updated_at: 1700000000,
    metadata: { file_size_bytes: 10 },
    derived_from: null,
    archived_at: null,
  };

  function makeStaged(index: number) {
    const token = `tok-${index}`;
    return {
      workspacePath: '/tmp/ws',
      docType: 'word' as const,
      documentId: token,
      filename: `f${index}.docx`,
      managedPath: `/tmp/ws/office/word/${token}/f${index}.docx`,
      originalName: `f${index}.docx`,
      sizeBytes: 10,
      importToken: token,
    };
  }

  function duplicateCheck(fileIndex: number) {
    return {
      files: [
        {
          file_path: `/tmp/ws/office/word/tok-${fileIndex}/f${fileIndex}.docx`,
          content_hash: 'sha256:' + 'a'.repeat(64),
          duplicates: [EXISTING_DOC],
        },
      ],
    };
  }

  /**
   * Start a batch that is expected to pause on the duplicate gate.
   *
   * The batch promise is handed back inside an object on purpose: an
   * `async` helper that RETURNED the promise would await it before
   * resolving, which deadlocks — the batch only finishes once the user
   * picks a duplicate action, and that choice cannot be made until this
   * helper returns.
   */
  async function startPausedBatch(result: {
    current: ReturnType<typeof useOfficeDocuments>;
  }): Promise<{ batch: Promise<OfficeMultiImportResult> }> {
    let batch!: Promise<OfficeMultiImportResult>;
    await act(async () => {
      batch = result.current.readDroppedMulti(['/tmp/src/f0.docx']);
      // Let the pre-flight settle: stage → hash check → dialog state.
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    await waitFor(() => expect(result.current.pendingDuplicate).not.toBeNull());
    return { batch };
  }

  it('pauses on a duplicate and opens the existing doc without re-reading or importing', async () => {
    mockImportDroppedMulti.mockResolvedValue({ imported: [makeStaged(0)], skipped: [] });
    mockCheckDuplicates.mockResolvedValueOnce(duplicateCheck(0));

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    const { batch } = await startPausedBatch(result);
    expect(result.current.pendingDuplicate?.filename).toBe('f0.docx');
    expect(result.current.pendingDuplicate?.duplicates[0].id).toBe('doc-existing');
    expect(result.current.pendingDuplicate?.contentHash).toBe('sha256:' + 'a'.repeat(64));

    act(() => {
      result.current.resolvePendingDuplicate('open-existing');
    });
    const out = await batch;
    expect(mockCheckDuplicates).toHaveBeenCalledWith('/tmp/ws', [
      '/tmp/ws/office/word/tok-0/f0.docx',
    ]);
    // Open-existing: staged copy discarded, nothing read or finalized.
    expect(mockDiscardImport).toHaveBeenCalledWith('tok-0');
    expect(mockReadWord).not.toHaveBeenCalled();
    expect(mockCompleteImport).not.toHaveBeenCalled();
    expect(out.imported).toEqual([]);
    expect(out.openedExisting.map((doc) => doc.id)).toEqual(['doc-existing']);
    expect(out.skipped).toEqual([
      { filename: 'f0.docx', reason: 'duplicate-open-existing', message: 'dup.docx' },
    ]);
    expect(result.current.pendingDuplicate).toBeNull();
  });

  it('new-version imports normally and records lineage to the existing doc', async () => {
    mockImportDroppedMulti.mockResolvedValue({ imported: [makeStaged(0)], skipped: [] });
    mockCheckDuplicates.mockResolvedValueOnce(duplicateCheck(0));
    const readResult = { paragraphs: [] };
    mockReadWord.mockResolvedValueOnce(readResult);

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    const { batch } = await startPausedBatch(result);

    let out!: OfficeMultiImportResult;
    await act(async () => {
      result.current.resolvePendingDuplicate('new-version');
      out = await batch;
    });

    expect(mockReadWord).toHaveBeenCalledWith({
      workspace_path: '/tmp/ws',
      file_path: '/tmp/ws/office/word/tok-0/f0.docx',
    });
    expect(mockCompleteImport).toHaveBeenCalledWith('tok-0');
    expect(mockDiscardImport).not.toHaveBeenCalled();
    expect(mockSetDocumentLineage).toHaveBeenCalledWith('tok-0', 'doc-existing');
    expect(out.imported).toHaveLength(1);
    expect(out.imported[0].readResult).toBe(readResult);
    expect(out.openedExisting).toEqual([]);
  });

  it('keep-copy imports the file without lineage or discard', async () => {
    mockImportDroppedMulti.mockResolvedValue({ imported: [makeStaged(0)], skipped: [] });
    mockCheckDuplicates.mockResolvedValueOnce(duplicateCheck(0));
    mockReadWord.mockResolvedValueOnce({ paragraphs: [] });

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    const { batch } = await startPausedBatch(result);

    let out!: OfficeMultiImportResult;
    await act(async () => {
      result.current.resolvePendingDuplicate('keep-copy');
      out = await batch;
    });

    expect(mockCompleteImport).toHaveBeenCalledWith('tok-0');
    expect(mockDiscardImport).not.toHaveBeenCalled();
    expect(mockSetDocumentLineage).not.toHaveBeenCalled();
    expect(out.imported).toHaveLength(1);
    expect(out.openedExisting).toEqual([]);
  });

  it('imports straight away when no duplicate matches (no pause)', async () => {
    mockImportDroppedMulti.mockResolvedValue({ imported: [makeStaged(0)], skipped: [] });
    mockCheckDuplicates.mockResolvedValueOnce({
      files: [
        {
          file_path: '/tmp/ws/office/word/tok-0/f0.docx',
          content_hash: 'sha256:' + 'b'.repeat(64),
          duplicates: [],
        },
      ],
    });
    mockReadWord.mockResolvedValueOnce({ paragraphs: [] });

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    let out!: OfficeMultiImportResult;
    await act(async () => {
      out = await result.current.readDroppedMulti(['/tmp/src/f0.docx']);
    });

    expect(result.current.pendingDuplicate).toBeNull();
    expect(mockCompleteImport).toHaveBeenCalledWith('tok-0');
    expect(out.imported).toHaveLength(1);
    expect(out.openedExisting).toEqual([]);
  });

  it('chunks the duplicate pre-flight at the backend cap (50 per request)', async () => {
    const staged = Array.from({ length: 51 }, (_, index) => makeStaged(index));
    mockImportDroppedMulti.mockResolvedValue({ imported: staged, skipped: [] });
    mockCheckDuplicates.mockImplementation(async (_ws: string, paths: string[]) => ({
      files: paths.map((path) => ({ file_path: path, content_hash: null, duplicates: [] })),
    }));
    mockReadWord.mockResolvedValue({ paragraphs: [] });

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    let out!: OfficeMultiImportResult;
    await act(async () => {
      out = await result.current.readDroppedMulti(['/tmp/src']);
    });

    expect(mockCheckDuplicates).toHaveBeenCalledTimes(2);
    expect(mockCheckDuplicates.mock.calls[0][1]).toHaveLength(50);
    expect(mockCheckDuplicates.mock.calls[1][1]).toHaveLength(1);
    expect(out.imported).toHaveLength(51);
  });
});
