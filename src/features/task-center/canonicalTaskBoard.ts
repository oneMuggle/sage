/**
 * M4.2 (2026-11-23): 用 canonical run 目录合成右栏兜底任务板。
 *
 * 内存 taskBoard 缺失时（会话从未在本窗口加载 / run 在另一窗口运行），
 * 右栏进度、任务树与计划卡没有数据。这里把 ``DirectoryRun`` 投影为
 * ``TaskBoardState``：计划任务 + 每任务状态 + 计数齐备，live 实时细节
 * 仍由后续 canonical 事件流补齐（事件订阅使用合成板的 runId）。
 *
 * 只读投影，不写回 chatStreamStore —— 内存 taskBoard 一旦出现即优先。
 */
import type { DirectoryRun } from '../../shared/api/orchRunClient';
import type { TaskPlanItem, TaskStatusEvent } from '../../shared/api/types/chatAndEventTypes';
import type { TaskBoardState } from '../send-message/chatStreamStore';

/** plan_json 损坏（plan 为空）时用子任务行兜底，保证任务树不空。 */
function planFromRun(run: DirectoryRun): TaskPlanItem[] {
  if (run.plan.length > 0) return run.plan;
  return run.tasks.map((task) => ({
    task_id: task.task_id,
    agent_id: task.agent_id,
    goal: task.goal,
    parent_task_id: task.parent_task_id,
    depth: task.depth,
  }));
}

function summarizeProgress(run: DirectoryRun): NonNullable<TaskBoardState['progress']> {
  let done = 0;
  let running = 0;
  let queued = 0;
  let failed = 0;
  let cancelled = 0;
  let skipped = 0;
  for (const task of run.tasks) {
    switch (task.status) {
      case 'done':
        done += 1;
        break;
      case 'running':
        running += 1;
        break;
      case 'queued':
        queued += 1;
        break;
      case 'paused':
        // 暂停任务在计数里仍算"未完成"，归入 queued 保持旧事件口径。
        queued += 1;
        break;
      case 'failed':
        failed += 1;
        break;
      case 'cancelled':
        cancelled += 1;
        break;
      case 'skipped':
        skipped += 1;
        break;
    }
  }
  return {
    total: run.tasks.length,
    done,
    running,
    queued,
    failed,
    cancelled,
    skipped,
  };
}

export function buildCanonicalTaskBoard(run: DirectoryRun): TaskBoardState {
  const statuses: Record<string, TaskStatusEvent> = {};
  for (const task of run.tasks) {
    statuses[task.task_id] = {
      state: 'task_status',
      run_id: run.run_id,
      task_id: task.task_id,
      status: task.status,
      agent_id: task.agent_id,
      goal: task.goal,
      error: task.error,
      output_preview: task.output_preview,
      retry_count: task.retry_count,
      retry_of: task.retry_of ?? undefined,
      used_tokens: task.used_tokens ?? undefined,
      duration_ms: task.duration_ms ?? undefined,
      parent_task_id: task.parent_task_id,
      depth: task.depth,
    };
  }
  const plan = planFromRun(run);
  // 已确认但任务行尚未落库的短暂窗口：计划里的任务按 queued 呈现，
  // 与内存 reducer 收到 task_plan 时的初始态一致（避免空行/未知状态）。
  for (const item of plan) {
    if (statuses[item.task_id]) continue;
    statuses[item.task_id] = {
      state: 'task_status',
      run_id: run.run_id,
      task_id: item.task_id,
      status: 'queued',
      agent_id: item.agent_id,
      goal: item.goal,
      error: null,
      output_preview: null,
      parent_task_id: item.parent_task_id ?? null,
      depth: item.depth ?? 0,
    };
  }
  return {
    runId: run.run_id,
    plan,
    statuses,
    progress: summarizeProgress(run),
    dispatchedAt: run.dispatched_at,
    confirmedAt: run.confirmed_at,
  };
}
