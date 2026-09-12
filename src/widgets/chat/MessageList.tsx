import { ChevronUp } from 'lucide-react';
import { useEffect, useState } from 'react';

import { BtwOverlay } from '../../features/chat';
import type { Message as MessageType } from '../../shared/lib/store';

import { Message } from './Message';

/** U11 (批次 C-3): 尾窗渲染步长 —— "加载更早"每次多显示的条数 */
const WINDOW_STEP = 60;

interface MessageListProps {
  messages: MessageType[];
  knowledgeRefs?: Record<string, { id: string; title: string }[]>;
  attachments?: Record<string, { name: string; size: number; type: string; dataUrl?: string }[]>;
  /** P1: 当前正在流式输出的消息 ID (用于 ThinkingPanel 自动展开) */
  streamingMessageId?: string | null;
  /** M4: 消息级分叉回调（提供时 user/assistant 消息显示分叉按钮） */
  onFork?: (messageId: string) => void;
  /** U5': 编辑重发回调（提供时 user 消息显示编辑按钮） */
  onEditResend?: (messageId: string) => void;
  /** R18-A: 重新生成回调（提供时 assistant 消息显示重新生成按钮） */
  onRegenerate?: (messageId: string) => void;
}

export function MessageList({
  messages,
  knowledgeRefs,
  attachments,
  streamingMessageId,
  onFork,
  onEditResend,
  onRegenerate,
}: MessageListProps) {
  // U11: 只渲染最近 WINDOW_STEP 条, 更早的按需加载 —— 避免长会话全量
  // 重渲染(每条 Message 都可能含 ReactMarkdown/Shiki)。
  const [windowSize, setWindowSize] = useState(WINDOW_STEP);
  const firstId = messages[0]?.id;

  // 切会话时重置窗口
  useEffect(() => {
    setWindowSize(WINDOW_STEP);
  }, [firstId]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted">
        <p className="text-lg mb-2">欢迎使用 Sage</p>
        <p className="text-sm">开始一段新对话吧</p>
      </div>
    );
  }

  const hiddenCount = Math.max(0, messages.length - windowSize);
  const visible = messages.slice(messages.length - windowSize);

  return (
    <>
      <div className="p-4 space-y-4">
        {hiddenCount > 0 && (
          <button
            data-testid="load-earlier"
            className="mx-auto flex items-center gap-1 px-3 py-1.5 text-xs border border-border rounded-radius-sm text-text-secondary hover:bg-bg-hover transition-colors"
            onClick={() => setWindowSize((w) => w + WINDOW_STEP)}
          >
            <ChevronUp className="w-3 h-3" />
            加载更早消息（还有 {hiddenCount} 条）
          </button>
        )}
        {visible.map((message) => (
          <Message
            key={message.id}
            message={message}
            knowledgeRefs={knowledgeRefs?.[message.id]}
            attachments={attachments?.[message.id]}
            isStreaming={message.id === streamingMessageId}
            onFork={onFork}
            onEditResend={onEditResend}
            onRegenerate={onRegenerate}
          />
        ))}
      </div>
      <BtwOverlay />
    </>
  );
}
