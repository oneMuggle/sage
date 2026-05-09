/**
 * Sage API - Tauri Commands 调用封装
 * 包含错误处理和重试逻辑
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

// ==================== 错误类型定义 ====================

export interface ApiError {
  error: string
  message: string
  details?: Record<string, unknown>
}

export class ApiException extends Error {
  code: string
  details: Record<string, unknown>
  
  constructor(error: ApiError) {
    super(error.message)
    this.name = 'ApiException'
    this.code = error.error
    this.details = error.details || {}
  }
}

// ==================== 重试配置 ====================

interface RetryConfig {
  maxRetries: number  // 最大重试次数
  retryDelay: number  // 重试延迟（毫秒）
  backoffMultiplier: number  // 退避倍数
}

const defaultRetryConfig: RetryConfig = {
  maxRetries: 3,
  retryDelay: 1000,
  backoffMultiplier: 2
}

// ==================== 输入安全处理 ====================

/**
 * 安全化用户输入，防止 XSS 攻击
 * @param input 用户输入字符串
 * @returns 安全化后的字符串
 */
function sanitizeInput(input: string): string {
  if (typeof input !== 'string') {
    return ''
  }
  
  return input
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;')
    .replace(/\//g, '&#x2F;')
}

/**
 * 验证会话ID格式
 * @param sessionId 会话ID
 * @returns 是否有效
 */
function isValidSessionId(sessionId: string): boolean {
  // UUID 格式验证
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
  return uuidRegex.test(sessionId)
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

// ==================== 重试装饰器 ====================

async function withRetry<T>(
  operation: () => Promise<T>,
  config: Partial<RetryConfig> = {}
): Promise<T> {
  const { maxRetries, retryDelay, backoffMultiplier } = {
    ...defaultRetryConfig,
    ...config
  }
  
  let lastError: Error | null = null
  let currentDelay = retryDelay
  
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await operation()
    } catch (error) {
      lastError = error as Error
      
      // 如果还有重试机会
      if (attempt < maxRetries) {
        console.warn(`请求失败，第 ${attempt + 1} 次重试，${currentDelay}ms 后...`)
        await new Promise(resolve => setTimeout(resolve, currentDelay))
        currentDelay *= backoffMultiplier
      }
    }
  }
  
  // 所有重试都失败了
  throw lastError
}

// ==================== 错误处理 ====================

function handleApiError(error: unknown): ApiException {
  if (error instanceof ApiException) {
    return error
  }
  
  // 尝试解析错误响应
  if (error && typeof error === 'object' && 'error' in error) {
    return new ApiException(error as ApiError)
  }
  
  // 包装未知错误
  return new ApiException({
    error: 'UNKNOWN_ERROR',
    message: error instanceof Error ? error.message : '未知错误',
    details: { originalError: String(error) }
  })
}

// ==================== Session API ====================

export const sessionApi = {
  async create(title: string = '新对话'): Promise<Session> {
    // 安全化标题输入
    const safeTitle = sanitizeInput(title)
    
    return withRetry(async () => {
      try {
        const invoke = await getInvoke()
        const session = await invoke<Session>('create_session', { title: safeTitle })
        return session
      } catch (error) {
        throw handleApiError(error)
      }
    })
  },

  async list(): Promise<Session[]> {
    return withRetry(async () => {
      try {
        const invoke = await getInvoke()
        return await invoke<Session[]>('list_sessions')
      } catch (error) {
        throw handleApiError(error)
      }
    })
  },

  async get(id: string): Promise<Session> {
    // 验证会话ID
    if (!isValidSessionId(id)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId: id }
      })
    }
    
    return withRetry(async () => {
      try {
        const invoke = await getInvoke()
        return await invoke<Session>('get_session', { id })
      } catch (error) {
        throw handleApiError(error)
      }
    })
  },

  async delete(id: string): Promise<void> {
    // 验证会话ID
    if (!isValidSessionId(id)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId: id }
      })
    }
    
    return withRetry(async () => {
      try {
        const invoke = await getInvoke()
        await invoke('delete_session', { id })
      } catch (error) {
        throw handleApiError(error)
      }
    })
  },

  async getMessages(sessionId: string): Promise<Message[]> {
    // 验证会话ID
    if (!isValidSessionId(sessionId)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId }
      })
    }
    
    return withRetry(async () => {
      try {
        const invoke = await getInvoke()
        return await invoke<Message[]>('get_messages', { sessionId })
      } catch (error) {
        throw handleApiError(error)
      }
    })
  },
}

