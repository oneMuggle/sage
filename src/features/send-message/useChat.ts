import { useCallback, useMemo, useRef, useState } from 'react';

import { ApiException, type AgentEvent, type ChatConfig } from '../../shared/api/api';
import { mapLLMErrorToText, type LLMErrorResponse } from '../../shared/lib/errorMapping';
import { logger } from '../../shared/lib/logger';
import { chatApi, useStore, type Message } from '../../shared/lib/store';
import { useSettings } from '../manage-settings/useSettings';

/** 把后端 AgentState 映射到 UI 中间态文本 (PR-6) */
function agentStateToUiText(state: AgentEvent['state'], toolName?: string): string | null {
  switch (state) {
    case 'thinking':
      return '🤔 思考中…';
    case 'acting':
      return toolName ? `🔧 调工具 ${toolName}…` : '🔧 行动中…';
    case 'observing':
      return '👀 观察结果…';
    case 'failed':
      return '❌ 失败';
    default:
      return null;
  }
}

export function useChat() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // PR-6: 流式当前 assistant 消息的内容覆盖 (派生 messages 的最后一条)
  const [streaming, setStreaming] = useState<{
    messageId: string;
    content: string;
    state: AgentEvent['state'] | null;
  } | null>(null);
  const { messages, addMessage, updateMessage, currentSessionId, loadMessages } = useStore();
  const { settings } = useSettings();
  const loadingRef = useRef(false);
  const cancelRef = useRef<(() => void) | null>(null);
  // PR-6: ref 镜像 streaming.content, finally 写回 store 时同步读 (避免依赖 React state)
  const streamingContentRef = useRef<string>('');

  const activeEndpoint = settings.endpoints.find((e) => e.isActive);

  /**
   * 派生 messages: 当 streaming 时, 替换 store.messages 中对应 id 的 content
   * — widget 看到的最后一条 assistant 消息会"长出"内容
   */
  const derivedMessages = useMemo<Message[]>(() => {
    if (!streaming) return messages;
    return messages.map((m) =>
      m.id === streaming.messageId ? { ...m, content: streaming.content } : m,
    );
  }, [messages, streaming]);

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

      const userMessage: Message = {
        id: crypto.randomUUID(),
        session_id: sid,
        role: 'user',
        content,
        created_at: Date.now(),
      };
      addMessage(userMessage);

      // PR-6: 先占位 assistant message, 流式过程中累积 content
      const assistantId = crypto.randomUUID();
      const assistantMessage: Message = {
        id: assistantId,
        session_id: sid,
        role: 'assistant',
        content: '🤔 思考中…',
        created_at: Date.now(),
      };
      addMessage(assistantMessage);
      setStreaming({ messageId: assistantId, content: '🤔 思考中…', state: 'thinking' });

      const config: ChatConfig = {
        apiKey: activeEndpoint.apiKey,
        apiUrl: activeEndpoint.baseUrl,
        model: settings.modelSelections.chatModelId ?? undefined,
        maxContext: settings.maxContext,
        temperature: settings.temperature,
      };

      const appendContent = (next: string): void => {
        streamingContentRef.current = next;
        setStreaming((prev) =>
          prev && prev.messageId === assistantId ? { ...prev, content: next } : prev,
        );
      };

      const handleError = (err: unknown): void => {
        logger.error(requestId, 'useChat.send.failed', err);
        if (err instanceof ApiException && err.llmError) {
          setError(mapLLMErrorToText(err.llmError));
          return;
        }
        const apiErr = err as {
          llmError?: LLMErrorResponse;
          error?: LLMErrorResponse;
          message?: string;
        };
        if (apiErr.llmError || apiErr.error) {
          setError(mapLLMErrorToText(apiErr.llmError ?? apiErr.error!));
        } else {
          setError(err instanceof Error ? err.message : '发送消息失败');
        }
      };

      try {
        await chatApi.chatStream(
          sid,
          content,
          {
            onEvent: (evt) => {
              const uiText = agentStateToUiText(evt.state, evt.tool_call?.function.name);
              // 累积策略: thinking/acting/observing 替换为 uiText (单一占位);
              // 若事件同时带 content (LLM 最终答案逐字到达), 替换占位为答案。
              if (typeof evt.content === 'string' && evt.content.length > 0) {
                appendContent(evt.content);
              } else if (uiText) {
                appendContent(uiText);
              }
              setStreaming((prev) =>
                prev && prev.messageId === assistantId ? { ...prev, state: evt.state } : prev,
              );
            },
            onError: (err) => {
              handleError(err);
            },
            onDone: () => {
              // 流自然结束 — 保留 streaming, 让用户看到最终内容;
              // finally 会清掉 streaming
            },
          },
          config,
        );
      } catch (err: unknown) {
        // chatStream 启动失败 (validate / listen 失败等)
        handleError(err);
      } finally {
        // 把流式最终 content 写回 store.messages,让 derivedMessages 退回
        // store 后仍显示完整答案 (而不是占位 "🤔 思考中…")
        const finalContent = streamingContentRef.current;
        if (finalContent) {
          updateMessage(assistantId, { content: finalContent });
        }
        streamingContentRef.current = '';
        setStreaming(null);
        cancelRef.current = null;
        setIsLoading(false);
        loadingRef.current = false;
      }
    },
    [currentSessionId, isLoading, activeEndpoint, settings, addMessage, updateMessage],
  );

  const interrupt = useCallback(async () => {
    // PR-6: 先取消前端 listener, 再请求后端中断
    if (cancelRef.current) {
      try {
        cancelRef.current();
      } catch {
        // ignore
      }
      cancelRef.current = null;
    }
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
    messages: derivedMessages,
    isLoading,
    error,
    clearError,
    sendMessage,
    interrupt,
    loadMessages: loadMessagesCallback,
  };
}
