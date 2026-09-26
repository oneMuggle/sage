// src/features/chat/textHighlight.ts
//
// 对话阅读体验 B3 / B4（docs/mcp-chat-reading-nav-optimization.md §10.4）：基于
// CSS Custom Highlight API 的检索词高亮。只登记 Range、不改 DOM —— 不影响 React
// 协调、复制和划词引用。Chromium 105+ 可用（两条分支都是 Electron 21 /
// Chromium 106）；不支持的环境（jsdom、旧浏览器）静默跳过，只保留定位本身。
//
// 样式见 src/index.css 的 ::highlight(...) 规则。

/** B3：侧栏搜索命中直达后的高亮 */
export const SEARCH_HIT_HIGHLIGHT = 'sage-search-hit';
/** B4：会话内查找 —— 已渲染区域内的全部命中 */
export const FIND_HIGHLIGHT = 'sage-find';
/** B4：会话内查找 —— 当前命中 */
export const FIND_CURRENT_HIGHLIGHT = 'sage-find-current';
/** B3 高亮的保留时间 */
export const SEARCH_HIT_HIGHLIGHT_MS = 8000;

/** 只在消息正文里匹配：工具卡片、来源列表、操作按钮不参与 */
const SCOPE_SELECTOR = '[data-quote-scope]';
/** 正文内也要跳过的节点：代码块工具栏按钮、KaTeX 的隐藏 MathML 副本 */
const SKIP_SELECTOR = 'button, script, style, .katex-mathml';

interface HighlightRegistryLike {
  set(name: string, highlight: object): unknown;
  delete(name: string): unknown;
}
type HighlightCtor = new (...ranges: Range[]) => { priority: number };

function highlightApi(): { registry: HighlightRegistryLike; Highlight: HighlightCtor } | null {
  const g = globalThis as unknown as {
    CSS?: { highlights?: HighlightRegistryLike };
    Highlight?: HighlightCtor;
  };
  if (!g.CSS?.highlights || typeof g.Highlight !== 'function') return null;
  return { registry: g.CSS.highlights, Highlight: g.Highlight };
}

export function isHighlightSupported(): boolean {
  return highlightApi() !== null;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** 拼接文本中的偏移 → (文本节点, 节点内偏移)。end=true 时落在前一节点的末尾 */
function locate(
  starts: number[],
  nodes: Text[],
  pos: number,
  end: boolean,
): { node: Text; offset: number } {
  let lo = 0;
  let hi = starts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (end ? starts[mid] < pos : starts[mid] <= pos) lo = mid;
    else hi = mid - 1;
  }
  return { node: nodes[lo], offset: pos - starts[lo] };
}

/**
 * 在 root 的正文范围内查找 query 的全部出现（不区分大小写的字面匹配），按文档
 * 顺序返回。同一正文块内的文本节点先拼接再匹配，因此可以跨过加粗等行内标记。
 */
export function findTextRanges(root: Element, query: string): Range[] {
  const needle = query.trim();
  if (!needle) return [];
  const scopes = root.matches(SCOPE_SELECTOR)
    ? [root]
    : Array.from(root.querySelectorAll(SCOPE_SELECTOR));
  const pattern = new RegExp(escapeRegExp(needle), 'gi');
  const ranges: Range[] = [];
  for (const scope of scopes) {
    const doc = scope.ownerDocument;
    const walker = doc.createTreeWalker(scope, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) =>
        node.parentElement?.closest(SKIP_SELECTOR)
          ? NodeFilter.FILTER_REJECT
          : NodeFilter.FILTER_ACCEPT,
    });
    const nodes: Text[] = [];
    const starts: number[] = [];
    let text = '';
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      starts.push(text.length);
      nodes.push(node as Text);
      text += (node as Text).data;
    }
    if (nodes.length === 0) continue;
    pattern.lastIndex = 0;
    for (let match = pattern.exec(text); match; match = pattern.exec(text)) {
      const from = locate(starts, nodes, match.index, false);
      const to = locate(starts, nodes, match.index + match[0].length, true);
      const range = doc.createRange();
      range.setStart(from.node, from.offset);
      range.setEnd(to.node, to.offset);
      ranges.push(range);
    }
  }
  return ranges;
}

/** 登记（或替换）一组高亮；ranges 为空时移除 */
export function setHighlight(name: string, ranges: Range[], priority = 0): void {
  const api = highlightApi();
  if (!api) return;
  if (ranges.length === 0) {
    api.registry.delete(name);
    return;
  }
  const highlight = new api.Highlight(...ranges);
  highlight.priority = priority;
  api.registry.set(name, highlight);
}

export function clearHighlights(...names: string[]): void {
  const api = highlightApi();
  if (!api) return;
  for (const name of names) api.registry.delete(name);
}

let searchHitTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * B3：高亮目标消息内的全部命中，SEARCH_HIT_HIGHLIGHT_MS 后清除；返回第一处命中。
 * 后端全文检索按词命中（多个词可以不相邻）：整句没有字面命中时退回逐词高亮。
 */
export function highlightSearchHits(messageEl: Element, query: string): Range | null {
  let ranges = findTextRanges(messageEl, query);
  const terms = Array.from(new Set(query.trim().split(/\s+/).filter(Boolean)));
  if (ranges.length === 0 && terms.length > 1) {
    ranges = terms
      .flatMap((term) => findTextRanges(messageEl, term))
      .sort((a, b) => a.compareBoundaryPoints(Range.START_TO_START, b));
  }
  setHighlight(SEARCH_HIT_HIGHLIGHT, ranges);
  if (searchHitTimer) clearTimeout(searchHitTimer);
  searchHitTimer = setTimeout(() => {
    searchHitTimer = null;
    clearHighlights(SEARCH_HIT_HIGHLIGHT);
  }, SEARCH_HIT_HIGHLIGHT_MS);
  return ranges[0] ?? null;
}

/**
 * B4：浅色高亮已渲染区域（root）内的全部命中，醒目色突出目标消息内第 index
 * 处命中（越界时取最后一处）；返回当前命中。
 */
export function highlightFindMatches(
  root: Element,
  messageEl: Element,
  query: string,
  index: number,
): Range | null {
  setHighlight(FIND_HIGHLIGHT, findTextRanges(root, query));
  const inMessage = findTextRanges(messageEl, query);
  const current =
    inMessage.length > 0 ? inMessage[Math.min(Math.max(index, 0), inMessage.length - 1)] : null;
  setHighlight(FIND_CURRENT_HIGHLIGHT, current ? [current] : [], 1);
  return current;
}

export function clearFindHighlights(): void {
  clearHighlights(FIND_HIGHLIGHT, FIND_CURRENT_HIGHLIGHT);
}

/**
 * 把 Range 滚动到滚动容器的中部。环境不提供 Range 几何信息（jsdom）、命中不可见
 * （折叠区域内）或没有滚动容器时返回 false，由调用方回退到元素级 scrollIntoView。
 */
export function scrollRangeIntoView(range: Range, scroller: HTMLElement | null): boolean {
  if (!scroller || typeof range.getBoundingClientRect !== 'function') return false;
  const rect = range.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return false;
  const box = scroller.getBoundingClientRect();
  scroller.scrollTop += rect.top - box.top - (box.height - rect.height) / 2;
  return true;
}
