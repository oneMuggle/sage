import { ChevronUp } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import type { Artifact } from '../../features/artifacts/artifactApi';
import { useArtifacts } from '../../features/artifacts/useArtifacts';
import { BtwOverlay } from '../../features/chat';
import { useMessageJump } from '../../features/chat/useMessageJump';
import type { Message as MessageType } from '../../shared/lib/store';

import { ChatFindBar } from './ChatFindBar';
import { Message } from './Message';
import { SelectionQuoteButton } from './SelectionQuoteButton';
import { TopicSeparator } from './TopicSeparator';

/** U11 (批次 C-3): 尾窗渲染步长 —— "加载更早"每次多显示的条数 */
const WINDOW_STEP = 60;

/** 对话阅读导航 A1: 定位命中后的短暂高亮（JUMP_FLASH_MS 后移除） */
const JUMP_FLASH_CLASS = 'rounded-radius-sm ring-2 ring-primary/50 bg-primary/5 transition-shadow';

interface MessageListProps {
  messages: MessageType[];
  /** right-panel R1 批次 B: 当前会话 ID —— 拉取产物列表建立
   * tool_call_id → 产物[] 映射，供消息内联产物 chip 点击直达预览 */
  sessionId?: string | null;
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
  /** R17-B: 消息删除回调（提供时历史消息显示两步确认删除按钮） */
  onDelete?: (messageId: string) => void;
  /** P0-1: 引用到对话回调（提供时 user/assistant 消息显示"引用到对话"） */
  onQuote?: (message: MessageType) => void;
  /** 对话阅读导航 A4: 划词引用回调（提供时在消息正文选中文本会浮出"引用"按钮） */
  onQuoteSelection?: (text: string) => void;
  /** P0-1: 保存此条消息到长期记忆（提供时 user/assistant 消息显示"保存到记忆"） */
  onSaveToMemory?: (message: MessageType) => void;
  /** 第二轮 B2: 继续生成（只传给最后一条消息，且仅在没有流式输出时） */
  onContinue?: () => void;
  /** 第二轮 C2: 回答版本切换后的回调（同上，只传给最后一条消息） */
  onAnswerVersionChange?: () => void;
}

export function MessageList({
  messages,
  sessionId,
  knowledgeRefs,
  attachments,
  streamingMessageId,
  onFork,
  onEditResend,
  onRegenerate,
  onDelete,
  onQuote,
  onQuoteSelection,
  onSaveToMemory,
  onContinue,
  onAnswerVersionChange,
}: MessageListProps) {
  // U11: 只渲染最近 WINDOW_STEP 条, 更早的按需加载 —— 避免长会话全量
  // 重渲染(每条 Message 都可能含 ReactMarkdown/Shiki)。
  const [windowSize, setWindowSize] = useState(WINDOW_STEP);
  const firstId = messages[0]?.id;

  // right-panel R1 批次 B: 产物列表（与右侧面板共享 artifactListStore 缓存，
  // 事件驱动刷新同源）→ tool_call_id 映射，供 Message 渲染内联产物 chip。
  const { artifacts } = useArtifacts(sessionId ?? null);
  const artifactsByToolCall = useMemo(() => {
    const map: Record<string, Artifact[]> = {};
    for (const a of artifacts) {
      if (!a.tool_call_id) continue;
      (map[a.tool_call_id] ??= []).push(a);
    }
    return map;
  }, [artifacts]);

  // 切会话时重置窗口
  useEffect(() => {
    setWindowSize(WINDOW_STEP);
  }, [firstId]);

  // 对话阅读导航 A1: 消费"定位到消息"请求 —— 目标在尾窗外时临时扩窗，
  // 定位后高亮并把窗口固化为扩大后的大小。
  const rootRef = useRef<HTMLDivElement>(null);
  const { effectiveWindow, flashId } = useMessageJump({
    rootRef,
    messages,
    windowSize,
    setWindowSize,
  });

  if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted">
        <p className="text-lg mb-2">欢迎使用 Sage</p>
        <p className="text-sm">开始一段新对话吧</p>
      </div>
    );
  }

  const hiddenCount = Math.max(0, messages.length - effectiveWindow);
  const visible = messages.slice(messages.length - effectiveWindow);
  const lastId = messages[messages.length - 1].id;

  return (
    <>
      {/* 第二轮 B4: 会话内查找栏（Ctrl/Cmd+F），在列表根节点之外，自身文字不参与匹配 */}
      <ChatFindBar messages={messages} />
      <div ref={rootRef} className="p-4 space-y-[var(--density-msg-gap)]">
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
          <div
            key={message.id}
            data-message-id={message.id}
            data-jump-flash={flashId === message.id ? 'true' : undefined}
            className={flashId === message.id ? JUMP_FLASH_CLASS : undefined}
          >
            {message.subtype === 'topic_separator' ? (
              <TopicSeparator content={message.content} />
            ) : (
              <Message
                message={message}
                knowledgeRefs={knowledgeRefs?.[message.id]}
                attachments={attachments?.[message.id]}
                isStreaming={message.id === streamingMessageId}
                onFork={onFork}
                onEditResend={onEditResend}
                onRegenerate={onRegenerate}
                onDelete={onDelete}
                onQuote={onQuote}
                onSaveToMemory={onSaveToMemory}
                artifactsByToolCall={artifactsByToolCall}
                onContinue={message.id === lastId && !streamingMessageId ? onContinue : undefined}
                onAnswerVersionChange={
                  message.id === lastId && !streamingMessageId ? onAnswerVersionChange : undefined
                }
              />
            )}
          </div>
        ))}
      </div>
      <BtwOverlay />
      {onQuoteSelection && <SelectionQuoteButton rootRef={rootRef} onQuote={onQuoteSelection} />}
    </>
  );
}
