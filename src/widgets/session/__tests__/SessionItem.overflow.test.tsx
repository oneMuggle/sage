import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Session } from '../../../shared/lib/store';
import { SessionItem } from '../SessionItem';

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

const makeSession = (overrides: Partial<Session> = {}): Session => ({
  id: 's-overflow-1',
  title: '这是一个非常非常长的会话标题用来测试溢出样式是否正常工作'.repeat(3),
  created_at: Date.now() - 60_000,
  updated_at: Date.now() - 60_000,
  last_message_at: Date.now() - 60_000,
  message_count: 42,
  last_message_preview:
    'https://example.com/very/long/unbroken/url/path/that/could/overflow/the/entire/sidebar/container/and/push/buttons/away',
  is_pinned: false,
  ...overrides,
});

describe('SessionItem — overflow & truncation safeguards', () => {
  it('renders root with w-full min-w-0 overflow-hidden', () => {
    renderWithI18n(
      <SessionItem
        session={makeSession()}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const item = screen.getByTestId('session-item');
    expect(item.className).toContain('w-full');
    expect(item.className).toContain('min-w-0');
    expect(item.className).toContain('overflow-hidden');
  });

  it('renders title with truncate flex-1 min-w-0 classes', () => {
    const session = makeSession();
    renderWithI18n(
      <SessionItem session={session} isActive={false} onSelect={vi.fn()} onDelete={vi.fn()} />,
    );

    const titleSpan = screen.getByText(session.title);
    expect(titleSpan.className).toContain('truncate');
    expect(titleSpan.className).toContain('flex-1');
    expect(titleSpan.className).toContain('min-w-0');
  });

  it('renders preview with truncate and keeps message count / time visible', () => {
    const session = makeSession();
    renderWithI18n(
      <SessionItem session={session} isActive={false} onSelect={vi.fn()} onDelete={vi.fn()} />,
    );

    const previewSpan = screen.getByText(session.last_message_preview!);
    expect(previewSpan.className).toContain('truncate');
    expect(previewSpan.className).toContain('flex-1');
    expect(previewSpan.className).toContain('min-w-0');

    // 消息条数依然渲染
    expect(screen.getByText('42 条')).toBeInTheDocument();
  });
});
