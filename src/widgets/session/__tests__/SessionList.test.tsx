import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Session } from '../../../shared/lib/store';
import { formatSessionListJson, formatSessionListMarkdown, SessionList } from '../SessionList';

const SAMPLE_SESSIONS: Session[] = [
  {
    id: 's1',
    title: '架构设计讨论',
    created_at: 1000,
    updated_at: 2000,
    last_message_at: 2000,
    message_count: 5,
    is_pinned: true,
  },
  {
    id: 's2',
    title: '性能优化排查',
    created_at: 1500,
    updated_at: 2500,
    last_message_at: null,
    message_count: 0,
    is_pinned: false,
  },
];

describe('SessionList', () => {
  it('module exports a component function', () => {
    expect(typeof SessionList).toBe('function');
  });

  it('renders empty state and exports Markdown/JSON for session list', () => {
    expect(formatSessionListMarkdown([])).toContain('_暂无对话记录_');
    const md = formatSessionListMarkdown(SAMPLE_SESSIONS, 's1');
    expect(md).toContain('# 会话列表摘要 (Session List)');
    expect(md).toContain('[当前] [置顶]');
    const parsed = JSON.parse(formatSessionListJson(SAMPLE_SESSIONS, 's1'));
    expect(parsed.total).toBe(2);

    const { unmount } = render(
      <I18nProvider>
        <SessionList sessions={[]} currentSessionId={null} onSelect={vi.fn()} onDelete={vi.fn()} />
      </I18nProvider>,
    );
    expect(screen.getByText('暂无对话记录')).toBeInTheDocument();
    unmount();

    render(
      <I18nProvider>
        <SessionList
          sessions={SAMPLE_SESSIONS}
          currentSessionId="s1"
          onSelect={vi.fn()}
          onDelete={vi.fn()}
        />
      </I18nProvider>,
    );
  });
});
