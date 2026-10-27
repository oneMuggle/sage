// src/widgets/chat/__tests__/Message.blocked.test.tsx
//
// R19-W1: 拦截信封 → 拦截卡片渲染（直播数组路径 + 历史回读字符串路径）。
// 回归重点：session_repo 把 tool_calls 整串原样落库，回读时 metadata 只存在于
// result JSON 内 —— 若不归一化，用户会看到裸 JSON 而非拦截卡片。

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { BlockedAction, Message as MessageType, ToolCall } from '../../../shared/lib/store';
import { Message } from '../Message';

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

const suggestedActions: BlockedAction[] = [
  { action: 'open_browser', label: '用浏览器打开', params: { url: 'https://example.com/x' } },
];

const envelope = JSON.stringify({
  content: '目标站点启用了反爬验证，静态抓取被拦截',
  metadata: {
    blockReason: 'antibot_cf',
    blockedUrl: 'https://example.com/x',
    suggestedActions,
  },
});

const blockedCall: ToolCall = {
  id: 'tc-1',
  name: 'web_fetch',
  args: { url: 'https://example.com/x' },
  result: envelope,
};

function assistantMsg(tool_calls: MessageType['tool_calls']): MessageType {
  return {
    id: 'm1',
    session_id: 's',
    role: 'assistant',
    content: '抓取失败了',
    created_at: 0,
    tool_calls,
  };
}

describe('Message 渲染拦截卡片（R19-W1）', () => {
  it('直播路径（tool_calls 为数组）渲染卡片，并隐藏裸 JSON', () => {
    renderWithI18n(<Message message={assistantMsg([blockedCall])} />);

    expect(screen.getByTestId('blocked-card')).toBeInTheDocument();
    expect(screen.getByText('Cloudflare 反爬验证')).toBeInTheDocument();
    expect(screen.getByText('https://example.com/x')).toBeInTheDocument();
    // 归一化后的可读文案出现在卡片内，原始信封 JSON 不出现在 DOM 中
    expect(screen.getByText('目标站点启用了反爬验证，静态抓取被拦截')).toBeInTheDocument();
    expect(screen.queryByText(/blockReason/)).not.toBeInTheDocument();
  });

  it('历史回读路径（tool_calls 为 JSON 字符串）同样渲染卡片', () => {
    renderWithI18n(<Message message={assistantMsg(JSON.stringify([blockedCall]))} />);

    expect(screen.getByTestId('blocked-card')).toBeInTheDocument();
    expect(screen.getByTestId('blocked-action-open_browser')).toBeInTheDocument();
  });

  it('卡片按钮点击透传 onBlockedAction', () => {
    const onBlockedAction = vi.fn();
    renderWithI18n(
      <Message message={assistantMsg([blockedCall])} onBlockedAction={onBlockedAction} />,
    );

    fireEvent.click(screen.getByTestId('blocked-action-open_browser'));
    expect(onBlockedAction).toHaveBeenCalledWith(suggestedActions[0]);
  });

  it('普通工具结果不渲染卡片，仍显示原始结果', () => {
    const ok: ToolCall = {
      id: 'tc-2',
      name: 'web_fetch',
      args: { url: 'https://example.com/x' },
      result: '抓取成功：正文内容',
    };
    renderWithI18n(<Message message={assistantMsg([ok])} />);

    expect(screen.queryByTestId('blocked-card')).not.toBeInTheDocument();
    expect(screen.getByText(/抓取成功/)).toBeInTheDocument();
  });
});
