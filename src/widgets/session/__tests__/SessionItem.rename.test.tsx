/**
 * U4' (对标增强第五轮批次 A): 会话 inline 重命名测试
 *
 * 无 onRename 时不渲染入口;点击铅笔进入编辑态,Enter 提交回调,
 * Esc/空标题取消;编辑中不触发 onSelect。
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

describe('SessionItem — inline rename (U4\')', () => {
  it('renders no rename entry when onRename is absent', () => {
    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('rename-session')).not.toBeInTheDocument();
  });

  it('enters edit mode, submits on Enter with trimmed title', () => {
    const onRename = vi.fn().mockResolvedValue(undefined);
    const onSelect = vi.fn();
    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={onSelect}
        onDelete={vi.fn()}
        onRename={onRename}
      />,
    );

    fireEvent.click(screen.getByTestId('rename-session'));
    const input = screen.getByTestId('rename-session-input');
    expect(input).toBeInTheDocument();

    fireEvent.change(input, { target: { value: '  新标题  ' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRename).toHaveBeenCalledWith('s-1', '新标题');
    expect(onSelect).not.toHaveBeenCalled();
    // 提交后回到展示态
    expect(screen.queryByTestId('rename-session-input')).not.toBeInTheDocument();
  });

  it('cancels on Escape without calling onRename', () => {
    const onRename = vi.fn().mockResolvedValue(undefined);
    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onRename={onRename}
      />,
    );

    fireEvent.click(screen.getByTestId('rename-session'));
    const input = screen.getByTestId('rename-session-input');
    fireEvent.change(input, { target: { value: '改动标题' } });
    fireEvent.keyDown(input, { key: 'Escape' });

    expect(onRename).not.toHaveBeenCalled();
    expect(screen.getByText('普通会话')).toBeInTheDocument();
  });

  it('skips submit for blank or unchanged title', () => {
    const onRename = vi.fn().mockResolvedValue(undefined);
    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onRename={onRename}
      />,
    );

    fireEvent.click(screen.getByTestId('rename-session'));
    const input = screen.getByTestId('rename-session-input');
    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onRename).not.toHaveBeenCalled();

    // 不变标题(直接 blur)也不提交
    fireEvent.click(screen.getByTestId('rename-session'));
    fireEvent.blur(screen.getByTestId('rename-session-input'));
    expect(onRename).not.toHaveBeenCalled();
  });
});
