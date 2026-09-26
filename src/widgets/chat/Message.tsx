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
  Pencil,
  RefreshCw,
  Check,
  Quote,
  FileText,
  Zap,
} from 'lucide-react';
import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import type { Artifact } from '../../features/artifacts/artifactApi';
import { MediaAttachment } from '../../features/chat/MediaAttachment';
import { useRightPanelStore } from '../../features/right-panel/rightPanelStore';
import { THINKING_PLACEHOLDER } from '../../features/send-message/thinkingPlaceholder';
import { humanizeToolCall } from '../../shared/lib/humanize';
import { useI18n } from '../../shared/lib/i18n';
import { hasUnclosedFence, splitStableChunks } from '../../shared/lib/markdownChunks';
import type { Message as MessageType, ToolCall } from '../../shared/lib/store';
import { TwoStepDelete } from '../sidebar/TwoStepDelete';

import { AnswerVersionSwitcher } from './AnswerVersionSwitcher';
import { CompactBanner } from './CompactBanner';
import { GenerationStatsBadge } from './GenerationStatsBadge';
import { HtmlCodeBlock } from './HtmlCodeBlock';
import { MarkdownImage } from './MarkdownImage';
import { MermaidBlock } from './MermaidBlock';
import { ReadAloudButton } from './ReadAloudButton';
import { ShikiCodeBlock } from './ShikiCodeBlock';
import { TruncationNotice } from './TruncationNotice';
import { FileChangeCards } from './changes/FileChangeCard';
import { resolveToolRenderer } from './toolRenderers';

interface MessageProps {
  message: MessageType;
  onFeedback?: (messageId: string, feedback: 'up' | 'down') => void;
  knowledgeRefs?: { id: string; title: string }[];
  attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
  /** P1: 该消息是否正在流式输出 (用于 ThinkingPanel 自动展开) */
  isStreaming?: boolean;
  /** M4: 从此消息分叉新会话（非破坏性，无需确认） */
  onFork?: (messageId: string) => void;
  /** U5': 编辑此条 user 消息并重发（分叉其前缀，原会话保留） */
  onEditResend?: (messageId: string) => void;
  /** R18-A: 重新生成此条 assistant 回答（fork 前缀 + 重发前驱 user 消息） */
  onRegenerate?: (messageId: string) => void;
  /** R17-B: 删除此条消息（两步确认，历史消息；流式中的消息不显示） */
  onDelete?: (messageId: string) => void;
  /** P0-1: 引用此条消息到输入框 */
  onQuote?: (message: MessageType) => void;
  /** P0-1: 将此条消息内容保存到长期记忆 */
  onSaveToMemory?: (message: MessageType) => void;
  /** 第二轮 B2: 截断回答的「继续生成」（MessageList 只传给会话最后一条消息） */
  onContinue?: () => void;
  /** 第二轮 C2: 回答版本切换后的回调（MessageList 只传给会话最后一条消息） */
  onAnswerVersionChange?: () => void;
  /** right-panel R1 批次 B: tool_call_id → 产物[] 映射 —— 命中的工具卡片
   * 下渲染内联产物 chip，点击直达右侧面板产物预览（对齐 Claude） */
  artifactsByToolCall?: Record<string, Artifact[]>;
}

/** Code block renderer — delegates to ShikiCodeBlock for syntax highlighting */
function CodeBlock({ language, children }: { language?: string; children: string }) {
  // Inline code fallback
  if (!language && !children.includes('\n')) {
    return (
      <code className="px-1.5 py-0.5 bg-bg-subtle rounded text-code font-mono">{children}</code>
    );
  }

  return <ShikiCodeBlock language={language}>{children}</ShikiCodeBlock>;
}

/** markdown 插件集 — 模块级稳定引用，避免每次渲染重建数组 */
const MD_REMARK_PLUGINS = [remarkGfm, remarkMath];
const MD_REHYPE_PLUGINS = [rehypeKatex];

const URL_SPLIT_RE = /(https?:\/\/[^\s<>()]+)/;

/** P3: 用户消息纯文本中的 URL 自动链接化（assistant 走 markdown 已自带链接） */
function renderTextWithLinks(text: string): ReactNode[] {
  return text.split(URL_SPLIT_RE).map((part, i) =>
    /^https?:\/\//.test(part) ? (
      <a
        key={i}
        href={part}
        target="_blank"
        rel="noopener noreferrer"
        className="underline break-all"
        onClick={(e) => e.stopPropagation()}
      >
        {part}
      </a>
    ) : (
      part
    ),
  );
}

