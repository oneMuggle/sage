/**
 * Markdown 插件集合 —— 抽出自 MessageMarkdownParts.tsx:45-46。
 *
 * 集中管理 remark/rehype 插件列表，保证所有消费方（聊天 / 产物 / Wiki）
 * 走同一套解析管线。类型用 `NonNullable<Options['remarkPlugins']>`，
 * 因为 react-markdown v9 不直接导出 `PluggableList`。
 */

import type React from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

type Options = React.ComponentProps<typeof ReactMarkdown>;

/** remark 插件集合：GFM 表/任务列表/删除线 + KaTeX 数学 */
export const MD_REMARK_PLUGINS: NonNullable<Options['remarkPlugins']> = [
  remarkGfm,
  remarkMath,
];

/** rehype 插件集合：KaTeX 渲染 */
export const MD_REHYPE_PLUGINS: NonNullable<Options['rehypePlugins']> = [rehypeKatex];
