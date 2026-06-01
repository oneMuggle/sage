import { useState, useCallback, useRef } from 'react'
import { chatApi, useStore, type Message } from '../lib/store'
import { useSettings } from './useSettings'
import type { ChatConfig } from '../lib/api'

export function useChat() {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { messages, addMessage, currentSessionId, loadMessages } = useStore()
  const { settings } = useSettings()
  const loadingRef = useRef(false)

  const activeEndpoint = settings.endpoints.find((e) => e.isActive)

  const sendMessage = useCallback(async (content: string, sessionId?: string) => {
    const sid = sessionId ?? currentSessionId
    if (!sid || isLoading || loadingRef.current) return

    if (!activeEndpoint?.baseUrl) {
      setError('未配置 API 地址，请在设置中配置')
      return
    }

    if (!settings.modelSelections.chatModelId) {
      setError('未选择对话模型，请在设置中配置')
      return
    }

    loadingRef.current = true
    setIsLoading(true)
    setError(null)

    try {
      const userMessage: Message = {
        id: crypto.randomUUID(),
        session_id: sid,
        role: 'user',
        content,
        created_at: Date.now(),
      }
      addMessage(userMessage)

      const config: ChatConfig = {
        apiKey: activeEndpoint.apiKey,
        apiUrl: activeEndpoint.baseUrl,
        model: settings.modelSelections.chatModelId ?? undefined,
        maxContext: settings.maxContext,
        temperature: settings.temperature,
      }
      const response = await chatApi.chat(sid, content, config)
      addMessage(response.message)
    } catch (err) {
      const message = err instanceof Error ? err.message : '发送消息失败'
      setError(message)
    } finally {
      setIsLoading(false)
      loadingRef.current = false
    }
  }, [currentSessionId, isLoading, activeEndpoint, settings, addMessage])

  const interrupt = useCallback(async () => {
    try {
      await chatApi.interrupt()
    } catch {
      // Interrupt failures are non-critical
    }
  }, [])

  const loadMessagesCallback = useCallback(async (sessionId: string) => {
    await loadMessages(sessionId)
  }, [loadMessages])

  const clearError = useCallback(() => setError(null), [])

  return {
    messages,
    isLoading,
    error,
    clearError,
    sendMessage,
    interrupt,
    loadMessages: loadMessagesCallback,
  }
}
