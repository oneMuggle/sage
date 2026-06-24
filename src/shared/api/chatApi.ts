/**
 * Sage API - Chat API
 * 包含同步聊天和流式聊天
 */

import { listen, type UnlistenFn } from './desktopEvent';
import { invoke } from './desktopInvoke';
import type { AgentEvent, ChatConfig, ChatResponse } from './types';
import { ApiException, handleApiError, isValidSessionId, sanitizeInput, withRetry } from './utils';

export const chatApi = {
  async chat(sessionId: string, message: string, config?: ChatConfig): Promise<ChatResponse> {
    // 安全化消息输入
    const safeMessage = sanitizeInput(message);

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

  async interrupt(): Promise<void> {
    try {
      await invoke('interrupt_agent');
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
  ): Promise<{ streamId: string; cancel: () => void }> {
    const safeMessage = sanitizeInput(message);
    if (!isValidSessionId(sessionId)) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的会话ID格式',
        details: { sessionId },
      });
    }
    if (!handlers || typeof handlers.onEvent !== 'function') {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: 'chatStream 缺少 onEvent 回调',
        details: {},
      });
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

    try {
      unlisten = await listen<AgentEvent>(eventName, (evt) => {
        const payload = evt.payload;
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
