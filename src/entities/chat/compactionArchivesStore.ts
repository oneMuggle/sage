import { create } from 'zustand';

/**
 * 压缩归档打开请求 — 让消息内的 CompactBanner 可以打开 Chat 页的
 * ArchivesModal，而不必把回调从 MessageList 一路 prop-drill 到 Message。
 *
 * 流转：CompactBanner 调 requestOpen(sessionId) → Chat 订阅 pendingSessionId，
 * 与当前会话匹配时打开 ArchivesModal 并 consume() 清空请求。
 */
export interface CompactionArchivesState {
  pendingSessionId: string | null;
  requestOpen: (sessionId: string) => void;
  consume: () => void;
}

export const useCompactionArchives = create<CompactionArchivesState>((set) => ({
  pendingSessionId: null,
  requestOpen: (sessionId) => set({ pendingSessionId: sessionId }),
  consume: () => set({ pendingSessionId: null }),
}));
