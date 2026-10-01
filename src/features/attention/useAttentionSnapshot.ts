// src/features/attention/useAttentionSnapshot.ts
//
// UX-IA R3 批次 D（数据层）：把注意力来源接到各自的 store 上。
//
// 与 attentionCenter.ts 的分工：那里是纯聚合（可单测），这里是订阅层。
// 两条纪律：
// 1. **只读不加载**。本 hook 不调用任何 load()/fetch —— 待办与定时任务的
//    拉取由各自整页负责（todoStore.load 的调用方是 TodoPage，scheduled 的
//    是 ScheduledTasks）。这里若顺手 load，等于把侧栏又绑回数据加载，
//    正是批次 0 刚解开的耦合。
// 2. **选择器返回原始值**。zustand 的选择器返回新对象会在每次渲染都判定为
//    变化并触发死循环，因此下面一律返回 number。
import { useMemo } from 'react';

import { usePermissionState } from '../../entities/permission/permissionState';
import { useQuestionState } from '../../entities/question/questionState';
import { useTodoStore } from '../../entities/todo/todoStore';
import type { Todo } from '../../shared/api/types';
import type { WorkspaceChanges } from '../../shared/api/workspaceApi';
import { useChangesListStore } from '../changes/changesListStore';

import { aggregateAttention, type AttentionSnapshot } from './attentionCenter';

/** 与被删的 TodoSection 口径一致：pending 与 in_progress 都算"待办"。 */
export function countPendingTodos(todos: readonly Todo[] | undefined): number {
  if (!todos) return 0;
  return todos.filter((t) => t.status === 'pending' || t.status === 'in_progress').length;
}

/** 工作区有未提交改动时返回涉及的文件数；干净或未拉取返回 0。 */
export function countDirtyFiles(changes: WorkspaceChanges | undefined): number {
  if (!changes || changes.clean) return 0;
  return changes.changes.length;
}

export interface UseAttentionOptions {
  /** 未读产物是"按会话已见基线"计算的，判定逻辑在 rightPanelStore 侧，故由调用方传入 */
  unseenArtifacts?: number;
  /** 变更列表按会话缓存，需会话 id 才能取到当前工作区的状态 */
  sessionId?: string | null;
}

export function useAttentionSnapshot(options: UseAttentionOptions = {}): AttentionSnapshot {
  const { unseenArtifacts = 0, sessionId = null } = options;

  const approvals = usePermissionState((s) => (s.currentRequest != null ? 1 : 0));
  const questions = useQuestionState((s) => (s.currentQuestion != null ? 1 : 0));
  const todos = useTodoStore((s) => countPendingTodos(s.todos));
  const dirty = useChangesListStore((s) => (sessionId ? countDirtyFiles(s.bySession[sessionId]) : 0));

  return useMemo(
    () =>
      aggregateAttention({
        pendingApprovals: approvals,
        pendingQuestions: questions,
        unseenArtifacts,
        pendingTodos: todos,
        dirtyFiles: dirty,
      }),
    [approvals, dirty, questions, todos, unseenArtifacts],
  );
}
