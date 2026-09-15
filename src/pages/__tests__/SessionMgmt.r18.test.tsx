/**
 * R18 批次 —— 会话管理交互测试
 *
 * - A: assistant 消息的"重新生成"按钮可见性与回调
 * - B: SessionItem 置顶切换按钮调用链
 * - C: SessionItem Markdown 导出按钮调用链
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../shared/lib/i18n';
import { useStore, type Session } from '../../shared/lib/store';
import { Message } from '../../widgets/chat/Message';
import { SessionItem } from '../../widgets/session/SessionItem';

const setPinnedMock = vi.fn();
const exportMarkdownMock = vi.fn();
const updateSessionMock = vi.fn();

vi.mock('../../shared/api/sessionApi', async () => {
  const actual = await vi.importActual<typeof import('../../shared/api/sessionApi')>(
    '../../shared/api/sessionApi',
  );
  return {
    ...actual,
    sessionApi: {
      ...actual.sessionApi,
      setPinned: (...args: unknown[]) => setPinnedMock(...args),
      exportMarkdown: (...args: unknown[]) => exportMarkdownMock(...args),
    },
  };
});

vi.mock('../../shared/api', async () => {
  const actual = await vi.importActual<typeof import('../../shared/api')>('../../shared/api');
  return {
    ...actual,
    sessionApi: {
      ...actual.sessionApi,
      setPinned: (...args: unknown[]) => setPinnedMock(...args),
      exportMarkdown: (...args: unknown[]) => exportMarkdownMock(...args),
    },
  };
});

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('Message — R18-A 重新生成', () => {
  const assistantMsg = {
    id: 'a1',
    session_id: 's1',
    role: 'assistant' as const,
    content: '第一次回答',
    created_at: 0,
  };

  it('assistant 消息显示重新生成按钮并回调', () => {
    const onRegenerate = vi.fn();
    renderWithI18n(<Message message={assistantMsg} onRegenerate={onRegenerate} />);
    fireEvent.click(screen.getByTestId('regenerate-message'));
    expect(onRegenerate).toHaveBeenCalledWith('a1');
  });

  it('user 消息不显示重新生成按钮', () => {
    renderWithI18n(
      <Message
        message={{ ...assistantMsg, role: 'user', content: '问' }}
        onRegenerate={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('regenerate-message')).not.toBeInTheDocument();
  });

  it('流式中的 assistant 消息不显示重新生成按钮', () => {
    renderWithI18n(<Message message={assistantMsg} isStreaming onRegenerate={vi.fn()} />);
    expect(screen.queryByTestId('regenerate-message')).not.toBeInTheDocument();
  });

  it('未传 onRegenerate 时不显示按钮', () => {
    renderWithI18n(<Message message={assistantMsg} />);
    expect(screen.queryByTestId('regenerate-message')).not.toBeInTheDocument();
  });
});

describe('SessionItem — R18-B/C 置顶与 Markdown 导出', () => {
  const mkSession = (isPinned: boolean): Session => ({
    id: 'sess-1',
    title: '会话甲',
    created_at: 0,
    updated_at: 0,
    last_message_at: 0,
    message_count: 2,
    is_pinned: isPinned,
  });

  beforeEach(() => {
    setPinnedMock.mockReset();
    exportMarkdownMock.mockReset();
    updateSessionMock.mockClear();
    useStore.setState({
      sessions: [],
      currentSessionId: null,
      messages: [],
      isLoading: false,
      updateSession: updateSessionMock,
    });
  });

  const renderItem = (session: Session) =>
    renderWithI18n(
      <SessionItem session={session} isActive={false} onSelect={vi.fn()} onDelete={vi.fn()} />,
    );

  it('未置顶会话点击置顶按钮 → setPinned(sess-1, true) + store 更新', async () => {
    setPinnedMock.mockResolvedValue(mkSession(true));
    renderItem(mkSession(false));
    fireEvent.click(screen.getByTestId('toggle-pin'));
    await waitFor(() => {
      expect(setPinnedMock).toHaveBeenCalledWith('sess-1', true);
      expect(updateSessionMock).toHaveBeenCalledWith('sess-1', { is_pinned: true });
    });
  });

  it('已置顶会话点击按钮 → setPinned(sess-1, false)', async () => {
    setPinnedMock.mockResolvedValue(mkSession(false));
    renderItem(mkSession(true));
    fireEvent.click(screen.getByTestId('toggle-pin'));
    await waitFor(() => expect(setPinnedMock).toHaveBeenCalledWith('sess-1', false));
  });

  it('Markdown 导出按钮存在并触发下载链路', async () => {
    exportMarkdownMock.mockResolvedValue({ html: '# 会话甲', filename: 'sage-session-x.md' });
    renderItem(mkSession(false));
    fireEvent.click(screen.getByTestId('export-session-md'));
    await waitFor(() => expect(exportMarkdownMock).toHaveBeenCalledWith('sess-1'));
  });
});
