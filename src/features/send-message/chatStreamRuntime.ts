import { type MutableRefObject, useCallback } from 'react';

import { useBtwState } from '../../entities/chat/btwState';
import { usePermissionState } from '../../entities/permission/permissionState';
import { useQuestionState } from '../../entities/question/questionState';
import type { AppSettings, EndpointConfig } from '../../entities/setting/types';
import type { AgentEvent, ChatConfig } from '../../shared/api';
import { clearSessionDraft } from '../../shared/lib/hooks/useSessionDraft';
import { logger } from '../../shared/lib/logger';
import { chatApi, type Message, useStore } from '../../shared/lib/store';
import { normalizeToolCallEnvelope } from '../../shared/lib/toolCallEnvelope';

import { selectSessionSlots, type TaskBoardState, useChatStreamStore } from './chatStreamStore';
import { applyOrchestrationEventToBoard } from './orchestrationEvents';
import {
  isValidCitationsPayload,
  isValidCompactPayload,
  isValidContextPressurePayload,
  isValidMemoriesPayload,
  isValidSkillsPayload,
  isValidSourcesPayload,
} from './transparencyPayload';

/**
 * 从 endpoint baseUrl 启发式推导 LLM provider 字符串。
 *
 * 后端在 PR-7a 后不再硬写 provider="custom",改用请求里的字段。
 * 暂时用 baseUrl 子串匹配,后续 PR 会给 EndpointConfig 加显式 provider
 * 字段(settings UI 让用户选),届时这个函数就退化成兜底。
 *
 * 返回值与 backend LLMConfig.provider 注释里允许的值对齐。
 */
export function inferProviderFromBaseUrl(baseUrl: string | undefined): string | undefined {
  if (!baseUrl) return undefined;
  const u = baseUrl.toLowerCase();
  if (u.includes('generativelanguage.googleapis.com')) return 'gemini';
  if (u.includes('api.openai.com')) return 'openai';
  if (u.includes('api.deepseek.com')) return 'deepseek';
  if (u.includes('anthropic.com')) return 'claude';
  // Ollama / 局域网 / 其它 OpenAI 兼容代理 → 后端默认 'custom'
  return undefined;
}

/** Multi-Agent Orchestration: 编排任务板聚合状态（task_plan/task_status 消费结果）
 *
 * 类型从 chatStreamStore 导出,保证 widget 文件
 *   `import type { TaskBoard } from '.../useChat'`
 * 继续可用,只是底层指向 TaskBoardState（结构等价）。
 */
export type TaskBoard = TaskBoardState;

/** S3 (2026-09-06): 单个会话的活跃流句柄 —— interrupt / 取消旧流按会话定位。 */
export interface ActiveStreamHandle {
  /** 后端 streamId（P0-2: interrupt 让后端命中真实 agent） */
  streamId: string | null;
  /** 前端 listener 取消函数（unlisten） */
  cancel: (() => void) | null;
  /** finishStream —— interrupt 时触发清理（HIGH-4） */
  finish: (() => void) | null;
}

/**
 * P1-6: 排队待发的一条消息。
 *
 * `id` 是 P1-6 新增的 —— 撤回操作需要稳定标识，不能用数组下标：
 * 队列在自动 flush 与用户撤回之间并发变化，下标会指向错误的条目。
 */
export interface PendingChatMessage {
  id: string;
  content: string;
  sid?: string;
  orchestrationMode?: ChatConfig['orchestrationMode'];
}

// A1 (parity-s4): module-level registry of live stream handles.
// Handles used to live only in the hook ref, so a background session stream
// could be watched but never cancelled after leaving the Chat page.
// markStreamActive/markStreamIdle keep this map in sync; TaskCenterWidget
// cancels any session stream via cancelSessionStream (frontend unlisten +
// finishStream cleanup + backend interrupt, same path as MEDIUM-1).
export const activeStreamRegistry = new Map<string, ActiveStreamHandle>();

/**
 * Cancel a session stream from outside useChat (e.g. the task-center capsule).
 * Returns true when a live frontend handle was found and torn down; when no
 * handle exists (e.g. after a renderer reload) it still best-effort notifies
 * the backend and returns false. Never throws.
 */
