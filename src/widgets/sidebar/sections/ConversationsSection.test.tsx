import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useMessageJumpStore } from '../../../features/chat/messageJumpStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import type { Session } from '../../../shared/lib/store';
import * as confirmService from '../../../shared/ui/ConfirmDialog/confirmService';

import { ConversationsSection } from './ConversationsSection';

const searchMessagesMock = vi.fn();
const archiveStaleMock = vi.fn(async (..._args: unknown[]) => ({ archived: 0 }));
const purgeArchivedMock = vi.fn(async (..._args: unknown[]) => ({ purged: 0 }));
vi.mock('../../../shared/api/sessionApi', () => ({
  sessionApi: {
    searchMessages: (...args: unknown[]) => searchMessagesMock(...args),
    archiveStale: (...args: unknown[]) => archiveStaleMock(...args),
    purgeArchived: (...args: unknown[]) => purgeArchivedMock(...args),
  },
}));

const sessions: Session[] = [
  {
    id: 's1',
    title: 'first',
    created_at: Date.now(),
    updated_at: Date.now(),
    last_message_at: null,
    message_count: 0,
    is_pinned: false,
  },
  {
    id: 's2',
    title: 'second',
    created_at: Date.now(),
    updated_at: Date.now(),
    last_message_at: null,
    message_count: 0,
    is_pinned: false,
  },
];

const renderWithI18n = (ui: React.ReactNode) => render(<I18nProvider>{ui}</I18nProvider>);

const baseProps = {
  sessions,
  currentSessionId: null as string | null,
  collapsed: false,
  onToggleCollapsed: () => {},
  onSelect: () => {},
  onDelete: () => {},
  onNewSession: () => {},
  onRefreshSessions: () => {},
};

