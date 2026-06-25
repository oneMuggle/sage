import { useCallback, useMemo, useRef, useState } from 'react';

import { resolveEndpoint } from '../../entities/setting/types';
import { ApiException, type AgentEvent, type ChatConfig } from '../../shared/api';
import { agentStateToText } from '../../shared/lib/agentStateMapping';
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

export function useChat() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // PR-6: 流式当前 assistant 消息的内容覆盖 (派生 messages 的最后一条)
  const [streaming, setStreaming] = useState<{
    messageId: string;
    content: string;
    reasoning: string; // 新增：累积的 LLM 思考/推理过程
    state: AgentEvent['state'] | null;
    /** 阶段 4: 当前执行 agent 的 ID */
    currentAgentId: string | null;
    /** P2: 当前 ReAct 迭代轮次 */
    iteration: number;
  } | null>(null);
  const { messages, addMessage, updateMessage, currentSessionId, loadMessages } = useStore();
  const { settings } = useSettings();
  const loadingRef = useRef(false);
  const cancelRef = useRef<(() => void) | null>(null);
  // HIGH-4 修复: finishStream 是 sendMessage 闭包内的函数,interrupt() 无法直接调用
  // 用 ref 把 finishStream 暴露出去,让 interrupt 也能触发清理流程
  const finishStreamRef = useRef<(() => void) | null>(null);
  // PR-6: ref 镜像 streaming.content, finally 写回 store 时同步读 (避免依赖 React state)
  const streamingContentRef = useRef<string>('');
  // 新增：ref 镜像 streaming.reasoning
  const streamingReasoningRef = useRef<string>('');
  // P0: 实时工具调用 — state 驱动 UI 渲染，ref 镜像供 finishStream 读取最新值
  const [streamingToolCalls, setStreamingToolCalls] = useState<ToolCall[]>([]);
  const streamingToolCallsRef = useRef<ToolCall[]>([]);

  const chatEndpoint = resolveEndpoint(settings.modelSelections.chatModel, settings.endpoints);

  /**
   * 派生 messages: 当 streaming 时, 替换 store.messages 中对应 id 的 content 和 reasoning_content
   * — widget 看到的最后一条 assistant 消息会"长出"内容
   */
  // MEDIUM-6: 提取 streaming 中实际用到的字段到局部变量,便于 useMemo 细粒度 deps
  const streamingMessageId = streaming?.messageId ?? null;
  const streamingContent = streaming?.content ?? '';
  const streamingReasoning = streaming?.reasoning ?? '';

  const derivedMessages = useMemo<Message[]>(() => {
    if (!streamingMessageId) return messages;
    return messages.map((m) =>
      m.id === streamingMessageId
        ? {
            ...m,
            content: streamingContent,
            reasoning_content: streamingReasoning || undefined,
            tool_calls: streamingToolCalls.length > 0 ? streamingToolCalls : undefined,
          }
        : m,
    );
    // MEDIUM-6: 拆细 deps — 仅依赖 streaming 中实际用到的字段,
    // 避免 currentAgentId/iteration/state 等无关变化触发 messages 数组重建
  }, [messages, streamingMessageId, streamingContent, streamingReasoning, streamingToolCalls]);

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
        // MEDIUM-1: 同时通知后端中断正在跑的 stream,避免 cancel 只 unlisten 前端
        // 而后端继续消耗 LLM token。fire-and-forget — interrupt 失败不影响新消息发送
        chatApi.interrupt().catch(() => {
          /* Interrupt failures are non-critical */
        });
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
        currentAgentId: null, // 阶段 4: 初始化 agentId
        iteration: 0, // P2: 初始化迭代轮次
      });
      // 重置 reasoning ref
      streamingReasoningRef.current = '';

      // P0: 重置实时工具调用 state + ref (每次 sendMessage 清空上一轮)
      streamingToolCallsRef.current = [];
      setStreamingToolCalls([]);

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
        let finalContent = lastDoneContent ?? streamingContentRef.current;
        const finalReasoning = streamingReasoningRef.current;
        const finalToolCalls = streamingToolCallsRef.current;
        // MEDIUM-2: 若 LLM 没返回任何 content (后端只发 thinking 但没 done.content),
        // 占位符 '🤔 思考中…' 会留在 store。fallback 到错误文案让用户看到明确失败
        if (!finalContent && !finalReasoning && finalToolCalls.length === 0) {
          finalContent = '[错误: 模型未返回任何内容]';
        } else if (
          finalContent === '🤔 思考中…' &&
          !finalReasoning &&
          finalToolCalls.length === 0
        ) {
          finalContent = '[错误: 模型未返回任何内容]';
        }
        if (finalContent || finalReasoning || finalToolCalls.length > 0) {
          updateMessage(assistantId, {
            content: finalContent,
            reasoning_content: finalReasoning || undefined,
            tool_calls: finalToolCalls.length > 0 ? finalToolCalls : undefined,
          });
        }
        streamingContentRef.current = '';
        streamingReasoningRef.current = '';
        streamingToolCallsRef.current = [];
        setStreamingToolCalls([]);
        setStreaming(null);
        cancelRef.current = null;
        resetLoading();
        // HIGH-4: 清空 ref 让 interrupt 知道当前 stream 已结束
        finishStreamRef.current = null;
      };
      // HIGH-4: 注册 finishStream 到 ref 供 interrupt 调用
      finishStreamRef.current = finishStream;

      try {
        // 解构 cancel 用于下次 sendMessage 时取消 (cancel-prev)
        const { cancel } = await chatApi.chatStream(
          sid,
          content,
          {
            onEvent: (evt) => {
              // 阶段 4: 累积 agent_id + 迭代轮次 (供前端显示"当前处理 agent")
              if (evt.agent_id || evt.iteration) {
                setStreaming((prev) =>
                  prev && prev.messageId === assistantId
                    ? {
                        ...prev,
                        currentAgentId: evt.agent_id ?? prev.currentAgentId,
                        iteration: evt.iteration ?? prev.iteration,
                      }
                    : prev,
                );
              }

              // 处理 reasoning 事件：累积 reasoning 内容（支持完整事件和增量事件）
              if ((evt.state === 'reasoning' || evt.state === 'reasoning_delta') && evt.reasoning) {
                streamingReasoningRef.current = streamingReasoningRef.current + evt.reasoning;
                setStreaming((prev) =>
                  prev && prev.messageId === assistantId
                    ? { ...prev, reasoning: streamingReasoningRef.current }
                    : prev,
                );
              }

              // P0: 实时工具调用 — acting 事件到达时立即更新 state + ref
              if (evt.state === 'acting' && evt.tool_call) {
                const tc = evt.tool_call;
                let args: Record<string, unknown> = {};
                try {
                  args = JSON.parse(tc.function.arguments);
                } catch {
                  // ignore parse errors
                }
                // HIGH-3: 记录 tool_call.id,供 observing 用 id 精确匹配 (而非按 index 错配)
                const newTc: ToolCall = {
                  id: tc.id,
                  name: tc.function.name,
                  args,
                };
                streamingToolCallsRef.current = [...streamingToolCallsRef.current, newTc];
                setStreamingToolCalls([...streamingToolCallsRef.current]);
              }
              // P0: observing 事件到达时按 tool_call_id 精确匹配并更新 result
              if (evt.state === 'observing' && evt.tool_result) {
                const tr = evt.tool_result;
                // HIGH-3: 用 tr.tool_call_id 查找匹配项;fallback 到最后一个 (兼容无 id 场景)
                const targetId = tr.tool_call_id;
                const targetIdx = targetId
                  ? streamingToolCallsRef.current.findIndex((t) => t.id === targetId)
                  : streamingToolCallsRef.current.length - 1;
                const targetTc = targetIdx >= 0 ? streamingToolCallsRef.current[targetIdx] : null;
                if (targetTc) {
                  // HIGH-2: 不可变更新 — 创建新对象而非原地 mutation,避免 React.memo 浅比较失效
                  let metadata = targetTc.metadata;
                  try {
                    const parsed = JSON.parse(tr.content);
                    if (parsed && typeof parsed === 'object' && parsed.metadata) {
                      metadata = parsed.metadata;
                    }
                  } catch {
                    // Not JSON, ignore
                  }
                  const newTc: ToolCall = {
                    ...targetTc,
                    result: tr.content,
                    metadata,
                  };
                  // 数组也新建 (targetIdx 处替换,其余共享引用保持稳定)
                  const updated = [
                    ...streamingToolCallsRef.current.slice(0, targetIdx),
                    newTc,
                    ...streamingToolCallsRef.current.slice(targetIdx + 1),
                  ];
                  streamingToolCallsRef.current = updated;
                  setStreamingToolCalls(updated);
                }
              }

              const uiText = agentStateToText(evt.state, evt.tool_call?.function.name);
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
    // HIGH-4: 触发 finishStream() 清理 streaming overlay
    // (之前 interrupt 只调了 cancel + 后端 interrupt,没有清 setStreaming(null),
    //  导致用户看到 '🤔 思考中…' 占位符永远不消失、ActiveAgentIndicator 不消失、
    //  isLoading 不重置、streamingToolCallsRef 持有陈旧数据)
    finishStreamRef.current?.();
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
    /** 阶段 4: 当前流式处理中的 agent ID (供 UI 显示"当前处理 agent") */
    currentAgentId: streaming?.currentAgentId ?? null,
    /** P1/P2: 当前正在流式输出的消息 ID (供 Message 组件判断 isStreaming) */
    streamingMessageId: streaming?.messageId ?? null,
    /** P2: 当前 ReAct 迭代轮次 */
    iteration: streaming?.iteration ?? 0,
    /** P2: 当前流式状态 (供 ActiveAgentIndicator 显示阶段) */
    streamingState: streaming?.state ?? null,
  };
}
