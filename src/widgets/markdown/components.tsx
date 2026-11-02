/**
 * Markdown 组件映射工厂 —— 统一三处实现（MessageMarkdownParts / FileContentRenderer / Wiki）。
 *
 * 设计取舍：
 * - `createMarkdownComponents(opts)` 工厂模式而非单例：opts 变化时重建 components map
 *   （useMemo 在调用方），避免 React 每次渲染都换引用导致 ReactMarkdown 全量重渲染。
 * - 把 chat 专有 UI（ShikiCodeBlock / MermaidBlock / MarkdownImage）作为可选分支，
 *   通过 `tier` 控制启用；minimal 档走降级（plain `<pre><code>`）。
 * - 本地文件链接判定 (`isLocalFilePathHref`) 走 `./links`，避免反向依赖 widgets/chat。
 * - heading id 由 `outline.headingIdForLine` 按 1-based 行号 lookup，
 *   与 TOC 完全一致；react-markdown 在 heading 渲染时通过 node.position.start.line 取。
 */

import { Copy } from 'lucide-react';
import { useMemo, useRef, useState, type ReactNode } from 'react';
import type { Components, ExtraProps } from 'react-markdown';

import { useOptionalI18n } from '../../shared/lib/i18n';
import { ContextMenu } from '../../shared/ui/ContextMenu/ContextMenu';
import { HtmlCodeBlock } from '../chat/HtmlCodeBlock';
import { MarkdownImage } from '../chat/MarkdownImage';
import { MermaidBlock } from '../chat/MermaidBlock';
import { ShikiCodeBlock } from '../chat/ShikiCodeBlock';

import { isLocalFilePathHref } from './links';
import { extractHeadings, headingIdForLine, type RawHeading } from './outline';
import { useMdI18n } from './useMdI18n';

export type MarkdownTier = 'minimal' | 'chat';

export interface MarkdownComponentsOptions {
  /** 渲染档位：minimal = 基础排版；chat = 加 Shiki/Mermaid/MarkdownImage/表格复制 */
  tier: MarkdownTier;
  /** 预解析的 heading 列表（与 buildMarkdownOutline 同源），用于 heading id lookup */
  headings: RawHeading[];
  /** 锚点 id 前缀，避免多实例冲突 */
  headingAnchorPrefix?: string;
  /** 表格限高（CSS 单位，默认 "24rem"）；传 "none" 不限高 */
  tableMaxHeight?: string;
  /** 本地文件链接点击回调（不传则降级为默认 <a>） */
  onLocalFileClick?: (href: string) => void;
  /** 点击标题回调（TOC 联动） */
  onHeadingClick?: (id: string) => void;
  /** 流式渲染（chat streaming） —— code 用 plain pre/code 避免 Shiki 抖动 */
  plainFences?: boolean;
}

/**
 * 创建 markdown 组件映射表。
 * 调用方应 useMemo 缓存，components 引用稳定 = ReactMarkdown 不会整树重建。
 *
 * 注意：工厂在渲染期被调用，内部使用 useMdI18n() hook 是合法的
 * （因为工厂调用方本身是 React 函数组件，hook 调用顺序稳定）。
 */
export function createMarkdownComponents(opts: MarkdownComponentsOptions): Components {
  const {
    tier,
    headings,
    headingAnchorPrefix = 'md',
    tableMaxHeight = '24rem',
    onLocalFileClick,
    onHeadingClick,
    plainFences = false,
  } = opts;

  const useRichBlocks = tier === 'chat' && !plainFences;

  const makeHeading =
    (level: 1 | 2 | 3 | 4 | 5 | 6) =>
    (props: React.ComponentPropsWithoutRef<'h1'> & ExtraProps): ReactNode => {
      const { node, children, ...rest } = props;
      const line = node?.position?.start.line;
      const id =
        (typeof line === 'number' && headingIdForLine(headings, line, headingAnchorPrefix)) ||
        undefined;
      const Tag = `h${level}` as const;
      return (
        <Tag
          id={id}
          onClick={id && onHeadingClick ? () => onHeadingClick(id) : undefined}
          style={id && onHeadingClick ? { cursor: 'pointer' } : undefined}
          {...rest}
        >
          {children}
        </Tag>
      );
    };

  const components: Components = {
    h1: makeHeading(1) as unknown as NonNullable<Components['h1']>,
    h2: makeHeading(2) as unknown as NonNullable<Components['h2']>,
    h3: makeHeading(3) as unknown as NonNullable<Components['h3']>,
    h4: makeHeading(4) as unknown as NonNullable<Components['h4']>,
    h5: makeHeading(5) as unknown as NonNullable<Components['h5']>,
    h6: makeHeading(6) as unknown as NonNullable<Components['h6']>,

    p: ({ children }) => <p>{children}</p>,

    a: ({ href, children }) => {
      if (isLocalFilePathHref(href)) {
        if (onLocalFileClick) {
          return (
            <a
              href={href}
              onClick={(e) => {
                e.preventDefault();
                onLocalFileClick(href!);
              }}
              title={href}
              data-local-file="true"
              data-testid="markdown-file-link"
            >
              {children}
            </a>
          );
        }
        return <span data-local-file="true">{children}</span>;
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      );
    },

    img: ({ src, alt }) =>
      useRichBlocks ? (
        <MarkdownImage src={src} alt={alt} />
      ) : (
        <img src={src} alt={alt || ''} loading="lazy" />
      ),

    table: ({ children }) => (
      <MarkdownTable maxHeight={tableMaxHeight}>{children}</MarkdownTable>
    ),

    th: ({ children }) => <th>{children}</th>,
    td: ({ children }) => <td>{children}</td>,

    ul: ({ children, ...rest }) => (
      <ul {...rest}>
        {children}
      </ul>
    ),
    ol: ({ children, ...rest }) => (
      <ol {...rest}>
        {children}
      </ol>
    ),
    li: ({ children, ...rest }) => (
      <li {...rest}>
        {children}
      </li>
    ),
    input: ({ ...rest }) => <input readOnly {...rest} />,

    blockquote: ({ children }) => <blockquote>{children}</blockquote>,

    hr: () => <hr />,

    pre: ({ children }) => <>{children}</>,

    code: (props) => {
      // node 必须解构出来但不使用：否则会随 rest 展开到 DOM 上触发 React 警告
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { className, children, node, ...rest } = props as {
        className?: string;
        children?: ReactNode;
        node?: ExtraProps['node'];
        [k: string]: unknown;
      };
      const match = /language-(\w+)/.exec(className || '');
      const codeString = String(children || '');
      const isInline = !match && !codeString.includes('\n');

      if (isInline) {
        return (
          <code className={className} {...rest}>
            {children}
          </code>
        );
      }

      const language = match?.[1];
      const stripped = codeString.replace(/\n$/, '');

      if (useRichBlocks) {
        if (language === 'mermaid') {
          return <MermaidBlock code={stripped} />;
        }
        if (language === 'html') {
          return <HtmlCodeBlock code={stripped} />;
        }
        return <ShikiCodeBlock language={language}>{stripped}</ShikiCodeBlock>;
      }

      return (
        <pre>
          <code className={language ? `language-${language}` : ''} {...rest}>
            {stripped}
          </code>
        </pre>
      );
    },
  };

  return components;
}

