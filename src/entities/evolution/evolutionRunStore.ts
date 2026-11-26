/**
 * Evolution Run Store — 进化任务运行状态的全局单一来源（2026-11-26）。
 *
 * 背景：此前「立即整理记忆 / 立即固化」的 running 状态只存在组件本地
 * useState 里，设置页切 tab 或跳到会话页会卸载组件，状态归零、按钮恢复
 * 可点 —— 而后端任务其实还在跑，结果与 UI 彻底失联，且可被重复触发。
 *
 * 本 store 从后端 EvolutionRunRegistry 快照（GET /scheduled/evolution/tasks
 * 的 run 字段）派生运行态，轮询放在 store 层：组件卸载不影响，任何页面
 * 重新挂载都能立刻恢复到「执行中 + 当前阶段」。
 */
import { toast } from 'sonner';
import { create } from 'zustand';

import { invoke } from '../../shared/api/desktopInvoke';
import type {
  EvolutionRunSnapshot,
  EvolutionTaskStatusEntry,
} from '../../shared/api/types/domainEntityTypes';

/** 运行中轮询间隔：阶段进度以秒级可见即可，过密会对后端造无谓压力。 */
export const EVOLUTION_RUN_POLL_MS = 1200;

/** 连续失败达到该次数后停止轮询，避免后端异常时打爆请求。 */
const MAX_CONSECUTIVE_POLL_FAILURES = 3;

const TASK_LABELS: Record<string, string> = {
  memory_reflection: '记忆整理',
  memory_pruning: '记忆修剪',
  memory_consolidation: '记忆固化',
  daily_summary: '每日摘要',
  preference_learning: '偏好学习',
  importance_reevaluation: '重要性重评估',
  skill_consolidation: '技能巡检',
};

interface EvolutionRunStoreState {
  /** 任务名 → 最近一次运行快照（running / 终态） */
  runs: Record<string, EvolutionRunSnapshot>;
  /** 最近一次轮询失败原因（成功后清空） */
  error: string | null;
  refresh: () => Promise<void>;
  trigger: (name: string) => Promise<EvolutionRunSnapshot | null>;
  /** 协作式取消：置后端取消标志并刷新快照（任务在检查点响应）。 */
  cancel: (name: string) => Promise<EvolutionRunSnapshot | null>;
  /** 测试用：清空状态并停止轮询 */
  reset: () => void;
}

let pollTimer: ReturnType<typeof setInterval> | null = null;
let pollFailures = 0;

function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function hasRunning(runs: Record<string, EvolutionRunSnapshot>): boolean {
  return Object.values(runs).some((run) => run.state === 'running');
}

export const useEvolutionRunStore = create<EvolutionRunStoreState>((set, get) => {
  const ensurePolling = (): void => {
    if (pollTimer !== null) return;
    pollTimer = setInterval(() => {
      void get().refresh();
    }, EVOLUTION_RUN_POLL_MS);
  };

  const applyEntries = (entries: EvolutionTaskStatusEntry[]): void => {
    const previous = get().runs;
    const next: Record<string, EvolutionRunSnapshot> = {};
    for (const entry of entries) {
      if (entry.run) next[entry.name] = entry.run;
    }
    // 只对本 session 内观察到 running 的 run 提示完成，避免首次挂载把
    // 历史终态误报成"刚刚完成"。
    for (const [name, run] of Object.entries(next)) {
      if (previous[name]?.state !== 'running' || run.state === 'running') continue;
      const label = TASK_LABELS[name] ?? name;
      if (run.state === 'succeeded') {
        toast.success(`${label}完成`);
      } else if (run.state === 'failed') {
        toast.error(`${label}失败${run.error ? `：${run.error}` : ''}`);
      } else {
        toast.info(`${label}已取消`);
      }
    }
    set({ runs: next, error: null });
    if (hasRunning(next)) {
      ensurePolling();
    } else {
      stopPolling();
    }
  };

  return {
    runs: {},
    error: null,

    async refresh(): Promise<void> {
      try {
        const raw = await invoke<{ tasks?: EvolutionTaskStatusEntry[] }>(
          'scheduled_evolution_tasks',
        );
        pollFailures = 0;
        applyEntries(raw?.tasks ?? []);
      } catch (err) {
        pollFailures += 1;
        set({ error: err instanceof Error ? err.message : String(err) });
        if (pollFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
          stopPolling();
        }
      }
    },

    async trigger(name: string): Promise<EvolutionRunSnapshot | null> {
      const raw = await invoke<unknown>('scheduled_evolution_run', { name });
      const body = (raw ?? {}) as Record<string, unknown>;
      if (body.ok === false) {
        throw new Error(typeof body.detail === 'string' ? body.detail : '任务启动失败');
      }
      // 立即取回新快照（running / 幂等 attach），再确保轮询持续 ——
      // 即使组件此刻卸载，store 层定时器仍会把任务推进到终态。
      await get().refresh();
      ensurePolling();
      return get().runs[name] ?? null;
    },

    async cancel(name: string): Promise<EvolutionRunSnapshot | null> {
      const raw = await invoke<unknown>('scheduled_evolution_cancel', { name });
      const body = (raw ?? {}) as Record<string, unknown>;
      if (body.ok === false) {
        throw new Error(typeof body.detail === 'string' ? body.detail : '取消失败');
      }
      // 立即刷新：snapshot 的 cancel_requested 让 UI 切到「取消中…」，
      // 任务在检查点响应后状态收敛为 cancelled。
      await get().refresh();
      ensurePolling();
      return get().runs[name] ?? null;
    },

    reset(): void {
      stopPolling();
      pollFailures = 0;
      set({ runs: {}, error: null });
    },
  };
});
