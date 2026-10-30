import { ChevronRight, MessageSquare, Wrench } from 'lucide-react';
import { memo, useEffect, useRef, useState } from 'react';

import type { Artifact } from '../../features/artifacts/artifactApi';
import type { BlockedAction, Message } from '../../shared/lib/store';

import { Message as MessageComponent } from './Message';
import { getTurnSummary, getTurnToolCallCount, isTurnCollapsible } from './turnGrouping';

interface TurnGroupProps {
  messages: Message[];
  turnId: string;
  streamingMessageId?: string | null;
  /** 对话阅读导航 A1: 当前高亮定位的消息 ID（透传自 MessageList） */
  flashId?: string | null;
  knowledgeRefs?: Record<string, { id: string; title: string }[]>;
  attachments?: Record<string, { name: string; size: number; type: string; dataUrl?: string }[]>;
  artifactsByToolCall?: Record<string, Artifact[]>;
  /** R96: 非 running 会话切换时回合默认展开 */
  defaultExpanded?: boolean;
  onFork?: (messageId: string) => void;
  onRewind?: (messageId: string) => void;
  onEditResend?: (messageId: string) => void;
  onRegenerate?: (messageId: string) => void;
  onDelete?: (messageId: string) => void;
  onQuote?: (message: Message) => void;
  /** 对话阅读导航 A4: 划词引用（消息右键菜单「引用选区」） */
  onQuoteSelection?: (text: string) => void;
  onSaveToMemory?: (message: Message) => void;
  /** P0-6: 打开记忆浏览器并定位到该条记忆 */
  onOpenMemory?: (memoryId: string) => void;
  onBlockedAction?: (action: BlockedAction) => void;
  onContinue?: () => void;
  onAnswerVersionChange?: () => void;
}

