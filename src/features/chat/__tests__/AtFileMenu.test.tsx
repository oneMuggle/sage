// src/features/chat/__tests__/AtFileMenu.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AtFileMenu } from '../AtFileMenu';

// Mock i18n hook
vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'chat.atFile.searching': '搜索中...',
        'chat.atFile.empty': '未找到文件',
        'chat.atFile.timeout': '搜索超时',
        'chat.atFile.error': '搜索失败',
        'chat.atFile.retry': '重试',
      };
      return translations[key] || key;
    },
  }),
}));

const searchMock = vi.fn();
vi.mock('../../../shared/api/fileSearchClient', () => ({
  fileSearchClient: { search: (...args: unknown[]) => searchMock(...args) },
  FileSearchTimeoutError: class FileSearchTimeoutError extends Error {},
}));

describe('AtFileMenu', () => {
  beforeEach(() => {
    searchMock.mockReset();
  });

  it('renders null when query is null', () => {
    const { container } = render(
      <AtFileMenu query={null} onSelect={vi.fn()} onClose={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders loading state initially', () => {
    searchMock.mockImplementation(
      () => new Promise(() => {}) // Never resolves
    );
    render(<AtFileMenu query="foo" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText(/搜索中/)).toBeInTheDocument();
  });

  it('renders empty state when search returns []', async () => {
    searchMock.mockResolvedValueOnce([]);
    render(<AtFileMenu query="nomatch" onSelect={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText(/未找到文件/)).toBeInTheDocument();
    });
  });

  it('renders search results', async () => {
    const results = [
      { path: 'src/foo.ts', name: 'foo.ts' },
      { path: 'src/bar.ts', name: 'bar.ts' },
    ];
    searchMock.mockResolvedValueOnce(results);
    render(<AtFileMenu query="test" onSelect={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText('foo.ts')).toBeInTheDocument();
      expect(screen.getByText('bar.ts')).toBeInTheDocument();
    });
  });

  it('calls onSelect when clicking a result', async () => {
    const onSelect = vi.fn();
    const results = [{ path: 'src/selected.ts', name: 'selected.ts' }];
    searchMock.mockResolvedValueOnce(results);
    render(<AtFileMenu query="select" onSelect={onSelect} onClose={vi.fn()} />);
    await waitFor(() => screen.getByText('selected.ts'));
    fireEvent.click(screen.getByText('selected.ts'));
    expect(onSelect).toHaveBeenCalledWith('src/selected.ts');
  });

  it('shows retry button on timeout error', async () => {
    const { FileSearchTimeoutError } = await import(
      '../../../shared/api/fileSearchClient'
    );
    searchMock.mockRejectedValueOnce(new FileSearchTimeoutError('slow'));
    render(<AtFileMenu query="slow" onSelect={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText(/重试/)).toBeInTheDocument();
    });
  });

  it('calls search with current query', async () => {
    searchMock.mockResolvedValueOnce([]);
    render(<AtFileMenu query="abc" onSelect={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => {
      expect(searchMock).toHaveBeenCalledWith('abc', expect.objectContaining({}));
    });
  });
});
