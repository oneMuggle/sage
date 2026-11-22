/**
 * M1: 任务 Transcript 视图 —— 子代理消息级过程记录。
 *
 * 与「过程」（实时事件/时间线）互补：这里展示 goal / 思考 / 正文 /
 * 工具调用与结果全文，运行中由 {@link useTaskTranscript} 增量轮询。
 * 思考行遵守全局/会话思考展示档位（detail 展开、trace 折叠、result 折叠
 * 为摘要条）。
 */

import { useEffect, useMemo, useRef } from 'react';

import type { DisplayMode } from '../../../features/chat/displayMode/types';
import { useDisplayMode } from '../../../features/chat/displayMode/useDisplayMode';
import type { TaskTranscriptMessage } from '../../../shared/api/orchEvents';

import { useTaskTranscript } from './useTaskTranscript';

interface TaskTranscriptPanelProps {
  runId: string;
  taskId: string;
  /** 任务仍在运行（开启增量轮询）。 */
  live: boolean;
  sessionId?: string | null;
}

function summarizeArgs(args: unknown): string {
  if (args === null || args === undefined) return '';
  try {
    const text = typeof args === 'string' ? args : JSON.stringify(args);
    return text.length > 120 ? `${text.slice(0, 120)}…` : text;
  } catch {
    return String(args);
  }
}

function formatDuration(durationMs: number | null): string {
  if (durationMs === null || durationMs === undefined) return '';
  if (durationMs < 1000) return `${durationMs}ms`;
  return `${(durationMs / 1000).toFixed(1)}s`;
}

function ReasoningBlock({ text, mode }: { text: string; mode: DisplayMode }) {
  const open = mode === 'detail';
  const label =
    mode === 'result'
      ? `已隐藏思考过程（${text.length} 字，点击展开）`
      : `思考（${text.length} 字）`;
  return (
    <details
      open={open}
      data-testid="task-transcript-reasoning"
      className="rounded border border-border/60 bg-bg-hover/40 px-2 py-1"
    >
      <summary className="cursor-pointer text-ui-2xs text-text-muted select-none">{label}</summary>
      <pre className="mt-1 text-xs text-text-secondary whitespace-pre-wrap break-words">{text}</pre>
    </details>
  );
}

function ToolCallBlock({ message }: { message: TaskTranscriptMessage }) {
  const args = summarizeArgs(message.tool_args);
  const fullArgs = useMemo(() => {
    if (message.tool_args === null || message.tool_args === undefined) return '';
    try {
      return typeof message.tool_args === 'string'
        ? message.tool_args
        : JSON.stringify(message.tool_args, null, 2);
    } catch {
      return String(message.tool_args);
    }
  }, [message.tool_args]);

  return (
    <div
      data-testid="task-transcript-tool-call"
      className="rounded border border-border/60 bg-surface px-2 py-1"
    >
      <div className="text-xs text-primary break-words">
        🔧 {message.tool_name ?? 'tool'}
        {args && <span className="text-text-secondary"> {args}</span>}
      </div>
      {fullArgs && fullArgs !== args && (
        <details className="mt-0.5">
          <summary className="cursor-pointer text-ui-2xs text-text-muted select-none">
            完整参数
          </summary>
          <pre className="mt-1 text-ui-2xs text-text-secondary whitespace-pre-wrap break-words">
            {fullArgs}
          </pre>
        </details>
      )}
    </div>
  );
}

function ToolResultBlock({ message }: { message: TaskTranscriptMessage }) {
  const duration = formatDuration(message.duration_ms);
  return (
    <details
      open={message.is_error}
      data-testid="task-transcript-tool-result"
      className={`rounded border px-2 py-1 ${
        message.is_error ? 'border-error/40 bg-error/5' : 'border-border/60 bg-bg-hover/40'
      }`}
    >
      <summary className="cursor-pointer text-ui-2xs select-none text-text-muted">
        👀 {message.tool_call_id ?? 'tool'} 返回{duration ? ` · ${duration}` : ''}
        {message.is_error ? '（错误）' : ''}
      </summary>
      <pre
        className={`mt-1 text-xs whitespace-pre-wrap break-words ${
          message.is_error ? 'text-error' : 'text-text-secondary'
        }`}
      >
        {message.tool_result ?? ''}
      </pre>
    </details>
  );
}

function MessageRow({ message, mode }: { message: TaskTranscriptMessage; mode: DisplayMode }) {
  switch (message.message_type) {
    case 'goal':
      return (
        <div data-testid="task-transcript-goal" className="rounded bg-primary/5 px-2 py-1">
          <div className="text-ui-2xs text-text-muted mb-0.5">任务目标</div>
          <div className="text-xs text-text whitespace-pre-wrap break-words">
            {message.content ?? ''}
          </div>
        </div>
      );
    case 'reasoning':
      return message.reasoning ? <ReasoningBlock text={message.reasoning} mode={mode} /> : null;
    case 'assistant':
      return (
        <div
          data-testid="task-transcript-assistant"
          className="text-xs text-text whitespace-pre-wrap break-words"
        >
          {message.content ?? ''}
        </div>
      );
    case 'tool_call':
      return <ToolCallBlock message={message} />;
    case 'tool_result':
      return <ToolResultBlock message={message} />;
    case 'error':
      return (
        <pre
          data-testid="task-transcript-error-row"
          className="rounded bg-error/5 px-2 py-1 text-xs text-error whitespace-pre-wrap break-words"
        >
          {message.content ?? ''}
        </pre>
      );
    default:
      return null;
  }
}

export function TaskTranscriptPanel({ runId, taskId, live, sessionId }: TaskTranscriptPanelProps) {
  const { mode } = useDisplayMode(sessionId ?? null, null);
  const { messages, loading, error, refresh } = useTaskTranscript({
    runId,
    taskId,
    enabled: true,
    live,
  });
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // 运行中在靠近底部时自动跟随新消息（用户上翻时不打扰）。
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !live) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [messages, live]);

  return (
    <div data-testid="task-transcript-panel" className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-ui-2xs text-text-muted">
          对话记录（{messages.length} 条{live ? ' · 实时更新' : ''}）
        </span>
        <button
          type="button"
          onClick={refresh}
          data-testid="task-transcript-refresh"
          className="text-ui-2xs text-text-secondary hover:text-text"
        >
          刷新
        </button>
      </div>
      {error && (
        <div data-testid="task-transcript-fetch-error" className="text-ui-2xs text-error">
          加载失败：{error}
        </div>
      )}
      {messages.length === 0 ? (
        <div data-testid="task-transcript-empty" className="text-xs text-text-muted">
          {loading ? '加载中…' : '暂无过程记录（任务可能尚未开始）'}
        </div>
      ) : (
        <div ref={scrollRef} className="max-h-[60vh] overflow-y-auto pr-1">
          <ul className="space-y-2">
            {messages.map((message) => (
              <li key={message.seq}>
                <MessageRow message={message} mode={mode} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