function TurnGroupComponent({
  messages,
  turnId,
  streamingMessageId,
  flashId,
  knowledgeRefs,
  attachments,
  artifactsByToolCall,
  onFork,
  onRewind,
  onEditResend,
  onRegenerate,
  onDelete,
  onQuote,
  onQuoteSelection,
  onSaveToMemory,
  onOpenMemory,
  onBlockedAction,
  onContinue,
  onAnswerVersionChange,
  defaultExpanded,
}: TurnGroupProps) {
  const collapsible = isTurnCollapsible(messages);
  const [expanded, setExpanded] = useState(defaultExpanded ?? false);

  // Issue 2: 会话从 running → completed/failed 时，defaultExpanded 从 false 变为 true，
  // 但 useState 只捕获初始值，不会自动同步。用 useRef 追踪前值，只在"false → true 翻转"
  // 时同步一次。expanded 不入依赖，避免用户手动折叠后被立即撤销。
  const prevDefaultExpanded = useRef(defaultExpanded);
  useEffect(() => {
    const wasFalse = !prevDefaultExpanded.current;
    prevDefaultExpanded.current = defaultExpanded;
    if (wasFalse && defaultExpanded) setExpanded(true);
  }, [defaultExpanded]);

  // 流式消息始终展开
  const isStreaming = messages.some((m) => m.id === streamingMessageId);
  const showCollapsed = collapsible && !expanded && !isStreaming;

  const toolCallCount = getTurnToolCallCount(messages);
  const summary = getTurnSummary(messages);
  const lastMessage = messages[messages.length - 1];
  const lastAssistantIdx = [...messages].findLastIndex((m) => m.role === 'assistant');

  if (showCollapsed) {
    return (
      <div
        className="rounded-radius-md border border-border bg-ui-card overflow-hidden"
        data-turn-id={turnId}
      >
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="w-full flex items-start gap-3 p-3 text-left hover:bg-bg-hover transition-colors"
          aria-label="展开对话轮次"
        >
          <ChevronRight className="w-4 h-4 text-text-muted mt-0.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            {summary && (
              <p className="text-ui-base text-text leading-relaxed line-clamp-3">{summary}</p>
            )}
            <div className="flex items-center gap-3 mt-1.5 text-ui-sm text-text-muted">
              {toolCallCount > 0 && (
                <span className="flex items-center gap-1">
                  <Wrench className="w-3 h-3" />
                  {toolCallCount} 个工具调用
                </span>
              )}
              <span className="flex items-center gap-1">
                <MessageSquare className="w-3 h-3" />
                {messages.filter((m) => m.role === 'assistant').length} 条回复
              </span>
              {lastMessage && (
                <span className="ml-auto text-ui-xs">{formatTurnTime(lastMessage.created_at)}</span>
              )}
            </div>
          </div>
        </button>
      </div>
    );
  }

  return (
    <div data-turn-id={turnId} className="space-y-0">
      {collapsible && !isStreaming && expanded && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="flex items-center gap-1.5 px-2 py-1 text-ui-sm text-text-muted hover:text-text transition-colors mb-1 rounded-radius-sm hover:bg-bg-hover"
          aria-label="折叠对话轮次"
        >
          <ChevronRight className="w-3 h-3 rotate-90" />
          收起 · {messages.filter((m) => m.role === 'assistant').length} 条回复
          {toolCallCount > 0 && ` · ${toolCallCount} 个工具调用`}
        </button>
      )}
      {messages.map((msg, idx) => (
        <div
          key={msg.id}
          data-message-id={msg.id}
          data-jump-flash={flashId === msg.id ? 'true' : undefined}
          className={flashId === msg.id ? TURN_JUMP_FLASH_CLASS : undefined}
        >
          <MessageComponent
            message={msg}
            knowledgeRefs={knowledgeRefs?.[msg.id]}
            attachments={attachments?.[msg.id]}
            isStreaming={msg.id === streamingMessageId}
            onFork={onFork}
            onRewind={onRewind}
            onEditResend={onEditResend}
            onRegenerate={onRegenerate}
            onDelete={onDelete}
            onQuote={onQuote}
            onQuoteSelection={onQuoteSelection}
            onSaveToMemory={onSaveToMemory}
            onOpenMemory={onOpenMemory}
            artifactsByToolCall={artifactsByToolCall}
            onBlockedAction={onBlockedAction}
            onContinue={idx === lastAssistantIdx ? onContinue : undefined}
            onAnswerVersionChange={idx === lastAssistantIdx ? onAnswerVersionChange : undefined}
          />
        </div>
      ))}
    </div>
  );
}

/** 对话阅读导航 A1: 定位命中后的短暂高亮（与 MessageList 中 JUMP_FLASH_CLASS 同步） */
const TURN_JUMP_FLASH_CLASS =
  'rounded-radius-sm ring-2 ring-primary/50 bg-primary/5 transition-shadow';

function formatTurnTime(ts: number): string {
  if (!ts) return '';
  const date = new Date(ts * 1000);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return '刚刚';
  if (diffMins < 60) return `${diffMins} 分钟前`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours} 小时前`;
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

export const TurnGroup = memo(TurnGroupComponent);

export interface TurnGroupAuditInput {
  turnId: string;
  messageCount: number;
  toolCallCount: number;
  isStreaming: boolean;
}

export interface TurnGroupAuditReport {
  turnId: string;
  messageCount: number;
  toolCallCount: number;
  isStreaming: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateTurnGroupAudit(input: TurnGroupAuditInput): TurnGroupAuditReport {
  const turnId = input.turnId.trim();
  const messageCount = Math.max(0, Math.trunc(input.messageCount));
  const toolCallCount = Math.max(0, Math.trunc(input.toolCallCount));
  const issueCodes: string[] = [];

  if (!turnId) {
    issueCodes.push('missing_turn_id');
  }
  if (messageCount === 0) {
    issueCodes.push('empty_turn_group');
  }

  return {
    turnId,
    messageCount,
    toolCallCount,
    isStreaming: Boolean(input.isStreaming),
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportTurnGroupAuditJson(input: TurnGroupAuditInput): string {
  return JSON.stringify(evaluateTurnGroupAudit(input));
}
