// U5 (2026-09-18): 待发送队列面板 —— 队列此前只有一枚 toast，用户看不到有几条在等、
// 也无法改顺序或撤掉误发的条目；这里锁住可见性与每条操作的归属。
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { QueuedChatMessage } from '../../../features/send-message/chatStreamStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { PendingQueuePanel } from '../PendingQueuePanel';

function item(id: string, content: string): QueuedChatMessage {
  return { id, sessionId: 's1', content, createdAt: 0 };
}

function setup(overrides: Partial<Parameters<typeof PendingQueuePanel>[0]> = {}) {
  const props = {
    items: [item('q1', '第一条'), item('q2', '第二条')],
    paused: false,
    onSendNow: vi.fn(),
    onEdit: vi.fn(),
    onMoveToFront: vi.fn(),
    onRemove: vi.fn(),
    onClear: vi.fn(),
    onResume: vi.fn(),
    ...overrides,
  };
  render(
    <I18nProvider defaultLocale="zh">
      <PendingQueuePanel {...props} />
    </I18nProvider>,
  );
  return props;
}

describe('PendingQueuePanel', () => {
  it('renders nothing when the queue is empty', () => {
    setup({ items: [] });
    expect(screen.queryByTestId('pending-queue')).toBeNull();
  });

  it('lists queued messages in send order with the count', () => {
    setup();
    const rows = screen.getAllByTestId('pending-queue-item');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('第一条');
    expect(rows[1].textContent).toContain('第二条');
    expect(screen.getByTestId('pending-queue')).toHaveTextContent('待发送 · 2');
  });

  it('routes per-item actions with that item id', () => {
    const props = setup();
    const rows = screen.getAllByTestId('pending-queue-item');
    fireEvent.click(rows[1].querySelector('[data-testid="pending-queue-send-now"]')!);
    fireEvent.click(rows[1].querySelector('[data-testid="pending-queue-remove"]')!);
    fireEvent.click(rows[1].querySelector('[data-testid="pending-queue-edit"]')!);
    fireEvent.click(rows[1].querySelector('[data-testid="pending-queue-top"]')!);

    expect(props.onSendNow).toHaveBeenCalledWith('q2');
    expect(props.onRemove).toHaveBeenCalledWith('q2');
    expect(props.onEdit).toHaveBeenCalledWith('q2');
    expect(props.onMoveToFront).toHaveBeenCalledWith('q2');
    // 队首没有"置顶"可点
    expect(rows[0].querySelector('[data-testid="pending-queue-top"]')).toBeNull();
  });

  it('offers resume only while paused and clear always', () => {
    const paused = setup({ paused: true });
    expect(screen.getByTestId('pending-queue-paused')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('pending-queue-resume'));
    expect(paused.onResume).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId('pending-queue-clear'));
    expect(paused.onClear).toHaveBeenCalledTimes(1);
  });

  it('hides the resume entry when auto-send is still live', () => {
    setup({ paused: false });
    expect(screen.queryByTestId('pending-queue-resume')).toBeNull();
  });
});
