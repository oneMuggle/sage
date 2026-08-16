/**
 * SessionItem 删除测试 — U12: 两步式确认删除（无 modal）
 *
 * 第一次点击仅 armed（显示"确认删除?"），第二次点击触发 onDelete；
 * 单次点击不删除；删除点击不触发外层行的 onSelect。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Session } from '../../../shared/lib/store';
import { SessionItem } from '../SessionItem';

const baseSession = (overrides: Partial<Session> = {}): Session => ({
  id: 's-1',
  title: '普通会话',
  created_at: 1_750_000_000_000,
  updated_at: 1_750_000_000_000,
  last_message_at: null,
  message_count: 0,
  is_pinned: false,
  ...overrides,
});

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('SessionItem — two-step delete (U12)', () => {
  it('第一次点击仅 armed，不调用 onDelete', () => {
    const onDelete = vi.fn();
    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={onDelete}
      />,
    );

    fireEvent.click(screen.getByTitle('删除'));

    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.getByTestId('delete-session')).toHaveAttribute('data-state', 'armed');
  });

  it('第二次点击触发 onDelete', () => {
    const onDelete = vi.fn();
    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={onDelete}
      />,
    );

    fireEvent.click(screen.getByTitle('删除'));
    fireEvent.click(screen.getByTitle('确认删除?'));

    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it('删除点击不触发外层行的 onSelect（阻止冒泡）', () => {
    const onSelect = vi.fn();
    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={onSelect}
        onDelete={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTitle('删除'));

    expect(onSelect).not.toHaveBeenCalled();
  });
});
