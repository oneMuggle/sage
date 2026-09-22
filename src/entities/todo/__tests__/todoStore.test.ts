import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/todoClient', () => ({
  todoClient: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    complete: vi.fn(),
    cancel: vi.fn(),
    summary: vi.fn(),
    stats: vi.fn(),
    get: vi.fn(),
  },
}));

import { todoClient } from '../../../shared/api/todoClient';
import { useTodoStore } from '../todoStore';

const client = todoClient as unknown as {
  list: ReturnType<typeof vi.fn>;
  create: ReturnType<typeof vi.fn>;
  update: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
  complete: ReturnType<typeof vi.fn>;
  cancel: ReturnType<typeof vi.fn>;
  summary: ReturnType<typeof vi.fn>;
  stats: ReturnType<typeof vi.fn>;
  get: ReturnType<typeof vi.fn>;
};

const sampleTodo = {
  id: 1,
  title: 'Test todo',
  status: 'pending' as const,
  priority: 'medium' as const,
  is_recurring: false,
  created_at: '2026-09-21T00:00:00',
  updated_at: '2026-09-21T00:00:00',
};

describe('useTodoStore', () => {
  beforeEach(() => {
    useTodoStore.setState({ todos: [], loading: false, error: null, summary: null });
    client.list.mockReset();
    client.create.mockReset();
    client.update.mockReset();
    client.delete.mockReset();
    client.complete.mockReset();
    client.cancel.mockReset();
    client.summary.mockReset();
    client.stats.mockReset();
    client.get.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('starts empty with no error and no summary', () => {
    const state = useTodoStore.getState();
    expect(state.todos).toEqual([]);
    expect(state.loading).toBe(false);
    expect(state.error).toBeNull();
    expect(state.summary).toBeNull();
  });

  it('load() fetches and stores response.items', async () => {
    client.list.mockResolvedValueOnce({
      items: [sampleTodo],
      total: 1,
      limit: 50,
      offset: 0,
    });
    await useTodoStore.getState().load();
    expect(useTodoStore.getState().todos).toEqual([sampleTodo]);
    expect(useTodoStore.getState().loading).toBe(false);
  });

  it('load() sets error string on failure and clears todos', async () => {
    client.list.mockRejectedValueOnce(new Error('boom'));
    await useTodoStore.getState().load();
    expect(useTodoStore.getState().error).toBe('boom');
    expect(useTodoStore.getState().todos).toEqual([]);
  });

  it('create() appends returned todo and returns it', async () => {
    client.create.mockResolvedValueOnce(sampleTodo);
    const result = await useTodoStore.getState().create({ title: 'Test todo' });
    expect(result).toEqual(sampleTodo);
    expect(useTodoStore.getState().todos).toEqual([sampleTodo]);
  });

  it('update() replaces the matching todo in place', async () => {
    useTodoStore.setState({ todos: [sampleTodo] });
    const updated = { ...sampleTodo, title: 'Renamed' };
    client.update.mockResolvedValueOnce(updated);
    const result = await useTodoStore.getState().update(1, { title: 'Renamed' });
    expect(result).toBe(updated);
    expect(useTodoStore.getState().todos[0].title).toBe('Renamed');
  });

  it('complete() replaces the matching todo with the returned completed one', async () => {
    useTodoStore.setState({ todos: [sampleTodo] });
    const completed = {
      ...sampleTodo,
      status: 'completed' as const,
      completed_at: '2026-09-21T01:00:00',
    };
    client.complete.mockResolvedValueOnce(completed);
    const result = await useTodoStore.getState().complete(1);
    expect(result.status).toBe('completed');
    expect(useTodoStore.getState().todos[0].status).toBe('completed');
  });

  it('cancel() replaces the matching todo with the returned cancelled one', async () => {
    useTodoStore.setState({ todos: [sampleTodo] });
    const cancelled = { ...sampleTodo, status: 'cancelled' as const };
    client.cancel.mockResolvedValueOnce(cancelled);
    const result = await useTodoStore.getState().cancel(1);
    expect(result.status).toBe('cancelled');
    expect(useTodoStore.getState().todos[0].status).toBe('cancelled');
  });

  it('delete() removes the matching todo', async () => {
    useTodoStore.setState({ todos: [sampleTodo, { ...sampleTodo, id: 2, title: 'Second' }] });
    client.delete.mockResolvedValueOnce(undefined);
    await useTodoStore.getState().delete(1);
    const ids = useTodoStore.getState().todos.map((t) => t.id);
    expect(ids).toEqual([2]);
  });

  it('delete() sets error and rethrows on failure', async () => {
    useTodoStore.setState({ todos: [sampleTodo] });
    client.delete.mockRejectedValueOnce(new Error('nope'));
    await expect(useTodoStore.getState().delete(1)).rejects.toThrow('nope');
    expect(useTodoStore.getState().error).toBe('nope');
    expect(useTodoStore.getState().todos).toEqual([sampleTodo]);
  });

  it('loadSummary() stores the summary', async () => {
    const fixture = {
      overdue: [],
      today: [],
      upcoming: [],
      high_priority: [],
      total_pending: 0,
      total_completed_today: 0,
    };
    client.summary.mockResolvedValueOnce(fixture);
    await useTodoStore.getState().loadSummary();
    expect(useTodoStore.getState().summary).toBe(fixture);
  });
});
