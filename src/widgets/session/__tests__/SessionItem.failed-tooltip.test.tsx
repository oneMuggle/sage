/**
 * 侧栏会话失败徽标的 tooltip 渲染（2026-10-22）
 *
 * sessions.last_error 现在会带上限装饰（"max_iterations_exceeded (limit=25)"），
 * tooltip 必须渲染成可读中文并显示具体上限值，让用户知道该调到多少。
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
  run_status: 'failed',
  ...overrides,
});

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

const renderFailed = (lastError: string | null) =>
  renderWithI18n(
    <SessionItem
      session={baseSession({ last_error: lastError })}
      isActive={false}
      onSelect={vi.fn()}
      onDelete={vi.fn()}
    />,
  );

describe('SessionItem — failed tooltip renders limit detail', () => {
  it('renders the iteration ceiling value in Chinese text', () => {
    renderFailed('max_iterations_exceeded (limit=25)');

    const badge = screen.getByTestId('session-failed');
    const title = badge.getAttribute('title') ?? '';
    expect(title).toContain('25');
    expect(title).toContain('上限');
    // 裸错误码不应直接暴露给用户
    expect(title).not.toContain('max_iterations_exceeded');
  });

  it('renders the tool budget ceiling value', () => {
    renderFailed('tool_budget_exceeded (limit=100)');

    const title = screen.getByTestId('session-failed').getAttribute('title') ?? '';
    expect(title).toContain('100');
    expect(title).not.toContain('tool_budget_exceeded');
  });

  it('falls back to the raw text for unknown error codes', () => {
    renderFailed('some_unknown_failure');

    const title = screen.getByTestId('session-failed').getAttribute('title') ?? '';
    expect(title).toContain('some_unknown_failure');
  });

  it('falls back to the bare status label when last_error is null', () => {
    renderFailed(null);

    const badge = screen.getByTestId('session-failed');
    expect(badge.getAttribute('title')).toBe('运行失败');
  });
});
