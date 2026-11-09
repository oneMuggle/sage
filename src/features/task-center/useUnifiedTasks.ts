// src/features/task-center/useUnifiedTasks.ts
//
// 纯读取 hook：六个 store → 一份归一列表。无副作用、无请求，
// 侧边栏分区与 /tasks 页面同时挂载也只做一次 useMemo 计算。
import { useEffect, useMemo, useRef } from 'react';

import { useLaneBoardStore } from '../../entities/orchestration/laneBoardStore';
import { useStore } from '../../shared/lib/store';
import { useChatStreamStore } from '../send-message/chatStreamStore';

import { useTaskCenterStore } from './taskCenterStore';
import type { UnifiedTaskEntry } from './unifiedTaskModel';
import {
  compareUnifiedTasks,
  isTerminalStatus,
  normalizeChatTask,
  normalizeGoalTask,
  normalizeLaneTask,
  normalizeRegistryTask,
  normalizeScheduledTask,
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
  /** 纯 running 数 */
  runningCount: number;
  loading: boolean;
  error: string | null;
}

const ACTIVE_STATUSES = new Set(['queued', 'running', 'paused', 'awaiting_approval']);

export function useUnifiedTasks(): UnifiedTasksResult {
  const registryTasks = useTaskCenterStore((s) => s.tasks);
  const streamSessions = useChatStreamStore((s) => s.sessions);
  const lanes = useLaneBoardStore((s) => s.lanes);
  const sessions = useStore((s) => s.sessions);
  const currentSessionId = useStore((s) => s.currentSessionId);

  const goals = useUnifiedTaskStore((s) => s.goals);
  const todos = useUnifiedTaskStore((s) => s.todos);
  const scheduledTasks = useUnifiedTaskStore((s) => s.scheduledTasks);
  const loading = useUnifiedTaskStore((s) => s.loading);
  const error = useUnifiedTaskStore((s) => s.error);

  // chat 首见时间：沿用 TaskCenterWidget 的 streamStartsRef 约定
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
  }, [registryTasks, activeStreamIds, sessionTitle, lanes, goals, todos, scheduledTasks]);

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
    runningCount: all.filter((e) => e.status === 'running').length,
    loading,
    error,
  };
}
