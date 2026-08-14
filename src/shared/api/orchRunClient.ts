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
}

export interface ResumeResponse {
  ok: boolean;
  new_run_id: string;
  session_id: string;
  plan: TaskPlanItem[];
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
  updatePlan(runId: string, plan: TaskPlanItem[]): Promise<{ ok: boolean }> {
    return invoke<{ ok: boolean }>('orchestration_update_plan', { run_id: runId, plan });
  },
};
