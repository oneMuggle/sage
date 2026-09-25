// src/features/chat/selectionQuote.ts
//
// 对话阅读导航 A4/A5（docs/mcp-chat-reading-nav-optimization.md）：
// 划词引用与"引用追加到草稿"的纯函数。
//
// - 只有落在同一个 `[data-quote-scope]`（消息气泡正文）内的选区才可引用：
//   跨消息的选区会把头像字母、按钮文字等杂质带进引用块。
// - 引用追加到草稿尾部，不覆盖用户已输入的内容；连续引用多段会依次累积。

/** 可引用区域的标记属性（Message 气泡正文上） */
export const QUOTE_SCOPE_ATTR = 'data-quote-scope';

/** 选区文本归一化：统一换行、去掉行尾空白、压缩 3 行以上的空行 */
export function normalizeSelectedText(text: string): string {
  return text
    .replace(/\r\n?/g, '\n')
    .replace(/[ \t\u00a0]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/** 转 Markdown 引用块：每行加 `> ` 前缀，空行保留 `>`（不留行尾空格） */
export function formatQuoteBlock(text: string): string {
  return text
    .split('\n')
    .map((line) => (line.trim() ? `> ${line}` : '>'))
    .join('\n');
}

/**
 * 把引用块追加到草稿：草稿为空 → 引用块 + 空行；
 * 草稿非空 → 草稿（去尾部空白）+ 空行 + 引用块 + 空行。
 */
export function appendQuoteToDraft(draft: string, quote: string): string {
  const block = quote.replace(/\s+$/, '');
  if (!block) return draft;
  const head = draft.replace(/\s+$/, '');
  return head ? `${head}\n\n${block}\n\n` : `${block}\n\n`;
}

function scopeOf(node: Node | null, root: Element): Element | null {
  if (!node) return null;
  const el = node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement;
  const scope = el?.closest(`[${QUOTE_SCOPE_ATTR}]`) ?? null;
  return scope && root.contains(scope) ? scope : null;
}

export interface QuotableSelection {
  text: string;
  /** 选区外接矩形（jsdom 等无布局环境为 null） */
  rect: DOMRect | null;
}

/** 判定当前选区是否可引用；可引用时返回归一化文本与选区矩形 */
export function getQuotableSelection(
  selection: Selection | null,
  root: Element | null,
): QuotableSelection | null {
  if (!selection || !root || selection.rangeCount === 0 || selection.isCollapsed) return null;
  const anchorScope = scopeOf(selection.anchorNode, root);
  if (!anchorScope || anchorScope !== scopeOf(selection.focusNode, root)) return null;
  const text = normalizeSelectedText(selection.toString());
  if (!text) return null;
  const range = selection.getRangeAt(0);
  const rect =
    typeof range.getBoundingClientRect === 'function' ? range.getBoundingClientRect() : null;
  return { text, rect };
}

/** 浮动按钮位置：默认在选区上方居中，顶部空间不足时放到下方，并限制在视口内 */
export function computeQuoteButtonPosition(
  rect: Pick<DOMRect, 'top' | 'bottom' | 'left' | 'width'> | null,
  viewportWidth: number,
  buttonHeight = 30,
  margin = 8,
): { top: number; left: number } {
  if (!rect) return { top: margin, left: margin };
  const above = rect.top - buttonHeight - margin;
  const top = above >= margin ? above : rect.bottom + margin;
  const center = rect.left + rect.width / 2;
  const left = Math.min(
    Math.max(center, margin + 40),
    Math.max(viewportWidth - margin - 40, margin),
  );
  return { top, left };
}
