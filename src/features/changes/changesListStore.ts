// src/features/changes/changesListStore.ts
//
// right-panel R3 批次 C: 工作区变更列表从 ChangesSection 组件内 useState
// 上抬为 zustand store —— 面板 header 的"变更 (N)"计数徽标需要在变更
// Tab 未激活时也能拿到数据（组件只在激活时挂载），故全局缓存。
// 结构镜像 artifactListStore：按会话缓存 + inflight 去重。
//
// right-panel R5: fetchDebounced —— workspace_changed 事件（写文件工具
// 落盘）触发的防抖刷新。一次 apply_patch 会连续到达多条事件，逐条
// refetch 纯属浪费；800ms 尾沿防抖把一轮写入合并为一次 git status。

import { create } from 'zustand';

import type { WorkspaceChanges } from '../../shared/api/workspaceApi';
import { workspaceApi } from '../../shared/api/workspaceApi';

/** workspace_changed 连续到达时的尾沿防抖窗口（毫秒） */
export const CHANGES_FETCH_DEBOUNCE_MS = 800;

interface ChangesListState {
  bySession: Record<string, WorkspaceChanges>;
  /** 每会话最近一次拉取的错误文案（友好化已在此层完成） */
  errors: Record<string, string | null>;
  loadingBy: Record<string, boolean>;
  fetch: (sessionId: string) => Promise<void>;
  /** 事件驱动刷新入口：尾沿防抖后 fetch（workspace_changed 高频到达时合并） */
  fetchDebounced: (sessionId: string) => void;
  clear: (sessionId: string) => void;
}

const inflight = new Map<string, Promise<void>>();
const debounceTimers = new Map<string, ReturnType<typeof setTimeout>>();

/** workspace_not_bound 错误 → 友好文案（与历史组件行为一致） */
function friendlyError(errMsg: string): string | null {
  if (errMsg.includes('workspace_not_bound') || errMsg.includes('尚未绑定工作区')) {
    return '当前会话尚未绑定工作区，无法查看变更';
  }
  return errMsg;
}

export const useChangesListStore = create<ChangesListState>((set, get) => ({
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

  fetchDebounced: (sessionId) => {
    const existing = debounceTimers.get(sessionId);
    if (existing) clearTimeout(existing);
    const timer = setTimeout(() => {
      debounceTimers.delete(sessionId);
      void get().fetch(sessionId);
    }, CHANGES_FETCH_DEBOUNCE_MS);
    debounceTimers.set(sessionId, timer);
  },

  clear: (sessionId) => {
    // 会话已销毁，挂起的防抖刷新一并取消（避免 clear 后又拉一次）
    const pendingTimer = debounceTimers.get(sessionId);
    if (pendingTimer) {
      clearTimeout(pendingTimer);
      debounceTimers.delete(sessionId);
    }
    set((prev) => {
      if (!(sessionId in prev.bySession)) return prev;
      const next = { ...prev.bySession };
      delete next[sessionId];
      return { bySession: next };
    });
  },
}));
