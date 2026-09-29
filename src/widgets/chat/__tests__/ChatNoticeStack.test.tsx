/**
 * UX-IA R1 批次 B：会话级提示按优先级合并。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ChatInlineError } from '../ChatInlineError';
import { CHAT_NOTICE_PRIORITY, ChatNoticeStack } from '../ChatNoticeStack';

const n = (key: string, priority: number) => ({
  key,
  priority,
  node: <div data-testid={`notice-${key}`}>{key}</div>,
});

describe('ChatNoticeStack', () => {
  it('renders nothing when there are no active notices', () => {
    const { container } = render(<ChatNoticeStack notices={[false, null, undefined]} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders a single notice without the toggle', () => {
    render(<ChatNoticeStack notices={[n('interrupted', CHAT_NOTICE_PRIORITY.interrupted)]} />);
    expect(screen.getByTestId('notice-interrupted')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-notice-toggle')).toBeNull();
  });

  it('shows only the highest-priority notice and collapses the rest', () => {
    render(
      <ChatNoticeStack
        notices={[
          n('topic-shift', CHAT_NOTICE_PRIORITY.topicShift),
          false,
          n('error', CHAT_NOTICE_PRIORITY.error),
          n('interrupted', CHAT_NOTICE_PRIORITY.interrupted),
        ]}
      />,
    );
    expect(screen.getByTestId('notice-error')).toBeInTheDocument();
    expect(screen.queryByTestId('notice-interrupted')).toBeNull();
    expect(screen.queryByTestId('notice-topic-shift')).toBeNull();
    const toggle = screen.getByTestId('chat-notice-toggle');
    expect(toggle).toHaveTextContent('另有 2 条提示');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('expands all notices in priority order and collapses again', () => {
    const { container } = render(
      <ChatNoticeStack
        notices={[
          n('topic-shift', CHAT_NOTICE_PRIORITY.topicShift),
          n('interrupted', CHAT_NOTICE_PRIORITY.interrupted),
        ]}
      />,
    );
    fireEvent.click(screen.getByTestId('chat-notice-toggle'));
    const keys = [...container.querySelectorAll('[data-notice-key]')].map((el) =>
      el.getAttribute('data-notice-key'),
    );
    expect(keys).toEqual(['interrupted', 'topic-shift']);
    expect(screen.getByTestId('chat-notice-toggle')).toHaveTextContent('收起其他提示');
    fireEvent.click(screen.getByTestId('chat-notice-toggle'));
    expect(screen.queryByTestId('notice-topic-shift')).toBeNull();
  });
});

describe('ChatInlineError', () => {
  it('renders the message and wires retry / close', () => {
    const onRetry = vi.fn();
    const onClose = vi.fn();
    render(<ChatInlineError error="boom" onRetry={onRetry} onClose={onClose} />);
    expect(screen.getByTestId('chat-inline-error')).toHaveTextContent('boom');
    fireEvent.click(screen.getByTestId('chat-error-retry'));
    fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
