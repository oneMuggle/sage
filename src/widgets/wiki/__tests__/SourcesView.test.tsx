import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

import { SourcesView } from '../SourcesView';

const mocks = vi.hoisted(() => ({
  state: { project: { id: 'p', name: 'P', path: '/proj' } },
  list: vi.fn(),
  importSource: vi.fn(),
  deleteSource: vi.fn(),
  readFile: vi.fn(),
  ingestStream: vi.fn(),
  addTask: vi.fn(),
  confirm: vi.fn(),
}));

vi.mock('../../../entities/wiki/store', () => ({
  useWikiStore: (select: (s: typeof mocks.state) => unknown) => select(mocks.state),
}));
vi.mock('../../../entities/wiki/queue-store', () => ({
  useQueueStore: { getState: () => ({ addTask: mocks.addTask }) },
}));
vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: { modelSelections: { chatModel: { modelId: 'model' } }, endpoints: [] },
  }),
}));
vi.mock('../../../entities/setting/types', () => ({
  resolveEndpoint: () => ({ baseUrl: 'https://example.test', apiKey: 'k' }),
}));
vi.mock('../../../features/wiki/useWikiIngest', () => ({
  useWikiIngest: () => ({ progress: null, done: false, error: null, reset: vi.fn() }),
}));
vi.mock('../../../shared/api-client/wiki', () => ({
  wikiListDirectory: mocks.list,
  wikiImportSource: mocks.importSource,
  wikiDeleteSource: mocks.deleteSource,
  wikiReadFile: mocks.readFile,
  wikiIngestStream: mocks.ingestStream,
}));
vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: mocks.confirm,
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.list.mockResolvedValue([
    {
      name: 'sources',
      path: 'raw/sources',
      is_dir: true,
      children: [{ name: 'a.md', path: 'raw/sources/a.md', is_dir: false, children: [] }],
    },
  ]);
  mocks.importSource.mockResolvedValue({ relative_path: 'raw/sources/x.md', name: 'x.md' });
  mocks.deleteSource.mockResolvedValue({
    success: true,
    source_deleted: 'raw/sources/a.md',
    deleted_wiki_pages: [],
    deleted_vectors: 0,
    cleaned_deadlinks: 0,
  });
  mocks.readFile.mockResolvedValue('# hello');
  mocks.ingestStream.mockResolvedValue({ streamId: 's1' });
  mocks.addTask.mockResolvedValue('task-1');
  mocks.confirm.mockResolvedValue(true);
});

it('renders raw/sources entries from the backend', async () => {
  render(<SourcesView />);

  expect(await screen.findByText('a.md')).toBeInTheDocument();
  expect(mocks.list).toHaveBeenCalledWith('raw/sources', '/proj');
});

it('imports a picked file then ingests the returned relative path', async () => {
  window.electronAPI = {
    ...(window.electronAPI ?? {}),
    selectFile: vi.fn().mockResolvedValue('/tmp/x.md'),
  } as never;

  render(<SourcesView />);
  await screen.findByText('a.md');

  fireEvent.click(screen.getByRole('button', { name: /导入文件/ }));

  await waitFor(() => {
    expect(mocks.importSource).toHaveBeenCalledWith('/tmp/x.md', '/proj');
    expect(mocks.ingestStream).toHaveBeenCalledWith(
      expect.objectContaining({ sourceFile: 'raw/sources/x.md' }),
    );
  });
});

it('deletes through the cascade endpoint and refreshes', async () => {
  render(<SourcesView />);
  await screen.findByText('a.md');

  fireEvent.click(screen.getByRole('button', { name: '删除' }));

  await waitFor(() => {
    expect(mocks.deleteSource).toHaveBeenCalledWith('raw/sources/a.md', '/proj');
  });
  expect(mocks.list).toHaveBeenCalledTimes(2);
});

it('enqueues a source file without starting an immediate ingest', async () => {
  render(<SourcesView />);
  await screen.findByText('a.md');

  fireEvent.click(screen.getByRole('button', { name: '加入队列' }));

  await waitFor(() => {
    expect(mocks.addTask).toHaveBeenCalledWith('/proj', 'raw/sources/a.md');
  });
  expect(mocks.ingestStream).not.toHaveBeenCalled();
});
