// 2026-11-07: 插话暂存区面板 — 锁住可见性、count、撤回路由。
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { PendingSteerItem } from '../../../features/send-message/chatStreamStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { PendingSteerPanel } from '../PendingSteerPanel';

function item(id: string, content: string): PendingSteerItem {
  return { id, content, sessionId: 'sess-1', createdAt: 1 };
}

function setup(overrides: Partial<Parameters<typeof PendingSteerPanel>[0]> = {}) {
  const props = {
    items: [item('a', '改用方法 B'), item('b', '再短一点')] as readonly PendingSteerItem[],
    onCancel: vi.fn(),
    ...overrides,
  };
  render(
    <I18nProvider defaultLocale="zh">
      <PendingSteerPanel {...props} />
    </I18nProvider>,
  );
  return props;
}

describe('PendingSteerPanel', () => {
  it('renders nothing when the staging area is empty', () => {
    setup({ items: [] });
    expect(screen.queryByTestId('pending-steer')).toBeNull();
  });

  it('lists items with a count and routes cancel by id', () => {
    const props = setup();
    const rows = screen.getAllByTestId('pending-steer-item');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('改用方法 B');
    expect(rows[1].textContent).toContain('再短一点');
    expect(screen.getByTestId('pending-steer')).toHaveTextContent('待生效 · 2');

    fireEvent.click(rows[1].querySelector('[data-testid="pending-steer-cancel"]')!);
    expect(props.onCancel).toHaveBeenCalledWith('b');
  });

  it('surfaces the hint line explaining when steers take effect', () => {
    setup();
    expect(screen.getByTestId('pending-steer-hint')).toHaveTextContent('AI 在下一个边界读取');
  });
});
