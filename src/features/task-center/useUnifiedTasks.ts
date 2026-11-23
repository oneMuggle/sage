/**
 * 订阅六个 Zustand store，归一合并为一份任务列表并按状态分组。
 * 每个挂载点各自执行 memo 计算；另用 ref + useEffect 维护后台会话首见时间。
 */
import { useEffect, useMemo, useRef } from 'react';

import { useLaneBoardStore } from '../../entities/orchestration/laneBoardStore';
import { useRunDirectoryStore } from '../../entities/orchestration/runDirectoryStore';
import { useStore } from '../../shared/lib/store';
import { useChatStreamStore } from '../send-message/chatStreamStore';

import { useTaskCenterStore } from './taskCenterStore';
import type { UnifiedTaskEntry } from './unifiedTaskModel';
import {
  compareUnifiedTasks,
  isTerminalStatus,
  mergeSubagentEntries,
  normalizeCanonicalRun,
  normalizeCanonicalTask,
  normalizeChatTask,
  normalizeGoalTask,
  normalizeLaneTask,
  normalizeRegistryTask,
  normalizeScheduledTask,
  normalizeSubagentTask,
  normalizeTodoTask,
} from './unifiedTaskModel';
import { useUnifiedTaskStore } from './unifiedTaskStore';

export interface UnifiedTaskGroups {
  active: UnifiedTaskEntry[];
  failed: UnifiedTaskEntry[];
  finished: UnifiedTaskEntry[];
}

export interface UnifiedTasksResult {
  groups: UnifiedTaskGroups;
  all: UnifiedTaskEntry[];
  /** 进行中 + 失败，用于 rail 角标 */
  attentionCount: number;
  loading: boolean;
  error: string | null;
}

const ACTIVE_STATUSES = new Set(['queued', 'running', 'paused', 'awaiting_approval']);

