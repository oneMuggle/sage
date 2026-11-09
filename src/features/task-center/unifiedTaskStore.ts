// src/features/task-center/unifiedTaskStore.ts
//
// 任务中心专用的三源只读数据视图。
// 不复用 useGoalStore / useTodoStore / useScheduledTaskStore：
//   - goalStore.load() 会继承用户在 /goals 页设置的 statusFilter（goalStore.ts:48）
//   - 页面 store 有各自的加载节奏与筛选态，会污染"全量视图"语义
import { create } from 'zustand';

import { listGoals } from '../../entities/autonomous-goals/goalApi';
import type { Goal } from '../../entities/autonomous-goals/types';
import { scheduledClient } from '../../shared/api/scheduledClient';
import { todoClient } from '../../shared/api/todoClient';
import type { ScheduledTask, Todo } from '../../shared/api/types';

const FULL_LIMIT = 200;

interface UnifiedTaskState {
  goals: Goal[];
  todos: Todo[];
  scheduledTasks: ScheduledTask[];
  loading: boolean;
  error: string | null;
  lastFetchedAt: number | null;
  refresh: () => Promise<void>;
  refreshGoals: () => Promise<void>;
  refreshTodos: () => Promise<void>;
  refreshScheduled: () => Promise<void>;
}

function toMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export const useUnifiedTaskStore = create<UnifiedTaskState>((set, get) => ({
  goals: [],
  todos: [],
  scheduledTasks: [],
  loading: false,
  error: null,
  lastFetchedAt: null,

  async refresh() {
    // 并发保护：已有请求在飞时不重复发
    if (get().loading) return;
    set({ loading: true, error: null });

    // 三源互不阻断：任一失败只记 error，其余照常落库
    const [goalsR, todosR, scheduledR] = await Promise.allSettled([
      listGoals(undefined, FULL_LIMIT, 0),
      todoClient.list({ limit: FULL_LIMIT, offset: 0, include_completed: true }),
      scheduledClient.list(),
    ]);

    const errors: string[] = [];

    const goals = goalsR.status === 'fulfilled' ? goalsR.value.items : [];
    if (goalsR.status === 'rejected') errors.push(toMessage(goalsR.reason));

    const todos = todosR.status === 'fulfilled' ? todosR.value.items : [];
    if (todosR.status === 'rejected') errors.push(toMessage(todosR.reason));

    // scheduledClient.list() 直接返回数组，不包 { items }
    const scheduledTasks = scheduledR.status === 'fulfilled' ? scheduledR.value : [];
    if (scheduledR.status === 'rejected') errors.push(toMessage(scheduledR.reason));

    set({
      goals,
      todos,
      scheduledTasks,
      loading: false,
      error: errors.length > 0 ? errors.join('; ') : null,
      lastFetchedAt: Date.now(),
    });
  },

  async refreshGoals() {
    try {
      const resp = await listGoals(undefined, FULL_LIMIT, 0);
      set({ goals: resp.items });
    } catch (err) {
      set({ error: toMessage(err) });
    }
  },

  async refreshTodos() {
    try {
      const resp = await todoClient.list({
        limit: FULL_LIMIT,
        offset: 0,
        include_completed: true,
      });
      set({ todos: resp.items });
    } catch (err) {
      set({ error: toMessage(err) });
    }
  },

  async refreshScheduled() {
    try {
      const list = await scheduledClient.list();
      set({ scheduledTasks: list });
    } catch (err) {
      set({ error: toMessage(err) });
    }
  },
}));

/** 测试与 M6 归档用：重置到初始态。 */
export function resetUnifiedTaskStore(): void {
  useUnifiedTaskStore.setState({
    goals: [],
    todos: [],
    scheduledTasks: [],
    loading: false,
    error: null,
    lastFetchedAt: null,
  });
}
