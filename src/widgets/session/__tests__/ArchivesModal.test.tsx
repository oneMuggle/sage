/**
 * R17-A2: 压缩谱系「查看归档」弹窗测试。
 *
 * - 打开时经 sessionApi.getLineage 拉取归档列表并逐条渲染
 * - 点选归档懒加载其消息（sessionApi.getMessages）并渲染 MessageList
 * - 空谱系显示空态；返回按钮回到列表
 *
 * sessionApi 模块级 mock；MessageList 以 testid stub（渲染细节归 MessageList 自己的测试）。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

// jsdom 不实现 ResizeObserver，但 @headlessui Dialog 内部使用它
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

const getLineageMock = vi.fn();
const getMessagesMock = vi.fn();

vi.mock('../../../shared/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../shared/api')>();
  return {
    ...actual,
    sessionApi: {
      ...actual.sessionApi,
      getLineage: (...args: unknown[]) => getLineageMock(...args),
      getMessages: (...args: unknown[]) => getMessagesMock(...args),
    },
  };
});

vi.mock('../../chat/MessageList', () => ({
  MessageList: ({ messages }: { messages: unknown[] }) => (
    <div data-testid="archive-messages">{messages.length} messages</div>
  ),
}));

import { ArchivesModal } from '../ArchivesModal';

const ARCHIVES = [
  {
    archive_session_id: 'arch-1',
    title: '归档 2026-09-01',
    message_count: 12,
    archived_at: 1_756_689_600_000,
    reason: 'compaction_prefix',
  },
];

describe('ArchivesModal (R17-A2)', () => {
  beforeEach(() => {
    getLineageMock.mockReset();
    getMessagesMock.mockReset();
  });

  it('loads lineage on open and renders archive entries', async () => {
    getLineageMock.mockResolvedValue({ session_id: 'sess-1', archives: ARCHIVES });

    render(<ArchivesModal isOpen onClose={() => undefined} sessionId="sess-1" />);

    expect(await screen.findByText('归档 2026-09-01')).toBeInTheDocument();
    expect(getLineageMock).toHaveBeenCalledWith('sess-1');
    expect(screen.getByText(/12 条/)).toBeInTheDocument();
  });

  it('lazily loads messages of the selected archive and renders them', async () => {
    getLineageMock.mockResolvedValue({ session_id: 'sess-1', archives: ARCHIVES });
    getMessagesMock.mockResolvedValue([
      { id: 'm1', session_id: 'arch-1', role: 'user', content: '你好', created_at: 1 },
      { id: 'm2', session_id: 'arch-1', role: 'assistant', content: '你好！', created_at: 2 },
    ]);

    render(<ArchivesModal isOpen onClose={() => undefined} sessionId="sess-1" />);
    fireEvent.click(await screen.findByTestId('archive-entry'));

    expect(await screen.findByTestId('archive-messages')).toHaveTextContent('2 messages');
    expect(getMessagesMock).toHaveBeenCalledWith('arch-1');
  });

  it('shows empty state when session has no archives', async () => {
    getLineageMock.mockResolvedValue({ session_id: 'sess-1', archives: [] });

    render(<ArchivesModal isOpen onClose={() => undefined} sessionId="sess-1" />);

    expect(await screen.findByText('该会话暂无压缩归档')).toBeInTheDocument();
  });

  it('back button returns to the archive list', async () => {
    getLineageMock.mockResolvedValue({ session_id: 'sess-1', archives: ARCHIVES });
    getMessagesMock.mockResolvedValue([]);

    render(<ArchivesModal isOpen onClose={() => undefined} sessionId="sess-1" />);
    fireEvent.click(await screen.findByTestId('archive-entry'));
    await screen.findByTestId('archive-messages');

    fireEvent.click(screen.getByText('← 返回归档列表'));
    await waitFor(() => expect(screen.getByTestId('archive-entry')).toBeInTheDocument());
  });

  it('does not fetch when closed or sessionId is null', () => {
    render(<ArchivesModal isOpen={false} onClose={() => undefined} sessionId="sess-1" />);
    render(<ArchivesModal isOpen onClose={() => undefined} sessionId={null} />);

    expect(getLineageMock).not.toHaveBeenCalled();
  });
});
