/**
 * 编排/任务板事件 → 会话槽位 store 的应用器（R35）。
 *
 * 从 useChat 的事件分支中抽取：task_plan / task_status / task_progress /
 * task_review / subagent_event / approval_mode / todo_snapshot /
 * artifact_created 八类事件的 store 写入逻辑两条路径共用——
 * 主聊天路径（sendMessage）与重接路径（reattachActiveStream），
 * 保证重接重放时编排任务板能完整重建。
 *
 * 返回 true 表示事件已被本函数消费（调用方可 return）。
 */

import type { OrchRunDetail } from '../../shared/api/orchRunClient';
import type { AgentEvent } from '../../shared/api/types';
import type {
  SubagentLiveEvent,
  TaskProgressEvent,
  TaskReviewEvent,
  TaskStatusEvent,
} from '../../shared/api/types';
import { bumpArtifactEvent } from '../artifacts/artifactEventsStore';
import { useChangesListStore } from '../changes/changesListStore';
import { maybeAutoOpenArtifactPanel } from '../right-panel/rightPanelStore';

import { mergeLiveEvent, useChatStreamStore } from './chatStreamStore';
import type { TaskBoardState } from './chatStreamStore';

export function applyOrchestrationEventToBoard(evt: AgentEvent, sid: string): boolean {
  const board = useChatStreamStore.getState();

  // S7: 产物事件 → 计数 store。
  // right-panel R1 批次 B: 当前查看的会话产出产物且面板关着时自动展开
  // （对齐 Claude artifacts；Bell 开关可关；后台会话不打扰，只走侧栏 📎N）。
  if (evt.state === 'artifact_created' && evt.artifact) {
    bumpArtifactEvent(sid);
    maybeAutoOpenArtifactPanel(sid);
    return true;
  }

  // Round 3 (2026-09-19): 编排拆解前置进度（需求澄清/事实侦察）——先于
  // task_plan 到达时任务板尚不存在，写独立槽位供指示条消费。
  if (evt.state === 'orch_preflight' && evt.preflight_phase) {
    board.setPreflightPhase(sid, evt.preflight_phase);
    return true;
  }

  // right-panel R5: 写文件工具落盘 → 变更列表防抖刷新（徽标实时化，
  // 不再依赖手动刷新/重进面板）。防抖合并一轮连续写入的多条事件。
  if (evt.state === 'workspace_changed') {
    useChangesListStore.getState().fetchDebounced(sid);
    return true;
  }

  // Multi-Agent Orchestration: task_plan → 初始化编排任务板。
  if (evt.state === 'task_plan' && evt.run_id && evt.plan) {
    // 前置阶段结束（进入确认/执行阶段）——清掉指示。
    board.setPreflightPhase(sid, null);
    board.setTaskBoard(sid, {
      runId: evt.run_id,
      plan: evt.plan,
      statuses: {},
      live: {},
    });
    return true;
  }


  // task_status → 按 run_id 匹配合并 + 重算 progress 5 元组。
  if (evt.state === 'task_status' && evt.run_id && evt.task_id) {
    const runId = evt.run_id;
    const taskId = evt.task_id;
    board.updateTaskBoard(sid, runId, (prev) => {
      if (!prev || prev.runId !== runId) return prev;
      // BU15 (round29): running 行实时计时 —— 前端 ingestion 打点
      // （后端事件不含 started_at）；终态事件整体替换后自然消失。
      const incoming = evt as TaskStatusEvent;
      const nextStatuses = {
        ...prev.statuses,
        [taskId]:
          incoming.status === 'running'
            ? { ...incoming, runningSince: Date.now() }
            : incoming,
      };
      const counts = { done: 0, running: 0, queued: 0, failed: 0, cancelled: 0 };
      for (const st of Object.values(nextStatuses)) {
        if (st.status === 'done') counts.done++;
        else if (st.status === 'running') counts.running++;
        else if (st.status === 'queued') counts.queued++;
        else if (st.status === 'failed') counts.failed++;
        else if (st.status === 'cancelled') counts.cancelled++;
      }
      const total = Math.max(prev.progress?.total ?? 0, Object.keys(nextStatuses).length);
      return {
        ...prev,
        statuses: nextStatuses,
        progress: { total, ...counts },
        // P1-5: 首个 task_status = 派发已开始。
        dispatchedAt: prev.dispatchedAt ?? Date.now(),
      };
    });
    return true;
  }

  // task_progress 整盘概览。
  if (evt.state === 'task_progress' && evt.run_id) {
    const runId = evt.run_id;
    const tp = evt as TaskProgressEvent;
    board.updateTaskBoard(sid, runId, (prev) =>
      prev && prev.runId === runId
        ? {
            ...prev,
            progress: {
              total: tp.total ?? 0,
              done: tp.done ?? 0,
              running: tp.running ?? 0,
              queued: tp.queued ?? 0,
              failed: tp.failed ?? 0,
              cancelled: tp.cancelled ?? 0,
            },
          }
        : prev,
    );
    return true;
  }

  // task_review → 复核结论横幅。
  if (evt.state === 'task_review' && evt.run_id) {
    const runId = evt.run_id;
    const review = evt as TaskReviewEvent;
    board.updateTaskBoard(sid, runId, (prev) =>
      prev && prev.runId === runId ? { ...prev, review } : prev,
    );
    return true;
  }

  // subagent_event 镜像 → 任务板 live 态（含轻量合成板）。
  if (evt.state === 'subagent_event' && evt.run_id && evt.task_id) {
    const runId = evt.run_id;
    const taskId = evt.task_id;
    const liveEvent = evt as SubagentLiveEvent;
    board.updateTaskBoard(sid, runId, (prev) => {
      if (!prev || prev.runId !== runId) {
        // 编排板（orch-*）不可被 agent-* 事件替换；agent 临时板允许接管。
        if (!prev || prev.runId.startsWith('agent-')) {
          return {
            runId,
            plan: [
              {
                task_id: taskId,
                agent_id: evt.agent_id ?? 'subagent',
                goal: evt.goal ?? '',
              },
            ],
            statuses: {},
            live: {
              [taskId]: mergeLiveEvent(undefined, liveEvent),
            },
          };
        }
        return prev;
      }
      return {
        ...prev,
        live: {
          ...(prev.live ?? {}),
          [taskId]: mergeLiveEvent(prev.live?.[taskId], liveEvent),
        },
      };
    });
    return true;
  }

  // approval_mode 切换回显。
  if (evt.state === 'approval_mode' && evt.run_id) {
    const runId = evt.run_id;
    const mode = evt.mode === 'auto' ? 'auto' : 'ask';
    board.updateTaskBoard(sid, runId, (prev) =>
      prev && prev.runId === runId ? { ...prev, approvalMode: mode } : prev,
    );
    return true;
  }

  // todo 快照。
  if (evt.state === 'todo_snapshot' && Array.isArray(evt.todos)) {
    board.setTodos(sid, evt.todos);
    return true;
  }

  // Task 11 (2026-09-17): topic_shifted 横幅态 — 写入 shiftInfo
  // 由 Chat.tsx 渲染 TopicShiftBanner;banner 自身持有可见性计时。
  if (evt.state === 'topic_shifted') {
    const segId = typeof evt.segment_id === 'number' ? evt.segment_id : 0;
    const reason = typeof evt.reason === 'string' ? evt.reason : '';
    board.setShiftInfo(sid, { segmentId: segId, reason, createdAt: Date.now() });
    return true;
  }

  return false;
}


