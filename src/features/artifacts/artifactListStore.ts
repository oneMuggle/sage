// src/features/artifacts/artifactListStore.ts
//
// right-panel R1 批次 A: 产物列表从 useArtifacts 组件内 useState 上抬为
// zustand store —— 右侧面板（ArtifactsSection）与消息流内联产物卡片
// （MessageList）需要同一份列表；各自 fetch 会双倍请求且事件驱动刷新时
// 抖动两次。store 层做按会话缓存 + inflight 去重，useArtifacts 重写为
// 它的 hook 封装（对外 API 不变），刷新仍由 artifactEventsStore 的计数
// 变化驱动（S7 链路不变）。

import { create } from 'zustand';

import { listArtifacts, type Artifact } from './artifactApi';

interface ArtifactListState {
  bySession: Record<string, Artifact[]>;
  /** 拉取指定会话的产物列表（inflight 去重；失败保留旧值，与旧行为一致） */
  fetch: (sessionId: string) => Promise<void>;
  /** 会话删除时防泄漏 */
  clear: (sessionId: string) => void;
}

/** 模块级 inflight 表：同会话并发 fetch 合并为一次请求 */
const inflight = new Map<string, Promise<void>>();

export const useArtifactListStore = create<ArtifactListState>((set) => ({
  bySession: {},

  fetch: (sessionId) => {
    const existing = inflight.get(sessionId);
    if (existing) return existing;
    const task = listArtifacts(sessionId)
      .then((artifacts) => {
        set((prev) => ({ bySession: { ...prev.bySession, [sessionId]: artifacts } }));
      })
      .catch(() => {
        // 请求失败保留旧列表，不崩溃调用方（与旧 useArtifacts 行为一致）
      })
      .finally(() => {
        inflight.delete(sessionId);
      });
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
