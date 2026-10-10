// @vitest-environment jsdom
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';
import { useTerminalPanelStore } from '../../../features/terminal-panel/terminalPanelStore';
import { ChatHeaderBar } from '../../../pages/chat/ChatHeaderBar';
import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { PageHeader } from '../../../shared/ui';
import { Message } from '../Message';
import { SubagentLivePanel } from '../SubagentLivePanel';

const renderWithI18n = (ui: React.ReactElement) =>
  render(
    <MemoryRouter>
      <I18nProvider defaultLocale="zh">{ui}</I18nProvider>
    </MemoryRouter>,
  );

describe('UI-R2-P0 Chat Header, Activity Panels & Message Reading Polish', () => {
  it('auto-collapses >= 3 completed tool calls into a group summary and expands on click', () => {
    const msg: MessageType = {
      id: 'm-tools-3',
      session_id: 's1',
      role: 'assistant',
      content: '已完成多步检索。',
      created_at: 0,
      tool_calls: [
        { name: 'read_file', args: { path: 'a.ts' }, result: 'alpha' },
        { name: 'read_file', args: { path: 'b.ts' }, result: 'beta' },
        { name: 'web_search', args: { query: 'gamma' }, result: 'delta' },
      ],
    };

    renderWithI18n(<Message message={msg} />);

    const toggle = screen.getByTestId('tool-calls-group-toggle');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveTextContent('已执行 3 步工具调用');
    expect(toggle).toHaveTextContent('read_file×2 · web_search');
    expect(screen.queryByText('a.ts')).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('a.ts')).toBeInTheDocument();
    expect(screen.getByText('b.ts')).toBeInTheDocument();
  });

  it('renders markdown table with copy-as-TSV button', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    const msg: MessageType = {
      id: 'm-table',
      session_id: 's1',
      role: 'assistant',
      content: '| 模块 | 状态 |\n| --- | --- |\n| 顶栏 | 已完成 |\n| 底栏 | 已完成 |',
      created_at: 0,
    };

    renderWithI18n(<Message message={msg} />);

    const copyBtn = screen.getByTestId('markdown-table-copy');
    expect(copyBtn).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(copyBtn);
    });
    expect(writeText).toHaveBeenCalledWith('模块\t状态\n顶栏\t已完成\n底栏\t已完成');
  });

  it('sets data-compact on ChatHeaderBar when rightPanelOpen is true while preserving new-session aria-label', () => {
    const noop = vi.fn();
    const baseProps = {
      workspacePath: null,
      currentSessionId: 's1',
      orchMode: 'direct',
      setOrchMode: noop,
      isLoading: false,
      hasConfig: true,
      onNewTopic: noop,
      isTempChat: false,
      setTempChatSessions: noop,
      onNewSession: noop,
      onToggleRightPanel: noop,
      unseenArtifactCount: 0,
    };
    const { rerender } = renderWithI18n(
      <ChatHeaderBar {...baseProps} rightPanelOpen={false} />,
    );

    expect(screen.getByTestId('chat-header-bar')).toHaveAttribute('data-compact', 'false');
    expect(screen.getByRole('button', { name: /新对话/ })).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <I18nProvider defaultLocale="zh">
          <ChatHeaderBar {...baseProps} rightPanelOpen={true} />
        </I18nProvider>
      </MemoryRouter>,
    );

    expect(screen.getByTestId('chat-header-bar')).toHaveAttribute('data-compact', 'true');
    expect(screen.getByRole('button', { name: /新对话/ })).toBeInTheDocument();
  });

  it('supports manual and terminal-open auto-collapse on SubagentLivePanel', () => {
    useTerminalPanelStore.setState({ open: false });
    const store = useChatStreamStore.getState();
    store.startStream('s1', 'm1');
    store.setStreamingMeta('s1', 'm1', {
      state: 'acting',
      currentAgentId: null,
      iteration: 1,
    });
    store.setTaskBoard('s1', {
      runId: 'r1',
      plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'Search docs', depends_on: [] }],
      statuses: { t1: { status: 'running' } as never },
      live: { t1: { liveStep: '正在分析接口契约', updatedAt: 1000 } as never },
      dispatchedAt: 1000,
    });

    renderWithI18n(<SubagentLivePanel sessionId="s1" />);
    const toggle = screen.getByTestId('subagent-live-toggle');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('正在分析接口契约')).toBeInTheDocument();

    act(() => {
      useTerminalPanelStore.setState({ open: true });
    });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('正在分析接口契约')).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('正在分析接口契约')).toBeInTheDocument();
  });

  it('renders unified PageHeader with h-12 shell, title, subtitle, and actions', () => {
    render(
      <PageHeader
        title="技能"
        subtitle="管理内置与外部技能"
        actions={<button type="button">刷新</button>}
      />,
    );
    const header = screen.getByTestId('page-header');
    expect(header.className).toContain('h-12');
    expect(screen.getByText('技能')).toBeInTheDocument();
    expect(screen.getByText('管理内置与外部技能')).toBeInTheDocument();
    expect(screen.getByText('刷新')).toBeInTheDocument();
  });
});
