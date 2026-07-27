import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { workspaceApi } from '../workspaceApi';

describe('workspaceApi', () => {
  beforeEach(() => {
    mockInvoke.mockReset();
  });

  it('binds a session workspace and maps the binding to camelCase', async () => {
    mockInvoke.mockResolvedValue({
      binding: {
        session_id: 'session-a',
        workspace_path: '/synthetic/work',
        generation: 2,
        activated_at: 100,
        revoked_at: null,
      },
    });

    const result = await workspaceApi.bind('session-a', '/synthetic/work');

    expect(mockInvoke).toHaveBeenCalledWith('workspace_bind', {
      sessionId: 'session-a',
      workspacePath: '/synthetic/work',
    });
    expect(result).toEqual({
      binding: {
        sessionId: 'session-a',
        workspacePath: '/synthetic/work',
        generation: 2,
        activatedAt: 100,
        revokedAt: null,
      },
    });
    expect(result.binding).not.toHaveProperty('session_id');
  });

  it('gets a mapped binding or null', async () => {
    mockInvoke
      .mockResolvedValueOnce({
        binding: {
          session_id: 'session-a',
          workspace_path: '/synthetic/work',
          generation: 3,
          activated_at: 200,
          revoked_at: null,
        },
      })
      .mockResolvedValueOnce({ binding: null });

    await expect(workspaceApi.get('session-a')).resolves.toEqual({
      binding: {
        sessionId: 'session-a',
        workspacePath: '/synthetic/work',
        generation: 3,
        activatedAt: 200,
        revokedAt: null,
      },
    });
    await expect(workspaceApi.get('session-b')).resolves.toEqual({ binding: null });
    expect(mockInvoke).toHaveBeenNthCalledWith(1, 'workspace_get', { sessionId: 'session-a' });
    expect(mockInvoke).toHaveBeenNthCalledWith(2, 'workspace_get', { sessionId: 'session-b' });
  });

  it('revokes a session workspace', async () => {
    mockInvoke.mockResolvedValue({ revoked: true, generation: 4 });

    await expect(workspaceApi.revoke('session-a')).resolves.toEqual({
      revoked: true,
      generation: 4,
    });
    expect(mockInvoke).toHaveBeenCalledWith('workspace_revoke', { sessionId: 'session-a' });
  });

  it('searches with the default limit and maps results to camelCase', async () => {
    mockInvoke.mockResolvedValue({
      results: [
        {
          name: 'deck.pptx',
          kind: 'office-ppt',
          doc_type: 'ppt',
          doc_id: 'doc-1',
          size_bytes: 42,
          needs_import: false,
          source_path: null,
        },
        {
          name: 'draft.docx',
          kind: 'office-word',
          doc_type: 'word',
          doc_id: null,
          size_bytes: 12,
          needs_import: true,
          source_path: 'draft.docx',
        },
      ],
      total: 2,
    });

    const result = await workspaceApi.search('session-a', 'Q&A');

    expect(mockInvoke).toHaveBeenCalledWith('workspace_search_files', {
      sessionId: 'session-a',
      query: 'Q&A',
      limit: 20,
    });
    expect(result).toEqual({
      results: [
        {
          name: 'deck.pptx',
          kind: 'office-ppt',
          docType: 'ppt',
          docId: 'doc-1',
          sizeBytes: 42,
          needsImport: false,
          sourcePath: null,
        },
        {
          name: 'draft.docx',
          kind: 'office-word',
          docType: 'word',
          docId: null,
          sizeBytes: 12,
          needsImport: true,
          sourcePath: 'draft.docx',
        },
      ],
      total: 2,
    });
    expect(result.results[0]).not.toHaveProperty('doc_type');
    expect(result.results[0]).not.toHaveProperty('source_path');
  });
});
