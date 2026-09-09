// src/shared/api/orchRunClient.ts
/**
 * 编排 run 生命周期客户端 —— plan 更新 / run 取消。
 * 与 orchestrationClient.ts（lane 维度：create_lane/list_lanes）互补,
 * 本客户端面向 run 维度。
 *
 * Wave 4 (2026-09-06): 历史编排记录功能移除 —— 删除 listRuns / getRun / resumeRun
 * 及其类型 (OrchRunSummary / OrchRunDetail / ResumeResponse)。
 */
import { invoke } from './desktopInvoke';
import type { TaskPlanItem } from './types';

export interface CancelRunResponse {
  ok: boolean;
  run_id: string;
  status: string;
}

export const orchRunClient = {
  cancelRun(runId: string): Promise<CancelRunResponse> {
    return invoke<CancelRunResponse>('orchestration_cancel_run', { run_id: runId });
  },
  updatePlan(runId: string, plan: TaskPlanItem[]): Promise<{ ok: boolean }> {
    return invoke<{ ok: boolean }>('orchestration_update_plan', { run_id: runId, plan });
  },
  // B3 (2026-09-09): 单任务跳过 —— queued 短路 / running 软中断，其余子任务不受影响。
  // 409 = 任务不在本批或已终态；404 = run 不在活动注册表。
  cancelTask(runId: string, taskId: string): Promise<{ ok: boolean; task_id: string; status: string }> {
    return invoke('orchestration_cancel_run_task', { run_id: runId, task_id: taskId });
  },
  // Fix #3 (2026-09-06): 用户确认 → 唤醒 producer 启动 conductor 执行。
  confirmRun(runId: string): Promise<{ ok: boolean }> {
    return invoke<{ ok: boolean }>('orchestration_confirm_run', { run_id: runId });
  },
};