/** 流式未闭合围栏的降级代码渲染 — 纯文本 pre，不随 delta 重复触发 Shiki/mermaid */
function PlainCodeBlock({ className, children }: { className?: string; children: unknown }) {
  const content = String(children).replace(/\n$/, '');
  if (!className && !content.includes('\n')) {
    return (
      <code className="px-1.5 py-0.5 bg-bg-subtle rounded text-code font-mono">{content}</code>
    );
  }
  return (
    <pre className="bg-[#282c34] text-gray-300 p-3 text-code font-mono leading-relaxed overflow-x-auto rounded-md my-2">
      <code>{content}</code>
    </pre>
  );
}

/** 自定义 component 映射 — 模块级单例（原先内联在 JSX 里，每次渲染重建整个映射对象） */
const markdownComponents = {
  code({ className, children }: { className?: string; children: unknown }) {
    const match = /language-(\w+)/.exec(className || '');
    const lang = match ? match[1] : undefined;
    const content = String(children).replace(/\n$/, '');
    // Inline code detection: no language class and short content
    const isInlineCode = !className && !content.includes('\n');
    if (isInlineCode || !lang) {
      return (
        <code className="px-1.5 py-0.5 bg-bg-subtle rounded text-code font-mono">{content}</code>
      );
    }
    // U7': Mermaid 图表渲染（动态加载，失败回退源码展示）
    if (lang === 'mermaid') {
      return <MermaidBlock code={content} />;
    }
    // P1: HTML 代码块支持源码/预览切换（sandbox iframe）
    if (lang === 'html') {
      return <HtmlCodeBlock code={content} />;
    }
    return <CodeBlock language={lang}>{content}</CodeBlock>;
  },
  // P1: 图片加载骨架 + 渐入 + 点击放大（Lightbox）
  img({ src, alt }: { src?: string; alt?: string }) {
    return <MarkdownImage src={src} alt={alt} />;
  },
  pre({ children }: { children?: ReactNode }) {
    return <>{children}</>;
  },
  table({ children }: { children?: ReactNode }) {
    return (
      // P2: 长表格纵向限高滚动 + 表头粘性（此前只能横向滚动，数十行的表
      // 把整条消息拉得极长）
      <div className="overflow-x-auto my-3 max-h-80 overflow-y-auto">
        <table className="min-w-full text-xs border-collapse border border-border">
          {children}
        </table>
      </div>
    );
  },
  th({ children }: { children?: ReactNode }) {
    return (
      <th className="border border-border px-3 py-1.5 bg-bg-subtle font-semibold text-left sticky top-0 z-[1]">
        {children}
      </th>
    );
  },
  td({ children }: { children?: ReactNode }) {
    return <td className="border border-border px-3 py-1.5">{children}</td>;
  },
  p({ children }: { children?: ReactNode }) {
    return <p className="mb-2 last:mb-0">{children}</p>;
  },
  ul({ children }: { children?: ReactNode }) {
    return <ul className="list-disc list-outside ml-5 mb-2">{children}</ul>;
  },
  ol({ children }: { children?: ReactNode }) {
    return <ol className="list-decimal list-outside ml-5 mb-2">{children}</ol>;
  },
  li({ children }: { children?: ReactNode }) {
    return <li className="mb-0.5">{children}</li>;
  },
  // P2: GFM 任务列表 checkbox 主题化（默认渲染无样式反馈）
  input({ type, checked, disabled }: { type?: string; checked?: boolean; disabled?: boolean }) {
    if (type === 'checkbox') {
      return (
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          className="mr-1.5 w-3.5 h-3.5 align-middle accent-primary"
        />
      );
    }
    return <input type={type} checked={checked} disabled={disabled} />;
  },
  a({ href, children }: { href?: string; children?: ReactNode }) {
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
  blockquote({ children }: { children?: ReactNode }) {
    return (
      <blockquote className="border-l-4 border-border pl-3 py-1 my-2 text-muted italic">
        {children}
      </blockquote>
    );
  },
  h1({ children }: { children?: ReactNode }) {
    return <h1 className="text-lg font-bold mt-4 mb-2">{children}</h1>;
  },
  h2({ children }: { children?: ReactNode }) {
    return <h2 className="text-base font-bold mt-3 mb-2">{children}</h2>;
  },
  h3({ children }: { children?: ReactNode }) {
    return <h3 className="text-sm font-bold mt-2 mb-1">{children}</h3>;
  },
};

/** 流式 live 尾块专用映射 — 未闭合围栏内的代码块降级纯文本 */
const liveMarkdownComponents: typeof markdownComponents = {
  ...markdownComponents,
  code: PlainCodeBlock,
};

/**
 * memo 化的 markdown 块渲染器 — P1 流式分块的关键。
 * 比较器按字符串值相等跳过重解析（slice 出的新字符串实例也能命中），
 * 已确定的稳定前缀块在每个 delta 到达时零成本跳过。
 */
const MarkdownChunk = memo(
  function MarkdownChunk({ md, plainFences }: { md: string; plainFences?: boolean }) {
    // Components 断言: 映射对象是模块级单例，handler 参数用窄化类型
    // （react-markdown 的 ExtraProps 交叉类型过宽，直接标注反而失配）
    const components = (plainFences ? liveMarkdownComponents : markdownComponents) as Components;
    return (
      <ReactMarkdown
        remarkPlugins={MD_REMARK_PLUGINS}
        rehypePlugins={MD_REHYPE_PLUGINS}
        components={components}
      >
        {md}
      </ReactMarkdown>
    );
  },
  (prev, next) => prev.md === next.md && prev.plainFences === next.plainFences,
);

/** ThinkingShimmer — 等待首 token 的 shimmer 占位（替代 "🤔 思考中…" 静态文本）。
 *  两根相位错开的扫光条，animate-shimmer 见 index.css；reduced-motion 下
 *  全局 media query 会把动画压到 0.01ms，自然退化为静态骨架。 */
function ThinkingShimmer() {
  return (
    <div className="flex items-center gap-2 py-1" data-testid="thinking-shimmer">
      <span className="h-2.5 w-44 rounded-full animate-shimmer" />
      <span
        className="h-2.5 w-24 rounded-full animate-shimmer"
        style={{ animationDelay: '-0.8s' }}
      />
    </div>
  );
}

/** ThinkingPanel - 可折叠的 LLM 思考过程展示面板
 *  P1: 流式 reasoning 时自动展开 (isStreaming=true)
 */
function ThinkingPanel({ reasoning, isStreaming }: { reasoning: string; isStreaming?: boolean }) {
  const [isExpanded, setIsExpanded] = useState(false);
  // P21: 流式期间自动滚动到底部，显示最新思考内容
  const contentRef = useRef<HTMLDivElement | null>(null);

  // P1 fix: 当 isStreaming 变为 true 时自动展开 (useState 只读初始值,需 useEffect 同步)
  useEffect(() => {
    if (isStreaming) setIsExpanded(true);
  }, [isStreaming]);

  // 流式期间 reasoning 增长时自动滚动到底部
  useEffect(() => {
    if (isStreaming && contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [reasoning]);

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
        <div
          ref={contentRef}
          className="px-3 py-2 bg-bg-subtle/50 border-t border-border/50 text-xs text-text-secondary leading-relaxed max-h-60 overflow-y-auto whitespace-pre-wrap"
        >
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

/** right-panel R5: 会改工作区文件的工具 —— 命中即渲染内联 diff 卡片 */
const FILE_WRITE_TOOLS = new Set(['write_file', 'edit_file', 'apply_patch']);

/**
 * 从工具调用参数提取目标文件路径（相对工作区根,与 git 接口口径一致）。
 * apply_patch 一次动多个文件 → 返回去重后的路径列表,逐文件各渲染一张卡。
 * 参数畸形（LLM 输出不可信）时返回空数组,不渲染卡片。
 */
function fileChangePaths(tc: ToolCall): string[] {
  if (!FILE_WRITE_TOOLS.has(tc.name)) return [];
  const args = (tc.args && typeof tc.args === 'object' ? tc.args : {}) as Record<string, unknown>;
  if (tc.name === 'apply_patch') {
    if (!Array.isArray(args.patches)) return [];
    const paths: string[] = [];
    for (const patch of args.patches) {
      const filePath = (patch as Record<string, unknown> | null)?.file_path;
      if (typeof filePath === 'string' && filePath.trim() && !paths.includes(filePath.trim())) {
        paths.push(filePath.trim());
      }
    }
    return paths;
  }
  const raw = tc.name === 'edit_file' ? args.file_path : args.path;
  return typeof raw === 'string' && raw.trim() ? [raw.trim()] : [];
}

/** 工具调用结果可折叠面板 — 大文件内容默认收起，避免刷屏
 *  阈值：超过 300 字符时自动折叠，用户可手动展开查看
 */
function ToolCallResult({ result }: { result: unknown }) {
  const safeResult = typeof result === 'string' ? result : JSON.stringify(result ?? '');
  const [isExpanded, setIsExpanded] = useState(false);
  const isLarge = safeResult.length > 300;

  if (!isLarge) {
    return <span className="text-text-primary break-all">{safeResult}</span>;
  }

  return (
    <div className="w-full">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-1 text-[11px] text-primary hover:text-primary/80 transition-colors"
      >
        {isExpanded ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
        <span>{isExpanded ? '收起' : `展开 (${safeResult.length} 字符)`}</span>
      </button>
      {isExpanded && (
        <pre className="mt-1 p-2 bg-bg-subtle border border-border rounded-radius-sm text-[11px] text-text-secondary overflow-x-auto max-h-80 overflow-y-auto whitespace-pre-wrap break-all font-mono">
          {safeResult}
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
  onEditResend,
  onRegenerate,
  onDelete,
  onQuote,
  onSaveToMemory,
  onContinue,
  onAnswerVersionChange,
  artifactsByToolCall,
}: MessageProps) {
  const { t } = useI18n();
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  const isSystem = message.role === 'system';
  const isError = message.content?.startsWith('[错误') ?? false;
  // 2026-09-13 P0: 首个 token 到达前 content 是哨兵占位值 — 渲染 shimmer
  // 骨架而非把 "🤔 思考中…" 当 markdown 静态文本展示。agent 中间态文案
  // (思考/调用工具) 会覆盖占位值，覆盖后自动回退 markdown 渲染。
  const isThinkingPlaceholder =
    isAssistant && isStreaming === true && message.content === THINKING_PLACEHOLDER;
  // 2026-09 step-by-step: 多步 run 中,中间步骤可能 content="" 但有
  // tool_calls / reasoning_content。气泡只在有内容时渲染;其他部件
  // (ThinkingPanel / tool_calls) 始终渲染,确保中间步骤不会"空泡"。
  const showBubble = isUser || (isAssistant && Boolean((message.content ?? '').trim()));

  // P1 流式分块: 已确定前缀切稳定块（memo 化跳过重解析），只有 live 尾块
  // 随 delta 全量 re-parse；非流式整体单块渲染，DOM 与旧实现一致。
  const displayContent = useMemo(
    () => message.content.replace(/<img\s+[^>]*src=["']data:[^"']*["'][^>]*\/?>/gi, ''),
    [message.content],
  );
  const chunks = useMemo(
    () =>
      isStreaming === true
        ? splitStableChunks(displayContent)
        : { stable: [], live: displayContent },
    [displayContent, isStreaming],
  );
  // 未闭合围栏: live 尾块里的半截代码降级纯文本，闭合后自动恢复高亮/mermaid
  const unclosedFence = useMemo(
    () => isStreaming === true && hasUnclosedFence(displayContent),
    [displayContent, isStreaming],
  );
  // 2026-09 修复: 历史消息的 tool_calls 从后端原样加载时是 JSON 字符串
  // (session_repo 不做 parse), 直接 .map 会崩。双态归一化。
  const toolCalls: ToolCall[] = useMemo(() => {
    const raw = message.tool_calls;
    if (Array.isArray(raw)) return raw;
    if (typeof raw === 'string' && raw) {
      try {
        const parsed = JSON.parse(raw) as unknown;
        return Array.isArray(parsed) ? (parsed as ToolCall[]) : [];
      } catch {
        return [];
      }
    }
    return [];
  }, [message.tool_calls]);
  // M4: 只有 user/assistant 消息可分叉（system/tool 行没有分叉语义）
  const canFork = Boolean(onFork) && (isUser || isAssistant);
  // U5': 编辑重发只对 user 消息有意义（重写用户输入，而非模型回答）
  const canEditResend = Boolean(onEditResend) && isUser;
  // R18-A: 重新生成仅对 assistant 消息有意义（重跑回答，原会话保留）
  const canRegenerate = Boolean(onRegenerate) && isAssistant && !isStreaming;
  // R17-A: 复制按钮恒显 —— 此前被 onFeedback 门控劫持（调用方从不传
  // onFeedback），主聊天没有任何复制入口。system/tool 行无复制语义。
  const canCopy =
    (isUser || isAssistant) && Boolean((message.content ?? '').trim()) && !isStreaming;
  // R17-B: 删除仅对历史消息开放（流式中的占位消息不可删）
  const canDelete = Boolean(onDelete) && (isUser || isAssistant) && !isStreaming;
  // P0-1: 引用/保存记忆对 user+assistant 均可
  const canQuote = Boolean(onQuote) && (isUser || isAssistant);
  const canSaveToMemory = Boolean(onSaveToMemory) && (isUser || isAssistant);
  const [copied, setCopied] = useState(false);
  // R38: 技能激活明细展开态
  const [skillsExpanded, setSkillsExpanded] = useState(false);
  const activatedSkills = message.activated_skills ?? [];
  // R81: 统一参考来源 —— 记忆召回 + 附件检索溯源 + 工具命中(web/wiki/MCP)
  // 收编为一个折叠区块（类文章引用列表），N=0 时整个 chip 不渲染。
  const [sourcesExpanded, setSourcesExpanded] = useState(false);
  const memoryRefs = message.memory_refs ?? [];
  const ragCitations = message.rag_citations ?? [];
  const toolSources = message.sources ?? [];
  // R86: @memory: 实体引用命中（kind='memory'）——与记忆召回同渲染进记忆分组
  const memorySources = toolSources.filter((s) => s.kind === 'memory');
  const wikiSources = toolSources.filter((s) => s.kind === 'wiki');
  const webSources = toolSources.filter((s) => s.kind === 'web');
  const mcpSources = toolSources.filter((s) => s.kind === 'tool');
  const sourcesTotal = memoryRefs.length + ragCitations.length + toolSources.length;
  // 各分组在统一编号里的起始偏移（列表带 [1][2]… 序号, 类文章引用）
  const ragOffset = memoryRefs.length + memorySources.length;
  const wikiOffset = ragOffset + ragCitations.length;
  const webOffset = wikiOffset + wikiSources.length;
  const toolOffset = webOffset + webSources.length;

  // R38: 系统消息（如压缩通知）居中渲染，无头像/气泡
  // 必须在所有 Hooks 之后 return，否则违反 React Hooks 规则
  if (isSystem && message.compact_info) {
    return (
      <div className="flex justify-center my-3">
        <CompactBanner info={message.compact_info} />
      </div>
    );
  }

  const copyToClipboard = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div
      data-testid={isAssistant ? 'chat-message-assistant' : undefined}
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
        {/* R38: 压缩续接行 —— 横幅置于气泡上方，摘要正文/Thinking/
            copy/regenerate/delete 等正文与 affordance 全部保留。 */}
        {message.compact_info && <CompactBanner info={message.compact_info} />}

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
              // right-panel R5: 写文件工具的内联 diff 卡片（展开懒加载,
              // 点击面板按钮直达右侧变更 Tab）
              const changePaths = message.session_id ? fileChangePaths(tc) : [];
              const isBlocked = Boolean(tc.metadata?.blockReason);
              const SpecializedRenderer = resolveToolRenderer(tc.name);

              // Artifact chips / image / media refs — 无论是否使用专用渲染器都渲染
              const extras = (
                <>
                  {tc.id && artifactsByToolCall?.[tc.id]?.length ? (
                    <div className="flex flex-wrap gap-1 px-2 pb-1.5">
                      {artifactsByToolCall[tc.id].map((art) => (
                        <button
                          key={art.id}
                          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-border bg-surface hover:bg-bg-hover text-[11px] text-primary transition-colors"
                          onClick={() => useRightPanelStore.getState().selectArtifact(art.id)}
                          title="在右侧面板中查看"
                          data-testid="message-artifact-chip"
                        >
                          <FileText className="w-3 h-3 shrink-0" />
                          <span className="truncate max-w-48">{art.name}</span>
                        </button>
                      ))}
                    </div>
                  ) : null}
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
                  {tc.metadata?.mediaRefs && tc.metadata.mediaRefs.length > 0 && (
                    <div className="px-2 pb-2">
                      {tc.metadata.mediaRefs.map((ref, refIdx) => (
                        <MediaAttachment
                          key={ref.id || refIdx}
                          url={ref.api_url ?? `/api/v1/media/${ref.id}`}
                          mimeType={ref.mime_type}
                          caption={`${ref.kind} — ${ref.source || tc.name}`}
                        />
                      ))}
                    </div>
                  )}
                </>
              );

              // 专用渲染器（ZCode-inspired） — 替代通用卡片头部+结果区
              if (SpecializedRenderer && !isBlocked) {
                return (
                  <div key={`${tc.name}-${idx}`} className="flex flex-col gap-1.5">
                    <SpecializedRenderer tc={tc} />
                    {changePaths.length > 0 && (
                      <FileChangeCards sessionId={message.session_id} paths={changePaths} />
                    )}
                    {extras}
                  </div>
                );
              }

              // 通用卡片（未注册专用渲染器 or 被拦截时走旧路径）
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
                  {/* right-panel R5/R6: 文件修改卡组（<3 个平铺,≥3 个折叠为汇总条） */}
                  {changePaths.length > 0 && (
                    <FileChangeCards sessionId={message.session_id} paths={changePaths} />
                  )}
                  {/* Tool result — 大文件内容可折叠 */}
                  {tc.result !== undefined && tc.result !== '' && !hasImage && (
                    <div className="px-2 pb-1.5">
                      <ToolCallResult result={tc.result} />
                    </div>
                  )}
                  {extras}
                </div>
              );
            })}
          </div>
        )}

        {/* 消息气泡 — 2026-09 step-by-step: 空内容时不渲染,避免空白气泡 */}
        {showBubble && (
        <div
          data-error={isError ? 'true' : undefined}
          data-quote-scope="message-body"
          className={`max-w-2xl px-3.5 py-2.5 rounded-radius-sm text-[13px] leading-relaxed ${
            isUser
              ? 'bg-primary text-text-inverse'
              : isError
                ? 'bg-error/10 border border-error/40 text-error'
                : 'bg-surface border border-border'
          }`}
        >
          {/* Message content with Markdown */}
          {isAssistant ? (
            isThinkingPlaceholder ? (
              <ThinkingShimmer />
            ) : (
              <div className="max-w-none max-w-3xl mx-auto w-full">
                {/* P2: 阅读宽度约束 48rem 居中（对标主流 AI 应用），宽屏下
                    长文不再一行拉满；表格/代码块仍在容器内滚动 */}
                {chunks.stable.map((md, i) => (
                  <MarkdownChunk key={i} md={md} />
                ))}
                <MarkdownChunk md={chunks.live} plainFences={unclosedFence || undefined} />
                {/* 流式生成光标 — 跟随内容尾部闪烁（reduced-motion 全局关闭） */}
                {isStreaming && (
                  <span className="stream-cursor" aria-hidden="true" data-testid="stream-cursor" />
                )}
              </div>
            )
          ) : (
            <p className="whitespace-pre-wrap">{renderTextWithLinks(message.content)}</p>
          )}
        </div>
        )}

        {/* 底部信息 */}
        <div className="flex items-center gap-2 mt-1 text-[11px] text-muted">
          {/* R81: 统一参考来源 chip（记忆 + 附件检索 + 工具命中收编，
              原 memory-used / rag-citations 两个分散 chip 合并为此处） */}
          {sourcesTotal > 0 && (
            <button
              type="button"
              onClick={() => setSourcesExpanded((v) => !v)}
              className="inline-flex items-center gap-0.5 text-primary hover:underline"
              title={t('chat.sources_toggle')}
              data-testid="message-sources-toggle"
            >
              <BookOpen className="w-3 h-3" />
              {t('chat.sources_count').replace('{n}', String(sourcesTotal))}
              <ChevronDown
                className={`w-3 h-3 transition-transform ${sourcesExpanded ? 'rotate-180' : ''}`}
              />
            </button>
          )}
          {/* R38: 技能激活展示 */}
          {activatedSkills.length > 0 && (
            <button
              type="button"
              onClick={() => setSkillsExpanded((v) => !v)}
              className="inline-flex items-center gap-0.5 text-amber-600 dark:text-amber-400 hover:underline"
              title={t('chat.skills_toggle')}
              data-testid="skill-activated-toggle"
            >
              <Zap className="w-3 h-3" />
              {activatedSkills.length} {t('chat.skills_activated')}
              <ChevronDown
                className={`w-3 h-3 transition-transform ${skillsExpanded ? 'rotate-180' : ''}`}
              />
            </button>
          )}
          <span>
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        </div>

        {/* R81: 统一参考来源区块 —— 记忆 / 附件检索 / 知识库 / 网页 / 工具，
            每条带统一序号 [n]（类文章引用），供用户核对来源可靠性。 */}
        {sourcesExpanded && sourcesTotal > 0 && (
          <div
            className="mt-1 p-2 rounded-radius-sm bg-bg-subtle border border-border text-xs space-y-2"
            data-testid="message-sources-list"
          >
            {(memoryRefs.length > 0 || memorySources.length > 0) && (
              <div className="space-y-1">
                <div className="text-[10px] font-medium text-muted uppercase tracking-wide">
                  {t('chat.sources_group_memory')}
                </div>
                {memoryRefs.map((ref, i) => (
                  <div key={`mem-${ref.id}-${i}`} className="flex items-start gap-1.5">
                    <span className="text-muted flex-shrink-0 font-mono">[{i + 1}]</span>
                    <span className="px-1 rounded bg-primary/10 text-primary flex-shrink-0">
                      {ref.memory_type}
                    </span>
                    <span className="text-text-secondary break-all">{ref.preview}</span>
                  </div>
                ))}
                {/* R86: @memory: 实体引用命中，序号与记忆召回连续 */}
                {memorySources.map((s, i) => (
                  <div key={`memsrc-${s.title}-${i}`} className="flex items-start gap-1.5">
                    <span className="text-muted flex-shrink-0 font-mono">
                      [{memoryRefs.length + i + 1}]
                    </span>
                    <span className="px-1 rounded bg-primary/10 text-primary flex-shrink-0">
                      @memory
                    </span>
                    <span className="text-text-secondary break-all">{s.snippet || s.title}</span>
                  </div>
                ))}
              </div>
            )}

            {ragCitations.length > 0 && (
              <div className="space-y-1">
                <div className="text-[10px] font-medium text-muted uppercase tracking-wide">
                  {t('chat.sources_group_attachment')}
                </div>
                {ragCitations.map((c, i) => (
                  <div key={`rag-${c.media_id}-${i}`} className="space-y-0.5">
                    <div className="flex items-start gap-1.5">
                      <span className="text-muted flex-shrink-0 font-mono">
                        [{ragOffset + i + 1}]
                      </span>
                      <span className="text-text-secondary font-mono break-all">
                        {c.filename || c.media_id}
                      </span>
                    </div>
                    {(c.chunks ?? []).length > 0 && (
                      <div className="pl-5 text-muted font-mono">
                        {(c.chunks ?? [])
                          .map((ch) => `#${ch.index} (${ch.score.toFixed(2)})`)
                          .join(' ')}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {wikiSources.length > 0 && (
              <div className="space-y-1">
                <div className="text-[10px] font-medium text-muted uppercase tracking-wide">
                  {t('chat.sources_group_wiki')}
                </div>
                {wikiSources.map((s, i) => (
                  <div key={`wiki-${s.path}-${i}`} className="space-y-0.5">
                    <div className="flex items-start gap-1.5">
                      <span className="text-muted flex-shrink-0 font-mono">
                        [{wikiOffset + i + 1}]
                      </span>
                      <span className="text-text-secondary font-mono break-all">
                        {s.title || s.path}
                      </span>
                      {s.score != null && (
                        <span className="text-muted flex-shrink-0">({s.score.toFixed(2)})</span>
                      )}
                    </div>
                    {s.snippet && <div className="pl-5 text-muted break-all">{s.snippet}</div>}
                  </div>
                ))}
              </div>
            )}

            {webSources.length > 0 && (
              <div className="space-y-1">
                <div className="text-[10px] font-medium text-muted uppercase tracking-wide">
                  {t('chat.sources_group_web')}
                </div>
                {webSources.map((s, i) => (
                  <div key={`web-${s.url}-${i}`} className="space-y-0.5">
                    <div className="flex items-start gap-1.5">
                      <span className="text-muted flex-shrink-0 font-mono">
                        [{webOffset + i + 1}]
                      </span>
                      {s.url ? (
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary hover:underline break-all"
                        >
                          {s.title || s.url}
                        </a>
                      ) : (
                        <span className="text-text-secondary break-all">{s.title}</span>
                      )}
                    </div>
                    {s.snippet && <div className="pl-5 text-muted break-all">{s.snippet}</div>}
                  </div>
                ))}
              </div>
            )}

            {mcpSources.length > 0 && (
              <div className="space-y-1">
                <div className="text-[10px] font-medium text-muted uppercase tracking-wide">
                  {t('chat.sources_group_tool')}
                </div>
                {mcpSources.map((s, i) => (
                  <div key={`tool-${s.server}-${s.tool}-${i}`} className="space-y-0.5">
                    <div className="flex items-start gap-1.5">
                      <span className="text-muted flex-shrink-0 font-mono">
                        [{toolOffset + i + 1}]
                      </span>
                      <span className="px-1 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400 flex-shrink-0">
                        {s.server}/{s.tool}
                      </span>
                    </div>
                    {s.preview && <div className="pl-5 text-muted break-all">{s.preview}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* R38: 技能激活明细（skill_activated 流事件携带，可展开） */}
        {skillsExpanded && activatedSkills.length > 0 && (
          <div
            className="mt-1 p-2 rounded-radius-sm bg-bg-subtle border border-border text-xs space-y-1"
            data-testid="skill-activated-list"
          >
            {activatedSkills.map((skill) => (
              <div key={skill.name} className="flex flex-col gap-0.5">
                <div className="flex items-start gap-1.5">
                  <span className="px-1 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400 flex-shrink-0">
                    技能
                  </span>
                  <span className="text-text-secondary break-all">{skill.name}</span>
                </div>
                {/* MEDIUM-3: 展示命中的触发词（extract_triggers 已小写化） */}
                {skill.triggers_matched && skill.triggers_matched.length > 0 && (
                  <div className="ml-5 flex flex-wrap gap-1">
                    {skill.triggers_matched.map((trigger, idx) => (
                      <span
                        key={idx}
                        className="px-1 py-0.5 rounded bg-bg-hover text-text-tertiary text-[10px]"
                      >
                        {trigger}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* 第二轮 B2: 触达输出上限被截断时提示；最后一条消息附带「继续生成」 */}
        {isAssistant && !isStreaming && (
          <TruncationNotice finishReason={message.finish_reason} onContinue={onContinue} />
        )}

        {/* Action buttons */}
        {(canCopy ||
          onFeedback ||
          canFork ||
          canEditResend ||
          canDelete ||
          canRegenerate ||
          canQuote ||
          canSaveToMemory) && (
          <div className="flex items-center gap-1 mt-2 pt-2 border-t border-border">
            {/* 第二轮 C2: 最后一轮的回答版本切换 ‹ 2/3 › */}
            {isAssistant && onAnswerVersionChange && !isStreaming && (
              <AnswerVersionSwitcher
                sessionId={message.session_id}
                messageId={message.id}
                onChanged={onAnswerVersionChange}
              />
            )}
            {canCopy && (
              <button
                onClick={copyToClipboard}
                className="p-1 rounded hover:bg-bg-hover"
                title={t('chat.copy')}
                aria-label={t('chat.copy')}
                data-testid="copy-message"
              >
                {copied ? <Check className="w-4 h-4 text-primary" /> : <Copy className="w-4 h-4" />}
              </button>
            )}
            {/* 第二轮 B1: 朗读（不支持 speechSynthesis 时按钮自行隐藏） */}
            {canCopy && isAssistant && (
              <ReadAloudButton messageId={message.id} content={message.content} />
            )}
            {onFeedback && (
              <>
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
            {canRegenerate && (
              <button
                onClick={() => onRegenerate?.(message.id)}
                className="p-1 rounded hover:bg-bg-hover"
                title={t('chat.regenerate')}
                aria-label={t('chat.regenerate')}
                data-testid="regenerate-message"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            )}
            {canEditResend && (
              <button
                onClick={() => onEditResend?.(message.id)}
                className="p-1 rounded hover:bg-bg-hover"
                title={t('chat.edit_resend')}
                aria-label={t('chat.edit_resend')}
                data-testid="edit-resend"
              >
                <Pencil className="w-4 h-4" />
              </button>
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
            {canDelete && (
              <TwoStepDelete
                data-testid="delete-message"
                onConfirm={() => onDelete?.(message.id)}
                label={t('chat.delete_message')}
                armedLabel={t('chat.delete_message_confirm')}
                className="p-1"
              />
            )}
            {canQuote && (
              <button
                onClick={() => onQuote?.(message)}
                className="p-1 rounded hover:bg-bg-hover"
                title={t('chat.quote_to_chat')}
                aria-label={t('chat.quote_to_chat')}
                data-testid="quote-message"
              >
                <Quote className="w-4 h-4" />
              </button>
            )}
            {canSaveToMemory && (
              <button
                onClick={() => onSaveToMemory?.(message)}
                className="p-1 rounded hover:bg-bg-hover"
                title={t('chat.save_to_memory')}
                aria-label={t('chat.save_to_memory')}
                data-testid="save-to-memory"
              >
                <Brain className="w-4 h-4" />
              </button>
            )}
            {/* 第二轮 C1: 生成速度统计（右对齐，悬停看明细） */}
            {isAssistant && !isStreaming && (
              <GenerationStatsBadge stats={message.generation_stats} />
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
    prev.onContinue === next.onContinue &&
    prev.onAnswerVersionChange === next.onAnswerVersionChange &&
    prev.onFeedback === next.onFeedback &&
    prev.knowledgeRefs === next.knowledgeRefs &&
    prev.attachments === next.attachments &&
    prev.onFork === next.onFork &&
    prev.onEditResend === next.onEditResend &&
    prev.onRegenerate === next.onRegenerate &&
    prev.onDelete === next.onDelete &&
    prev.onQuote === next.onQuote &&
    prev.onSaveToMemory === next.onSaveToMemory &&
    prev.artifactsByToolCall === next.artifactsByToolCall
  );
});
