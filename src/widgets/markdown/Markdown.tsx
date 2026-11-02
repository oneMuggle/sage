/**
 * 共享 Markdown 渲染器 —— 三处实现（MessageMarkdownParts / FileContentRenderer / Wiki）
 * 的单一收敛点。
 *
 * 使用示例：
 *   <Markdown content={md} tier="minimal" />                     // 产物 / Wiki
 *   <Markdown content={md} tier="chat" onLocalFileClick={...} /> // 聊天
 *
 * 设计取舍：
 * - `tier` 仅两档：`minimal` 走基础排版 + plain fences；`chat` 走 Shiki/Mermaid/
 *   MarkdownImage/表格复制等完整 chat UI。原本计划的 `full` 档（KaTeX 显式 opt-in）
 *   砍掉 —— 现有三处实现都默认启用 KaTeX，没必要单独一档。
 * - 自带 .md-content 作用域样式（CSS 文件 side-effect 引入），调用方无需包容器。
 * - heading 锚点由 `headingAnchorPrefix` 唯一化 —— 多实例共存时避免 id 冲突。
 * - 内部 `useMemo` 缓存 components map —— 仅 opts 语义字段变化才重建。
 */

import { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  createMarkdownComponents,
  markdownComponentsDeps,
  useMarkdownHeadings,
  type MarkdownTier,
} from './components';
import { MD_REHYPE_PLUGINS, MD_REMARK_PLUGINS } from './plugins';
import './markdown.css';

export interface MarkdownProps {
  /** markdown 源文本 */
  content: string;
  /** 渲染档位 */
  tier?: MarkdownTier;
  /** 外层 div 的 className（会与 `.md-content` 合并） */
  className?: string;
  /** 锚点 id 前缀（多实例共存时唯一化） */
  headingAnchorPrefix?: string;
  /** 表格最大高度（CSS 单位，默认 "24rem"；"none" 不限高） */
  tableMaxHeight?: string;
  /** 流式渲染 —— code 走 plain pre/code 避免 Shiki 抖动 */
  plainFences?: boolean;
  /** 本地文件链接点击回调 */
  onLocalFileClick?: (href: string) => void;
  /** 标题点击回调（TOC 联动） */
  onHeadingClick?: (id: string) => void;
  /** data-testid —— 测试定位用 */
  testId?: string;
  /** 自定义 remarkPlugins（默认 = MD_REMARK_PLUGINS） */
  remarkPlugins?: typeof MD_REMARK_PLUGINS;
  /** 自定义 rehypePlugins（默认 = MD_REHYPE_PLUGINS） */
  rehypePlugins?: typeof MD_REHYPE_PLUGINS;
}

export function Markdown({
  content,
  tier = 'minimal',
  className,
  headingAnchorPrefix = 'md',
  tableMaxHeight = '24rem',
  plainFences = false,
  onLocalFileClick,
  onHeadingClick,
  testId,
  remarkPlugins = MD_REMARK_PLUGINS,
  rehypePlugins = MD_REHYPE_PLUGINS,
}: MarkdownProps) {
  const headings = useMarkdownHeadings(content);

  const components = useMemo(
    () =>
      createMarkdownComponents({
        tier,
        headings,
        headingAnchorPrefix,
        tableMaxHeight,
        onLocalFileClick,
        onHeadingClick,
        plainFences,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [...markdownComponentsDeps({
      tier,
      headings,
      headingAnchorPrefix,
      tableMaxHeight,
      onLocalFileClick,
      onHeadingClick,
      plainFences,
    })],
  );

  const containerClass = className ? `md-content ${className}` : 'md-content';

  return (
    <div className={containerClass} data-testid={testId}>
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
