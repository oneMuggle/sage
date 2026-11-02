import { Brain, ChevronDown, Eye, EyeOff } from 'lucide-react';
import {
  memo,
  createContext,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import {
  remarkFileRefLinks,
  useConfirmedFilePaths,
} from '../../features/chat/useConfirmedFilePaths';
import { useRightPanelStore } from '../../features/right-panel/rightPanelStore';
import { humanizeToolCall } from '../../shared/lib/humanize';
import type { ToolCall } from '../../shared/lib/store';

import { Markdown } from '../markdown';
import { MD_REHYPE_PLUGINS, MD_REMARK_PLUGINS } from '../markdown/plugins';

const URL_SPLIT_RE = /(https?:\/\/[^\s<>()]+)/;

/** 本地/工作区文件链接判定（feat/file-reference-preview）——非外链且有路径特征 */
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

/** 文本兜底文件引用（feat/file-reference-preview M5）：Provider 在消息层
 *  批量确认正文中的路径是否存在，MarkdownChunk 据此注入 remark 插件。 */
const ConfirmedFilePathsContext = createContext<ReadonlySet<string>>(new Set<string>());

interface FileRefLinksProviderProps {
  sessionId: string | null | undefined;
  text: string;
  enabled: boolean;
  children: ReactNode;
}

export function FileRefLinksProvider({
  sessionId,
  text,
  enabled,
  children,
}: FileRefLinksProviderProps) {
  const confirmed = useConfirmedFilePaths(text, sessionId, enabled);
  return (
    <ConfirmedFilePathsContext.Provider value={confirmed}>
      {children}
    </ConfirmedFilePathsContext.Provider>
  );
}

/**
 * 本地文件链接 → 右栏文件预览。
 * 模块级函数（引用稳定）—— Markdown 内部据此缓存 components map，
 * 避免每次渲染重建整棵 markdown 树。
 */
function openLocalFilePreview(href: string) {
  useRightPanelStore.getState().openFilePreview(href);
}

/**
 * memo 化的 markdown 块渲染器 — P1 流式分块的关键。
 * 比较器按字符串值相等跳过重解析（slice 出的新字符串实例也能命中），
 * 已确定的稳定前缀块在每个 delta 到达时零成本跳过。
 *
 * 渲染委托给共享 `<Markdown tier="chat">`（widgets/markdown）——
 * 与产物面板 / Wiki 走同一套 GFM 排版、代码块、表格实现。
 */
export const MarkdownChunk = memo(
  function MarkdownChunk({ md, plainFences }: { md: string; plainFences?: boolean }) {
    // 文本兜底文件引用：仅当本消息有「已确认存在」的路径时追加 remark 插件
    const confirmedPaths = useContext(ConfirmedFilePathsContext);
    const remarkPlugins = useMemo(
      () =>
        confirmedPaths.size > 0
          ? ([
              ...MD_REMARK_PLUGINS,
              remarkFileRefLinks(confirmedPaths),
            ] as unknown as typeof MD_REMARK_PLUGINS)
          : MD_REMARK_PLUGINS,
      [confirmedPaths],
    );
    // 每条消息的锚点前缀独立 —— 避免多条消息的 heading id 互相覆盖
    const rawId = useId();
    const anchorPrefix = `chat-${rawId.replace(/[^a-zA-Z0-9]/g, '')}`;
    return (
      <Markdown
        content={md}
        tier="chat"
        plainFences={plainFences}
        onLocalFileClick={openLocalFilePreview}
        remarkPlugins={remarkPlugins}
        rehypePlugins={MD_REHYPE_PLUGINS}
        headingAnchorPrefix={anchorPrefix}
      />
    );
  },
  (prev, next) => prev.md === next.md && prev.plainFences === next.plainFences,
);

/** ThinkingShimmer — 等待首 token 的占位 UI。
 *  2026-10-26: 方案 D+C（混合+品牌化）— 图标 + 文字 + 计时器 + 品牌化脉冲动画。
 *  替代原有的 shimmer 条，提供更有"生命感"和明确语义的等待体验。
 *  - 大脑图标 + 品牌色光环：强化品牌识别
 *  - 渐变背景 + 脉冲动画：品牌化视觉效果
 *  - "正在思考..."文字：明确告知状态，消除不确定性
 *  - 计时器紧贴文字：提供进度感，降低焦虑
 *  - reduced-motion 下动画退化为静态，保持可读性 */
export function ThinkingShimmer({ startTime }: { startTime?: number }) {
  const [elapsed, setElapsed] = useState(0);
  const [dots, setDots] = useState('');

  useEffect(() => {
    if (!startTime) return;

    // 立即计算一次
    setElapsed(Math.floor((Date.now() - startTime) / 1000));

    // 每秒更新计时器
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);

    return () => clearInterval(timer);
  }, [startTime]);

  // 省略号动画：. → .. → ... → 循环
  useEffect(() => {
    const dotsTimer = setInterval(() => {
      setDots((prev) => (prev.length >= 3 ? '' : prev + '.'));
    }, 500);

    return () => clearInterval(dotsTimer);
  }, []);

  return (
    <div
      className="inline-flex items-center gap-2 py-1.5 px-3 rounded-full bg-gradient-to-r from-primary/10 to-primary/5 border border-primary/20"
      data-testid="thinking-shimmer"
    >
      {/* 大脑图标 + 品牌色光环 */}
      <div className="relative">
        <Brain className="w-4 h-4 text-primary animate-pulse" />
        {/* 光环效果 */}
        <div className="absolute inset-0 w-4 h-4 rounded-full bg-primary/30 animate-ping" />
      </div>

      {/* 文字 + 省略号动画 */}
      <span className="text-ui-sm text-text font-medium">
        正在思考
        <span className="inline-block w-4 text-left" data-testid="thinking-dots">
          {dots}
        </span>
      </span>

      {/* 计时器（紧贴文字） */}
      {startTime && elapsed > 0 && (
        <span className="text-ui-xs text-muted font-mono" data-testid="thinking-timer">
          {elapsed}s
        </span>
      )}
    </div>
  );
}

