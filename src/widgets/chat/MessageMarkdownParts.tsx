import { Brain, ChevronDown, Eye, EyeOff } from 'lucide-react';
import { memo, useEffect, useRef, useState, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import { humanizeToolCall } from '../../shared/lib/humanize';
import type { ToolCall } from '../../shared/lib/store';

import { HtmlCodeBlock } from './HtmlCodeBlock';
import { MarkdownImage } from './MarkdownImage';
import { MermaidBlock } from './MermaidBlock';
import { ShikiCodeBlock } from './ShikiCodeBlock';

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
// eslint-disable-next-line react-refresh/only-export-components
export function renderTextWithLinks(text: string): ReactNode[] {
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
        <table className="min-w-full text-ui-sm border-collapse border border-border">
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
        title={href}
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
    return <h1 className="text-ui-xl font-bold mt-4 mb-2">{children}</h1>;
  },
  h2({ children }: { children?: ReactNode }) {
    return <h2 className="text-ui-lg font-bold mt-3 mb-2">{children}</h2>;
  },
  h3({ children }: { children?: ReactNode }) {
    return <h3 className="text-ui-base font-bold mt-2 mb-1">{children}</h3>;
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
export const MarkdownChunk = memo(
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
export function ThinkingShimmer() {
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
export function ThinkingPanel({ reasoning, isStreaming }: { reasoning: string; isStreaming?: boolean }) {
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
  }, [reasoning, isStreaming]);

  return (
    <div className="mb-2 border border-border/50 rounded-radius-sm overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-bg-subtle hover:bg-bg-hover transition-colors text-left"
        aria-expanded={isExpanded}
      >
        <Brain className="w-4 h-4 text-primary" />
        <span className="text-ui-sm font-medium text-text-secondary">
          思考过程 ({reasoning.length} 字)
        </span>
        <ChevronDown
          className={`w-4 h-4 ml-auto transition-transform ${isExpanded ? 'rotate-180' : ''}`}
        />
      </button>
      {isExpanded && (
        <div
          ref={contentRef}
          className="px-3 py-2 bg-bg-subtle/50 border-t border-border/50 text-ui-sm text-text-secondary leading-relaxed max-h-60 overflow-y-auto whitespace-pre-wrap"
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
export function ToolCallTitle({ name, args }: { name: string; args: Record<string, unknown> }) {
  const human = humanizeToolCall(name, args);
  return (
    <>
      <span className="text-text-secondary">
        {human.verb}
        {human.object !== '' && (
          <>
            {' '}
            {human.scope ? (
              <code className="rounded bg-bg-hover px-1 py-0.5 font-mono text-ui-2xs text-text break-all">
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
          className={`rounded px-1 py-0.5 text-ui-xs leading-none ${
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
// eslint-disable-next-line react-refresh/only-export-components
export function fileChangePaths(tc: ToolCall): string[] {
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
export function ToolCallResult({ result }: { result: unknown }) {
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
        className="flex items-center gap-1 text-ui-2xs text-primary hover:text-primary/80 transition-colors"
      >
        {isExpanded ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
        <span>{isExpanded ? '收起' : `展开 (${safeResult.length} 字符)`}</span>
      </button>
      {isExpanded && (
        <pre className="mt-1 p-2 bg-bg-subtle border border-border rounded-radius-sm text-ui-2xs text-text-secondary overflow-x-auto max-h-80 overflow-y-auto whitespace-pre-wrap break-all font-mono">
          {safeResult}
        </pre>
      )}
    </div>
  );
}

