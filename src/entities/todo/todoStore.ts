import { toast } from 'sonner';
import { create } from 'zustand';

import { todoClient } from '../../shared/api/todoClient';
import type {
  CreateTodoInput,
  Todo,
  TodoBatchCompleteResult,
  TodoDropZone,
  TodoListParams,
  TodoSummary,
  UpdateTodoInput,
} from '../../shared/api/types';
import { applyOptimisticMove, buildMoveRequest } from '../../shared/lib/dnd/todoDrag';

interface TodoState {
  todos: Todo[];
  loading: boolean;
  error: string | null;
  summary: TodoSummary | null;
  params: TodoListParams;
  load: (params?: TodoListParams) => Promise<void>;
  setParams: (params: TodoListParams) => Promise<void>;
  create: (input: CreateTodoInput) => Promise<Todo>;
  update: (id: number, changes: UpdateTodoInput) => Promise<Todo>;
  delete: (id: number) => Promise<void>;
  complete: (id: number) => Promise<Todo>;
  cancel: (id: number) => Promise<Todo>;
  batchComplete: (ids: number[]) => Promise<TodoBatchCompleteResult>;
  batchDelete: (ids: number[]) => Promise<number>;
  snooze: (id: number, minutes: number) => Promise<Todo>;
  /**
   * P1 拖拽移动：乐观重排 + 失败回滚。
   *
   * 落点非法时（找不到行 / 拖到自己）**不发请求**，直接返回 ``false``。
   */
  moveTodo: (draggedId: number, targetId: number, zone: TodoDropZone) => Promise<boolean>;
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
  params: { sort_by: 'manual' },

  async load(params?: TodoListParams) {
    set({ loading: true, error: null });
    try {
      const response = await todoClient.list(params);
      set({ todos: response.items, loading: false, params: params ?? get().params });
    } catch (error: unknown) {
      set({ todos: [], loading: false, error: getErrorMessage(error) });
    }
  },

  async setParams(params: TodoListParams) {
    set({ params });
    await get().load(params);
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

  // 批量操作走单次后端请求；完成后重载当前筛选，保证 total/排序与服务端一致。
  async batchComplete(ids: number[]) {
    const result = await todoClient.batchComplete(ids);
    await get().load(get().params);
    return result;
  },

  async batchDelete(ids: number[]) {
    const result = await todoClient.batchDelete(ids);
    await get().load(get().params);
    return result.deleted;
  },

  async snooze(id: number, minutes: number) {
    const updated = await todoClient.snooze(id, minutes);
    set({ todos: get().todos.map((t) => (t.id === id ? updated : t)) });
    return updated;
  },

  /**
   * P1 拖拽移动：先本地重排（乐观），请求失败则回滚原数组并 toast。
   *
   * 成功后**不**把服务端返回的 ``sort_order`` 合并回本地数组 ——
   * 服务端的绝对值（中点插入，可能非常大）与本地的 1024 步进值不同源，
   * 混用会算出错误的本地次序。两者的**相对次序**始终一致（服务端把目标
   * 插在同一相对位置），渲染只关心次序，因此保留乐观数组即可。
   */
  async moveTodo(draggedId: number, targetId: number, zone: TodoDropZone) {
    const previous = get().todos;
    const optimistic = applyOptimisticMove(previous, draggedId, targetId, zone);
    if (optimistic === previous) return false;

    set({ todos: optimistic });
    try {
      await todoClient.move(draggedId, buildMoveRequest(targetId, zone));
      return true;
    } catch (error: unknown) {
      set({ todos: previous });
      const detail =
        error instanceof Error && error.message.trim() ? error.message.trim() : String(error);
      toast.error(`移动待办失败：${detail}`);
      throw error;
    }
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

export function buildTodoStoreAuditSnapshot(input: TodoStoreAuditInput = {}): string {
  const todoCount = Math.max(0, input.todoCount ?? 0);
  const pendingCount = Math.max(0, input.pendingCount ?? 0);
  const loading = Boolean(input.loading);
  const hasError = Boolean(input.hasError);
  const hasSummary = Boolean(input.hasSummary);
  return `todos:${todoCount}|pending:${pendingCount}|loading:${loading ? 'yes' : 'no'}|err:${hasError ? 'yes' : 'no'}|summary:${hasSummary ? 'yes' : 'no'}`;
}

export function buildTodoStoreAuditJson(input: TodoStoreAuditInput = {}): string {
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

export function auditTodoStoreGovernance(
  state: {
    totalCount?: number;
    inProgressCount?: number;
  } = {},
): {
  module: 'src/entities/todo/todoStore.ts';
  phase: 'P156';
  totalCount: number;
  inProgressCount: number;
  healthy: boolean;
} {
  const totalCount =
    typeof state.totalCount === 'number' && Number.isFinite(state.totalCount)
      ? Math.max(0, Math.trunc(state.totalCount))
      : 0;
  const inProgressCount =
    typeof state.inProgressCount === 'number' && Number.isFinite(state.inProgressCount)
      ? Math.max(0, Math.trunc(state.inProgressCount))
      : 0;
  return {
    module: 'src/entities/todo/todoStore.ts',
    phase: 'P156',
    totalCount,
    inProgressCount,
    healthy: inProgressCount <= 1 && inProgressCount <= totalCount + 1,
  };
}
