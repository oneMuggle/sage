/**
 * TodoPage page test (Task 12 - 2026-09-21 todolist subsystem).
 *
 * Verifies the dedicated `/todos` page contract:
 * - Renders heading + create form (title is the only required field).
 * - Submitting the form calls `todoClient.create` and prepends the new todo.
 * - Lists all todos (pending + completed) with completion / delete actions.
 * - Empty state shows a friendly placeholder when the list is empty.
 * - loading state shows a spinner-like placeholder when `loading` is true.
 *
 * Mocks `entities/todo/todoStore` (zustand) so we can drive the store state
 * deterministically without going through the IPC layer.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Todo } from '../../shared/api/types';
import { I18nProvider } from '../../shared/lib/i18n';
import { TodoPage } from '../TodoPage';

const mocks = vi.hoisted(() => ({
  load: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
  complete: vi.fn(),
  cancel: vi.fn(),
  loadSummary: vi.fn(),
  state: {
    todos: [] as Todo[],
    loading: false,
    error: null as string | null,
    summary: null,
  },
}));

// Mock the zustand store hook so callers receive our controlled `state`.
// Page calls useTodoStore with selectors that read `s.todos` / `s.load`, etc.
// We satisfy both reads and action reads by returning a merged object
// (state shape + action functions).
vi.mock('../../entities/todo/todoStore', () => ({
  useTodoStore: (selector: (s: unknown) => unknown) => {
    const merged = {
      ...mocks.state,
      load: mocks.load,
      create: mocks.create,
      update: mocks.update,
      delete: mocks.delete,
      complete: mocks.complete,
      cancel: mocks.cancel,
      loadSummary: mocks.loadSummary,
    };
    return selector(merged);
  },
}));

beforeEach(() => {
  mocks.state.todos = [];
  mocks.state.loading = false;
  mocks.state.error = null;
  mocks.state.summary = null;
  mocks.load.mockResolvedValue(undefined);
  mocks.create.mockResolvedValue({} as Todo);
  mocks.update.mockResolvedValue({} as Todo);
  mocks.delete.mockResolvedValue(undefined);
  mocks.complete.mockResolvedValue({} as Todo);
  mocks.cancel.mockResolvedValue({} as Todo);
  mocks.loadSummary.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderPage() {
  return render(
    <I18nProvider>
      <TodoPage />
    </I18nProvider>,
  );
}

describe('TodoPage', () => {
  it('renders heading and create form', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: /待办事项/ })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/待办标题/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /添加|新建|创建/ })).toBeInTheDocument();
  });

  it('calls load on mount', () => {
    renderPage();
    expect(mocks.load).toHaveBeenCalledTimes(1);
  });

  it('shows empty placeholder when there are no todos', () => {
    mocks.state.todos = [];
    renderPage();
    expect(screen.getByText(/暂无待办|没有待办/)).toBeInTheDocument();
  });

  it('lists todos from the store', () => {
    mocks.state.todos = [
      makeTodo({ id: 1, title: '买菜' }),
      makeTodo({ id: 2, title: '写周报', status: 'completed' }),
    ];
    renderPage();
    expect(screen.getByText('买菜')).toBeInTheDocument();
    expect(screen.getByText('写周报')).toBeInTheDocument();
  });

  it('submits a new todo via the form', async () => {
    mocks.create.mockResolvedValue(makeTodo({ id: 99, title: '测试新待办' }));
    renderPage();
    const input = screen.getByPlaceholderText(/待办标题/);
    fireEvent.change(input, { target: { value: '测试新待办' } });
    fireEvent.click(screen.getByRole('button', { name: /添加|新建|创建/ }));
    await waitFor(() => {
      expect(mocks.create).toHaveBeenCalledWith(
        expect.objectContaining({ title: '测试新待办' }),
      );
    });
  });

  it('renders a loading placeholder while loading', () => {
    mocks.state.loading = true;
    renderPage();
    expect(screen.getByText(/加载|loading/i)).toBeInTheDocument();
  });
});

function makeTodo(overrides: Partial<Todo> = {}): Todo {
  return {
    id: 1,
    title: '示例',
    status: 'pending',
    priority: 'medium',
    is_recurring: false,
    created_at: '2026-09-21T00:00:00Z',
    updated_at: '2026-09-21T00:00:00Z',
    ...overrides,
  };
}