/**
 * 2026-09 修复: 删除会话的级联清理 —— 旧路径只删 store 里的会话与消息:
 * 1) 后端 agent 流继续跑, 白白消耗 token; 2) chatStreamStore 的会话槽位
 * (streaming/toolCalls/taskBoard/todos)永久残留, 迟到事件可能复活死会话
 * (clearSession 此前全仓库零调用)。顺序: 先取消流(防迟到事件重填),
 * 再清槽位, 最后删会话记录。
 */
export async function deleteSessionCascade(sid: string): Promise<void> {
  try {
    await cancelSessionStream(sid);
  } catch {
    // 非活跃会话 / 后端未起 —— 忽略, 继续清理本地状态
  }
  useChatStreamStore.getState().clearSession(sid);
  clearSessionDraft(sid);
  await useStore.getState().deleteSession(sid);
}

export async function cancelSessionStream(sid: string): Promise<boolean> {
  const handle = activeStreamRegistry.get(sid);
  if (!handle) {
    try {
      await chatApi.interrupt(undefined, sid);
    } catch {
      /* best-effort only */
    }
    return false;
  }
  const cancel = handle.cancel;
  handle.cancel = null;
  try {
    cancel?.();
  } catch {
    /* ignore listener teardown errors */
  }
  try {
    handle.finish?.();
  } catch {
    /* ignore finish errors */
  }
  if (activeStreamRegistry.get(sid) === handle) activeStreamRegistry.delete(sid);
  chatApi.interrupt(handle.streamId ?? undefined, sid).catch(() => {
    /* Interrupt failures are non-critical */
  });
  return true;
}