/**
 * 表格 —— 包一层 .md-table-wrap 容器，加复制按钮 + 限高 + 右键菜单。
 * 复制输出 TSV（与历史 MessageMarkdownParts 行为一致）。
 */
function MarkdownTable({
  children,
  maxHeight,
}: {
  children: ReactNode;
  maxHeight: string;
}) {
  const t = useMdI18n();
  const globalI18n = useOptionalI18n();
  const tableRef = useRef<HTMLTableElement | null>(null);
  const [copied, setCopied] = useState(false);
  const clamp = maxHeight !== 'none';

  // 右键菜单文案优先用全局词典（与其它右键菜单观感一致），
  // 无 I18nProvider 时退回本模块自带词典。
  const copyMenuLabel = globalI18n ? globalI18n.t('contextMenu.table.copy') : t('md.table.copy');

  const copyTable = async () => {
    const table = tableRef.current;
    if (!table) return;
    try {
      await navigator.clipboard.writeText(tableToTsv(table));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // 老浏览器 clipboard API 可能失败，静默降级
    }
  };

  const menuItems = () => [
    {
      id: 'copy-table',
      label: copyMenuLabel,
      icon: Copy,
      onSelect: () => void copyTable(),
    },
  ];

  return (
    <ContextMenu items={menuItems}>
      <div
        className="md-table-wrap"
        data-clamp={clamp ? '' : undefined}
        style={clamp ? ({ '--md-table-max-height': maxHeight } as React.CSSProperties) : undefined}
      >
        <button
          type="button"
          className="md-table-copy-btn"
          onClick={() => void copyTable()}
          data-testid="markdown-table-copy"
          data-copied={copied ? 'true' : undefined}
          aria-label={t('md.table.copy')}
        >
          {copied ? t('md.table.copied') : t('md.table.copy')}
        </button>
        <table ref={tableRef}>{children}</table>
      </div>
    </ContextMenu>
  );
}

/**
 * 把 <table> DOM 转成 TSV 文本 —— 与 MessageMarkdownParts 现有行为一致。
 * 抽出来是为了单测覆盖。
 */
export function tableToTsv(table: Element): string {
  const rows: string[] = [];
  table.querySelectorAll('tr').forEach((tr) => {
    const cells: string[] = [];
    tr.querySelectorAll('th, td').forEach((cell) => {
      const text = ((cell as HTMLElement).innerText ?? (cell as HTMLElement).textContent ?? '')
        .replace(/\n/g, ' ')
        .replace(/\t/g, ' ')
        .trim();
      cells.push(text);
    });
    rows.push(cells.join('\t'));
  });
  return rows.join('\n');
}

/**
 * 调用方 useMemo 的 key 比较函数 —— 避免每次渲染都重建 components map。
 * 仅当 opts 的语义字段变化时才重建。
 */
export function markdownComponentsDeps(opts: MarkdownComponentsOptions): unknown[] {
  return [
    opts.tier,
    opts.headings,
    opts.headingAnchorPrefix,
    opts.tableMaxHeight,
    opts.onLocalFileClick,
    opts.onHeadingClick,
    opts.plainFences,
  ];
}

/**
 * 从源 markdown 文本预解析 heading 列表。
 * 调用方应 useMemo 缓存，作为 `headings` 传给 createMarkdownComponents。
 */
export function useMarkdownHeadings(source: string): RawHeading[] {
  return useMemo(() => extractHeadings(source), [source]);
}