export function useUnifiedTasks(): UnifiedTasksResult {
  const registryTasks = useTaskCenterStore((s) => s.tasks);
  const streamSessions = useChatStreamStore((s) => s.sessions);
  const lanes = useLaneBoardStore((s) => s.lanes);
  const directoryRuns = useRunDirectoryStore((s) => s.runs);
  const sessions = useStore((s) => s.sessions);
  const currentSessionId = useStore((s) => s.currentSessionId);

  const goals = useUnifiedTaskStore((s) => s.goals);
  const todos = useUnifiedTaskStore((s) => s.todos);
  const scheduledTasks = useUnifiedTaskStore((s) => s.scheduledTasks);
  const loading = useUnifiedTaskStore((s) => s.loading);
  const error = useUnifiedTaskStore((s) => s.error);

  // chat 首见时间：沿用历史 streamStartsRef 约定（原胶囊 → 现侧边栏任务中心）
  const streamStartsRef = useRef<Map<string, number>>(new Map());

  const activeStreamIds = useMemo(
    () =>
      Object.entries(streamSessions)
        .filter(([, slots]) => slots.streaming != null)
        .map(([id]) => id)
        .filter((id) => id !== currentSessionId),
    [streamSessions, currentSessionId],
  );

  // 维护首见时间：进入即记，退出即删
  useEffect(() => {
    const map = streamStartsRef.current;
    const now = Date.now();
    for (const id of activeStreamIds) {
      if (!map.has(id)) map.set(id, now);
    }
    for (const id of [...map.keys()]) {
      if (!activeStreamIds.includes(id)) map.delete(id);
    }
  }, [activeStreamIds]);

  const sessionTitle = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of sessions) map.set(s.id, s.title ?? s.id);
    return map;
  }, [sessions]);

  const all = useMemo<UnifiedTaskEntry[]>(() => {
    const starts = streamStartsRef.current;
    const entries: UnifiedTaskEntry[] = [];

    for (const t of Object.values(registryTasks)) entries.push(normalizeRegistryTask(t));

    for (const id of activeStreamIds) {
      entries.push(
        normalizeChatTask({
          sessionId: id,
          title: sessionTitle.get(id) ?? id,
          firstSeenAt: starts.get(id) ?? Date.now(),
        }),
      );
    }

    // M4.2: canonical run 目录 → 子任务行 + run 兜底行。会话从未在本窗口
    // 加载过（或跨窗口运行）时，内存 taskBoard 缺失，这里是唯一可见来源。
    const canonicalById = new Map<string, UnifiedTaskEntry>();
    const canonicalRunEntries: UnifiedTaskEntry[] = [];
    for (const run of directoryRuns) {
      const title = sessionTitle.get(run.session_id) ?? run.session_id;
      for (const task of run.tasks) {
        const entry = normalizeCanonicalTask(run, task, title);
        if (entry) canonicalById.set(entry.id, entry);
      }
      const runEntry = normalizeCanonicalRun(run);
      if (runEntry) canonicalRunEntries.push(runEntry);
    }

    // M2.4: 编排任务板子任务 → 任务中心条目的（活跃/失败），
    // 由 TaskCenter 直接"打开子代理线程"（定位到任务详情）。
    // M4.2: 同 id 的 canonical 行在此合并 —— canonical 定状态，内存补
    // liveStep / 待审批 / 真实会话标题。
    for (const [sid, slots] of Object.entries(streamSessions)) {
      const board = slots.taskBoard;
      if (!board) continue;
      const title = sessionTitle.get(sid) ?? sid;
      const planById = new Map(board.plan.map((p) => [p.task_id, p]));
      for (const [taskId, status] of Object.entries(board.statuses ?? {})) {
        const planItem = planById.get(taskId);
        const live = board.live?.[taskId];
        const entry = normalizeSubagentTask({
          sessionId: sid,
          sessionTitle: title,
          runId: board.runId,
          taskId,
          agentId: status.agent_id || planItem?.agent_id || 'agent',
          goal: status.goal || planItem?.goal || taskId,
          status: status.status,
          liveStep: live?.liveStep ?? null,
          waitingApproval: live?.waitingApproval ?? null,
          startedAt: status.runningSince ?? null,
          error: status.error ?? null,
        });
        if (!entry) continue;
        const canonical = canonicalById.get(entry.id);
        if (canonical) {
          canonicalById.delete(entry.id);
          entries.push(mergeSubagentEntries(canonical, entry));
        } else {
          entries.push(entry);
        }
      }
    }
    for (const entry of canonicalById.values()) entries.push(entry);
    for (const entry of canonicalRunEntries) entries.push(entry);

    for (const lane of lanes) {
      const e = normalizeLaneTask(lane);
      if (e) entries.push(e);
    }

    for (const goal of goals) {
      const e = normalizeGoalTask(goal);
      if (e) entries.push(e);
    }

    for (const todo of todos) {
      const e = normalizeTodoTask(todo);
      if (e) entries.push(e);
    }

    for (const task of scheduledTasks) {
      const e = normalizeScheduledTask(task);
      if (e) entries.push(e);
    }

    return entries.sort(compareUnifiedTasks);
  }, [
    registryTasks,
    activeStreamIds,
    sessionTitle,
    lanes,
    goals,
    todos,
    scheduledTasks,
    streamSessions,
    directoryRuns,
  ]);

  const groups = useMemo<UnifiedTaskGroups>(() => {
    const active: UnifiedTaskEntry[] = [];
    const failed: UnifiedTaskEntry[] = [];
    const finished: UnifiedTaskEntry[] = [];
    for (const e of all) {
      if (e.status === 'failed') failed.push(e);
      else if (ACTIVE_STATUSES.has(e.status)) active.push(e);
      else if (isTerminalStatus(e.status)) finished.push(e);
    }
    return { active, failed, finished };
  }, [all]);

  return {
    groups,
    all,
    attentionCount: groups.active.length + groups.failed.length,
    loading,
    error,
  };
}