// ==================== Message API ====================

export const messageApi = {
  async delete(id: string): Promise<void> {
    // 验证消息ID格式
    if (!id || typeof id !== 'string') {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的消息ID',
        details: { messageId: id }
      })
    }
    
    return withRetry(async () => {
      try {
        const invoke = await getInvoke()
        await invoke('delete_message', { id })
      } catch (error) {
        throw handleApiError(error)
      }
    })
  },
}

// ==================== Chat API ====================

export const chatApi = {
  async chat(sessionId: string, message: string): Promise<ChatResponse> {
    // 安全化消息输入
    const safeMessage = sanitizeInput(message)
    
    // 验证会话ID
    if (!isValidSessionId(sessionId)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId }
      })
    }
    
    return withRetry(async () => {
      try {
        const invoke = await getInvoke()
        const response = await invoke<ChatResponse>('agent_chat', { 
          sessionId, 
          message: safeMessage 
        })
        return response
      } catch (error) {
        throw handleApiError(error)
      }
    }, { maxRetries: 2 })  // chat 操作重试次数少一些
  },

  async interrupt(): Promise<void> {
    try {
      const invoke = await getInvoke()
      await invoke('interrupt_agent')
    } catch (error) {
      console.error('中断请求失败:', error)
      // 中断操作不重试，忽略错误
    }
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
    // 安全化查询输入
    const safeQuery = sanitizeInput(query)
    
    return withRetry(async () => {
      try {
        const invoke = await getInvoke()
        return await invoke<Memory[]>('search_memory', {
          query: safeQuery,
          memoryType: memoryType || null,
          limit: 20,
        })
      } catch (error) {
        throw handleApiError(error)
      }
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
    // 安全化内容输入
    const safeContent = sanitizeInput(content)
    const safeTags = Array.isArray(tags) ? tags.map(t => sanitizeInput(t)) : []
    
    // 验证重要性值
    const safeImportance = Math.min(10, Math.max(0, Number(importance) || 5))
    
    return withRetry(async () => {
      try {
        const invoke = await getInvoke()
        return await invoke<Memory>('save_memory', {
          content: safeContent,
          memoryType,
          importance: safeImportance,
          tags: safeTags,
        })
      } catch (error) {
        throw handleApiError(error)
      }
    })
  },

  /**
   * 删除记忆
   */
  async deleteMemory(id: string): Promise<void> {
    // 验证记忆ID
    if (!id || typeof id !== 'string') {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的记忆ID',
        details: { memoryId: id }
      })
    }
    
    return withRetry(async () => {
      try {
        const invoke = await getInvoke()
        await invoke('delete_memory', { id })
      } catch (error) {
        throw handleApiError(error)
      }
    })
  },

  /**
   * 获取记忆列表
   */
  async getMemories(
    memoryType?: 'episodic' | 'semantic',
    page: number = 1,
    pageSize: number = 20
  ): Promise<Memory[]> {
    // 验证分页参数
    const safePage = Math.max(1, Number(page) || 1)
    const safePageSize = Math.min(100, Math.max(1, Number(pageSize) || 20))
    
    return withRetry(async () => {
      try {
        const invoke = await getInvoke()
        return await invoke<Memory[]>('get_memories', {
          memoryType: memoryType || null,
          page: safePage,
          pageSize: safePageSize,
        })
      } catch (error) {
        throw handleApiError(error)
      }
    })
  },
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

// ==================== 导出工具函数 ====================

export { sanitizeInput, isValidSessionId }
