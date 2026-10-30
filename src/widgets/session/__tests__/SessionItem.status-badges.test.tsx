/** 会话状态徽章：重试中 / 后台运行中（2026-10-30）。 */
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';
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

describe('SessionItem — 状态徽章', () => {
  beforeEach(() => {
    useChatStreamStore.setState({ sessions: {} } as never);
  });

  afterEach(() => {
    cleanup();
    useChatStreamStore.setState({ sessions: {} } as never);
  });

  it('shows the retrying badge when the live slot carries retryInfo', () => {
    act(() => {
      const store = useChatStreamStore.getState();
      store.startStream('s-1', 'm-1');
      store.setRetryInfo('s-1', 'm-1', {
        attempt: 2,
        max_attempts: 3,
        error_type: 'timeout',
        error_message: 'LLM 代理超时',
        delay: 4,
      });
    });

    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const badge = screen.getByTestId('session-retrying');
    expect(badge).toBeInTheDocument();
    expect(badge.getAttribute('title')).toContain('重试中（2/3）');
    expect(badge.getAttribute('title')).toContain('LLM 代理超时');
    // 重试中不再显示普通运行中图标
    expect(screen.queryByTestId('session-running')).toBeNull();
  });

  it('shows the normal running badge when there is no retryInfo', () => {
    act(() => {
      useChatStreamStore.getState().startStream('s-1', 'm-1');
    });

    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByTestId('session-running')).toBeInTheDocument();
    expect(screen.queryByTestId('session-retrying')).toBeNull();
  });

  it('shows the background-running badge when db says running but no live slot', () => {
    renderWithI18n(
      <SessionItem
        session={baseSession({ run_status: 'running' })}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByTestId('session-running-background')).toBeInTheDocument();
    expect(screen.queryByTestId('session-running')).toBeNull();
  });
});
