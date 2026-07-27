// src/features/chat/__tests__/AtFileMenu.test.tsx
// Task 7 (2026-07-26) — AtFileMenu now consumes sessionId/workspacePath
// from `useWorkspaceContext` and exposes a discriminated-union `onSelect`.
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AtFileMenu } from '../AtFileMenu';

vi.mock('../../../shared/api/fileSearchClient', () => ({
  fileSearchClient: {
    search: vi.fn().mockResolvedValue([]),
  },
  FileSearchTimeoutError: class extends Error {},
  classifyAtFileSelection: (r: { kind: string; docId: string | null }) => {
    if (r.kind === 'file') return 'file';
    return r.docId ? 'office' : 'office-import';
  },
}));

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
  useOptionalWorkspaceContextMock.mockReset();
  useOptionalWorkspaceContextMock.mockReturnValue({
    sessionId: 'session-1',
    binding: { workspacePath: '/w/my-ws' },
  });
});

describe('AtFileMenu kind rendering', () => {
  it('renders office-ppt icon for ppt results', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      {
        path: '/w/proposal.pptx',
        name: 'proposal.pptx',
        size: 100,
        kind: 'office-ppt',
        docId: null,
        docType: 'ppt',
        sourcePath: '/w/proposal.pptx',
      },
    ] as never);
    const onSelect = vi.fn();
    render(<AtFileMenu query="prop" onSelect={onSelect} onClose={vi.fn()} />);
    expect(await screen.findByText('📊')).toBeInTheDocument();
  });

  it('renders office-word icon for docx results', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      {
        path: '/w/notes.docx',
        name: 'notes.docx',
        size: 50,
        kind: 'office-word',
        docId: null,
        docType: 'word',
        sourcePath: '/w/notes.docx',
      },
    ] as never);
    render(<AtFileMenu query="notes" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('📝')).toBeInTheDocument();
  });

  it('renders office-excel icon for xlsx results', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      {
        path: '/w/budget.xlsx',
        name: 'budget.xlsx',
        size: 80,
        kind: 'office-excel',
        docId: null,
        docType: 'excel',
        sourcePath: '/w/budget.xlsx',
      },
    ] as never);
    render(<AtFileMenu query="bud" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('📈')).toBeInTheDocument();
  });

  it('renders file icon (📄) for fs results', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      {
        path: '/w/foo.txt',
        name: 'foo.txt',
        size: 10,
        kind: 'file',
        docId: null,
        docType: null,
        sourcePath: null,
      },
    ] as never);
    render(<AtFileMenu query="foo" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('📄')).toBeInTheDocument();
  });

  it('selecting a managed office item calls onSelect with kind="office"', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      {
        path: '/w/x.pptx',
        name: 'x.pptx',
        size: 100,
        kind: 'office-ppt',
        docId: 'doc-x',
        docType: 'ppt',
        sourcePath: '/w/x.pptx',
      },
    ] as never);
    const onSelect = vi.fn();
    render(<AtFileMenu query="x" onSelect={onSelect} onClose={vi.fn()} />);
    const btn = await screen.findByRole('button');
    fireEvent.click(btn);
    expect(onSelect).toHaveBeenCalledWith({
      kind: 'office',
      ref: { docId: 'doc-x', docType: 'ppt', filename: 'x.pptx' },
    });
  });

  it('mixed kinds render in order with their respective icons', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      {
        path: '/w/a.txt',
        name: 'a.txt',
        kind: 'file',
        docId: null,
        docType: null,
        sourcePath: null,
      },
      {
        path: '/w/b.pptx',
        name: 'b.pptx',
        kind: 'office-ppt',
        docId: null,
        docType: 'ppt',
        sourcePath: '/tmp/b.pptx',
      },
      {
        path: '/w/c.xlsx',
        name: 'c.xlsx',
        kind: 'office-excel',
        docId: 'doc-c',
        docType: 'excel',
        sourcePath: '/w/c.xlsx',
      },
    ] as never);
    render(<AtFileMenu query="" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('📄')).toBeInTheDocument();
    expect(screen.getByText('📊')).toBeInTheDocument();
    expect(screen.getByText('📈')).toBeInTheDocument();
  });
});

describe('AtFileMenu — workspace-context plumbing', () => {
  it('forwards sessionId to fileSearchClient.search', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockReset();
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([]);
    render(<AtFileMenu query="prop" onSelect={vi.fn()} onClose={vi.fn()} />);
    await vi.waitFor(() => {
      expect(fs.fileSearchClient.search).toHaveBeenCalledWith(
        'session-1',
        'prop',
        expect.objectContaining({ signal: expect.anything() }),
      );
    });
  });

  it('does not call fileSearchClient.search when sessionId is null', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockReset();
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([]);
    useOptionalWorkspaceContextMock.mockReturnValue({ sessionId: null, binding: null });
    render(<AtFileMenu query="x" onSelect={vi.fn()} onClose={vi.fn()} />);
    await new Promise((r) => setTimeout(r, 50));
    expect(fs.fileSearchClient.search).not.toHaveBeenCalled();
  });

  it('disables office items when workspace is not bound', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      {
        path: '/tmp/o.pptx',
        name: 'o.pptx',
        kind: 'office-ppt',
        docId: null,
        docType: 'ppt',
        sourcePath: '/tmp/o.pptx',
      },
    ] as never);
    useOptionalWorkspaceContextMock.mockReturnValue({ sessionId: 'session-1', binding: null });
    render(<AtFileMenu query="o" onSelect={vi.fn()} onClose={vi.fn()} />);
    const btn = await screen.findByRole('button');
    expect(btn).toBeDisabled();
  });
});
