import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../../../entities/todo/todoStore', () => {
  const state = {
    todos: [],
    loading: false,
    error: null,
    summary: null,
    load: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    complete: vi.fn(),
    cancel: vi.fn(),
    loadSummary: vi.fn(),
  };
  const hook = (sel?: (s: unknown) => unknown) => (sel ? sel(state) : state);
  return {
    useTodoStore: Object.assign(hook, { getState: () => state }),
  };
});

import { I18nProvider } from '../../../../shared/lib/i18n';
import { TodoSection } from '../TodoSection';

const noop = () => {};

describe('TodoSection', () => {
  it('renders the empty state when no todos', () => {
    render(
      <MemoryRouter>
        <I18nProvider>
          <TodoSection collapsed={false} onToggleCollapsed={noop} />
        </I18nProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('todo-list')).toBeTruthy();
    expect(screen.getByText('暂无待办')).toBeTruthy();
  });

  it('renders a link to the /todos page', () => {
    render(
      <MemoryRouter>
        <I18nProvider>
          <TodoSection collapsed={false} onToggleCollapsed={noop} />
        </I18nProvider>
      </MemoryRouter>,
    );
    const link = screen.getByRole('link', { name: /todos\.create|新建待办|add todo/i });
    expect(link).toBeTruthy();
    expect(link.getAttribute('href')).toBe('/todos');
  });
});
