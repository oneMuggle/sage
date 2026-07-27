/**
 * fileSearchClient (Task 7, 2026-07-26)
 *
 * Public signature: `search(sessionId, query, options?)` — delegates to
 * `workspaceApi.search(sessionId, query, limit)`. No more raw
 * `workspace_search_files` invoke or `officeApi.listDocuments` fallback;
 * the workspace-aware search is the single source of truth.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockWorkspaceSearch = vi.fn();

vi.mock('../workspaceApi', () => ({
  workspaceApi: {
    search: (...args: unknown[]) => mockWorkspaceSearch(...args),
  },
}));

import { fileSearchClient } from '../fileSearchClient';

const SESSION_ID = 'session-1';

function makeWorkspaceResults(results: unknown[] = [], total?: number) {
  return {
    results: results as never,
    total: typeof total === 'number' ? total : results.length,
  };
}

describe('fileSearchClient.search', () => {
  beforeEach(() => {
    mockWorkspaceSearch.mockReset();
  });

  it('delegates to workspaceApi.search with the given sessionId/query/limit', async () => {
    mockWorkspaceSearch.mockResolvedValue(makeWorkspaceResults());
    await fileSearchClient.search(SESSION_ID, 'foo');
    expect(mockWorkspaceSearch).toHaveBeenCalledWith(SESSION_ID, 'foo', 20);
  });

  it('honours the explicit limit option', async () => {
    mockWorkspaceSearch.mockResolvedValue(makeWorkspaceResults());
    await fileSearchClient.search(SESSION_ID, 'foo', { limit: 5 });
    expect(mockWorkspaceSearch).toHaveBeenCalledWith(SESSION_ID, 'foo', 5);
  });

  it('maps workspace results to FileSearchResult rows', async () => {
    mockWorkspaceSearch.mockResolvedValue({
      results: [
        {
          name: 'proposal.pptx',
          kind: 'office-ppt',
          docType: 'ppt',
          docId: 'doc-1',
          sizeBytes: 1024,
          needsImport: false,
          sourcePath: '/w/office/ppt/1/proposal.pptx',
        },
      ],
      total: 1,
    });

    const out = await fileSearchClient.search(SESSION_ID, 'prop');
    expect(out).toEqual([
      {
        path: '/w/office/ppt/1/proposal.pptx',
        name: 'proposal.pptx',
        size: 1024,
        kind: 'office-ppt',
        docId: 'doc-1',
        docType: 'ppt',
        sourcePath: '/w/office/ppt/1/proposal.pptx',
      },
    ]);
  });

  it('returns an empty array when sessionId is empty (no active session)', async () => {
    const out = await fileSearchClient.search('', 'foo');
    expect(out).toEqual([]);
    expect(mockWorkspaceSearch).not.toHaveBeenCalled();
  });

  it('propagates workspaceApi.search rejections (caller falls back gracefully)', async () => {
    mockWorkspaceSearch.mockRejectedValue(new Error('backend down'));
    await expect(fileSearchClient.search(SESSION_ID, 'foo')).rejects.toThrow('backend down');
  });

  it('throws FileSearchTimeoutError when the search hangs past the timeout', async () => {
    mockWorkspaceSearch.mockImplementation(
      () => new Promise(() => undefined) as ReturnType<typeof mockWorkspaceSearch>,
    );
    const { FileSearchTimeoutError } = await import('../fileSearchClient');
    vi.useFakeTimers();
    try {
      const promise = fileSearchClient.search(SESSION_ID, 'foo');
      const expectation = expect(promise).rejects.toBeInstanceOf(FileSearchTimeoutError);
      await vi.advanceTimersByTimeAsync(3000);
      await expectation;
    } finally {
      vi.useRealTimers();
    }
  });

  it('throws DOMException("aborted") when the signal is already aborted', async () => {
    mockWorkspaceSearch.mockResolvedValue(makeWorkspaceResults());
    const ctrl = new AbortController();
    ctrl.abort();
    await expect(
      fileSearchClient.search(SESSION_ID, 'foo', { signal: ctrl.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('returns empty array when no active session (missing-session contract)', async () => {
    mockWorkspaceSearch.mockResolvedValue(makeWorkspaceResults());
    const out = await fileSearchClient.search('', 'foo');
    expect(out).toEqual([]);
  });

  it('classifies a managed office doc (docId present) as office kind', async () => {
    mockWorkspaceSearch.mockResolvedValue({
      results: [
        {
          name: 'managed.pptx',
          kind: 'office-ppt',
          docType: 'ppt',
          docId: 'doc-m',
          sizeBytes: 1,
          needsImport: false,
          sourcePath: '/w/office/ppt/m/managed.pptx',
        },
      ],
      total: 1,
    });
    const out = await fileSearchClient.search(SESSION_ID, 'man');
    expect(out[0].kind).toBe('office-ppt');
    expect(out[0].docId).toBe('doc-m');
  });

  it('classifies a plain file (kind=file, docId=null) and keeps docId null', async () => {
    mockWorkspaceSearch.mockResolvedValue({
      results: [
        {
          name: 'note.md',
          kind: 'file',
          docType: null,
          docId: null,
          sizeBytes: 12,
          needsImport: false,
          sourcePath: 'note.md',
        },
      ],
      total: 1,
    });
    const out = await fileSearchClient.search(SESSION_ID, 'note');
    expect(out[0].kind).toBe('file');
    expect(out[0].docId).toBeNull();
    expect(out[0].docType).toBeNull();
  });

  it('marks an unmanaged office doc with needsImport for the import flow', async () => {
    mockWorkspaceSearch.mockResolvedValue({
      results: [
        {
          name: 'outside.pptx',
          kind: 'office-ppt',
          docType: 'ppt',
          docId: null,
          sizeBytes: 1,
          needsImport: true,
          sourcePath: '/tmp/outside.pptx',
        },
      ],
      total: 1,
    });
    const out = await fileSearchClient.search(SESSION_ID, 'out');
    expect(out[0].kind).toBe('office-ppt');
    expect(out[0].docId).toBeNull();
    expect(out[0].sourcePath).toBe('/tmp/outside.pptx');
  });
});

describe('fileSearchClient — AtFileSelection helpers', () => {
  beforeEach(() => {
    mockWorkspaceSearch.mockReset();
  });

  it('classifyAtFileSelection returns "file" for plain files', async () => {
    const { classifyAtFileSelection } = await import('../fileSearchClient');
    expect(
      classifyAtFileSelection({
        path: 'a.txt',
        name: 'a.txt',
        kind: 'file',
        docId: null,
        docType: null,
        sourcePath: null,
      }),
    ).toBe('file');
  });

  it('classifyAtFileSelection returns "office" for managed office docs', async () => {
    const { classifyAtFileSelection } = await import('../fileSearchClient');
    expect(
      classifyAtFileSelection({
        path: '/w/m.pptx',
        name: 'm.pptx',
        kind: 'office-ppt',
        docId: 'doc-m',
        docType: 'ppt',
        sourcePath: '/w/m.pptx',
      }),
    ).toBe('office');
  });

  it('classifyAtFileSelection returns "office-import" for unmanaged office docs', async () => {
    const { classifyAtFileSelection } = await import('../fileSearchClient');
    expect(
      classifyAtFileSelection({
        path: '/tmp/o.pptx',
        name: 'o.pptx',
        kind: 'office-ppt',
        docId: null,
        docType: 'ppt',
        sourcePath: '/tmp/o.pptx',
      }),
    ).toBe('office-import');
  });

  it('fileSearchResultToChatOfficeRef returns null for plain files (NEVER fabricates a ref)', async () => {
    const { fileSearchResultToChatOfficeRef } = await import('../fileSearchClient');
    expect(
      fileSearchResultToChatOfficeRef({
        path: 'a.txt',
        name: 'a.txt',
        kind: 'file',
        docId: null,
        docType: null,
        sourcePath: null,
      }),
    ).toBeNull();
  });

  it('fileSearchResultToChatOfficeRef returns the ref for managed office docs', async () => {
    const { fileSearchResultToChatOfficeRef } = await import('../fileSearchClient');
    expect(
      fileSearchResultToChatOfficeRef({
        path: '/w/m.pptx',
        name: 'm.pptx',
        kind: 'office-ppt',
        docId: 'doc-m',
        docType: 'ppt',
        sourcePath: '/w/m.pptx',
      }),
    ).toEqual({ docId: 'doc-m', docType: 'ppt', filename: 'm.pptx' });
  });
});
