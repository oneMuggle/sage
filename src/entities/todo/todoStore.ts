import { create } from 'zustand';

import { todoClient } from '../../shared/api/todoClient';
import type { CreateTodoInput, Todo, TodoSummary, UpdateTodoInput } from '../../shared/api/types';

interface TodoState {
  todos: Todo[];
  loading: boolean;
  error: string | null;
  summary: TodoSummary | null;
  load: () => Promise<void>;
  create: (input: CreateTodoInput) => Promise<Todo>;
  update: (id: number, changes: UpdateTodoInput) => Promise<Todo>;
  delete: (id: number) => Promise<void>;
  complete: (id: number) => Promise<Todo>;
  cancel: (id: number) => Promise<Todo>;
  loadSummary: () => Promise<void>;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export const useTodoStore = create<TodoState>((set, get) => ({
  todos: [],
  loading: false,
  error: null,
  summary: null,

  async load() {
    set({ loading: true, error: null });
    try {
      const response = await todoClient.list();
      set({ todos: response.items, loading: false });
    } catch (error: unknown) {
      set({ todos: [], loading: false, error: getErrorMessage(error) });
    }
  },

  async create(input: CreateTodoInput) {
    const todo = await todoClient.create(input);
    set({ todos: [...get().todos, todo] });
    return todo;
  },

  async update(id: number, changes: UpdateTodoInput) {
    const updated = await todoClient.update(id, changes);
    set({ todos: get().todos.map((t) => (t.id === id ? updated : t)) });
    return updated;
  },

  async delete(id: number) {
    try {
      await todoClient.delete(id);
      set({ todos: get().todos.filter((t) => t.id !== id), error: null });
    } catch (error: unknown) {
      set({ error: getErrorMessage(error) });
      throw error;
    }
  },

  async complete(id: number) {
    const updated = await todoClient.complete(id);
    set({ todos: get().todos.map((t) => (t.id === id ? updated : t)) });
    return updated;
  },

  async cancel(id: number) {
    const updated = await todoClient.cancel(id);
    set({ todos: get().todos.map((t) => (t.id === id ? updated : t)) });
    return updated;
  },

  async loadSummary() {
    const next = await todoClient.summary();
    set({ summary: next });
  },
}));

export interface TodoStoreAuditInput {
  todoCount?: number;
  pendingCount?: number;
  loading?: boolean;
  hasError?: boolean;
  hasSummary?: boolean;
}

export function buildTodoStoreAuditSnapshot(
  input: TodoStoreAuditInput = {},
): string {
  const todoCount = Math.max(0, input.todoCount ?? 0);
  const pendingCount = Math.max(0, input.pendingCount ?? 0);
  const loading = Boolean(input.loading);
  const hasError = Boolean(input.hasError);
  const hasSummary = Boolean(input.hasSummary);
  return `todos:${todoCount}|pending:${pendingCount}|loading:${loading ? 'yes' : 'no'}|err:${hasError ? 'yes' : 'no'}|summary:${hasSummary ? 'yes' : 'no'}`;
}

export function buildTodoStoreAuditJson(
  input: TodoStoreAuditInput = {},
): string {
  const todoCount = Math.max(0, input.todoCount ?? 0);
  const pendingCount = Math.max(0, input.pendingCount ?? 0);
  const loading = Boolean(input.loading);
  const hasError = Boolean(input.hasError);
  const hasSummary = Boolean(input.hasSummary);
  return JSON.stringify({
    todoCount,
    pendingCount,
    loading,
    hasError,
    hasSummary,
    snapshot: buildTodoStoreAuditSnapshot(input),
  });
}
