// src/features/artifacts/artifactEventsStore.ts
//
// S7 (2026-09-06): 产物创建事件计数 —— 事件驱动刷新的数据源。
//
// 链路：工具线程 record_artifact 落库 → artifact_repo 监听器广播 →
// 活跃 chat 流入队 `artifact_created` 事件 → useChat.onEvent 调
// bumpArtifactEvent(sessionId) → 本 store 计数 +1。
//
// 消费方：
// - useArtifacts: 订阅本 store，计数变化时重新拉取产物列表（此前只能
//   切会话或手动刷新，流式写文件后面板不更新）。
// - SessionItem（侧栏）: 计数 > 0 时显示产物徽章 📎N。
//
// 计数是"本次应用运行内"的累计值，不持久化 —— 侧栏徽章表达的是
// "这个会话刚产出了 N 个文件"的瞬时感知，权威列表始终以 REST 为准。

import { create } from 'zustand';

interface ArtifactEventsState {
  /** sessionId → 本次运行内产物创建事件计数 */
  counts: Record<string, number>;
  /** S7: artifact_created 事件到达（useChat.onEvent 调用） */
  bump: (sessionId: string) => void;
  /** 清空指定会话的计数（会话删除时防泄漏；一般无需手动调） */
  clear: (sessionId: string) => void;
}

export const useArtifactEventsStore = create<ArtifactEventsState>((set) => ({
  counts: {},
  bump: (sessionId) =>
    set((prev) => ({
      counts: { ...prev.counts, [sessionId]: (prev.counts[sessionId] ?? 0) + 1 },
    })),
  clear: (sessionId) =>
    set((prev) => {
      if (!(sessionId in prev.counts)) return prev;
      const next = { ...prev.counts };
      delete next[sessionId];
      return { counts: next };
    }),
}));

/** 非 hook 入口 —— useChat 的事件回调里直接调，避免引入 hook 依赖。 */
export function bumpArtifactEvent(sessionId: string): void {
  useArtifactEventsStore.getState().bump(sessionId);
}
