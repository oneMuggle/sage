import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { resolveEndpoint } from '../entities/setting/types';
import { useArtifactEventsStore } from '../features/artifacts/artifactEventsStore';
import { useSessionMemoryPause } from '../features/chat/useSessionMemoryPause';
import { useSettings } from '../features/manage-settings/useSettings';
import { useRightPanelStore } from '../features/right-panel/rightPanelStore';
import { useChatStreamStore } from '../features/send-message/chatStreamStore';
import { restoreRunToBoard } from '../features/send-message/orchestrationEvents';
import { useChat } from '../features/send-message/useChat';
import { useTerminalPanelStore } from '../features/terminal-panel/terminalPanelStore';
import { type ChatOfficeRef } from '../shared/api';
import { maybeIndexAttachment } from '../shared/api/attachmentAutoIndex';
import { loadAttachmentRagConfig } from '../shared/api/attachmentRagConfig';
// RD20 (round43): 历史 run → 任务板恢复映射。
import { CHAT_DOCUMENT_EXTENSIONS } from '../shared/lib/hooks/useFileUpload';
import { useStore } from '../shared/lib/store';
import { useIsMobile } from '../shared/lib/useIsMobile';
import { useCurrentWorkspace } from '../shared/lib/workspaceContext';
import { LoadingState } from '../shared/ui/LoadingState';
import {
  ActiveAgentIndicator,
  ChatInput,
  MessageList,
  PendingQueueStrip,
  RunSummaryPanel,
  SubagentLivePanel,
} from '../widgets/chat';
import { ChatInlineError } from '../widgets/chat/ChatInlineError';
import { CHAT_NOTICE_PRIORITY, ChatNoticeStack } from '../widgets/chat/ChatNoticeStack';
import { INTERRUPTED_RUN_ERROR, InterruptedRunBanner } from '../widgets/chat/InterruptedRunBanner';
import { KeyboardShortcutsHelp } from '../widgets/chat/KeyboardShortcutsHelp';
import { MemoryWriteHints } from '../widgets/chat/MemoryWriteHints';
import { RightPanel } from '../widgets/chat/RightPanel';
import { TerminalPanel } from '../widgets/chat/TerminalPanel';
import { TopicShiftBanner } from '../widgets/chat/TopicShiftBanner';
import { RewindDialog } from '../widgets/chat/rewind/RewindDialog';
import { ArchivesModal } from '../widgets/session';

import { ChatHeaderBar } from './chat/ChatHeaderBar';
import { PlanApprovalBar } from './chat/PlanApprovalBar';
import { useChatMessageActions } from './chat/useChatMessageActions';
import { useChatStickyScroll } from './chat/useChatStickyScroll';

/** 稳定空数组: toolCalls 缺省时避免每次渲染产生新引用击穿 RightPanel memo (F1) */
const EMPTY_TOOL_CALLS: readonly never[] = [];


