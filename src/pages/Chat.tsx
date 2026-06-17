import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { useSettings } from '../features/manage-settings/useSettings';
import { useChat } from '../features/send-message/useChat';
import { useStore } from '../shared/lib/store';
import { ErrorState } from '../shared/ui/ErrorState';
import { LoadingState } from '../shared/ui/LoadingState';
import { ChatInput, MessageList } from '../widgets/chat';

export function Chat() {
  const { messages, isLoading, error, clearError, sendMessage, interrupt, loadMessages } =
    useChat();

  const { currentSessionId, setCurrentSessionId, createSession } = useStore();
  const { settings } = useSettings();
  const navigate = useNavigate();
  // PR-7: 跟随新消息/流式 token 自动滚到底。依赖同时含 messages.length
  // 和最后一条消息的 content 长度 — 流式更新时 length 不变但 content 在变。
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastMsg = messages[messages.length - 1];
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, lastMsg?.content]);

  const activeEndpoint = settings.endpoints.find((e) => e.isActive);
  const hasConfig =
    Boolean(activeEndpoint?.baseUrl) && Boolean(settings.modelSelections.chatModelId);
  const showConfigWarning = !hasConfig;

  useEffect(() => {
    if (currentSessionId) {
      loadMessages(currentSessionId);
    }
  }, [currentSessionId, loadMessages]);

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
    <div className="flex-1 flex flex-col">
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

      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {isLoading && messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <LoadingState label="正在加载对话..." />
          </div>
        ) : (
          <MessageList messages={messages} />
        )}
      </div>

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
        isLoading={isLoading}
        disabled={!hasConfig}
        placeholder="输入消息..."
      />
    </div>
  );
}
