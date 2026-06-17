import { render, screen } from '@testing-library/react';
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
