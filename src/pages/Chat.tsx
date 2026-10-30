import { ChevronDown } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { StepConfirmDialog } from '../components/StepConfirmDialog';
import type { StepConfirmAction } from '../components/StepConfirmDialog';
import { resolveEndpoint } from '../entities/setting/types';
import { useArtifactEventsStore } from '../features/artifacts/artifactEventsStore';
import { useSessionMemoryPause } from '../features/chat/useSessionMemoryPause';
import { useSettings } from '../features/manage-settings/useSettings';
import { useRightPanelStore } from '../features/right-panel/rightPanelStore';
import {
  selectSessionSlots,
  useChatStreamStore,
  type QueuedChatMessage,
} from '../features/send-message/chatStreamStore';
import type { DeliveryMode } from '../features/send-message/deliveryMode';
import { buildMessageDisplayMeta } from '../features/send-message/messageDisplayMeta';
import { restoreRunToBoard } from '../features/send-message/orchestrationEvents';
import type { PendingComposerOptions } from '../features/send-message/pendingComposerOptions';
import { useChat } from '../features/send-message/useChat';
import { useTerminalPanelStore } from '../features/terminal-panel/terminalPanelStore';
import { type ChatOfficeRef } from '../shared/api';
import { maybeIndexAttachment } from '../shared/api/attachmentAutoIndex';
import { loadAttachmentRagConfig } from '../shared/api/attachmentRagConfig';
import { orchRunControlClient } from '../shared/api/orchRunControlClient';
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
  RunSummaryPanel,
  SubagentLivePanel,
} from '../widgets/chat';
import { ChatSessionNotices } from '../widgets/chat/ChatSessionNotices';
import { KeyboardShortcutsHelp } from '../widgets/chat/KeyboardShortcutsHelp';
import { MemoryWriteHints } from '../widgets/chat/MemoryWriteHints';
import { PendingQueuePanel } from '../widgets/chat/PendingQueuePanel';
import { RightPanel } from '../widgets/chat/RightPanel';
import { TerminalPanel } from '../widgets/chat/TerminalPanel';
import { RewindDialog } from '../widgets/chat/rewind/RewindDialog';
import { ArchivesModal } from '../widgets/session';

import { ChatHeaderBar } from './chat/ChatHeaderBar';
import { PlanApprovalBar } from './chat/PlanApprovalBar';
import { useChatMessageActions } from './chat/useChatMessageActions';
import { useChatStickyScroll } from './chat/useChatStickyScroll';

/** 稳定空数组: toolCalls 缺省时避免每次渲染产生新引用击穿 RightPanel memo (F1) */
const EMPTY_TOOL_CALLS: readonly never[] = [];

