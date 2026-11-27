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
import { MemoryRouter } from 'react-router-dom';
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
  setParams: vi.fn(),
  batchComplete: vi.fn(),
  batchDelete: vi.fn(),
  exportTodos: vi.fn(),
  listTags: vi.fn(),
  dailyBrief: vi.fn(),
  weeklyReview: vi.fn(),
  heatmap: vi.fn(),
  snooze: vi.fn(),
  worklogList: vi.fn(),
  state: {
    todos: [] as Todo[],
    loading: false,
    error: null as string | null,
    summary: null,
    params: {} as Record<string, unknown>,
  },
}));

vi.mock('../../shared/api/todoClient', () => ({
  todoClient: {
    exportTodos: mocks.exportTodos,
    listTags: mocks.listTags,
    dailyBrief: mocks.dailyBrief,
    weeklyReview: mocks.weeklyReview,
    heatmap: mocks.heatmap,
    snooze: mocks.snooze,
  },
}));

vi.mock('../../shared/api/agentsApi', () => ({
  agentsApi: { list: vi.fn().mockResolvedValue([]) },
}));

// 工作日志分段只用到 list（收件箱 + 已确认流各一次）。
vi.mock('../../shared/api/worklogClient', () => ({
  worklogClient: {
    list: mocks.worklogList,
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    confirm: vi.fn(),
    dismiss: vi.fn(),
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
      setParams: mocks.setParams,
      batchComplete: mocks.batchComplete,
      batchDelete: mocks.batchDelete,
      snooze: mocks.snooze,
    };
    return selector(merged);
  },
}));

