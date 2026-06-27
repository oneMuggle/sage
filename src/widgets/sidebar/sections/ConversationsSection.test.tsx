import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Session } from '../../../shared/lib/store';

import { ConversationsSection } from './ConversationsSection';

const sessions: Session[] = [
  {
    id: 's1',
    title: 'first',
    created_at: Date.now(),
    updated_at: Date.now(),
    last_message_at: null,
    message_count: 0,
    is_pinned: false,
  },
  {
    id: 's2',
    title: 'second',
    created_at: Date.now(),
    updated_at: Date.now(),
    last_message_at: null,
    message_count: 0,
    is_pinned: false,
  },
];

const renderWithI18n = (ui: React.ReactNode) => render(<I18nProvider>{ui}</I18nProvider>);

const baseProps = {
  sessions,
  order: ['s1', 's2'],
  currentSessionId: null as string | null,
  collapsed: false,
  onToggleCollapsed: () => {},
  onSelect: () => {},
  onDelete: () => {},
  onNewSession: () => {},
  onOrderChange: () => {},
};

describe('ConversationsSection', () => {
  it('renders section label and sessions', () => {
    renderWithI18n(<ConversationsSection {...baseProps} />);
    expect(screen.getByText('会话')).toBeInTheDocument();
    expect(screen.getByText('first')).toBeInTheDocument();
    expect(screen.getByText('second')).toBeInTheDocument();
  });

  it('hides body when collapsed', () => {
    renderWithI18n(<ConversationsSection {...baseProps} collapsed={true} />);
    expect(screen.queryByText('first')).not.toBeInTheDocument();
  });

  it('clicking the trailing "+" button calls onNewSession', () => {
    const onNew = vi.fn();
    renderWithI18n(<ConversationsSection {...baseProps} onNewSession={onNew} />);
    fireEvent.click(screen.getByRole('button', { name: '新对话' }));
    expect(onNew).toHaveBeenCalledTimes(1);
  });

  it('clicking collapse button calls onToggleCollapsed', () => {
    const onToggle = vi.fn();
    renderWithI18n(<ConversationsSection {...baseProps} onToggleCollapsed={onToggle} />);
    fireEvent.click(screen.getByRole('button', { name: '折叠' }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
