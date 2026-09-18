import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

import { WikiChat } from '../WikiChat';

const mocks = vi.hoisted(() => ({
  state: { project: { id: 'a', name: 'A', path: '/a' }, openFile: vi.fn(), setActiveView: vi.fn() },
  list: vi.fn(),
  send: vi.fn(),
  locate: vi.fn(),
  stream: {
    answer: '',
    citations: [],
    sources: [],
    streaming: false,
    completed: false,
    error: null,
  },
}));
vi.mock('../../../entities/wiki/store', () => ({
  useWikiStore: (select: (s: typeof mocks.state) => unknown) => select(mocks.state),
}));
vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: { modelSelections: { chatModel: { modelId: 'model' } }, endpoints: [] },
  }),
}));
vi.mock('../../../entities/setting/types', () => ({
  resolveEndpoint: () => ({ baseUrl: 'https://example.test', apiKey: '' }),
}));
vi.mock('../../../features/wiki/useWikiChatStream', () => ({
  useWikiChatStream: (id: string | null, request: unknown) => {
    if (id) mocks.send(request);
    return mocks.stream;
  },
}));
vi.mock('../../../shared/api-client/wiki', () => ({
  wikiListDirectory: mocks.list,
  wikiChatStream: mocks.send,
  locateWikiCitation: mocks.locate,
}));
beforeEach(() => {
  vi.clearAllMocks();
  mocks.state.project = { id: 'a', name: 'A', path: '/a' };
  mocks.list.mockResolvedValue([
    {
      name: 'wiki',
      path: 'wiki',
      is_dir: true,
      children: [{ name: 'a.md', path: 'wiki/a.md', is_dir: false }],
    },
  ]);
  mocks.send.mockResolvedValue({ streamId: 's1' });
  Object.assign(mocks.stream, {
    answer: '',
    citations: [],
    sources: [],
    streaming: false,
    completed: false,
    error: null,
  });
});
it('caps default and select-all sources at 500 without broadening the request', async () => {
  mocks.list.mockResolvedValue(
    Array.from({ length: 501 }, (_, index) => ({
      name: `${index}.md`,
      path: `wiki/${index}.md`,
      is_dir: false,
    })),
  );
  render(<WikiChat />);
  await screen.findByRole('checkbox', { name: 'wiki/0.md' });
  expect(
    screen.getAllByRole('checkbox').filter((node) => (node as HTMLInputElement).checked),
  ).toHaveLength(500);
  expect(screen.getByText(/最多选择 500/)).toBeInTheDocument();
  fireEvent.click(screen.getByText('清空选择'));
  fireEvent.click(screen.getByText('全选'));
  expect(
    screen.getAllByRole('checkbox').filter((node) => (node as HTMLInputElement).checked),
  ).toHaveLength(500);
});

it('requires a selected source and sends only selected paths', async () => {
  render(<WikiChat />);
  const source = await screen.findByRole('checkbox', { name: 'wiki/a.md' });
  fireEvent.change(screen.getByPlaceholderText('输入你的问题...'), {
    target: { value: 'question' },
  });
  fireEvent.click(source);
  expect(screen.getByRole('button', { name: '发送问题' })).toBeDisabled();
  fireEvent.click(source);
  fireEvent.click(screen.getByRole('button', { name: '发送问题' }));
  await waitFor(() =>
    expect(mocks.send).toHaveBeenCalledWith(
      expect.objectContaining({ selectedPaths: ['wiki/a.md'] }),
    ),
  );
});
it('keeps completed answers when starting another question and clears on project switch', async () => {
  const view = render(<WikiChat />);
  await screen.findByRole('checkbox', { name: 'wiki/a.md' });
  fireEvent.change(screen.getByPlaceholderText('输入你的问题...'), { target: { value: 'first' } });
  fireEvent.click(screen.getByRole('button', { name: '发送问题' }));
  await waitFor(() => expect(mocks.send).toHaveBeenCalled());
  act(() => {
    Object.assign(mocks.stream, { answer: 'first answer', completed: true });
    view.rerender(<WikiChat />);
  });
  expect(await screen.findByText('first answer')).toBeInTheDocument();
  act(() => {
    Object.assign(mocks.stream, { answer: '', completed: false });
  });
  fireEvent.change(screen.getByPlaceholderText('输入你的问题...'), { target: { value: 'second' } });
  fireEvent.click(screen.getByRole('button', { name: '发送问题' }));
  expect(screen.getByText('first answer')).toBeInTheDocument();
  act(() => {
    mocks.state.project = { id: 'b', name: 'B', path: '/b' };
    view.rerender(<WikiChat />);
  });
  expect(screen.queryByText('first answer')).not.toBeInTheDocument();
  await screen.findByRole('checkbox', { name: 'wiki/a.md' });
});
it('shows a changed citation without highlighting stale coordinates', async () => {
  const citation = {
    id: 'S1',
    path: 'wiki/a.md',
    title: 'Evidence A',
    excerpt: 'old evidence',
    content_hash: 'hash',
    line_start: 1,
    line_end: 2,
  };
  mocks.locate.mockResolvedValue({ ...citation, changed: true, excerpt: 'new content' });
  const view = render(<WikiChat />);
  await screen.findByRole('checkbox', { name: 'wiki/a.md' });
  fireEvent.change(screen.getByPlaceholderText('输入你的问题...'), {
    target: { value: 'question' },
  });
  fireEvent.click(screen.getByRole('button', { name: '发送问题' }));
  await waitFor(() => expect(mocks.send).toHaveBeenCalled());
  act(() => {
    Object.assign(mocks.stream, {
      answer: 'answer [S1]',
      citations: [citation],
      sources: [citation],
      completed: true,
    });
    view.rerender(<WikiChat />);
  });
  fireEvent.click(await screen.findByRole('button', { name: /Evidence A/ }));
  expect(await screen.findByText(/来源已变化/)).toBeInTheDocument();
  expect(screen.queryByLabelText('定位原文')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '打开原文件' }));
  expect(mocks.state.openFile).toHaveBeenCalledWith('wiki/a.md');
});

it('shows request failures and allows retry', async () => {
  Object.assign(mocks.stream, { completed: true, error: '查询失败：offline' });
  render(<WikiChat />);
  await screen.findByRole('checkbox', { name: 'wiki/a.md' });
  fireEvent.change(screen.getByPlaceholderText('输入你的问题...'), {
    target: { value: 'question' },
  });
  fireEvent.click(screen.getByRole('button', { name: '发送问题' }));
  expect(await screen.findByText(/查询失败/)).toBeInTheDocument();
  fireEvent.change(screen.getByPlaceholderText('输入你的问题...'), { target: { value: 'retry' } });
  expect(screen.getByRole('button', { name: '发送问题' })).toBeEnabled();
});

it('shows source loading failures and does not allow sending', async () => {
  mocks.list.mockRejectedValue(new Error('offline'));
  render(<WikiChat />);
  expect(await screen.findByText(/来源加载失败/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '发送问题' })).toBeDisabled();
});
