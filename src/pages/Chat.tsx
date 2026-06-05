import { useEffect } from 'react';

import { useChat } from '../features/send-message/useChat';
import { useStore } from '../lib/store';
import { ChatInput, MessageList } from '../widgets/chat';

export function Chat() {
  const { messages, isLoading, error, clearError, sendMessage, interrupt, loadMessages } =
    useChat();

  const { currentSessionId, setCurrentSessionId, createSession } = useStore();

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

      {/* Error banner */}
      {error && (
        <div className="mx-4 mt-2 px-3 py-2 text-xs rounded-radius-sm bg-red-50 border border-red-200 text-red-700 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={clearError} className="ml-2 text-red-500 hover:text-red-700 font-medium">
            关闭
          </button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        <MessageList messages={messages} />
      </div>

      <ChatInput
        onSend={handleSendMessage}
        onInterrupt={interrupt}
        isLoading={isLoading}
        disabled={false}
        placeholder="输入消息..."
      />
    </div>
  );
}
