/** 手动归档 / 恢复归档入口测试（侧栏会话条目）。 */
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

describe('SessionItem — manual archive', () => {
  it('renders no archive entry when onArchive is absent', () => {
    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('archive-session')).not.toBeInTheDocument();
  });

  it('calls onArchive and does not select the session', () => {
    const onArchive = vi.fn();
    const onSelect = vi.fn();
    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={onSelect}
        onDelete={vi.fn()}
        onArchive={onArchive}
      />,
    );

    fireEvent.click(screen.getByTestId('archive-session'));

    expect(onArchive).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('disables archive while the session is running', () => {
    renderWithI18n(
      <SessionItem
        session={baseSession({ run_status: 'running' })}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onArchive={vi.fn()}
      />,
    );

    expect(screen.getByTestId('archive-session')).toBeDisabled();
  });

  it('renders restore entry in archived view and hides pin', () => {
    const onUnarchive = vi.fn();
    renderWithI18n(
      <SessionItem
        session={baseSession({ is_archived: true })}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onUnarchive={onUnarchive}
      />,
    );

    fireEvent.click(screen.getByTestId('unarchive-session'));

    expect(onUnarchive).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('toggle-pin')).not.toBeInTheDocument();
  });
});
