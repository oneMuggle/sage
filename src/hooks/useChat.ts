import { useState, useCallback } from 'react'
import { chatApi, useStore, type Message } from '../lib/store'

export function useChat() {
  const [isLoading, setIsLoading] = useState(false)
  const { messages, addMessage, currentSessionId, loadMessages } = useStore()

  const sendMessage = useCallback(async (content: string) => {
    if (!currentSessionId || isLoading) return

    setIsLoading(true)
    try {
      // 添加用户消息
      const userMessage: Message = {
        id: crypto.randomUUID(),
        session_id: currentSessionId,
        role: 'user',
        content,
        created_at: Date.now(),
      }
      addMessage(userMessage)

      // 调用 Agent
      const response = await chatApi.chat(currentSessionId, content)
      
      // 添加助手消息
      addMessage(response.message)
    } catch (error) {
      console.error('发送消息失败:', error)
    } finally {
      setIsLoading(false)
    }
  }, [currentSessionId, isLoading, addMessage])

  const interrupt = useCallback(async () => {
    try {
      await chatApi.interrupt()
    } catch (error) {
      console.error('中断失败:', error)
    }
  }, [])

  const loadMessagesCallback = useCallback(async (sessionId: string) => {
    await loadMessages(sessionId)
  }, [loadMessages])

  return {
    messages,
    isLoading,
    sendMessage,
    interrupt,
    loadMessages: loadMessagesCallback,
  }
}
