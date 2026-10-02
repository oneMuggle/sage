// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { PendingQueueStrip } from '../PendingQueueStrip';

describe('PendingQueueStrip (P1-6)', () => {
  it('renders nothing when the queue is empty', () => {
    const { container } = render(
      <PendingQueueStrip items={[]} onCancel={vi.fn()} onClearAll={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId('pending-queue-strip')).not.toBeInTheDocument();
  });

  it('shows the queue size and every queued message', () => {
    render(
      <PendingQueueStrip
        items={[
          { id: 'a', content: '第一条排队内容' },
          { id: 'b', content: '第二条排队内容' },
        ]}
        onCancel={vi.fn()}
        onClearAll={vi.fn()}
      />,
    );
    expect(screen.getByTestId('pending-queue-count')).toHaveTextContent('已排队 2 条');
    expect(screen.getAllByTestId('pending-queue-item')).toHaveLength(2);
    expect(screen.getByText('第一条排队内容')).toBeInTheDocument();
    expect(screen.getByText('第二条排队内容')).toBeInTheDocument();
  });

  it('states that queued messages are sent automatically after the current reply', () => {
    // 透明可控：自动连发是本组件存在的理由，必须写在明面上而不是只靠 toast。
    render(
      <PendingQueueStrip items={[{ id: 'a', content: 'x' }]} onCancel={vi.fn()} onClearAll={vi.fn()} />,
    );
    expect(screen.getByTestId('pending-queue-strip')).toHaveTextContent('当前回复结束后自动发送');
  });

  it('cancels the specific message, not a positional slot', () => {
    // 关键回归：撤回必须按稳定 id 命中。队列在自动 flush 与用户撤回之间并发
    // 变化，若按下标撤回会撤掉错误的那一条。
    const onCancel = vi.fn();
    render(
      <PendingQueueStrip
        items={[
          { id: 'a', content: '第一条排队内容' },
          { id: 'b', content: '第二条排队内容' },
        ]}
        onCancel={onCancel}
        onClearAll={vi.fn()}
      />,
    );
    const cancelButtons = screen.getAllByTestId('pending-queue-cancel');
    fireEvent.click(cancelButtons[1]);
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledWith('b');
  });

  it('clears the whole queue on demand', () => {
    const onClearAll = vi.fn();
    render(
      <PendingQueueStrip
        items={[
          { id: 'a', content: 'x' },
          { id: 'b', content: 'y' },
        ]}
        onCancel={vi.fn()}
        onClearAll={onClearAll}
      />,
    );
    fireEvent.click(screen.getByTestId('pending-queue-clear-all'));
    expect(onClearAll).toHaveBeenCalledTimes(1);
  });

  it('exposes the queue as a status region for assistive tech', () => {
    render(
      <PendingQueueStrip items={[{ id: 'a', content: 'x' }]} onCancel={vi.fn()} onClearAll={vi.fn()} />,
    );
    expect(screen.getByRole('status')).toBeInTheDocument();
  });
});
