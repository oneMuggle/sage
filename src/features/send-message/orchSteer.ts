import { useRunControlStore } from '../../entities/orchestration/runControlStore';
import type { TaskSummary } from '../../shared/api/orchEvents';
import { orchRunControlClient } from '../../shared/api/orchRunControlClient';

const TERMINAL_TASK: ReadonlySet<TaskSummary['status']> = new Set([
  'succeeded',
  'completed',
  'failed',
  'cancelled',
]);
const TERMINAL_RUN: ReadonlySet<string> = new Set(['completed', 'failed', 'cancelled']);

/** 可接插话的 task：正在跑的优先，其次重试/等输入/等审批的，最后一条非终态兜底。 */
function pickSteerableTask(tasks: readonly TaskSummary[]): TaskSummary | null {
  return (
    tasks.find((t) => t.status === 'running') ??
    tasks.find(
      (t) =>
        t.status === 'retrying' || t.status === 'waiting_input' || t.status === 'waiting_approval',
    ) ??
    tasks.find((t) => !TERMINAL_TASK.has(t.status)) ??
    null
  );
}

/**
 * P2-c (2026-09-20): 编排 run 的插话通道。
 *
 * 编排模式下 chat 流没有可 steer 的单 agent run，转向入口一直是任务详情抽屉里
 * 的 ContextInput（要选 run + task + 类型 + 生效模式）。聊天框这条路径此前直接
 * 退化成排队，用户想插话必须先去开抽屉。这里按投递门面的语义补齐：拿当前 run 的
 * 活跃 task，以 `additional_context` / `next_boundary` 转达，与抽屉那条通道同一
 * 个后端端点。
 *
 * 失败（无快照、run/task 已终态、CAS revision 冲突、IPC 异常）一律返回 false，
 * 由调用方回退到排队 —— 插话失败不该丢消息。
 */
export async function steerActiveOrchTask(
  runId: string | null | undefined,
  content: string,
): Promise<boolean> {
  if (!runId) return false;
  const run = useRunControlStore.getState().runs.get(runId);
  if (!run || TERMINAL_RUN.has(run.status)) return false;
  const task = pickSteerableTask(run.tasks);
  if (!task) return false;
  try {
    await orchRunControlClient.steerTask({
      run_id: runId,
      task_id: task.task_id,
      message_type: 'additional_context',
      content,
      apply_mode: 'next_boundary',
      expected_task_revision: task.revision ?? 0,
    });
    return true;
  } catch {
    return false;
  }
}
