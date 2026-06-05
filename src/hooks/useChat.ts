import { useState, useCallback, useRef } from 'react';

import { ApiException, type ChatConfig } from '../lib/api';
import { mapLLMErrorToText, type LLMErrorResponse } from '../lib/errorMapping';
import { logger } from '../lib/logger';
import { chatApi, useStore, type Message } from '../lib/store';

import { useSettings } from './useSettings';

export function useChat() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { messages, addMessage, currentSessionId, loadMessages } = useStore();
  const { settings } = useSettings();
  const loadingRef = useRef(false);

  const activeEndpoint = settings.endpoints.find((e) => e.isActive);

  const sendMessage = useCallback(
    async (content: string, sessionId?: string) => {
      const sid = sessionId ?? currentSessionId;
      if (!sid || isLoading || loadingRef.current) return;

      if (!activeEndpoint?.baseUrl) {
        setError('未配置 API 地址，请在设置中配置');
        return;
      }

      if (!settings.modelSelections.chatModelId) {
        setError('未选择对话模型，请在设置中配置');
        return;
      }

      const requestId = crypto.randomUUID();
      logger.info(requestId, 'useChat.send.start', {
        sessionId: sid,
        hasApiKey: Boolean(activeEndpoint?.apiKey),
        hasModel: Boolean(settings.modelSelections.chatModelId),
      });

      loadingRef.current = true;
      setIsLoading(true);
      setError(null);

      try {
        const userMessage: Message = {
          id: crypto.randomUUID(),
          session_id: sid,
          role: 'user',
          content,
          created_at: Date.now(),
        };
        addMessage(userMessage);

        const config: ChatConfig = {
          apiKey: activeEndpoint.apiKey,
          apiUrl: activeEndpoint.baseUrl,
          model: settings.modelSelections.chatModelId ?? undefined,
          maxContext: settings.maxContext,
          temperature: settings.temperature,
        };
        const response = await chatApi.chat(sid, content, config);
        addMessage(response.message);
      } catch (err: unknown) {
        logger.error(requestId, 'useChat.send.failed', err);

        // ApiException 携带着结构化 LLMErrorResponse（保存为 llmError 字段）
        if (err instanceof ApiException && err.llmError) {
          setError(mapLLMErrorToText(err.llmError));
          return;
        }

        // 兜底：Tauri 通道可能直接抛出后端结构，err 上可能有 llmError/error 字段
        const apiErr = err as {
          llmError?: LLMErrorResponse;
          error?: LLMErrorResponse;
          message?: string;
        };
        if (apiErr.llmError || apiErr.error) {
          setError(mapLLMErrorToText(apiErr.llmError ?? apiErr.error!));
        } else {
          const message = err instanceof Error ? err.message : '发送消息失败';
          setError(message);
        }
      } finally {
        setIsLoading(false);
        loadingRef.current = false;
      }
    },
    [currentSessionId, isLoading, activeEndpoint, settings, addMessage],
  );

  const interrupt = useCallback(async () => {
    try {
      await chatApi.interrupt();
    } catch {
      // Interrupt failures are non-critical
    }
  }, []);

  const loadMessagesCallback = useCallback(
    async (sessionId: string) => {
      await loadMessages(sessionId);
    },
    [loadMessages],
  );

  const clearError = useCallback(() => setError(null), []);

  return {
    messages,
    isLoading,
    error,
    clearError,
    sendMessage,
    interrupt,
    loadMessages: loadMessagesCallback,
  };
}
