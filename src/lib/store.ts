import { create } from 'zustand';

import { invoke } from './tauriInvoke';

// Re-export API modules from api.ts for convenience
export { sessionApi, messageApi, chatApi, memoryApi } from './api';

// ==================== 类型定义 ====================

// 会话
export interface Session {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  last_message_at: number | null;
  message_count: number;
  is_pinned: boolean;
  metadata?: Record<string, unknown>;
}

// 工具调用结构（与后端 AgentEvent 保持一致）
export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result?: string;
}

// 消息
export interface Message {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  created_at: number;
  model?: string;
  provider?: string;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
  memory_applied?: number;
}

// 状态接口
interface StoreState {
  // 会话状态
  sessions: Session[];
  currentSessionId: string | null;
  messages: Message[];

  // 加载状态
  isLoading: boolean;

  // 操作方法
  loadSessions: () => Promise<void>;
  setCurrentSessionId: (id: string | null) => void;
  createSession: () => Promise<string>;
  deleteSession: (id: string) => Promise<void>;

  loadMessages: (sessionId: string) => Promise<void>;
  addMessage: (message: Message) => void;
  /** PR-6: 用同一 id 的新对象替换某条消息 (流式 chat 结束时写回最终 content) */
  updateMessage: (id: string, patch: Partial<Message>) => void;
  clearMessages: () => void;
}

// ==================== Zustand Store ====================

const SESSION_STORAGE_KEY = 'sage-current-session-id';

export const useStore = create<StoreState>((set, _get) => ({
  // 初始状态
  sessions: [],
  currentSessionId: (() => {
    try {
      return localStorage.getItem(SESSION_STORAGE_KEY);
    } catch {
      return null;
    }
  })(),
  messages: [],
  isLoading: false,

  // 加载会话列表
  loadSessions: async () => {
    try {
      const sessions = await invoke<Session[]>('list_sessions');
      set({ sessions });
    } catch (error) {
      console.error('加载会话列表失败:', error);
    }
  },

  // 设置当前会话
  setCurrentSessionId: (id) => {
    try {
      if (id) {
        localStorage.setItem(SESSION_STORAGE_KEY, id);
      } else {
        localStorage.removeItem(SESSION_STORAGE_KEY);
      }
    } catch {
      // Silently fail
    }
    set({ currentSessionId: id });
  },

  // 创建会话
  createSession: async () => {
    try {
      const session = await invoke<Session>('create_session', { title: '新对话' });
      set((state) => ({
        sessions: [session, ...state.sessions],
        currentSessionId: session.id,
      }));
      return session.id;
    } catch (error) {
      console.error('创建会话失败:', error);
      throw error;
    }
  },

  // 删除会话
  deleteSession: async (id) => {
    try {
      await invoke('delete_session', { id });
      set((state) => ({
        sessions: state.sessions.filter((s) => s.id !== id),
        currentSessionId: state.currentSessionId === id ? null : state.currentSessionId,
        messages: state.currentSessionId === id ? [] : state.messages,
      }));
    } catch (error) {
      console.error('删除会话失败:', error);
    }
  },

  // 加载消息
  loadMessages: async (sessionId) => {
    try {
      set({ isLoading: true });
      const messages = await invoke<Message[]>('get_messages', { sessionId });
      set({ messages, isLoading: false });
    } catch (error) {
      console.error('加载消息失败:', error);
      set({ isLoading: false });
    }
  },

  // 添加消息
  addMessage: (message) => {
    set((state) => ({
      messages: [...state.messages, message],
    }));
  },

  // PR-6: 按 id 替换 (流式 chat 把占位 assistant 写回最终 content)
  updateMessage: (id, patch) => {
    set((state) => ({
      messages: state.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    }));
  },

  // 清空消息
  clearMessages: () => {
    set({ messages: [] });
  },
}));

// ==================== 懒加载页面组件 ====================
// 使用 React.lazy 懒加载页面组件，减少初始加载时间
// 注意: 实际的懒加载组件在各自页面文件中

export const LazyChat = () => import('../pages/Chat');
export const LazySettings = () => import('../pages/Settings');
export const LazyMemory = () => import('../pages/Memory');
export const LazySkills = () => import('../pages/Skills');
export const LazyKnowledge = () => import('../pages/Knowledge');

// ==================== 缓存策略 ====================

// 消息缓存 (内存中缓存)
const messageCache = new Map<string, { messages: Message[]; timestamp: number }>();
const MESSAGE_CACHE_TTL = 5 * 60 * 1000; // 5分钟

/**
 * 获取缓存的消息
 * @param sessionId 会话ID
 * @returns 缓存的消息或null
 */
export function getCachedMessages(sessionId: string): Message[] | null {
  const cached = messageCache.get(sessionId);
  if (cached && Date.now() - cached.timestamp < MESSAGE_CACHE_TTL) {
    return cached.messages;
  }
  messageCache.delete(sessionId);
  return null;
}

/**
 * 设置消息缓存
 * @param sessionId 会话ID
 * @param messages 消息列表
 */
export function setCachedMessages(sessionId: string, messages: Message[]): void {
  messageCache.set(sessionId, {
    messages,
    timestamp: Date.now(),
  });
}

/**
 * 清除指定会话的缓存
 * @param sessionId 会话ID
 */
export function clearCachedMessages(sessionId?: string): void {
  if (sessionId) {
    messageCache.delete(sessionId);
  } else {
    messageCache.clear();
  }
}

/**
 * 清理过期缓存
 */
export function cleanupExpiredCache(): void {
  const now = Date.now();
  for (const [key, value] of messageCache.entries()) {
    if (now - value.timestamp > MESSAGE_CACHE_TTL) {
      messageCache.delete(key);
    }
  }
}