export function Chat() {
  const {
    messages,
    isLoading,
    error,
    errorSessionId,
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
    reattachActiveStream, // R25-D4: renderer 重载后重接后端仍在跑的流
    clearTaskBoard, // Wave 3: 取消执行后清空任务板
    planApprovalFor, // PM2 (round8): 计划模式待批准的会话 ID
    preflightPhase, // Round 3 (2026-09-19): 编排拆解前置阶段（澄清/侦察指示）
    clearPlanApproval, // PM2: 清除批准状态
    pendingMessages, // P1-6: 排队待发消息（会自动连发，需可见可撤）
    cancelPending, // P1-6: 撤回单条排队消息
    clearPendingForSession, // P1-6: 清空本会话排队消息
  } = useChat();
  // right-panel R1 批次 A: 开合上抬 rightPanelStore（自动唤起/内联卡片需要
  // 跨组件写面板状态）；localStorage 迁移进 store，此处只读订阅。
  const isMobile = useIsMobile();
  const rightPanelOpen = useRightPanelStore((s) => s.open);

  const {
    currentSessionId,
    setCurrentSessionId,
    createSession,
    loadSessions,
    sessions,
    isLoading: storeLoading,
    removeMessage,
  } = useStore();
  const [tempChatSessions, setTempChatSessions] = useSessionMemoryPause(currentSessionId);
  const [orchMode, setOrchMode] = useState<string>('auto');

  // 崩溃恢复）后长任务输出不再丢失。内部有会话级去重守卫。
  useEffect(() => {
    if (!currentSessionId) return;
    void reattachActiveStream(currentSessionId);
  }, [currentSessionId, reattachActiveStream]);

  // L16 (round4 批次 A): run 级崩溃恢复横幅 —— 后端启动时把滞留 running
  // 的会话统一标记 failed(INTERRUPTED_RUN_ERROR);聊天页识别该终态后给出
  // "重发最后一条消息"的恢复入口,而不是让用户对着侧栏灰点猜。
  const currentSession = sessions.find((s) => s.id === currentSessionId);
  const interruptedRun =
    currentSession?.run_status === 'failed' && currentSession?.last_error === INTERRUPTED_RUN_ERROR;
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

  // 仅在当前会话命中时显示,避免后台会话触发的事件串台。`handleRetreat`
  // 由 TopicShiftBanner 在用户点"恢复完整上下文"后调用,组件已先调
  // sessionApi.retreatSegment 删 separator,这里再 loadMessages 重拉并清
  // 掉 store 里的 shiftInfo(防止 banner 重渲染)。
  //
  // Fix round 1 (2026-09-17): 后台会话触发的 topic_shifted 不会被 banner
  // 消费,如果一直留在 store 里,用户后续切回该会话就会看到陈旧横幅。
  // 这里读出时检查 createdAt:超过 30s(> 10s 自动消失时长,留足边界)
  // 视为过期,清掉 store 并返回 null。
  const SHIFT_INFO_TTL_MS = 30_000;
  const rawShiftInfo = useChatStreamStore((s) =>
    currentSessionId != null ? (s.sessions[currentSessionId]?.shiftInfo ?? null) : null,
  );
  const shiftInfo = useMemo(() => {
    if (!rawShiftInfo) return null;
    if (!currentSessionId) return null;
    if (Date.now() - rawShiftInfo.createdAt > SHIFT_INFO_TTL_MS) {
      // 过期:清掉 store,避免下次重渲染再次进入此分支
      useChatStreamStore.getState().setShiftInfo(currentSessionId, null);
      return null;
    }
    return rawShiftInfo;
  }, [rawShiftInfo, currentSessionId]);
  const handleRetreat = useCallback(async () => {
    if (!currentSessionId) return;
    useChatStreamStore.getState().setShiftInfo(currentSessionId, null);
    await loadMessages(currentSessionId);
  }, [currentSessionId, loadMessages]);
  const showTopicShiftBanner = currentSessionId != null && shiftInfo != null && !isLoading;
  const isTempChat = currentSessionId != null && tempChatSessions.has(currentSessionId);
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
  const [archivesOpen, setArchivesOpen] = useState(false);
  const { scrollRef, showJumpToLatest, scrollToLatest } = useChatStickyScroll({
    currentSessionId,
    messages,
    streamingMessageId,
    taskBoard,
  });

  const chatEndpoint = resolveEndpoint(settings.modelSelections.chatModel, settings.endpoints);
  const hasConfig =
    Boolean(chatEndpoint?.baseUrl) && Boolean(settings.modelSelections.chatModel.modelId);
  const showConfigWarning = !hasConfig;

  useEffect(() => {
    if (currentSessionId) {
      loadMessages(currentSessionId);
    }
  }, [currentSessionId, loadMessages]);


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
      // Clear location state so refresh doesn't re-send.
      // 2026-09 修复: 裸 replaceState({}, '') 会把 react-router 存在
      // history.state 里的 {idx, key} 一并抹掉, 破坏后退导航 —— 改走
      // router API 只清业务 state。
      navigate(location.pathname + location.search, { replace: true, state: null });
    }
  }, [
    pendingMessage,
    currentSessionId,
    sendMessage,
    settingsLoading,
    storeLoading,
    location.pathname,
    location.search,
    navigate,
  ]);

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
        orchestrationMode?: string;
        // PM1 (round8): /plan 计划模式 —— 本次 run 只读 + 计划产出。
        planMode?: boolean;
        /** Task 5 (2026-09-17): 上下文重置标记 —— "新话题" 按钮触发， 后端在本轮消息前插入 topic_separator 并清空 LLM 历史窗口。 */
        contextReset?: boolean;
      },
    ) => {
      clearError();
      const officeRefs = options?.officeRefs;
      const orchestrationMode = options?.orchestrationMode;
      // 后端口径: ≤4 张、单张解码后 ≤5MiB；前端先行裁剪并提示。
      const MAX_IMAGES = 4;

      // r75: 聊天文档附件 MIME 映射（扩展名集合用 useFileUpload.CHAT_DOCUMENT_EXTENSIONS 共享口径）
      const CHAT_DOC_MIME: Record<string, string> = {
        pdf: 'application/pdf',
        docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      };
      const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
      const dataUrls = (options?.images ?? [])
        .map((img) => img.dataUrl)
        .filter((d): d is string => Boolean(d));
      const sized = dataUrls.filter((d) => (d.length * 3) / 4 <= MAX_IMAGE_BYTES);
      if (sized.length < dataUrls.length) {
        toast.warning('部分图片超过 5MiB 上限，已跳过');
      }
      const images = sized.slice(0, MAX_IMAGES);
      if (sized.length > MAX_IMAGES) {
        toast.warning(`最多发送 ${MAX_IMAGES} 张图片，已截取前 ${MAX_IMAGES} 张`);
      }
      const attachmentMediaIds: string[] = [];
      for (const att of options?.attachments ?? []) {
        if (!att.dataUrl) continue;
        const ext = att.name.split('.').pop()?.toLowerCase() ?? '';
        if (!CHAT_DOCUMENT_EXTENSIONS.has(ext)) continue;
        try {
          const bytes = atob(att.dataUrl.split(',')[1] ?? '');
          const buffer = new Uint8Array(bytes.length);
          for (let i = 0; i < bytes.length; i++) buffer[i] = bytes.charCodeAt(i);
          const res = (await window.electronAPI?.media?.uploadAttachment?.(
            buffer.buffer,
            att.name,
            att.type || CHAT_DOC_MIME[ext] || 'text/plain',
          )) as { media_ref?: { id?: string } } | undefined;
          if (res?.media_ref?.id) {
            attachmentMediaIds.push(res.media_ref.id);
            // r74: 检索配置启用时自动建索引（fire-and-forget，不阻断发送）
            maybeIndexAttachment(res.media_ref.id);
          } else toast.warning(`附件上传失败: ${att.name}`);
        } catch {
          toast.warning(`附件上传失败: ${att.name}`);
        }
      }

      // r67: 超长文档检索注入（opt-in，localStorage 配置）
      const r67Rag = loadAttachmentRagConfig();
      const attachmentRag = r67Rag.enabled ? { embed: r67Rag.embed, top_k: r67Rag.top_k } : null;

      if (!currentSessionId) {
        const sessionId = await createSession();
        await sendMessage(content, sessionId, officeRefs, orchestrationMode, {
          planMode: options?.planMode,
          memoryDisabled: tempChatSessions.has(sessionId),
          images,
          attachmentMediaIds,
          attachmentRag,
          contextReset: options?.contextReset,
        });
      } else {
        await sendMessage(content, undefined, officeRefs, orchestrationMode, {
          planMode: options?.planMode,
          memoryDisabled: tempChatSessions.has(currentSessionId),
          images,
          attachmentMediaIds,
          attachmentRag,
          contextReset: options?.contextReset,
        });
      }
    },
    [clearError, currentSessionId, createSession, sendMessage, tempChatSessions],
  );

  const {
    handleCompact,
    handleLearn,
    handleFork,
    rewindTarget,
    setRewindTarget,
    handleRewind,
    handleRewindForked,
    editResendTarget,
    editResendNotice,
    quotedDraft,
    quoteText,
    handleStartEditResend,
    handleSendMessageWithEditResend,
    handleRegenerate,
    handleAnswerVersionChange,
    handleContinue,
    handleDeleteMessage,
    handleQuote,
    handleSaveToMemory,
    handleOpenMemory,
    handleBlockedAction,
    handleCancelRun,
    handleRerunFailed,
  } = useChatMessageActions({
    currentSessionId,
    isLoading,
    messages,
    loadMessages,
    loadSessions,
    setCurrentSessionId,
    removeMessage,
    sendMessage: sendMessage as never,
    handleSendMessage: handleSendMessage as never,
    clearTaskBoard,
    setArchivesOpen,
    navigate,
  });

  const handleToggleRightPanel = useCallback(() => {
    useRightPanelStore.getState().toggle();
  }, []);

  const artifactEventCount = useArtifactEventsStore((s) =>
    currentSessionId ? (s.counts[currentSessionId] ?? 0) : 0,
  );
  const seenArtifactCount = useRightPanelStore((s) =>
    currentSessionId ? (s.seenArtifactCount[currentSessionId] ?? 0) : 0,
  );
  const unseenArtifactCount = Math.max(0, artifactEventCount - seenArtifactCount);
  useEffect(() => {
    if (rightPanelOpen && currentSessionId) {
      useRightPanelStore.getState().markArtifactsSeen(currentSessionId);
    }
  }, [rightPanelOpen, currentSessionId, artifactEventCount]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'p' || e.key === 'P')) {
        e.preventDefault();
        handleToggleRightPanel();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [handleToggleRightPanel]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === '`') {
        e.preventDefault();
        useTerminalPanelStore.getState().toggle();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // R17-D: 顶层错误不再整页替换 —— 历史消息全部被顶掉、上下文丢失
  // 是主流应用的反模式。改为在消息区下方渲染内联错误条，历史与输入框
  // 保持可见可用，用户可"关闭"清除错误继续对话。

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <ChatHeaderBar
        workspacePath={workspacePath}
        currentSessionId={currentSessionId}
        orchMode={orchMode}
        setOrchMode={setOrchMode}
        isLoading={isLoading}
        hasConfig={hasConfig}
        onNewTopic={() => void handleSendMessageWithEditResend('', { contextReset: true })}
        isTempChat={isTempChat}
        setTempChatSessions={setTempChatSessions}
        onNewSession={handleNewSession}
        rightPanelOpen={rightPanelOpen}
        onToggleRightPanel={handleToggleRightPanel}
        unseenArtifactCount={unseenArtifactCount}
      />

      {/* P1 (UI 优化方案 2026-09-13): 内容行 —— 右面板 push 模式参与 flex
          布局（挤压主区成三栏，对齐 Claude artifacts）；窄屏回退 overlay。
          right-panel R1 批次 D: relative 供面板最大化时 absolute 覆盖。 */}
      <div className="flex-1 flex min-h-0 overflow-hidden relative">
        <div className="flex-1 flex flex-col min-h-0 min-w-0">
          {/* UX-IA R1 批次 B: 会话级提示按优先级合并（错误 > 中断 > 话题切换），
              同一时刻只展示最重要的一条，其余折叠为「另有 N 条提示」。
              R17-D 语义不变：只渲染归属当前会话的错误，"重试"作用于出错会话本身。 */}
          <ChatNoticeStack
            notices={[
              error != null &&
                error !== '' &&
                errorSessionId === currentSessionId && {
                  key: 'error',
                  priority: CHAT_NOTICE_PRIORITY.error,
                  node: (
                    <ChatInlineError
                      error={error}
                      onRetry={() => {
                        clearError();
                        const lastUser = [...messages].reverse().find((m) => m.role === 'user');
                        if (lastUser) void sendMessage(lastUser.content);
                      }}
                      onClose={clearError}
                    />
                  ),
                },
              showInterruptBanner && {
                key: 'interrupted',
                priority: CHAT_NOTICE_PRIORITY.interrupted,
                node: (
                  <InterruptedRunBanner
                    onRetry={retryInterruptedRun}
                    onDismiss={() =>
                      setDismissedInterrupts((prev) => new Set(prev).add(currentSessionId ?? ''))
                    }
                  />
                ),
              },
              showTopicShiftBanner && {
                key: 'topic-shift',
                priority: CHAT_NOTICE_PRIORITY.topicShift,
                node: (
                  <TopicShiftBanner
                    sessionId={currentSessionId!}
                    reason={shiftInfo.reason}
                    onRetreat={() => void handleRetreat()}
                  />
                ),
              },
            ]}
          />

          <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto relative">
            {isLoading && messages.length === 0 ? (
              <div className="flex items-center justify-center h-full">
                <LoadingState label="正在加载对话..." />
              </div>
            ) : (
              <MessageList
                messages={messages}
                sessionId={currentSessionId}
                streamingMessageId={streamingMessageId}
                onFork={handleFork}
                onRewind={handleRewind}
                onEditResend={handleStartEditResend}
                onRegenerate={handleRegenerate}
                onContinue={handleContinue}
                onAnswerVersionChange={handleAnswerVersionChange}
                onDelete={handleDeleteMessage}
                onQuote={handleQuote}
                onQuoteSelection={quoteText}
                onSaveToMemory={handleSaveToMemory}
                onOpenMemory={handleOpenMemory}
                onBlockedAction={handleBlockedAction}
              />
            )}
            {/* 对标 S2: 内联记忆提示（"已记住"可撤销）；临时聊天不显示 */}
            {!isTempChat && <MemoryWriteHints sessionId={currentSessionId} />}
            <PlanApprovalBar
              planApprovalFor={planApprovalFor}
              currentSessionId={currentSessionId}
              clearPlanApproval={clearPlanApproval}
              messages={messages}
              sendMessage={sendMessage as never}
              preflightPhase={preflightPhase}
              taskBoard={taskBoard ?? null}
              onCancelRun={handleCancelRun}
            />
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

          {/* P2-6 运行后摘要：编排 run 终态时补一段「结果 / 碰了什么 / 哪些失败」。
              与 SubagentLivePanel 互斥（一个渲染运行中、一个渲染结束后），
              位置相邻，用户视线不用跳。普通对话无 taskBoard → 组件自行返回 null。 */}
          <RunSummaryPanel
            sessionId={currentSessionId}
            onRerunFailed={
              taskBoard
                ? () => void handleRerunFailed(taskBoard.runId)
                : undefined
            }
          />

          {showConfigWarning && (
            <div
              data-testid="config-warning"
              className="px-4 py-2 bg-warning/10 border-t border-warning/40 text-warning text-xs flex items-center gap-2"
            >
              <span aria-hidden="true">⚠️</span>
              <span>
                未配置 API 端点或对话模型，
                <button
                  type="button"
                  onClick={() => navigate('/settings')}
                  className="underline text-warning hover:text-warning/80 transition-colors"
                >
                  前往设置
                </button>
              </span>
            </div>
          )}

          {/* TM2 (DSH 对标 R11): 上下文水位徽章（≥0.6 才渲染） */}
          <KeyboardShortcutsHelp />
          {/* P1-6: 排队队列常驻可见。放在输入框正上方 —— 队列会在当前回复
              结束后自动连发，用户必须能在真正发出去之前看见并撤回。
              只展示当前会话的条目（队列按会话隔离，见 useChat S3）。 */}
          <PendingQueueStrip
            items={pendingMessages
              .filter((p) => p.sid === currentSessionId)
              .map((p) => ({ id: p.id, content: p.content }))}
            onCancel={cancelPending}
            onClearAll={() => {
              if (currentSessionId) clearPendingForSession(currentSessionId);
            }}
          />
          <ChatInput
            onSend={handleSendMessageWithEditResend}
            onInterrupt={interrupt}
            onCompact={handleCompact}
            onLearn={handleLearn}
            isLoading={isLoading}
            disabled={!hasConfig}
            placeholder="输入消息..."
            workspacePath={workspacePath}
            injectedDraft={editResendTarget ?? quotedDraft}
            editResendNotice={editResendNotice}
            orchestrationMode={orchMode}
            onOrchestrationModeChange={setOrchMode}
            hideOrchModeBar
            hideNewTopic
          />
          {/* Phase 3 (2026-09-25): 底部终端面板（VS Code 风格），Ctrl+` 切换 */}
          <TerminalPanel />
        </div>
        {/* /左列 */}

        {/* Artifacts Panel: 桌面端 push（挤压主区），窄屏 overlay 回退。
            right-panel R1: 开合/Tab/最大化/选中产物由 rightPanelStore 自持 */}
        <RightPanel
          variant={isMobile ? 'overlay' : 'push'}
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
          onRerunFailed={(runId) => void handleRerunFailed(runId)}
          onRetryTask={(runId, taskId) => void handleRerunFailed(runId, [taskId])}
          onSelectRun={(run) => {
            // RD23 (round52): 历史 run 浏览器 —— 切换到所选 run 的任务板。
            const restored = restoreRunToBoard(run);
            if (restored && currentSessionId) {
              useChatStreamStore.getState().setTaskBoard(currentSessionId, {
                runId: run.run_id,
                plan: restored.plan,
                statuses: restored.statuses,
                progress: restored.progress,
                dispatchedAt: restored.dispatchedAt,
                endedAt: restored.endedAt,
              });
            }
          }}
        />
      </div>
      {/* /内容行 */}

      {/* R17-A2: 压缩谱系归档查看器（compact 成功 toast「查看归档」打开） */}
      <ArchivesModal
        isOpen={archivesOpen}
        onClose={() => setArchivesOpen(false)}
        sessionId={currentSessionId}
      />
      {rewindTarget && currentSessionId && (
        <RewindDialog
          isOpen
          sessionId={currentSessionId}
          messageId={rewindTarget.messageId}
          messageCreatedAt={rewindTarget.createdAt}
          onClose={() => setRewindTarget(null)}
          onForked={handleRewindForked}
        />
      )}
    </div>
  );
}