beforeEach(() => {
  mocks.state.todos = [];
  mocks.state.loading = false;
  mocks.state.error = null;
  mocks.state.summary = null;
  mocks.state.params = {};
  mocks.load.mockResolvedValue(undefined);
  mocks.create.mockResolvedValue({} as Todo);
  mocks.update.mockResolvedValue({} as Todo);
  mocks.delete.mockResolvedValue(undefined);
  mocks.complete.mockResolvedValue({} as Todo);
  mocks.cancel.mockResolvedValue({} as Todo);
  mocks.loadSummary.mockResolvedValue(undefined);
  mocks.setParams.mockResolvedValue(undefined);
  mocks.batchComplete.mockResolvedValue({ completed: 1, missing: [] });
  mocks.batchDelete.mockResolvedValue(1);
  mocks.exportTodos.mockResolvedValue({
    filename: 'sage-todos.md',
    format: 'md',
    content: '- [ ] 示例',
  });
  mocks.listTags.mockResolvedValue([]);
  mocks.dailyBrief.mockResolvedValue({ content: '• 处理逾期项' });
  mocks.weeklyReview.mockResolvedValue({ content: '## 完成情况' });
  mocks.heatmap.mockResolvedValue({
    days: [{ date: '2026-11-18', count: 2 }],
    total: 2,
    max: 2,
  });
  mocks.snooze.mockResolvedValue({} as Todo);
  mocks.worklogList.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  Object.defineProperty(URL, 'createObjectURL', {
    writable: true,
    value: vi.fn(() => 'blob:mock'),
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    writable: true,
    value: vi.fn(),
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderPage(initialEntry = '/todos') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <I18nProvider>
        <TodoPage />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe('TodoPage', () => {
  it('renders heading and create form', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: /待办事项/ })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/待办标题/)).toBeInTheDocument();
    expect(screen.getByTestId('todo-submit')).toBeInTheDocument();
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
    fireEvent.click(screen.getByTestId('todo-submit'));
    await waitFor(() => {
      expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ title: '测试新待办' }));
    });
  });

  it('renders a loading placeholder while loading', () => {
    mocks.state.loading = true;
    renderPage();
    expect(screen.getByText(/加载|loading/i)).toBeInTheDocument();
  });

  it('debounces search input into a backend q param', async () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText('搜索待办...'), {
      target: { value: '周报' },
    });
    await waitFor(
      () => {
        expect(mocks.setParams).toHaveBeenCalledWith(expect.objectContaining({ q: '周报' }));
      },
      { timeout: 1500 },
    );
  });

  it('batch complete uses the batch endpoint via the store', async () => {
    mocks.state.todos = [makeTodo({ id: 11, title: '批量任务' })];
    renderPage();
    fireEvent.click(screen.getByLabelText('选择 批量任务'));
    fireEvent.click(screen.getByRole('button', { name: '批量完成' }));
    await waitFor(() => {
      expect(mocks.batchComplete).toHaveBeenCalledWith([11]);
    });
  });

  it('export button downloads via todoClient.exportTodos', async () => {
    mocks.state.todos = [makeTodo({ id: 1, title: '导出任务' })];
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: '导出 Markdown' }));
    await waitFor(() => {
      expect(mocks.exportTodos).toHaveBeenCalledWith('md', true);
    });
  });

  it('creates a subtask from a top-level row inline input', async () => {
    mocks.state.todos = [makeTodo({ id: 1, title: '父任务' })];
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: '为 父任务 添加子任务' }));
    const input = screen.getByTestId('todo-subtask-input');
    fireEvent.change(input, { target: { value: '子任务' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => {
      expect(mocks.create).toHaveBeenCalledWith({
        title: '子任务',
        parent_id: 1,
      });
    });
  });

  it('opens quick add with the N shortcut and creates a parsed todo', async () => {
    renderPage();

    fireEvent.keyDown(window, { key: 'n' });
    const input = await screen.findByTestId('quick-add-input');
    fireEvent.change(input, { target: { value: '明天下午3点 交报告 !高 #工作' } });
    expect(screen.getByTestId('quick-add-preview').textContent).toContain('优先级 高');

    fireEvent.click(screen.getByTestId('quick-add-submit'));

    await waitFor(() => {
      expect(mocks.create).toHaveBeenCalledWith(
        expect.objectContaining({
          title: '交报告',
          priority: 'high',
          tags: ['工作'],
          due_at: expect.stringMatching(/T15:00:00$/),
        }),
      );
    });
  });

  it('switches the smart view via the toolbar', async () => {
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: '今天' }));

    await waitFor(() => {
      expect(mocks.setParams).toHaveBeenCalledWith(expect.objectContaining({ view: 'today' }));
    });
  });

  it('submits reminder offsets chosen in the create form', async () => {
    renderPage();

    const titleInput = screen.getByPlaceholderText(/待办标题/);
    fireEvent.focus(titleInput);
    fireEvent.change(titleInput, { target: { value: '带提醒的任务' } });
    fireEvent.click(screen.getByTestId('todo-reminder-60'));
    fireEvent.click(screen.getByTestId('todo-submit'));

    await waitFor(() => {
      expect(mocks.create).toHaveBeenCalledWith(
        expect.objectContaining({
          title: '带提醒的任务',
          reminder_offsets: [60],
        }),
      );
    });
  });

  it('opens the AI brief dialog from the header', async () => {
    renderPage();

    fireEvent.click(screen.getByTestId('todo-ai-brief'));

    expect(await screen.findByTestId('todo-ai-content')).toHaveTextContent('处理逾期项');
    expect(mocks.dailyBrief).toHaveBeenCalledTimes(1);
  });

  it('toggles the completion heatmap', async () => {
    renderPage();

    fireEvent.click(screen.getByTestId('todo-heatmap-toggle'));

    expect(await screen.findByTestId('todo-heatmap')).toBeInTheDocument();
    expect(mocks.heatmap).toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('todo-heatmap-toggle'));
    await waitFor(() => {
      expect(screen.queryByTestId('todo-heatmap')).not.toBeInTheDocument();
    });
  });

  it('switches to the worklog tab and hides todo-only header actions', async () => {
    renderPage();

    expect(screen.getByTestId('todo-tab-todos')).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(screen.getByTestId('todo-tab-logs'));

    expect(await screen.findByTestId('todo-worklog-panel')).toBeInTheDocument();
    expect(screen.getByTestId('todo-tab-logs')).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByTestId('todo-ai-brief')).not.toBeInTheDocument();
    expect(mocks.worklogList).toHaveBeenCalledWith({ status: 'pending', limit: 50 });
    expect(mocks.worklogList).toHaveBeenCalledWith({ status: 'confirmed', limit: 200 });
  });

  it('opens the worklog tab directly from ?tab=logs', async () => {
    renderPage('/todos?tab=logs');

    expect(await screen.findByTestId('todo-worklog-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('todo-create-title')).not.toBeInTheDocument();
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
