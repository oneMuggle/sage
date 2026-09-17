import { useCallback, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

import { useBtwState } from '../../entities/chat/btwState';
import { usePermissionState } from '../../entities/permission/permissionState';
import { useQuestionState } from '../../entities/question/questionState';
import { resolveEndpoint } from '../../entities/setting/types';
import {
  ApiException,
  type ChatConfig,
  type ChatOfficeRef,
  type TaskPlanItem,
} from '../../shared/api';
import { agentStateToText } from '../../shared/lib/agentStateMapping';
import {
  mapAgentErrorToText,
  mapLLMErrorToText,
  type LLMErrorResponse,
} from '../../shared/lib/errorMapping';
import { clearSessionDraft } from '../../shared/lib/hooks/useSessionDraft';
import { logger } from '../../shared/lib/logger';
// Task 5: modelWindows imports removed — frontend no longer computes history budget.
// Backend now resolves effective window from catalog and computes budget.
import { chatApi, useStore, type Message } from '../../shared/lib/store';
import { useSettings } from '../manage-settings/useSettings';

import { selectSessionSlots, useChatStreamStore, type TaskBoardState } from './chatStreamStore';
import { applyOrchestrationEventToBoard } from './orchestrationEvents';
import { notifySession, shouldNotify } from './sessionNotify';
import { THINKING_PLACEHOLDER } from './thinkingPlaceholder';

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

/** Multi-Agent Orchestration: 编排任务板聚合状态（task_plan/task_status 消费结果）
 *
 * 类型从 chatStreamStore 导出,保证 widget 文件
 *   `import type { TaskBoard } from '.../useChat'`
 * 继续可用,只是底层指向 TaskBoardState（结构等价）。
 */
export type TaskBoard = TaskBoardState;

/** S3 (2026-09-06): 单个会话的活跃流句柄 —— interrupt / 取消旧流按会话定位。 */
interface ActiveStreamHandle {
  /** 后端 streamId（P0-2: interrupt 让后端命中真实 agent） */
  streamId: string | null;
  /** 前端 listener 取消函数（unlisten） */
  cancel: (() => void) | null;
  /** finishStream —— interrupt 时触发清理（HIGH-4） */
  finish: (() => void) | null;
}

// A1 (parity-s4): module-level registry of live stream handles.
// Handles used to live only in the hook ref, so a background session stream
// could be watched but never cancelled after leaving the Chat page.
// markStreamActive/markStreamIdle keep this map in sync; TaskCenterWidget
// cancels any session stream via cancelSessionStream (frontend unlisten +
// finishStream cleanup + backend interrupt, same path as MEDIUM-1).
const activeStreamRegistry = new Map<string, ActiveStreamHandle>();

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

export function useChat() {
  // S3 (2026-09-06) 多会话并行: "在流中"状态从 hook 级单布尔改为 **按会话**
  // 的 Set。跨会话互不阻塞（会话 A 流式中可直接在会话 B 发送 → 两条流后端
  // 并行跑），同会话内仍串行 —— 忙时消息入队（U5），当前回复结束后自动发送。
  // activeSids(state) 驱动 re-render；activeSidsRef 同步镜像供守卫读取。
  const [activeSids, setActiveSids] = useState<ReadonlySet<string>>(new Set());
  const activeSidsRef = useRef<Set<string>>(new Set());
  // sid → 活跃流句柄（S3: cancelRef/streamIdRef/finishStreamRef 单例的键控版）
  const activeHandleRef = useRef<Map<string, ActiveStreamHandle>>(new Map());
  const [error, setError] = useState<string | null>(null);
  // 2026-09 修复: 记录错误归属会话 —— 后台会话 A 失败时, 横幅不应出现在
  // 用户正在看的会话 B (且旧实现的"重试"按钮会重发 B 的消息)。
  const [errorSessionId, setErrorSessionId] = useState<string | null>(null);
  // PM2 (round8): 计划模式完成的会话 ID —— 非空时 Chat 渲染"按计划执行"批准条。
  const [planApprovalFor, setPlanApprovalFor] = useState<string | null>(null);
  const { messages, addMessage, updateMessage, currentSessionId, loadMessages } = useStore();
  const { settings } = useSettings();

  // U5 (对标增强第二轮批次 B): 流式中用户继续发送 → 入队,当前回复自然
  // 结束(onDone)后自动发送。错误/中断路径不自动 flush——连续失败场景
  // 自动重发只会重复报错。S3: 队列按会话隔离,A 队列的消息不会在 B 的
  // 流结束后被误发。
  const pendingMessagesRef = useRef<
    Array<{
      content: string;
      sid?: string;
      orchestrationMode?: ChatConfig['orchestrationMode'];
    }>
  >([]);
  const sendMessageRef = useRef<typeof sendMessage | null>(null);

  // 流式当前 assistant 消息的内容覆盖 (派生 messages 的最后一条) —— 2026-08-19
  // 搬到 chatStreamStore(独立 zustand),跨路由切换保留,避免 Chat 页卸载后
  // widget 看到 '🤔 思考中…' 占位符看不到真实 LLM 进度。
  // S2: 读当前会话的槽位 —— 切到会话 B 就看 B 的实时进度(A 的流在后台
  // 继续累积,切回 A 时内容完整可见)。
  const { streaming, streamingToolCalls, taskBoard } = useChatStreamStore((s) =>
    selectSessionSlots(s, currentSessionId),
  );

  // Phase 6: /btw 补充消息状态(component-local,与流式 chat 无关)
  const [isBtwStreaming, setIsBtwStreaming] = useState(false);
  const btwCancelRef = useRef<(() => void) | null>(null);

  const chatEndpoint = resolveEndpoint(settings.modelSelections.chatModel, settings.endpoints);

  // S3: isLoading 语义收窄为"当前会话是否在流中"（此前是 hook 级单布尔,
  //  会话 A 流式中切到 B,B 的输入框也被禁用）。Chat 页所有 isLoading 消费
  //  (ChatInput 禁用 / compact / learn / fork 守卫)都是当前会话语义,收窄后
  //  行为恰好正确;流仍在后台跑,不受影响。
  const isLoading =
    currentSessionId != null && (activeSids.has(currentSessionId) || streaming != null);

  const markStreamActive = useCallback((sid: string, handle: ActiveStreamHandle): void => {
    activeHandleRef.current.set(sid, handle);
    activeStreamRegistry.set(sid, handle);
    activeSidsRef.current.add(sid);
    setActiveSids(new Set(activeSidsRef.current));
  }, []);

  const markStreamIdle = useCallback((sid: string): void => {
    activeHandleRef.current.delete(sid);
    activeStreamRegistry.delete(sid);
    activeSidsRef.current.delete(sid);
    setActiveSids(new Set(activeSidsRef.current));
  }, []);

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
    async (
      content: string,
      sessionId?: string,
      officeRefs?: readonly ChatOfficeRef[],
      orchestrationMode?: ChatConfig['orchestrationMode'],
      opts?: {
        planOverride?: TaskPlanItem[];
        runId?: string;
        planMode?: boolean;
        /** 对标 S2: 临时聊天（本轮不读写长期记忆） */
        memoryDisabled?: boolean;
        /** R23-D2: 聊天图片输入（base64 data URL，≤4 张/单张 5MiB） */
        images?: string[];
        attachmentMediaIds?: string[];
      },
    ) => {
      const sid = sessionId ?? currentSessionId;
      if (!sid) return;
      // S3: 守卫按会话 —— 只有**同一会话**已有流在跑时才入队;其它会话
      // 的流与本会话无关,不再被 isLoading 全局守卫误伤。
      if (activeSidsRef.current.has(sid)) {
        // RT5 (round7): 会话忙时先尝试 steering —— 用户补充指示注入当前
        // run（下一迭代边界生效），而不是只能排队成"下一个新 run"。
        // 仅普通聊天路径注入；编排模式的转向走 orch steering（ContextInput），
        // steer 失败（流已结束/不在运行窗口）回退既有队列语义。
        if (!orchestrationMode) {
          const activeStreamId = activeHandleRef.current.get(sid)?.streamId;
          if (activeStreamId && (await chatApi.steer(activeStreamId, content))) {
            toast.info('已转达，将在下一迭代边界生效');
            return;
          }
        }
        // U5: 忙时不再丢弃消息——入队,当前回复自然结束后自动发送
        pendingMessagesRef.current.push({ content, sid, orchestrationMode });
        toast.info('已加入队列,当前回复完成后自动发送');
        return;
      }

      // 安全网: 清理该会话的遗留流(React StrictMode 双调用 / 双击等极端
      // 场景)。正常路径守卫已拦住,不会走到这里。S3: 只清**同会话**的流,
      // 跨会话流保持后台并行(旧实现 cancelRef 单例会误伤其它会话)。
      const prevHandle = activeHandleRef.current.get(sid);
      if (prevHandle) {
        if (prevHandle.cancel) {
          try {
            prevHandle.cancel();
          } catch {
            /* ignore */
          }
          activeHandleRef.current.delete(sid);
          // MEDIUM-1: 同时通知后端中断正在跑的 stream,避免 cancel 只 unlisten 前端
          // 而后端继续消耗 LLM token。fire-and-forget — interrupt 失败不影响新消息发送
          // P0-2 (2026-08-20): 把 streamId 传给后端,让 /interrupt 命中真实 agent。
          chatApi.interrupt(prevHandle.streamId ?? undefined, sid).catch(() => {
            /* Interrupt failures are non-critical */
          });
        }
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

      markStreamActive(sid, { streamId: null, cancel: null, finish: null });
      setError(null);
      setErrorSessionId(null);

      const userMessage: Message = {
        id: crypto.randomUUID(),
        session_id: sid,
        role: 'user',
        content,
        created_at: Date.now(),
      };
      addMessage(userMessage);

      if (!chatEndpoint?.baseUrl) {
        // 仍记录错误供上层展示,但消息已经进 store
        setError('未配置 API 地址，请在设置中配置');
        setErrorSessionId(sid);
        markStreamIdle(sid);
        return;
      }

      if (!settings.modelSelections.chatModel.modelId) {
        setError('未选择对话模型，请在设置中配置');
        setErrorSessionId(sid);
        markStreamIdle(sid);
        return;
      }

      // PR-6: 先占位 assistant message, 流式过程中累积 content
      // 2026-09-13 P0: 哨兵值抽为 THINKING_PLACEHOLDER，Message 据此渲染
      // shimmer 占位而非把占位文案当 markdown 静态文本。
      const assistantId = crypto.randomUUID();
      const assistantMessage: Message = {
        id: assistantId,
        session_id: sid,
        role: 'assistant',
        content: THINKING_PLACEHOLDER,
        created_at: Date.now(),
      };
      addMessage(assistantMessage);
      // startStream 内部已重置该会话槽位的 content/reasoning/streamingToolCalls/
      // taskBoard — 流式进度全部走 store,跨路由切换保留(2026-08-19)。
      // S2: 只重置本会话槽位,并行会话互不覆盖。
      useChatStreamStore.getState().startStream(sid, assistantId, {
        initialContent: THINKING_PLACEHOLDER,
      });

      const config: ChatConfig = {
        apiKey: chatEndpoint.apiKey,
        apiUrl: chatEndpoint.baseUrl,
        model: settings.modelSelections.chatModel.modelId ?? undefined,
        // Task 5 (2026-09-15): send raw maxContext + autoContext to backend.
        // Backend resolves effective window from catalog and computes history budget.
        // No longer sending computed historyBudgetFor() — that was the bug.
        maxContext: settings.maxContext,
        autoContext: settings.autoContext,
        temperature: settings.temperature,
        // 从 baseUrl 推导 provider,后端不再硬写 "custom"。
        // TODO(PR-7a+): 给 EndpointConfig 加 provider 字段,这里直接读,
        // 不再靠 URL 启发式。详见 docs/plans/2026-06-17_thinking-passthrough.md
        provider: inferProviderFromBaseUrl(chatEndpoint.baseUrl),
        // 由 /orchestrate /single 斜杠命令传入;普通消息 undefined → 后端 auto
        orchestrationMode,
        // Wave 3: resume 恢复流透传
        planOverride: opts?.planOverride,
        runId: opts?.runId,
        // PM1 (round8): 计划模式透传（本次 run 只读 + 计划指令）
        planMode: opts?.planMode,
        memoryDisabled: opts?.memoryDisabled,
      };

      const appendContent = (next: string): void => {
        // I5: 流式逐字 — appendContent 通过 store 累加 (跨路由切换保留)
        useChatStreamStore.getState().appendContent(sid, assistantId, next);
      };

      // S8 (round4): 后台会话注意力通知 —— 目标会话非当前查看 / 窗口不可见
      // 时,在完成/失败/等审批三个节点发 OS 通知;点击由 App 的桥接跳转回会话。
      const maybeNotify = (kind: 'done' | 'failed' | 'approval', body: string): void => {
        if (!shouldNotify(sid, currentSessionId)) return;
        const labels = { done: '已完成', failed: '运行失败', approval: '等待审批' } as const;
        const session = useStore.getState().sessions.find((s) => s.id === sid);
        const title = session?.title ? `${session.title} · ${labels[kind]}` : labels[kind];
        notifySession({ sessionId: sid, title, body });
      };

      // I5-2: 中间态 (thinking/acting/observing) 的 uiText 应"覆盖"而非"追加"，
      // 避免 "🤔 思考中…🤔 思考中…" 这种重复前缀 bug。
      // appendContent 用于累积真实回答 (content_delta / done.content)，
      // replaceContent 用于切换中间态占位符。
      const replaceContent = (next: string): void => {
        useChatStreamStore.getState().replaceContent(sid, assistantId, next);
      };

      const handleError = (err: unknown): void => {
        logger.error(requestId, 'useChat.send.failed', err);
        if (err instanceof ApiException && err.llmError) {
          setError(mapLLMErrorToText(err.llmError));
          setErrorSessionId(sid);
          return;
        }
        const apiErr = err as {
          llmError?: LLMErrorResponse;
          error?: LLMErrorResponse;
          message?: string;
        };
        if (apiErr.llmError || apiErr.error) {
          setError(mapLLMErrorToText(apiErr.llmError ?? apiErr.error!));
          setErrorSessionId(sid);
          return;
        }
        // 后端 agent.run_loop / agent_tool 在 FAILED 收尾时把 ``payload.error``
        // 包成 ``new Error(errMsg)``（见 chatApi.ts:198-199），所以这里
        // 只能从 ``Error.message`` 拿到原始错误码。先查 agent runtime 表
        // （max_iterations_exceeded / tool_budget_exceeded / subagent_*），
        // 命中就用中文提示；不命中再退回 ``err.message``（保留网络/HTTP 错误）。
        const raw = err instanceof Error ? err.message : String(err ?? '');
        const agentText = mapAgentErrorToText(raw);
        setError(agentText ?? raw ?? '发送消息失败');
        setErrorSessionId(sid);
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
      // flushQueue=true 仅限流自然结束(onDone) —— 错误/中断不自动发队列消息
      const finishStream = (flushQueue = false): void => {
        if (finished) return;
        finished = true;
        // 2026-08-19: 从 store 读最新流式内容(跨路由保留,finishStream 内
        // 不再持有 ref — store 是单一数据源)。S2: 读本会话槽位。
        const streamSnapshot = selectSessionSlots(useChatStreamStore.getState(), sid).streaming;
        // 优先用 done 事件自带的完整 content (避免混入 thinking 占位符)
        // 退回到 store streaming.content (向后兼容旧的非流式 done 事件)
        let finalContent = lastDoneContent ?? streamSnapshot?.content ?? '';
        const finalReasoning = streamSnapshot?.reasoning ?? '';
        const finalToolCalls = selectSessionSlots(
          useChatStreamStore.getState(),
          sid,
        ).streamingToolCalls;
        // MEDIUM-2: 若 LLM 没返回任何 content (后端只发 thinking 但没 done.content),
        // 占位符 '🤔 思考中…' 会留在 store。fallback 到错误文案让用户看到明确失败
        if (!finalContent && !finalReasoning && finalToolCalls.length === 0) {
          finalContent = '[错误: 模型未返回任何内容]';
        } else if (
          finalContent === THINKING_PLACEHOLDER &&
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
        // 2026-08-19: 精准重置流式 state + toolCalls,**不清 taskBoard**
        // (与原 commit 一致:finishStream 旧实现只 setStreaming(null) + 清 ref,
        //  taskBoard 留到下条消息 startStream 触发重置。
        //  resetAll() 会顺手清掉 taskBoard,破坏 useChat.taskBoard 单测:
        //  "accumulates task_plan then task_status into board" 等依赖
        //  finishStream 后 taskBoard 仍可见。clearStream + resetToolCalls
        //  组合即可,语义等价于旧 setStreaming(null) + 清 ref)
        useChatStreamStore.getState().clearStream(sid, assistantId);
        useChatStreamStore.getState().resetToolCalls(sid);
        // S3: 注销本会话的活跃句柄(替代旧 cancelRef/streamIdRef/finishStreamRef 清理)
        markStreamIdle(sid);
        // M1: 流结束/错误 → 关闭遗留的审批对话框(后端 gate 已超时 fail-closed,
        // 对话框里的请求必然已失效,不能再让 UI 卡着)。S3: 只关**本会话**的
        // 挂起审批 —— 并行会话 B 的审批不能被 A 的流结束误关。
        usePermissionState.getState().resolve(sid);
        // M2 part B: 同理关闭遗留的提问对话框(后端 gate 已超时按空应答处理)
        useQuestionState.getState().resolve(sid);
        // 流结束后刷新侧栏会话列表（获取自动生成的标题 + S1 落库的运行态徽章）
        // hex 路径无 NDJSON session_updated 事件，此处兜底刷新
        void useStore.getState().loadSessions();
        // R25-D5: 消息对账 —— 网关/scheduler 等外部写库方不经本渲染进程，
        // 流结束后以服务端为准刷新一次，消除"开着会话看不到新消息"的窗口
        // （loadMessages 每次直查 get_messages，无缓存问题）。
        void useStore.getState().loadMessages(sid);
        // U5 + S3: 流自然结束后发送**该会话**队列中的下一条(短暂让位,避免与
        // 收尾渲染竞争)。其它会话的队列不受影响。
        if (flushQueue) {
          const pending = pendingMessagesRef.current;
          const idx = pending.findIndex((p) => p.sid === sid);
          if (idx >= 0) {
            const [next] = pending.splice(idx, 1);
            window.setTimeout(() => {
              void sendMessageRef.current?.(
                next.content,
                next.sid,
                undefined,
                next.orchestrationMode,
              );
            }, 300);
          }
        }
      };
      // S3: 注册本会话句柄（HIGH-4: interrupt 经句柄触发 finishStream 清理）
      const streamHandle: ActiveStreamHandle = {
        streamId: null,
        cancel: null,
        finish: finishStream,
      };
      markStreamActive(sid, streamHandle);

      try {
        // 解构 cancel/streamId 存入本会话句柄
        // P0-2 (2026-08-20): interrupt 用 streamId 让后端命中真实 agent。
        const { streamId, cancel } = await chatApi.chatStream(
          sid,
          content,
          {
            onEvent: (evt) => {
              if (finished) return;
              // 会话标题更新事件 (producer 在 DONE 前推送)
              // 立即刷新侧栏会话列表, 这样 DONE 到达时标题已可见
              if (evt.type === 'session_updated') {
                void useStore.getState().loadSessions();
                return;
              }

              // 阶段 4: 累积 agent_id + 迭代轮次 (供前端显示"当前处理 agent")
              if (evt.agent_id || evt.iteration) {
                useChatStreamStore.getState().setStreamingMeta(sid, assistantId, {
                  currentAgentId: evt.agent_id ?? null,
                  iteration: evt.iteration ?? 0,
                });
              }

              // M1 工具审批: permission_request 事件 → 写入 permission store,
              // 全局 ApprovalDialog 弹出。后端 gate 阻塞等待应答(最长 300s,
              // fail-closed),随后的 observing 事件自然覆盖流式状态。
              // uiText 分支对该 state 返回 null,不会碰消息气泡占位符。
              // S4: 记录所属会话 —— 侧边栏按会话聚合"待审批"注意力点。
              if (evt.state === 'permission_request' && evt.permission_request) {
                usePermissionState.getState().setFromEvent(evt.permission_request, sid);
                // S8: 后台会话卡在审批时用户看不到对话框 —— OS 通知提醒
                maybeNotify('approval', `${evt.permission_request.tool_name} 等待确认`);
              }

              // M2 part B: ask_user_question 事件 → 写入 question store,
              // 全局 QuestionDialog 弹出。后端 gate 阻塞等待应答(最长 300s,
              // 超时 = 空应答软结果),随后的 observing 事件自然覆盖流式状态。
              // uiText 分支对该 state 返回 null,不会碰消息气泡占位符。
              // S4: 同上,按会话记录。
              if (evt.state === 'ask_user_question' && evt.user_question) {
                useQuestionState.getState().setFromEvent(evt.user_question, sid);
              }

              // R35: 编排/任务板事件（task_plan/status/progress/review、
              // subagent_event、approval_mode、todo_snapshot、artifact_created）
              // 抽取到 orchestrationEvents.applyOrchestrationEventToBoard，
              // 主路径与重接路径共用（重接重放时任务板完整重建）。
              if (applyOrchestrationEventToBoard(evt, sid)) {
                return;
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
                  const safeResult = typeof tr.content === 'string'
                    ? tr.content
                    : JSON.stringify(tr.content ?? '');
                  useChatStreamStore.getState().appendOrUpdateToolCall(sid, {
                    ...targetTc,
                    result: safeResult,
                    metadata,
                  });
                }
              }

              const uiText = agentStateToText(evt.state, evt.tool_call?.function.name);
              // 累积策略 (I5: 流式逐字):
              // - content_delta + done.content 触发 appendContent 追加 (累积真实回答)
              // - thinking/acting/observing 的 uiText 触发 replaceContent 覆盖
              //   (切换中间态占位, 避免 "🤔 思考中…🤔 思考中…" 重复前缀)
              // - reasoning 事件已在上面处理，不触发 content 更新
              if (
                evt.state === 'reasoning' ||
                evt.state === 'reasoning_delta' ||
                evt.state === 'reasoning_final'
              ) {
                // reasoning 事件不更新 content，仅更新 state。
                // reasoning_delta 复用同一处理,避免依赖 producer 必须以
                // 完整 reasoning 事件收尾的顺序不变式。
                // reasoning_final (2026-09-02): 后端每段末尾全量对齐事件,同样不进 content。
                useChatStreamStore.getState().setStreamingMeta(sid, assistantId, {
                  state: evt.state,
                });
              } else if (typeof evt.content === 'string' && evt.content.length > 0) {
                appendContent(evt.content);
                if (evt.state === 'done') {
                  lastDoneContent = evt.content;
                }
                useChatStreamStore
                  .getState()
                  .setStreamingMeta(sid, assistantId, { state: evt.state });
              } else if (uiText) {
                replaceContent(uiText);
                useChatStreamStore
                  .getState()
                  .setStreamingMeta(sid, assistantId, { state: evt.state });
              }
            },
            onError: (err) => {
              if (finished) return;
              handleError(err);
              // S8: 后台会话失败提醒（前台当前会话不打扰）
              maybeNotify('failed', err instanceof Error ? err.message.slice(0, 120) : '运行失败');
              finishStream();
            },
            onDone: () => {
              if (finished) return;
              // S8: 后台会话完成提醒
              maybeNotify('done', (lastDoneContent ?? '').slice(0, 120));
              // PM2: 计划模式 run 自然完成 → 该会话进入"待批准"状态
              if (opts?.planMode) setPlanApprovalFor(sid);
              // 流自然结束 — 把 streaming.content 写回 store,
              // 然后清掉 streaming overlay 让消息退回 store 视图
              // U5: 自然结束才 flush 队列(错误/中断路径 flushQueue=false)
              finishStream(true);
            },
          },
          config,
          officeRefs,
          opts?.images,
          opts?.attachmentMediaIds,
        );
        // Never let a late subscription overwrite a newer run's handle.
        if (finished || activeStreamRegistry.get(sid) !== streamHandle) {
          cancel();
          void chatApi.interrupt(streamId);
        } else {
          streamHandle.cancel = cancel;
          streamHandle.streamId = streamId;
        }
      } catch (err: unknown) {
        // chatStream 启动失败 (validate / listen 失败等)
        // onDone/onError 不会触发,这里兜底
        if (!finished) {
          handleError(err);
          finishStream();
        }
      }
    },
    [
      currentSessionId,
      chatEndpoint,
      settings,
      addMessage,
      updateMessage,
      markStreamActive,
      markStreamIdle,
    ],
  );
  // U5: 队列 flush 用 ref 取最新 sendMessage(避免闭包捕获旧 isLoading)
  sendMessageRef.current = sendMessage;

  /** Wave 3 (2026-08-14): 取消执行后清空任务板。S2: 只清当前会话的。 */
  const clearTaskBoard = useCallback(() => {
    if (currentSessionId == null) return;
    useChatStreamStore.getState().setTaskBoard(currentSessionId, null);
  }, [currentSessionId]);

  const interrupt = useCallback(async () => {
    if (currentSessionId != null) await cancelSessionStream(currentSessionId);
  }, [currentSessionId]);

  const loadMessagesCallback = useCallback(
    async (sessionId: string) => {
      await loadMessages(sessionId);
    },
    [loadMessages],
  );

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
              const errText =
                typeof raw === 'string'
                  ? raw
                  : (raw?.message ?? '流式失败');
              finishReattach(null, errText);
              return;
            }
            // R35: 编排/任务板事件走共享应用器 —— 重放时任务板/live 态
            // 完整重建（与主路径同一套 store 写入）。
            if (applyOrchestrationEventToBoard(evt, sid)) {
              return;
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
    [chatEndpoint, settings],
  );

  const clearError = useCallback(() => {
    setError(null);
    setErrorSessionId(null);
  }, []);

  return {
    errorSessionId,
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
    /** P0: 当前流式工具调用列表 (供 ProgressSection 显示实时工具进度) */
    streamingToolCalls,
    /** Multi-Agent Orchestration: 编排任务板 (供 TaskTreeSection 渲染任务树) */
    taskBoard,
    /** Wave 3: 取消执行后清空任务板 */
    clearTaskBoard,
    /** Phase 6: /btw 补充消息方法 */
    askBtw,
    /** Phase 6: /btw 是否正在流式输出 */
    isBtwStreaming,
    /** PM2 (round8): 计划模式已完成、待用户批准的会话 ID（null = 无） */
    planApprovalFor,
    /** PM2: 清除计划批准状态（批准执行或忽略时调用） */
    clearPlanApproval: useCallback(() => setPlanApprovalFor(null), []),
    reattachActiveStream,
  };
}