/** ThinkingPanel - 可折叠的 LLM 思考过程展示面板
 *  P1: 流式 reasoning 时自动展开 (isStreaming=true)
 */
export function ThinkingPanel({
  reasoning,
  isStreaming,
}: {
  reasoning: string;
  isStreaming?: boolean;
}) {
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

export interface MessageMarkdownPartsAuditInput {
  blockCount: number;
  codeBlockCount: number;
  tableCount: number;
  unfinishedFenceCount: number;
}

export interface MessageMarkdownPartsAuditReport {
  blockCount: number;
  codeBlockCount: number;
  tableCount: number;
  unfinishedFenceCount: number;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateMessageMarkdownPartsAudit(
  input: MessageMarkdownPartsAuditInput,
): MessageMarkdownPartsAuditReport {
  const blockCount = Math.max(0, Math.trunc(input.blockCount));
  const codeBlockCount = Math.max(0, Math.trunc(input.codeBlockCount));
  const tableCount = Math.max(0, Math.trunc(input.tableCount));
  const unfinishedFenceCount = Math.max(0, Math.trunc(input.unfinishedFenceCount));
  const issueCodes: string[] = [];

  if (blockCount === 0) {
    issueCodes.push('empty_markdown_parts');
  }
  if (unfinishedFenceCount > 0) {
    issueCodes.push('unclosed_markdown_code_fence');
  }
  if (codeBlockCount + tableCount > blockCount && blockCount > 0) {
    issueCodes.push('part_count_mismatch');
  }

  return {
    blockCount,
    codeBlockCount,
    tableCount,
    unfinishedFenceCount,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportMessageMarkdownPartsAuditJson(input: MessageMarkdownPartsAuditInput): string {
  return JSON.stringify(evaluateMessageMarkdownPartsAudit(input));
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditMessageMarkdownPartsGovernance(): string {
  return JSON.stringify({
    module: 'message-markdown-parts',
    phase: 'P186',
    audited: true,
  });
}
