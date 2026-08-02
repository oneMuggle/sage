import {
  Copy,
  ThumbsUp,
  ThumbsDown,
  BookOpen,
  Wrench,
  Brain,
  ChevronDown,
  GitBranch,
  Eye,
  EyeOff,
} from 'lucide-react';
import { memo } from 'react';
import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { humanizeToolCall } from '../../shared/lib/humanize';
import { useI18n } from '../../shared/lib/i18n';
import type { Message as MessageType, ToolCall } from '../../shared/lib/store';

import { ShikiCodeBlock } from './ShikiCodeBlock';

interface MessageProps {
  message: MessageType;
  onFeedback?: (messageId: string, feedback: 'up' | 'down') => void;
  knowledgeRefs?: { id: string; title: string }[];
  attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
  /** P1: 该消息是否正在流式输出 (用于 ThinkingPanel 自动展开) */
  isStreaming?: boolean;
  /** M4: 从此消息分叉新会话（非破坏性，无需确认） */
  onFork?: (messageId: string) => void;
}

/** Code block renderer — delegates to ShikiCodeBlock for syntax highlighting */
function CodeBlock({ language, children }: { language?: string; children: string }) {
  // Inline code fallback
  if (!language && !children.includes('\n')) {
    return <code className="px-1.5 py-0.5 bg-bg-subtle rounded text-xs font-mono">{children}</code>;
  }

  return <ShikiCodeBlock language={language}>{children}</ShikiCodeBlock>;
}

/** ThinkingPanel - 可折叠的 LLM 思考过程展示面板
 *  P1: 流式 reasoning 时自动展开 (isStreaming=true)
 */
function ThinkingPanel({ reasoning, isStreaming }: { reasoning: string; isStreaming?: boolean }) {
  const [isExpanded, setIsExpanded] = useState(false);

  // P1 fix: 当 isStreaming 变为 true 时自动展开 (useState 只读初始值,需 useEffect 同步)
  useEffect(() => {
    if (isStreaming) setIsExpanded(true);
  }, [isStreaming]);

  return (
    <div className="mb-2 border border-border/50 rounded-radius-sm overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-bg-subtle hover:bg-bg-hover transition-colors text-left"
        aria-expanded={isExpanded}
      >
        <Brain className="w-4 h-4 text-primary" />
        <span className="text-xs font-medium text-text-secondary">
          思考过程 ({reasoning.length} 字)
        </span>
        <ChevronDown
          className={`w-4 h-4 ml-auto transition-transform ${isExpanded ? 'rotate-180' : ''}`}
        />
      </button>
      {isExpanded && (
        <div className="px-3 py-2 bg-bg-subtle/50 border-t border-border/50 text-xs text-text-secondary leading-relaxed max-h-60 overflow-y-auto whitespace-pre-wrap">
          {reasoning}
        </div>
      )}
    </div>
  );
}

/** U8: humanized tool call title — "Write **src/App.tsx**" / "Run `pytest`"
 *  代替原来的 write_file({"path":...}) 技术化展示。
 *  - 无 scope 的动作（文件操作）：对象加粗
 *  - 有 scope 的动作（shell / 网络）：对象用 code chip + scope 标签
 *    （local = 本机执行，external = 请求会离开本机）
 */
function ToolCallTitle({ name, args }: { name: string; args: Record<string, unknown> }) {
  const human = humanizeToolCall(name, args);
  return (
    <>
      <span className="text-text-secondary">
        {human.verb}
        {human.object !== '' && (
          <>
            {' '}
            {human.scope ? (
              <code className="rounded bg-bg-hover px-1 py-0.5 font-mono text-[11px] text-text break-all">
                {human.object}
              </code>
            ) : (
              <strong className="font-semibold text-text break-all">{human.object}</strong>
            )}
          </>
        )}
      </span>
      {human.scope && (
        <span
          className={`rounded px-1 py-0.5 text-[10px] leading-none ${
            human.scope === 'external' ? 'bg-warning/10 text-warning' : 'bg-bg-hover text-muted'
          }`}
        >
          {human.scope}
        </span>
      )}
    </>
  );
}

/** 工具调用结果可折叠面板 — 大文件内容默认收起，避免刷屏
 *  阈值：超过 300 字符时自动折叠，用户可手动展开查看
 */
