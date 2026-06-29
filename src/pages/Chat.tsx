import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { resolveEndpoint } from '../entities/setting/types';
import { useSettings } from '../features/manage-settings/useSettings';
import { CreateTaskModal } from '../features/scheduled/CreateTaskModal';
import { useChat } from '../features/send-message/useChat';
import { useStore } from '../shared/lib/store';
import { ErrorState } from '../shared/ui/ErrorState';
import { LoadingState } from '../shared/ui/LoadingState';
import { ActiveAgentIndicator, ChatInput, MessageList } from '../widgets/chat';

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
    isLoading: storeLoading,
  } = useStore();
  const { settings, isLoading: settingsLoading } = useSettings();
  const navigate = useNavigate();
  const location = useLocation();
  const pendingSentRef = useRef(false);
  const [scheduleModalOpen, setScheduleModalOpen] = useState(false);
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
    _options?: {
      knowledgeRefs?: { id: string; title: string }[];
      attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
      images?: { name: string; size: number; type: string; dataUrl?: string }[];
    },
  ) => {
    clearError();
    if (!currentSessionId) {
      const sessionId = await createSession();
      await sendMessage(content, sessionId);
    } else {
      await sendMessage(content);
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
          <MessageList messages={messages} streamingMessageId={streamingMessageId} />
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
        onSchedule={() => setScheduleModalOpen(true)}
        isLoading={isLoading}
        disabled={!hasConfig}
        placeholder="输入消息..."
      />
      {scheduleModalOpen && currentSessionId && (
        <CreateTaskModal
          open={scheduleModalOpen}
          onClose={() => setScheduleModalOpen(false)}
          sessionId={currentSessionId}
        />
      )}
    </div>
  );
}
