/**
 * Markdown 渲染器统一出口 —— 单一收敛点。
 *
 * 消费者典型用法：
 *   import { Markdown, buildMarkdownOutline, extractHeadings } from '../markdown';
 *   <Markdown content={md} tier="minimal" />
 *
 * 导出分类：
 * - 主组件：Markdown, MarkdownOutline
 * - 工厂：createMarkdownComponents, useMarkdownHeadings, markdownComponentsDeps
 * - 大纲工具：extractHeadings, buildMarkdownOutline, headingIdForLine, slugifyHeading
 * - 链接判定：isLocalFilePathHref
 * - 插件：MD_REMARK_PLUGINS, MD_REHYPE_PLUGINS
 * - i18n：useMdI18n, MARKDOWN_I18N_DICTS, markdownZh, markdownEn
 * - 表格工具：tableToTsv
 * - 类型：MarkdownTier, MarkdownComponentsOptions, MarkdownProps, MarkdownOutlineProps,
 *        TocEntry, RawHeading, MarkdownOutlineData, HeadingLevel, MarkdownI18nKey
 */

// 主组件
export { Markdown, type MarkdownProps } from './Markdown';
export { MarkdownOutline, type MarkdownOutlineProps } from './MarkdownOutline';

// 组件工厂
export {
  createMarkdownComponents,
  useMarkdownHeadings,
  markdownComponentsDeps,
  tableToTsv,
  type MarkdownTier,
  type MarkdownComponentsOptions,
} from './components';

// 大纲（TOC）
export {
  extractHeadings,
  buildMarkdownOutline,
  headingIdForLine,
  slugifyHeading,
  type TocEntry,
  type RawHeading,
  type MarkdownOutlineData,
  type HeadingLevel,
} from './outline';

// 链接判定
export { isLocalFilePathHref } from './links';

// 插件集合
export { MD_REMARK_PLUGINS, MD_REHYPE_PLUGINS } from './plugins';

// i18n
export {
  MARKDOWN_I18N_DICTS,
  MARKDOWN_I18N_KEYS,
  markdownZh,
  markdownEn,
  type MarkdownI18nKey,
} from './i18n';
export { useMdI18n } from './useMdI18n';
