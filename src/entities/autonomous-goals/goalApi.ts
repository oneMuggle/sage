/**
 * 闲时自主目标执行系统 — API 客户端
 *
 * 通过 Electron IPC relay (backendRequest) 调用后端 REST API。
 */
import { backendRequest } from '../../shared/api/backendRequest';

import type {
  CreateGoalInput,
  ExecutionReport,
  GenerateCheckpointsResponse,
  Goal,
  GoalListResponse,
  GoalStatus,
  UpdateGoalInput,
} from './types';

const BASE = '/api/v1/goals';

/** 列出目标（可按状态过滤） */
export async function listGoals(
  status?: GoalStatus,
  limit = 50,
  offset = 0,
): Promise<GoalListResponse> {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  params.set('limit', String(limit));
  params.set('offset', String(offset));

  return backendRequest<GoalListResponse>({
    method: 'GET',
    path: `${BASE}?${params.toString()}`,
  });
}

/** 创建目标 */
export async function createGoal(input: CreateGoalInput): Promise<Goal> {
  return backendRequest<Goal>({
    method: 'POST',
    path: BASE,
    body: input,
  });
}

/** 获取目标详情 */
export async function getGoal(goalId: string): Promise<Goal> {
  return backendRequest<Goal>({
    method: 'GET',
    path: `${BASE}/${goalId}`,
  });
}

/** 更新目标 */
export async function updateGoal(goalId: string, input: UpdateGoalInput): Promise<Goal> {
  return backendRequest<Goal>({
    method: 'PUT',
    path: `${BASE}/${goalId}`,
    body: input,
  });
}

/** 删除目标 */
export async function deleteGoal(goalId: string): Promise<void> {
  await backendRequest<void>({
    method: 'DELETE',
    path: `${BASE}/${goalId}`,
  });
}

/** 启动目标执行 */
export async function startGoal(goalId: string): Promise<Goal> {
  return backendRequest<Goal>({
    method: 'POST',
    path: `${BASE}/${goalId}/start`,
  });
}

/** 暂停目标执行 */
export async function pauseGoal(goalId: string): Promise<Goal> {
  return backendRequest<Goal>({
    method: 'POST',
    path: `${BASE}/${goalId}/pause`,
  });
}

/** 取消目标执行 */
export async function cancelGoal(goalId: string): Promise<Goal> {
  return backendRequest<Goal>({
    method: 'POST',
    path: `${BASE}/${goalId}/cancel`,
  });
}

/** 获取执行报告 */
export async function getExecutionReport(goalId: string): Promise<ExecutionReport> {
  return backendRequest<ExecutionReport>({
    method: 'GET',
    path: `${BASE}/${goalId}/report`,
  });
}

/** 使用 LLM 生成检查点 */
export async function generateCheckpoints(goalId: string): Promise<GenerateCheckpointsResponse> {
  return backendRequest<GenerateCheckpointsResponse>({
    method: 'POST',
    path: `${BASE}/${goalId}/generate-checkpoints`,
  });
}

export function formatGoalListQuerySummary(
  status?: GoalStatus,
  limit = 50,
  offset = 0,
): string {
  return `path=${BASE} · status=${status ?? 'all'} · limit=${limit} · offset=${offset}`;
}

export function formatGoalListQueryJson(
  status?: GoalStatus,
  limit = 50,
  offset = 0,
): string {
  return JSON.stringify(
    {
      basePath: BASE,
      status: status ?? null,
      limit,
      offset,
    },
    null,
    2,
  );
}
