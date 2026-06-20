import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

describe('Message', () => {
  it('renders plain text content', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '你好！',
      created_at: 0,
    };
    render(<Message message={msg} />);
    expect(screen.getByText('你好！')).toBeInTheDocument();
  });

  it('renders tool_call indicator', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '观察中...',
      created_at: 0,
      tool_calls: [
        {
          name: 'calculator',
          args: { expression: '1+1' },
          result: '2',
        },
      ],
    };
    const { container } = render(<Message message={msg} />);
    expect(container.textContent).toContain('calculator');
    expect(container.textContent).toContain('2');
  });

  it('applies error style when content starts with [错误', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '[错误:auth_failed] API Key 无效',
      created_at: 0,
    };
    const { container } = render(<Message message={msg} />);
    const errorEl = container.querySelector('[data-error="true"]');
    expect(errorEl).toBeInTheDocument();
  });

  it('message row does not constrain to max-w-[720px] (full-width layout)', () => {
    // Regression for "对话区域没有占满": previously Message.tsx had
    // `max-w-[720px]` on the row, leaving a big empty right side.
    // Width should now come from the MessageList container.
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: 'hi',
      created_at: 0,
    };
    const { container } = render(<Message message={msg} />);
    const row = container.firstChild as HTMLElement;
    expect(row.className).not.toMatch(/max-w-\[720px\]/);
    expect(row.className).toMatch(/\bw-full\b/);
  });

  it('message bubble caps width with max-w-2xl (so text stays readable)', () => {
    // PR-7b: width constraint moved from MessageList wrapper to the bubble
    // itself, so the panel uses full width but text doesn't get too wide.
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: 'hi',
      created_at: 0,
    };
    const { container } = render(<Message message={msg} />);
    // 找 data-error 属性所在的 div(就是气泡)
    const bubble = container.querySelector('div[class*="max-w-2xl"]');
    expect(bubble).toBeTruthy();
  });
});

describe('ThinkingPanel', () => {
  it('renders reasoning_content when present', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '答案是 42',
      created_at: 0,
      reasoning_content: '让我思考一下：6 * 7 = 42',
    };
    const { container } = render(<Message message={msg} />);
    // 应该渲染思考过程按钮
    expect(container.textContent).toContain('思考过程');
    expect(container.textContent).toContain('17'); // 字符数
  });

  it('does not render thinking panel when reasoning_content is absent', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '你好！',
      created_at: 0,
    };
    const { container } = render(<Message message={msg} />);
    // 不应该渲染思考过程按钮
    expect(container.textContent).not.toContain('思考过程');
  });

  it('does not render thinking panel for user messages', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'user',
      content: '你好',
      created_at: 0,
      reasoning_content: '这不是用户的思考过程',
    };
    const { container } = render(<Message message={msg} />);
    // 用户消息不应该渲染思考过程面板
    expect(container.textContent).not.toContain('思考过程');
  });

  it('expands thinking panel on click', () => {
    const msg: MessageType = {
      id: '1',
      session_id: 's',
      role: 'assistant',
      content: '答案',
      created_at: 0,
      reasoning_content: '这是思考内容',
    };
    const { container } = render(<Message message={msg} />);
    // 点击展开
    const button = container.querySelector('button');
    expect(button).toBeInTheDocument();
    // 初始状态：思考内容不可见（折叠）
    expect(container.textContent).not.toContain('这是思考内容');
    // 点击按钮
    fireEvent.click(button!);
    // 展开后：思考内容可见
    expect(container.textContent).toContain('这是思考内容');
  });
});
