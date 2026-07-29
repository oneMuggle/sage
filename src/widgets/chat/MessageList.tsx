import { BtwOverlay } from '../../features/chat';
import type { Message as MessageType } from '../../shared/lib/store';

import { Message } from './Message';

interface MessageListProps {
  messages: MessageType[];
  knowledgeRefs?: Record<string, { id: string; title: string }[]>;
  attachments?: Record<string, { name: string; size: number; type: string; dataUrl?: string }[]>;
  /** P1: 当前正在流式输出的消息 ID (用于 ThinkingPanel 自动展开) */
  streamingMessageId?: string | null;
  /** M4: 消息级分叉回调（提供时 user/assistant 消息显示分叉按钮） */
  onFork?: (messageId: string) => void;
}

export function MessageList({
  messages,
  knowledgeRefs,
  attachments,
  streamingMessageId,
  onFork,
}: MessageListProps) {
  if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted">
        <p className="text-lg mb-2">欢迎使用 Sage</p>
        <p className="text-sm">开始一段新对话吧</p>
      </div>
    );
  }

  return (
    <>
      <div className="p-4 space-y-4">
        {messages.map((message) => (
          <Message
            key={message.id}
            message={message}
            knowledgeRefs={knowledgeRefs?.[message.id]}
            attachments={attachments?.[message.id]}
            isStreaming={message.id === streamingMessageId}
            onFork={onFork}
          />
        ))}
      </div>
      <BtwOverlay />
    </>
  );
}
