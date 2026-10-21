/**
 * 闲时自主目标执行系统 — Zustand Store
 *
 * 集中管理目标列表状态与操作。
 */
import { toast } from 'sonner';
import { create } from 'zustand';

import * as goalApi from './goalApi';
import type { CreateGoalInput, Goal, GoalStatus, UpdateGoalInput } from './types';

interface GoalState {
  goals: Goal[];
  total: number;
  loading: boolean;
  error: string | null;
  statusFilter: GoalStatus | null;

  // Actions
  load: (status?: GoalStatus) => Promise<void>;
  setStatusFilter: (status: GoalStatus | null) => void;
  create: (input: CreateGoalInput) => Promise<Goal>;
  update: (goalId: string, input: UpdateGoalInput) => Promise<Goal>;
  delete: (goalId: string) => Promise<void>;
  start: (goalId: string) => Promise<Goal>;
  pause: (goalId: string) => Promise<Goal>;
  cancel: (goalId: string) => Promise<Goal>;
  refreshOne: (goalId: string) => Promise<void>;
  clearError: () => void;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export const useGoalStore = create<GoalState>((set, get) => ({
  goals: [],
  total: 0,
  loading: false,
  error: null,
  statusFilter: null,

  async load(status?: GoalStatus) {
    set({ loading: true, error: null });
    try {
      const effectiveStatus = status ?? get().statusFilter ?? undefined;
      const response = await goalApi.listGoals(effectiveStatus);
      set({
        goals: response.items,
        total: response.total,
        loading: false,
      });
    } catch (error: unknown) {
      set({ goals: [], total: 0, loading: false, error: getErrorMessage(error) });
    }
  },

  setStatusFilter(status: GoalStatus | null) {
    set({ statusFilter: status });
  },

  async create(input: CreateGoalInput) {
    try {
      const goal = await goalApi.createGoal(input);
      set({ goals: [...get().goals, goal], total: get().total + 1 });
      toast.success(`目标「${goal.name}」已创建`);
      return goal;
    } catch (error: unknown) {
      set({ error: getErrorMessage(error) });
      toast.error('创建目标失败');
      throw error;
    }
  },

  async update(goalId: string, input: UpdateGoalInput) {
    try {
      const updated = await goalApi.updateGoal(goalId, input);
      set({ goals: get().goals.map((g) => (g.id === goalId ? updated : g)) });
      return updated;
    } catch (error: unknown) {
      set({ error: getErrorMessage(error) });
      throw error;
    }
  },

  async delete(goalId: string) {
    try {
      const removed = get().goals.find((g) => g.id === goalId);
      await goalApi.deleteGoal(goalId);
      set({
        goals: get().goals.filter((g) => g.id !== goalId),
        total: Math.max(0, get().total - 1),
        error: null,
      });
      if (removed) toast.success(`目标「${removed.name}」已删除`);
    } catch (error: unknown) {
      set({ error: getErrorMessage(error) });
      toast.error('删除目标失败');
      throw error;
    }
  },

  async start(goalId: string) {
    try {
      const updated = await goalApi.startGoal(goalId);
      set({ goals: get().goals.map((g) => (g.id === goalId ? updated : g)) });
      toast.success(`目标「${updated.name}」已启动`);
      return updated;
    } catch (error: unknown) {
      set({ error: getErrorMessage(error) });
      toast.error('启动目标失败');
      throw error;
    }
  },

  async pause(goalId: string) {
    try {
      const updated = await goalApi.pauseGoal(goalId);
      set({ goals: get().goals.map((g) => (g.id === goalId ? updated : g)) });
      toast.success(`目标「${updated.name}」已暂停`);
      return updated;
    } catch (error: unknown) {
      set({ error: getErrorMessage(error) });
      toast.error('暂停目标失败');
      throw error;
    }
  },

  async cancel(goalId: string) {
    try {
      const updated = await goalApi.cancelGoal(goalId);
      set({ goals: get().goals.map((g) => (g.id === goalId ? updated : g)) });
      toast.success(`目标「${updated.name}」已取消`);
      return updated;
    } catch (error: unknown) {
      set({ error: getErrorMessage(error) });
      toast.error('取消目标失败');
      throw error;
    }
  },

  async refreshOne(goalId: string) {
    try {
      const goal = await goalApi.getGoal(goalId);
      set({ goals: get().goals.map((g) => (g.id === goalId ? goal : g)) });
    } catch (error: unknown) {
      // Silent refresh failure — don't overwrite main error state
      console.warn('Goal refresh failed:', getErrorMessage(error));
    }
  },

  clearError() {
    set({ error: null });
  },
}));

export function formatGoalStoreSummary(
  state: Pick<
    GoalState,
    'goals' | 'total' | 'loading' | 'error' | 'statusFilter'
  > = useGoalStore.getState(),
): string {
  return `goals=${state.goals.length}/${state.total} · filter=${state.statusFilter ?? 'all'} · loading=${state.loading} · error=${state.error ?? 'none'}`;
}

export function formatGoalStoreJson(
  state: Pick<
    GoalState,
    'goals' | 'total' | 'loading' | 'error' | 'statusFilter'
  > = useGoalStore.getState(),
): string {
  return JSON.stringify(
    {
      goalCount: state.goals.length,
      total: state.total,
      statusFilter: state.statusFilter,
      loading: state.loading,
      error: state.error,
    },
    null,
    2,
  );
}