export function applyTransparencyAndToolEvents(
  evt: AgentEvent,
  ctx: {
    sid: string;
    assistantId: string;
    clientMessageId: string;
    requestId: string;
    addMessage: (msg: Message) => void;
    updateMessage: (id: string, patch: Partial<Message>) => void;
  },
): void {
  const { sid, assistantId, clientMessageId, requestId, addMessage, updateMessage } = ctx;
  // R38: 透明度增强事件 — 技能激活 / 记忆召回 / 上下文压缩
  // 这些事件不影响对话主流程，仅用于 UI 展示。fail-safe: 任何
  // 异常只跳过更新，绝不阻断聊天。
  // MEDIUM-2: 运行时载荷校验 — 防止伪造/畸形数据进入气泡文案。
  // 校验不通过时丢弃该事件（不更新 UI），而非按畸形值渲染。
  // R97: 四类载荷校验收敛到 transparencyPayload.ts（主/重接/btw 共用）。
  if (evt.state === 'memory_used' && evt.memories) {
    if (isValidMemoriesPayload(evt.memories)) {
      updateMessage(assistantId, {
        memory_refs: evt.memories,
        memory_applied: evt.memories.length,
      });
    } else {
      logger.warn(requestId, 'R38.memory_used.malformed', evt.memories);
    }
  }
  if (evt.state === 'skill_activated' && evt.skills) {
    if (isValidSkillsPayload(evt.skills)) {
      updateMessage(`u-${clientMessageId}`, { activated_skills: evt.skills });
    } else {
      logger.warn(requestId, 'R38.skill_activated.malformed', evt.skills);
    }
  }
  // TM2 (DSH 对标 R11): 上下文水位 —— 写入 store 供输入区
  // 水位徽章渲染（<0.6 徽章不渲染，默认安静）。
  if (evt.state === 'context_pressure' && evt.context_pressure) {
    if (isValidContextPressurePayload(evt.context_pressure)) {
      useStore.getState().setContextPressure({
        session_id: sid,
        pressure: evt.context_pressure.pressure,
        total_tokens: evt.context_pressure.total_tokens,
        budget_tokens: evt.context_pressure.budget_tokens,
      });
    } else {
      logger.warn(
        requestId,
        'TM2.context_pressure.malformed',
        evt.context_pressure,
      );
    }
  }
  if (evt.state === 'compact_triggered' && evt.compact) {
    if (isValidCompactPayload(evt.compact)) {
      // 插入特殊系统消息气泡（非普通 assistant 气泡）
      // LOW-1: 统一口径 —— "before → after 条（removed 条历史已合并为摘要）"
      const compactMsg: Message = {
        id: crypto.randomUUID(),
        session_id: sid,
        role: 'system',
        content: `📦 上下文已压缩：${evt.compact.before} → ${evt.compact.after} 条（${evt.compact.removed} 条历史已合并为摘要）`,
        created_at: Date.now(),
        compact_info: { ...evt.compact },
      };
      addMessage(compactMsg);
    } else {
      logger.warn(requestId, 'R38.compact_triggered.malformed', evt.compact);
    }
  }
  // r71: 附件检索注入溯源 → 引用明细随消息落库（气泡内展示）。
  // R81 修复: 多附件各推一个事件, 按 media_id 合并而非整体替换
  // （updateMessage 是浅合并, 直接赋值会丢掉前一个附件的引用）。
  // R97: 载荷校验对齐重接路径（每项须有字符串 media_id）。
  if (evt.state === 'attachment_rag_used' && evt.citations?.length) {
    if (isValidCitationsPayload(evt.citations)) {
      const existing = useStore
        .getState()
        .messages.find((m) => m.id === assistantId)?.rag_citations;
      const merged = [...(existing ?? [])];
      for (const c of evt.citations) {
        const idx = merged.findIndex((x) => x.media_id === c.media_id);
        if (idx >= 0) merged[idx] = c;
        else merged.push(c);
      }
      updateMessage(assistantId, { rag_citations: merged });
    }
  }
  // R81: 统一参考来源 —— 检索类工具命中（web/wiki/MCP）done 前
  // 一次性推送。载荷校验对齐 MEDIUM-2: 数组且每项 kind 合法
  // （R92: 校验收敛到 transparencyPayload.ts，主/重接/btw 三路径共用）。
  if (evt.state === 'sources_used' && evt.sources) {
    if (isValidSourcesPayload(evt.sources)) {
      updateMessage(assistantId, { sources: evt.sources });
    } else {
      logger.warn(requestId, 'R81.sources_used.malformed', evt.sources);
    }
  }

  // 处理 reasoning 事件：三种 state 不同处理 (2026-09-02 bug fix)
  //   - reasoning_delta: 增量, appendReasoning 累积
  //   - reasoning:       旧路径兼容 (非流式 LLM, 直接 yield 全量), append 累加
  //   - reasoning_final: 后端每段末尾发 done_reasoning 全量, replace 替换
  //                     (不再 append → 避免与 reasoning_delta 重复显示)
  if (evt.state === 'reasoning_delta' && evt.reasoning) {
    useChatStreamStore.getState().appendReasoning(sid, assistantId, evt.reasoning);
  } else if (evt.state === 'reasoning' && evt.reasoning) {
    useChatStreamStore.getState().appendReasoning(sid, assistantId, evt.reasoning);
  } else if (evt.state === 'reasoning_final' && evt.reasoning) {
    useChatStreamStore.getState().replaceReasoning(sid, assistantId, evt.reasoning);
  }

  // P0: 实时工具调用 — acting 事件到达时立即追加到 store
  // (2026-08-19) store 内按 id 去重,appendOrUpdateToolCall 自身持有列表
  if (evt.state === 'acting' && evt.tool_call) {
    const tc = evt.tool_call;
    let args: Record<string, unknown> = {};
    try {
      args = JSON.parse(tc.function.arguments);
    } catch {
      // ignore parse errors
    }
    // HIGH-3: 记录 tool_call.id,供 observing 用 id 精确匹配 (而非按 index 错配)
    useChatStreamStore.getState().appendOrUpdateToolCall(sid, {
      id: tc.id,
      name: tc.function.name,
      args,
    });
  }
  // P0: observing 事件到达时按 tool_call_id 精确匹配并更新 result
  // (2026-08-19) store 持有工具调用列表,appendOrUpdateToolCall 按 id 查找
  // 已有项并合并新字段(原 ref 切片逻辑等价)
  if (evt.state === 'observing' && evt.tool_result) {
    const tr = evt.tool_result;
    // HIGH-3: 用 tr.tool_call_id 查找匹配项;fallback 到最后一个 (兼容无 id 场景)
    const targetId = tr.tool_call_id;
    const currentTcs = selectSessionSlots(
      useChatStreamStore.getState(),
      sid,
    ).streamingToolCalls;
    const targetIdx = targetId
      ? currentTcs.findIndex((t) => t.id === targetId)
      : currentTcs.length - 1;
    const targetTc = targetIdx >= 0 ? currentTcs[targetIdx] : null;
    if (targetTc) {
      // HIGH-2: 不可变更新 — 创建新对象而非原地 mutation,避免 React.memo 浅比较失效
      let metadata = targetTc.metadata;
      try {
        const parsed = JSON.parse(tr.content);
        if (parsed && typeof parsed === 'object') {
          // Extract existing metadata if present
          if (parsed.metadata) {
            metadata = parsed.metadata;
          }
          // Phase 3 (2026-09-12): extract multimodal tool output
          // TTS/image generation tools return media_ref/media_refs + api_url/api_urls
          if (!metadata) metadata = {};
          if (parsed.media_ref) {
            metadata.mediaRefs = [parsed.media_ref];
          } else if (parsed.media_refs && Array.isArray(parsed.media_refs)) {
            metadata.mediaRefs = parsed.media_refs;
          }
          if (parsed.api_url) {
            metadata.apiUrls = [parsed.api_url];
          } else if (parsed.api_urls && Array.isArray(parsed.api_urls)) {
            metadata.apiUrls = parsed.api_urls;
          }
        }
      } catch {
        // Not JSON, ignore
      }
      // 防御: 后端历史 bug (execute_code_tool 异常退出返回 dict error)
      // 可能让 tr.content 是对象而非字符串,这里强制序列化为字符串以避免
      // React 渲染对象时触发 "Objects are not valid as a React child"。
      const safeResult =
        typeof tr.content === 'string' ? tr.content : JSON.stringify(tr.content ?? '');
      // R19-W1: 拦截信封归一化（提取可读 content + 提升 metadata 到
      // ToolCall.metadata），与 Message 历史回读路径共用同一实现
      useChatStreamStore
        .getState()
        .appendOrUpdateToolCall(
          sid,
          normalizeToolCallEnvelope({ ...targetTc, result: safeResult, metadata }),
        );
    }
  }

}

