/**
 * MessageList 测试
 * - 空消息列表显示欢迎语
 * - 多条消息按顺序渲染
 * - 透传 knowledgeRefs/attachments 到 Message
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import type { Message as MessageType } from '../../../shared/lib/store';
import { MessageList } from '../MessageList';

// Mock BtwOverlay to avoid I18nProvider context issues
vi.mock('../../../features/chat', () => ({
  BtwOverlay: () => null,
}));

const baseMsg = (id: string, role: MessageType['role'], content: string): MessageType => ({
  id,
  session_id: 's',
  role,
  content,
  created_at: 0,
});

describe('MessageList', () => {
  it('shows welcome state when messages array is empty', () => {
    render(<MessageList messages={[]} />);
    expect(screen.getByText('欢迎使用 Sage')).toBeInTheDocument();
    expect(screen.getByText('开始一段新对话吧')).toBeInTheDocument();
  });

  it('renders all messages in order', () => {
    const messages: MessageType[] = [
      baseMsg('1', 'user', '问题'),
      baseMsg('2', 'assistant', '回答'),
    ];
    render(<MessageList messages={messages} />);
    expect(screen.getByText('问题')).toBeInTheDocument();
    expect(screen.getByText('回答')).toBeInTheDocument();
  });

  it('forwards knowledgeRefs to the matching message', () => {
    const messages: MessageType[] = [baseMsg('m1', 'assistant', 'with refs')];
    render(
      <MessageList messages={messages} knowledgeRefs={{ m1: [{ id: 'k1', title: '知识A' }] }} />,
    );
    expect(screen.getByText('知识A')).toBeInTheDocument();
  });

  it('wrapper does not constrain width (full panel width, bubble caps internally)', () => {
    // PR-7b regression: MessageList 不再带 max-w-3xl mx-auto。
    // 之前把整个 wrapper 限到 768px 居中 → 在 1040px 主区域里左右各空 136px。
    // 现在 wrapper 撑满主区域,宽度约束下放到 Message 气泡( max-w-2xl)。
    const messages: MessageType[] = [baseMsg('1', 'user', 'hi')];
    const { container } = render(<MessageList messages={messages} />);
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.className).not.toMatch(/max-w-3xl/);
    expect(wrapper.className).not.toMatch(/mx-auto/);
  });
});
