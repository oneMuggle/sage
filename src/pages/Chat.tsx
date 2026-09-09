import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { PlanCard } from '../components/PlanCard';
import { resolveEndpoint } from '../entities/setting/types';
import { useSettings } from '../features/manage-settings/useSettings';
import { useChatStreamStore, type TaskBoardState } from '../features/send-message/chatStreamStore';
import { useChat } from '../features/send-message/useChat';
import { sessionApi, learnApi, type ChatOfficeRef } from '../shared/api';
import { orchRunClient } from '../shared/api/orchRunClient';
import { useI18n } from '../shared/lib/i18n';
import { useStore } from '../shared/lib/store';
import { useCurrentWorkspace } from '../shared/lib/workspaceContext';
import { ErrorState } from '../shared/ui/ErrorState';
import { LoadingState } from '../shared/ui/LoadingState';
import { ActiveAgentIndicator, ChatInput, MessageList, SubagentLivePanel } from '../widgets/chat';
import { ContextMeter } from '../widgets/chat/ContextMeter';
import { INTERRUPTED_RUN_ERROR, InterruptedRunBanner } from '../widgets/chat/InterruptedRunBanner';
import { RightPanel } from '../widgets/chat/RightPanel';
import { RightPanelToggle } from '../widgets/chat/RightPanelToggle';
import { SessionModelPicker } from '../widgets/chat/SessionModelPicker';
import { SessionUsageBadge } from '../widgets/chat/SessionUsageBadge';

/** t() 结果是静态模板，这里做最小占位符替换（i18n 无内置插值）。 */
function fill(template: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (acc, [key, value]) => acc.replace(`{${key}}`, String(value)),
    template,
  );
}

/** 稳定空数组: toolCalls 缺省时避免每次渲染产生新引用击穿 RightPanel memo (F1) */
const EMPTY_TOOL_CALLS: readonly never[] = [];

/**
 * Sticky-bottom 阈值(scrollTop 距底部 ≤ 此值视作"在底部")。
 *
 * - 太大会让用户微调 scrollbar 也算"在底部"→ 流式 token 抢焦点
 * - 太小会让 1px 误差就让"跳到最新"按钮闪出/消失
 * 经验值 48px 对应 ~5 行文字,大多数用户用滚轮 1-2 击内仍能停在阈值内。
 */
const BOTTOM_THRESHOLD_PX = 48;

