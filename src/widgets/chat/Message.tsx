import {
  Copy,
  ThumbsUp,
  ThumbsDown,
  BookOpen,
  Check,
  Wrench,
  Brain,
  ChevronDown,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import remarkGfm from 'remark-gfm';

import type { Message as MessageType, ToolCall } from '../../shared/lib/store';

interface MessageProps {
  message: MessageType;
  onFeedback?: (messageId: string, feedback: 'up' | 'down') => void;
  knowledgeRefs?: { id: string; title: string }[];
  attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
  // 流式状态（用于 ThinkingPanel 三模式判断）
  isStreaming?: boolean;
  reasoningComplete?: boolean;
}

/** Code block renderer with syntax highlighting + copy button */
function CodeBlock({ language, children }: { language?: string; children: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(children);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Inline code fallback
  if (!language && !children.includes('\n')) {
    return <code className="px-1.5 py-0.5 bg-bg-subtle rounded text-xs font-mono">{children}</code>;
  }

  return (
    <div className="relative group">
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#282c34] rounded-t-md text-xs text-gray-300">
        <span className="font-mono">{language || 'text'}</span>
        <button
          onClick={handleCopy}
          className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 px-2 py-0.5 rounded hover:bg-white/10 text-gray-300 hover:text-white"
          title="复制代码"
        >
          {copied ? (
            <Check className="w-3.5 h-3.5 text-green-400" />
          ) : (
            <Copy className="w-3.5 h-3.5" />
          )}
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <SyntaxHighlighter
        language={language || 'text'}
        style={oneDark}
        customStyle={{
          margin: 0,
          borderTopLeftRadius: 0,
          borderTopRightRadius: 0,
          fontSize: '12px',
          lineHeight: '1.5',
        }}
        showLineNumbers
        wrapLongLines
      >
        {children.replace(/\n$/, '')}
      </SyntaxHighlighter>
    </div>
  );
}

/** ThinkingPanel - LLM 思考过程展示面板（三模式）
 * - 流式中 (isStreaming + !reasoningComplete): 展开 + 光标闪烁 + "思考中…" 脉冲标题
 * - 刚完成 (isStreaming + reasoningComplete): 光标消失 → 1.5s 后自动折叠
 * - 历史消息 (!isStreaming): 默认折叠（向后兼容）
 */
function ThinkingPanel({
  reasoning,
  isStreaming = false,
  reasoningComplete = false,
}: {
  reasoning: string;
  isStreaming?: boolean;
  reasoningComplete?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const userTouchedRef = useRef(false);

  // 流式模式: 自动展开；历史模式: 默认折叠
  useEffect(() => {
    if (isStreaming) {
      setIsExpanded(true);
    } else if (!userTouchedRef.current) {
      setIsExpanded(false);
    }
  }, [isStreaming]);

  // 完成后 1.5s 自动折叠（除非用户手动操作过）
  useEffect(() => {
    if (isStreaming && reasoningComplete && !userTouchedRef.current) {
      const timer = setTimeout(() => setIsExpanded(false), 1500);
      return () => clearTimeout(timer);
    }
  }, [isStreaming, reasoningComplete]);

  const handleToggle = () => {
    userTouchedRef.current = true;
    setIsExpanded((v) => !v);
  };

  const showCursor = isStreaming && !reasoningComplete;
  const headerText = showCursor ? '思考中…' : `思考过程 (${reasoning.length} 字)`;

  return (
    <div className="mb-2 border border-role-purple/20 border-l-[3px] border-l-role-purple rounded-radius-sm overflow-hidden bg-role-purple/5">
      <button
        onClick={handleToggle}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-role-purple/10 transition-colors text-left"
        aria-expanded={isExpanded}
      >
        <Brain className="w-4 h-4 text-role-purple" />
        <span
          className={`text-xs font-medium text-role-purple-text ${showCursor ? 'animate-pulse' : ''}`}
        >
          {headerText}
        </span>
        <ChevronDown
          className={`w-4 h-4 ml-auto text-role-purple transition-transform ${isExpanded ? 'rotate-180' : ''}`}
        />
      </button>
      {isExpanded && (
        <div className="px-3 py-2 border-t border-role-purple/20 text-xs text-text-secondary leading-relaxed max-h-60 overflow-y-auto whitespace-pre-wrap font-mono">
          {reasoning}
          {showCursor && <span className="thinking-cursor">▌</span>}
        </div>
      )}
    </div>
  );
}

export function Message({
  message,
  onFeedback,
  knowledgeRefs,
  attachments,
  isStreaming = false,
  reasoningComplete = false,
}: MessageProps) {
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  const isError = message.content?.startsWith('[错误') ?? false;
  const toolCalls: ToolCall[] = message.tool_calls ?? [];

  const copyToClipboard = () => {
    navigator.clipboard.writeText(message.content);
  };

  return (
    <div className={`flex gap-3 mb-5 w-full ${isUser ? 'flex-row-reverse' : ''}`}>
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
          <ThinkingPanel
            reasoning={message.reasoning_content}
            isStreaming={isStreaming}
            reasoningComplete={reasoningComplete}
          />
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

        {/* 工具调用展示（ReAct 模式） */}
        {toolCalls.length > 0 && (
          <div className="mt-2 flex flex-col gap-1.5">
            {toolCalls.map((tc, idx) => {
              const hasImage = tc.metadata?.imageData;
              return (
                <div
                  key={`${tc.name}-${idx}`}
                  className="flex flex-col gap-1.5 rounded border border-border bg-bg-subtle text-[12px]"
                >
                  {/* Tool call header */}
                  <div className="flex flex-wrap items-center gap-1.5 px-2 py-1.5 font-mono">
                    <Wrench className="w-3 h-3 text-primary shrink-0" />
                    <span className="font-semibold text-primary">{tc.name}</span>
                    {!hasImage && (
                      <>
                        <span className="text-muted">(</span>
                        <span className="text-text-secondary break-all">
                          {JSON.stringify(tc.args)}
                        </span>
                        <span className="text-muted">)</span>
                      </>
                    )}
                    {tc.result !== undefined && tc.result !== '' && !hasImage && (
                      <>
                        <span className="text-muted">→</span>
                        <span className="text-text-primary break-all">{tc.result}</span>
                      </>
                    )}
                  </div>
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
        {onFeedback && (
          <div className="flex items-center gap-1 mt-2 pt-2 border-t border-border">
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
          </div>
        )}
      </div>
    </div>
  );
}
