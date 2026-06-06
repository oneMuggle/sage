/**
 * MessageList 测试
 * - 空消息列表显示欢迎语
 * - 多条消息按顺序渲染
 * - 透传 knowledgeRefs/attachments 到 Message
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import type { Message as MessageType } from '../../../lib/store';
import { MessageList } from '../MessageList';

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
      <MessageList
        messages={messages}
        knowledgeRefs={{ m1: [{ id: 'k1', title: '知识A' }] }}
      />,
    );
    expect(screen.getByText('知识A')).toBeInTheDocument();
  });
});
