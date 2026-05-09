/**
 * Sage API - Tauri Commands 调用封装
 */

// ==================== 类型定义 ====================

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

export interface Message {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  created_at: number
  model?: string
  provider?: string
  tool_calls?: ToolCall[]
  tool_call_id?: string
}

export interface ToolCall {
  name: string
  args: Record<string, unknown>
  result?: string
}

export interface ChatRequest {
  session_id: string
  message: string
}

export interface ChatResponse {
  message: Message
  session?: Session
}

// ==================== Memory 类型定义 ====================

export interface Memory {
  id: string
  content: string
  summary?: string
  memory_type?: 'episodic' | 'semantic' | 'working'
  session_id?: string
  importance: number
  tags: string[]
  created_at: number
  accessed_at?: number
  access_count: number
}

// ==================== 懒加载 Tauri API ====================

let _invoke: any = null

async function getInvoke() {
  if (!_invoke) {
    const module = await import('@tauri-apps/api/tauri')
    _invoke = module.invoke
  }
  return _invoke
}

// ==================== Session API ====================

export const sessionApi = {
  async create(title: string = '新对话'): Promise<Session> {
    const invoke = await getInvoke()
    return invoke('create_session', { title })
  },

  async list(): Promise<Session[]> {
    const invoke = await getInvoke()
    return invoke('list_sessions')
  },

  async get(id: string): Promise<Session> {
    const invoke = await getInvoke()
    return invoke('get_session', { id })
  },

  async delete(id: string): Promise<void> {
    const invoke = await getInvoke()
    return invoke('delete_session', { id })
  },

  async getMessages(sessionId: string): Promise<Message[]> {
    const invoke = await getInvoke()
    return invoke('get_messages', { sessionId })
  },
}

// ==================== Message API ====================

export const messageApi = {
  async delete(id: string): Promise<void> {
    const invoke = await getInvoke()
    return invoke('delete_message', { id })
  },
}

// ==================== Chat API ====================

export const chatApi = {
  async chat(sessionId: string, message: string): Promise<ChatResponse> {
    const invoke = await getInvoke()
    return invoke('agent_chat', { sessionId, message })
  },

  async interrupt(): Promise<void> {
    const invoke = await getInvoke()
    return invoke('interrupt_agent')
  },
}

// ==================== Memory API ====================

export const memoryApi = {
  /**
   * 搜索记忆
   */
  async searchMemories(
    query: string,
    memoryType?: 'episodic' | 'semantic'
  ): Promise<Memory[]> {
    const invoke = await getInvoke()
    return invoke('search_memory', {
      query,
      memoryType: memoryType || null,
      limit: 20,
    })
  },

  /**
   * 保存记忆
   */
  async saveMemory(
    content: string,
    memoryType: 'episodic' | 'semantic',
    importance: number = 5,
    tags?: string[]
  ): Promise<Memory> {
    const invoke = await getInvoke()
    return invoke('save_memory', {
      content,
      memoryType,
      importance,
      tags: tags || [],
    })
  },

  /**
   * 删除记忆
   */
  async deleteMemory(id: string): Promise<void> {
    const invoke = await getInvoke()
    return invoke('delete_memory', { id })
  },

  /**
   * 获取记忆列表
   */
  async getMemories(
    memoryType?: 'episodic' | 'semantic',
    page: number = 1,
    pageSize: number = 20
  ): Promise<Memory[]> {
    const invoke = await getInvoke()
    return invoke('get_memories', {
      memoryType: memoryType || null,
      page,
      pageSize,
    })
  },
}
