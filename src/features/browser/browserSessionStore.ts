/**
 * 受控浏览器会话记忆（C2）。
 *
 * 浏览器步骤的 `browser_meta.session_id` 只存在于工具结果里；一轮 stream
 * 结束（`finishStream` / `resetToolCalls`）后实时切片会被清空，如果面板只
 * 依赖切片就会丢失会话 id、停止轮询确认项。这里按**对话 id** 记住最近一次
 * 看到的浏览器会话 id，进程内长期保留（不随 stream 生命周期清理）。
 */

import { create } from 'zustand';

/** 最多记住的对话数；防止长期运行无限增长。 */
const MAX_ENTRIES = 32;

interface BrowserSessionState {
  /** conversationId → 最近一次观察到的浏览器 session_id */
  byConversation: Record<string, string>;
  remember: (conversationId: string | null | undefined, sessionId: string) => void;
  forget: (conversationId: string) => void;
  reset: () => void;
}

function trimEntries(entries: Record<string, string>): Record<string, string> {
  const keys = Object.keys(entries);
  if (keys.length <= MAX_ENTRIES) return entries;
  const trimmed: Record<string, string> = {};
  for (const key of keys.slice(keys.length - MAX_ENTRIES)) {
    trimmed[key] = entries[key];
  }
  return trimmed;
}

export const useBrowserSessionStore = create<BrowserSessionState>((set) => ({
  byConversation: {},
  remember: (conversationId, sessionId) => {
    if (!conversationId || !sessionId) return;
    set((state) => {
      if (state.byConversation[conversationId] === sessionId) return state;
      return {
        byConversation: trimEntries({
          ...state.byConversation,
          [conversationId]: sessionId,
        }),
      };
    });
  },
  forget: (conversationId) =>
    set((state) => {
      if (!(conversationId in state.byConversation)) return state;
      const next = { ...state.byConversation };
      delete next[conversationId];
      return { byConversation: next };
    }),
  reset: () => set({ byConversation: {} }),
}));

/** 记住某对话的浏览器会话（跨 stream 生命周期）。 */
export function rememberBrowserSession(
  conversationId: string | null | undefined,
  sessionId: string,
): void {
  useBrowserSessionStore.getState().remember(conversationId, sessionId);
}

/** 读取某对话记住的浏览器会话。 */
export function rememberedBrowserSession(conversationId: string | null | undefined): string | null {
  if (!conversationId) return null;
  return useBrowserSessionStore.getState().byConversation[conversationId] ?? null;
}
