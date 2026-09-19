// src/features/changes/changesListStore.ts
//
// right-panel R3 批次 C: 工作区变更列表从 ChangesSection 组件内 useState
// 上抬为 zustand store —— 面板 header 的"变更 (N)"计数徽标需要在变更
// Tab 未激活时也能拿到数据（组件只在激活时挂载），故全局缓存。
// 结构镜像 artifactListStore：按会话缓存 + inflight 去重。

import { create } from 'zustand';

import type { WorkspaceChanges } from '../../shared/api/workspaceApi';
import { workspaceApi } from '../../shared/api/workspaceApi';

interface ChangesListState {
  bySession: Record<string, WorkspaceChanges>;
  /** 每会话最近一次拉取的错误文案（友好化已在此层完成） */
  errors: Record<string, string | null>;
  loadingBy: Record<string, boolean>;
  fetch: (sessionId: string) => Promise<void>;
  clear: (sessionId: string) => void;
}

const inflight = new Map<string, Promise<void>>();

/** workspace_not_bound 错误 → 友好文案（与历史组件行为一致） */
function friendlyError(errMsg: string): string | null {
  if (errMsg.includes('workspace_not_bound') || errMsg.includes('尚未绑定工作区')) {
    return '当前会话尚未绑定工作区，无法查看变更';
  }
  return errMsg;
}

export const useChangesListStore = create<ChangesListState>((set) => ({
  bySession: {},
  errors: {},
  loadingBy: {},

  fetch: (sessionId) => {
    const existing = inflight.get(sessionId);
    if (existing) return existing;
    set((prev) => ({ loadingBy: { ...prev.loadingBy, [sessionId]: true } }));
    // async IIFE：workspaceApi.getChanges 缺失（测试部分 mock / 旧宿主）时
    // 同步抛错也进入统一错误通道，不会以 unhandled rejection 冒泡
    const task = (async () => {
      try {
        const changes = await workspaceApi.getChanges(sessionId);
        set((prev) => ({
          bySession: { ...prev.bySession, [sessionId]: changes },
          errors: { ...prev.errors, [sessionId]: null },
        }));
      } catch (e: unknown) {
        const errMsg = e instanceof Error ? e.message : String(e);
        set((prev) => ({
          errors: { ...prev.errors, [sessionId]: friendlyError(errMsg) },
        }));
      } finally {
        inflight.delete(sessionId);
        set((prev) => ({ loadingBy: { ...prev.loadingBy, [sessionId]: false } }));
      }
    })();
    inflight.set(sessionId, task);
    return task;
  },

  clear: (sessionId) =>
    set((prev) => {
      if (!(sessionId in prev.bySession)) return prev;
      const next = { ...prev.bySession };
      delete next[sessionId];
      return { bySession: next };
    }),
}));
