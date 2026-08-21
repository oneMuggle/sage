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
  type TaskProgressEvent,
  type TaskReviewEvent,
  type TaskStatusEvent,
} from '../../shared/api';
import { orchRunClient } from '../../shared/api/orchRunClient';
import { agentStateToText } from '../../shared/lib/agentStateMapping';
import {
  mapAgentErrorToText,
  mapLLMErrorToText,
  type LLMErrorResponse,
} from '../../shared/lib/errorMapping';
import { logger } from '../../shared/lib/logger';
import { chatApi, useStore, type Message } from '../../shared/lib/store';
import { useSettings } from '../manage-settings/useSettings';

import { useChatStreamStore, type TaskBoardState } from './chatStreamStore';

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

export function useChat() {
  // isLoading / error / isBtwStreaming 仍为 component-local,表征的是这个
  // hook 实例自身的 UI 状态,跨页面保留没意义(页面卸载 → UI 自然消失)。
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { messages, addMessage, updateMessage, currentSessionId, loadMessages } = useStore();
  const { settings } = useSettings();
  // refs 保留:loadingRef / cancelRef / finishStreamRef / btwCancelRef 都是
  // hook 实例级别的协调状态,不需要跨路由保留。
  const loadingRef = useRef(false);
  const cancelRef = useRef<(() => void) | null>(null);
  // HIGH-4 修复: finishStream 是 sendMessage 闭包内的函数,interrupt() 无法直接调用
  // 用 ref 把 finishStream 暴露出去,让 interrupt 也能触发清理流程
  const finishStreamRef = useRef<(() => void) | null>(null);
  // P0-2 (2026-08-20): 当前 streamId —— interrupt 需要它让后端定位真实 agent。
  const streamIdRef = useRef<string | null>(null);

  // 流式当前 assistant 消息的内容覆盖 (派生 messages 的最后一条) —— 2026-08-19
  // 搬到 chatStreamStore(独立 zustand),跨路由切换保留,避免 Chat 页卸载后
  // widget 看到 '🤔 思考中…' 占位符看不到真实 LLM 进度。
  const streaming = useChatStreamStore((s) => s.streaming);
  const streamingToolCalls = useChatStreamStore((s) => s.streamingToolCalls);
  const taskBoard = useChatStreamStore((s) => s.taskBoard);

  // Phase 6: /btw 补充消息状态(component-local,与流式 chat 无关)
  const [isBtwStreaming, setIsBtwStreaming] = useState(false);
  const btwCancelRef = useRef<(() => void) | null>(null);

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
    async (
      content: string,
      sessionId?: string,
      officeRefs?: readonly ChatOfficeRef[],
      orchestrationMode?: ChatConfig['orchestrationMode'],
      opts?: { planOverride?: TaskPlanItem[]; runId?: string },
    ) => {
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
        // P0-2 (2026-08-20): 把当前 streamId 传给后端,让 /interrupt 命中真实 agent。
        chatApi.interrupt(streamIdRef.current ?? undefined).catch(() => {
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
      // startStream 内部已重置 content/reasoning/streamingToolCalls/taskBoard —
      // 流式进度全部走 store,跨路由切换保留(2026-08-19)
      useChatStreamStore.getState().startStream(assistantId, { initialContent: '🤔 思考中…' });

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
        // 由 /orchestrate /single 斜杠命令传入;普通消息 undefined → 后端 auto
        orchestrationMode,
        // Wave 3: resume 恢复流透传
        planOverride: opts?.planOverride,
        runId: opts?.runId,
      };

      const appendContent = (next: string): void => {
        // I5: 流式逐字 — appendContent 通过 store 累加 (跨路由切换保留)
        useChatStreamStore.getState().appendContent(assistantId, next);
      };

      // I5-2: 中间态 (thinking/acting/observing) 的 uiText 应"覆盖"而非"追加"，
      // 避免 "🤔 思考中…🤔 思考中…" 这种重复前缀 bug。
      // appendContent 用于累积真实回答 (content_delta / done.content)，
      // replaceContent 用于切换中间态占位符。
      const replaceContent = (next: string): void => {
        useChatStreamStore.getState().replaceContent(assistantId, next);
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
        // 2026-08-19: 从 store 读最新流式内容(跨路由保留,finishStream 内
        // 不再持有 ref — store 是单一数据源)
        const streamSnapshot = useChatStreamStore.getState().streaming;
        // 优先用 done 事件自带的完整 content (避免混入 thinking 占位符)
        // 退回到 store streaming.content (向后兼容旧的非流式 done 事件)
        let finalContent = lastDoneContent ?? streamSnapshot?.content ?? '';
        const finalReasoning = streamSnapshot?.reasoning ?? '';
        const finalToolCalls = useChatStreamStore.getState().streamingToolCalls;
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
        // 2026-08-19: 精准重置流式 state + toolCalls,**不清 taskBoard**
        // (与原 commit 一致:finishStream 旧实现只 setStreaming(null) + 清 ref,
        //  taskBoard 留到下条消息 startStream 触发重置。
        //  resetAll() 会顺手清掉 taskBoard,破坏 useChat.taskBoard 单测:
        //  "accumulates task_plan then task_status into board" 等依赖
        //  finishStream 后 taskBoard 仍可见。clearStream + resetToolCalls
        //  组合即可,语义等价于旧 setStreaming(null) + 清 ref)
        useChatStreamStore.getState().clearStream(assistantId);
        useChatStreamStore.getState().resetToolCalls();
        cancelRef.current = null;
        resetLoading();
        // M1: 流结束/错误 → 关闭遗留的审批对话框(后端 gate 已超时 fail-closed,
        // 对话框里的请求必然已失效,不能再让 UI 卡着)
        usePermissionState.getState().resolve();
        // M2 part B: 同理关闭遗留的提问对话框(后端 gate 已超时按空应答处理)
        useQuestionState.getState().resolve();
        // HIGH-4: 清空 ref 让 interrupt 知道当前 stream 已结束
        finishStreamRef.current = null;
        // P0-2 (2026-08-20): 清空 streamId —— 流已结束，interrupt 不应命中陈旧实例。
        streamIdRef.current = null;
        // 流结束后刷新侧栏会话列表（获取自动生成的标题）
        // hex 路径无 NDJSON session_updated 事件，此处兜底刷新
        void useStore.getState().loadSessions();
      };
      // HIGH-4: 注册 finishStream 到 ref 供 interrupt 调用
      finishStreamRef.current = finishStream;

      try {
        // 解构 cancel 用于下次 sendMessage 时取消 (cancel-prev)
        // P0-2 (2026-08-20): 同时解构 streamId,存入 ref 供 interrupt 回调使用。
        const { streamId, cancel } = await chatApi.chatStream(
          sid,
          content,
          {
            onEvent: (evt) => {
              // 会话标题更新事件 (producer 在 DONE 前推送)
              // 立即刷新侧栏会话列表, 这样 DONE 到达时标题已可见
              if (evt.type === 'session_updated') {
                void useStore.getState().loadSessions();
                return;
              }

              // 阶段 4: 累积 agent_id + 迭代轮次 (供前端显示"当前处理 agent")
              if (evt.agent_id || evt.iteration) {
                useChatStreamStore.getState().setStreamingMeta(assistantId, {
                  currentAgentId: evt.agent_id ?? null,
                  iteration: evt.iteration ?? 0,
                });
              }

              // Multi-Agent Orchestration: task_plan 事件 → 初始化编排任务板。
              // "先消费、不进内容累加器" — 不产生消息气泡占位文本,后续 uiText
              // 分支不会命中。
              if (evt.state === 'task_plan' && evt.run_id && evt.plan) {
                useChatStreamStore.getState().setTaskBoard({
                  runId: evt.run_id,
                  plan: evt.plan,
                  statuses: {},
                });
                return;
              }
              // Multi-Agent Orchestration: task_status 事件 → 按 run_id 匹配合并进任务板。
              // 旧 run 的 task_status 直接忽略（prev 为 null 或 runId 不匹配都返回原值）。
              // 后端 task_status 载荷含 TaskStatusEvent 全字段,故宽松 AgentEvent 可直接 cast。
              // 进度可视化 P0-2 (2026-08-12): 同步重算 progress 5 元组,让
              // ProgressSection 无需等待 task_progress 就能实时反映 done/queued。
              if (evt.state === 'task_status' && evt.run_id && evt.task_id) {
                // 闭包内 TS 不保留 evt 字段的 narrowing,先捕获为 const
                const runId = evt.run_id;
                const taskId = evt.task_id;
                useChatStreamStore.getState().updateTaskBoard(runId, (prev) => {
                  if (!prev || prev.runId !== runId) return prev;
                  const nextStatuses = {
                    ...prev.statuses,
                    [taskId]: evt as TaskStatusEvent,
                  };
                  const counts = { done: 0, running: 0, queued: 0, failed: 0, cancelled: 0 };
                  for (const st of Object.values(nextStatuses)) {
                    if (st.status === 'done') counts.done++;
                    else if (st.status === 'running') counts.running++;
                    else if (st.status === 'queued') counts.queued++;
                    else if (st.status === 'failed') counts.failed++;
                    else if (st.status === 'cancelled') counts.cancelled++;
                  }
                  const total = Math.max(
                    prev.progress?.total ?? 0,
                    Object.keys(nextStatuses).length,
                  );
                  return {
                    ...prev,
                    statuses: nextStatuses,
                    progress: { total, ...counts },
                    // P1-5: 首个 task_status = 派发已开始,记录时间戳供
                    // PlanCard 锁定（派发后 plan_update 后端返回 409）。
                    dispatchedAt: prev.dispatchedAt ?? Date.now(),
                  };
                });
                return;
              }
              // 进度可视化 P0-2 (2026-08-12): task_progress 整盘概览事件。
              // 后端在 task_plan 之后立即推一次(total=N,全 queued),前端
              // 据此初始化 progress;后续 task_status 触发时由上面 reducer
              // 实时聚合覆盖,保持单一数据源。AgentEvent 在宽松字段下
              // 5 元组都是 optional,运行时真有数据(后端 SSE 保证),此处
              // 用 TaskProgressEvent 收紧类型避免反复 ?? 0 退化。
              if (evt.state === 'task_progress' && evt.run_id) {
                const runId = evt.run_id;
                const tp = evt as TaskProgressEvent;
                useChatStreamStore.getState().updateTaskBoard(runId, (prev) =>
                  prev && prev.runId === runId
                    ? {
                        ...prev,
                        progress: {
                          total: tp.total ?? 0,
                          done: tp.done ?? 0,
                          running: tp.running ?? 0,
                          queued: tp.queued ?? 0,
                          failed: tp.failed ?? 0,
                          cancelled: tp.cancelled ?? 0,
                        },
                      }
                    : prev,
                );
                return;
              }

              // M1 工具审批: permission_request 事件 → 写入 permission store,
              // 全局 ApprovalDialog 弹出。后端 gate 阻塞等待应答(最长 300s,
              // fail-closed),随后的 observing 事件自然覆盖流式状态。
              // uiText 分支对该 state 返回 null,不会碰消息气泡占位符。
              if (evt.state === 'permission_request' && evt.permission_request) {
                usePermissionState.getState().setFromEvent(evt.permission_request);
              }

              // M2 part B: ask_user_question 事件 → 写入 question store,
              // 全局 QuestionDialog 弹出。后端 gate 阻塞等待应答(最长 300s,
              // 超时 = 空应答软结果),随后的 observing 事件自然覆盖流式状态。
              // uiText 分支对该 state 返回 null,不会碰消息气泡占位符。
              if (evt.state === 'ask_user_question' && evt.user_question) {
                useQuestionState.getState().setFromEvent(evt.user_question);
              }

              // P0-6 (2026-08-20): task_review 事件 → 复核结论写入任务板，
              // 由 TaskTreeSection 渲染横幅。不进消息气泡 ——
              // agentStateMapping 对 task_review 返回 null 的既有行为保留。
              if (evt.state === 'task_review' && evt.run_id) {
                const runId = evt.run_id;
                const review = evt as TaskReviewEvent;
                useChatStreamStore
                  .getState()
                  .updateTaskBoard(runId, (prev) =>
                    prev && prev.runId === runId ? { ...prev, review } : prev,
                  );
                return;
              }

              // 处理 reasoning 事件：累积 reasoning 内容（支持完整事件和增量事件）
              if ((evt.state === 'reasoning' || evt.state === 'reasoning_delta') && evt.reasoning) {
                useChatStreamStore.getState().appendReasoning(assistantId, evt.reasoning);
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
                useChatStreamStore.getState().appendOrUpdateToolCall({
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
                const currentTcs = useChatStreamStore.getState().streamingToolCalls;
                const targetIdx = targetId
                  ? currentTcs.findIndex((t) => t.id === targetId)
                  : currentTcs.length - 1;
                const targetTc = targetIdx >= 0 ? currentTcs[targetIdx] : null;
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
                  useChatStreamStore.getState().appendOrUpdateToolCall({
                    ...targetTc,
                    result: tr.content,
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
              if (evt.state === 'reasoning' || evt.state === 'reasoning_delta') {
                // reasoning 事件不更新 content，仅更新 state。
                // reasoning_delta 复用同一处理,避免依赖 producer 必须以
                // 完整 reasoning 事件收尾的顺序不变式。
                useChatStreamStore.getState().setStreamingMeta(assistantId, { state: evt.state });
              } else if (typeof evt.content === 'string' && evt.content.length > 0) {
                appendContent(evt.content);
                if (evt.state === 'done') {
                  lastDoneContent = evt.content;
                }
                useChatStreamStore.getState().setStreamingMeta(assistantId, { state: evt.state });
              } else if (uiText) {
                replaceContent(uiText);
                useChatStreamStore.getState().setStreamingMeta(assistantId, { state: evt.state });
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
          officeRefs,
        );
        // 存 cancel 用于下次 sendMessage 取消 + interrupt 用
        cancelRef.current = cancel;
        // P0-2 (2026-08-20): 记录当前 streamId，interrupt 时让后端命中真实 agent。
        streamIdRef.current = streamId;
      } catch (err: unknown) {
        // chatStream 启动失败 (validate / listen 失败等)
        // onDone/onError 不会触发,这里兜底
        handleError(err);
        finishStream();
      }
    },
    [currentSessionId, isLoading, chatEndpoint, settings, addMessage, updateMessage],
  );

  /** Wave 3 (2026-08-14): resume 恢复流 —— resumeRun → sendMessage(original_request, plan_override)。 */
  const resumeOrchestration = useCallback(
    async (runId: string) => {
      const resp = await orchRunClient.resumeRun(runId);
      // §13.7 (2026-08-15): 旧库 NULL original_request 兜底 —— 占位文案继续 + 提示，
      // 避免空串被当成正常消息发给 LLM（ChatRequest.message 无非空校验）。
      const content = resp.original_request ?? '（旧记录无原始请求，已从计划恢复）';
      if (!resp.original_request) {
        toast.info('该记录缺少原始请求，已从计划恢复执行');
      }
      await sendMessage(content, undefined, undefined, 'force_multi', {
        planOverride: resp.plan,
        runId: resp.new_run_id,
      });
    },
    [sendMessage],
  );

  /** Wave 3 (2026-08-14): 取消执行后清空任务板。 */
  const clearTaskBoard = useCallback(() => useChatStreamStore.getState().setTaskBoard(null), []);

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
      // P0-2 (2026-08-20): 带上当前 streamId 让后端命中真实运行的 agent。
      await chatApi.interrupt(streamIdRef.current ?? undefined);
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
    /** P0: 当前流式工具调用列表 (供 ProgressSection 显示实时工具进度) */
    streamingToolCalls,
    /** Multi-Agent Orchestration: 编排任务板 (供 TaskTreeSection 渲染任务树) */
    taskBoard,
    /** Wave 3: resume 恢复流入口 (计划卡恢复按钮调用) */
    resumeOrchestration,
    /** Wave 3: 取消执行后清空任务板 */
    clearTaskBoard,
    /** Phase 6: /btw 补充消息方法 */
    askBtw,
    /** Phase 6: /btw 是否正在流式输出 */
    isBtwStreaming,
  };
}
