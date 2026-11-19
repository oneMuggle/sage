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
 *   todo_batch_complete → POST /api/v1/todos/batch/complete
 *   todo_batch_delete   → POST /api/v1/todos/batch/delete
 *   todo_export         → GET  /api/v1/todos/export
 *   todo_tags           → GET  /api/v1/todos/tags
 *
 * All methods throw on IPC failure; callers wrap in try/catch and surface a
 * toast on failure.
 */
import { invoke } from './desktopInvoke';
import type {
  CreateTodoInput,
  Todo,
  TodoAiText,
  TodoBatchCompleteResult,
  TodoBatchDeleteResult,
  TodoExportResult,
  TodoExtractResult,
  TodoHeatmapResult,
  TodoListParams,
  TodoListResponse,
  TodoStats,
  TodoSummary,
  TodoTagCount,
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

  async listTags(): Promise<TodoTagCount[]> {
    return invoke<TodoTagCount[]>('todo_tags', {});
  },

  /** 阶段 2：从会话提炼待办候选（不落库，确认后 batchCreate）。 */
  async extractFromSession(sessionId: string, messageIds?: string[]): Promise<TodoExtractResult> {
    return invoke<TodoExtractResult>('todo_extract', {
      session_id: sessionId,
      ...(messageIds && messageIds.length > 0 ? { message_ids: messageIds } : {}),
    });
  },

  async batchCreate(items: CreateTodoInput[]): Promise<Todo[]> {
    const result = await invoke<{ items: Todo[] }>('todo_batch_create', { items });
    return result.items;
  },

  async dailyBrief(): Promise<TodoAiText> {
    return invoke<TodoAiText>('todo_brief', {});
  },

  async weeklyReview(): Promise<TodoAiText> {
    return invoke<TodoAiText>('todo_weekly_review', {});
  },

  async batchComplete(ids: number[]): Promise<TodoBatchCompleteResult> {
    return invoke<TodoBatchCompleteResult>('todo_batch_complete', { ids });
  },

  async batchDelete(ids: number[]): Promise<TodoBatchDeleteResult> {
    return invoke<TodoBatchDeleteResult>('todo_batch_delete', { ids });
  },

  async exportTodos(format: 'json' | 'md', includeCompleted = false): Promise<TodoExportResult> {
    return invoke<TodoExportResult>('todo_export', {
      format,
      include_completed: includeCompleted,
    });
  },

  /** 阶段 3：完成热力图（最近 N 天按日聚合完成数）。 */
  async heatmap(days: number = 91): Promise<TodoHeatmapResult> {
    return invoke<TodoHeatmapResult>('todo_heatmap', { days });
  },

  /** 阶段 3：推迟提醒（due_at 后移 N 分钟，snooze_count 自增）。 */
  async snooze(id: number, minutes: number): Promise<Todo> {
    return invoke<Todo>('todo_snooze', { id, minutes });
  },
};

export function formatTodoListSummary(
  res: Pick<TodoListResponse, 'items' | 'total' | 'limit' | 'offset'>,
): string {
  return `${res.items.length}/${res.total} todos · offset ${res.offset} · limit ${res.limit}`;
}

export function formatTodoListJson(
  res: Pick<TodoListResponse, 'items' | 'total' | 'limit' | 'offset'>,
): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.todo_list.v1',
      itemCount: res.items.length,
      total: res.total,
      limit: res.limit,
      offset: res.offset,
    },
    null,
    2,
  );
}

export function auditTodoClientGovernance(): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.api.todo_client.governance.v1',
      phase: 'P177',
      methods: [
        'list',
        'create',
        'get',
        'update',
        'delete',
        'complete',
        'cancel',
        'summary',
        'stats',
        'batchComplete',
        'batchDelete',
        'exportTodos',
        'listTags',
      ],
      sampleSummary: formatTodoListSummary({ items: [], total: 0, limit: 20, offset: 0 }),
    },
    null,
    2,
  );
}
