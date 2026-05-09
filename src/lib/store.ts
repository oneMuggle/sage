import { create } from 'zustand'

// ==================== 类型定义 ====================

// 会话
export interface Session {
  id: string
  title: string
  created_at: number
  updated_at: number
  last_message_at: number | null
  message_count: number
  is_pinned: boolean
  metadata?: Record<string, unknown>
}

// 消息
export interface Message {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  created_at: number
  model?: string
  provider?: string
  tool_calls?: Array<{
    name: string
    args: Record<string, unknown>
    result?: string
  }>
  tool_call_id?: string
}

// 状态接口
interface StoreState {
  // 会话状态
  sessions: Session[]
  currentSessionId: string | null
  messages: Message[]
  
  // 加载状态
  isLoading: boolean
  
  // 操作方法
  loadSessions: () => Promise<void>
  setCurrentSessionId: (id: string | null) => void
  createSession: () => Promise<string>
  deleteSession: (id: string) => Promise<void>
  
  loadMessages: (sessionId: string) => Promise<void>
  addMessage: (message: Message) => void
  clearMessages: () => void
}

// ==================== Zustand Store ====================

export const useStore = create<StoreState>((set, get) => ({
  // 初始状态
  sessions: [],
  currentSessionId: null,
  messages: [],
  isLoading: false,
  
  // 加载会话列表
  loadSessions: async () => {
    try {
      const { invoke } = await import('@tauri-apps/api/tauri')
      const sessions = await invoke<Session[]>('list_sessions')
      set({ sessions })
    } catch (error) {
      console.error('加载会话列表失败:', error)
    }
  },
  
  // 设置当前会话
  setCurrentSessionId: (id) => {
    set({ currentSessionId: id })
  },
  
  // 创建会话
  createSession: async () => {
    try {
      const { invoke } = await import('@tauri-apps/api/tauri')
      const session = await invoke<Session>('create_session', { title: '新对话' })
      set((state) => ({
        sessions: [session, ...state.sessions],
        currentSessionId: session.id
      }))
      return session.id
    } catch (error) {
      console.error('创建会话失败:', error)
      throw error
    }
  },
  
  // 删除会话
  deleteSession: async (id) => {
    try {
      const { invoke } = await import('@tauri-apps/api/tauri')
      await invoke('delete_session', { id })
      set((state) => ({
        sessions: state.sessions.filter((s) => s.id !== id),
        currentSessionId: state.currentSessionId === id ? null : state.currentSessionId,
        messages: state.currentSessionId === id ? [] : state.messages,
      }))
    } catch (error) {
      console.error('删除会话失败:', error)
    }
  },
  
  // 加载消息
  loadMessages: async (sessionId) => {
    try {
      set({ isLoading: true })
      const { invoke } = await import('@tauri-apps/api/tauri')
      const messages = await invoke<Message[]>('get_messages', { sessionId })
      set({ messages, isLoading: false })
    } catch (error) {
      console.error('加载消息失败:', error)
      set({ isLoading: false })
    }
  },
  
  // 添加消息
  addMessage: (message) => {
    set((state) => ({
      messages: [...state.messages, message],
    }))
  },
  
  // 清空消息
  clearMessages: () => {
    set({ messages: [] })
  },
}))
