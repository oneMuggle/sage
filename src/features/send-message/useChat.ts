import { useCallback, useMemo, useRef, useState } from 'react';

import { resolveEndpoint } from '../../entities/setting/types';
import { ApiException, type AgentEvent, type ChatConfig } from '../../shared/api/api';
import { mapLLMErrorToText, type LLMErrorResponse } from '../../shared/lib/errorMapping';
import { logger } from '../../shared/lib/logger';
import { chatApi, useStore, type Message, type ToolCall } from '../../shared/lib/store';
import { useSettings } from '../manage-settings/useSettings';

/**
 * 从 endpoint baseUrl 启发式推导 LLM provider 字符串。
 *
 * 后端在 PR-7a 后不再硬写 provider="custom",改用请求里的字段。
 * 暂时用 baseUrl 子串匹配,后续 PR 会给 EndpointConfig 加显式 provider
 * 字段(settings UI 让用户选),届时这个函数就退化成兜底。
 *
 * 返回值与 backend LLMConfig.provider 注释里允许的值对齐。
 */
function inferProviderFromBaseUrl(baseUrl: string | undefined): string | undefined {
  if (!baseUrl) return undefined;
  const u = baseUrl.toLowerCase();
  if (u.includes('generativelanguage.googleapis.com')) return 'gemini';
  if (u.includes('api.openai.com')) return 'openai';
  if (u.includes('api.deepseek.com')) return 'deepseek';
  if (u.includes('anthropic.com')) return 'claude';
  // Ollama / 局域网 / 其它 OpenAI 兼容代理 → 后端默认 'custom'
  return undefined;
}

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
    reasoning: string; // 新增：累积的 LLM 思考/推理过程
    state: AgentEvent['state'] | null;
  } | null>(null);
  const { messages, addMessage, updateMessage, currentSessionId, loadMessages } = useStore();
  const { settings } = useSettings();
  const loadingRef = useRef(false);
  const cancelRef = useRef<(() => void) | null>(null);
  // PR-6: ref 镜像 streaming.content, finally 写回 store 时同步读 (避免依赖 React state)
  const streamingContentRef = useRef<string>('');
  // 新增：ref 镜像 streaming.reasoning
  const streamingReasoningRef = useRef<string>('');

  const chatEndpoint = resolveEndpoint(settings.modelSelections.chatModel, settings.endpoints);

  /**
   * 派生 messages: 当 streaming 时, 替换 store.messages 中对应 id 的 content 和 reasoning_content
   * — widget 看到的最后一条 assistant 消息会"长出"内容
   */
  const derivedMessages = useMemo<Message[]>(() => {
    if (!streaming) return messages;
    return messages.map((m) =>
      m.id === streaming.messageId
        ? { ...m, content: streaming.content, reasoning_content: streaming.reasoning || undefined }
        : m,
    );
  }, [messages, streaming]);

  const sendMessage = useCallback(
    async (content: string, sessionId?: string) => {
      const sid = sessionId ?? currentSessionId;
      if (!sid || isLoading || loadingRef.current) return;

      // 取消上一次还在飞的 chatStream (React StrictMode 双调用 / 用户双击 /
      // 路由切换等场景),避免两个流并存导致 invoke 重复 + LLM 双调用 + 流事件混乱
      if (cancelRef.current) {
        try {
          cancelRef.current();
        } catch {
          /* ignore */
        }
        cancelRef.current = null;
      }

      // 即使 settings 缺失,user 消息也必须先 addMessage 再校验失败返回 —
      // ChatInput 已在 UI 层通过 disabled 状态阻止发送路径,
      // 此处的校验是 belt-and-suspenders 兜底(防止通过其他入口直接调 sendMessage)

      const requestId = crypto.randomUUID();
      logger.info(requestId, 'useChat.send.start', {
        sessionId: sid,
        hasApiKey: Boolean(chatEndpoint?.apiKey),
        hasModel: Boolean(settings.modelSelections.chatModel.modelId),
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

      const resetLoading = (): void => {
        loadingRef.current = false;
        setIsLoading(false);
      };

      if (!chatEndpoint?.baseUrl) {
        // 仍记录错误供上层展示,但消息已经进 store
        setError('未配置 API 地址，请在设置中配置');
        resetLoading();
        return;
      }

      if (!settings.modelSelections.chatModel.modelId) {
        setError('未选择对话模型，请在设置中配置');
        resetLoading();
        return;
      }

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
      setStreaming({
        messageId: assistantId,
        content: '🤔 思考中…',
        reasoning: '',
        state: 'thinking',
      });
      // 重置 reasoning ref
      streamingReasoningRef.current = '';

      // Accumulate tool calls during streaming
      const streamingToolCalls: ToolCall[] = [];

      const config: ChatConfig = {
        apiKey: chatEndpoint.apiKey,
        apiUrl: chatEndpoint.baseUrl,
        model: settings.modelSelections.chatModel.modelId ?? undefined,
        maxContext: settings.maxContext,
        temperature: settings.temperature,
        // 从 baseUrl 推导 provider,后端不再硬写 "custom"。
        // TODO(PR-7a+): 给 EndpointConfig 加 provider 字段,这里直接读,
        // 不再靠 URL 启发式。详见 docs/plans/2026-06-17_thinking-passthrough.md
        provider: inferProviderFromBaseUrl(chatEndpoint.baseUrl),
      };

      const appendContent = (next: string): void => {
        // I5: 流式逐字 — 之前是覆盖 (ref = next), 现在追加 (ref += next),
        // 让 CONTENT_DELTA 事件累积成完整回答
        streamingContentRef.current = streamingContentRef.current + next;
        setStreaming((prev) =>
          prev && prev.messageId === assistantId ? { ...prev, content: prev.content + next } : prev,
        );
      };

      // I5-2: 中间态 (thinking/acting/observing) 的 uiText 应"覆盖"而非"追加"，
      // 避免 "🤔 思考中…🤔 思考中…" 这种重复前缀 bug。
      // appendContent 用于累积真实回答 (content_delta / done.content)，
      // replaceContent 用于切换中间态占位符。
      const replaceContent = (next: string): void => {
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

      // 把流式最终 content 写回 store.messages,让 derivedMessages 退回
      // store 后仍显示完整答案 (而不是占位 "🤔 思考中…")。
      // 不能放 finally ——chatStream promise 在 listen() resolve 后就返回,
      // 不等 NDJSON 事件到。事件真实到达时机是 IPC 跨进程 (异步 macrotask),
      // 所以 cleanup 必须由 onDone / onError 触发。
      //
      // I5: onDone 时存 done 事件的 content (完整回答, 不是累积的 ref,
      // 因为 ref 里混了 '🤔 思考中…' 占位符)。finishStream 用这个写 store。
      let finished = false;
      let lastDoneContent: string | null = null;
      const finishStream = (): void => {
        if (finished) return;
        finished = true;
        // 优先用 done 事件自带的完整 content (避免混入 thinking 占位符)
        // 退回到 streamingContentRef (向后兼容旧的非流式 done 事件)
        const finalContent = lastDoneContent ?? streamingContentRef.current;
        const finalReasoning = streamingReasoningRef.current;
        if (finalContent || finalReasoning || streamingToolCalls.length > 0) {
          updateMessage(assistantId, {
            content: finalContent,
            reasoning_content: finalReasoning || undefined,
            tool_calls: streamingToolCalls.length > 0 ? streamingToolCalls : undefined,
          });
        }
        streamingContentRef.current = '';
        streamingReasoningRef.current = '';
        setStreaming(null);
        cancelRef.current = null;
        resetLoading();
      };

      try {
        // 解构 cancel 用于下次 sendMessage 时取消 (cancel-prev)
        const { cancel } = await chatApi.chatStream(
          sid,
          content,
          {
            onEvent: (evt) => {
              // 处理 reasoning 事件：累积 reasoning 内容
              if (evt.state === 'reasoning' && evt.reasoning) {
                streamingReasoningRef.current = streamingReasoningRef.current + evt.reasoning;
                setStreaming((prev) =>
                  prev && prev.messageId === assistantId
                    ? { ...prev, reasoning: streamingReasoningRef.current }
                    : prev,
                );
              }

              // Collect tool calls during streaming
              if (evt.state === 'acting' && evt.tool_call) {
                const tc = evt.tool_call;
                let args: Record<string, unknown> = {};
                try {
                  args = JSON.parse(tc.function.arguments);
                } catch {
                  // ignore parse errors
                }
                streamingToolCalls.push({
                  name: tc.function.name,
                  args,
                });
              }
              if (evt.state === 'observing' && evt.tool_result) {
                const tr = evt.tool_result;
                // Find the matching tool call (by matching tool_call_id to the last acting event)
                const lastTc = streamingToolCalls[streamingToolCalls.length - 1];
                if (lastTc) {
                  lastTc.result = tr.content;
                  // Try to parse JSON result to extract metadata (e.g., image data from MCP tools)
                  try {
                    const parsed = JSON.parse(tr.content);
                    if (parsed && typeof parsed === 'object' && parsed.metadata) {
                      lastTc.metadata = parsed.metadata;
                    }
                  } catch {
                    // Not JSON, ignore
                  }
                }
              }

              const uiText = agentStateToUiText(evt.state, evt.tool_call?.function.name);
              // 累积策略 (I5: 流式逐字):
              // - content_delta + done.content 触发 appendContent 追加 (累积真实回答)
              // - thinking/acting/observing 的 uiText 触发 replaceContent 覆盖
              //   (切换中间态占位, 避免 "🤔 思考中…🤔 思考中…" 重复前缀)
              // - reasoning 事件已在上面处理，不触发 content 更新
              if (evt.state === 'reasoning') {
                // reasoning 事件不更新 content，仅更新 state
                setStreaming((prev) =>
                  prev && prev.messageId === assistantId ? { ...prev, state: evt.state } : prev,
                );
              } else if (typeof evt.content === 'string' && evt.content.length > 0) {
                appendContent(evt.content);
                if (evt.state === 'done') {
                  lastDoneContent = evt.content;
                }
                setStreaming((prev) =>
                  prev && prev.messageId === assistantId ? { ...prev, state: evt.state } : prev,
                );
              } else if (uiText) {
                replaceContent(uiText);
                setStreaming((prev) =>
                  prev && prev.messageId === assistantId ? { ...prev, state: evt.state } : prev,
                );
              }
            },
            onError: (err) => {
              handleError(err);
              finishStream();
            },
            onDone: () => {
              // 流自然结束 — 把 streaming.content 写回 store,
              // 然后清掉 streaming overlay 让消息退回 store 视图
              finishStream();
            },
          },
          config,
        );
        // 存 cancel 用于下次 sendMessage 取消 + interrupt 用
        cancelRef.current = cancel;
      } catch (err: unknown) {
        // chatStream 启动失败 (validate / listen 失败等)
        // onDone/onError 不会触发,这里兜底
        handleError(err);
        finishStream();
      }
    },
    [currentSessionId, isLoading, chatEndpoint, settings, addMessage, updateMessage],
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
