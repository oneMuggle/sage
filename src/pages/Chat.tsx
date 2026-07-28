import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { resolveEndpoint } from '../entities/setting/types';
import { useSettings } from '../features/manage-settings/useSettings';
import { useChat } from '../features/send-message/useChat';
import { sessionApi, type ChatOfficeRef } from '../shared/api';
import { useI18n } from '../shared/lib/i18n';
import { useStore } from '../shared/lib/store';
import { useCurrentWorkspace } from '../shared/lib/workspaceContext';
import { ErrorState } from '../shared/ui/ErrorState';
import { LoadingState } from '../shared/ui/LoadingState';
import { ActiveAgentIndicator, ChatInput, MessageList } from '../widgets/chat';

/** t() 结果是静态模板，这里做最小占位符替换（i18n 无内置插值）。 */
function fill(template: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (acc, [key, value]) => acc.replace(`{${key}}`, String(value)),
    template,
  );
}

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
  } = useChat();

  const {
    currentSessionId,
    setCurrentSessionId,
    createSession,
    loadSessions,
    isLoading: storeLoading,
  } = useStore();
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
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastMsg = messages[messages.length - 1];
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [
    messages.length,
    lastMsg?.content,
    lastMsg?.reasoning_content,
    lastMsg?.tool_calls?.length,
    // streamingMessageId 变化时也需要滚 (新 stream 开始)
    streamingMessageId,
  ]);

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
      // Clear location state so refresh doesn't re-send
      window.history.replaceState({}, '');
    }
  }, [pendingMessage, currentSessionId, sendMessage, settingsLoading, storeLoading]);

  const handleNewSession = async () => {
    const sessionId = await createSession();
    setCurrentSessionId(sessionId);
  };

  const handleSendMessage = async (
    content: string,
    options?: {
      knowledgeRefs?: { id: string; title: string }[];
      attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
      images?: { name: string; size: number; type: string; dataUrl?: string }[];
      officeRefs?: readonly ChatOfficeRef[];
    },
  ) => {
    clearError();
    const officeRefs = options?.officeRefs;
    if (!currentSessionId) {
      const sessionId = await createSession();
      await sendMessage(content, sessionId, officeRefs);
    } else {
      await sendMessage(content, undefined, officeRefs);
    }
  };

  // M4: /compact slash action — 调后端压缩当前会话，成功后重载消息
  // （续接摘要行由后端持久化，重载后即显示在聊天列表中）。
  // MEDIUM-1: 流式中（isLoading）early-return —— 两个并发手动压缩会在后端
  // 各自通过 should_compact 检查并写出重复续接行；前端守卫是必须的修复，
  // 后端 409 compact_in_progress 只是兜底。
  const handleCompact = async () => {
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
        toast.error(fill(t('chat.compact_failed'), { message: result.message ?? result.error ?? '' }));
      }
    } catch (e) {
      toast.error(
        fill(t('chat.compact_failed'), { message: e instanceof Error ? e.message : String(e) }),
      );
    }
  };

  // M4: 消息级分叉 — 非破坏性操作（无需确认）。成功后切换到新会话
  // （复用现有 session-switch 路径：setCurrentSessionId → loadMessages effect）。
  // MEDIUM-1: 流式中（isLoading）early-return —— 流式写入与 fork 前缀复制
  // 并发会复制出不完整的消息序列，且中途切换会话会打断流式 UI。
  const handleFork = async (messageId: string) => {
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
        <h2 className="text-sm font-semibold text-text">对话</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={handleNewSession}
            className="px-2 py-1 text-xs border border-border rounded-radius-sm hover:bg-bg-hover transition-colors"
          >
            + 新对话
          </button>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
        {isLoading && messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <LoadingState label="正在加载对话..." />
          </div>
        ) : (
          <MessageList
            messages={messages}
            streamingMessageId={streamingMessageId}
            onFork={handleFork}
          />
        )}
      </div>

      {/* 阶段 4 + P2: 流式处理时显示当前活跃 agent + 迭代轮次 + 阶段 */}
      <ActiveAgentIndicator
        agentId={currentAgentId}
        iteration={iteration}
        streamingState={streamingState}
      />

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
        onSend={handleSendMessage}
        onInterrupt={interrupt}
        onCompact={handleCompact}
        isLoading={isLoading}
        disabled={!hasConfig}
        placeholder="输入消息..."
        workspacePath={workspacePath}
      />
    </div>
  );
}
