// src/features/chat/markdownText.ts
//
// 对话阅读体验第二轮（docs/mcp-chat-reading-nav-optimization.md §10.4）：
// Markdown → 可读纯文本。B1 朗读与 B4 会话内查找共用 —— 两者都需要"用户在
// 气泡里看到的文字"，而不是 Markdown 源码（链接地址、强调符号、表格竖线等
// 不应被朗读，也不应计入查找命中）。
//
// 只做轻量的正则剥离，不引入 Markdown 解析器：输出只用于朗读和计数，不用于
// 渲染，少量边界差异可以接受。代码（围栏块与行内）先换成占位符保护起来，
// 避免 `**kwargs`、`a || b` 这类内容被当成标记剥掉。

export interface PlainTextOptions {
  /**
   * 围栏代码块的处理方式：缺省保留代码文本（查找需要命中代码）；
   * 传入字符串时用该文案替换整个代码块（朗读代码没有意义）。
   */
  codeBlockReplacement?: string;
}

const FENCED_CODE = /^[ \t]*(`{3,}|~{3,})[^\n]*\n([\s\S]*?)(?:^[ \t]*\1[ \t]*$|(?![\s\S]))/gm;
const INLINE_CODE = /`([^`\n]+)`/g;
// 私有区字符作占位符界定符：正文里几乎不会出现，且不触发 no-control-regex
const PLACEHOLDER = /\uE000(\d+)\uE001/g;

export function markdownToPlainText(markdown: string, options: PlainTextOptions = {}): string {
  const { codeBlockReplacement } = options;
  const kept: string[] = [];
  const keep = (value: string): string => {
    kept.push(value);
    return `\uE000${kept.length - 1}\uE001`;
  };

  const text = markdown
    .replace(/\r\n?/g, '\n')
    .replace(FENCED_CODE, (_match, _fence: string, code: string) => {
      return `\n${keep(codeBlockReplacement ?? code.replace(/\n$/, ''))}\n`;
    })
    .replace(INLINE_CODE, (_match, code: string) => keep(code))
    // 图片 / 链接只保留可见文字
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/<(https?:\/\/[^>\s]+)>/g, '$1')
    // 行内 HTML 标签
    .replace(/<\/?[a-zA-Z][^>]*>/g, '')
    // 块级标记：标题、引用、列表（含任务框）、分隔线
    .replace(/^[ \t]*#{1,6}[ \t]+/gm, '')
    .replace(/^[ \t]*>[ \t]?/gm, '')
    .replace(/^[ \t]*(?:[-*+]|\d+[.)])[ \t]+(?:\[[ xX]\][ \t]+)?/gm, '')
    .replace(/^[ \t]*(?:[-*_][ \t]*){3,}$/gm, '')
    // 表格：去掉分隔行，单元格之间用空格隔开
    .replace(/^[ \t]*\|?(?:[ \t]*:?-{3,}:?[ \t]*\|)+(?:[ \t]*:?-{3,}:?)?[ \t]*$/gm, '')
    .replace(/^[ \t]*\|(.*?)\|?[ \t]*$/gm, (_match, cells: string) =>
      cells
        .split('|')
        .map((cell) => cell.trim())
        .join(' '),
    )
    // 强调 / 删除线；下划线只在词边界处视为强调（snake_case 保持原样）
    .replace(/(\*\*|__|~~)(?=\S)([\s\S]*?\S)\1/g, '$2')
    .replace(/\*(?=\S)([^*\n]*?\S)\*/g, '$1')
    .replace(/(^|[^\p{L}\p{N}_])_(?=\S)([^_\n]*?\S)_(?![\p{L}\p{N}_])/gu, '$1$2');

  return text
    .replace(PLACEHOLDER, (_match, index: string) => kept[Number(index)] ?? '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
