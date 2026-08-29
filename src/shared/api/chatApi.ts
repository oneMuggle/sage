/**
 * Sage API - Chat API
 * 包含同步聊天和流式聊天
 */

import { clientLogger } from '../log/client';

import { runDemoChatStream } from './demoChatScript';
import { isDemoMode } from './demoInterceptors';
import { listen, type UnlistenFn } from './desktopEvent';
import { invoke } from './desktopInvoke';
import type { AgentEvent, ChatConfig, ChatOfficeRef, ChatResponse } from './types';
import { ApiException, handleApiError, isValidSessionId, sanitizeInput, withRetry } from './utils';

// DIAG(2026-07-30): 当 stream 以 FAILED 收尾时,把整轮事件序列推到主进程日志,
// 便于定位 '为什么 agent 跑到 max_iterations'。仅用于排查,不参与业务逻辑。
const STREAM_TRACE_MAX = 50;

export const chatApi = {
  async chat(sessionId: string, message: string, config?: ChatConfig): Promise<ChatResponse> {
    const safeMessage = sanitizeInput(message);
    if (isDemoMode()) {
      throw new ApiException({
        error: 'DEMO_MODE_UNSUPPORTED',
        message: '演示模式不支持同步聊天，请使用流式聊天',
        details: {},
      });
    }

    // 验证会话ID
    if (!isValidSessionId(sessionId)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId },
      });
    }

    return withRetry(
      async () => {
        try {
          const response = await invoke<ChatResponse>('agent_chat', {
            sessionId,
            message: safeMessage,
            apiKey: config?.apiKey ?? null,
            apiUrl: config?.apiUrl ?? null,
            model: config?.model ?? null,
            maxContext: config?.maxContext ?? null,
            temperature: config?.temperature ?? null,
            provider: config?.provider ?? null,
            reasoningEffort: config?.reasoningEffort ?? null,
            thinkingBudget: config?.thinkingBudget ?? null,
          });
          return response;
        } catch (error) {
          throw handleApiError(error);
        }
      },
      { maxRetries: 2 },
    ); // chat 操作重试次数少一些
  },

  async interrupt(streamId?: string): Promise<void> {
    try {
      // P0-2 (2026-08-20): 带上 streamId 让后端命中真实运行的 agent。
      // Electron relay camelToSnakeKeys 会把 body 转成 { stream_id }。
      await invoke('interrupt_agent', streamId ? { streamId } : {});
    } catch (error) {
      console.error('中断请求失败:', error);
      // 中断操作不重试，忽略错误
    }
  },

  /**
   * 流式聊天 (PR-6)
   * 1. invoke('agent_chat_stream') 立刻返回 stream_id (UUID)
   * 2. listen('chat-stream-{stream_id}') 订阅 Tauri event
   * 3. 逐事件回调 onEvent; state=done/failed 时调 onDone 并自动 cancel
   * 4. 调用方在 unmount/中断时调返回的 cancel() 释放 listener
   *
   * Task 7 (2026-07-26): optional 5th arg `officeRefs` is forwarded
   * verbatim into the `agent_chat_stream` invoke body. The backend
   * (`backend/office/chat_refs.py`) validates each ref against the active
   * workspace binding and rejects unauthorized refs before streaming.
   *
   * 注: 后端流是 fire-and-forget, 本方法不取消后端; 中断整个 chat 用 chatApi.interrupt()
   */
  async chatStream(
    sessionId: string,
    message: string,
    handlers: {
      onEvent: (event: AgentEvent) => void;
      onError?: (error: Error) => void;
      onDone?: () => void;
    },
    config?: ChatConfig,
    officeRefs?: readonly ChatOfficeRef[],
  ): Promise<{ streamId: string; cancel: () => void }> {
    const safeMessage = sanitizeInput(message);
    if (!handlers || typeof handlers.onEvent !== 'function') {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: 'chatStream 缺少 onEvent 回调',
        details: {},
      });
    }
    const isBtwSession = sessionId === '__btw__';
    if (!isBtwSession && !isValidSessionId(sessionId)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId },
      });
    }
    // 演示模式 (2026-08-27): 不发请求, 按脚本时间线推同形事件流。
    // 仅保留 /btw 使用的特殊会话，其余路径仍遵守 UUID 校验。
    if (isDemoMode()) {
      return runDemoChatStream(sessionId, safeMessage, handlers);
    }

    // 1) 启动流 (同步 invoke, 立即返回 { streamId: "..." } 对象)
    const { streamId } = await invoke<{ streamId: string }>('agent_chat_stream', {
      sessionId,
      message: safeMessage,
      apiKey: config?.apiKey ?? null,
      apiUrl: config?.apiUrl ?? null,
      model: config?.model ?? null,
      maxContext: config?.maxContext ?? null,
      temperature: config?.temperature ?? null,
      provider: config?.provider ?? null,
      reasoningEffort: config?.reasoningEffort ?? null,
      thinkingBudget: config?.thinkingBudget ?? null,
      // Task 7: forwarded as-is. Backend authorizes before reading.
      officeRefs: officeRefs ?? [],
      // Multi-Agent Orchestration: undefined → null,后端默认 auto
      orchestrationMode: config?.orchestrationMode ?? null,
      // Wave 3 A10 (2026-08-14): resume plan_override / run_id 透传。
      plan_override: config?.planOverride ?? null,
      run_id: config?.runId ?? null,
    });
    const eventName = `chat-stream-${streamId}`;

    // 2) 监听事件
    let unlisten: UnlistenFn | null = null;
    let settled = false;

    const cancel = (): void => {
      if (unlisten) {
        try {
          unlisten();
        } catch {
          // ignore
        }
        unlisten = null;
      }
    };

    const finishOnce = (cb: () => void): void => {
      if (settled) return;
      settled = true;
      cancel();
      try {
        cb();
      } catch {
        // 用户回调里抛错不外泄
      }
    };

    // DIAG(2026-07-30): 整轮事件缓冲,用于 FAILED 时 dump 整链到主进程日志
    const trace: AgentEvent[] = [];

    try {
      unlisten = await listen<AgentEvent>(eventName, (evt) => {
        const payload = evt.payload;
        // DIAG(2026-07-30): 仅在 state=failed 时 dump 整轮事件,定位 max_iterations 根因
        trace.push(payload);
        if (trace.length > STREAM_TRACE_MAX) trace.shift();
        try {
          handlers.onEvent(payload);
        } catch (cbErr) {
          // 用户回调抛错 → 终止流,不让坏回调拖死循环
          if (handlers.onError) {
            handlers.onError(cbErr instanceof Error ? cbErr : new Error(String(cbErr)));
          }
          finishOnce(() => handlers.onDone?.());
          return;
        }
        if (payload.state === 'done' || payload.state === 'failed') {
          if (payload.state === 'failed' && payload.error && handlers.onError) {
            // DIAG(2026-07-30): stream 以 FAILED 收尾时,把整轮 trace 推到主进程日志
            // 让主进程侧能看到 LLM 在哪几步反复调工具,从而定位 max_iterations 根因。
            clientLogger.warn('chatStream: stream ended FAILED', {
              streamId,
              error: payload.error,
              iterations: payload.iteration,
              agentId: payload.agent_id,
              traceLen: trace.length,
              trace: trace.map((e) => ({
                state: e.state,
                iteration: e.iteration,
                agentId: e.agent_id,
                toolName: e.tool_call?.function?.name,
                toolResultLen: e.tool_result?.content?.length,
              })),
            });
            // payload.error 可能是后端 LLMError.to_dict() 返回的 dict
            // (含 type/message/status_code),不能直接 new Error(dict)
            // (那会让 message 变成 "[object Object]")。
            // 提取 message 字符串,fallback 到 JSON.stringify 兜底。
            const errPayload = payload.error;
            const errMsg =
              typeof errPayload === 'string'
                ? errPayload
                : ((errPayload as { message?: string }).message ?? JSON.stringify(errPayload));
            handlers.onError(new Error(errMsg));
          }
          finishOnce(() => handlers.onDone?.());
        }
      });
    } catch (listenErr) {
      // listen 失败: 后端流可能已经在推,告知用户
      const err = listenErr instanceof Error ? listenErr : new Error('订阅流式事件失败');
      if (handlers.onError) handlers.onError(err);
      throw new ApiException({
        error: 'STREAM_LISTEN_FAILED',
        message: err.message,
        details: { streamId },
      });
    }

    return { streamId, cancel };
  },
};