export function Chat() {
  const {
    messages,
    isLoading,
    error,
    clearError,
    sendMessage,
    interrupt,
    loadMessages,
    currentAgentId, // 阶段 4: 当前流式处理中的 agent ID
    streamingMessageId, // P1: 当前流式消息 ID
    iteration, // P2: ReAct 迭代轮次
    streamingState, // P2: 当前流式状态
    streamingToolCalls, // 右侧面板 Progress: 实时流式工具调用
    taskBoard, // Multi-Agent Orchestration: 编排任务板
    clearTaskBoard, // Wave 3: 取消执行后清空任务板
  } = useChat();
  const [rightPanelOpen, setRightPanelOpen] = useState(false);

  const {
    currentSessionId,
    setCurrentSessionId,
    createSession,
    loadSessions,
    sessions,
    isLoading: storeLoading,
  } = useStore();

  // L16 (round4 批次 A): run 级崩溃恢复横幅 —— 后端启动时把滞留 running
  // 的会话统一标记 failed(INTERRUPTED_RUN_ERROR);聊天页识别该终态后给出
  // "重发最后一条消息"的恢复入口,而不是让用户对着侧栏灰点猜。
  const currentSession = sessions.find((s) => s.id === currentSessionId);
  const interruptedRun =
    currentSession?.run_status === 'failed' &&
    currentSession?.last_error === INTERRUPTED_RUN_ERROR;
  const [dismissedInterrupts, setDismissedInterrupts] = useState<Set<string>>(new Set());
  const showInterruptBanner =
    currentSessionId != null && interruptedRun && !dismissedInterrupts.has(currentSessionId);

  const retryInterruptedRun = useCallback(() => {
    if (!currentSessionId) return;
    const lastUser = [...messages].reverse().find((m) => m.role === 'user');
    if (!lastUser) {
      toast.error('找不到可重发的消息');
      return;
    }
    void sendMessage(lastUser.content, currentSessionId);
  }, [currentSessionId, messages, sendMessage]);

  const { t } = useI18n();
  const { settings, isLoading: settingsLoading } = useSettings();
  const navigate = useNavigate();
  const location = useLocation();
  // Office M1-M2 chat-read: inject the active workspace path so the
  // ChatInput → AtFileMenu chain can surface office docs in @ autocomplete.
  // Default provider value is `undefined` (no workspace selected yet in M1-M2),
  // which keeps file-search behavior unchanged in production. Office.tsx will
  // be migrated onto this context in a follow-up PR.
  const workspacePath = useCurrentWorkspace();
  const pendingSentRef = useRef(false);
  // LOW-1: 跟随新消息/流式 token 自动滚到底。
  // 必须用 derivedMessages 而非 messages —— 流式 override 只在 derivedMessages 里,
  // 原 messages 中最后一条仍是占位符 '🤔 思考中…'。
  // 依赖:消息条数 + 最后一条 content + reasoning + tool_call 数 — 任一变化都触发滚动。
  //
  // Task 2 (Win7 parity) sticky-bottom UX:
  // - 之前未实现时,流式 token 每来一次都强制 scrollTop=scrollHeight,
  //   用户上滚读历史时焦点被频繁拉回底部,无法阅读 — Win7 packaged 后端
  //   日志记录到该 UX 退化。
  // - 修法:加 ``wasAtBottomRef`` + ``BOTTOM_THRESHOLD_PX`` 跟踪,只在
  //   上次 scroll 事件时位于阈值内才 auto-scroll。
  // - ``lastMsgLengthRef`` 检测"用户刚发了新消息"(消息条数增加)→ 强制一次
  //   scroll,不依赖 wasAtBottomRef。
  // - "跳到最新"按钮在 ``wasAtBottomRef.current === false && streamingMessageId`` 时渲染,
  //   固定右下角,a11y ``aria-label="跳到最新"``。
  const scrollRef = useRef<HTMLDivElement>(null);
  const wasAtBottomRef = useRef(true);
  const lastMsgLengthRef = useRef(0);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const lastMsg = messages[messages.length - 1];
  const previousMessagesRef = useRef<typeof messages>([]);

  // A session switch replaces the scrollable content; discard the previous
  // session's sticky-bottom state before the new message list is measured.
  useEffect(() => {
    wasAtBottomRef.current = true;
    lastMsgLengthRef.current = 0;
    previousMessagesRef.current = [];
    setShowJumpToLatest(false);
  }, [currentSessionId]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const prevLength = lastMsgLengthRef.current;
    const currentLength = messages.length;
    const previousMessages = previousMessagesRef.current;
    const addedUserMessage =
      currentLength > prevLength &&
      messages.slice(previousMessages.length).some((message) => message.role === 'user');
    lastMsgLengthRef.current = currentLength;
    previousMessagesRef.current = messages;

    if (addedUserMessage || wasAtBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- messages 本身不加入 deps，避免每次 render 都触发；通过 messages.length + lastMsg 字段变化驱动
  }, [
    messages.length,
    lastMsg?.content,
    lastMsg?.reasoning_content,
    lastMsg?.tool_calls?.length,
    // streamingMessageId 变化时也需要滚 (新 stream 开始)
    streamingMessageId,
  ]);

  // Scroll listener: 维护 wasAtBottomRef + showJumpToLatest UI state。
  // 用 ``wasAtBottomRef`` 同步标记 + ``useState`` 异步刷新,避免 setState 触发的
  // re-render 打断滚动节奏(scrollTop 频繁跳变会让 wasAtBottom 状态本身抖动)。
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onScroll = () => {
      const distance = el.scrollHeight - el.clientHeight - el.scrollTop;
      const atBottom = distance <= BOTTOM_THRESHOLD_PX;
      wasAtBottomRef.current = atBottom;
      // ``showJumpToLatest`` 仅在流式进行 + 离开底部时显示
      setShowJumpToLatest(!atBottom && Boolean(streamingMessageId));
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    // 初始挂载时跑一次,让 wasAtBottom 反映真实初始状态
    onScroll();
    return () => {
      el.removeEventListener('scroll', onScroll);
    };
  }, [streamingMessageId]);

  // Fix #4 (2026-09-06): PlanCard 出现时自动滚动到可视区域。
  // 当 taskBoard 首次设置且未派发时，PlanCard 在消息列表下方渲染，
  // 但自动滚动依赖项（messages.length 等）不变，用户可能看不到。
  // 此 effect 在 taskBoard.runId 变化（新计划到达）或 dispatchedAt 从 null
  // 变为非 null（已派发）时触发，将 PlanCard 滚动到视口中心。
  useEffect(() => {
    if (taskBoard && !taskBoard.dispatchedAt && scrollRef.current) {
      const planCard = scrollRef.current.querySelector('[data-testid="plan-card"]');
      // ``typeof scrollIntoView === 'function'`` 守卫 jsdom 等不支持的测试环境。
      if (planCard && typeof planCard.scrollIntoView === 'function') {
        planCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- taskBoard 整体不加入依赖，仅跟踪 runId + dispatchedAt 变化
  }, [taskBoard?.runId, taskBoard?.dispatchedAt]);

  const scrollToLatest = () => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    wasAtBottomRef.current = true;
    setShowJumpToLatest(false);
  };

  const chatEndpoint = resolveEndpoint(settings.modelSelections.chatModel, settings.endpoints);
  const hasConfig =
    Boolean(chatEndpoint?.baseUrl) && Boolean(settings.modelSelections.chatModel.modelId);
  const showConfigWarning = !hasConfig;

  useEffect(() => {
    if (currentSessionId) {
      loadMessages(currentSessionId);
    }
  }, [currentSessionId, loadMessages]);

  // C1 (2026-09-09): 历史任务板恢复 —— 会话切换时拉取该会话最近的编排
  // run（plan + tasks + 终态），重开历史会话也能看到当时的任务树与结果
  // 预览（时间线经既有 snapshot/events 回放通道按 runId 订阅）。会话正在
  // 流式中（直播板已存在）时跳过，避免覆盖实时状态。
  useEffect(() => {
    if (!currentSessionId) return;
    let cancelled = false;
    const { getState } = useChatStreamStore;
    const slots = getState().sessions[currentSessionId];
    if (slots?.streaming || slots?.taskBoard) return;
    orchRunClient
      .listSessionRuns(currentSessionId)
      .then((resp) => {
        if (cancelled) return;
        const run = resp.runs[0];
        if (!run || run.tasks.length === 0) return;
        type PlanItem = TaskBoardState['plan'][number];
        const plan = run.plan as unknown as PlanItem[];
        const statuses: TaskBoardState['statuses'] = {};
        const progress = { total: 0, done: 0, running: 0, queued: 0, failed: 0, cancelled: 0 };
        progress.total = run.tasks.length;
        for (const task of run.tasks) {
          const status = String(task.status ?? 'queued');
          const taskId = String(task.task_id);
          statuses[taskId] = {
            state: 'task_status',
            run_id: run.run_id,
            task_id: taskId,
            status: status as TaskBoardState['statuses'][string]['status'],
            agent_id: String(task.agent_id ?? ''),
            goal: String(task.goal ?? ''),
            error: (task.error as string | null) ?? null,
            output_preview: (task.output_preview as string | null) ?? null,
            retry_count: (task.retry_count as number) ?? 0,
          };
          if (status in progress) progress[status as keyof typeof progress] += 1;
        }
        // 动态加任务的 run 可能 plan_json 为空 —— 从任务行反推 plan 保证任务树可渲染
        const effPlan: PlanItem[] =
          plan.length > 0
            ? plan
            : run.tasks.map((task) => ({
                task_id: String(task.task_id),
                agent_id: String(task.agent_id ?? ''),
                goal: String(task.goal ?? ''),
              }));
        const board: TaskBoardState = {
          runId: run.run_id,
          plan: effPlan,
          statuses,
          progress,
          dispatchedAt: run.created_at,
        };
        useChatStreamStore.getState().setTaskBoard(currentSessionId, board);
      })
      .catch(() => {
        /* 历史恢复是增强能力：失败静默（无编排历史的常态路径） */
      });
    return () => {
      cancelled = true;
    };
  }, [currentSessionId]);

  // Auto-send pending message passed from Welcome page via router state
  const pendingMessage = (location.state as { pendingMessage?: string } | null)?.pendingMessage;
  useEffect(() => {
    if (
      pendingMessage &&
      currentSessionId &&
      !pendingSentRef.current &&
      !settingsLoading &&
      !storeLoading
    ) {
      pendingSentRef.current = true;
      sendMessage(pendingMessage, currentSessionId);
      // Clear location state so refresh doesn't re-send
      window.history.replaceState({}, '');
    }
  }, [pendingMessage, currentSessionId, sendMessage, settingsLoading, storeLoading]);

  const handleNewSession = async () => {
    // 与 Sidebar 的 "+ 新对话" 行为对齐:跳到欢迎页由用户输入后再创建会话。
    // 必须清空 currentSessionId,否则 ChatRoute 因为 sessionId 非空仍会
    // 渲染 Chat 页,导致跳到 /welcome 后又被重定向回 /chat。
    setCurrentSessionId(null);
    navigate('/welcome');
  };

  // useCallback 稳定回调引用: Message.tsx 的 memo 比较器逐一比较 onFork 等
  // 回调 props, 每次渲染新建函数会把 60 条可见消息的 memo 全部击穿 —— 流式
  // 期间每 token 全量重渲染 (F1)。
  const handleSendMessage = useCallback(
    async (
      content: string,
      options?: {
        knowledgeRefs?: { id: string; title: string }[];
        attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
        images?: { name: string; size: number; type: string; dataUrl?: string }[];
        officeRefs?: readonly ChatOfficeRef[];
        // Wave 3 C6: 放宽为 string —— 编排模式条可传 'template:<id>' 等。
        orchestrationMode?: string;
      },
    ) => {
      clearError();
      const officeRefs = options?.officeRefs;
      const orchestrationMode = options?.orchestrationMode;
      if (!currentSessionId) {
        const sessionId = await createSession();
        await sendMessage(content, sessionId, officeRefs, orchestrationMode);
      } else {
        await sendMessage(content, undefined, officeRefs, orchestrationMode);
      }
    },
    [clearError, currentSessionId, createSession, sendMessage],
  );

  // M4: /compact slash action — 调后端压缩当前会话，成功后重载消息
  // （续接摘要行由后端持久化，重载后即显示在聊天列表中）。
  // MEDIUM-1: 流式中（isLoading）early-return —— 两个并发手动压缩会在后端
  // 各自通过 should_compact 检查并写出重复续接行；前端守卫是必须的修复，
  // 后端 409 compact_in_progress 只是兜底。
  const handleCompact = useCallback(async () => {
    if (!currentSessionId || isLoading) return;
    try {
      const result = await sessionApi.compact(currentSessionId);
      if (result.ok && result.compacted) {
        toast.success(
          fill(t('chat.compact_success'), {
            before: result.before,
            after: result.after,
            removed: result.removed,
          }),
        );
        await loadMessages(currentSessionId);
      } else if (result.ok) {
        toast.info(t('chat.compact_skipped'));
      } else {
        toast.error(
          fill(t('chat.compact_failed'), { message: result.message ?? result.error ?? '' }),
        );
      }
    } catch (e) {
      toast.error(
        fill(t('chat.compact_failed'), { message: e instanceof Error ? e.message : String(e) }),
      );
    }
  }, [currentSessionId, isLoading, loadMessages, t]);

  // Task 12 (2026-08-03): /learn slash action — 触发 Background Review
  // 当前会话，产生技能草案候选。成功后跳转到 Skills 页面的 Pending Drafts tab。
  // 与 /compact 对齐：流式中 early-return。
  const handleLearn = useCallback(async () => {
    if (!currentSessionId || isLoading) return;
    try {
      toast.info(t('chat.learn_reviewing'));
      await learnApi.trigger(currentSessionId);
      toast.success(t('chat.learn_queued'));
      navigate('/skills?tab=drafts');
    } catch (e) {
      toast.error(
        fill(t('chat.learn_failed'), { error: e instanceof Error ? e.message : String(e) }),
      );
    }
  }, [currentSessionId, isLoading, navigate, t]);

  // M4: 消息级分叉 — 非破坏性操作（无需确认）。成功后切换到新会话
  // （复用现有 session-switch 路径：setCurrentSessionId → loadMessages effect）。
  // MEDIUM-1: 流式中（isLoading）early-return —— 流式写入与 fork 前缀复制
  // 并发会复制出不完整的消息序列，且中途切换会话会打断流式 UI。
  const handleFork = useCallback(
    async (messageId: string) => {
      if (!currentSessionId || isLoading) return;
      try {
        const forked = await sessionApi.fork(currentSessionId, messageId);
        toast.success(t('chat.fork_success'));
        void loadSessions(); // 刷新侧栏（含 fork 徽标）
        setCurrentSessionId(forked.id);
      } catch (e) {
        toast.error(
          fill(t('chat.fork_failed'), { message: e instanceof Error ? e.message : String(e) }),
        );
      }
    },
    [currentSessionId, isLoading, loadSessions, setCurrentSessionId, t],
  );

  // U5' (对标增强第五轮批次 A): 编辑重发。
  // ① 点击 user 消息的编辑按钮 → 原文回填输入框 + 进入编辑态（editResendTarget）；
  // ② 用户改写后发送 → fork 当前会话（before_message 开区间截到该消息之前，
  //    首条消息得到空前缀会话）→ 对 fork 会话发送改写内容 → 跳转 fork 会话。
  // 原会话完整保留（透明可控：编辑重发不截断历史）。fork 会话经 B1 继承
  // 源会话工作区绑定，agent 上下文不断链。
  const [editResendTarget, setEditResendTarget] = useState<{
    messageId: string;
    text: string;
    nonce: number;
  } | null>(null);
  // 传给 memo 组件的 props 引用需稳定: 内联箭头函数/对象字面量每次渲染
  // 都是新引用, 会击穿 React.memo (F1)。
  const cancelEditResend = useCallback(() => setEditResendTarget(null), []);
  const editResendNotice = useMemo(
    () => (editResendTarget ? { onCancel: cancelEditResend } : null),
    [cancelEditResend, editResendTarget],
  );
  const handleToggleRightPanel = useCallback(() => setRightPanelOpen((v) => !v), []);

  // messages 每 token 换新引用, 直接进 deps 会击穿 memo —— 经 ref 读取,
  // 回调引用保持恒定 (F1)。
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const handleStartEditResend = useCallback((messageId: string) => {
    const target = messagesRef.current.find((m) => m.id === messageId);
    if (!target || target.role !== 'user') return;
    setEditResendTarget({
      messageId,
      text: target.content,
      nonce: Date.now(),
    });
  }, []);

  const handleSendMessageWithEditResend = useCallback(
    async (
      content: string,
      options?: Parameters<typeof handleSendMessage>[1],
    ) => {
      if (!editResendTarget) {
        await handleSendMessage(content, options);
        return;
      }
      const target = editResendTarget;
      setEditResendTarget(null); // 先清编辑态，防 fork 失败重试时二次分叉
      if (!currentSessionId || isLoading) {
        await handleSendMessage(content, options);
        return;
      }
      try {
        const forked = await sessionApi.fork(currentSessionId, target.messageId, undefined, {
          beforeMessage: true,
        });
        toast.success(t('chat.edit_resend_forked'));
        void loadSessions();
        setCurrentSessionId(forked.id);
        await sendMessage(content, forked.id);
      } catch (e) {
        toast.error(
          fill(t('chat.fork_failed'), { message: e instanceof Error ? e.message : String(e) }),
        );
        // fork 失败退回普通发送，改写内容不丢
        await handleSendMessage(content, options);
      }
    },
    [
      currentSessionId,
      editResendTarget,
      handleSendMessage,
      isLoading,
      loadSessions,
      sendMessage,
      setCurrentSessionId,
      t,
    ],
  );

  // Wave 3 C4+H1 (2026-08-15): 统一取消语义 —— 未派发/已派发/运行中一律调
  // cancelRun（后端置 cancelled + dispatcher.cancel() 阻止自动派发，避免空转
  // 烧 token），成功或 409 等错误都清空 taskBoard（board 信息已过时）。
  // M1：取消失败也照常清理，避免计划卡永久锁定 + unhandled rejection。
  const handleCancelRun = async (runId: string) => {
    try {
      await orchRunClient.cancelRun(runId);
    } catch {
      // 409（run 已终态）等 → 前端照常清空计划卡（board 信息过时）
    }
    clearTaskBoard();
  };

  // 顶层错误：渲染整页 ErrorState，提供"关闭"清除错误后回到聊天
  if (error) {
    return (
      <div className="flex-1 flex flex-col">
        <div className="h-12 flex items-center justify-between px-5 border-b border-border bg-surface flex-shrink-0">
          <h2 className="text-sm font-semibold text-text">对话</h2>
        </div>
        <div className="flex-1 flex items-center justify-center p-4">
          <ErrorState
            title="对话出错"
            message={error}
            onRetry={clearError}
            retryLabel="关闭并重试"
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* 页面头部 */}
      <div className="h-12 flex items-center justify-between px-5 border-b border-border bg-surface flex-shrink-0">
        <div className="flex items-center gap-4 min-w-0">
          <h2 className="text-sm font-semibold text-text shrink-0">对话</h2>
          {/* U8: 会话级模型切换(G5 收尾) · U14: 会话用量徽章 · U17: 上下文占用 */}
          <SessionModelPicker sessionId={currentSessionId} />
          <SessionUsageBadge sessionId={currentSessionId} />
          <ContextMeter sessionId={currentSessionId} />
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleNewSession}
            className="px-2 py-1 text-xs border border-border rounded-radius-sm hover:bg-bg-hover transition-colors"
          >
            + 新对话
          </button>
          <RightPanelToggle open={rightPanelOpen} onClick={() => setRightPanelOpen((v) => !v)} />
        </div>
      </div>

      {showInterruptBanner && (
        <InterruptedRunBanner
          onRetry={retryInterruptedRun}
          onDismiss={() =>
            setDismissedInterrupts((prev) => new Set(prev).add(currentSessionId ?? ''))
          }
        />
      )}

      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto relative">
        {isLoading && messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <LoadingState label="正在加载对话..." />
          </div>
        ) : (
          <MessageList
            messages={messages}
            streamingMessageId={streamingMessageId}
            onFork={handleFork}
            onEditResend={handleStartEditResend}
          />
        )}
        {/* 编排计划确认卡 (Fix #2): 未派发时在主对话区域显示,方便用户查看和确认 */}
        {taskBoard && !taskBoard.dispatchedAt && (
          <div className="px-4 pb-2">
            <PlanCard
              runId={taskBoard.runId}
              plan={taskBoard.plan}
              locked={false}
              needConfirm={true}
              onCancel={() => void handleCancelRun(taskBoard.runId)}
            />
          </div>
        )}
        {/* Task 2: sticky-bottom "跳到最新" 按钮 — 用户离开底部 + 流式进行中显示,
            固定右下角,a11y ``aria-label="跳到最新"``。点击后 scrollTop=scrollHeight
            并把 wasAtBottomRef 重置。 */}
        {showJumpToLatest && (
          <button
            type="button"
            onClick={scrollToLatest}
            aria-label="跳到最新"
            className="absolute bottom-4 right-4 px-3 py-1.5 bg-primary text-text-inverse text-xs rounded-radius-sm shadow-md hover:bg-primary-hover transition-colors z-10"
          >
            跳到最新
          </button>
        )}
      </div>

      {/* 阶段 4 + P2: 流式处理时显示当前活跃 agent + 迭代轮次 + 阶段 */}
      <ActiveAgentIndicator
        agentId={currentAgentId}
        iteration={iteration}
        streamingState={streamingState}
      />

      {/* live-events P0 (2026-09-06): 编排子代理实时执行面板 —— 派发后
          conductor 阻塞在 dispatch_subagents 内,这里逐行展示每个子任务的
          实时步骤,消除"只能被动等待"的黑盒感。 */}
      <SubagentLivePanel sessionId={currentSessionId} />

      {showConfigWarning && (
        <div
          data-testid="config-warning"
          className="px-4 py-2 bg-yellow-50 border-t border-yellow-300 text-yellow-900 text-xs flex items-center gap-2"
        >
          <span aria-hidden="true">⚠️</span>
          <span>
            未配置 API 端点或对话模型，
            <button
              type="button"
              onClick={() => navigate('/settings')}
              className="underline text-yellow-900 hover:text-yellow-700 transition-colors"
            >
              前往设置
            </button>
          </span>
        </div>
      )}

      <ChatInput
        onSend={handleSendMessageWithEditResend}
        onInterrupt={interrupt}
        onCompact={handleCompact}
        onLearn={handleLearn}
        isLoading={isLoading}
        disabled={!hasConfig}
        placeholder="输入消息..."
        workspacePath={workspacePath}
        injectedDraft={editResendTarget}
        editResendNotice={editResendNotice}
      />

      {/* Artifacts Panel: 右侧抽屉（fixed 定位，叠加在页面右缘） */}
      <RightPanel
        open={rightPanelOpen}
        onToggle={handleToggleRightPanel}
        iteration={iteration}
        streamingState={streamingState}
        // ?? [] 为防御:个别测试 mock useChat 时可能缺该字段;生产 hook 保证非空
        toolCalls={streamingToolCalls ?? EMPTY_TOOL_CALLS}
        isLoading={isLoading}
        sessionId={currentSessionId}
        taskBoard={taskBoard ?? null}
        // C4+H1 (2026-08-15): 任意阶段取消都走 handleCancelRun ——
        // cancelRun（未派发时后端置 cancelled + dispatcher.cancel() 阻止
        // 自动派发）+ 清空 taskBoard。
        onCancelExecution={(runId) => void handleCancelRun(runId)}
      />
    </div>
  );
}
