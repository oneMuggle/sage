/**
 * Markdown 渲染器本地文案（中英双语）。
 *
 * 设计取舍：
 * - **不**注入到 `shared/lib/i18n` 全局词典 —— 避免 shared→widgets 反向依赖，
 *   也避免改动基线外的 i18n 文件影响其他模块。
 * - 自包含 + 用 `useOptionalI18n()` 取 locale，provider 缺失时默认中文。
 * - 后续若新增文案，只在此文件增删 key；调用方类型自动收窄。
 *
 * 注：shared/lib/i18n/zh.ts (44 行) 与 en.ts (43 行) 都不在 architecture-baseline
 * 追踪名单（已 grep 验证），但本模块选择"自包含"而非"合并进全局词典"，
 * 是为了让 widgets/markdown 彻底零全局改动即可运作。
 */

export const MARKDOWN_I18N_KEYS = [
  'md.table.copy',
  'md.table.copied',
  'md.code.copy',
  'md.code.copied',
  'md.code.fold',
  'md.code.unfold',
  'md.code.wrapOn',
  'md.code.wrapOff',
  'md.outline.title',
  'md.outline.itemCount',
  'md.outline.empty',
] as const;

export type MarkdownI18nKey = (typeof MARKDOWN_I18N_KEYS)[number];

export const markdownZh: Record<MarkdownI18nKey, string> = {
  'md.table.copy': '复制表格',
  'md.table.copied': '已复制',
  'md.code.copy': '复制',
  'md.code.copied': '已复制',
  'md.code.fold': '折叠',
  'md.code.unfold': '展开',
  'md.code.wrapOn': '换行：开',
  'md.code.wrapOff': '换行：关',
  'md.outline.title': '大纲',
  'md.outline.itemCount': '{count} 项',
  'md.outline.empty': '无标题',
};

export const markdownEn: Record<MarkdownI18nKey, string> = {
  'md.table.copy': 'Copy table',
  'md.table.copied': 'Copied',
  'md.code.copy': 'Copy',
  'md.code.copied': 'Copied',
  'md.code.fold': 'Collapse',
  'md.code.unfold': 'Expand',
  'md.code.wrapOn': 'Wrap: on',
  'md.code.wrapOff': 'Wrap: off',
  'md.outline.title': 'Outline',
  'md.outline.itemCount': '{count} items',
  'md.outline.empty': 'No headings',
};

export const MARKDOWN_I18N_DICTS = {
  zh: markdownZh,
  en: markdownEn,
} as const;
