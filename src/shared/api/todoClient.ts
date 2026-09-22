/**
 * IPC client for the personal todolist subsystem.
 *
 * Translates to backend HTTP via Electron preload:
 *   todo_list      → GET    /api/v1/todos
 *   todo_create    → POST   /api/v1/todos
 *   todo_get       → GET    /api/v1/todos/{id}
 *   todo_update    → PUT    /api/v1/todos/{id}
 *   todo_delete    → DELETE /api/v1/todos/{id}
 *   todo_complete  → POST   /api/v1/todos/{id}/complete
 *   todo_cancel    → POST   /api/v1/todos/{id}/cancel
 *   todo_summary   → GET    /api/v1/todos/summary
 *   todo_stats     → GET    /api/v1/todos/stats
 *
 * All methods throw on IPC failure; callers wrap in try/catch and surface a
 * toast on failure.
 */
import { invoke } from './desktopInvoke';
import type {
  CreateTodoInput,
  Todo,
  TodoListParams,
  TodoListResponse,
  TodoStats,
  TodoSummary,
  UpdateTodoInput,
} from './types';

export const todoClient = {
  async list(params?: TodoListParams): Promise<TodoListResponse> {
    return invoke<TodoListResponse>('todo_list', { ...(params ?? {}) });
  },

  async create(input: CreateTodoInput): Promise<Todo> {
    return invoke<Todo>('todo_create', { ...input });
  },

  async get(id: number): Promise<Todo> {
    return invoke<Todo>('todo_get', { id });
  },

  async update(id: number, changes: UpdateTodoInput): Promise<Todo> {
    return invoke<Todo>('todo_update', { id, ...changes });
  },

  async delete(id: number): Promise<void> {
    await invoke<void>('todo_delete', { id });
  },

  async complete(id: number): Promise<Todo> {
    return invoke<Todo>('todo_complete', { id });
  },

  async cancel(id: number): Promise<Todo> {
    return invoke<Todo>('todo_cancel', { id });
  },

  async summary(): Promise<TodoSummary> {
    return invoke<TodoSummary>('todo_summary', {});
  },

  async stats(): Promise<TodoStats> {
    return invoke<TodoStats>('todo_stats', {});
  },
};