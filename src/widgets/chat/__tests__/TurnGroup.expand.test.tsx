/**
 * TurnGroup 展开/折叠交互测试（Issue 2，2026-10-29）
 *
 * 覆盖两条行为：
 *   1. defaultExpanded 从 false 翻到 true 时自动展开（会话 running → 结束）。
 *   2. 用户手动折叠后不会被 defaultExpanded 强制展开（回归）。
 *
 * 回归背景：最初的实现把 `expanded` 放进了 useEffect 依赖数组，导致
 * 用户点「收起」→ expanded 变 false → effect 立刻命中
 * `defaultExpanded && !expanded` → 又展开，手动折叠永远不生效。
 * 正确做法是用 useRef 追踪 defaultExpanded 的前值，只响应 false → true 翻转。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Message } from '../../../shared/lib/store';

import { TurnGroup } from '../TurnGroup';

// 本用例只关心 TurnGroup 自身的展开/折叠状态机，Message 内部渲染与断言无关
vi.mock('../Message', () => ({
  Message: ({ message }: { message: { id: string; content: string } }) => (
    <div data-testid={`msg-${message.id}`}>{message.content}</div>
  ),
}));

const baseMsg = (id: string, role: Message['role'], content: string): Message => ({
  id,
  session_id: 'sess-1',
  role,
  content,
  created_at: 0,
});

/** 可折叠 turn：assistant/tool 消息 >= 3 条（见 isTurnCollapsible） */
const collapsibleMessages = (): Message[] => [
  baseMsg('u1', 'user', '问题'),
  baseMsg('a1', 'assistant', '回答 1'),
  baseMsg('a2', 'assistant', '回答 2'),
  baseMsg('a3', 'assistant', '回答 3'),
];

describe('TurnGroup — defaultExpanded 同步', () => {
  it('defaultExpanded 从 false 变 true 时自动展开', () => {
    const { rerender } = render(
      <TurnGroup messages={collapsibleMessages()} turnId="turn-1" defaultExpanded={false} />,
    );
    expect(screen.getByRole('button', { name: '展开对话轮次' })).toBeInTheDocument();

    // 会话跑完：defaultExpanded 翻 true → 应自动展开
    rerender(
      <TurnGroup messages={collapsibleMessages()} turnId="turn-1" defaultExpanded={true} />,
    );
    expect(screen.queryByRole('button', { name: '展开对话轮次' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '折叠对话轮次' })).toBeInTheDocument();
  });

  it('defaultExpanded 为 true 时用户手动折叠后不被强制展开（回归）', () => {
    const { rerender } = render(
      <TurnGroup messages={collapsibleMessages()} turnId="turn-1" defaultExpanded={true} />,
    );
    expect(screen.getByRole('button', { name: '折叠对话轮次' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '折叠对话轮次' }));
    expect(screen.getByRole('button', { name: '展开对话轮次' })).toBeInTheDocument();

    // 父组件再次重渲染（新消息到达 → messages 引用变化），defaultExpanded 未翻转，
    // 手动折叠必须保持
    rerender(
      <TurnGroup messages={collapsibleMessages()} turnId="turn-1" defaultExpanded={true} />,
    );
    expect(screen.getByRole('button', { name: '展开对话轮次' })).toBeInTheDocument();
  });

  it('自动展开后用户手动折叠，再次重渲染仍保持折叠（回归）', () => {
    const { rerender } = render(
      <TurnGroup messages={collapsibleMessages()} turnId="turn-1" defaultExpanded={false} />,
    );
    rerender(
      <TurnGroup messages={collapsibleMessages()} turnId="turn-1" defaultExpanded={true} />,
    );
    expect(screen.getByRole('button', { name: '折叠对话轮次' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '折叠对话轮次' }));
    expect(screen.getByRole('button', { name: '展开对话轮次' })).toBeInTheDocument();

    rerender(
      <TurnGroup messages={collapsibleMessages()} turnId="turn-1" defaultExpanded={true} />,
    );
    expect(screen.getByRole('button', { name: '展开对话轮次' })).toBeInTheDocument();
  });

  it('defaultExpanded 保持 false 时用户手动展开不被撤销', () => {
    const { rerender } = render(
      <TurnGroup messages={collapsibleMessages()} turnId="turn-1" defaultExpanded={false} />,
    );
    fireEvent.click(screen.getByRole('button', { name: '展开对话轮次' }));
    expect(screen.getByRole('button', { name: '折叠对话轮次' })).toBeInTheDocument();

    rerender(
      <TurnGroup messages={collapsibleMessages()} turnId="turn-1" defaultExpanded={false} />,
    );
    expect(screen.getByRole('button', { name: '折叠对话轮次' })).toBeInTheDocument();
  });
});