export function useChatReattachAndBtw(params: {
  addMessage: (msg: Message) => void;
  updateMessage: (id: string, patch: Partial<Message>) => void;
  markStreamActive: (sid: string, handle: ActiveStreamHandle) => void;
  markStreamIdle: (sid: string) => void;
  chatEndpoint: EndpointConfig | null | undefined;
  settings: AppSettings;
  btwCancelRef: MutableRefObject<(() => void) | null>;
  setIsBtwStreaming: (v: boolean) => void;
}) {
  const {
    addMessage,
    updateMessage,
    markStreamActive,
    markStreamIdle,
    chatEndpoint,
    settings,
    btwCancelRef,
    setIsBtwStreaming,
  } = params;
  // R25-D4: reattach —— renderer 重载/切回会话时,后端仍在跑的 chat 流
  // 通过 activeStream 查询 + listenStream 重新接上。BroadcastQueue 会把
  // attach 前缓冲的事件重放给首个 subscriber,占位消息能追上完整内容。
  // 精简事件面: content/reasoning 增量 + done/failed 终态 + 审批/提问
  // 转发（R35: 编排任务板经 orchestrationEvents 在重放时完整重建）。
  const reattachActiveStream = useCallback(
    async (sid: string) => {
      // Reserve synchronously, BEFORE activeStream's first await. The same map
      // also owns regular sends across hook remounts / StrictMode instances.
      if (!sid || activeStreamRegistry.has(sid)) return;
      let assistantId: string | null = null;
      let finished = false;
      let acc = '';
      let accReasoning = '';
      const handle: ActiveStreamHandle = { streamId: null, cancel: null, finish: null };
      const finishReattach = (finalContent: string | null, errText?: string) => {
        if (finished) return;
        finished = true;
        try {
          handle.cancel?.();
        } catch {
          // Listener teardown must not prevent clearing session state.
        }
        handle.cancel = null;
        if (activeStreamRegistry.get(sid) !== handle) return;
        if (assistantId === null) {
          markStreamIdle(sid);
          return;
        }
        if (finalContent !== null) {
          updateMessage(assistantId, { content: finalContent });
        } else if (errText) {
          updateMessage(assistantId, { content: `[错误] ${errText}` });
        }
        useChatStreamStore.getState().clearStream(sid, assistantId);
        useChatStreamStore.getState().resetToolCalls(sid);
        markStreamIdle(sid);
        usePermissionState.getState().resolve(sid);
        useQuestionState.getState().resolve(sid);
        // R25-D5: 对账 —— producer 的 DONE 持久化是权威,重载服务端真值
        void useStore.getState().loadMessages(sid);
        void useStore.getState().loadSessions();
      };

      handle.finish = () => finishReattach(acc || null);
      // A lookup reservation is not a running reply: do not disable idle chat actions.
      activeStreamRegistry.set(sid, handle);
      try {
        const streamId = await chatApi.activeStream(sid);
        if (finished || activeStreamRegistry.get(sid) !== handle) return;
        if (!streamId) {
          finishReattach(null);
          return;
        }
        handle.streamId = streamId;
        markStreamActive(sid, handle);
        const messageId = crypto.randomUUID();
        assistantId = messageId;
        addMessage({
          id: messageId,
          session_id: sid,
          role: 'assistant',
          content: '',
          created_at: Date.now(),
        });
        useChatStreamStore.getState().startStream(sid, messageId, { initialContent: '' });
        const { cancel } = await chatApi.listenStream(streamId, {
          onEvent: (evt) => {
            if (finished) return;
            if (evt.type === 'session_updated') {
              void useStore.getState().loadSessions();
              return;
            }
            if (evt.state === 'content_delta' && evt.content) {
              acc += evt.content;
              useChatStreamStore.getState().replaceContent(sid, messageId, acc);
              return;
            }
            if ((evt.state === 'reasoning_delta' || evt.state === 'reasoning') && evt.reasoning) {
              accReasoning += evt.reasoning;
              useChatStreamStore.getState().replaceReasoning(sid, messageId, accReasoning);
              return;
            }
            if (evt.state === 'reasoning_final') {
              accReasoning = evt.reasoning ?? accReasoning;
              useChatStreamStore.getState().replaceReasoning(sid, messageId, accReasoning);
              return;
            }
            if (evt.state === 'permission_request' && evt.permission_request) {
              usePermissionState.getState().setFromEvent(evt.permission_request, sid);
              return;
            }
            if (evt.state === 'ask_user_question' && evt.user_question) {
              useQuestionState.getState().setFromEvent(evt.user_question, sid);
              return;
            }
            if (evt.state === 'done') {
              const finalContent = evt.content ?? acc;
              finishReattach(finalContent);
              return;
            }
            if (evt.state === 'failed') {
              // 2026-09 修复: error 信封统一为 dict | string 双态, 提取 message
              const raw = evt.error;
              const errText = typeof raw === 'string' ? raw : (raw?.message ?? '流式失败');
              finishReattach(null, errText);
              return;
            }
            // R35: 编排/任务板事件走共享应用器 —— 重放时任务板/live 态
            // 完整重建（与主路径同一套 store 写入）。
            if (applyOrchestrationEventToBoard(evt, sid)) {
              return;
            }
            // r77: 重接路径补 memory_used —— 重放时 memory_refs 不丢失（与主路径同口径）
            // R87/R97: 载荷校验走共享 helper（transparencyPayload.ts）
            if (evt.state === 'memory_used' && evt.memories) {
              if (
                isValidMemoriesPayload(evt.memories) &&
                evt.memories.length > 0
              ) {
                updateMessage(messageId, {
                  memory_refs: evt.memories,
                  memory_applied: evt.memories.length,
                });
              }
            }
            // r71: 重接路径同主路径 —— 检索引用明细随消息落库
            // R87/R97: 载荷校验走共享 helper（每项须有字符串 media_id）
            if (evt.state === 'attachment_rag_used' && evt.citations?.length) {
              if (isValidCitationsPayload(evt.citations)) {
                const existing = useStore
                  .getState()
                  .messages.find((m) => m.id === messageId)?.rag_citations;
                const merged = [...(existing ?? [])];
                for (const c of evt.citations) {
                  const idx = merged.findIndex((x) => x.media_id === c.media_id);
                  if (idx >= 0) merged[idx] = c;
                  else merged.push(c);
                }
                updateMessage(messageId, { rag_citations: merged });
              }
            }
            // R81: 重接路径同主路径 —— 统一参考来源回放
            // R85: 载荷校验对齐主路径 MEDIUM-2 口径（R92 收敛到共享 helper）。
            if (evt.state === 'sources_used' && isValidSourcesPayload(evt.sources)) {
              updateMessage(messageId, { sources: evt.sources });
            }
            // 其余事件（工具 acting/observing 等）降级为 streaming meta 文案
            useChatStreamStore.getState().setStreamingMeta(sid, messageId, {
              state: evt.state,
            });
          },
          onError: (err) => finishReattach(null, err.message),
          onDone: () => finishReattach(acc || null),
        });
        if (finished || activeStreamRegistry.get(sid) !== handle) cancel();
        else handle.cancel = cancel;
      } catch {
        finishReattach(null, '重新接上流失败');
      }
    },
    [addMessage, updateMessage, markStreamActive, markStreamIdle],
  );

  // Phase 6: /btw 补充消息
  const askBtw = useCallback(
    async (question: string) => {
      // 取消之前的 btw 流
      if (btwCancelRef.current) {
        try {
          btwCancelRef.current();
        } catch {
          /* ignore */
        }
        btwCancelRef.current = null;
      }

      // 重置 btw 状态
      useBtwState.getState().open(question);

      try {
        const { cancel } = await chatApi.chatStream(
          '__btw__',
          question,
          {
            onEvent: (evt) => {
              if (evt.state === 'content_delta' && evt.content) {
                useBtwState.getState().appendDelta(evt.content);
              } else if (evt.state === 'sources_used' && evt.sources) {
                // R92: /btw 走同一 /chat/stream 管道 —— sources_used 同样到达，
                // 载荷校验（共享 helper）通过后写入 btw 状态（浮层渲染）。
                if (isValidSourcesPayload(evt.sources)) {
                  useBtwState.getState().setSources(evt.sources);
                }
              } else if (evt.state === 'done') {
                if (evt.content) {
                  useBtwState.getState().appendDelta(evt.content);
                }
                setIsBtwStreaming(false);
                btwCancelRef.current = null;
              } else if (evt.state === 'failed') {
                useBtwState.getState().setLoading(false);
                setIsBtwStreaming(false);
                btwCancelRef.current = null;
              }
            },
            onError: () => {
              useBtwState.getState().setLoading(false);
              setIsBtwStreaming(false);
              btwCancelRef.current = null;
            },
            onDone: () => {
              setIsBtwStreaming(false);
              btwCancelRef.current = null;
            },
          },
          // 使用主 chat 的配置
          {
            apiKey: chatEndpoint?.apiKey,
            apiUrl: chatEndpoint?.baseUrl,
            model: settings.modelSelections.chatModel.modelId ?? undefined,
            maxContext: settings.maxContext,
            autoContext: settings.autoContext,
            temperature: settings.temperature,
            provider: chatEndpoint?.baseUrl
              ? (() => {
                  const u = chatEndpoint.baseUrl.toLowerCase();
                  if (u.includes('generativelanguage.googleapis.com')) return 'gemini';
                  if (u.includes('api.openai.com')) return 'openai';
                  if (u.includes('api.deepseek.com')) return 'deepseek';
                  if (u.includes('anthropic.com')) return 'claude';
                  return undefined;
                })()
              : undefined,
          },
        );

        btwCancelRef.current = cancel;
        setIsBtwStreaming(true);
      } catch (err) {
        logger.error('askBtw.failed', err instanceof Error ? err.message : String(err));
        useBtwState.getState().setLoading(false);
        setIsBtwStreaming(false);
      }
    },
    [chatEndpoint, settings, btwCancelRef, setIsBtwStreaming],
  );

  return { reattachActiveStream, askBtw };
}