describe('ConversationsSection', () => {
  beforeEach(() => {
    searchMessagesMock.mockReset();
    useMessageJumpStore.setState({ pending: null });
  });

  it('renders section label and sessions', () => {
    renderWithI18n(<ConversationsSection {...baseProps} />);
    expect(screen.getByText('会话')).toBeInTheDocument();
    expect(screen.getByText('first')).toBeInTheDocument();
    expect(screen.getByText('second')).toBeInTheDocument();
  });

  it('hides body when collapsed', () => {
    renderWithI18n(<ConversationsSection {...baseProps} collapsed={true} />);
    expect(screen.queryByText('first')).not.toBeInTheDocument();
  });

  it('clicking the trailing "+" button calls onNewSession', () => {
    const onNew = vi.fn();
    renderWithI18n(<ConversationsSection {...baseProps} onNewSession={onNew} />);
    fireEvent.click(screen.getByRole('button', { name: '新对话' }));
    expect(onNew).toHaveBeenCalledTimes(1);
  });

  it('clicking collapse button calls onToggleCollapsed', () => {
    const onToggle = vi.fn();
    renderWithI18n(<ConversationsSection {...baseProps} onToggleCollapsed={onToggle} />);
    fireEvent.click(screen.getByRole('button', { name: '折叠' }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  describe('自动归档 + 清空归档（对标 ZCode taskAutoArchive）', () => {
    beforeEach(() => {
      archiveStaleMock.mockClear();
      purgeArchivedMock.mockClear();
      localStorage.clear();
    });

    it('归档视图提供自动归档天数选择与清空按钮', () => {
      renderWithI18n(<ConversationsSection {...baseProps} />);
      fireEvent.click(screen.getByTestId('toggle-archived'));
      expect(screen.getByTestId('auto-archive-select')).toBeInTheDocument();
      expect(screen.getByTestId('purge-archived')).toBeInTheDocument();
    });

    it('选择天数后写入 localStorage 并触发 archiveStale', async () => {
      renderWithI18n(<ConversationsSection {...baseProps} />);
      fireEvent.click(screen.getByTestId('toggle-archived'));
      fireEvent.change(screen.getByTestId('auto-archive-select'), {
        target: { value: '14' },
      });
      await waitFor(() => expect(archiveStaleMock).toHaveBeenCalledWith(14));
      expect(localStorage.getItem('sage:session-auto-archive-days')).toBe('14');
    });

    it('清空全部归档：确认后调用 purge 并刷新列表', async () => {
      const confirmSpy = vi.spyOn(confirmService, 'confirmDialog').mockResolvedValue(true);
      const refresh = vi.fn();
      const archived: Session[] = sessions.map((s) => ({ ...s, is_archived: true }));
      renderWithI18n(
        <ConversationsSection {...baseProps} sessions={archived} onRefreshSessions={refresh} />,
      );
      fireEvent.click(screen.getByTestId('toggle-archived'));
      fireEvent.click(screen.getByTestId('purge-archived'));
      await waitFor(() => expect(purgeArchivedMock).toHaveBeenCalledTimes(1));
      expect(refresh).toHaveBeenCalled();
      confirmSpy.mockRestore();
    });

    it('清空全部归档：取消确认则不调用 purge', async () => {
      const confirmSpy = vi.spyOn(confirmService, 'confirmDialog').mockResolvedValue(false);
      const refresh = vi.fn();
      const archived: Session[] = sessions.map((s) => ({ ...s, is_archived: true }));
      renderWithI18n(
        <ConversationsSection {...baseProps} sessions={archived} onRefreshSessions={refresh} />,
      );
      fireEvent.click(screen.getByTestId('toggle-archived'));
      fireEvent.click(screen.getByTestId('purge-archived'));
      expect(purgeArchivedMock).not.toHaveBeenCalled();
      confirmSpy.mockRestore();
    });
  });

  it("U4': filters sessions by title (case-insensitive) and shows no-match", () => {
    renderWithI18n(<ConversationsSection {...baseProps} />);
    const search = screen.getByTestId('session-search');

    fireEvent.change(search, { target: { value: 'FIR' } });
    expect(screen.getByText('first')).toBeInTheDocument();
    expect(screen.queryByText('second')).not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: 'zzz' } });
    expect(screen.queryByText('first')).not.toBeInTheDocument();
    expect(screen.getByText('无匹配会话')).toBeInTheDocument();

    // 清空恢复完整列表
    fireEvent.change(search, { target: { value: '' } });
    expect(screen.getByText('first')).toBeInTheDocument();
    expect(screen.getByText('second')).toBeInTheDocument();
  });

  it("U4': passes onRename down to session items", () => {
    const onRename = vi.fn().mockResolvedValue(undefined);
    renderWithI18n(<ConversationsSection {...baseProps} onRename={onRename} />);
    expect(screen.getAllByTestId('rename-session').length).toBe(sessions.length);
  });

  it('F12: 消息命中会话并入列表并显示计数徽标', async () => {
    searchMessagesMock.mockResolvedValue([
      {
        messageId: 'm1',
        sessionId: 's2',
        sessionTitle: 'second',
        role: 'user',
        snippet: '内容命中',
        createdAt: 1,
      },
    ]);
    renderWithI18n(<ConversationsSection {...baseProps} />);

    const search = screen.getByTestId('session-search');
    fireEvent.change(search, { target: { value: '内容' } });

    // 防抖后调用消息搜索
    await waitFor(() => {
      expect(searchMessagesMock).toHaveBeenCalledWith('内容', { limit: 50 });
    });
    // 标题不匹配的 s2 因消息命中而并入展示,徽标显示命中数
    await waitFor(() => {
      expect(screen.getByTestId('session-message-hits')).toBeInTheDocument();
    });
    expect(screen.getByText('second')).toBeInTheDocument();
    // 清空搜索后徽标消失
    fireEvent.change(search, { target: { value: '' } });
    await waitFor(() => {
      expect(screen.queryByTestId('session-message-hits')).not.toBeInTheDocument();
    });
  });

  it('F12: 少于 2 字符不触发消息搜索', async () => {
    renderWithI18n(<ConversationsSection {...baseProps} />);
    fireEvent.change(screen.getByTestId('session-search'), { target: { value: 'a' } });
    await new Promise((r) => setTimeout(r, 400));
    expect(searchMessagesMock).not.toHaveBeenCalled();
  });

  it('A3: 点开消息命中的会话时登记定位到最新命中消息', async () => {
    searchMessagesMock.mockResolvedValue([
      {
        messageId: 'm-new',
        sessionId: 's2',
        sessionTitle: 'second',
        role: 'assistant',
        snippet: '内容',
        createdAt: 2,
      },
      {
        messageId: 'm-old',
        sessionId: 's2',
        sessionTitle: 'second',
        role: 'user',
        snippet: '内容',
        createdAt: 1,
      },
    ]);
    const onSelect = vi.fn();
    renderWithI18n(<ConversationsSection {...baseProps} onSelect={onSelect} />);

    fireEvent.change(screen.getByTestId('session-search'), { target: { value: '内容' } });
    await waitFor(() => {
      expect(screen.getByTestId('session-message-hits')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('second'));
    expect(onSelect).toHaveBeenCalledWith('s2');
    expect(useMessageJumpStore.getState().pending?.messageId).toBe('m-new');
  });

  it('A3: 非搜索态点击会话不登记定位请求', () => {
    const onSelect = vi.fn();
    renderWithI18n(<ConversationsSection {...baseProps} onSelect={onSelect} />);
    fireEvent.click(screen.getByText('first'));
    expect(onSelect).toHaveBeenCalledWith('s1');
    expect(useMessageJumpStore.getState().pending).toBeNull();
  });
});