function ToolCallResult({ result }: { result: string }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const isLarge = result.length > 300;

  if (!isLarge) {
    return <span className="text-text-primary break-all">{result}</span>;
  }

  return (
    <div className="w-full">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-1 text-[11px] text-primary hover:text-primary/80 transition-colors"
      >
        {isExpanded ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
        <span>{isExpanded ? '收起' : `展开 (${result.length} 字符)`}</span>
      </button>
      {isExpanded && (
        <pre className="mt-1 p-2 bg-bg-subtle border border-border rounded-radius-sm text-[11px] text-text-secondary overflow-x-auto max-h-80 overflow-y-auto whitespace-pre-wrap break-all font-mono">
          {result}
        </pre>
      )}
    </div>
  );
}

// MEDIUM-5: React.memo 包装,自定义比较函数避免 ReactMarkdown 重解析
// - 仅当 message 引用变、isStreaming 变化、knowledgeRefs/attachments 引用变时才重渲染
// - 在每个 content_delta 触发 N 条历史消息重渲染的场景下,这是关键优化
function MessageComponent({
  message,
  onFeedback,
  knowledgeRefs,
  attachments,
  isStreaming,
  onFork,
}: MessageProps) {
  const { t } = useI18n();
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  const isError = message.content?.startsWith('[错误') ?? false;
  const toolCalls: ToolCall[] = message.tool_calls ?? [];
  // M4: 只有 user/assistant 消息可分叉（system/tool 行没有分叉语义）
  const canFork = Boolean(onFork) && (isUser || isAssistant);

  const copyToClipboard = () => {
    navigator.clipboard.writeText(message.content);
  };

  return (
    <div
      className={`flex gap-3 mb-5 w-full animate-message-enter ${isUser ? 'flex-row-reverse' : ''}`}
    >
      {/* 头像 */}
      <div
        className={`w-7 h-7 rounded-radius-sm flex-shrink-0 flex items-center justify-center text-xs font-semibold ${
          isAssistant ? 'bg-primary/10 text-primary' : 'bg-bg text-muted border border-border'
        }`}
      >
        {isAssistant ? 'S' : 'U'}
      </div>

      <div className={`flex-1 ${isUser ? 'flex flex-col items-end' : ''}`}>
        {/* ThinkingPanel - LLM 思考过程展示（仅 assistant 消息且有 reasoning_content 时） */}
        {isAssistant && message.reasoning_content && (
          <ThinkingPanel reasoning={message.reasoning_content} isStreaming={isStreaming} />
        )}

        {/* Knowledge references */}
        {knowledgeRefs && knowledgeRefs.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-1">
            {knowledgeRefs.map((ref) => (
              <span
                key={ref.id}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] bg-primary/10 text-primary"
              >
                <BookOpen className="w-2.5 h-2.5" />
                {ref.title}
              </span>
            ))}
          </div>
        )}

        {/* File attachments */}
        {attachments && attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {attachments.map((file, idx) => (
              <span
                key={idx}
                className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs border ${
                  isUser
                    ? 'bg-text-inverse/15 border-text-inverse/20 text-text-inverse'
                    : 'bg-bg-subtle border-border text-text-secondary'
                }`}
              >
                {file.type.startsWith('image/') && file.dataUrl ? (
                  <img src={file.dataUrl} alt="" className="w-4 h-4 rounded object-cover" />
                ) : null}
                <span className="truncate max-w-24">{file.name}</span>
              </span>
            ))}
          </div>
        )}

        {/* 工具调用展示（ReAct 模式）— 在消息内容之前，因为工具调用先于最终回答 */}
        {toolCalls.length > 0 && (
          <div className="mb-2 flex flex-col gap-1.5">
            {toolCalls.map((tc, idx) => {
              const hasImage = tc.metadata?.imageData;
              return (
                <div
                  key={`${tc.name}-${idx}`}
                  className="flex flex-col gap-1.5 rounded border border-border bg-bg-subtle text-[12px]"
                >
                  {/* Tool call header — U8: humanized title + 弱化的原始工具名(调试用) */}
                  <div className="flex flex-wrap items-center gap-1.5 px-2 py-1.5">
                    <Wrench className="w-3 h-3 text-primary shrink-0" />
                    <ToolCallTitle name={tc.name} args={tc.args} />
                    <span className="font-mono text-[10px] text-muted">{tc.name}</span>
                  </div>
                  {/* Tool result — 大文件内容可折叠 */}
                  {tc.result !== undefined && tc.result !== '' && !hasImage && (
                    <div className="px-2 pb-1.5">
                      <ToolCallResult result={tc.result} />
                    </div>
                  )}
                  {/* Inline image preview for diagram tools */}
                  {hasImage && (
                    <div className="px-2 pb-2">
                      <img
                        src={tc.metadata!.imageData}
                        alt={`Diagram from ${tc.name}`}
                        className="max-w-full rounded border border-border"
                        style={{ maxHeight: '400px', backgroundColor: '#ffffff' }}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* 消息气泡 */}
        <div
          data-error={isError ? 'true' : undefined}
          className={`max-w-2xl px-3.5 py-2.5 rounded-radius-sm text-[13px] leading-relaxed ${
            isUser
              ? 'bg-primary text-text-inverse'
              : isError
                ? 'bg-red-50 border border-red-300 text-red-900'
                : 'bg-surface border border-border'
          }`}
        >
          {/* Message content with Markdown */}
          {isAssistant ? (
            <div className="max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ className, children }) {
                    const match = /language-(\w+)/.exec(className || '');
                    const lang = match ? match[1] : undefined;
                    const content = String(children).replace(/\n$/, '');
                    // Inline code detection: no language class and short content
                    const isInlineCode = !className && !content.includes('\n');
                    if (isInlineCode) {
                      return (
                        <code className="px-1.5 py-0.5 bg-bg-subtle rounded text-xs font-mono">
                          {content}
                        </code>
                      );
                    }
                    if (!lang) {
                      return (
                        <code className="px-1.5 py-0.5 bg-bg-subtle rounded text-xs font-mono">
                          {content}
                        </code>
                      );
                    }
                    return <CodeBlock language={lang}>{content}</CodeBlock>;
                  },
                  pre({ children }) {
                    return <>{children}</>;
                  },
                  table({ children }) {
                    return (
                      <div className="overflow-x-auto my-3">
                        <table className="min-w-full text-xs border-collapse border border-border">
                          {children}
                        </table>
                      </div>
                    );
                  },
                  th({ children }) {
                    return (
                      <th className="border border-border px-3 py-1.5 bg-bg-subtle font-semibold text-left">
                        {children}
                      </th>
                    );
                  },
                  td({ children }) {
                    return <td className="border border-border px-3 py-1.5">{children}</td>;
                  },
                  p({ children }) {
                    return <p className="mb-2 last:mb-0">{children}</p>;
                  },
                  ul({ children }) {
                    return <ul className="list-disc list-outside ml-5 mb-2">{children}</ul>;
                  },
                  ol({ children }) {
                    return <ol className="list-decimal list-outside ml-5 mb-2">{children}</ol>;
                  },
                  li({ children }) {
                    return <li className="mb-0.5">{children}</li>;
                  },
                  a({ href, children }) {
                    return (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary hover:underline"
                      >
                        {children}
                      </a>
                    );
                  },
                  blockquote({ children }) {
                    return (
                      <blockquote className="border-l-4 border-border pl-3 py-1 my-2 text-muted italic">
                        {children}
                      </blockquote>
                    );
                  },
                  h1({ children }) {
                    return <h1 className="text-lg font-bold mt-4 mb-2">{children}</h1>;
                  },
                  h2({ children }) {
                    return <h2 className="text-base font-bold mt-3 mb-2">{children}</h2>;
                  },
                  h3({ children }) {
                    return <h3 className="text-sm font-bold mt-2 mb-1">{children}</h3>;
                  },
                }}
              >
                {message.content.replace(/<img\s+[^>]*src=["']data:[^"']*["'][^>]*\/?>/gi, '')}
              </ReactMarkdown>
            </div>
          ) : (
            <p className="whitespace-pre-wrap">{message.content}</p>
          )}
        </div>

        {/* 底部信息 */}
        <div className="flex items-center gap-2 mt-1 text-[11px] text-muted">
          {message.memory_applied && message.memory_applied > 0 && (
            <span className="text-primary">{message.memory_applied} 条记忆已应用</span>
          )}
          <span>
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        </div>

        {/* Action buttons */}
        {(onFeedback || canFork) && (
          <div className="flex items-center gap-1 mt-2 pt-2 border-t border-border">
            {onFeedback && (
              <>
                <button
                  onClick={copyToClipboard}
                  className="p-1 rounded hover:bg-bg-hover"
                  title="复制"
                >
                  <Copy className="w-4 h-4" />
                </button>
                <button
                  onClick={() => onFeedback(message.id, 'up')}
                  className="p-1 rounded hover:bg-bg-hover"
                  title="有帮助"
                >
                  <ThumbsUp className="w-4 h-4" />
                </button>
                <button
                  onClick={() => onFeedback(message.id, 'down')}
                  className="p-1 rounded hover:bg-bg-hover"
                  title="没帮助"
                >
                  <ThumbsDown className="w-4 h-4" />
                </button>
              </>
            )}
            {canFork && (
              <button
                onClick={() => onFork?.(message.id)}
                className="p-1 rounded hover:bg-bg-hover"
                title={t('chat.fork_from_here')}
                data-testid="fork-message"
              >
                <GitBranch className="w-4 h-4" />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export const Message = memo(MessageComponent, (prev, next) => {
  // 自定义比较:仅当 message 对象引用变化 / isStreaming 变化 / 关联数据变化时重渲染
  // ReactMarkdown 和 Prism SyntaxHighlighter 很重,跳过能显著降低 token 级重渲染成本
  return (
    prev.message === next.message &&
    prev.isStreaming === next.isStreaming &&
    prev.onFeedback === next.onFeedback &&
    prev.knowledgeRefs === next.knowledgeRefs &&
    prev.attachments === next.attachments &&
    prev.onFork === next.onFork
  );
});
