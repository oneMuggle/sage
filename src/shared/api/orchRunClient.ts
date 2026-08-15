// src/shared/api/orchRunClient.ts
/**
 * 编排 run 生命周期客户端 —— 历史列表 / 详情 / 恢复 / plan 更新。
 * 与 orchestrationClient.ts（lane 维度：create_lane/list_lanes）互补,
 * 本客户端面向 run 维度（Wave 2 P1-4 持久化的 /api/v1/orch/runs 4 端点）。
 */
import { invoke } from './desktopInvoke';
import type { TaskPlanItem } from './types';

export interface OrchRunSummary {
  run_id: string;
  session_id: string;
  status: string;
  created_at: number;
  final_summary?: string;
}

export interface OrchRunDetail {
  run_id: string;
  session_id: string;
  status: string;
  created_at: number;
  plan: TaskPlanItem[];
  tasks: Array<Record<string, unknown>>;
  /** 原始用户请求 —— 恢复流（PR C C5）逐字回填依赖它。 */
  original_request?: string;
}

export interface ResumeResponse {
  ok: boolean;
  new_run_id: string;
  session_id: string;
  plan: TaskPlanItem[];
  /** 原始用户请求（旧库 NULL 行可能缺失,故 optional）。 */
  original_request?: string;
}

export interface CancelRunResponse {
  ok: boolean;
  run_id: string;
  status: string;
}

export const orchRunClient = {
  listRuns(limit = 50): Promise<OrchRunSummary[]> {
    return invoke<OrchRunSummary[]>('orchestration_list_runs', { params: { limit } });
  },
  getRun(runId: string): Promise<OrchRunDetail> {
    return invoke<OrchRunDetail>('orchestration_get_run', { run_id: runId });
  },
  resumeRun(runId: string): Promise<ResumeResponse> {
    return invoke<ResumeResponse>('orchestration_resume_run', { run_id: runId });
  },
  cancelRun(runId: string): Promise<CancelRunResponse> {
    return invoke<CancelRunResponse>('orchestration_cancel_run', { run_id: runId });
  },
  updatePlan(runId: string, plan: TaskPlanItem[]): Promise<{ ok: boolean }> {
    return invoke<{ ok: boolean }>('orchestration_update_plan', { run_id: runId, plan });
  },
};
