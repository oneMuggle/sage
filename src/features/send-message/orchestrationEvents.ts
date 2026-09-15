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

import type { AgentEvent } from '../../shared/api/types';
import type {
  SubagentLiveEvent,
  TaskProgressEvent,
  TaskReviewEvent,
  TaskStatusEvent,
} from '../../shared/api/types';
import { bumpArtifactEvent } from '../artifacts/artifactEventsStore';

import {
  mergeLiveEvent,
  useChatStreamStore,
} from './chatStreamStore';

export function applyOrchestrationEventToBoard(evt: AgentEvent, sid: string): boolean {
  const board = useChatStreamStore.getState();

  // S7: 产物事件 → 计数 store。
  if (evt.state === 'artifact_created' && evt.artifact) {
    bumpArtifactEvent(sid);
    return true;
  }

  // Multi-Agent Orchestration: task_plan → 初始化编排任务板。
  if (evt.state === 'task_plan' && evt.run_id && evt.plan) {
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
      const nextStatuses = {
        ...prev.statuses,
        [taskId]: evt as TaskStatusEvent,
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

  return false;
}