/** 队列空态的稳定引用：useChat 在部分测试里被 mock 掉字段，兜底值必须是同一引用。 */
const EMPTY_PENDING_QUEUE: readonly QueuedChatMessage[] = [];

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
    executionModeRecommendation, // 2026-10-28 (Plan Mode 增强): 执行模式推荐
    clearPlanApproval, // PM2: 清除批准状态
    pendingQueue, // U5 (2026-09-18): 本会话待发送队列
    queuePaused, // U5: 队列是否因上一轮异常收尾而暂停
    removeQueuedMessage,
    moveQueuedMessageToFront,
    reorderQueuedMessages,
    clearQueuedMessages,
    editQueuedMessage,
    sendQueuedMessageNow,
    resumeQueuedMessages,
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
  // Issue 1 (2026-10-29): 横幅组装与"已忽略"状态已下沉到 ChatSessionNotices。
  const currentSession = sessions.find((s) => s.id === currentSessionId);

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

  // Phase 3 (2026-10-28): 步骤确认 —— 后端推 awaiting_step_confirm 事件后
  // 写入 store 的 stepConfirm 槽位。渲染 StepConfirmDialog 等用户选择；
  // 用户响应后调后端 /runs/{runId}/step-confirm 唤醒 dispatcher 并清空槽位。
  const stepConfirm = useChatStreamStore((s) =>
    currentSessionId != null ? selectSessionSlots(s, currentSessionId).stepConfirm : null,
  );
  const stepConfirmRunId = useChatStreamStore((s) =>
    currentSessionId != null ? selectSessionSlots(s, currentSessionId).taskBoard?.runId : null,
  );
  // Issue 3: 跨 run 累加的轮次偏移。后端 ReAct 的 iteration 是每次 run 的局部
  // 计数器（for i in range(max_iterations)），失败后"继续"会从 0 重新开始。
  // 前端在 clearStream 时把上一轮已达轮次累加进 iterationOffset，
  // 显示时用 offset + 当前 run 的 iteration，实现"接着上次继续"。
  const iterationOffset = useChatStreamStore((s) =>
    currentSessionId != null ? selectSessionSlots(s, currentSessionId).iterationOffset : 0,
  );
  const handleStepConfirm = useCallback(
    async (action: StepConfirmAction) => {
      if (!currentSessionId || !stepConfirm) return;
      // code review #14: 槽位有 pending 确认但拿不到 runId 时不能静默 return —
      // 对话框按钮点了没反应，用户只能刷新页面。报错并清空本地槽位，
      // dispatcher 端 600s 超时会以 abort 收口。
      if (!stepConfirmRunId) {
        toast.error('步骤确认缺少 run 信息，已跳过此步确认');
        useChatStreamStore.getState().setStepConfirm(currentSessionId, null);
        return;
      }
      try {
        await orchRunControlClient.confirmStep({
          run_id: stepConfirmRunId,
          task_id: stepConfirm.stepId,
          action,
        });
      } catch (err) {
        // 失败仍清空本地槽位，避免对话框卡死；dispatcher 端 600s 超时会以 abort 收口。
        const message = err instanceof Error ? err.message : String(err);
        toast.error(`步骤确认提交失败：${message}`);
      } finally {
        useChatStreamStore.getState().setStepConfirm(currentSessionId, null);
      }
    },
    [currentSessionId, stepConfirm, stepConfirmRunId],
  );
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
  const { scrollRef, showScrollToBottom, scrollToLatest } = useChatStickyScroll({
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

  // Auto-send pending message passed from Welcome page via router state.
  // The effect lives below `handleSendMessage` so the first message reuses the
  // same upload path (attachments / images / office refs) as in-chat sends.
  const pendingMessage = (location.state as { pendingMessage?: string } | null)?.pendingMessage;
  const pendingOptions = (location.state as { pendingOptions?: PendingComposerOptions } | null)
    ?.pendingOptions;

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
        /**
         * P2-a: 投递通道（插话 / 排队 / 打断并发送）—— 只在当前会话已有活跃
         * 流时有语义，空闲发送时 useChat 会忽略。
         */
        delivery?: DeliveryMode;
      },
    ) => {
      clearError();
      const officeRefs = options?.officeRefs;
      const orchestrationMode = options?.orchestrationMode;
      // 后端口径: ≤4 张、单张解码后 ≤5MiB；前端先行裁剪并提示。
      const MAX_IMAGES = 4;

      // r75: 聊天文档附件 MIME 映射（扩展名集合用 useFileUpload.CHAT_DOCUMENT_EXTENSIONS 共享口径）
      // 2026-10-13: 新增 xlsx MIME（后端 openpyxl 解析需要正确 content-type）
      const CHAT_DOC_MIME: Record<string, string> = {
        pdf: 'application/pdf',
        docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
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

      // 用户消息展示元数据：气泡上回显附件 / @ 文件引用 / office 引用。
      // 只保留真正随消息上传的文档附件（不支持的扩展名已在上层提示丢弃），
      // 且不含 dataUrl —— 避免 base64 落库。
      const displayMeta = buildMessageDisplayMeta({
        content,
        attachments: (options?.attachments ?? []).filter((att) => {
          if (!att.dataUrl) return false;
          const ext = att.name.split('.').pop()?.toLowerCase() ?? '';
          return CHAT_DOCUMENT_EXTENSIONS.has(ext);
        }),
        images: options?.images,
        officeRefs,
        knowledgeRefs: options?.knowledgeRefs,
        workspacePath,
      });

      if (!currentSessionId) {
        const sessionId = await createSession();
        await sendMessage(content, sessionId, officeRefs, orchestrationMode, {
          planMode: options?.planMode,
          memoryDisabled: tempChatSessions.has(sessionId),
          images,
          attachmentMediaIds,
          attachmentRag,
          contextReset: options?.contextReset,
          displayMeta,
        });
      } else {
        await sendMessage(content, undefined, officeRefs, orchestrationMode, {
          planMode: options?.planMode,
          memoryDisabled: tempChatSessions.has(currentSessionId),
          images,
          attachmentMediaIds,
          attachmentRag,
          contextReset: options?.contextReset,
          // P2-a: 会话忙时的投递通道（插话 / 排队 / 打断并发送）
          delivery: options?.delivery,
          displayMeta,
        });
      }
    },
    [clearError, currentSessionId, createSession, sendMessage, tempChatSessions],
  );

  // Auto-send the message composed on the Welcome page. Runs after mount and
  // as soon as the session/config are ready; `handleSendMessage` performs the
  // same attachment/image upload as an in-chat send so drag-and-drop files
  // referenced on the Welcome page are not lost.
  // 2026-10-29 修复: 仅附件/引用、无正文时 pendingMessage 为空字符串,
  // 旧守卫 `pendingMessage &&` 会把整条消息丢弃 —— 改为「有正文或有选项」
  // 任一成立即触发。
  const hasPendingContent = Boolean(
    pendingMessage ||
    (pendingOptions &&
      ((pendingOptions.attachments && pendingOptions.attachments.length > 0) ||
        (pendingOptions.images && pendingOptions.images.length > 0) ||
        (pendingOptions.officeRefs && pendingOptions.officeRefs.length > 0) ||
        (pendingOptions.knowledgeRefs && pendingOptions.knowledgeRefs.length > 0))),
  );
  useEffect(() => {
    if (
      hasPendingContent &&
      currentSessionId &&
      !pendingSentRef.current &&
      !settingsLoading &&
      !storeLoading
    ) {
      pendingSentRef.current = true;
      void handleSendMessage(pendingMessage ?? '', pendingOptions);
      // Clear location state so refresh doesn't re-send.
      // 2026-09 修复: 裸 replaceState({}, '') 会把 react-router 存在
      // history.state 里的 {idx, key} 一并抹掉, 破坏后退导航 —— 改走
      // router API 只清业务 state。
      navigate(location.pathname + location.search, { replace: true, state: null });
    }
  }, [
    hasPendingContent,
    pendingMessage,
    pendingOptions,
    currentSessionId,
    handleSendMessage,
    settingsLoading,
    storeLoading,
    location.pathname,
    location.search,
    navigate,
  ]);

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
    setDraftText,
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

  // U5 (2026-09-18): 待发送队列操作。"编辑"复用 injectedDraft 通道把排队
  // 内容回填输入框（不触发编辑重发的 fork 语义）；"立即发送"由 useChat
  // 负责先停当前流再发。可选调用是兜底:部分测试 mock useChat 时缺这些键。
  const handleEditQueuedMessage = useCallback(
    (id: string) => {
      // 编辑重发态下 injectedDraft 被 editResendTarget 占用（约定：编辑态优先），
      // 此时取走排队消息会无处回填、内容静默丢失 —— 因此先挡住，不动队列。
      if (editResendTarget) {
        toast.info('请先完成或取消当前消息的编辑');
        return;
      }
      const item = editQueuedMessage?.(id);
      if (item) setDraftText?.(item.content);
    },
    [editQueuedMessage, editResendTarget, setDraftText],
  );
  const handleSendQueuedNow = useCallback(
    (id: string) => {
      void sendQueuedMessageNow?.(id);
    },
    [sendQueuedMessageNow],
  );
  const handleMoveQueuedToFront = useCallback(
    (id: string) => {
      moveQueuedMessageToFront?.(id);
    },
    [moveQueuedMessageToFront],
  );
  const handleReorderQueue = useCallback(
    (fromId: string, toId: string) => {
      reorderQueuedMessages?.(fromId, toId);
    },
    [reorderQueuedMessages],
  );
  const handleRemoveQueuedMessage = useCallback(
    (id: string) => {
      removeQueuedMessage?.(id);
    },
    [removeQueuedMessage],
  );
  const handleClearQueue = useCallback(() => {
    clearQueuedMessages?.();
  }, [clearQueuedMessages]);
  const handleResumeQueue = useCallback(() => {
    resumeQueuedMessages?.();
  }, [resumeQueuedMessages]);
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
          {/* UX-IA R1 批次 B: 会话级提示按优先级合并（错误 > 会话失败 > 中断 > 话题切换），
              同一时刻只展示最重要的一条，其余折叠为「另有 N 条提示」。
              R17-D 语义不变：只渲染归属当前会话的错误，"重试"作用于出错会话本身。
              Issue 1 (2026-10-29): 通知组装逻辑下沉到 ChatSessionNotices。 */}
          <ChatSessionNotices
            currentSessionId={currentSessionId}
            currentSession={currentSession}
            error={error}
            errorSessionId={errorSessionId}
            messages={messages}
            shiftInfo={shiftInfo}
            isLoading={isLoading}
            onClearError={clearError}
            onSendMessage={sendMessage}
            onRetreat={() => void handleRetreat()}
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
                runStatus={currentSession?.run_status}
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
              recommendedExecutionMode={executionModeRecommendation?.mode ?? null}
              executionModeReasoning={executionModeRecommendation?.reasoning}
            />
            {/* Issue 4: 滚动到底部按钮 — 从文档流迁移到滚动容器内，sticky 悬浮在底部。
                pointer-events-none 让容器背景不拦点击，仅按钮可点。 */}
            {showScrollToBottom && (
              <div className="sticky bottom-2 flex justify-center py-2 pointer-events-none">
                <button
                  type="button"
                  onClick={scrollToLatest}
                  aria-label="滚动到最新消息"
                  className="pointer-events-auto flex items-center justify-center w-9 h-9 rounded-full bg-bg-elevated border border-border shadow-lg hover:bg-bg-hover transition-colors"
                >
                  <ChevronDown className="w-4 h-4 text-text-secondary" />
                </button>
              </div>
            )}
          </div>

          {/* Phase 3 (2026-10-28): 步骤确认对话框 —— auto_confirm 步骤执行前
              弹出，等用户 continue/skip/abort。固定浮层，覆盖全屏。 */}
          {stepConfirm && <StepConfirmDialog step={stepConfirm} onConfirm={handleStepConfirm} />}

          {/* 阶段 4 + P2: 流式处理时显示当前活跃 agent + 迭代轮次 + 阶段 */}
          <ActiveAgentIndicator
            agentId={currentAgentId}
            iteration={iteration}
            iterationOffset={iterationOffset}
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
            onRerunFailed={taskBoard ? () => void handleRerunFailed(taskBoard.runId) : undefined}
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
          {/* U5: 待发送队列常驻可见 —— 队列会在当前回复结束后自动连发，
              用户必须能在真正发出去之前看见 / 撤回 / 置顶 / 立即发送。 */}
          <PendingQueuePanel
            items={pendingQueue ?? EMPTY_PENDING_QUEUE}
            paused={Boolean(queuePaused)}
            onSendNow={handleSendQueuedNow}
            onEdit={handleEditQueuedMessage}
            onMoveToFront={handleMoveQueuedToFront}
            onReorder={handleReorderQueue}
            onRemove={handleRemoveQueuedMessage}
            onClear={handleClearQueue}
            onResume={handleResumeQueue}
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

// eslint-disable-next-line react-refresh/only-export-components
export function auditChatPageGovernance(
  state: {
    headerControlsInTopBar?: boolean;
    singleRowBottomComposer?: boolean;
    activeSessionId?: string;
  } = {},
): {
  module: 'src/pages/Chat.tsx';
  phase: 'P143';
  headerControlsInTopBar: boolean;
  singleRowBottomComposer: boolean;
  activeSessionId: string;
  healthy: boolean;
} {
  const headerControlsInTopBar = state.headerControlsInTopBar !== false;
  const singleRowBottomComposer = state.singleRowBottomComposer !== false;
  const activeSessionId =
    typeof state.activeSessionId === 'string' && state.activeSessionId.trim().length > 0
      ? state.activeSessionId.trim()
      : 'default';
  return {
    module: 'src/pages/Chat.tsx',
    phase: 'P143',
    headerControlsInTopBar,
    singleRowBottomComposer,
    activeSessionId,
    healthy: headerControlsInTopBar && singleRowBottomComposer && activeSessionId.length > 0,
  };
}
