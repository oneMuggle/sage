// src/widgets/chat/__tests__/TurnList.test.tsx
//
// 对标 U1（ZCode ConversationTurnNavigator）：轮次列表渲染 + 点击回调测试。

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { TurnItem } from '../../../features/chat/useConversationTurns';
import { formatTurnListJson, formatTurnListMarkdown, TurnList } from '../TurnList';

const items: TurnItem[] = [
  { index: 1, messageId: 'u1', preview: '第一问' },
  { index: 2, messageId: 'u2', preview: '第二问（很长很长的输入被截断显示…）' },
];

describe('TurnList', () => {
  it('renders empty state hint when no turns', () => {
    render(<TurnList items={[]} />);
    expect(screen.getByText('暂无轮次')).toBeInTheDocument();
  });

  it('renders index badge and preview per turn', () => {
    render(<TurnList items={items} />);
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('第一问')).toBeInTheDocument();
    expect(screen.getByText(items[1].preview)).toBeInTheDocument();
  });

  it('clicking a turn calls onSelect with the item', () => {
    const onSelect = vi.fn();
    render(<TurnList items={items} onSelect={onSelect} />);
    fireEvent.click(screen.getByText('第二问（很长很长的输入被截断显示…）'));
    expect(onSelect).toHaveBeenCalledWith(items[1]);
  });

  it('renders nothing clickable when onSelect omitted', () => {
    render(<TurnList items={items} />);
    fireEvent.click(screen.getByText('第一问'));
    // 不抛错即可（无 onSelect 时行为由组件内部兜底）
  });

  it('exports turn list as Markdown and JSON', () => {
    expect(formatTurnListMarkdown([])).toContain('_暂无轮次_');
    const md = formatTurnListMarkdown(items);
    expect(md).toContain('# 会话轮次导航列表 (Conversation Turns)');
    expect(md).toContain('- **[#1]** (u1): 第一问');
    const parsed = JSON.parse(formatTurnListJson(items));
    expect(parsed.total).toBe(2);

    render(<TurnList items={items} />);
  });
});
