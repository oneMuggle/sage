/**
 * AtFileMenu ref-selection — Task 7 (2026-07-26)
 *
 * Validates the discriminated-union `onSelect` payload:
 *   - plain file → `{ kind: 'file', path, name }`
 *   - managed office (docId present) → `{ kind: 'office', ref: ChatOfficeRef }`
 *   - unmanaged office (no docId) → `{ kind: 'office-import', result }`
 *
 * Hard invariant: AtFileMenu MUST NEVER fabricate a `ChatOfficeRef` for a
 * plain file. The 'office' branch is gated on a real docId from the
 * workspace search response.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fileSearchClient } from '../../../shared/api/fileSearchClient';
import { AtFileMenu } from '../AtFileMenu';

vi.mock('../../../shared/api/fileSearchClient', async () => {
  const actual = await vi.importActual<typeof import('../../../shared/api/fileSearchClient')>(
    '../../../shared/api/fileSearchClient',
  );
  return {
    fileSearchClient: {
      search: vi.fn().mockResolvedValue([]),
    },
    FileSearchTimeoutError: class extends Error {},
    classifyAtFileSelection: actual.classifyAtFileSelection,
    fileSearchResultToChatOfficeRef: actual.fileSearchResultToChatOfficeRef,
  };
});

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}));

const useOptionalWorkspaceContextMock = vi.fn();
vi.mock('../../../shared/lib/workspaceContext', async () => {
  const actual = await vi.importActual<typeof import('../../../shared/lib/workspaceContext')>(
    '../../../shared/lib/workspaceContext',
  );
  return {
    ...actual,
    useOptionalWorkspaceContext: () => useOptionalWorkspaceContextMock(),
  };
});

beforeEach(() => {
  vi.mocked(fileSearchClient.search).mockReset();
  useOptionalWorkspaceContextMock.mockReset();
  useOptionalWorkspaceContextMock.mockReturnValue({
    sessionId: 'session-1',
    binding: { workspacePath: '/w/my-ws' },
  });
});

describe('AtFileMenu — onSelect discriminated union', () => {
  it('plain file selection yields kind="file" with the path', async () => {
    vi.mocked(fileSearchClient.search).mockResolvedValue([
      {
        path: '/w/foo.txt',
        name: 'foo.txt',
        kind: 'file',
        docId: null,
        docType: null,
        sourcePath: null,
      },
    ] as never);
    const onSelect = vi.fn();
    render(<AtFileMenu query="foo" onSelect={onSelect} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button'));
    expect(onSelect).toHaveBeenCalledWith({
      kind: 'file',
      path: '/w/foo.txt',
      name: 'foo.txt',
    });
  });

  it('plain file selection NEVER fabricates a ChatOfficeRef', async () => {
    vi.mocked(fileSearchClient.search).mockResolvedValue([
      {
        path: '/w/foo.txt',
        name: 'foo.txt',
        kind: 'file',
        docId: null,
        docType: null,
        sourcePath: null,
      },
    ] as never);
    const onSelect = vi.fn();
    render(<AtFileMenu query="foo" onSelect={onSelect} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button'));
    const arg = onSelect.mock.calls[0][0];
    expect(arg).not.toHaveProperty('ref');
    expect(arg.kind).toBe('file');
  });

  it('managed office selection yields kind="office" with a real ChatOfficeRef', async () => {
    vi.mocked(fileSearchClient.search).mockResolvedValue([
      {
        path: '/w/managed.pptx',
        name: 'managed.pptx',
        kind: 'office-ppt',
        docId: 'doc-m',
        docType: 'ppt',
        sourcePath: '/w/managed.pptx',
      },
    ] as never);
    const onSelect = vi.fn();
    render(<AtFileMenu query="man" onSelect={onSelect} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button'));
    expect(onSelect).toHaveBeenCalledWith({
      kind: 'office',
      ref: { docId: 'doc-m', docType: 'ppt', filename: 'managed.pptx' },
    });
    // No path on the ref branch
    expect(onSelect.mock.calls[0][0]).not.toHaveProperty('path');
  });

  it('unmanaged office selection yields kind="office-import" with the result', async () => {
    vi.mocked(fileSearchClient.search).mockResolvedValue([
      {
        path: '/tmp/unmanaged.pptx',
        name: 'unmanaged.pptx',
        kind: 'office-ppt',
        docId: null,
        docType: 'ppt',
        sourcePath: '/tmp/unmanaged.pptx',
      },
    ] as never);
    const onSelect = vi.fn();
    render(<AtFileMenu query="unman" onSelect={onSelect} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button'));
    expect(onSelect).toHaveBeenCalledTimes(1);
    const arg = onSelect.mock.calls[0][0];
    expect(arg.kind).toBe('office-import');
    expect(arg.result).toMatchObject({
      path: '/tmp/unmanaged.pptx',
      name: 'unmanaged.pptx',
      docId: null,
      sourcePath: '/tmp/unmanaged.pptx',
    });
  });

  it('managed office (real docId present) yields kind="office" even if sourcePath points elsewhere', async () => {
    // Workspace search should only return managed docs with a docId;
    // the backend classifies them as "office" not "office-import". The
    // presence of a real docId wins — the renderer trusts the backend's
    // authoritative answer.
    vi.mocked(fileSearchClient.search).mockResolvedValue([
      {
        path: '/w/managed-import.pptx',
        name: 'managed-import.pptx',
        kind: 'office-ppt',
        docId: 'doc-mni',
        docType: 'ppt',
        sourcePath: '/tmp/managed-import.pptx',
      },
    ] as never);
    const onSelect = vi.fn();
    render(<AtFileMenu query="mni" onSelect={onSelect} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button'));
    expect(onSelect.mock.calls[0][0]).toEqual({
      kind: 'office',
      ref: { docId: 'doc-mni', docType: 'ppt', filename: 'managed-import.pptx' },
    });
  });

  it('mixed selection: each item produces the correct kind', async () => {
    vi.mocked(fileSearchClient.search).mockResolvedValue([
      {
        path: '/w/a.txt',
        name: 'a.txt',
        kind: 'file',
        docId: null,
        docType: null,
        sourcePath: null,
      },
      {
        path: '/w/b-managed.pptx',
        name: 'b-managed.pptx',
        kind: 'office-ppt',
        docId: 'doc-b',
        docType: 'ppt',
        sourcePath: '/w/b-managed.pptx',
      },
      {
        path: '/tmp/c-unmanaged.pptx',
        name: 'c-unmanaged.pptx',
        kind: 'office-ppt',
        docId: null,
        docType: 'ppt',
        sourcePath: '/tmp/c-unmanaged.pptx',
      },
    ] as never);
    const onSelect = vi.fn();
    render(<AtFileMenu query="" onSelect={onSelect} onClose={vi.fn()} />);
    const buttons = await screen.findAllByRole('button');
    fireEvent.click(buttons[0]);
    fireEvent.click(buttons[1]);
    fireEvent.click(buttons[2]);
    expect(onSelect.mock.calls[0][0].kind).toBe('file');
    expect(onSelect.mock.calls[1][0].kind).toBe('office');
    expect(onSelect.mock.calls[2][0].kind).toBe('office-import');
  });
});

describe('AtFileMenu — workspace-context gating', () => {
  it('does not search when sessionId is missing', async () => {
    useOptionalWorkspaceContextMock.mockReturnValue({ sessionId: null, binding: null });
    render(<AtFileMenu query="foo" onSelect={vi.fn()} onClose={vi.fn()} />);
    await new Promise((r) => setTimeout(r, 30));
    expect(fileSearchClient.search).not.toHaveBeenCalled();
  });

  it('disables office items when workspace is not bound (file remains enabled)', async () => {
    useOptionalWorkspaceContextMock.mockReturnValue({ sessionId: 'session-1', binding: null });
    vi.mocked(fileSearchClient.search).mockResolvedValue([
      {
        path: '/w/foo.txt',
        name: 'foo.txt',
        kind: 'file',
        docId: null,
        docType: null,
        sourcePath: null,
      },
      {
        path: '/tmp/o.pptx',
        name: 'o.pptx',
        kind: 'office-ppt',
        docId: null,
        docType: 'ppt',
        sourcePath: '/tmp/o.pptx',
      },
    ] as never);
    render(<AtFileMenu query="foo" onSelect={vi.fn()} onClose={vi.fn()} />);
    const buttons = await screen.findAllByRole('button');
    // First button is the file — enabled.
    expect(buttons[0]).not.toBeDisabled();
    // Second button is the unmanaged office — disabled (no workspace).
    expect(buttons[1]).toBeDisabled();
  });
});