// RD20 (round43): 历史编排 run → 任务板恢复（纯函数，供 Chat 会话切换时
// 调用）。RT24 字段 used_tokens/duration_ms 一并映射；endedAt 取任务最大
// finished_at（无终态任务时为 null）。无任务返回 null。
export function restoreRunToBoard(
  run: OrchRunDetail,
): {
  plan: TaskBoardState['plan'];
  statuses: TaskBoardState['statuses'];
  progress: TaskBoardState['progress'];
  dispatchedAt: number;
  endedAt: number | null;
} | null {
  if (run.tasks.length === 0) return null;
  type PlanItem = TaskBoardState['plan'][number];
  const plan = run.plan as unknown as PlanItem[];
  const statuses: TaskBoardState['statuses'] = {};
  const progress = { total: 0, done: 0, running: 0, queued: 0, failed: 0, cancelled: 0 };
  progress.total = run.tasks.length;
  let endedAt: number | null = null;
  for (const task of run.tasks) {
    const status = String(task.status ?? 'queued');
    const taskId = String(task.task_id);
    statuses[taskId] = {
      state: 'task_status',
      run_id: run.run_id,
      task_id: taskId,
      status: status as TaskBoardState['statuses'][string]['status'],
      agent_id: String(task.agent_id ?? ''),
      goal: String(task.goal ?? ''),
      error: (task.error as string | null) ?? null,
      output_preview: (task.output_preview as string | null) ?? null,
      retry_count: (task.retry_count as number) ?? 0,
      // RT24 (round32): 历史回看携带任务级用量/时长。
      used_tokens: (task.used_tokens as number | undefined) ?? undefined,
      duration_ms: (task.duration_ms as number | undefined) ?? undefined,
      // RT26 (round49): 历史回看携带重派来源（恢复"重派"徽章）。
      retry_of: (task.retry_of as string | undefined) ?? undefined,
    };
    if (status in progress) progress[status as keyof typeof progress] += 1;
    const finished = Number(task.finished_at ?? 0);
    if (finished > (endedAt ?? 0)) endedAt = finished;
  }
  // 动态加任务的 run 可能 plan_json 为空 —— 从任务行反推 plan 保证任务树可渲染
  const effPlan: PlanItem[] =
    plan.length > 0
      ? plan
      : run.tasks.map((task) => ({
          task_id: String(task.task_id),
          agent_id: String(task.agent_id ?? ''),
          goal: String(task.goal ?? ''),
        }));
  return {
    plan: effPlan,
    statuses,
    progress,
    dispatchedAt: run.created_at,
    endedAt,
  };
}
