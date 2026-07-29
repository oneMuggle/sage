/**
 * M4: 侧栏会话 fork 徽标测试
 *
 * session.fork_root 存在时显示 git-branch 徽标（tooltip 带 fork_root），
 * 普通会话不渲染徽标。
 */
import { render, screen } from '@testing-library/react';
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

describe('SessionItem — fork badge (M4)', () => {
  it('renders fork badge with fork_root tooltip for forked sessions', () => {
    renderWithI18n(
      <SessionItem
        session={baseSession({ id: 'fork-1', title: 'Fork: 普通会话', fork_root: 'origin-9' })}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const badge = screen.getByTestId('fork-badge');
    expect(badge).toHaveAttribute('title', '分叉会话 · fork_root: origin-9');
    expect(badge).toHaveAttribute('aria-label', '分叉会话');
  });

  it('does not render fork badge for non-forked sessions', () => {
    renderWithI18n(
      <SessionItem
        session={baseSession({ fork_root: null })}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('fork-badge')).not.toBeInTheDocument();
  });

  it('does not render fork badge when fork_root field is absent (old backend)', () => {
    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('fork-badge')).not.toBeInTheDocument();
  });
});
