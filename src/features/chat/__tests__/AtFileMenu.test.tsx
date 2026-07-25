// src/features/chat/__tests__/AtFileMenu.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AtFileMenu } from '../AtFileMenu';

vi.mock('../../../shared/api/fileSearchClient', () => ({
  fileSearchClient: {
    search: vi.fn().mockResolvedValue([]),
  },
  FileSearchTimeoutError: class extends Error {},
}));

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}));

describe('AtFileMenu kind rendering', () => {
  it('renders office-ppt icon for ppt results', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      { path: '/w/proposal.pptx', name: 'proposal.pptx', size: 100, kind: 'office-ppt' },
    ] as never);
    const onSelect = vi.fn();
    render(<AtFileMenu query="prop" onSelect={onSelect} onClose={vi.fn()} />);
    expect(await screen.findByText('📊')).toBeInTheDocument();
  });

  it('renders office-word icon for docx results', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      { path: '/w/notes.docx', name: 'notes.docx', size: 50, kind: 'office-word' },
    ] as never);
    render(<AtFileMenu query="notes" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('📝')).toBeInTheDocument();
  });

  it('renders office-excel icon for xlsx results', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      { path: '/w/budget.xlsx', name: 'budget.xlsx', size: 80, kind: 'office-excel' },
    ] as never);
    render(<AtFileMenu query="bud" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('📈')).toBeInTheDocument();
  });

  it('renders file icon (📄) for fs results', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      { path: '/w/foo.txt', name: 'foo.txt', size: 10, kind: 'file' },
    ] as never);
    render(<AtFileMenu query="foo" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('📄')).toBeInTheDocument();
  });

  it('selecting an office item calls onSelect with the path', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      { path: '/w/x.pptx', name: 'x.pptx', size: 100, kind: 'office-ppt' },
    ] as never);
    const onSelect = vi.fn();
    render(<AtFileMenu query="x" onSelect={onSelect} onClose={vi.fn()} />);
    const btn = await screen.findByRole('button');
    fireEvent.click(btn);
    expect(onSelect).toHaveBeenCalledWith('/w/x.pptx');
  });

  it('mixed kinds render in order with their respective icons', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      { path: '/w/a.txt', name: 'a.txt', kind: 'file' },
      { path: '/w/b.pptx', name: 'b.pptx', kind: 'office-ppt' },
      { path: '/w/c.xlsx', name: 'c.xlsx', kind: 'office-excel' },
    ] as never);
    render(<AtFileMenu query="" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('📄')).toBeInTheDocument();
    expect(screen.getByText('📊')).toBeInTheDocument();
    expect(screen.getByText('📈')).toBeInTheDocument();
  });

  // ─── workspacePath plumbing (T6.WS.GAP closure) ────────────────

  it('forwards workspacePath to fileSearchClient.search as 3rd arg', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockReset();
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([]);
    render(
      <AtFileMenu
        query="prop"
        onSelect={vi.fn()}
        onClose={vi.fn()}
        workspacePath="/w/my-workspace"
      />
    );
    await vi.waitFor(() => {
      expect(fs.fileSearchClient.search).toHaveBeenCalledWith(
        'prop',
        expect.objectContaining({ signal: expect.anything() }),
        '/w/my-workspace'
      );
    });
  });

  it('omits workspacePath when not provided (caller did not inject)', async () => {
    const fs = await import('../../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockReset();
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([]);
    render(<AtFileMenu query="x" onSelect={vi.fn()} onClose={vi.fn()} />);
    await vi.waitFor(() => {
      expect(fs.fileSearchClient.search).toHaveBeenCalledWith(
        'x',
        expect.objectContaining({ signal: expect.anything() }),
        undefined
      );
    });
  });
});
